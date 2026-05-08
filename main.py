import json
import os
from typing import List, Optional, Dict
import asyncio
import aiofiles
import numpy as np
import faiss
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import AsyncOpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta
from pathlib import Path
import math
import re
from zoneinfo import ZoneInfo
from crawling import scraper as event_scraper
from crawling.event_normalizer import event_signature, normalize_events

# fastapi 웹 서버
# Jinja2Templates, StaticFiles: HTML, 정적 파일(css, js) 처리
# aiofiles: 비동기 파일 입출력
# numpy / faiss: 벡터 검색용 (이벤트 임베딩 처리).
# openai.AsyncOpenAI: OpenAI API 비동기 호출
# dotenv: .env 파일에서 환경 변수 읽기.
# datetime : 날짜 계산
# path : 경로 처리

# =========================
# App / Templates / Static
# =========================
app = FastAPI()
load_dotenv()  # .env 파일 로드

STATIC_DIR = "static"
TEMPLATES_DIR = "templates"

# 정적 파일 / 템플릿 등록
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# =========================
# Config
# =========================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EVENTS_JSON_PATH = Path("events.json")
EVENTS_EN_JSON_PATH = Path("events_en.json")
EMBEDDINGS_CACHE_PATH = Path("embeddings_cache.json")
translation_lock = asyncio.Lock()
APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Seoul"))
DAILY_REFRESH_HOUR = int(os.getenv("DAILY_REFRESH_HOUR", "12"))
DAILY_REFRESH_MINUTE = int(os.getenv("DAILY_REFRESH_MINUTE", "0"))

# OPENAI_API_KEY가 없으면 None으로 설정
openai_client: Optional[AsyncOpenAI] = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# =========================
# In-memory cache
# =========================
events_data: List[dict] = [] #한국어 이벤트 데이터
events_data_en: List[dict] = [] #영어 이벤트 데이터
event_embeddings: Optional[np.ndarray] = None #모든 이벤트 임베딩 행렬
faiss_index: Optional[faiss.Index] = None #FAISS 검색 인덱스
refresh_lock = asyncio.Lock()

# 세션별 대화 히스토리 저장용 메모리
conversation_memory: Dict[str, List[Dict[str, str]]] = {} 
MAX_MEMORY = 10 #세션당 최대 대화 기록 수

def calculate_distance(lat1, lon1, lat2, lon2):
    """두 좌표 간의 직선 거리 계산 (단위: km)"""
    if None in [lat1, lon1, lat2, lon2]:
        return 9999.0  # 좌표가 없으면 아주 먼 거리로 설정
    
    radius = 6371  # 지구 반지름
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + \
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
        math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c

async def translate_event_with_openai(event: dict) -> dict:
    """행사 정보를 OpenAI를 사용해 영어로 번역"""
    if not openai_client:
        return {}

    # 번역할 필드
    title = event.get("title") or ""
    place = event.get("place") or ""
    host = event.get("host") or ""
    period = event.get("period") or ""  # 번역 대상에 포함
    category = event.get("category") or ""
    cost = event.get("cost") or ""
    # state는 번역 X

    if not title and not place and not host and not period and not category and not cost:
        return {"id": event.get("id")}

    system_prompt = """
You are a helpful translation assistant.
Translate the following JSON values from Korean to English.
- Keep the JSON structure.
- Provide only the translated JSON object, without any additional text or explanations.
- If a field is empty or missing, keep it as an empty string.
"""
    user_content = json.dumps({
        "title": title,
        "place": place,
        "host": host,
        "period": period,
        "category": category,
        "cost": cost
    }, ensure_ascii=False)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]

    try:
        resp = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        translated_content = json.loads(resp.choices[0].message.content)
        return {
            "id": event.get("id"),
            "title_en": translated_content.get("title", ""),
            "place_en": translated_content.get("place", ""),
            "host_en": translated_content.get("host", ""),
            "period_en": translated_content.get("period", ""),
            "category_en": translated_content.get("category", ""),
            "cost_en": translated_content.get("cost", "")
        }
    except Exception as e:
        print(f"Error translating event ID {event.get('id')}: {e}")
        return {
            "id": event.get("id"),
            "title_en": "",
            "place_en": "",
            "host_en": "",
            "period_en": "",
            "category_en": "",
            "cost_en": ""
        }

