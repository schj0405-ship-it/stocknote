"""
진단용 임시 스크립트입니다. 삼성전자 2025년 반기 데이터에서
"순이익"이나 "매출액"이 들어간 모든 항목의 원본 데이터를 그대로 출력합니다.
문제 원인을 정확히 확인한 뒤에는 지워도 되는 파일입니다.
"""
import requests
from config import DART_API_KEY

corp_code = "00126380"  # 삼성전자
url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
params = {
    "crtfc_key": DART_API_KEY,
    "corp_code": corp_code,
    "bsns_year": "2025",
    "reprt_code": "11012",  # 반기
    "fs_div": "CFS",
}

response = requests.get(url, params=params)
data = response.json()

if data.get("status") != "000":
    print("API 오류:", data)
else:
    for item in data["list"]:
        name = item.get("account_nm", "")
        if "순이익" in name or "매출액" in name:
            print("-" * 60)
            print("sj_div            :", item.get("sj_div"))
            print("sj_nm             :", item.get("sj_nm"))
            print("account_nm        :", item.get("account_nm"))
            print("account_detail    :", item.get("account_detail"))
            print("thstrm_nm         :", item.get("thstrm_nm"))
            print("thstrm_amount     :", item.get("thstrm_amount"))
            print("thstrm_add_amount :", item.get("thstrm_add_amount"))
