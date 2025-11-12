# main.py
import json
import os
from typing import List, Tuple, Optional
import asyncio
import aiofiles
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import AsyncOpenAI
from dotenv import load_dotenv
from datetime import datetime

# =========================
# App / Templates / Static
# =========================
app = FastAPI()
load_dotenv()

# 정적 파일 및 템플릿 경로
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# =========================
# Config (ENV 권장)
# =========================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # 환경변수로 주입 권장
EVENTS_JSON_PATH = os.getenv(
    "EVENTS_JSON_PATH",
    os.path.join(BASE_DIR, "events.json")  # 기본: 서버 기준 ./events.json
)
EVENTS_EN_JSON_PATH = os.getenv(
    "EVENTS_EN_JSON_PATH",
    os.path.join(BASE_DIR, "events_en.json")
)

openai_client: Optional[AsyncOpenAI] = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# =========================
# In-memory cache
# =========================
events_data: List[dict] = []


def compute_event_state(period: str) -> str:
    """
    period: "YYYY-MM-DD~YYYY-MM-DD" 형식
    현재 날짜 기준으로 진행중 / 종료 결정
    """
    if not period or "~" not in period:
        return "진행중"  # 기간 정보 없으면 기본 진행중

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
            return "마감"
    except Exception:
        return "진행중"  # 파싱 오류 시 기본 진행중

async def translate_event_with_openai(event: dict) -> dict:
    """행사 정보를 OpenAI를 사용해 영어로 번역"""
    if not openai_client:
        return {}

    # 번역할 필드
    title = event.get("title") or ""
    place = event.get("place") or ""
    host = event.get("host") or ""
    period = event.get("period") or ""  # 번역 대상에 포함
    # state는 번역 X

    if not title and not place and not host and not period:
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
        "period": period
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
            "period_en": translated_content.get("period", "")
        }
    except Exception as e:
        print(f"Error translating event ID {event.get('id')}: {e}")
        return {
            "id": event.get("id"),
            "title_en": "",
            "place_en": "",
            "host_en": "",
            "period_en": ""
        }

def build_reason(event: Optional[dict], keywords: List[str]) -> dict:
    """추천 사유 텍스트(ko/en) 구성"""
    if not event:
        return {
            "ko": "요청과 일치하는 행사를 찾지 못했습니다. 다른 조건으로 다시 시도해보세요.",
            "en": "No matching events were found. Try adjusting the filters and ask again."
        }

    # ko
    title_ko = event.get("title") or "행사"
    location = event.get("place") or event.get("location") or ""
    period = event.get("period") or event.get("date") or event.get("datetime") or ""
    host = event.get("host") or event.get("organization") or ""

    # en (번역 필드 우선 사용)
    title_en = event.get("title_en") or title_ko

    top_keywords = [k for k in (keywords or []) if k][:3]
    keyword_str = ", ".join(top_keywords)

    reason_ko = []
    reason_en = []

    if keyword_str:
        reason_ko.append(f"'{keyword_str}' 키워드와 가장 잘 맞는 '{title_ko}' 행사를 추천했어요.")
        reason_en.append(f"We matched the keywords '{keyword_str}' with the event '{title_en}'.")
    else:
        reason_ko.append(f"'{title_ko}' 행사를 추천했어요.")
        reason_en.append(f"We recommend the event '{title_en}'.")

    if period:
        reason_ko.append(f"일정은 {period}입니다.")
        reason_en.append(f"It runs on {period}.")

    if location:
        reason_ko.append(f"장소는 {location}이에요.")
        reason_en.append(f"The venue is {location}.")

    if host:
        reason_ko.append(f"주관 기관은 {host}입니다.")
        reason_en.append(f"Hosted by {host}.")

    reason_ko.append("자세한 사항은 행사 링크에서 확인해보세요.")
    reason_en.append("Check the event link for more details.")

    return {"ko": " ".join(reason_ko), "en": " ".join(reason_en)}


