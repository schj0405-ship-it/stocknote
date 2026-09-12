"""
네이버 금융에서 재무데이터(매출액·영업이익·당기순이익)를 가져오는 파일입니다.

[왜 이 파일이 필요한가]
연결 진단 결과, 배포된 서버(미국 Streamlit Cloud)에서 OpenDART 서버
(opendart.fss.or.kr, 61.73.60.206)로는 연결 자체가 되지 않는 것으로 확인
되었습니다(TCP 연결 8초 시간 초과). 반면 같은 서버에서 네이버 금융
(finance.naver.com)은 0.6초 만에 정상 응답했습니다. 즉 "한국이 멀어서"가
아니라 OpenDART 쪽에서만 이 서버의 접속을 막고 있는 상태입니다.

그래서 OpenDART가 실패할 때 네이버 금융의 '기업실적분석' 표에서 같은
숫자를 대신 가져오도록 이 파일을 만들었습니다. 이미 주가를 가져올 때
(stock_price.py) 같은 방식으로 네이버를 쓰고 있고, 그건 배포 환경에서
정상 동작하는 것이 확인된 방식입니다.

[OpenDART와 다른 점 - 미리 알아두셔야 할 한계]
1. 단위가 억원 단위로 반올림되어 있습니다. (예: 3,338,467억원)
   OpenDART는 1원 단위까지 주지만, 네이버는 억원 단위까지만 줍니다.
2. 가져올 수 있는 기간이 최근 3~4개 연도, 최근 4~6개 분기로 제한됩니다.
   그보다 오래된 분기는 네이버 표에 아예 없습니다.
3. 지배주주순이익은 이 표에 없어서 가져올 수 없습니다.
4. 분기 숫자는 이미 "그 분기 하나만"의 값입니다(OpenDART처럼 누적값을
   빼서 계산할 필요가 없습니다).
5. 열 이름에 (E)가 붙은 것은 실제 실적이 아니라 증권사들의 "예상치"라서
   제외합니다.
"""

import requests
import streamlit as st

from html_table import parse_tables, split_header_and_data, table_text

NAVER_MAIN_URL = "https://finance.naver.com/item/main.naver?code={code}"
REQUEST_TIMEOUT = 8

# 네이버 표에서 찾을 항목 이름 → 이 앱에서 쓰는 이름
METRIC_ROW_NAMES = {
    "매출액": "매출액",
    "영업이익": "영업이익",
    "당기순이익": "당기순이익",
}

# 억원 단위를 원 단위로 바꾸는 값 (1억 = 100,000,000원)
UNIT_EOK = 100_000_000


def _clean_column_label(label):
    """
    열 이름을 '2025.03' 같은 깔끔한 형태로 다듬습니다.
    네이버 표의 열 이름은 '2025.12(E)'(예상치) 형태로 올 수 있어서,
    예상치는 제외하고 '연도.월' 부분만 잘라냅니다.
    """
    text = str(label).strip()
    if "(E)" in text or "(e)" in text:
        return None  # 예상치는 실제 실적이 아니므로 제외
    parts = text.split(".")
    if len(parts) < 2:
        return None
    year, month = parts[0].strip(), parts[1].strip()[:2]
    if not (year.isdigit() and month.isdigit() and len(year) == 4):
        return None
    return f"{year}.{month}"


def _parse_amount(value):
    """
    표의 숫자(예: '3,338,467' 또는 '-1,234')를 원 단위 정수로 바꿉니다.
    빈칸이거나 숫자가 아니면 None을 돌려줍니다.
    """
    if value is None:
        return None
    text = str(value).replace(",", "").replace(" ", "").strip()
    if text in ("", "-", "nan", "None"):
        return None
    try:
        return int(round(float(text) * UNIT_EOK))
    except (TypeError, ValueError):
        return None


def _find_performance_table(tables):
    """
    네이버 종목 페이지에는 표가 여러 개 있습니다. 그중 '기업실적분석' 표를
    찾아내야 하는데, 표의 순서는 페이지가 바뀌면 달라질 수 있어서 순서로
    찾지 않고 "'주요재무정보'와 '매출액'이라는 글자가 둘 다 들어있는 표"를
    조건으로 찾습니다.
    """
    for table in tables:
        text = table_text(table)
        if "주요재무정보" in text and "매출액" in text:
            return table
    return None


