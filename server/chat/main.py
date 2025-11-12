# main.py
import asyncio
import json
import math
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiofiles
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from openai import AsyncOpenAI

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
# Config (ENV 권장)
# =========================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
EVENTS_JSON_PATH = os.getenv("EVENTS_JSON_PATH", os.path.join(BASE_DIR, "events.json"))
EVENTS_EN_JSON_PATH = os.getenv("EVENTS_EN_JSON_PATH", os.path.join(BASE_DIR, "events_en.json"))

openai_client: Optional[AsyncOpenAI] = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# =========================
# In-memory caches
# =========================
events_data: List[Dict[str, Any]] = []
event_documents: List[str] = []
event_embeddings: List[List[float]] = []
conversation_histories: Dict[str, List[Dict[str, Any]]] = {}
embeddings_lock = asyncio.Lock()

# =========================
# Prompt & tool definitions
# =========================
SYSTEM_PROMPT = """
You are KAIEF, an affable bilingual AI assistant that helps people discover cultural events in Korea.
Hold natural multi-turn conversations just like a general-purpose AI model would. Track context across turns
and respond in the same language as the user unless they request otherwise.

When a user asks for event recommendations, searches for events, or needs details that require the event
catalogue, you must call the `recommend_events` tool with a concise query summarizing their needs. After
receiving tool output, craft a friendly, well-structured answer that references the retrieved events.
If the tool returns no events, acknowledge that clearly and suggest how the user might refine the request.
Never fabricate events that are not present in the tool response. For general chit-chat or knowledge
questions, respond directly without calling any tools.
""".strip()

FEW_SHOT_MESSAGES: List[Dict[str, Any]] = [
    {
        "role": "user",
        "content": "주말에 가족이랑 즐길 수 있는 과학 체험 행사 추천해줘",
    },
    {
        "role": "assistant",
        "tool_calls": [
            {
                "id": "call_fewshot_1",
                "type": "function",
                "function": {
                    "name": "recommend_events",
                    "arguments": json.dumps({"query": "주말 가족 과학 체험", "limit": 3}, ensure_ascii=False),
                },
            }
        ],
        "content": "",
    },
    {
        "role": "tool",
        "tool_call_id": "call_fewshot_1",
        "name": "recommend_events",
        "content": json.dumps(
            {
                "query": "주말 가족 과학 체험",
                "events": [
                    {
                        "id": 101,
                        "title": "패밀리 과학 놀이터",
                        "period": "2024-05-11~2024-05-12",
                        "place": "성남 어린이과학관",
                        "summary": "주말에 가족이 함께 참여하는 과학 실험과 워크숍",
                    }
                ],
                "context": "- 패밀리 과학 놀이터: 주말 체험형 프로그램, 어린이와 보호자 동반 참여",
            },
            ensure_ascii=False,
        ),
    },
    {
        "role": "assistant",
        "content": "주말에 가족과 함께 참여할 수 있는 \"패밀리 과학 놀이터\"를 추천드려요. 성남 어린이과학관에서 열리고, 다양한 실험과 워크숍이 마련되어 있습니다. 일정과 장소를 확인하고 방문 계획을 세워보세요!",
    },
    {
        "role": "user",
        "content": "고마워!",
    },
    {
        "role": "assistant",
        "content": "별말씀을요. 더 궁금한 점이 있으면 언제든 물어보세요!",
    },
    {
        "role": "user",
        "content": "What exactly is AI?",
    },
    {
        "role": "assistant",
        "content": "Artificial intelligence (AI) refers to computer systems designed to perform tasks that typically require human intelligence, such as learning from data, reasoning, recognizing patterns, or generating language.",
    },
]

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "recommend_events",
            "description": "Retrieve the most relevant Korean events using embeddings and return structured details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Concise description of the user's needs for matching events.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of events to return.",
                        "default": 3,
                        "minimum": 1,
                        "maximum": 5,
                    },
                    "language": {
                        "type": "string",
                        "description": "User language hint such as 'ko' or 'en' to tailor summaries.",
                    },
                },
                "required": ["query"],
            },
        },
    }
]