async def extract_keywords_with_openai(raw_message: str) -> List[str]:
    """
    OpenAI를 사용해 정규화 키워드 추출.
    OPENAI_API_KEY 미설정 시, 간단 폴백(띄어쓰기 기반 상위 몇 개 단어) 사용.
    """
    # 폴백: 키워드 간단 분리
    if not openai_client:
        words = [w.strip() for w in raw_message.split() if len(w.strip()) >= 2]
        # 너무 일반적인 단어 제거(간단 룰)
        stop = {"행사", "추천", "알려줘", "찾아줘", "있을까", "좀", "요", "은", "는", "이", "가"}
        keywords = [w for w in words if w not in stop][:6]
        return keywords or ([raw_message] if raw_message else [])

    system_prompt = """
당신은 행사 추천 시스템을 위한 '키워드 정규화 추출기'입니다.
반드시 JSON 객체만 반환합니다.

[목표]
- 사용자의 자유로운 한국어 입력에서 검색/필터에 유용한 핵심 키워드를 3~7개 추출합니다.
- 동의어/상위어/연령대/대상/활동유형/공간유형/비용 등으로 '정규화'된 키워드를 포함합니다.
- '가족'이 포함되면 '초등학생','놀이','사회성','어린이' 같은 연관 키워드를 적극 확장합니다.

[출력 형식 - 반드시 준수]
{
  "keywords": ["정규화된, 소문자, 공백 제거 최소화, 한글 유지"],
  "categories": ["(선택) 카테고리 라벨"],
  "inferred": ["(선택) 암시된 조건/의도"],
  "excluded": ["(선택) 제외해야 할 것(부정 표현)"]
}

[정규화/확장 규칙 요약]
- 날짜: 오늘/주말/이번주/이번달 등 의미 보존
- 비용: 무료/유료
- 공간: 실내/야외/온라인
- 대상: 어린이/초등학생/청소년/성인/어르신 등
- 활동: 체험/공연/전시/강연/교육/대회 등
- 지역/고유명사: 원형 유지
- 부정: "~말고, 제외, 빼고, 싫어" → excluded
- 3~7개, 중복/불용어 제거
"""

    fewshot = [
        {
            "role": "user",
            "content": "주말에 가족이랑 아이가 즐길 수 있는 무료 야외 체험 있어?"
        },
        {
            "role": "assistant",
            "content": """
{
  "keywords": ["주말","가족","어린이","초등학생","야외","체험","무료"],
  "categories": ["교육","체험"],
  "inferred": ["가족 동반","놀이","사회성"],
  "excluded": []
}
""".strip()
        },
        {
            "role": "user",
            "content": "고등학생 대상 ai 경진대회 같은 거 있을까? 분당 근처면 좋고, 온라인 말고 오프라인 원해."
        },
        {
            "role": "assistant",
            "content": """
{
  "keywords": ["고등학생","청소년","ai","대회","경진대회","분당","오프라인"],
  "categories": ["대회","교육"],
  "inferred": ["진학/스펙","코딩"],
  "excluded": ["온라인"]
}
""".strip()
        },
        {
            "role": "user",
            "content": "실내 전시 찾아줘. 어린이용 말고 성인 위주로, 미술 쪽이면 좋겠어."
        },
        {
            "role": "assistant",
            "content": """
{
  "keywords": ["실내","전시","미술","성인"],
  "categories": ["전시","문화"],
  "inferred": [],
  "excluded": ["어린이","초등학생","가족"]
}
""".strip()
        },
        {
            "role": "user",
            "content": "무료 강연 좋은데 야외는 말고 실내 위주로. 어린이 프로그램은 빼줘."
        },
        {
            "role": "assistant",
            "content": """
{
  "keywords": ["무료","강연","실내"],
  "categories": ["강연","교육"],
  "inferred": [],
  "excluded": ["야외","어린이","초등학생","가족"]
}
""".strip()
        },
    ]

    messages = [{"role": "system", "content": system_prompt}] + fewshot + [
        {"role": "user", "content": raw_message}
    ]

    resp = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.2,
        top_p=0.9,
    )

    try:
        parsed = json.loads(resp.choices[0].message.content)
    except Exception:
        # 안전 폴백
        words = [w.strip() for w in raw_message.split() if len(w.strip()) >= 2]
        return words[:6] or ([raw_message] if raw_message else [])

    candidates = parsed.get("keywords") or parsed.get("categories") or []
    if isinstance(candidates, str):
        candidates = [candidates]
    keywords = [k for k in candidates if isinstance(k, str) and k.strip()]
    return keywords or ([raw_message] if raw_message else [])


