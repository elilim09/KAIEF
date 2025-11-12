# main.py
import json
import math
import os
import re
from typing import Any, Dict, List, Optional

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
DEFAULT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

openai_client: Optional[AsyncOpenAI] = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# =========================
# In-memory cache
# =========================
events_data: List[dict] = []


class EventRetriever:
    """행사 데이터를 위한 간단한 RAG 검색기"""

    def __init__(self, embedding_model: str) -> None:
        self.embedding_model = embedding_model
        self.events: List[dict] = []
        self.documents: List[Dict[str, Any]] = []
        self.embeddings: List[Any] = []
        self._vector_mode: str = "openai"  # 또는 fallback
        self._embedding_ready: bool = False
        self._lock = asyncio.Lock()
        self._event_by_id: Dict[Any, dict] = {}

    def refresh(self, events: List[dict]) -> None:
        self.events = events or []
        self._event_by_id = {event["id"]: event for event in self.events if "id" in event}
        self.documents = [
            {
                "id": event["id"],
                "text": self._compose_document(event)
            }
            for event in self.events
            if "id" in event
        ]
        self.embeddings = []
        self._embedding_ready = False

    def _compose_document(self, event: dict) -> str:
        sections = []
        title = event.get("title") or ""
        title_en = event.get("title_en") or ""
        if title:
            sections.append(f"제목: {title}")
        if title_en and title_en != title:
            sections.append(f"Title: {title_en}")
        category = event.get("category") or event.get("category_en") or ""
        if category:
            sections.append(f"카테고리: {category}")
        period = event.get("period") or event.get("date") or event.get("datetime") or ""
        if period:
            sections.append(f"기간: {period}")
        period_en = event.get("period_en")
        if period_en and period_en != period:
            sections.append(f"Schedule: {period_en}")
        place = event.get("place") or event.get("location") or ""
        if place:
            sections.append(f"장소: {place}")
        place_en = event.get("place_en")
        if place_en and place_en != place:
            sections.append(f"Venue: {place_en}")
        host = event.get("host") or event.get("organization") or ""
        if host:
            sections.append(f"주최: {host}")
        host_en = event.get("host_en")
        if host_en and host_en != host:
            sections.append(f"Host: {host_en}")
        description = event.get("deep_data") or event.get("description") or event.get("overview") or ""
        if description:
            sections.append(f"설명: {description}")
        description_en = event.get("description_en")
        if description_en and description_en != description:
            sections.append(f"Summary: {description_en}")
        cost = event.get("cost")
        if cost:
            sections.append(f"비용: {cost}")
        keywords = event.get("keywords")
        if keywords:
            sections.append(f"키워드: {keywords}")
        return "\n".join(sections)

    def _tokenize(self, text: str) -> List[str]:
        return [tok for tok in re.findall(r"[\w가-힣]+", text.lower()) if tok]

    def _fallback_vectorize(self, text: str) -> Dict[str, float]:
        tokens = self._tokenize(text)
        freq: Dict[str, float] = {}
        for token in tokens:
            freq[token] = freq.get(token, 0.0) + 1.0
        norm = math.sqrt(sum(v * v for v in freq.values())) or 1.0
        freq["__norm__"] = norm
        return freq

    def _fallback_cosine(self, a: Dict[str, float], b: Dict[str, float]) -> float:
        norm_a = a.get("__norm__", 0.0)
        norm_b = b.get("__norm__", 0.0)
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        keys = set(a.keys()) | set(b.keys())
        keys.discard("__norm__")
        dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
        return dot / (norm_a * norm_b) if dot else 0.0

    async def ensure_embeddings(self) -> None:
        if self._embedding_ready:
            return
        async with self._lock:
            if self._embedding_ready:
                return
            if not self.documents:
                self._embedding_ready = True
                return

            texts = [doc["text"] for doc in self.documents]
            if openai_client:
                try:
                    resp = await openai_client.embeddings.create(
                        model=self.embedding_model,
                        input=texts,
                    )
                    embeddings = [item.embedding for item in resp.data]  # type: ignore[attr-defined]
                    if len(embeddings) != len(texts):
                        raise ValueError("Embedding response size mismatch")
                    self.embeddings = embeddings
                    self._vector_mode = "openai"
                except Exception as exc:
                    print(f"[EventRetriever] Failed to fetch embeddings from OpenAI: {exc}. Falling back to local vectors.")
                    self.embeddings = [self._fallback_vectorize(text) for text in texts]
                    self._vector_mode = "fallback"
            else:
                self.embeddings = [self._fallback_vectorize(text) for text in texts]
                self._vector_mode = "fallback"

            self._embedding_ready = True

    async def search(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        query = (query or "").strip()
        if not query:
            return []

        await self.ensure_embeddings()
        if not self.documents or not self.embeddings:
            return []

        vector_mode = self._vector_mode
        query_vector: Any

        if vector_mode == "openai" and openai_client:
            try:
                resp = await openai_client.embeddings.create(
                    model=self.embedding_model,
                    input=[query],
                )
                query_vector = resp.data[0].embedding  # type: ignore[index]
            except Exception as exc:
                print(f"[EventRetriever] Query embedding failed: {exc}. Using fallback vectors.")
                vector_mode = "fallback"
                query_vector = self._fallback_vectorize(query)
        else:
            query_vector = self._fallback_vectorize(query)
            vector_mode = "fallback"

        scored: List[Dict[str, Any]] = []
        for doc, embedding in zip(self.documents, self.embeddings):
            event = self._event_by_id.get(doc["id"]) if self._event_by_id else None
            if not event:
                continue
            if vector_mode == "openai":
                if not isinstance(embedding, list):
                    continue
                norm_query = math.sqrt(sum(v * v for v in query_vector))
                norm_doc = math.sqrt(sum(v * v for v in embedding))
                if norm_query == 0.0 or norm_doc == 0.0:
                    score = 0.0
                else:
                    score = sum(q * d for q, d in zip(query_vector, embedding)) / (norm_query * norm_doc)
            else:
                if not isinstance(embedding, dict):
                    continue
                score = self._fallback_cosine(query_vector, embedding)  # type: ignore[arg-type]

            if score <= 0:
                continue
            scored.append({
                "event": event,
                "score": float(score),
                "document": doc["text"],
                "vector_mode": vector_mode,
            })

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:max(1, top_k)]