def merge_translated_events(base_events: List[dict], translated_events: List[dict]) -> List[dict]:
    translated_by_id = {
        event.get("id"): event
        for event in translated_events
        if isinstance(event, dict) and event.get("id") is not None
    }
    return [
        {**event, **translated_by_id.get(event.get("id"), {})}
        for event in base_events
    ]


async def translate_events_to_english(force: bool = False) -> List[dict]:
    global events_data_en

    if not openai_client:
        return merge_translated_events(events_data, events_data_en)

    current_signature = event_signature(events_data)
    if (
        not force
        and events_data_en
        and len(events_data_en) == len(events_data)
        and getattr(app.state, "events_en_signature", None) == current_signature
    ):
        return events_data_en

    async with translation_lock:
        if (
            not force
            and events_data_en
            and len(events_data_en) == len(events_data)
            and getattr(app.state, "events_en_signature", None) == current_signature
        ):
            return events_data_en

        print("[translate] Starting event translation...")
        translated_events = []

        batch_size = 10
        for i in range(0, len(events_data), batch_size):
            batch = events_data[i:i+batch_size]
            tasks = [translate_event_with_openai(event) for event in batch]
            results = await asyncio.gather(*tasks)

            translated_events.extend([r for r in results if r and r.get("id") is not None])

            print(f"[translate] Batch {i//batch_size + 1} ({len(translated_events)}/{len(events_data)})")
            await asyncio.sleep(1.0)

        cache_payload = {
            "event_signature": current_signature,
            "events": translated_events,
        }
        async with aiofiles.open(EVENTS_EN_JSON_PATH, mode="w", encoding="utf-8") as f:
            await f.write(json.dumps(cache_payload, indent=2, ensure_ascii=False))

        events_data_en = merge_translated_events(events_data, translated_events)
        app.state.events_en_signature = current_signature
        print(f"[translate] Successfully translated and saved {len(translated_events)} events.")
        return events_data_en


@app.post("/api/translate_events")
async def api_translate_events():
    if not openai_client:
        return JSONResponse(status_code=400, content={"message": "OpenAI API key is not configured."})

    translated = await translate_events_to_english(force=True)
    return {"message": f"Successfully translated {len(translated)} events.", "path": str(EVENTS_EN_JSON_PATH)}


def today_kst():
    return datetime.now(APP_TIMEZONE).date()


def parse_period_dates(period: str):
    if not period:
        return None, None

    text = str(period)
    matches = re.findall(r"\d{4}-\d{1,2}-\d{1,2}|\d{8}", text)
    dates = []
    for value in matches[:2]:
        try:
            if "-" in value:
                dates.append(datetime.strptime(value, "%Y-%m-%d").date())
            else:
                dates.append(datetime.strptime(value, "%Y%m%d").date())
        except ValueError:
            continue

    if not dates:
        return None, None
    if len(dates) == 1:
        return dates[0], dates[0]
    return dates[0], dates[1]


def compute_event_state(period: str) -> str: #이벤트 상태 계산
    #이벤트 기간이랑 오늘 날짜 비교해서 이벤트가 예정, 진행중, 종료으로 반환
    #근데 기간 정보가 없거나 형식 이상하면 알수없음 반환
    start_date, end_date = parse_period_dates(period)
    if not start_date or not end_date:
        return "알수없음"

    today = today_kst()
    if today < start_date:
        return "예정"
    if start_date <= today <= end_date:
        return "진행중"
    return "종료"


def is_current_year_event(period: str) -> bool:
    start_date, end_date = parse_period_dates(period)
    if not start_date or not end_date:
        return False

    current_year = today_kst().year
    year_start = datetime(current_year, 1, 1).date()
    year_end = datetime(current_year, 12, 31).date()
    return start_date <= year_end and end_date >= year_start


