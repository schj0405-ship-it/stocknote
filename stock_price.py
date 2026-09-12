"""
네이버 금융에서 주가를 가져오는 파일입니다.

솔직히 말씀드릴 부분: OpenDART와 달리 네이버 금융은 "이렇게 요청하면
이런 데이터를 준다"고 공식적으로 정해둔 API가 아닙니다. 사람이 눈으로
보는 웹페이지의 표를 프로그램이 대신 읽어오는 방식(크롤링)이라,
네이버가 페이지 구조를 바꾸면 이 코드도 같이 고쳐야 할 수 있습니다.

[2026-09-11 수정 - 배포 서버에서 현재가가 계속 '정보 없음'으로 나오던 원인]
예전에는 pandas의 read_html로 표를 읽었습니다. 그런데 read_html은 내부적으로
lxml이라는 별도 부품을 필요로 하고, 배포 서버에서는 이 부품을 찾지 못해
ImportError가 나고 있었습니다. 이 파일은 실패하면 조용히 None을 돌려주도록
되어 있어서, 오류가 눈에 띄지 않은 채 "현재가 정보 없음"으로만 보였습니다.
이제는 파이썬에 기본으로 들어있는 기능만 쓰는 html_table.py로 바꿔서,
추가 부품 설치 여부와 상관없이 항상 동작합니다.

[2026-09-12 보강]
1. 글자 저장 방식(인코딩)을 자동으로 판별합니다. 예전에는 euc-kr로 고정해뒀는데,
   네이버가 페이지를 UTF-8로 바꾸면 한글이 전부 깨져서 '종가'라는 글자를 찾지
   못하게 됩니다.
2. 표 읽기가 실패하면, 네이버 모바일 금융 자료(JSON)에서 한 번 더 시도합니다.
"""

import re

import requests
import streamlit as st

from html_table import decode_response, parse_tables, table_text

DATE_PATTERN = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")
DAILY_PRICE_URL = "https://finance.naver.com/item/sise_day.naver?code={code}&page=1"
MOBILE_BASIC_URL = "https://m.stock.naver.com/api/stock/{code}/basic"

PC_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/",
}
MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Referer": "https://m.stock.naver.com/",
    "Accept": "application/json",
}


def _find_daily_price_table(tables):
    """'일별 시세' 표(제목 줄에 '날짜'와 '종가'가 있는 표)를 찾습니다."""
    for table in tables:
        text = table_text(table)
        if "날짜" in text and "종가" in text:
            return table
    return None


def _column_index(table, column_name):
    """제목 줄에서 원하는 칸(예: '종가')이 몇 번째인지 찾습니다."""
    for row in table:
        texts = [cell["text"].strip() for cell in row]
        if column_name in texts:
            return texts.index(column_name)
    return None


def fetch_price_from_html(html_text):
    """
    '일별 시세' 페이지 내용에서 가장 최근 종가를 뽑아냅니다.
    (인터넷 연결과 분리해두면 이 계산 부분만 따로 시험해볼 수 있습니다.)
    """
    tables = parse_tables(html_text)
    table = _find_daily_price_table(tables)
    if table is None:
        return None

    close_index = _column_index(table, "종가")
    if close_index is None:
        return None

    for row in table:
        texts = [cell["text"].strip() for cell in row]
        if not texts or not DATE_PATTERN.match(texts[0]):
            continue  # 날짜로 시작하지 않는 줄(제목 줄, 빈 줄)은 건너뜁니다.
        if close_index >= len(texts):
            continue
        try:
            return int(texts[close_index].replace(",", ""))
        except (TypeError, ValueError):
            continue
    return None


def _fetch_price_from_mobile_api(stock_code):
    """표 읽기가 실패했을 때 쓰는 보조 방법입니다(JSON으로 현재가를 받아옵니다)."""
    url = MOBILE_BASIC_URL.format(code=str(stock_code).zfill(6))
    try:
        response = requests.get(url, headers=MOBILE_HEADERS, timeout=8)
        payload = response.json()
    except Exception:
        return None

    for key in ("closePrice", "nowPrice", "tradePrice", "currentPrice"):
        value = payload.get(key)
        if value is None:
            continue
        try:
            return int(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
    return None


@st.cache_data(ttl=300, show_spinner=False)
def get_current_price(stock_code):
    """
    네이버 금융에서 가장 최근 종가(직전 거래일 마감 가격)를 가져옵니다.

    stock_code: 종목코드 (6자리, 예: 삼성전자 "005930")
    반환값: 정수(원 단위) 또는 못 가져왔으면 None
    """
    if not stock_code:
        return None

    url = DAILY_PRICE_URL.format(code=str(stock_code).zfill(6))

    try:
        response = requests.get(url, headers=PC_HEADERS, timeout=8)
        price = fetch_price_from_html(decode_response(response))
        if price:
            return price
    except Exception:
        pass  # 아래 보조 방법으로 한 번 더 시도합니다.

    return _fetch_price_from_mobile_api(stock_code)


if __name__ == "__main__":
    종목코드 = "005930"  # 삼성전자
    가격 = get_current_price(종목코드)
    print(f"종목코드 {종목코드}의 최근 종가:", 가격)