event_retriever = EventRetriever(EMBEDDING_MODEL)


async def translate_en_to_ko(text: str) -> str:
    """영문을 한국어로 번역"""
    if not openai_client:
        return text  # 폴백: 그대로 반환

    system_prompt = "Translate the following English text into natural Korean without losing meaning."
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text}
    ]

    try:
        resp = await openai_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=messages,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        translated = resp.choices[0].message.content
        return (translated or text).strip()
    except Exception:
        return text


def compute_event_state(period: str) -> str:
    """기간 텍스트로 행사 진행 상태 계산"""
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


async def translate_event_with_openai(event: dict) -> dict:
    """행사 정보를 OpenAI를 사용해 영어로 번역"""
    if not openai_client:
        return {}

    title = event.get("title") or ""
    place = event.get("place") or ""
    host = event.get("host") or ""
    period = event.get("period") or ""

    if not title and not place and not host and not period:
        return {"id": event.get("id")}

    system_prompt = """
You are a helpful translation assistant.
Translate the following JSON values from Korean to English.
- Keep the JSON structure.
- Provide only the translated JSON object, without any additional text or explanations.
- If a field is empty or missing, keep it as an empty string.
"""

    user_content = json.dumps(
        {
            "title": title,
            "place": place,
            "host": host,
            "period": period,
        },
        ensure_ascii=False,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        resp = await openai_client.chat.completions.create(
            model=DEFAULT_MODEL,
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
        }
    except Exception as exc:
        print(f"Error translating event ID {event.get('id')}: {exc}")
        return {
            "id": event.get("id"),
            "title_en": "",
            "place_en": "",
            "host_en": "",
            "period_en": "",
        }


def detect_language(raw_message: str) -> str:
    """간단한 언어 감지"""
    if not raw_message:
        return "ko"

    letters = [ch for ch in raw_message if ch.isalpha()]
    if not letters:
        return "ko"

    ascii_letters = sum(1 for ch in letters if ch.isascii())
    non_ascii_letters = len(letters) - ascii_letters

    if ascii_letters and (non_ascii_letters == 0 or ascii_letters >= non_ascii_letters * 2):
        return "en"
    return "ko"


def prepare_event_for_language(event: dict, language: str, score: Optional[float] = None) -> dict:
    if not event:
        return {}

    event_copy = {k: v for k, v in event.items()}
    state_map = {
        "진행중": "Ongoing",
        "종료": "Ended",
        "예정": "Upcoming",
        "알수없음": "Unknown",
    }

    if language == "en":
        event_copy["title_original"] = event.get("title")
        event_copy["place_original"] = event.get("place") or event.get("location")
        event_copy["host_original"] = event.get("host") or event.get("organization")
        event_copy["period_original"] = event.get("period") or event.get("date") or event.get("datetime")
        if event.get("title_en"):
            event_copy["title"] = event.get("title_en")
        if event.get("place_en"):
            event_copy["place"] = event.get("place_en")
        if event.get("host_en"):
            event_copy["host"] = event.get("host_en")
        if event.get("period_en"):
            event_copy["period"] = event.get("period_en")
        if event.get("state") in state_map:
            event_copy["state"] = state_map[event.get("state")]

    if score is not None:
        event_copy["rag_score"] = round(float(score), 4)

    return event_copy


def build_reason_payload(text: str, language: str) -> Dict[str, str]:
    message = (text or "").strip()
    if not message:
        message = "죄송하지만 요청하신 내용에 응답할 수 없습니다."
    return {"ko": message, "en": message}


SYSTEM_PROMPT = """
당신은 KAIEF라는 이름의 AI 어시스턴트입니다. 사용자의 질문에 친절하게 답변하고, 필요한 경우 대한민국의 행사 정보를 추천합니다.
- 일반적인 대화, 설명, 질문에는 스스로 답변합니다.
- 사용자가 행사 추천이나 갈 곳, 참여할 프로그램 등을 묻는 경우에는 반드시 `search_events` 도구를 호출해 관련 행사를 조회한 뒤 답변하세요.
- 도구를 통해 받은 행사 정보를 바탕으로 신뢰할 수 있는 추천 답변을 작성하고, 결과가 없으면 정중하게 사유를 설명합니다.
- 사용자의 언어(한국어 또는 영어)에 맞춰 자연스럽게 응답합니다.
- 도구 결과를 사용할 때는 행사명, 일정, 장소 등 핵심 정보를 명확하게 전달하고, 필요한 경우 불릿 리스트를 활용합니다.
""".strip()


FEWSHOT_MESSAGES = [
    {
        "role": "user",
        "content": "안녕?",
    },
    {
        "role": "assistant",
        "content": "안녕하세요! 궁금한 것이 있으면 무엇이든 말씀해주세요.",
    },
    {
        "role": "user",
        "content": "지금 날씨 어때?",
    },
    {
        "role": "assistant",
        "content": "제가 직접 날씨를 확인할 수는 없지만, 기상청이나 날씨 앱에서 현재 정보를 빠르게 확인할 수 있어요.",
    },
    {
        "role": "user",
        "content": "주말에 가족이랑 갈 만한 행사 추천해줘",
    },
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_example_1",
                "type": "function",
                "function": {
                    "name": "search_events",
                    "arguments": json.dumps({"query": "주말 가족 체험 행사", "top_k": 3}, ensure_ascii=False),
                },
            }
        ],
    },
    {
        "role": "tool",
        "tool_call_id": "call_example_1",
        "content": json.dumps(
            {
                "query": "주말 가족 체험 행사",
                "results": [
                    {
                        "event_id": 0,
                        "title": "가족과 함께하는 과학 체험전",
                        "period": "2024-08-01~2024-08-15",
                        "place": "서울 과학관",
                        "score": 0.89,
                        "context": "가족 대상 체험 프로그램과 야외 활동이 포함된 행사",
                    }
                ],
            },
            ensure_ascii=False,
        ),
    },
    {
        "role": "assistant",
        "content": "주말에 온 가족이 즐길 수 있는 과학 체험전을 추천드려요. 8월 1일부터 15일까지 서울 과학관에서 열리고, 다양한 야외 프로그램이 마련되어 있어요.",
    },
]


