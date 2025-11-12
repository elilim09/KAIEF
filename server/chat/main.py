import json
import os
from typing import List, Optional, Dict
import asyncio
import aiofiles
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# =========================
# Config
# =========================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EVENTS_JSON_PATH = os.path.join(BASE_DIR, "events.json")

openai_client: Optional[AsyncOpenAI] = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# =========================
# In-memory cache
# =========================
events_data: List[dict] = []

# 세션별 대화 히스토리 저장용 메모리
conversation_memory: Dict[str, List[Dict[str, str]]] = {}
MAX_MEMORY = 10


def compute_event_state(period: str) -> str:
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


# =========================
# Lifespan
# =========================
@app.on_event("startup")
async def load_events_data():
    global events_data
    try:
        async with aiofiles.open(EVENTS_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.loads(await f.read())
            if isinstance(data, list):
                raw_events = data
            elif isinstance(data, dict) and "events" in data:
                raw_events = data["events"]
            else:
                raw_events = []
        events_data = [{**event, "id": i} for i, event in enumerate(raw_events)]
        for e in events_data:
            e["state"] = compute_event_state(e.get("period") or "")
        print(f"[startup] Loaded {len(events_data)} events.")
    except Exception as e:
        print(f"[startup] Error loading events: {e}")
        events_data = []


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
# Chatbot Logic
# =========================
async def chatbot(message: str, chat_history: list = None, session_id: str = None) -> dict:
    """
    사용자 메시지를 받아 OpenAI API를 통해 답변 생성
    - message: 사용자 입력 문자열
    - chat_history: 이전 대화 리스트
    - session_id: 세션별 메모리 관리용
    """

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

    # compact_events 구성
    compact_events = [
        {
            "id": e.get("id"),
            "title": e.get("title"),
            "period": e.get("period"),
            "place": e.get("place"),
            "host": e.get("host"),
            "state": e.get("state"),
        }
        for e in events_data
    ]

    # system prompt
    system_prompt = f"""
너는 대한민국의 문화, 축제, 전시, 행사 정보를 추천하는 똑똑한 챗봇이야.
사용자의 질문을 이해하고 관련 이벤트를 추천해.

응답 형식은 반드시 JSON으로, 아래 구조를 따라야 해:
{{
  "response": {{
    "intent": "<event_search|greeting|help|smalltalk|other>",
    "keywords": ["사용자 메시지에서 추출한 핵심 키워드"],
    "recommended_event": {{
        "id": "<숫자>",
        "title": "<행사명>",
        "place": "<장소>",
        "host": "<주최자>",
        "period": "<YYYY-MM-DD~YYYY-MM-DD>",
        "state": "<진행중|예정|마감>"
    }},
    "reason": {{
        "ko": "<추천 이유 한글>",
        "en": "<추천 이유 영어>"
    }}
  }}
}}

### 대화 규칙
- 최대 3개 행사만 추천
- 항상 JSON 구조를 깨뜨리지 마
- 사용자의 언어 감지 후, reason의 ko/en 내용을 채워야 함
- 질문과 무관한 내용은 제거
- 날짜, 장소, 주최자는 반드시 포함
- 이전 대화 6개까지 기억하고 컨텍스트 반영
- 오늘 날짜: {datetime.now().strftime('%Y-%m-%d')}

### 행사 데이터
{json.dumps(compact_events, ensure_ascii=False)}
"""

    # messages 구성: system + 최근 6개 대화 + 사용자 입력
    messages = [{"role": "system", "content": system_prompt}]
    # history에서 role/content 모두 문자열로 유지
    for h in history[-6:]:
        messages.append({
            "role": h["role"],
            "content": str(h["content"])  # ✅ 반드시 문자열
        })
    messages.append({"role": "user", "content": str(message)})

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.5,
        )
        reply = response.choices[0].message.content.strip()

        # 히스토리 업데이트
        if session_id:
            history.append({"role": "user", "content": message})
            history.append({"role": "assistant", "content": reply})
            if len(history) > 10 * 2:  # MAX_MEMORY*2
                conversation_memory[session_id] = history[-20:]

        return {"response": reply}

    except Exception as e:
        print(f"[chatbot] Error: {e}")
        return {"response": "죄송합니다. 잠시 후 다시 시도해주세요."}


# =========================
# API routes
# =========================
@app.post("/api/chat")
async def api_chat(request: Request):
    data = await request.json()
    raw_message = (data.get("message") or "").strip()
    chat_history = data.get("chat_history", [])
    return await chatbot(raw_message, chat_history)


@app.get("/api/events")
async def api_events():
    return {"events": events_data}


# =========================
# Health Check
# =========================
@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}
