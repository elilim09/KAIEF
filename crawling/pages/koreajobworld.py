import subprocess
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

# 소스: 한국잡월드
# 링크: https://www.koreajobworld.or.kr/

__all__ = ["scrape_koreajobworld_events_page"]

# [ADDED] 외부 utils 모듈 대신 파일 내에 직접 정의하여 경로 오류 방지
def extract_http_url_from_js(text):
    """JavaScript 코드 내에서 HTTP URL 추출 (패키지 의존성 제거)"""
    if not text:
        return None
    match = re.search(r"(https?://[^\s'\"]+)", text)
    return match.group(1) if match else None

def deep_scrape_koreajobworld_page(link):
    event_data = ""
    if not link or link.startswith("javascript:"):
        return ""
    try:
        # -L 옵션으로 리다이렉트 대응
        result = subprocess.run(
            ["curl", "-L", link], capture_output=True, check=True, timeout=30)
        try:
            html_content = result.stdout.decode('utf-8', errors='ignore')
        except UnicodeDecodeError:
            html_content = result.stdout.decode('euc-kr', errors='ignore')

        soup = BeautifulSoup(html_content, "html.parser")
        
        # 본문 영역 후보군 탐색
        candidates = [
            ("div", "board-view"), ("div", "view_con"), ("div", "bbs_view"),
            ("div", "contents"), ("div", "content")
        ]
        for name, cls in candidates:
            node = soup.find(name, class_=cls)
            if node:
                event_data = node.get_text(separator="\n", strip=True)
                if event_data: break

    except Exception as e:
        print(f"상세 페이지 오류 ({link}): {e}")
    return event_data

def scrape_koreajobworld_events_page(max_news_pages=2): # 페이지 수는 조절 가능
    sources = []
    # 공지사항 리스트
    news_base = "https://www.koreajobworld.or.kr/boardList.do?mid=42&menuId=55&bid=1&site=10&portalMenuNo=39"
    
    print("한국잡월드 크롤링 시작...")
    
    # 1. 새소식 및 공지사항 섹션
    for page in range(1, max_news_pages + 1):
        list_url = f"{news_base}&pageIndex={page}"
        try:
            res = subprocess.run(["curl", "-L", list_url], capture_output=True, check=True, timeout=30)
            html = res.stdout.decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html, "html.parser")

            rows = soup.select("table tbody tr")
            if not rows: break

            for tr in rows:
                tds = tr.find_all("td")
                if len(tds) < 2: continue

                title_cell = tr.find("td", class_="text-left") or tds[1]
                a = title_cell.find("a")
                title = a.get_text(strip=True) if a else title_cell.get_text(strip=True)

                # 링크 추출
                raw_href = a.get("href", "") if a else ""
                raw_onclick = a.get("onclick", "") if a else ""
                js_url = extract_http_url_from_js(raw_href) or extract_http_url_from_js(raw_onclick)
                final_link = js_url if js_url else urljoin(list_url, raw_href)

                # 날짜 추출
                date_text = ""
                for td in reversed(tds):
                    txt = td.get_text(strip=True)
                    if re.search(r"\d{4}[.\-]\d{1,2}[.\-]\d{1,2}", txt):
                        date_text = txt.replace(".", "-") # 형식 통일
                        break

                sources.append({
                    "title": title,
                    "url": final_link,          # 필드명 통일
                    "period": date_text,        # 필드명 통일
                    "place": "한국잡월드",       # 장소 명시
                    "category": "새소식&공지",
                    "source": "한국잡월드",
                    "state": "진행중"
                })
        except Exception as e:
            print(f"목록 페이지 오류 p{page}: {e}")

    # 2. 이벤트/공모전 섹션 추가
    event_url = "https://www.koreajobworld.or.kr/event/showList.do?site=10&searchEvent=04&portalMenuNo=247"
    try:
        res = subprocess.run(["curl", "-L", event_url], capture_output=True, check=True, timeout=30)
        soup = BeautifulSoup(res.stdout.decode('utf-8', errors='ignore'), "html.parser")
        # 카드형 리스트 탐색 (사이트 구조에 따라 유동적)
        items = soup.select("ul.program_list li, div.item")
        for item in items:
            title_node = item.select_one(".title, dt, strong")
            if not title_node: continue
            
            title = title_node.get_text(strip=True)
            # 날짜 및 장소 파싱 (텍스트 기반)
            item_text = item.get_text()
            date_m = re.search(r"(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})", item_text)
            date_str = date_m.group(1).replace(".", "-") if date_m else ""
            
            sources.append({
                "title": title,
                "url": event_url,
                "period": date_str,
                "place": "한국잡월드",
                "category": "이벤트",
                "source": "한국잡월드",
                "state": "진행중"
            })
    except Exception as e:
        print(f"이벤트 페이지 오류: {e}")

    print(f"한국잡월드 총 {len(sources)}건 수집 완료.")
    return sources