EVENT_SEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_events",
            "description": "사용자의 질의에 맞춰 행사 데이터를 검색합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "사용자의 자연어 질의. 핵심 요구를 그대로 전달하세요.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "검색 결과 개수 (1~5)",
                        "minimum": 1,
                        "maximum": 5,
                        "default": 3,
                    },
                },
                "required": ["query"],
            },
        },
    }
]


async def run_assistant_with_tools(raw_message: str, language: str) -> Dict[str, Any]:
    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}] + FEWSHOT_MESSAGES + [
        {"role": "user", "content": raw_message}
    ]

    used_tool = False
    recommended_event: Dict[str, Any] = {}
    last_tool_results: List[Dict[str, Any]] = []

    for _ in range(3):
        response = await openai_client.chat.completions.create(
            model=DEFAULT_MODEL,
            messages=messages,
            tools=EVENT_SEARCH_TOOLS,
            temperature=0.6,
        )
        choice = response.choices[0]
        message = choice.message

        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            used_tool = True
            for call in tool_calls:
                if call.type != "function" or call.function.name != "search_events":
                    continue

                args = {}
                if call.function.arguments:
                    try:
                        args = json.loads(call.function.arguments)
                    except json.JSONDecodeError:
                        args = {"query": raw_message}

                query = args.get("query") or raw_message
                top_k = args.get("top_k", 3)
                if not isinstance(top_k, int):
                    top_k = 3
                top_k = max(1, min(5, top_k))

                results = await event_retriever.search(query, top_k=top_k)
                formatted_results: List[Dict[str, Any]] = []
                for item in results:
                    event = item["event"]
                    score = item["score"]
                    formatted_results.append(
                        {
                            "event_id": event.get("id"),
                            "title": event.get("title"),
                            "title_en": event.get("title_en"),
                            "period": event.get("period") or event.get("date") or event.get("datetime"),
                            "period_en": event.get("period_en"),
                            "place": event.get("place") or event.get("location"),
                            "place_en": event.get("place_en"),
                            "host": event.get("host") or event.get("organization"),
                            "host_en": event.get("host_en"),
                            "category": event.get("category"),
                            "state": event.get("state"),
                            "url": event.get("url"),
                            "score": round(float(score), 4),
                            "context": item.get("document"),
                            "vector_mode": item.get("vector_mode"),
                        }
                    )
                    if not recommended_event:
                        recommended_event = prepare_event_for_language(event, language, score)

                last_tool_results = formatted_results

                tool_payload = {
                    "query": query,
                    "results": formatted_results,
                }

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(tool_payload, ensure_ascii=False),
                    }
                )
            continue

        final_text = message.content or ""
        return {
            "text": final_text,
            "used_tool": used_tool,
            "recommended_event": recommended_event,
            "tool_results": last_tool_results,
        }

    return {
        "text": "요청을 처리하는 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.",
        "used_tool": used_tool,
        "recommended_event": recommended_event,
        "tool_results": last_tool_results,
    }