# =========================
# Utility functions
# =========================

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
        if start_date <= today <= end_date:
            return "진행중"
        return "종료"
    except Exception:
        return "알수없음"


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def build_event_document(event: Dict[str, Any]) -> str:
    parts = [
        event.get("title"),
        event.get("category"),
        event.get("period"),
        event.get("place"),
        event.get("host"),
        event.get("deep_data"),
        event.get("description"),
        event.get("overview"),
    ]
    translated_parts = [
        event.get("title_en"),
        event.get("category_en"),
        event.get("place_en"),
        event.get("host_en"),
        event.get("period_en"),
        event.get("description_en"),
    ]
    content = " \n ".join(str(part).strip() for part in parts + translated_parts if part)
    return content or event.get("title", "")


async def translate_event_with_openai(event: Dict[str, Any]) -> Dict[str, Any]:
    if not openai_client:
        return {}

    title = event.get("title") or ""
    place = event.get("place") or ""
    host = event.get("host") or ""
    period = event.get("period") or ""

    if not any([title, place, host, period]):
        return {"id": event.get("id")}

    system_prompt = (
        "You are a helpful translation assistant. Translate the provided JSON values from Korean to English. "
        "Return only the translated JSON object without explanations."
    )
    user_content = json.dumps(
        {
            "title": title,
            "place": place,
            "host": host,
            "period": period,
        },
        ensure_ascii=False,
    )

    try:
        resp = await openai_client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
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
        }
    except Exception as exc:  # pragma: no cover - network failure fallback
        print(f"[warn] Failed to translate event {event.get('id')}: {exc}")
        return {
            "id": event.get("id"),
            "title_en": "",
            "place_en": "",
            "host_en": "",
            "period_en": "",
        }


async def prepare_event_embeddings(force: bool = False) -> None:
    global event_documents, event_embeddings
    if not openai_client:
        event_documents = []
        event_embeddings = []
        return

    if event_documents and event_embeddings and not force:
        return

    async with embeddings_lock:
        if event_documents and event_embeddings and not force:
            return

        texts = [build_event_document(event) for event in events_data]
        event_documents = texts
        event_embeddings = []

        if not texts:
            return

        batch_size = 64
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            try:
                resp = await openai_client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
            except Exception as exc:  # pragma: no cover - network failure fallback
                print(f"[warn] Failed to create embeddings batch {i//batch_size}: {exc}")
                event_embeddings = []
                return

            for item in resp.data:
                event_embeddings.append(item.embedding)

        if len(event_embeddings) != len(events_data):
            print("[warn] Embedding count mismatch. Clearing embeddings.")
            event_embeddings = []


async def ensure_event_embeddings() -> None:
    if not event_embeddings or len(event_embeddings) != len(events_data):
        await prepare_event_embeddings(force=True)


def build_event_summary(event: Dict[str, Any]) -> str:
    pieces = []
    title = event.get("title") or event.get("title_en") or "이름 미상 행사"
    period = event.get("period") or event.get("period_en")
    place = event.get("place") or event.get("place_en")
    category = event.get("category") or event.get("category_en")
    if period:
        pieces.append(f"일정 {period}")
    if place:
        pieces.append(f"장소 {place}")
    if category:
        pieces.append(f"분야 {category}")
    overview = event.get("deep_data") or event.get("description") or event.get("overview")
    if overview:
        pieces.append(overview)
    return f"{title}: " + ", ".join(pieces)


