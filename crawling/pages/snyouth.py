import subprocess
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# 소스: 성남시청소년재단
# 링크: https://www.snyouth.or.kr/

__all__ = ["scrape_snyouth_events_page"]

# [ADDED] 외부 utils 모듈 대신 파일 내에 직접 정의하여 경로 오류 방지
def is_within_month(date_str):
    """등록일자가 현재로부터 1개월 이내인지 확인"""
    try:
        if not date_str: return False
        # 날짜 형식 처리 (예: 2024-11-01)
        target_date = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
        one_month_ago = datetime.now().date() - timedelta(days=30)
        return target_date >= one_month_ago
    except Exception:
        return True # 파싱 에러 시 일단 포함

def deep_scrape_snyouth_event_page(link):
    event_data = ""
    if not link: return ""
    try:
        result = subprocess.run(
            ["curl", "-L", link], # -L 옵션 추가 (리다이렉트 대응)
            capture_output=True, check=True, timeout=30
        )
        try:
            html_content = result.stdout.decode('utf-8')
        except UnicodeDecodeError:
            html_content = result.stdout.decode('euc-kr', errors='ignore')

        soup = BeautifulSoup(html_content, "html.parser")
        event_view = soup.find("div", class_="board-view")

        if not event_view:
            return ""

        event_data = event_view.get_text(separator="\n", strip=True)

    except Exception as e:
        print(f"상세 페이지 오류: {e}")

    return event_data

def scrape_snyouth_events_page(page_number):
    url = f"https://www.snyouth.or.kr/fmcs/123?page={page_number}"
    events_on_page = []

    try:
        result = subprocess.run(
            ["curl", "-L", url], capture_output=True, check=True, timeout=30)
        try:
            html_content = result.stdout.decode('utf-8')
        except UnicodeDecodeError:
            html_content = result.stdout.decode('euc-kr', errors='ignore')

        soup = BeautifulSoup(html_content, "html.parser")
        event_list = soup.find("tbody")

        if not event_list:
            return []

        events = event_list.find_all("tr")

        for event in events:
            title_cell = event.find("td", class_="text-left")
            if not title_cell: continue

            title = title_cell.get_text(strip=True)
            link_tag = title_cell.find("a")
            link = link_tag["href"] if link_tag else ""
            
            # 절대 경로 생성
            absolute_link = f"https://www.snyouth.or.kr/fmcs/123{link}" if link else ""

            # 날짜 추출 (5번째 td)
            tds = event.find_all("td")
            date_str = tds[4].get_text(strip=True).replace("등록일자", "") if len(tds) > 4 else ""

            # [FIXED] 외부 utils 대신 내부 함수 사용
            if not is_within_month(date_str):
                continue

            events_on_page.append({
                "title": title,
                "url": absolute_link, # 통합을 위해 'link' -> 'url'로 변경 권장
                "period": date_str,   # 통합을 위해 'date' -> 'period'로 변경 권장
                "place": "성남시청소년재단",
                "source": "성남시청소년재단",
                "state": "진행중"
            })

    except Exception as e:
        print(f"성남청소년재단 스크래핑 오류: {e}")

    return events_on_page