async def handle_chat_logic(raw_message: str, user_id: str = "default_user") -> dict:
    if not raw_message:
        text = "메시지를 입력해주세요."
        return {
            "response": {
                "intent": "chat",
                "keywords": [],
                "recommended_event": {},
                "reason": build_reason_payload(text, "ko"),
            }
        }

    language = detect_language(raw_message)

    if not openai_client:
        message = (
            "OpenAI API 키가 설정되어 있지 않아 대화 기능을 사용할 수 없습니다. "
            "환경 변수를 확인한 뒤 다시 시도해주세요."
        )
        return {
            "response": {
                "intent": "chat",
                "keywords": [],
                "recommended_event": {},
                "reason": build_reason_payload(message, language),
            }
        }

    try:
        assistant_output = await run_assistant_with_tools(raw_message, language)
    except Exception as exc:
        error_message = f"요청을 처리하는 중 오류가 발생했습니다: {exc}"
        return {
            "response": {
                "intent": "chat",
                "keywords": [],
                "recommended_event": {},
                "reason": build_reason_payload(error_message, language),
            }
        }

    text = assistant_output.get("text", "")
    used_tool = assistant_output.get("used_tool", False)
    recommended_event = assistant_output.get("recommended_event") if used_tool else {}

    response_payload: Dict[str, Any] = {
        "intent": "event_recommendation" if used_tool else "chat",
        "keywords": [],
        "recommended_event": recommended_event or {},
        "reason": build_reason_payload(text, language),
    }

    tool_results = assistant_output.get("tool_results")
    if used_tool and tool_results:
        response_payload["alternatives"] = tool_results

    return {"response": response_payload}


