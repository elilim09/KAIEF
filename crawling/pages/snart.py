import subprocess
import time
from datetime import date, timedelta
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# 소스: 성남아트센터
# 링크: https://www.snart.or.kr/

__all__ = ["scrape_snart_events_page"]

def scrape_snart_events_page():
    base_url = "https://www.snart.or.kr"
    events_on_site = []
    today = date.today()

    print("성남아트센터 데이터 수집 시작...")
    
    # 1: 공연, 2: 전시
    for type_id in [1, 2]:
        # 너무 많은 날짜 호출은 서버 차단의 위험이 있으므로, 
        # 주요 일정을 포함하는 최근 15일 정도로 범위를 조정하거나 
        # 대표 목록 페이지를 긁는 것이 안전합니다.
        for i in range(15): 
            current_date = today + timedelta(days=i)
            date_str = current_date.strftime("%Y%m%d")
            
            # 실제 성남아트센터 비동기 호출 주소
            api_url = f"{base_url}/web/simpleShowsMainReNew?date={date_str}&type={type_id}"
            
            try:
                # curl 명령어로 데이터 가져오기
                result = subprocess.run(
                    ["curl", "-s", "-L", api_url], 
                    capture_output=True, 
                    check=True, 
                    timeout=20
                )
                
                # [중요] JSON 변환 없이 바로 HTML로 인식
                html_content = result.stdout.decode('utf-8', errors='ignore').strip()
                
                if not html_content or "데이터가 없습니다" in html_content:
                    continue

                soup = BeautifulSoup(html_content, "html.parser")
                # 성남아트센터의 리스트 아이템 태그 확인
                items = soup.select("li.list, div.item, .show_item") 

                if not items:
                    continue

                for item in items:
                    # 제목 추출
                    title_node = item.select_one(".title, strong, h3")
                    if not title_node: continue
                    title = title_node.get_text(strip=True)

                    # 날짜 및 장소 추출
                    date_val = item.select_one(".date").get_text(strip=True) if item.select_one(".date") else ""
                    place_val = item.select_one(".place").get_text(strip=True) if item.select_one(".place") else "성남아트센터"

                    # 상세 링크 및 이미지
                    link_node = item.find("a")
                    link = urljoin(base_url, link_node['href']) if link_node and 'href' in link_node.attrs else base_url
                    
                    img_node = item.find("img")
                    img = urljoin(base_url, img_node['src']) if img_node and 'src' in img_node.attrs else ""

                    # 중복 제거 (제목이 같으면 스킵)
                    if any(e['title'] == title for e in events_on_site):
                        continue

                    events_on_site.append({
                        "title": title,
                        "url": link,
                        "period": date_val,
                        "place": f"성남아트센터 {place_val}",
                        "category": "공연" if type_id == 1 else "전시",
                        "image": img,
                        "source": "성남아트센터",
                        "state": "진행중"
                    })
                
                # 서버 부하 방지
                time.sleep(0.1)

            except Exception as e:
                # 개별 날짜 오류는 무시하고 진행
                continue

    print(f"성남아트센터 수집 완료: 총 {len(events_on_site)}건")
    return events_on_site