def is_recommendable_event(event: dict) -> bool:
    state = str(event.get("state") or "").strip()
    if state in {"종료", "마감", "끝남", "ended", "closed", "finished"}:
        return False

    period = event.get("period") or ""
    if not is_current_year_event(period):
        return False

    start_date, end_date = parse_period_dates(period)
    if end_date and end_date < today_kst():
        return False
    return True


def create_event_text(event: dict) -> str:
    #event.json에서 이벤트 정보를 임베딩용 텍스트로 변환
    title = event.get("title", "")
    place = event.get("place", "")
    host = event.get("host", "")
    period = event.get("period", "")
    state = event.get("state", "")
    description = event.get("description", "")
    source = event.get("source", "")
    category = event.get("category", "")

    text_parts = [
        f"제목: {title}",
        f"장소: {place}",
        f"주최: {host}",
        f"출처: {source}",
        f"분류: {category}",
        f"기간: {period}",
        f"상태: {state}",
    ]

    if description: #이벤트에 설명 있으면 설명 추가
        text_parts.append(f"설명: {description}")

    return " | ".join(text_parts)


async def get_embedding(text: str, model: str = "text-embedding-3-small") -> List[float]:
    #text-embedding-3-small 를 사용하여 텍스트 임베딩 생성
    try:
        response = await openai_client.embeddings.create(
            input=text,
            model=model
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"[get_embedding] Error: {e}")
        return [0.0] * 1536  # 기본 차원


async def build_vector_database():
    #이벤트 데이터의 벡터 데이터베이스 구축
    #요약
    #json에 캐쉬 있는지 확인 -> 있으면 로드 -> FAISS 인덱스 생성
    #없으면 이벤트 데이터 임베딩 생성 -> FAISS 인덱스 생성 -> 캐쉬 저장
    
    global event_embeddings, faiss_index

    if not openai_client or not events_data:
        print("[build_vector_database] No OpenAI client or events data")
        event_embeddings = None
        faiss_index = None
        return

    # 캐시 확인
    current_signature = event_signature(events_data)
    if EMBEDDINGS_CACHE_PATH.exists(): #캐쉬파일 존재하면
        try:
            async with aiofiles.open(str(EMBEDDINGS_CACHE_PATH), "r", encoding="utf-8") as f: #비동기로 파일 연다
                cache_data = json.loads(await f.read())
                embeddings_list = cache_data.get("embeddings", [])
                cache_signature = cache_data.get("event_signature")
                if len(embeddings_list) == len(events_data) and cache_signature == current_signature:
                    event_embeddings = np.array(embeddings_list, dtype=np.float32) #numpy 배열로 변환
                    print(f"[build_vector_database] Loaded {len(embeddings_list)} embeddings from cache")

                    # FAISS 인덱스 생성
                    dimension = event_embeddings.shape[1]
                    faiss_index = faiss.IndexFlatL2(dimension)
                    faiss_index.add(event_embeddings)
                    return
        except Exception as e:
            print(f"[build_vector_database] Cache load error: {e}")

    # 캐시가 없으면 새로 생성
    print(f"[build_vector_database] Creating embeddings for {len(events_data)} events...")


    embeddings_list = []  # 모든 이벤트 임베딩 저장용
    # 배치 처리로 임베딩 생성 (API 호출 최적화)
    # 이벤트 개많아서 50개씩 나눠서 처리함
    batch_size = 50
    for i in range(0, len(events_data), batch_size):
        batch = events_data[i:i + batch_size] #이벤트 배치
         #배치의 각 이벤트에 대해 임베딩용 텍스트 생성
        texts = [create_event_text(event) for event in batch] #임베딩용 텍스트 리스트

        # 배치로 임베딩 요청
        try:
            response = await openai_client.embeddings.create(
                input=texts,
                model="text-embedding-3-small"
            )
            batch_embeddings = [data.embedding for data in response.data] #배치 임베딩 리스트
            embeddings_list.extend(batch_embeddings) #전체 임베딩 리스트에 추가
            print(f"[build_vector_database] Processed {len(embeddings_list)}/{len(events_data)} events")
        except Exception as e:
            print(f"[build_vector_database] Batch error: {e}")
            # 에러 발생시 개별 처리
            for text in texts: #개별 텍스트에 대해 임베딩 생성
                embedding = await get_embedding(text) #임베딩 생성
                embeddings_list.append(embedding)

        # API 레이트 리밋 방지
        await asyncio.sleep(0.5)

    event_embeddings = np.array(embeddings_list, dtype=np.float32) #numpy 배열로 변환

    # FAISS 인덱스 생성
    dimension = event_embeddings.shape[1]
    faiss_index = faiss.IndexFlatL2(dimension) #L2 거리 기반 유사도 검색
    faiss_index.add(event_embeddings) #임베딩 추가
    #이러면 search_similar_events에서 FAISS를 통해 가장 유사한 이벤트를 개빠르게 찾을 수 있음

    # 캐시 저장
    try:
        cache_data = {"event_signature": current_signature, "embeddings": embeddings_list}
        async with aiofiles.open(str(EMBEDDINGS_CACHE_PATH), "w", encoding="utf-8") as f: #비동기로 파일 열기
            await f.write(json.dumps(cache_data)) #캐시 데이터 저장
        print("[build_vector_database] Embeddings cached successfully")
    except Exception as e:
        print(f"[build_vector_database] Cache save error: {e}")

    #json으로 캐쉬 저장해서 다음에 api 안쓰고 빠르게 로딩 가능함 재활용 느낌


