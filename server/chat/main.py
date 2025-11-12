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
            "url": e.get("url") or e.get("link") or "#",
        }
        for e in events_data
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
# - Remember last 6 conversations and reflect context
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

Example 3 (English Input - Children's Museum):
User: What kind of exhibition do you have at the children's museum?
Assistant: 
{{
  "response": {{
    "intent": "event_search",
    "recommended_event": [
      {{
        "id": 202,
        "title": "Interactive Children's Exhibition",
        "place": "National Children's Museum",
        "host": "Ministry of Culture, Sports and Tourism",
        "period": "2025-11-10~2025-11-25",
        "state": "Ongoing",
        "url": "http://example.com/childrens-exhibit"
      }}
    ],
    "reason": {{
      "ko": "아이들이 즐길 수 있는 체험 전시입니다.",
      "en": "An interactive exhibition suitable for children."
    }}
  }}
}}

### Now respond to the user's question with the same JSON structure as shown in the examples above.
Today's date: {datetime.now().strftime('%Y-%m-%d')}
Event data: {json.dumps(compact_events, ensure_ascii=False)}
"""


    # messages 구성: system + 최근 6개 대화 + 사용자 입력
    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-6:]:
        messages.append({"role": h["role"], "content": str(h["content"])})
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
            if len(history) > 20:
                conversation_memory[session_id] = history[-20:]

        # 반드시 JSON으로 파싱 후 반환
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
    raw_message = (data.get("message") or "").strip()
    chat_history = data.get("chat_history", [])
    return await chatbot(raw_message, chat_history)


@app.get("/events")
async def api_events():
    print(events_data[1])
    return {"events": events_data}


# =========================
# Health Check
# =========================
@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}