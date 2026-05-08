import re
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests


__all__ = ["scrape_ggcf_programs_page"]

BASE_URL = "https://www.ggcf.kr"
CMS_BASE_URL = "https://cms.ggcf.kr"
APP_TIMEZONE = ZoneInfo("Asia/Seoul")

ENDPOINTS = [
    ("events", "행사"),
    ("exhibitions", "전시"),
    ("edus", "교육"),
]


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


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


def make_period(start, end):
    start_date = parse_date(start)
    end_date = parse_date(end)
    if start_date and end_date:
        return f"{start_date}~{end_date}"
    return start_date or end_date


def is_active_current_year(item):
    state = clean_text(item.get("progress"))
    if state in {"종료", "마감"}:
        return False

    today = datetime.now(APP_TIMEZONE).date()
    year_start = today.replace(month=1, day=1)
    year_end = today.replace(month=12, day=31)
    start_date = parse_iso_date(item.get("progress_start"))
    end_date = parse_iso_date(item.get("progress_finish")) or start_date

    if not start_date or not end_date:
        return state in {"진행중", "진행예정", "예정"}
    return end_date >= today and start_date <= year_end and end_date >= year_start


def build_image_url(file_url):
    path = clean_text(file_url)
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        return path
    return urljoin(CMS_BASE_URL, path)


def item_to_event(item, category):
    href = clean_text(item.get("href"))
    if href.startswith("//"):
        href = f"https:{href}"

    application_period = make_period(item.get("application_start"), item.get("application_finish"))
    description_parts = [clean_text(item.get("summary"))]
    if application_period:
        description_parts.append(f"접수기간: {application_period}")

    return {
        "title": clean_text(item.get("title")),
        "period": make_period(item.get("progress_start"), item.get("progress_finish")),
        "place": clean_text(item.get("place")),
        "host": clean_text(item.get("affiliationName")) or "경기문화재단",
        "source": "경기문화재단",
        "category": category,
        "state": clean_text(item.get("progress")) or "알수없음",
        "image": build_image_url(item.get("fileUrl")),
        "url": href,
        "description": "\n".join(part for part in description_parts if part and part != "-"),
        "source_id": f"ggcf:{category}:{item.get('id')}",
        "affiliation_code": clean_text(item.get("affiliation_code")),
    }


def request_ggcf(endpoint, page, year):
    try:
        response = requests.get(
            f"{BASE_URL}/api/{endpoint}",
            params={"page": page, "year": year},
            headers={"Accept": "application/json", "User-Agent": "KAIEF event scraper"},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"경기문화재단 API 요청 실패({endpoint}, page={page}): {e}")
        return None


def scrape_ggcf_programs_page(max_pages_per_endpoint=20):
    print("경기문화재단 행사/전시/교육 데이터 수집 시작...")
    current_year = datetime.now(APP_TIMEZONE).year
    events = []

    for endpoint, category in ENDPOINTS:
        page = 1
        while page <= max_pages_per_endpoint:
            payload = request_ggcf(endpoint, page, current_year)
            if not payload:
                break

            items = payload.get("list") or []
            if not isinstance(items, list) or not items:
                break

            for item in items:
                if not isinstance(item, dict) or not is_active_current_year(item):
                    continue
                event = item_to_event(item, category)
                if event["title"]:
                    events.append(event)

            last_page = int(payload.get("last_page") or page)
            if page >= last_page:
                break
            page += 1

    print(f"경기문화재단 수집 완료: 총 {len(events)}건")
    return events
