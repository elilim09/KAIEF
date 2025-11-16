import json
import os
from typing import List, Optional, Dict
import asyncio
import aiofiles
import numpy as np
import faiss
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import AsyncOpenAI
from dotenv import load_dotenv
from datetime import datetime
from pathlib import Path

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

# OPENAI_API_KEY가 없으면 None으로 설정
openai_client: Optional[AsyncOpenAI] = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# =========================
# In-memory cache
# =========================
events_data: List[dict] = [] #한국어 이벤트 데이터
events_data_en: List[dict] = [] #영어 이벤트 데이터
event_embeddings: Optional[np.ndarray] = None #모든 이벤트 임베딩 행렬
faiss_index: Optional[faiss.Index] = None #FAISS 검색 인덱스

# 세션별 대화 히스토리 저장용 메모리
conversation_memory: Dict[str, List[Dict[str, str]]] = {} 
MAX_MEMORY = 10 #세션당 최대 대화 기록 수


def compute_event_state(period: str) -> str: #이벤트 상태 계산
    #이벤트 기간이랑 오늘 날짜 비교해서 이벤트가 예정, 진행중, 종료으로 반환
    #근데 기간 정보가 없거나 형식 이상하면 알수없음 반환
    if not period or "~" not in period:
        return "알수없음"
    try:
        start_str, end_str = period.split("~")
        start_date = datetime.strptime(start_str.strip(), "%Y-%m-%d").date()
        end_date = datetime.strptime(end_str.strip(), "%Y-%m-%d").date()
        today = datetime.now().date()
        if today < start_date:
            return "예정"
        elif start_date <= today <= end_date:
            return "진행중"
        else:
            return "종료"
    except Exception:
        return "알수없음"


def create_event_text(event: dict) -> str:
    #event.json에서 이벤트 정보를 임베딩용 텍스트로 변환
    title = event.get("title", "")
    place = event.get("place", "")
    host = event.get("host", "")
    period = event.get("period", "")
    state = event.get("state", "")
    description = event.get("description", "")

    text_parts = [
        f"제목: {title}",
        f"장소: {place}",
        f"주최: {host}",
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
        return

    # 캐시 확인
    if EMBEDDINGS_CACHE_PATH.exists(): #캐쉬파일 존재하면
        try:
            async with aiofiles.open(str(EMBEDDINGS_CACHE_PATH), "r", encoding="utf-8") as f: #비동기로 파일 연다
                cache_data = json.loads(await f.read())
                embeddings_list = cache_data.get("embeddings", [])
                if len(embeddings_list) == len(events_data): #임베딩 수가 이벤트 수와 같으면
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
        cache_data = {"embeddings": embeddings_list}
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


# =========================
# Lifespan
# =========================
@app.on_event("startup")
async def load_events_data():
    # 한국어, 영어 events 파일 모두 로드 및 벡터 DB 구축
    global events_data, events_data_en
    try:
        # --- 한국어 파일 ---
        async with aiofiles.open(str(EVENTS_JSON_PATH), "r", encoding="utf-8") as f:
            data = json.loads(await f.read())
            if isinstance(data, list):
                raw_events = data
            elif isinstance(data, dict) and "events" in data:
                raw_events = data["events"]
            else:
                raw_events = []
        events_data = [{**event, "id": i} for i, event in enumerate(raw_events)]
        for e in events_data:
            e["state"] = compute_event_state(e.get("period") or "") #이벤트 상태 계산

        # --- 영어 파일 (있을 경우) ---
        if EVENTS_EN_JSON_PATH.exists():
            async with aiofiles.open(str(EVENTS_EN_JSON_PATH), "r", encoding="utf-8") as f_en:
                data_en = json.loads(await f_en.read())
                if isinstance(data_en, list):
                    raw_events_en = data_en
                elif isinstance(data_en, dict) and "events" in data_en:
                    raw_events_en = data_en["events"]
                else:
                    raw_events_en = []
            events_data_en = [{**event, "id": i} for i, event in enumerate(raw_events_en)]
            for e in events_data_en:
                e["state"] = e.get("state") or "Unknown"
        else:
            events_data_en = []

        print(f"[startup] Loaded {len(events_data)} Korean events, {len(events_data_en)} English events.")

        # 벡터 데이터베이스 구축
        await build_vector_database()

    except Exception as e:
        print(f"[startup] Error loading events: {e}")
        events_data = []
        events_data_en = []


# =========================
# Page routes
# =========================
@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/chat")


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})


@app.get("/feed", response_class=HTMLResponse)
async def feed_page(request: Request):
    return templates.TemplateResponse("feed.html", {"request": request})