def score_event(event: dict, keywords: List[str]) -> int:
    """간단한 키워드 점수 계산 (번역 필드 포함)"""
    # 원본 필드
    title = (event.get('title') or '').lower()
    description = (event.get('deep_data') or '').lower()
    category_text = (event.get('category') or '').lower()
    # 번역 필드
    title_en = (event.get('title_en') or '').lower()
    description_en = (event.get('description_en') or '').lower()
    category_text_en = (event.get('category_en') or '').lower()

    score = 0
    for kw in keywords:
        k = kw.lower()
        # 원본 텍스트에서 점수 계산
        if k in title:
            score += 2
        if k in description:
            score += 1
        if k in category_text:
            score += 1
        # 번역 텍스트에서 점수 계산 (가중치 동일하게 부여)
        if title_en and k in title_en:
            score += 2
        if description_en and k in description_en:
            score += 1
        if category_text_en and k in category_text_en:
            score += 1
    return score


async def handle_chat_logic(raw_message: str) -> dict:
    """채팅 API 공용 로직"""
    if not raw_message:
        return {
            "response": {
                "keywords": [],
                "recommended_event": {},
                "reason": {
                    "ko": "메시지를 입력해주세요.",
                    "en": "Please enter a message to begin."
                }
            }
        }

    try:
        keywords = await extract_keywords_with_openai(raw_message)
        # 매칭
        matching: List[Tuple[dict, int]] = []
        for ev in events_data:
            s = score_event(ev, keywords)
            if s > 0:
                matching.append((ev, s))

        if not matching:
            return {
                "response": {
                    "keywords": keywords,
                    "recommended_event": {},
                    "reason": build_reason(None, keywords),
                }
            }

        best_event, _ = max(matching, key=lambda x: x[1])
        return {
            "response": {
                "keywords": keywords,
                "recommended_event": best_event,
                "reason": build_reason(best_event, keywords),
            }
        }
    except Exception as e:
        # 에러 시에도 일관된 JSON 반환
        return {
            "response": {
                "keywords": [],
                "recommended_event": {},
                "reason": {
                    "ko": f"오류가 발생했습니다: {str(e)}",
                    "en": f"An error occurred: {str(e)}"
                }
            }
        }


# =========================
# Lifespan
# =========================
@app.on_event("startup")
async def load_events_data():
    """서버 시작 시 events.json 및 번역 파일 로딩"""
    global events_data
    
    # 1. 원본 데이터 로드
    try:
        async with aiofiles.open(EVENTS_JSON_PATH, mode="r", encoding="utf-8") as f:
            content = await f.read()
            data = json.loads(content)
            if isinstance(data, dict) and "events" in data:
                raw_events = data["events"] or []
            elif isinstance(data, list):
                raw_events = data
            else:
                raw_events = []
        
        # 각 이벤트에 고유 ID 부여 (인덱스 사용)
        events_data = [{**event, "id": i} for i, event in enumerate(raw_events)]
        print(f"[startup] Loaded {len(events_data)} events from {EVENTS_JSON_PATH}")
        for ev in events_data:
            ev["state"] = compute_event_state(ev.get("period") or "")
    except FileNotFoundError:
        events_data = []
        print(f"[startup] Could not find events.json: {EVENTS_JSON_PATH}")
    except json.JSONDecodeError:
        events_data = []
        print(f"[startup] Error decoding events.json: {EVENTS_JSON_PATH}")

    # 2. 번역 데이터 로드 및 병합
    if not os.path.exists(EVENTS_EN_JSON_PATH):
        print(f"[startup] Translated events file not found: {EVENTS_EN_JSON_PATH}")
        print("[startup] You can generate it by calling the /api/translate-events endpoint.")
    else:
        try:
            async with aiofiles.open(EVENTS_EN_JSON_PATH, mode="r", encoding="utf-8") as f:
                translated_events_list = json.loads(await f.read())
                
                # id를 키로 하는 딕셔너리로 변환하여 빠른 조회를 위함
                translated_map = {item['id']: item for item in translated_events_list}
                
                merged_count = 0
                for event in events_data:
                    if event['id'] in translated_map:
                        event.update(translated_map[event['id']])
                        merged_count += 1
                print(f"[startup] Merged {merged_count} translated events from {EVENTS_EN_JSON_PATH}")

        except json.JSONDecodeError:
            print(f"[startup] Error decoding {EVENTS_EN_JSON_PATH}. Skipping merge.")
        except Exception as e:
            print(f"[startup] An error occurred while merging translated data: {e}")

    if not OPENAI_API_KEY:
        print("[warn] OPENAI_API_KEY is not set. Keyword extraction and translation will use fallback logic.")