async def recommend_events_tool(query: str, limit: int = 3, language: Optional[str] = None) -> Dict[str, Any]:
    if not query:
        return {"query": "", "events": [], "context": ""}

    if not events_data:
        return {"query": query, "events": [], "context": "No events are available."}

    if not openai_client or not OPENAI_API_KEY:
        return {
            "query": query,
            "events": [],
            "context": "OpenAI client is not configured; cannot perform embedding search.",
        }

    await ensure_event_embeddings()

    if not event_embeddings or len(event_embeddings) != len(events_data):
        return {
            "query": query,
            "events": [],
            "context": "Event embeddings are not ready.",
        }

    try:
        query_embedding_resp = await openai_client.embeddings.create(model=EMBEDDING_MODEL, input=[query])
    except Exception as exc:  # pragma: no cover - network failure fallback
        print(f"[warn] Failed to embed query: {exc}")
        return {"query": query, "events": [], "context": "Failed to embed query."}

    query_vector = query_embedding_resp.data[0].embedding

    scored_events: List[Dict[str, Any]] = []
    for idx, (event, embedding) in enumerate(zip(events_data, event_embeddings)):
        score = cosine_similarity(query_vector, embedding)
        scored_events.append({"index": idx, "score": score})

    scored_events.sort(key=lambda item: item["score"], reverse=True)

    limit = max(1, min(limit, 5))
    selected = []
    context_lines = []
    for item in scored_events[:limit]:
        event = events_data[item["index"]]
        payload = {
            "id": event.get("id"),
            "title": event.get("title"),
            "title_en": event.get("title_en"),
            "category": event.get("category"),
            "category_en": event.get("category_en"),
            "period": event.get("period"),
            "period_en": event.get("period_en"),
            "place": event.get("place"),
            "place_en": event.get("place_en"),
            "host": event.get("host"),
            "host_en": event.get("host_en"),
            "state": event.get("state"),
            "cost": event.get("cost"),
            "url": event.get("url"),
            "deep_data": event.get("deep_data"),
            "description": event.get("description"),
            "overview": event.get("overview"),
            "score": round(float(item["score"]), 4),
        }
        selected.append(payload)
        context_lines.append(f"- {build_event_summary(event)} (score: {item['score']:.3f})")

    return {
        "query": query,
        "events": selected,
        "context": "\n".join(context_lines),
        "language": language,
    }


def get_base_messages() -> List[Dict[str, Any]]:
    return [{"role": "system", "content": SYSTEM_PROMPT}] + FEW_SHOT_MESSAGES.copy()


def get_history(user_id: str) -> List[Dict[str, Any]]:
    return conversation_histories.setdefault(user_id, [])


def trim_history(history: List[Dict[str, Any]], max_messages: int = 24) -> List[Dict[str, Any]]:
    if len(history) <= max_messages:
        return history
    return history[-max_messages:]


async def chat_completion(messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Any:
    if not openai_client:
        raise RuntimeError("OpenAI client is not configured.")
    return await openai_client.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        tools=tools,
        temperature=0.6,
    )


async def handle_chat_logic(raw_message: str, user_id: str = "default_user") -> Dict[str, Any]:
    raw_message = (raw_message or "").strip()
    if not raw_message:
        return {"response": {"message": "메시지를 입력해주세요.", "events": []}}

    history = get_history(user_id)
    history.append({"role": "user", "content": raw_message})
    history[:] = trim_history(history)

    messages = get_base_messages() + history

    events_payload: List[Dict[str, Any]] = []
    try:
        first_completion = await chat_completion(messages, tools=TOOLS)
    except Exception as exc:  # pragma: no cover - network failure fallback
        error_message = f"OpenAI 호출 중 오류가 발생했습니다: {exc}"
        history.append({"role": "assistant", "content": error_message})
        return {"response": {"message": error_message, "events": []}}

    first_message = first_completion.choices[0].message

    if first_message.tool_calls:
        assistant_record: Dict[str, Any] = {"role": "assistant", "tool_calls": first_message.tool_calls}
        if first_message.content:
            assistant_record["content"] = first_message.content
        history.append(assistant_record)

        for tool_call in first_message.tool_calls:
            function_name = tool_call.function.name
            arguments = {}
            try:
                if tool_call.function.arguments:
                    arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}

            if function_name == "recommend_events":
                tool_result = await recommend_events_tool(
                    query=arguments.get("query", raw_message),
                    limit=arguments.get("limit", 3),
                    language=arguments.get("language"),
                )
                events_payload = tool_result.get("events", [])
            else:
                tool_result = {"error": f"Unknown tool {function_name}"}

            history.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": function_name,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                }
            )

        history[:] = trim_history(history)
        messages = get_base_messages() + history
        try:
            second_completion = await chat_completion(messages)
            final_message = second_completion.choices[0].message.content or ""
        except Exception as exc:  # pragma: no cover - network failure fallback
            final_message = f"도움말을 생성하는 중 오류가 발생했습니다: {exc}"
        history.append({"role": "assistant", "content": final_message})
        history[:] = trim_history(history)
        return {"response": {"message": final_message, "events": events_payload}}

    final_content = first_message.content or ""
    history.append({"role": "assistant", "content": final_content})
    history[:] = trim_history(history)
    return {"response": {"message": final_content, "events": events_payload}}


