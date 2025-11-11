# main.py
import json
import os
from typing import List, Tuple, Optional
import aiofiles
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import AsyncOpenAI
from dotenv import load_dotenv

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

openai_client: Optional[AsyncOpenAI] = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# =========================
# In-memory cache
# =========================
events_data: List[dict] = []


# =========================
# Helpers
# =========================
def build_reason(event: Optional[dict], keywords: List[str]) -> dict:
    """추천 사유 텍스트(ko/en) 구성"""
    if not event:
        return {
            "ko": "요청과 일치하는 행사를 찾지 못했습니다. 다른 조건으로 다시 시도해보세요.",
            "en": "No matching events were found. Try adjusting the filters and ask again."
        }

    title = event.get("title") or "행사"
    location = event.get("place") or event.get("location") or ""
    period = event.get("period") or event.get("date") or event.get("datetime") or ""
    host = event.get("host") or event.get("organization") or ""

    top_keywords = [k for k in (keywords or []) if k][:3]
    keyword_str = ", ".join(top_keywords)

    reason_ko = []
    reason_en = []

    if keyword_str:
        reason_ko.append(f"'{keyword_str}' 키워드와 가장 잘 맞는 '{title}' 행사를 추천했어요.")
        reason_en.append(f"We matched the keywords '{keyword_str}' with the event '{title}'.")
    else:
        reason_ko.append(f"'{title}' 행사를 추천했어요.")
        reason_en.append(f"We recommend the event '{title}'.")

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
    """간단한 키워드 점수 계산"""
    title = (event.get('title') or '').lower()
    description = (event.get('deep_data') or '').lower()
    category_text = (event.get('category') or '').lower()

    score = 0
    for kw in keywords:
        k = kw.lower()
        if k in title:
            score += 2
        if k in description:
            score += 1
        if k in category_text:
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
    """서버 시작 시 events.json 로딩"""
    global events_data
    try:
        async with aiofiles.open(EVENTS_JSON_PATH, mode="r", encoding="utf-8") as f:
            content = await f.read()
            data = json.loads(content)
            # 파일이 배열이면 그대로, { "events": [...] } 구조면 events만 취함
            if isinstance(data, dict) and "events" in data:
                events_data = data["events"] or []
            elif isinstance(data, list):
                events_data = data
            else:
                events_data = []
        print(f"[startup] Loaded events: {len(events_data)} from {EVENTS_JSON_PATH}")
    except FileNotFoundError:
        events_data = []
        print(f"[startup] events.json 파일을 찾을 수 없습니다: {EVENTS_JSON_PATH}")
    except json.JSONDecodeError:
        events_data = []
        print(f"[startup] events.json 디코딩 중 오류가 발생했습니다: {EVENTS_JSON_PATH}")

    if not OPENAI_API_KEY:
        print("[warn] OPENAI_API_KEY 환경변수가 설정되지 않았습니다. 키워드 추출은 간단 폴백 로직을 사용합니다.")


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