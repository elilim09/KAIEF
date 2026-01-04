import requests
import os
from dotenv import load_dotenv

load_dotenv()

def get_location_coords(query):
    # .env에 저장된 키를 가져오거나 직접 입력
    kakao_api_key = "fdb547ead6f1567f1c5296bb67fe5366"
    
    # 'address' 대신 'keyword'를 사용하면 건물명으로도 검색 가능합니다.
    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {kakao_api_key}"}
    params = {"query": query}

    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            if data['documents']:
                # 가장 정확도가 높은 첫 번째 결과의 좌표 반환
                lat = data['documents'][0]['y']
                lng = data['documents'][0]['x']
                address_name = data['documents'][0]['address_name']
                print(f"[{query}] 검색 성공: {address_name}")
                return float(lat), float(lng)
            else:
                print(f"[{query}] 결과가 없습니다. (키워드 매칭 실패)")
        else:
            print(f"API 에러: {response.status_code}")
    except Exception as e:
        print(f"오류 발생: {e}")
    
    return None, None

# 테스트: 건물 이름으로 검색
lat, lng = get_location_coords("수원시청")
print(f"위도: {lat}, 경도: {lng}")