# =========================
# Lifespan
# =========================
@app.on_event("startup")
async def load_events_data() -> None:
    global events_data
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
        events_data = [{**event, "id": i} for i, event in enumerate(raw_events)]
        for ev in events_data:
            ev["state"] = compute_event_state(ev.get("period") or "")
        print(f"[startup] Loaded {len(events_data)} events from {EVENTS_JSON_PATH}")
    except FileNotFoundError:
        events_data = []
        print(f"[startup] Could not find events.json: {EVENTS_JSON_PATH}")
    except json.JSONDecodeError:
        events_data = []
        print(f"[startup] Error decoding events.json: {EVENTS_JSON_PATH}")

    if os.path.exists(EVENTS_EN_JSON_PATH):
        try:
            async with aiofiles.open(EVENTS_EN_JSON_PATH, mode="r", encoding="utf-8") as f:
                translated_events_list = json.loads(await f.read())
            translated_map = {item["id"]: item for item in translated_events_list}
            merged_count = 0
            for event in events_data:
                translated = translated_map.get(event["id"])
                if translated:
                    event.update(translated)
                    merged_count += 1
            print(f"[startup] Merged {merged_count} translated events from {EVENTS_EN_JSON_PATH}")
        except Exception as exc:
            print(f"[startup] Failed to merge translated events: {exc}")
    else:
        print(f"[startup] Translated events file not found: {EVENTS_EN_JSON_PATH}")

    if OPENAI_API_KEY:
        asyncio.create_task(prepare_event_embeddings())
    else:
        print("[warn] OPENAI_API_KEY is not set. Event recommendations will be limited.")


# =========================
# Page routes
# =========================
@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/chat", status_code=302)


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("chat.html", {"request": request})


@app.get("/feed", response_class=HTMLResponse)
async def feed_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("feed.html", {"request": request})


# =========================
# API routes
# =========================
@app.post("/api/chat")
async def api_chat(request: Request) -> Dict[str, Any]:
    data = await request.json()
    raw_message = (data.get("message") or "").strip()
    user_id = (data.get("user_id") or "default_user").strip() or "default_user"
    return await handle_chat_logic(raw_message, user_id=user_id)


@app.get("/api/events")
async def api_events() -> Dict[str, Any]:
    return {"events": events_data}


@app.post("/api/translate-events")
async def api_translate_events() -> JSONResponse:
    if not openai_client:
        return JSONResponse(status_code=400, content={"message": "OpenAI API key is not configured."})

    translated_events: List[Dict[str, Any]] = []
    batch_size = 10
    for i in range(0, len(events_data), batch_size):
        batch = events_data[i : i + batch_size]
        tasks = [translate_event_with_openai(event) for event in batch]
        results = await asyncio.gather(*tasks)
        translated_events.extend([result for result in results if result and result.get("id") is not None])
        await asyncio.sleep(1.5)

    async with aiofiles.open(EVENTS_EN_JSON_PATH, mode="w", encoding="utf-8") as f:
        await f.write(json.dumps(translated_events, indent=2, ensure_ascii=False))

    return JSONResponse(
        content={
            "message": f"Successfully translated {len(translated_events)} events.",
            "path": EVENTS_EN_JSON_PATH,
        }
    )


# =========================
# Legacy aliases
# =========================
@app.post("/chat")
async def legacy_chat(request: Request) -> Dict[str, Any]:
    return await api_chat(request)


@app.get("/events")
async def legacy_events() -> Dict[str, Any]:
    return await api_events()


@app.get("/feed.html", include_in_schema=False)
async def legacy_feed_html() -> RedirectResponse:
    return RedirectResponse(url="/feed", status_code=301)


@app.get("/chat.html", include_in_schema=False)
async def legacy_chat_html() -> RedirectResponse:
    return RedirectResponse(url="/chat", status_code=301)


# =========================
# Health check
# =========================
@app.get("/healthz", include_in_schema=False)
async def healthz() -> Dict[str, bool]:
    return {"ok": True}
