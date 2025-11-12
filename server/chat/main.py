import json
import math
import os
from typing import List, Optional, Dict, Any
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

EMBEDDING_MODEL = "text-embedding-3-small"
MAX_HISTORY_MESSAGES = 12
MAX_STORED_MESSAGES = MAX_HISTORY_MESSAGES * 2
MAX_EVENT_DESCRIPTION_LENGTH = 600

# =========================
# In-memory cache
# =========================
events_data: List[dict] = []

# 각 이벤트의 임베딩 캐시
event_embeddings: List[Dict[str, Any]] = []

# 세션별 대화 히스토리 저장용 메모리
conversation_memory: Dict[str, List[Dict[str, Any]]] = {}


def detect_language(text: str) -> str:
    if not text:
        return "ko"
    has_hangul = any("\uac00" <= ch <= "\ud7a3" for ch in text)
    if has_hangul:
        return "ko"
    has_ascii = any("A" <= ch <= "Z" or "a" <= ch <= "z" for ch in text)
    if has_ascii:
        return "en"
    return "ko"


def trim_text(value: Optional[str], limit: int = MAX_EVENT_DESCRIPTION_LENGTH) -> str:
    if not value:
        return ""
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def format_event_document(event: Dict[str, Any]) -> str:
    parts = [
        f"Title: {event.get('title', '')}",
        f"Category: {event.get('category', '')}",
        f"Audience: {event.get('audience', '')}",
        f"Period: {event.get('period') or event.get('date') or event.get('datetime', '')}",
        f"Place: {event.get('place') or event.get('location', '')}",
        f"Host: {event.get('host') or event.get('organization', '')}",
        f"State: {event.get('state') or event.get('status', '')}",
        f"Cost: {event.get('cost', '')}",
        f"Summary: {trim_text(event.get('deep_data') or event.get('description') or event.get('overview') or '')}",
    ]
    return "\n".join(part for part in parts if part)


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def build_event_embeddings(events: List[dict]):
    global event_embeddings
    event_embeddings = []
    if not events or not openai_client:
        return
    batch_size = 64
    try:
        for start in range(0, len(events), batch_size):
            batch = events[start : start + batch_size]
            documents = [format_event_document(event) for event in batch]
            embedding_response = await openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=documents,
            )
            for event, embedding_data in zip(batch, embedding_response.data):
                event_embeddings.append({
                    "event": event,
                    "embedding": embedding_data.embedding,
                })
        print(f"[startup] Generated embeddings for {len(event_embeddings)} events.")
    except Exception as e:
        print(f"[startup] Failed to generate embeddings: {e}")
        event_embeddings = []


def normalize_history_content(content: Any, language: str) -> str:
    if content is None:
        return ""
    if isinstance(content, dict):
        reason = content.get("reason")
        if isinstance(reason, dict):
            reason_text = reason.get(language) or reason.get("ko") or reason.get("en") or ""
        elif reason:
            reason_text = str(reason)
        else:
            reason_text = ""

        events = content.get("recommended_event")
        event_lines: List[str] = []
        if isinstance(events, list):
            iterable = events
        elif isinstance(events, dict):
            iterable = [events]
        else:
            iterable = []
        for ev in iterable:
            if not isinstance(ev, dict):
                continue
            title = ev.get("title") or ""
            place = ev.get("place") or ev.get("location") or ""
            period = ev.get("period") or ev.get("date") or ev.get("datetime") or ""
            event_lines.append(
                " - ".join(part for part in [title, place, period] if part)
            )
        parts = []
        if reason_text:
            parts.append(reason_text)
        if event_lines:
            label = "추천 행사" if language == "ko" else "Recommended events"
            parts.append(f"{label}:\n" + "\n".join(event_lines))
        return "\n\n".join(parts) or json.dumps(content, ensure_ascii=False)
    return str(content)


def normalize_history_for_llm(history: List[Dict[str, Any]], language: str) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    if not history:
        return normalized
    for item in history[-MAX_HISTORY_MESSAGES:]:
        role = item.get("role") if isinstance(item, dict) else None
        content = item.get("content") if isinstance(item, dict) else None
        normalized_content = normalize_history_content(content, language)
        if not role or not normalized_content:
            continue
        normalized.append({"role": role, "content": normalized_content})
    return normalized


