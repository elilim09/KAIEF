import subprocess
import time
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

# 소스: 맹산환경생태학습원
# 링크: https://mpark.seongnam.go.kr:10003

__all__ = ["scrape_mpark_events_page"]

# [ADDED] 경로 에러 방지를 위해 날짜 체크 로직 내장
def is_within_month(date_str):
    """등록일자가 현재로부터 1개월 이내인지 확인"""
    try:
        if not date_str: return False
        # 날짜 형식 파싱 (YYYY-MM-DD)
        target_date = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
        one_month_ago = datetime.now().date() - timedelta(days=30)
        return target_date >= one_month_ago
    except Exception:
        return True # 파싱 에러 시 데이터 누락 방지를 위해 포함

def deep_scrape_mpark_event_page(link):
    event_data = ""
    try:
        # -L 옵션 추가: 리다이렉트 대응
        result = subprocess.run(
            ["curl", "-L", link], capture_output=True, check=True, timeout=30)
        try:
            html_content = result.stdout.decode('utf-8')
        except UnicodeDecodeError:
            html_content = result.stdout.decode('euc-kr', errors='ignore')

        soup = BeautifulSoup(html_content, "html.parser")
        content_div = soup.find("div", class_="bbsContents")
        if content_div:
            event_data = content_div.get_text(separator="\n", strip=True)
    except Exception as e:
        print(f"상세 페이지 오류 ({link}): {e}")
    return event_data


def scrape_mpark_events_page():
    base_url = "https://mpark.seongnam.go.kr:10003"
    events_on_site = []
    page = 1
    print("맹산환경생태학습원 스크레이핑 중...")
    
    while page <= 5:
        list_url = f"{base_url}/main.php?menugrp=040100&master=bbs&act=list&master_sid=3&Page={page}"
        try:
            result = subprocess.run(
                ["curl", "-L", list_url], capture_output=True, check=True, timeout=30)
            try:
                html_content = result.stdout.decode('utf-8')
            except UnicodeDecodeError:
                html_content = result.stdout.decode('euc-kr', errors='ignore')

            soup = BeautifulSoup(html_content, "html.parser")
            notice_list = soup.select("div.bbsContent table tr")

            if len(notice_list) <= 1:
                break

            found_count = 0
            for notice in notice_list:
                if not notice.find_all('td'):
                    continue

                title_cell = notice.find("td", class_="text-left")
                if not title_cell:
                    continue

                title = title_cell.get_text(strip=True)
                link_tag = title_cell.find('a')
                relative_link = link_tag['href'] if link_tag else None

                if not relative_link:
                    continue

                absolute_link = f"{base_url}/{relative_link}"

                cells = notice.find_all("td")
                # 날짜 추출
                date_str = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                found_count += 1
                
                # [FIXED] 내장된 날짜 체크 함수 사용
                if not is_within_month(date_str):
                    continue
                
                # 데이터 형식을 챗봇 서버 사양에 맞춤
                events_on_site.append({
                    "title": title,
                    "url": absolute_link,       # link -> url
                    "period": date_str,         # date -> period
                    "place": "맹산환경생태학습원", # 좌표 검색을 위한 명확한 장소명
                    "source": "맹산환경생태학습원",
                    "category": "환경",
                    "state": "진행중",
                    "description": deep_scrape_mpark_event_page(absolute_link)
                })

            print(f"{page}페이지에서 {found_count}개의 이벤트를 찾았습니다.")
            if found_count == 0:
                break
            page += 1
            time.sleep(0.1)

        except Exception as e:
            print(f"맹산 스크래핑 오류: {e}")
            break

    print(f"맹산환경생태학습원에서 총 {len(events_on_site)}개의 이벤트를 찾았습니다.")
    return events_on_site