# =========================
# Lifespan
# =========================
@app.on_event("startup")
async def load_events_data():
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
                    if event["id"] in translated_map:
                        event.update(translated_map[event["id"]])
                        merged_count += 1
                print(f"[startup] Merged {merged_count} translated events from {EVENTS_EN_JSON_PATH}")
        except json.JSONDecodeError:
            print(f"[startup] Error decoding {EVENTS_EN_JSON_PATH}. Skipping merge.")
        except Exception as exc:
            print(f"[startup] An error occurred while merging translated data: {exc}")
    else:
        print(f"[startup] Translated events file not found: {EVENTS_EN_JSON_PATH}")

    event_retriever.refresh(events_data)

    if openai_client:
        try:
            await event_retriever.ensure_embeddings()
        except Exception as exc:
            print(f"[startup] Embedding pre-computation failed: {exc}")
    else:
        print("[warn] OPENAI_API_KEY is not set. The assistant will operate in fallback mode.")


# =========================
# Page routes (완전 분리)
# =========================
@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/chat", status_code=302)


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})


@app.get("/feed", response_class=HTMLResponse)
async def feed_page(request: Request):
    return templates.TemplateResponse("feed.html", {"request": request})


# =========================
# API routes (권장 경로)
# =========================
@app.post("/api/chat")
async def api_chat(request: Request):
    data = await request.json()
    raw_message = (data.get("message") or "").strip()
    return await handle_chat_logic(raw_message)


@app.get("/api/events")
async def api_events():
    return {"events": events_data}


@app.post("/api/translate-events")
async def api_translate_events():
    if not openai_client:
        return JSONResponse(status_code=400, content={"message": "OpenAI API key is not configured."})

    print("Starting event translation...")

    translated_events = []
    batch_size = 10
    for i in range(0, len(events_data), batch_size):
        batch = events_data[i:i + batch_size]
        tasks = [translate_event_with_openai(event) for event in batch]
        results = await asyncio.gather(*tasks)
        translated_events.extend([r for r in results if r and r.get("id") is not None])
        print(f"Translated batch {i // batch_size + 1} ({len(translated_events)}/{len(events_data)})")
        await asyncio.sleep(1.5)

    async with aiofiles.open(EVENTS_EN_JSON_PATH, mode="w", encoding="utf-8") as f:
        await f.write(json.dumps(translated_events, indent=2, ensure_ascii=False))

    print(f"Successfully translated and saved {len(translated_events)} events.")
    return {"message": f"Successfully translated {len(translated_events)} events.", "path": EVENTS_EN_JSON_PATH}


# =========================
# Legacy aliases (하위호환)
# =========================
@app.post("/chat")
async def legacy_chat(request: Request):
    return await api_chat(request)


@app.get("/events")
async def legacy_events():
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
