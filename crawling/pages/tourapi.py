import os
import re
from datetime import date
from html import unescape
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup


__all__ = ["scrape_tourapi_events_page"]

BASE_URL = "https://apis.data.go.kr/B551011/KorService2"
MOBILE_APP = "KAIEF"


def get_service_key():
    key = (
        os.getenv("KTO_TOUR_API_KEY")
        or os.getenv("TOUR_API_KEY")
        or os.getenv("DATA_GO_KR_SERVICE_KEY")
        or ""
    ).strip()
    return unquote(key) if "%" in key else key


def normalize_items(items):
    if not items:
        return []
    if isinstance(items, list):
        return items
    if isinstance(items, dict):
        return [items]
    return []


def get_nested(data, *keys):
    cur = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def request_tourapi(endpoint, params=None):
    service_key = get_service_key()
    if not service_key:
        return None

    merged_params = {
        "serviceKey": service_key,
        "MobileOS": "ETC",
        "MobileApp": MOBILE_APP,
        "_type": "json",
        **(params or {}),
    }
    try:
        res = requests.get(f"{BASE_URL}/{endpoint}", params=merged_params, timeout=15)
        res.raise_for_status()
        payload = res.json()
        header = get_nested(payload, "response", "header") or {}
        if str(header.get("resultCode", "0000")) not in {"0000", "0"}:
            print(f"TourAPI 오류({endpoint}): {header.get('resultMsg')}")
            return None
        return payload
    except Exception as e:
        print(f"TourAPI 요청 실패({endpoint}): {e}")
        return None


def extract_text(value):
    if value is None:
        return ""
    text = BeautifulSoup(unescape(str(value)), "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def extract_url(value):
    if not value:
        return ""
    raw = unescape(str(value))
    href_match = re.search(r'href=["\']([^"\']+)["\']', raw, re.IGNORECASE)
    url = href_match.group(1) if href_match else raw
    if "<" in url and ">" in url:
        url = BeautifulSoup(url, "html.parser").get_text("", strip=True)
    url = url.strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith(("http://", "https://")):
        return url
    return ""


def format_date(value):
    text = str(value or "").strip()
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def make_period(start, end):
    start_date = format_date(start)
    end_date = format_date(end)
    if start_date and end_date:
        return f"{start_date}~{end_date}"
    return start_date or end_date


def parse_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def event_state(start, end):
    today = date.today()
    start_text = str(start or "").strip()
    end_text = str(end or "").strip()
    try:
        start_date = date.fromisoformat(format_date(start_text))
        end_date = date.fromisoformat(format_date(end_text or start_text))
    except ValueError:
        return "알수없음"

    if today < start_date:
        return "진행예정"
    if start_date <= today <= end_date:
        return "진행중"
    return "종료"


def fetch_event_details(content_id, content_type_id):
    if not content_id:
        return {}, {}

    common_payload = request_tourapi(
        "detailCommon2",
        {
            "contentId": content_id,
            "contentTypeId": content_type_id or "15",
            "defaultYN": "Y",
            "firstImageYN": "Y",
            "areacodeYN": "Y",
            "catcodeYN": "Y",
            "addrinfoYN": "Y",
            "mapinfoYN": "Y",
            "overviewYN": "Y",
        },
    )
    intro_payload = request_tourapi(
        "detailIntro2",
        {
            "contentId": content_id,
            "contentTypeId": content_type_id or "15",
        },
    )

    common_items = normalize_items(get_nested(common_payload or {}, "response", "body", "items", "item"))
    intro_items = normalize_items(get_nested(intro_payload or {}, "response", "body", "items", "item"))
    return (common_items[0] if common_items else {}), (intro_items[0] if intro_items else {})


def item_to_event(item, details=None, intro=None):
    details = details or {}
    intro = intro or {}

    title = extract_text(item.get("title") or details.get("title"))
    addr1 = extract_text(item.get("addr1") or details.get("addr1"))
    addr2 = extract_text(item.get("addr2") or details.get("addr2"))
    event_place = extract_text(intro.get("eventplace"))
    place = event_place or " ".join(part for part in [addr1, addr2] if part).strip()

    start = item.get("eventstartdate") or intro.get("eventstartdate")
    end = item.get("eventenddate") or intro.get("eventenddate")
    homepage = extract_url(details.get("homepage") or intro.get("eventhomepage"))

    overview = extract_text(details.get("overview"))
    use_time = extract_text(intro.get("usetimefestival"))
    sponsor = extract_text(intro.get("sponsor1") or intro.get("sponsor2"))
    image = item.get("firstimage") or details.get("firstimage") or item.get("firstimage2") or ""

    description_parts = [overview]
    if use_time:
        description_parts.append(f"이용요금: {use_time}")
    description = "\n".join(part for part in description_parts if part)

    return {
        "title": title,
        "period": make_period(start, end),
        "place": place or "상세 장소 확인 필요",
        "host": sponsor or "한국관광공사",
        "source": "한국관광공사 TourAPI",
        "category": "축제/행사",
        "state": event_state(start, end),
        "cost": use_time,
        "image": image,
        "url": homepage,
        "description": description,
        "lat": parse_float(item.get("mapy") or details.get("mapy")),
        "lng": parse_float(item.get("mapx") or details.get("mapx")),
        "content_id": item.get("contentid"),
        "content_type_id": item.get("contenttypeid"),
    }


def scrape_tourapi_events_page(num_rows=50, max_pages=2, detail_limit=40):
    if not get_service_key():
        print("TourAPI 인증키가 없어 건너뜁니다. (.env에 KTO_TOUR_API_KEY 설정)")
        return []

    print("한국관광공사 TourAPI 행사 데이터 수집 시작...")
    today = date.today()
    year_end = date(today.year, 12, 31)
    events = []

    for page_no in range(1, max_pages + 1):
        payload = request_tourapi(
            "searchFestival2",
            {
                "numOfRows": num_rows,
                "pageNo": page_no,
                "arrange": "O",
                "eventStartDate": today.strftime("%Y%m%d"),
                "eventEndDate": year_end.strftime("%Y%m%d"),
            },
        )
        items = normalize_items(get_nested(payload or {}, "response", "body", "items", "item"))
        if not items:
            break

        for item in items:
            details, intro = {}, {}
            if len(events) < detail_limit:
                details, intro = fetch_event_details(item.get("contentid"), item.get("contenttypeid"))
            event = item_to_event(item, details, intro)
            if event["title"]:
                events.append(event)

        if len(items) < num_rows:
            break

    print(f"한국관광공사 TourAPI 수집 완료: 총 {len(events)}건")
    return events
