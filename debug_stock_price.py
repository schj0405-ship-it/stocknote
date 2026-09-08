"""
1-7단계 진단용 스크립트입니다. (2탄)
stock_price.py의 get_current_price 함수는 에러가 나도 조용히 None을 돌려주게 만들어놔서,
정확히 어디서 왜 실패하는지가 안 보입니다. 이 스크립트는 에러를 숨기지 않고 그대로 보여줍니다.
문제 원인을 확인한 뒤에는 지워도 되는 파일입니다.
"""
import pandas as pd
import requests

stock_code = "005930"  # 삼성전자
url = f"https://finance.naver.com/item/sise_day.naver?code={stock_code}&page=1"
headers = {"User-Agent": "Mozilla/5.0"}

print("[1] 페이지 요청")
response = requests.get(url, headers=headers, timeout=5)
print("상태 코드(200이면 정상):", response.status_code)

response.encoding = "euc-kr"
print("\n[2] pd.read_html로 표 읽기 시도")
tables = pd.read_html(response.text)  # 여기서 에러가 나면 아래에 그대로 출력됩니다
print(f"찾은 표 개수: {len(tables)}")

# 출력이 너무 길어지지 않도록, 각 표의 크기(행,열)와 컬럼 이름만 짧게 보여줍니다.
for i, t in enumerate(tables):
    print(f"표 {i}: 크기={t.shape}, 컬럼={list(t.columns)}")

print("\n[3] 그중 '종가'라는 컬럼이 있는 표를 찾아서 위 3줄만 출력")
found = False
for i, t in enumerate(tables):
    if "종가" in list(t.columns):
        found = True
        print(f"\n표 {i}에서 '종가' 컬럼 발견:")
        print(t.dropna().head(3))
        break

if not found:
    print("'종가'라는 이름의 컬럼을 가진 표를 못 찾았습니다.")