# =========================
# Chatbot Logic with RAG
# =========================
async def chatbot(message: str, chat_history: list = None, session_id: str = None) -> dict:
    #RAG 기반 챗봇: 벡터 유사도 검색으로 관련 이벤트를 찾아 답변 생성
    if not message:
        return {"response": "메시지를 입력해주세요."}

    if not openai_client:
        return {"response": "OpenAI API 키가 설정되어 있지 않습니다."}

    # 세션별 대화 기록 관리
    if session_id:
        if session_id not in conversation_memory:
            conversation_memory[session_id] = []
        history = conversation_memory[session_id]
    else:
        history = chat_history or []

    #RAG: 벡터 유사도 검색으로 관련 이벤트 찾기
    similar_events = await search_similar_events(message, top_k=20)

    # compact_events 구성
    compact_events = [
        {
            "id": e.get("id"),
            "title": e.get("title"),
            "period": e.get("period"),
            "place": e.get("place"),
            "host": e.get("host"),
            "state": e.get("state"),
            "url": e.get("url") or e.get("link") or "#",
        }
        for e in similar_events
    ]

    system_prompt = f"""
You are an AI chatbot that recommends cultural events, exhibitions, and festivals in South Korea.
Your response MUST be in JSON format.
The 'recommended_event' field must always be an array. Do NOT change the field structure.

### Conversation Rules
# - MUST follow JSON format strictly
# - NEVER change field names or structure
# - NEVER break JSON structure
# - Detect user's language (Korean or English) and respond accordingly
# - Remove irrelevant content
# - Include date, place, and host information
# - Remember last 4 conversations and reflect context
# - Today's date: {datetime.now().strftime('%Y-%m-%d')}
# - If any field is missing, set it to "Unknown" (Korean: "알수없음")

### CRITICAL: Language Translation Rules
- If user writes in KOREAN → respond in Korean (all fields in Korean)
- If user writes in ENGLISH → respond in English AND translate all event fields:
  * title → translate to English
  * place → translate to English
  * host → translate to English
  * state → translate to English ("예정"→"Scheduled", "진행중"→"Ongoing", "종료"→"Ended")
  * reason → provide in both languages

Example 1 (Korean Input):
User: 이번 주말에 갈 전시 추천해줘
Assistant:
{{
  "response": {{
    "intent": "event_search",
    "recommended_event": [
        {{
            "id": 101,
            "title": "서울 현대미술 전시",
            "place": "서울 시립미술관",
            "host": "서울시",
            "period": "2025-11-15~2025-11-20",
            "state": "예정",
            "url": "http://example.com/seoul-art-exhibit"
        }}
    ],
    "reason": {{
        "ko": "이번 주말에 서울에서 진행되는 현대미술 전시입니다.",
        "en": "A contemporary art exhibition in Seoul this weekend."
    }}
  }}
}}

Example 2 (English Input):
User: What exhibitions are available this weekend?
Assistant:
{{
  "response": {{
    "intent": "event_search",
    "recommended_event": [
        {{
            "id": 101,
            "title": "Seoul Contemporary Art Exhibition",
            "place": "Seoul Museum of Art",
            "host": "Seoul Metropolitan Government",
            "period": "2025-11-15~2025-11-20",
            "state": "Scheduled",
            "url": "http://example.com/seoul-art-exhibit"
        }}
    ],
    "reason": {{
        "ko": "이번 주말에 서울에서 진행되는 현대미술 전시입니다.",
        "en": "A contemporary art exhibition in Seoul this weekend."
    }}
  }}
}}

### Now respond to the user's question with the same JSON structure as shown in the examples above.
Today's date: {datetime.now().strftime('%Y-%m-%d')}
Retrieved events (via semantic search): {json.dumps(compact_events, ensure_ascii=False)}
"""

    # messages 구성: system + 최근 4개 대화 + 사용자 입력
    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-4:]:
        messages.append({"role": "assistant" if h["role"] == "assistant" else "user", "content": str(h["content"])})
    messages.append({"role": "user", "content": str(message)})

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.5, #창의성 조절
        )
        reply = response.choices[0].message.content.strip()

        # 히스토리 업데이트
        if session_id:
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": reply})
            if len(history) > 16:
                conversation_memory[session_id] = history[-16:]

        # JSON 파싱
        try:
            json_reply = json.loads(reply)
            return {"response": json_reply["response"]}
        except Exception:
            return {"response": {
                "intent": "other",
                "recommended_event": [],
                "reason": {"ko": reply, "en": reply}
            }}

    except Exception as e:
        print(f"[chatbot] Error: {e}")
        return {"response": {
            "intent": "other",
            "recommended_event": [],
            "reason": {"ko": "죄송합니다. 잠시 후 다시 시도해주세요.", "en": "Sorry, please try again later."}
        }}


# =========================
# API routes
# =========================
@app.post("/api/chat")
async def api_chat(request: Request):
    data = await request.json()
    raw_message = (data.get("message") or "").strip() #사용자 메시지
    chat_history = data.get("chat_history", []) #대화 히스토리
    return await chatbot(raw_message, chat_history)


@app.get("/events")
async def api_events():
    return {"events": events_data}


@app.get("/events_en")
async def api_events_en():
    """영어 이벤트 반환"""
    return {"events": events_data_en if events_data_en else events_data}


# =========================
# Health Check
# =========================
@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}
