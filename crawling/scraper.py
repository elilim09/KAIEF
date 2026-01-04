import json
import os
import requests
import time
from datetime import datetime
from dotenv import load_dotenv

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

# .env 파일에서 KAKAO_API_KEY 로드
load_dotenv()
KAKAO_API_KEY = os.getenv("KAKAO_API_KEY")

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

# ==========================================
# 2. 문화포털 API 스크래퍼
# ==========================================
def scrape_culture_events_page():
    print("culture.go.kr API를 스크래핑하는 중...")
    service_key = "79058de8-e03d-4a28-af3d-d9f39db0d5e8"
    xml_data = get_exhibition_data(service_key, num_of_rows=100)
    if xml_data is None:
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
                'state': '진행중'
            }
            events.append(event)
    return events

# ==========================================
# 3. 메인 실행 제어 로직
# ==========================================
def main():
    raw_events = []

    # 데이터 수집
    print("--- 각 사이트 데이터 수집 시작 ---")
    raw_events.extend(scrape_culture_events_page())
    
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
    all_events = [
        e for e in raw_events 
        if e.get('title') and not any(k in e['title'] for k in exclude_keywords)
    ]
    print(f"필터링 완료: {len(raw_events)}개 -> {len(all_events)}개")

    # ------------------------------------------
    # 좌표 추가 및 보정
    # ------------------------------------------
    print(f"\n--- 좌표 변환 시작 ({len(all_events)} 건) ---")
    
    for i, event in enumerate(all_events):
        title = (event.get('title') or "").strip()
        # 장소가 비어있으면 주최측 정보를 기본값으로 사용
        if not event.get('place'):
            if 'pangyomuseum' in event.get('url', ''): event['place'] = "판교박물관"
            elif 'seongnamculture' in event.get('url', ''): event['place'] = "성남문화원"
            else: event['place'] = event.get('host', '')

        place = (event.get('place') or "").strip()
        host = (event.get('host') or "").strip()
        lat, lng = None, None

        # 1. 수동 매핑 사전 확인
        for key, coords in MANUAL_MAPPING.items():
            if key in title or key in place or key in host:
                lat, lng = coords
                break

        # 2. 카카오 API 검색 (수동 매핑 실패 시)
        if lat is None:
            # 전략: 호스트+장소 -> 장소 -> 호스트 순서로 시도
            queries = [f"{host} {place}", place, host]
            for q in queries:
                if len(q) > 1:
                    lat, lng = get_kakao_coordinates(q)
                    if lat: break

        event['lat'] = lat
        event['lng'] = lng

        if lat is None:
            print(f"  [⚠️ 좌표 실패] {title[:25]}...")

        if (i + 1) % 20 == 0:
            print(f"진행 상황: {i + 1}/{len(all_events)} 건 처리 완료...")
        
        time.sleep(0.1)

    # 최종 저장
    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(all_events, f, ensure_ascii=False, indent=4)

    print(f"\n모든 작업 완료! 'events.json' 저장됨.")

if __name__ == "__main__":
    main()