import os
import re
from datetime import datetime
from html import unescape
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup


__all__ = ["scrape_seoul_events_page"]

BASE_URL = "http://openapi.seoul.go.kr:8088"
APP_TIMEZONE = ZoneInfo("Asia/Seoul")


def get_service_key():
    key = (os.getenv("SEOUL_OPEN_API_KEY") or os.getenv("SEOUL_API_KEY") or "").strip()
    return unquote(key) if "%" in key else key


def clean_text(value):
    if value is None:
        return ""
    raw = unescape(str(value))
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True) if "<" in raw and ">" in raw else raw
    return re.sub(r"\s+", " ", text).strip()


def clean_url(*values):
    for value in values:
        url = clean_text(value)
        if url.startswith("//"):
            return f"https:{url}"
        if url.startswith(("http://", "https://")):
            return url
    return ""


def parse_date(value):
    text = clean_text(value)
    match = re.search(r"\d{4}-\d{1,2}-\d{1,2}|\d{8}", text)
    if not match:
        return ""
    raw = match.group(0)
    if "-" in raw:
        year, month, day = raw.split("-")
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"


def parse_iso_date(value):
    date_text = parse_date(value)
    if not date_text:
        return None
    try:
        return datetime.strptime(date_text, "%Y-%m-%d").date()
    except ValueError:
        return None


def make_period(row):
    start = parse_date(row.get("STRTDATE"))
    end = parse_date(row.get("END_DATE"))
    if not start or not end:
        date_text = clean_text(row.get("DATE"))
        parts = re.split(r"\s*~\s*", date_text)
        if parts:
            start = start or parse_date(parts[0])
            end = end or parse_date(parts[-1])
    if start and end:
        return f"{start}~{end}"
    return start or end


def parse_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def event_state(start, end):
    today = datetime.now(APP_TIMEZONE).date()
    if not start or not end:
        return "알수없음"
    if today < start:
        return "진행예정"
    if start <= today <= end:
        return "진행중"
    return "종료"


def is_active_current_year(row):
    today = datetime.now(APP_TIMEZONE).date()
    year_start = today.replace(month=1, day=1)
    year_end = today.replace(month=12, day=31)
    start = parse_iso_date(row.get("STRTDATE") or row.get("DATE"))
    end = parse_iso_date(row.get("END_DATE")) or start

    if not start or not end:
        return False
    return end >= today and start <= year_end and end >= year_start


def row_to_event(row):
    start = parse_iso_date(row.get("STRTDATE") or row.get("DATE"))
    end = parse_iso_date(row.get("END_DATE")) or start

    description_parts = []
    for label, key in [
        ("시간", "PRO_TIME"),
        ("대상", "USE_TRGT"),
        ("문의", "INQUIRY"),
        ("프로그램", "PROGRAM"),
        ("기타", "ETC_DESC"),
    ]:
        text = clean_text(row.get(key))
        if text:
            description_parts.append(f"{label}: {text}")

    gu_name = clean_text(row.get("GUNAME"))
    place = clean_text(row.get("PLACE"))
    if gu_name and place and gu_name not in place:
        place = f"서울 {gu_name} {place}"

    return {
        "title": clean_text(row.get("TITLE")),
        "period": make_period(row),
        "place": place,
        "host": clean_text(row.get("ORG_NAME")) or "서울문화포털",
        "source": "서울 열린데이터광장",
        "category": clean_text(row.get("CODENAME") or row.get("THEMECODE")),
        "state": event_state(start, end),
        "cost": clean_text(row.get("USE_FEE")),
        "audience": clean_text(row.get("USE_TRGT")),
        "image": clean_url(row.get("MAIN_IMG")),
        "url": clean_url(row.get("HMPG_ADDR"), row.get("ORG_LINK")),
        "description": "\n".join(description_parts),
        "lat": parse_float(row.get("LAT")),
        "lng": parse_float(row.get("LOT")),
        "source_id": clean_text(row.get("HMPG_ADDR")),
    }


def request_seoul_openapi(service_key, start_index, end_index):
    try:
        response = requests.get(
            f"{BASE_URL}/{service_key}/json/culturalEventInfo/{start_index}/{end_index}/",
            headers={"User-Agent": "KAIEF event scraper"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("culturalEventInfo", {}).get("RESULT", {})
        if result and result.get("CODE") not in {"INFO-000", None}:
            print(f"서울 열린데이터 API 오류: {result.get('MESSAGE')}")
            return None
        return payload
    except Exception as e:
        print(f"서울 열린데이터 API 요청 실패({start_index}-{end_index}): {e}")
        return None


def scrape_seoul_events_page(page_size=100, max_pages=10):
    service_key = get_service_key()
    if not service_key:
        print("서울 열린데이터 API 키가 없어 건너뜁니다. (.env에 SEOUL_OPEN_API_KEY 설정)")
        return []

    print("서울 열린데이터 문화행사 데이터 수집 시작...")
    events = []

    for page in range(max_pages):
        start_index = page * page_size + 1
        end_index = start_index + page_size - 1
        payload = request_seoul_openapi(service_key, start_index, end_index)
        if not payload:
            break

        body = payload.get("culturalEventInfo") or {}
        rows = body.get("row") or []
        if isinstance(rows, dict):
            rows = [rows]
        if not rows:
            break

        for row in rows:
            if not isinstance(row, dict) or not is_active_current_year(row):
                continue
            event = row_to_event(row)
            if event["title"]:
                events.append(event)

        total = int(body.get("list_total_count") or 0)
        if end_index >= total or len(rows) < page_size:
            break

    print(f"서울 열린데이터 수집 완료: 총 {len(events)}건")
    return events
