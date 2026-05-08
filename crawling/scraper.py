import json
import os
import sys
import requests
import time
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)
# 기존 스크래퍼 임포트
from pages.seongnam import scrape_seongnam_events_page
from pages.snyouth import scrape_snyouth_events_page
from pages.snart import scrape_snart_events_page
from pages.mpark import scrape_mpark_events_page
from pages.ppark import scrape_ppark_events_page
from pages.koreajobworld import scrape_koreajobworld_events_page
from pages.seongnamculture import scrape_seongnamculture_events_page
from pages.pangyomeseum import scrape_pangyomuseum_events_page
from pages.pangyowelfare import scrape_pangyowelfare_events_page
from pages.pangyonoin import scrape_pangyonoin_events_page
from pages.culture import get_exhibition_data, xml_to_dict
from pages.ggcf import scrape_ggcf_programs_page
from pages.seoul import scrape_seoul_events_page
from pages.tourapi import scrape_tourapi_events_page
from event_normalizer import normalize_events

# .env 파일에서 KAKAO_API_KEY 로드
load_dotenv()
KAKAO_API_KEY = os.getenv("KAKAO_API_KEY")
APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Seoul"))
KAKAO_REQUEST_DELAY = float(os.getenv("KAKAO_REQUEST_DELAY", "0.03"))

# ==========================================
# 1. 좌표 변환 유틸리티 및 수동 데이터
# ==========================================
MANUAL_MAPPING = {
    "판교환경생태학습원": (37.4025, 127.1001),
    "성남문화원": (37.4632, 127.1472),
    "성남문화의집": (37.4421, 127.1485),
    "수내동고가": (37.3781, 127.1234),
    "성남아트센터": (37.4022, 127.1287),
    "예술의전당": (37.4785, 127.0118),
    "국립중앙박물관": (37.5238, 126.9790)
}

def get_kakao_coordinates(query):
    """카카오 키워드 검색 API를 이용해 장소의 좌표 추출"""
    if not KAKAO_API_KEY or not query or len(query.strip()) < 2:
        return None, None
    
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_API_KEY}"}
    params = {"query": query}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data['documents']:
                return float(data['documents'][0]['y']), float(data['documents'][0]['x'])
    except Exception as e:
        print(f"API 호출 오류 ({query}): {e}")
    
    return None, None