async def search_similar_events(query: str, top_k: int = 20) -> List[dict]:
    #rag - 쿼리와 유사한 이벤트 검색
    #query : 사용자 질문
    #top_k : 반환할 유사 이벤트 개수
    #요약
    #쿼리 임베딩 생성 -> FAISS로 유사도 검색 -> 유사 이벤트 반환
    if not faiss_index or not openai_client:
        return events_data[:top_k]

    try:
        # 쿼리 임베딩 생성
        query_embedding = await get_embedding(query) #쿼리를 벡터로 변환
        query_vector = np.array([query_embedding], dtype=np.float32) #2차원 배열로 변환 왜냐하면 faiss가 2차원으로만 검색 가능

        # FAISS로 유사도 검색
        distances, indices = faiss_index.search(query_vector, min(top_k, len(events_data)))
        # indices: 유사한 이벤트의 인덱스 리스트
        # min(top_k, len(events_data)) : 이벤트 개수보다 top_k가 크면 오류나니까 방지

        # 결과 반환
        similar_events = []
        for idx in indices[0]:
            if 0 <= idx < len(events_data):
                event = events_data[idx].copy() #인덱스에 해당하는 이벤트 복사
                similar_events.append(event) #유사 이벤트 순서대로 리스트에 추가

        return similar_events
    except Exception as e:
        print(f"[search_similar_events] Error: {e}")
        return events_data[:top_k] #에러시 그냥 처음부터 top_k개 반환