# =========================
# Page routes (완전 분리)
# =========================
@app.get("/", include_in_schema=False)
async def root():
    # 기본 진입은 /chat 로 리다이렉트
    return RedirectResponse(url="/chat", status_code=302)


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """
    채팅 전용 페이지 (templates/chat.html 렌더링)
    프론트엔드는 /api/chat 을 호출하도록 구성 권장.
    """
    return templates.TemplateResponse("chat.html", {"request": request})


@app.get("/feed", response_class=HTMLResponse)
async def feed_page(request: Request):
    """
    피드 전용 페이지 (templates/feed.html 렌더링)
    프론트엔드는 /api/events 를 호출하도록 구성 권장.
    """
    return templates.TemplateResponse("feed.html", {"request": request})


# =========================
# API routes (권장 경로)
# =========================
@app.post("/api/chat")
async def api_chat(request: Request):
    """
    채팅 API (POST /api/chat)
    Body: { "message": "..." }
    """
    data = await request.json()
    raw_message = (data.get("message") or "").strip()
    return await handle_chat_logic(raw_message)


@app.get("/api/events")
async def api_events():
    """행사 목록 API (GET /api/events)"""
    return {"events": events_data}
@app.post("/api/translate-events")
async def api_translate_events():
    if not openai_client:
        return JSONResponse(status_code=400, content={"message": "OpenAI API key is not configured."})

    print("Starting event translation...")

    translated_events = []

    batch_size = 10  # 한 번에 10개씩 번역
    for i in range(0, len(events_data), batch_size):
        batch = events_data[i:i+batch_size]
        tasks = [translate_event_with_openai(event) for event in batch]
        results = await asyncio.gather(*tasks)

        # 성공한 것만 추가
        translated_events.extend([r for r in results if r and r.get("id") is not None])

        print(f"Translated batch {i//batch_size + 1} ({len(translated_events)}/{len(events_data)})")
        await asyncio.sleep(1.5)  # rate limit 방지 대기

    # 저장
    async with aiofiles.open(EVENTS_EN_JSON_PATH, mode="w", encoding="utf-8") as f:
        await f.write(json.dumps(translated_events, indent=2, ensure_ascii=False))

    print(f"Successfully translated and saved {len(translated_events)} events.")
    return {"message": f"Successfully translated {len(translated_events)} events.", "path": EVENTS_EN_JSON_PATH}

# =========================
# Legacy aliases (하위호환)
# =========================
@app.post("/chat")
async def legacy_chat(request: Request):
    """이전 프런트가 POST /chat 을 호출하던 경우 지원"""
    return await api_chat(request)


@app.get("/events")
async def legacy_events():
    """이전 프런트가 GET /events 를 호출하던 경우 지원"""
    return await api_events()


@app.get("/feed.html", include_in_schema=False)
async def legacy_feed_html():
    return RedirectResponse(url="/feed", status_code=301)

@app.get("/chat.html", include_in_schema=False)
async def legacy_chat_html():
    return RedirectResponse(url="/chat", status_code=301)


# =========================
# Health check
# =========================
@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}