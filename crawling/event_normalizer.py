import hashlib
import json
import re
from typing import Any, Dict, Iterable, List


PLACE_BY_SOURCE = {
    "성남시청": "성남시",
    "성남시청소년재단": "성남시청소년재단",
    "성남아트센터": "성남아트센터",
    "맹산환경생태학습원": "맹산환경생태학습원",
    "판교환경생태학습원": "판교환경생태학습원",
    "한국잡월드": "한국잡월드",
    "성남문화원": "성남문화원",
    "판교박물관": "판교박물관",
    "판교종합사회복지관": "판교종합사회복지관",
    "판교노인종합복지관": "판교노인종합복지관",
}


ALIAS_KEYS = {"link", "date", "deep_data", "datetime", "location", "organization", "status"}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = " ".join(clean_text(item) for item in value)
    return re.sub(r"\s+", " ", str(value)).strip()


def clean_multiline(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:7000]


def first_value(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


def normalize_period(value: Any) -> str:
    period = clean_text(value)
    if not period:
        return ""

    period = period.replace("행사일 :", "").replace("행사일:", "").strip()
    period = re.sub(r"\b(\d{4})(\d{2})(\d{2})\b", r"\1-\2-\3", period)
    period = re.sub(r"(\d{4})[./](\d{1,2})[./](\d{1,2})", _pad_date, period)
    period = re.sub(r"(\d{4}-\d{2}-\d{2})\s*[-~–]\s*(\d{4}-\d{2}-\d{2})", r"\1~\2", period)
    period = re.sub(r"\s*[~–]\s*", "~", period)
    return period


def _pad_date(match: re.Match) -> str:
    year, month, day = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def infer_source(event: Dict[str, Any]) -> str:
    source = first_value(event.get("source"))
    if source:
        return source

    url = first_value(event.get("url"), event.get("link"))
    host = first_value(event.get("host"))
    if "culture.go.kr" in url or host:
        return "문화포털"
    return ""


def infer_place(event: Dict[str, Any], source: str) -> str:
    place = first_value(event.get("place"), event.get("location"))
    if place:
        return place

    url = first_value(event.get("url"), event.get("link"))
    for key, mapped_place in PLACE_BY_SOURCE.items():
        if key == source or key in url:
            return mapped_place

    return first_value(event.get("host"), event.get("organization"), source)


def normalize_event(event: Dict[str, Any], event_id: int | None = None) -> Dict[str, Any]:
    source = infer_source(event)
    state = first_value(event.get("state"), event.get("status")) or "알수없음"
    normalized = {
        "title": first_value(event.get("title")),
        "period": normalize_period(first_value(event.get("period"), event.get("date"), event.get("datetime"))),
        "place": infer_place(event, source),
        "host": first_value(event.get("host"), event.get("organization"), source),
        "source": source,
        "category": first_value(event.get("category")),
        "state": state,
        "cost": first_value(event.get("cost")),
        "audience": first_value(event.get("audience")),
        "image": first_value(event.get("image")),
        "url": first_value(event.get("url"), event.get("link")),
        "description": clean_multiline(first_value(event.get("description"), event.get("deep_data"), event.get("overview"))),
    }

    if event_id is not None:
        normalized["id"] = event_id
    elif "id" in event:
        normalized["id"] = event.get("id")

    for coord_key in ("lat", "lng"):
        if coord_key in event:
            normalized[coord_key] = event.get(coord_key)

    for key, value in event.items():
        if key not in normalized and key not in ALIAS_KEYS:
            normalized[key] = value

    return normalized


def normalize_events(events: Iterable[Dict[str, Any]], with_ids: bool = False) -> List[Dict[str, Any]]:
    return [
        normalize_event(event, index if with_ids else None)
        for index, event in enumerate(events)
        if isinstance(event, dict)
    ]


def event_signature(events: Iterable[Dict[str, Any]]) -> str:
    payload = [
        {
            "title": event.get("title", ""),
            "period": event.get("period", ""),
            "place": event.get("place", ""),
            "host": event.get("host", ""),
            "state": event.get("state", ""),
            "description": event.get("description", ""),
        }
        for event in events
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