def sanitize_chatbot_response(response_payload: dict, context_events: List[dict], lang: str) -> dict:
    if not isinstance(response_payload, dict):
        return response_payload

    allowed_by_title = {
        str(event.get("title") or "").strip(): event
        for event in context_events
        if event.get("title")
    }
    allowed_by_url = {
        str(event.get("url") or "").strip(): event
        for event in context_events
        if event.get("url") and event.get("url") != "#"
    }
    allowed_by_id = {
        str(event.get("id")): event
        for event in context_events
        if event.get("id") is not None
    }

    recommended = response_payload.get("recommended_event", [])
    if isinstance(recommended, dict):
        recommended = [recommended]
    elif not isinstance(recommended, list):
        recommended = []

    filtered_events = []
    for event in recommended:
        if not isinstance(event, dict):
            continue

        title = str(event.get("title") or "").strip()
        url = str(event.get("url") or "").strip()
        event_id = str(event.get("id")) if event.get("id") is not None else ""
        source_event = allowed_by_id.get(event_id) or allowed_by_title.get(title) or allowed_by_url.get(url)
        if source_event and is_recommendable_event(source_event):
            merged_event = {**event, **source_event}
            filtered_events.append(merged_event)

    response_payload["recommended_event"] = filtered_events
    if not filtered_events:
        response_payload["intent"] = response_payload.get("intent") or "event_search"
        if lang == "en":
            response_payload["reason"] = {
                "ko": "현재 조건에 맞는 진행 중이거나 예정된 행사를 찾지 못했습니다.",
                "en": "I couldn't find any ongoing or upcoming events that match your request."
            }
        else:
            response_payload["reason"] = {
                "ko": "현재 조건에 맞는 진행 중이거나 예정된 행사를 찾지 못했습니다.",
                "en": "I couldn't find any ongoing or upcoming events that match your request."
            }

    return response_payload


