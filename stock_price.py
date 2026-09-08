"""
네이버 금융에서 주가를 가져오는 파일입니다.

솔직히 말씀드릴 부분: OpenDART와 달리 네이버 금융은 "이렇게 요청하면
이런 데이터를 준다"고 공식적으로 정해둔 API가 아닙니다. 사람이 눈으로
보는 웹페이지의 표를 프로그램이 대신 읽어오는 방식(크롤링)이라,
네이버가 페이지 구조를 바꾸면 이 코드도 같이 고쳐야 할 수 있습니다.
그래서 이 파일은 실행해보고 결과를 같이 확인한 뒤에 다듬는 게 안전합니다.
"""
from io import StringIO

import pandas as pd
import requests


def get_current_price(stock_code):
    """
    네이버 금융의 '일별 시세' 페이지에서 가장 최근 종가(직전 거래일 마감 가격)를
    가져옵니다.

    stock_code: 종목코드 (6자리, 예: 삼성전자 "005930")
    반환값: 정수(원 단위) 또는 못 가져왔으면 None
    """
    url = f"https://finance.naver.com/item/sise_day.naver?code={stock_code}&page=1"
    headers = {"User-Agent": "Mozilla/5.0"}  # 프로그램이 아니라 웹 브라우저인 것처럼 알려주는 표시

    try:
        response = requests.get(url, headers=headers, timeout=5)
        response.encoding = "euc-kr"  # 네이버 금융 페이지가 쓰는 글자 인코딩

        # pandas 최신 버전은 문자열을 그대로 주면 "파일 경로/URL인 줄 알고" 찾다가
        # 에러를 냅니다. StringIO로 감싸서 "이건 파일 경로가 아니라 텍스트 내용이야"라고
        # 알려줘야 합니다.
        tables = pd.read_html(StringIO(response.text))
        df = tables[0].dropna()

        if df.empty:
            return None

        최근종가 = df.iloc[0]["종가"]
        return int(최근종가)
    except Exception:
        # 페이지 구조가 예상과 다르거나 네트워크 문제가 있으면 None을 돌려줍니다.
        return None


if __name__ == "__main__":
    종목코드 = "005930"  # 삼성전자
    가격 = get_current_price(종목코드)
    print(f"종목코드 {종목코드}의 최근 종가:", 가격)
