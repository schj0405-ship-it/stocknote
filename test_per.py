"""
1-7단계 진단용 스크립트입니다.
PER 계산에 필요한 두 가지 재료(유통주식수, 현재 주가)를 각각 따로 테스트합니다.
문제 없이 잘 나오는지 확인한 뒤에는 지워도 되는 파일입니다.
"""
from get_financial_data import find_corp_code, find_stock_code, get_shares_outstanding
from stock_price import get_current_price

회사이름 = "삼성전자"

corp_code = find_corp_code(회사이름)
stock_code = find_stock_code(회사이름)
print("corp_code(고유번호):", corp_code)
print("stock_code(종목코드):", stock_code)

print("-" * 40)
print("[1] OpenDART 유통주식수 조회 (반기 기준)")
shares = get_shares_outstanding(corp_code, "2025", "11012")
print("유통주식수:", shares)

print("-" * 40)
print("[2] 네이버 금융 현재가 조회")
if stock_code is None:
    print("stock_code를 못 찾아서 건너뜁니다. corp_codes.csv에 stock_code 컬럼이 있는지 확인해주세요.")
else:
    price = get_current_price(stock_code)
    print("현재가:", price)
