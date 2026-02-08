import requests
import xml.etree.ElementTree as ET
import json
from requests.exceptions import RequestException # 추가

def get_exhibition_data(service_key, num_of_rows=10, page_no=1):
    url = f"https://api.kcisa.kr/openapi/API_CCA_145/request?serviceKey={service_key}&numOfRows={num_of_rows}&pageNo={page_no}"
    try:
        # 타임아웃을 30초 정도로 조절하고, 실패 시 에러를 던지도록 함
        response = requests.get(url, timeout=30)
        response.raise_for_status() # HTTP 에러 체크
        return ET.fromstring(response.content)
    except RequestException as e:
        print(f"문화포털 API 연결 실패: {e}")
        return None

def xml_to_dict(element):
    if element is None:
        return None
    result = {}
    for child in element:
        child_data = xml_to_dict(child)
        if child.tag in result:
            if type(result[child.tag]) is list:
                result[child.tag].append(child_data if child_data else child.text)
            else:
                result[child.tag] = [result[child.tag], child_data if child_data else child.text]
        else:
            if len(child) == 0:
                result[child.tag] = child.text
            else:
                result[child.tag] = child_data
    return result