def build_retrieval_query(message: str, history: List[Dict[str, str]]) -> str:
    if not history:
        return message
    user_messages = [h["content"] for h in history if h.get("role") == "user"]
    relevant = user_messages[-2:] + [message]
    return "\n".join(filter(None, relevant))


def format_event_for_prompt(event: Dict[str, Any], score: float) -> Dict[str, Any]:
    return {
        "id": event.get("id"),
        "title": event.get("title"),
        "category": event.get("category"),
        "period": event.get("period") or event.get("date") or event.get("datetime"),
        "place": event.get("place") or event.get("location"),
        "host": event.get("host") or event.get("organization"),
        "state": event.get("state") or event.get("status"),
        "url": event.get("url") or event.get("link"),
        "summary": trim_text(event.get("deep_data") or event.get("description") or event.get("overview")),
        "score": round(score, 4),
    }


async def retrieve_relevant_events(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    if not query:
        return []
    if openai_client and event_embeddings:
        try:
            embedding_response = await openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=[query],
            )
            query_vec = embedding_response.data[0].embedding
            scored = [
                {
                    "event": item["event"],
                    "score": cosine_similarity(query_vec, item["embedding"]),
                }
                for item in event_embeddings
            ]
            scored.sort(key=lambda x: x["score"], reverse=True)
            filtered = [item for item in scored if item["score"] > 0.15]
            if not filtered:
                return scored[:top_k]
            return filtered[:top_k]
        except Exception as e:
            print(f"[retrieve] Embedding retrieval failed: {e}")

    # Fallback: simple keyword matching
    lowered_query = query.lower()
    scored_fallback = []
    for event in events_data:
        haystack = " ".join(
            str(event.get(key, ""))
            for key in ("title", "category", "deep_data", "description", "place", "host")
        ).lower()
        score = sum(1 for token in lowered_query.split() if token and token in haystack)
        if score:
            scored_fallback.append({"event": event, "score": float(score)})
    scored_fallback.sort(key=lambda x: x["score"], reverse=True)
    return scored_fallback[:top_k]


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
        await build_event_embeddings(events_data)
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
        return {
            "response": {
                "intent": "other",
                "recommended_event": [],
                "reason": {
                    "ko": "메시지를 입력해주세요.",
                    "en": "Please enter a message.",
                },
            }
        }

    user_language = detect_language(message)

    if not openai_client:
        reason_map = {
            "ko": "OpenAI API 키가 설정되어 있지 않습니다.",
            "en": "The OpenAI API key is not configured.",
        }
        primary_reason = reason_map.get(user_language, reason_map["ko"])
        reason_map[user_language] = primary_reason
        return {
            "response": {
                "intent": "other",
                "recommended_event": [],
                "reason": reason_map,
            }
        }

    # 세션별 대화 기록 관리
    session_history_ref: Optional[List[Dict[str, Any]]] = None
    if session_id:
        session_history_ref = conversation_memory.setdefault(session_id, [])

    stored_history: List[Dict[str, Any]] = []
    if isinstance(chat_history, list) and chat_history:
        stored_history = chat_history
        if session_id:
            conversation_memory[session_id] = chat_history[-MAX_STORED_MESSAGES:]
            session_history_ref = conversation_memory[session_id]
    elif session_history_ref is not None:
        stored_history = session_history_ref

    language_label = "한국어" if user_language == "ko" else "English"

    normalized_history = normalize_history_for_llm(stored_history, user_language)
    retrieval_query = build_retrieval_query(message, normalized_history)
    retrieved_items = await retrieve_relevant_events(retrieval_query, top_k=5)
    rag_events_for_prompt = [
        format_event_for_prompt(item["event"], item["score"])
        for item in retrieved_items
    ]

    system_prompt = f"""
너는 대한민국의 문화, 전시, 축제 정보를 소개하고 대화를 이어가는 AI 큐레이터다.
반드시 아래 JSON 구조를 그대로 유지한 문자열로만 응답해야 한다.

{{
  "response": {{
    "intent": "event_search" 또는 "other" 등 사용자 의도를 나타내는 문자열,
    "recommended_event": [{{...}}],
    "reason": {{"ko": "", "en": ""}}
  }}
}}

- recommended_event는 항상 배열이며 비어 있을 수 있다.
- 각 recommended_event 항목에는 id, title, place, host, period, state, url을 가능한 한 채워라. 정보가 없으면 "알수없음" 또는 "Unknown"으로 기록해라.
- reason.ko와 reason.en 키를 유지하되, 사용자 언어({language_label})에 맞춰 reason의 해당 언어 값을 자연스럽고 대화체로 작성하고, 다른 언어는 간결한 번역을 제공해라.
- 제공된 대화 맥락을 활용하여 사용자가 이미 전달한 정보나 선호를 반복해서 묻지 말고 자연스럽게 이어서 대화해라.
- 추천할 만한 행사가 없으면 recommended_event는 빈 배열로 두고, 사용자가 도움이 될 만한 추가 질문이나 제안을 reason에 포함해라.
- 소규모 잡담이나 다른 문의에도 친절하게 응답하되 JSON 구조는 반드시 유지해라.
- 오늘 날짜는 {datetime.now().strftime('%Y-%m-%d')}이다.
- 반드시 사용자 메시지와 동일한 언어({language_label})로 reason의 주요 문장을 작성해라.
"""

    messages = [{"role": "system", "content": system_prompt}]

    if rag_events_for_prompt:
        messages.append(
            {
                "role": "system",
                "content": "다음은 RAG 검색으로 찾은 관련 행사 후보 목록이다. 높은 점수일수록 관련도가 높다. 필요한 정보만 활용해라.\n"
                + json.dumps(rag_events_for_prompt, ensure_ascii=False),
            }
        )
    else:
        messages.append(
            {
                "role": "system",
                "content": "RAG 검색 결과가 없거나 충분하지 않다. 사용자의 질문을 더 파악하고 필요하다면 추가 정보를 요청해라.",
            }
        )

    messages.extend(normalized_history)
    messages.append({"role": "user", "content": message})
    
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.5,
        )
        reply = response.choices[0].message.content.strip()

        # 히스토리 업데이트
        if session_history_ref is not None:
            session_history_ref.append({"role": "user", "content": message})
            if len(session_history_ref) > MAX_STORED_MESSAGES:
                conversation_memory[session_id] = session_history_ref[-MAX_STORED_MESSAGES:]
                session_history_ref = conversation_memory[session_id]

        # 반드시 JSON으로 파싱 후 반환
        try:
            json_reply = json.loads(reply)
            if session_history_ref is not None:
                session_history_ref.append({"role": "assistant", "content": json_reply.get("response")})
                if len(session_history_ref) > MAX_STORED_MESSAGES:
                    conversation_memory[session_id] = session_history_ref[-MAX_STORED_MESSAGES:]
                    session_history_ref = conversation_memory[session_id]
            return {"response": json_reply["response"]}
        except Exception:
            fallback_reason = {
                "ko": reply if user_language == "ko" else "죄송합니다. 응답을 이해하지 못했습니다.",
                "en": reply if user_language == "en" else "Sorry, I couldn't understand the response.",
            }
            if session_history_ref is not None:
                session_history_ref.append({
                    "role": "assistant",
                    "content": {
                        "intent": "other",
                        "recommended_event": [],
                        "reason": fallback_reason,
                    },
                })
                if len(session_history_ref) > MAX_STORED_MESSAGES:
                    conversation_memory[session_id] = session_history_ref[-MAX_STORED_MESSAGES:]
                    session_history_ref = conversation_memory[session_id]
            return {"response": {
                "intent": "other",
                "recommended_event": [],
                "reason": fallback_reason,
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


@app.get("/api/events")
async def api_events():
    return {"events": events_data}


# =========================
# Health Check
# =========================
@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}