def _build_columns(header_rows):
    """
    제목 줄 두 개를 합쳐서, 각 칸이 '연간 실적'인지 '분기 실적'인지와
    어느 시점(2025.03 등)인지를 짝지어 돌려줍니다.

    네이버 표의 제목은 두 줄로 되어 있습니다.
      첫째 줄 : [주요재무정보(두 줄 차지)] [최근 연간 실적(3칸 차지)] [최근 분기 실적(4칸 차지)]
      둘째 줄 : [2023.12] [2024.12] [2025.12(E)] [2025.03] [2025.06] ...
    그래서 첫째 줄에서 '몇 칸을 차지하는지(colspan)'만큼 이름을 늘어놓으면
    둘째 줄의 시점들과 하나씩 정확히 맞춰집니다.
    """
    if len(header_rows) < 2:
        return []

    groups = []
    for cell in header_rows[0]:
        if cell["rowspan"] > 1:
            continue  # '주요재무정보' 칸은 항목 이름 칸이라 제외합니다.
        groups.extend([cell["text"]] * cell["colspan"])

    periods = [cell["text"] for cell in header_rows[1]]
    return list(zip(groups, periods))


@st.cache_data(ttl=900, show_spinner=False)
def fetch_naver_financials(stock_code):
    """
    종목코드를 받아서 네이버 금융의 기업실적분석 표를 읽어옵니다.

    돌려주는 값(성공 시):
    {
      "연간": { 2024: {"매출액": 숫자, "영업이익": 숫자, "당기순이익": 숫자}, ... },
      "분기": { (2025, 1): {"매출액": ..., "영업이익": ..., "당기순이익": ...}, ... },
    }
    실패 시: {"오류": "안내 문구"}
    """
    if not stock_code:
        return {"오류": "종목코드가 없어서 네이버에서 조회할 수 없습니다."}

    url = NAVER_MAIN_URL.format(code=str(stock_code).zfill(6))
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.encoding = "euc-kr"  # 네이버 금융이 쓰는 글자 인코딩
        tables = parse_tables(response.text)
    except Exception as e:
        # 오류 종류만이 아니라 실제 내용까지 함께 알려줍니다.
        # (지난번에는 종류만 표시해서 "ImportError"라는 것만 알 수 있었고,
        #  무엇이 없다는 것인지 알 수 없어 원인 파악이 늦어졌습니다.)
        return {"오류": f"네이버 금융 연결에 실패했습니다. ({type(e).__name__}: {e})"}

    table = _find_performance_table(tables)
    if table is None:
        return {"오류": "네이버 금융 페이지에서 '기업실적분석' 표를 찾지 못했습니다."}

    header_rows, data_rows = split_header_and_data(table)
    columns = _build_columns(header_rows)
    if not columns:
        return {"오류": "네이버 '기업실적분석' 표의 제목 줄을 해석하지 못했습니다."}

    # 항목 이름(매출액 등) → 그 줄의 값들
    row_values = {}
    for row in data_rows:
        if not row:
            continue
        label = row[0]["text"].strip()
        row_values[label] = [cell["text"] for cell in row[1:]]

    annual = {}
    quarterly = {}

    for index, (group, period_label) in enumerate(columns):
        period = _clean_column_label(period_label)
        if period is None:
            continue

        is_quarter = "분기" in group
        is_annual = "연간" in group
        if not is_quarter and not is_annual:
            continue

        year_text, month_text = period.split(".")
        year, month = int(year_text), int(month_text)

        values = {}
        for row_name, metric in METRIC_ROW_NAMES.items():
            cells = row_values.get(row_name)
            if not cells or index >= len(cells):
                values[metric] = None
            else:
                values[metric] = _parse_amount(cells[index])

        if is_annual:
            annual[year] = values
        else:
            # 3월=1분기, 6월=2분기, 9월=3분기, 12월=4분기
            if month not in (3, 6, 9, 12):
                continue  # 결산월이 다른 회사는 분기 매칭이 어긋나서 건너뜁니다.
            quarter = month // 3
            quarterly[(year, quarter)] = values

    if not annual and not quarterly:
        return {"오류": "네이버 금융 표에서 읽을 수 있는 실적 숫자가 없습니다."}

    return {"연간": annual, "분기": quarterly}


def get_quarter_values(stock_code, year, quarter):
    """
    특정 (연도, 분기)의 매출액·영업이익·당기순이익을 네이버에서 가져옵니다.
    성공 시 {"매출액": .., "영업이익": .., "당기순이익": ..},
    실패 시 {"오류": "안내 문구"}
    """
    data = fetch_naver_financials(stock_code)
    if "오류" in data:
        return data

    values = data["분기"].get((year, quarter))
    if values is None:
        return {
            "오류": (
                f"네이버 금융에는 {year}년 {quarter}분기 실적이 없습니다"
                " (네이버는 최근 4~6개 분기만 제공합니다)."
            )
        }
    return values


def get_annual_values(stock_code, year):
    """특정 연도의 연간 실적을 네이버에서 가져옵니다."""
    data = fetch_naver_financials(stock_code)
    if "오류" in data:
        return data

    values = data["연간"].get(year)
    if values is None:
        return {"오류": f"네이버 금융에는 {year}년 연간 실적이 없습니다."}
    return values
