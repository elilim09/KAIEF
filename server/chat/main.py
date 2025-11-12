import json
import os
from typing import List, Optional, Dict, Tuple
import asyncio
import math

import aiofiles
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import AsyncOpenAI
from dotenv import load_dotenv
from datetime import datetime
from langdetect import detect, DetectorFactory

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

EMBEDDING_MODEL = "text-embedding-3-small"
RETRIEVAL_TOP_K = 5

# 언어 감지의 일관성을 위해 시드 고정
DetectorFactory.seed = 0

# =========================
# In-memory cache
# =========================
events_data: List[dict] = []
event_embeddings: List[List[float]] = []

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
    global events_data, event_embeddings
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
        if openai_client and events_data:
            event_embeddings = await build_event_embeddings(events_data)
            print(f"[startup] Generated embeddings for {len(event_embeddings)} events.")
        else:
            event_embeddings = []
    except Exception as e:
        print(f"[startup] Error loading events: {e}")
        events_data = []
        event_embeddings = []


def build_event_text(event: Dict[str, str]) -> str:
    parts = [
        event.get("title") or "",
        event.get("description") or "",
        event.get("place") or "",
        event.get("host") or "",
        event.get("period") or "",
        event.get("category") or "",
        event.get("tags") or "",
    ]
    return " \n".join([p for p in parts if p])


async def build_event_embeddings(events: List[Dict[str, str]]) -> List[List[float]]:
    """Generate embeddings for events using the configured embedding model."""
    if not openai_client:
        return []

    texts = [build_event_text(event) for event in events]
    embeddings: List[List[float]] = []
    batch_size = 64

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = await openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=batch,
        )
        embeddings.extend([item.embedding for item in response.data])
        await asyncio.sleep(0)  # allow event loop to switch tasks

    return embeddings


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    if not vec1 or not vec2:
        return 0.0
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


async def retrieve_relevant_events(query: str) -> List[Tuple[dict, float]]:
    """Retrieve top events using embedding-based semantic search."""
    if not openai_client or not events_data or not event_embeddings:
        return []

    response = await openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query,
    )
    query_embedding = response.data[0].embedding

    scored_events = []
    for event, event_embedding in zip(events_data, event_embeddings):
        score = cosine_similarity(query_embedding, event_embedding)
        scored_events.append((event, score))

    scored_events.sort(key=lambda item: item[1], reverse=True)
    return scored_events[:RETRIEVAL_TOP_K]


def detect_user_language(message: str) -> str:
    try:
        language_code = detect(message)
        return language_code
    except Exception:
        return "ko"


def normalize_language(language_code: str) -> Tuple[str, str]:
    language_code = (language_code or "ko").split("-")[0].lower()
    language_map = {
        "ko": "Korean",
        "en": "English",
        "ja": "Japanese",
        "zh": "Chinese",
    }
    return language_code, language_map.get(language_code, "Unknown")


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

    compact_events = [
        {
            "id": e.get("id"),
            "title": e.get("title"),
            "period": e.get("period"),
            "place": e.get("place"),
            "host": e.get("host"),
            "state": e.get("state"),
            "url": e.get("url"),
        }
        for e in events_data
    ]

    user_lang_code, user_lang_name = normalize_language(detect_user_language(message))

    retrieved = await retrieve_relevant_events(message)
    retrieved_events_payload = [
        {
            "id": event.get("id"),
            "title": event.get("title"),
            "place": event.get("place"),
            "host": event.get("host"),
            "period": event.get("period"),
            "state": event.get("state"),
            "url": event.get("url"),
            "similarity": round(score, 4),
            "summary": event.get("description") or event.get("summary") or "",
        }
        for event, score in retrieved
    ]

    retrieval_instruction = json.dumps(retrieved_events_payload, ensure_ascii=False)

    system_prompt = f"""
너는 대한민국 문화/전시/축제 정보를 추천하는 AI 챗봇이자 전문 큐레이터야.
다음 규칙을 항상 따라.

1. 응답은 반드시 JSON 형식이며, 최상위 키는 response 야.
2. response.intent 는 사용자의 의도를 반영한 값(event_search, chit_chat 등)으로 채워.
3. response.recommended_event 는 배열이며, 각 원소는 id, title, place, host, period, state, url 을 포함해야 해. 누락된 값은 "알수없음"으로 작성해.
4. response.reason 은 ko, en 두 필드를 포함하고, 각각 한국어와 영어 설명을 제공해야 해. 하지만 사용자의 주 언어({user_lang_name})로 작성한 설명을 우선적으로 자연스럽게 제공하고, 다른 언어 버전도 충실히 번역해.
5. JSON 구조를 절대 변경하지 말고, 설명 외의 문장은 금지야.
6. 대화 맥락을 충분히 활용해서 부드럽고 일관된 흐름을 유지해.
7. 행사를 추천할 때는 아래의 임베딩 기반 검색 결과를 우선 활용하고, 관련도가 낮으면 추천하지 말고 다른 도움이 될 만한 답변을 해.
8. 제공된 행사 정보 외의 내용을 언급할 때는 명확히 추론임을 밝히고, 허구의 링크는 만들지 마.
9. 사용자가 {user_lang_name} 로 말했으므로, 모든 자연어 설명은 반드시 {user_lang_name} 로 자연스럽게 작성하고 필요 시 다른 언어 번역은 부가적으로 제공해.
10. 오늘 날짜는 {datetime.now().strftime('%Y-%m-%d')} 이고, 이 정보를 참고해 행사 상태를 판단해.

### 임베딩 검색 결과 (유사도 높은 순)
{retrieval_instruction}

### 전체 행사 메타데이터
{json.dumps(compact_events, ensure_ascii=False)}

위 정보를 사용해서 사용자의 요청에 가장 잘 맞는 답변을 JSON 으로 출력해.
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
    session_id = data.get("session_id")
    return await chatbot(raw_message, chat_history, session_id=session_id)


@app.get("/api/events")
async def api_events():
    return {"events": events_data}


# =========================
# Health Check
# =========================
@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}