# =========================
# Event Refresh / Scheduler
# =========================
def _extract_event_list(data) -> List[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "events" in data:
        return data["events"]
    return []


def _extract_event_signature(data) -> Optional[str]:
    if isinstance(data, dict):
        signature = data.get("event_signature")
        return str(signature) if signature else None
    return None


async def load_events_from_disk():
    # 한국어, 영어 events 파일 모두 로드
    global events_data, events_data_en

    async with aiofiles.open(str(EVENTS_JSON_PATH), "r", encoding="utf-8") as f:
        raw_events = _extract_event_list(json.loads(await f.read()))

    normalized_events = normalize_events(raw_events, with_ids=True)
    for event in normalized_events:
        existing_state = str(event.get("state") or "").strip()
        computed_state = compute_event_state(event.get("period") or "")
        if existing_state in {"마감", "종료"}:
            event["state"] = existing_state
        elif computed_state != "알수없음":
            event["state"] = computed_state
        elif not event.get("state"):
            event["state"] = "알수없음"

    loaded_events_en = []
    loaded_events_en_signature = None
    if EVENTS_EN_JSON_PATH.exists():
        async with aiofiles.open(str(EVENTS_EN_JSON_PATH), "r", encoding="utf-8") as f_en:
            data_en = json.loads(await f_en.read())
            raw_events_en = _extract_event_list(data_en)
            loaded_events_en_signature = _extract_event_signature(data_en)
        loaded_events_en = merge_translated_events(normalized_events, raw_events_en)
        for event in loaded_events_en:
            event["state"] = event.get("state") or "Unknown"

    events_data = normalized_events
    events_data_en = loaded_events_en
    app.state.events_en_signature = loaded_events_en_signature
    print(f"[refresh] Loaded {len(events_data)} Korean events, {len(events_data_en)} English events.")


async def refresh_event_pipeline(reason: str, crawl_first: bool = True):
    async with refresh_lock:
        print(f"[refresh] Started ({reason})")
        try:
            if crawl_first:
                print("[refresh] Crawling events...")
                await asyncio.to_thread(event_scraper.main)
                print("[refresh] Crawling finished")

            await load_events_from_disk()
            await build_vector_database()
            print(f"[refresh] Finished ({reason})")
        except Exception as e:
            print(f"[refresh] Failed ({reason}): {e}")
            if not events_data and EVENTS_JSON_PATH.exists():
                try:
                    await load_events_from_disk()
                    await build_vector_database()
                    print("[refresh] Fallback loaded existing events.json")
                except Exception as fallback_error:
                    print(f"[refresh] Fallback failed: {fallback_error}")


def next_daily_refresh_time(now: datetime) -> datetime:
    target = now.replace(
        hour=DAILY_REFRESH_HOUR,
        minute=DAILY_REFRESH_MINUTE,
        second=0,
        microsecond=0,
    )
    if now >= target:
        target += timedelta(days=1)
    return target


async def daily_refresh_loop():
    while True:
        now = datetime.now(APP_TIMEZONE)
        target = next_daily_refresh_time(now)
        wait_seconds = max((target - now).total_seconds(), 1)
        print(f"[scheduler] Next refresh: {target.isoformat()}")
        try:
            await asyncio.sleep(wait_seconds)
            await refresh_event_pipeline("scheduled", crawl_first=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[scheduler] Refresh loop error: {e}")
            await asyncio.sleep(60)


@app.on_event("startup")
async def startup_event_refresh():
    await refresh_event_pipeline("startup", crawl_first=True)
    app.state.daily_refresh_task = asyncio.create_task(daily_refresh_loop())


@app.on_event("shutdown")
async def shutdown_event_refresh():
    task = getattr(app.state, "daily_refresh_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# =========================
# Page routes
# =========================
@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/chat")


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse(request, "chat.html")


@app.get("/feed", response_class=HTMLResponse)
async def feed_page(request: Request):
    return templates.TemplateResponse(request, "feed.html")


# =========================
# Chatbot Logic with RAG
# =========================
LOCATION_COORDS = {
    "강남": {"lat": 37.4979, "lng": 127.0276},
    "서울": {"lat": 37.5665, "lng": 126.9780},
    "과천": {"lat": 37.4294, "lng": 126.9899},
    "청주": {"lat": 36.6424, "lng": 127.4890},
    "제주": {"lat": 33.4890, "lng": 126.4983},
    "성남": {"lat": 37.4200, "lng": 127.1267},
    "판교": {"lat": 37.3947, "lng": 127.1111}
}

async def chatbot(message: str, chat_history: list = None, session_id: str = None, user_location: dict = None) -> dict:
    # 1. 초기 설정 및 히스토리 방어 코드
    if chat_history is None:
        chat_history = []
    
    # 세션 기반 메모리 (전역 변수 conversation_memory가 있다고 가정)
    # history 변수를 chat_history로 통일하거나 세션에서 가져와야 함
    current_history = chat_history if not session_id else conversation_memory.get(session_id, [])
        
    base_lat = user_location.get('lat') if user_location else None
    base_lng = user_location.get('lng') if user_location else None
    target_area = "현재 위치"

    # 질문 내 지역명 확인
    for area, coords in LOCATION_COORDS.items():
        if area in message:
            base_lat = coords['lat']
            base_lng = coords['lng']
            target_area = area
            break

    # 2. RAG 검색 및 3. 데이터 정제 (작성하신 로직 유지)
    similar_events = await search_similar_events(message, top_k=30)
    refined_events = []
    for e in similar_events:
        if not is_recommendable_event(e):
            continue
        dist = calculate_distance(base_lat, base_lng, e.get('lat'), e.get('lng')) if base_lat and e.get('lat') else None
        refined_events.append({
            "id": e.get("id"),
            "title": e.get("title", "제목 없음"),
            "period": e.get("period") or "상설 전시 (일정 확인 필요)",
            "place": e.get("place") or "상세 장소 확인 필요",
            "host": e.get("host") or "기관 정보 없음",
            "source": e.get("source") or "출처 확인 필요",
            "category": e.get("category") or "분류 확인 필요",
            "state": e.get("state") or "진행 중",
            "distance_km": dist,
            "url": e.get("url") or "#",
            "description": (e.get("description") or "")[:600]
        })

    # 4. 거리순 정렬
    if base_lat:
        refined_events.sort(key=lambda x: (x['distance_km'] is None, x['distance_km']))

    # 5. LLM에 전달할 컨텍스트 생성
    # 상위 10개만 전달
    context_events = refined_events[:10]
    user_lang = "ko" if re.search(r"[가-힣]", message) else "en"
    
    system_prompt = f"""
    You are an AI chatbot that recommends cultural events, exhibitions, and festivals in South Korea.
Your response MUST be in JSON format.
The 'recommended_event' field must always be an array. Do NOT change the field structure.

### Priority & Location Rules
1. Location Extraction: Identify if the user mentioned a specific location (e.g., "Gangnam", "Pangyo", "Seoul").
2. Priority: If a location is specified, prioritize events with the shortest 'distance_km' from that location.
3. Distance Context: In the 'reason' field, if an event is very close to the requested location, mention its proximity.

### Conversation Rules
- MUST follow JSON format strictly
- NEVER change field names or structure
- NEVER break JSON structure
- Detect user's language (Korean or English) and respond accordingly
- Remove irrelevant content
- Include date, place, and host information
- Remember last 4 conversations and reflect context
- Today's date: {today_kst().isoformat()}
- If any field is missing, set it to "Unknown" (Korean: "알수없음")
- Recommend ONLY events included in Retrieved events. Never invent events, venues, dates, or URLs.
- Never recommend events whose state is "종료" or "마감", or whose end date is before today's date.
- Recommend ONLY events whose period overlaps the current year ({today_kst().year}). Do not recommend events from other years or events with unknown dates.
- Do not reuse sample, previous conversation, or user-provided event names as recommendations unless the same event exists in Retrieved events.
- If Retrieved events is empty, return an empty recommended_event array and explain that no ongoing/upcoming matching event was found.
- When recommending an event, preserve its id and url from Retrieved events.

### CRITICAL: Language Translation Rules
- If user writes in KOREAN → respond in Korean (all fields in Korean)
- If user writes in ENGLISH → respond in English AND translate all event fields:
  * title → translate to English
  * place → translate to English
  * host → translate to English
  * state → translate to English ("예정"→"Scheduled", "진행중"→"Ongoing", "종료"→"Ended")
  * reason → provide in both languages

### Response Context
The provided 'Retrieved events' are already filtered to ongoing or upcoming events and sorted by distance from the user's requested location or current location. Use this order to provide the most relevant recommendations.

Return shape:
{{
  "response": {{
    "intent": "event_search",
    "recommended_event": [],
    "reason": {{"ko": "...", "en": "..."}}
  }}
}}

Today's date: {today_kst().isoformat()}
Retrieved events (via semantic search): {json.dumps(context_events, ensure_ascii=False)}
    """

    # 5. 메시지 구성 (System + 히스토리 + 현재 질문)
    messages = [{"role": "system", "content": system_prompt}]
    # 6. OpenAI API 호출
    for h in current_history[-4:]:
        role = "assistant" if h.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": str(h.get("content", ""))})
    
    messages.append({"role": "user", "content": str(message)})

    # 6. API 호출 및 처리
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.5,
            response_format={"type": "json_object"}
        )
        reply = response.choices[0].message.content.strip()

        # [수정포인트] 메모리 업데이트 시 변수명 불일치 해결
        if session_id:
            current_history.append({"role": "user", "content": message})
            current_history.append({"role": "assistant", "content": reply})
            conversation_memory[session_id] = current_history[-16:]

        # 7. 응답 파싱
        try:
            json_reply = json.loads(reply)
            response_payload = json_reply.get("response", json_reply)
            response_payload = sanitize_chatbot_response(response_payload, context_events, user_lang)
            return {"response": response_payload}
        except Exception:
            return {"response": {"intent": "other", "reason": {"ko": reply}}}

    except Exception as e:
        print(f"[chatbot] Error: {e}")
        return {"response": {"intent": "error", "reason": {"ko": "오류 발생"}}}
# =========================
# API routes
# =========================
@app.post("/api/chat")
async def api_chat(request: Request):
    data = await request.json()
    raw_message = (data.get("message") or "").strip() #사용자 메시지
    chat_history = data.get("chat_history", []) #대화 히스토리
    user_location = data.get("location")
    return await chatbot(raw_message, chat_history, user_location=user_location)


@app.get("/events")
async def api_events():
    return {"events": events_data}


@app.get("/events_en")
async def api_events_en():
    """영어 이벤트 반환"""
    translated = await translate_events_to_english(force=False)
    has_translation = any(event.get("title_en") for event in translated)
    return {"events": translated if translated else events_data, "translated": has_translation}


# =========================
# Health Check
# =========================
@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}