def parse_coord(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_period_dates(period):
    if not period:
        return None, None

    matches = re.findall(r"\d{4}-\d{1,2}-\d{1,2}|\d{8}", str(period))
    dates = []
    for value in matches[:2]:
        try:
            if "-" in value:
                dates.append(datetime.strptime(value, "%Y-%m-%d").date())
            else:
                dates.append(datetime.strptime(value, "%Y%m%d").date())
        except ValueError:
            continue

    if not dates:
        return None, None
    if len(dates) == 1:
        return dates[0], dates[0]
    return dates[0], dates[1]


def is_active_current_year_event(event):
    state = str(event.get("state") or "").strip()
    if state in {"종료", "마감", "끝남", "ended", "closed", "finished"}:
        return False

    start_date, end_date = parse_period_dates(event.get("period") or "")
    if not start_date or not end_date:
        return False

    today = datetime.now(APP_TIMEZONE).date()
    year_start = today.replace(month=1, day=1)
    year_end = today.replace(month=12, day=31)
    return end_date >= today and start_date <= year_end and end_date >= year_start


def dedupe_events(events):
    deduped = []
    seen = set()

    for event in events:
        title = re.sub(r"\s+", " ", str(event.get("title") or "")).strip().lower()
        period = re.sub(r"\s+", "", str(event.get("period") or "")).strip()
        place = re.sub(r"\s+", " ", str(event.get("place") or "")).strip().lower()
        url = str(event.get("url") or "").strip()
        source_id = str(event.get("source_id") or event.get("content_id") or "").strip()

        key = (title, period, place) if title and period else (url or source_id or title, period, place)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(event)

    return deduped


def build_coordinate_queries(host, place):
    ignored = {"기타", "문화포털", "한국관광공사", "서울문화포털", "상세 장소 확인 필요", "기관 정보 없음"}
    host_text = re.sub(r"\s+", " ", str(host or "")).strip()
    place_text = re.sub(r"\s+", " ", str(place or "")).strip()
    has_host = len(host_text) >= 2 and host_text not in ignored
    has_place = len(place_text) >= 2 and place_text not in ignored
    queries = []

    if has_place:
        queries.append(place_text)
    if has_host and has_place:
        queries.append(f"{host_text} {place_text}")
    if has_host:
        queries.append(host_text)

    return queries

# ==========================================
# 2. 문화포털 API 스크래퍼
def scrape_culture_events_page():
    print("culture.go.kr API를 스크래핑하는 중...")
    service_key = "79058de8-e03d-4a28-af3d-d9f39db0d5e8"
    
    try:
        # 데이터 양이 많으면 서버가 힘들어할 수 있으니 100개 -> 50개 정도로 줄여보는 것도 방법입니다.
        xml_data = get_exhibition_data(service_key, num_of_rows=50) 
        if xml_data is None:
            print("문화포털 API로부터 데이터를 받지 못했습니다. (건너뜀)")
            return []

        data = xml_to_dict(xml_data)
        events = []
        if data and 'body' in data and 'items' in data['body'] and 'item' in data['body']['items']:
            items = data['body']['items']['item']
            if isinstance(items, dict): items = [items]
            
            for item in items:
                event = {
                    'title': item.get('TITLE'),
                    'period': item.get('PERIOD'),
                    'place': item.get('EVENT_SITE'),
                    'cost': item.get('CHARGE'),
                    'image': item.get('IMAGE_OBJECT'),
                    'url': item.get('URL'),
                    'host': item.get('CNTC_INSTT_NM'),
                    'source': '문화포털',
                    'state': '진행중'
                }
                events.append(event)
        return events
    except Exception as e:
        print(f"문화포털 파싱 중 알 수 없는 오류 발생: {e}")
        return []
# ==========================================
# 3. 메인 실행 제어 로직
# ==========================================
def main():
    raw_events = []

    # 데이터 수집
    print("--- 각 사이트 데이터 수집 시작 ---")
    raw_events.extend(scrape_culture_events_page())
    raw_events.extend(scrape_tourapi_events_page(num_rows=100, max_pages=5, detail_limit=80))
    raw_events.extend(scrape_seoul_events_page())
    raw_events.extend(scrape_ggcf_programs_page())
    
    page = 1
    while True:
        events = scrape_seongnam_events_page(page)
        if not events: break
        raw_events.extend(events)
        if not any(e['state'] in ['진행중', '진행예정'] for e in events): break
        page += 1

    raw_events.extend(scrape_snyouth_events_page(1))
    raw_events.extend(scrape_mpark_events_page())
    raw_events.extend(scrape_snart_events_page())
    raw_events.extend(scrape_ppark_events_page())
    raw_events.extend(scrape_koreajobworld_events_page())
    raw_events.extend(scrape_seongnamculture_events_page())
    raw_events.extend(scrape_pangyomuseum_events_page())
    raw_events.extend(scrape_pangyowelfare_events_page())
    raw_events.extend(scrape_pangyonoin_events_page())

    # ------------------------------------------
    # 데이터 필터링 (공지/마감 제거)
    # ------------------------------------------
    exclude_keywords = ['[공지]', '[마감]', '[채용]', '<긴급', '안내', '휴관', '인터넷장애']
    normalized_events = normalize_events(raw_events)
    filtered_events = [
        e for e in normalized_events
        if (
            e.get('title')
            and not any(k in e['title'] for k in exclude_keywords)
            and is_active_current_year_event(e)
        )
    ]
    all_events = dedupe_events(filtered_events)
    print(f"필터링 완료: {len(raw_events)}개 -> {len(all_events)}개")

    # ------------------------------------------
    # 좌표 추가 및 보정
    # ------------------------------------------
    print(f"\n--- 좌표 변환 시작 ({len(all_events)} 건) ---")
    coordinate_cache = {}
    
    for i, event in enumerate(all_events):
        title = (event.get('title') or "").strip()
        # 장소가 비어있으면 주최측 정보를 기본값으로 사용
        if not event.get('place'):
            if 'pangyomuseum' in event.get('url', ''): event['place'] = "판교박물관"
            elif 'seongnamculture' in event.get('url', ''): event['place'] = "성남문화원"
            else: event['place'] = event.get('host', '')

        place = (event.get('place') or "").strip()
        host = (event.get('host') or "").strip()
        lat = parse_coord(event.get('lat'))
        lng = parse_coord(event.get('lng'))

        # 1. 수동 매핑 사전 확인
        if lat is None or lng is None:
            for key, coords in MANUAL_MAPPING.items():
                if key in title or key in place or key in host:
                    lat, lng = coords
                    break

        # 2. 카카오 API 검색 (수동 매핑 실패 시)
        if lat is None or lng is None:
            # 전략: 장소 -> 호스트+장소 -> 호스트 순서로 시도. 같은 장소는 API를 반복 호출하지 않는다.
            for q in build_coordinate_queries(host, place):
                if q not in coordinate_cache:
                    coordinate_cache[q] = get_kakao_coordinates(q)
                    time.sleep(KAKAO_REQUEST_DELAY)
                lat, lng = coordinate_cache[q]
                if lat is not None and lng is not None:
                    break

        event['lat'] = lat
        event['lng'] = lng

        if lat is None:
            print(f"  [⚠️ 좌표 실패] {title[:25]}...")

        if (i + 1) % 20 == 0:
            print(f"진행 상황: {i + 1}/{len(all_events)} 건 처리 완료...")
        
    # 최종 저장
    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(all_events, f, ensure_ascii=False, indent=4)

    print(f"\n모든 작업 완료! 'events.json' 저장됨.")

if __name__ == "__main__":
    main()
