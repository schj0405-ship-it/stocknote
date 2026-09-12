"""
네이버 금융에서 재무데이터(매출액·영업이익·당기순이익)를 가져오는 파일입니다.

[왜 이 파일이 필요한가]
연결 진단 결과, 배포된 서버(미국 Streamlit Cloud)에서 OpenDART 서버
(opendart.fss.or.kr)로는 연결 자체가 되지 않는 것으로 확인되었습니다
(TCP 연결 시간 초과). 반면 같은 서버에서 네이버 금융은 0.5초 만에 정상
응답했습니다. 즉 "한국이 멀어서"가 아니라 OpenDART 쪽에서만 이 서버의
접속을 막고 있는 상태입니다. 그래서 OpenDART가 실패하면 네이버에서 같은
숫자를 대신 가져옵니다.

[2026-09-12 전면 보강 - 왜 또 실패했는가]
직전 진단에서 8단계가 "'기업실적분석' 표를 찾지 못했습니다"로 실패했습니다.
연결은 됐는데(7·8-2단계 성공) 표를 못 찾은 것이라, 원인이 될 수 있는 경우가
여럿이었습니다.
  (1) 글자 저장 방식(인코딩)을 잘못 골라 한글이 깨져서 '매출액'을 못 찾음
  (2) 표의 닫는 표시가 빠져 있어서 표 읽기 자체가 실패
  (3) 네이버가 이 서버에는 표가 빠진 다른 화면을 내려줌
어느 것인지 화면만 보고는 알 수 없어서, 셋 다 통하도록 아래처럼 고쳤습니다.

  1. 먼저 네이버 '모바일 금융 데이터 주소'에서 JSON(표가 아니라 숫자만 정리된
     형태) 으로 받아옵니다. 표가 아니므로 (1)(2)(3) 문제가 원천적으로 없습니다.
  2. 그게 안 되면 기존 방식대로 종목 페이지의 '기업실적분석' 표를 읽습니다.
     이때 글자 저장 방식은 자동으로 판별하고(html_table.decode_response),
     표 찾기 조건도 훨씬 느슨하게 바꿨습니다.
  3. 두 방법 모두 실패하면, 각각 왜 실패했는지를 한 줄씩 모아서 알려줍니다.
     (지금까지는 마지막 실패 이유만 보여서 원인 파악이 느렸습니다.)

[OpenDART와 다른 점 - 미리 알아두셔야 할 한계]
1. 단위가 억원 단위로 반올림되어 있습니다.
2. 가져올 수 있는 기간이 최근 3~4개 연도, 최근 4~6개 분기로 제한됩니다.
3. 지배주주순이익은 제공되지 않습니다.
4. 분기 숫자는 이미 "그 분기 하나만"의 값입니다(OpenDART처럼 누적값을 빼서
   계산할 필요가 없습니다).
5. 열 이름에 (E)가 붙은 것은 실제 실적이 아니라 증권사 '예상치'라서 제외합니다.
"""

import re

import requests
import streamlit as st

from html_table import decode_response, parse_tables, table_text

NAVER_MAIN_URL = "https://finance.naver.com/item/main.naver?code={code}"
NAVER_MOBILE_API = "https://m.stock.naver.com/api/stock/{code}/finance/{kind}"
REQUEST_TIMEOUT = 8

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

# 네이버 표/자료에서 찾을 항목 이름
METRIC_NAMES = ("매출액", "영업이익", "당기순이익")

UNIT_EOK = 100_000_000        # 1억 = 100,000,000원
WON_LIKE_THRESHOLD = 1e9      # 이 값보다 크면 이미 '원' 단위로 적힌 숫자로 봅니다.

# '2025.03', '202503', '2025/03' 등을 모두 인식합니다.
_PERIOD_PATTERN = re.compile(r"(19|20)(\d{2})[.\-/]?(0[1-9]|1[0-2])")


# ----------------------------------------------------------------------
# 공통 도구
# ----------------------------------------------------------------------
def _parse_period(label):
    """
    기간 표시를 (연도, 월)로 바꿉니다. 예상치((E))는 제외합니다.
    예: '2025.03' → (2025, 3) / '202512(E)' → None
    """
    if label is None:
        return None
    text = str(label).strip().replace(" ", "")
    if "(E)" in text.upper():
        return None
    found = _PERIOD_PATTERN.search(text)
    if not found:
        return None
    year = int(found.group(1) + found.group(2))
    month = int(found.group(3))
    return year, month


def _to_number(value):
    """'3,338,467' 같은 글자를 숫자로 바꿉니다. 숫자가 아니면 None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace(" ", "").strip()
    text = text.replace("원", "").replace("억", "")
    if text in ("", "-", "--", "nan", "None", "N/A", "해당사항없음"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _unit_multiplier(numbers):
    """
    이 자료가 '억원' 단위인지 '원' 단위인지 판단해서 곱할 값을 돌려줍니다.

    네이버 표는 억원 단위(예: 삼성전자 매출 3,008,700)지만, 자료 종류에 따라
    원 단위로 내려오는 경우도 있습니다. 원 단위인데 또 1억을 곱하면 숫자가
    1억 배로 틀어지므로, 가장 큰 값을 보고 한 번에 판단합니다.
    """
    largest = max((abs(n) for n in numbers if n is not None), default=0)
    return 1 if largest >= WON_LIKE_THRESHOLD else UNIT_EOK


def _month_to_quarter(month):
    """3월=1분기, 6월=2분기, 9월=3분기, 12월=4분기. 그 외는 None."""
    if month in (3, 6, 9, 12):
        return month // 3
    return None


def _empty_metrics():
    return {name: None for name in METRIC_NAMES}


# ----------------------------------------------------------------------
# 방법 1) 네이버 모바일 금융 데이터(JSON)
# ----------------------------------------------------------------------
def _scalar(value):
    """자료에서 실제 숫자(또는 숫자 글자)를 꺼냅니다."""
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, dict):
        for key in ("value", "val", "amount", "num", "data"):
            if key in value:
                inner = _scalar(value[key])
                if inner is not None:
                    return inner
    return None


def _collect_period_values(node):
    """
    자료 조각 안에서 '기간 → 값' 짝을 모두 찾아냅니다.

    네이버가 자료 모양을 바꿔도 계속 동작하도록, 정해진 이름에 의존하지 않고
    아래 두 가지 흔한 형태를 모두 인식합니다.
      형태 A : {"202503": {"value": "79,140"}, "202506": ...}
      형태 B : [{"key": "202503", "value": "79,140"}, ...]
    """
    collected = {}

    def visit(current):
        if isinstance(current, dict):
            # 형태 A
            for key, value in current.items():
                period = _parse_period(key)
                if period:
                    number = _to_number(_scalar(value))
                    if number is not None:
                        collected[period] = number

            # 형태 B
            period = None
            for key in ("key", "period", "date", "term", "yymm", "title"):
                if key in current:
                    period = _parse_period(current.get(key))
                    if period:
                        break
            if period:
                for key in ("value", "val", "amount", "num"):
                    if key in current:
                        number = _to_number(_scalar(current[key]))
                        if number is not None:
                            collected[period] = number
                        break

            for value in current.values():
                visit(value)

        elif isinstance(current, list):
            for value in current:
                visit(value)

    visit(node)
    return collected


def _extract_metrics_from_json(payload):
    """JSON 자료에서 {'매출액': {(2025,3): 79140.0, ...}, ...} 형태를 만듭니다."""
    found = {}

    def visit(current):
        if isinstance(current, dict):
            title = None
            for key in ("title", "name", "titleKo", "korName", "key"):
                value = current.get(key)
                if isinstance(value, str) and value.strip() in METRIC_NAMES:
                    title = value.strip()
                    break
            if title:
                values = _collect_period_values(current)
                if values:
                    found.setdefault(title, {}).update(values)
            for value in current.values():
                visit(value)
        elif isinstance(current, list):
            for value in current:
                visit(value)

    visit(payload)
    return found


def _fetch_from_mobile_api(stock_code):
    """
    네이버 모바일 금융의 재무 자료를 JSON으로 받아옵니다.
    돌려주는 값: (연간 dict, 분기 dict, 안내문구)
    """
    code = str(stock_code).zfill(6)
    annual, quarterly = {}, {}
    notes = []

    for kind in ("annual", "quarter"):
        url = NAVER_MOBILE_API.format(code=code, kind=kind)
        try:
            response = requests.get(url, headers=MOBILE_HEADERS, timeout=REQUEST_TIMEOUT)
            status = response.status_code
            payload = response.json()
        except Exception as e:
            notes.append(f"모바일 {kind}: 실패 ({type(e).__name__})")
            continue

        metrics = _extract_metrics_from_json(payload)
        if not metrics:
            notes.append(f"모바일 {kind}: 응답코드 {status}, 원하는 항목 없음")
            continue

        every_number = [n for values in metrics.values() for n in values.values()]
        multiplier = _unit_multiplier(every_number)

        for metric, values in metrics.items():
            for (year, month), number in values.items():
                amount = int(round(number * multiplier))
                if kind == "annual":
                    annual.setdefault(year, _empty_metrics())[metric] = amount
                else:
                    quarter = _month_to_quarter(month)
                    if quarter:
                        target = quarterly.setdefault((year, quarter), _empty_metrics())
                        target[metric] = amount

        notes.append(f"모바일 {kind}: 성공 (항목 {len(metrics)}개)")

    return annual, quarterly, "; ".join(notes)


# ----------------------------------------------------------------------
# 방법 2) 종목 페이지의 '기업실적분석' 표 읽기
# ----------------------------------------------------------------------
def _find_performance_table(tables):
    """
    '기업실적분석' 표를 찾습니다.

    예전에는 "'주요재무정보'와 '매출액'이 둘 다 있는 표"만 인정했는데, 그
    조건이 하나라도 어긋나면 표를 통째로 못 찾았습니다. 이제는 점수를 매겨서
    가장 그럴듯한 표를 고릅니다(항목 이름이 있을수록, 기간 열이 많을수록 높은 점수).
    """
    best_table, best_score = None, 0
    for table in tables:
        text = table_text(table)
        if "매출액" not in text:
            continue
        score = 0
        if "주요재무정보" in text:
            score += 5
        if "영업이익" in text:
            score += 2
        if "당기순이익" in text:
            score += 2
        periods = {
            match.group(0) for match in _PERIOD_PATTERN.finditer(text.replace(" ", ""))
        }
        score += len(periods)
        if len(periods) >= 2 and score > best_score:
            best_table, best_score = table, score
    return best_table


def _period_row_index(table):
    """기간(2025.03 등)이 가장 많이 들어있는 줄이 '기간 제목 줄'입니다."""
    best_index, best_count = None, 0
    for index, row in enumerate(table):
        count = sum(
            1
            for cell in row
            if _parse_period(cell["text"]) or "(E)" in cell["text"].upper()
        )
        if count > best_count:
            best_index, best_count = index, count
    return best_index if best_count >= 2 else None


def _period_columns(row):
    """
    기간 제목 줄을 '값 칸 순서'와 맞춰서 정리합니다.
    맨 앞의 항목 이름 칸('주요재무정보' 등)은 값 칸이 아니므로 떼어냅니다.
    """
    columns = []
    for cell in row:
        text = cell["text"]
        is_estimate = "(E)" in text.upper()
        columns.append(
            {
                "period": None if is_estimate else _parse_period(text),
                "estimate": is_estimate,
            }
        )
    while columns and columns[0]["period"] is None and not columns[0]["estimate"]:
        columns.pop(0)
    return columns


def _group_labels(table, period_index, column_count):
    """
    기간 줄 바로 위의 '최근 연간 실적 / 최근 분기 실적' 줄을 칸 수에 맞춰 펼칩니다.
    (칸 하나가 여러 칸을 차지하는 colspan을 그대로 반영합니다.)
    """
    if period_index is None or period_index == 0:
        return [None] * column_count

    labels = []
    for cell in table[period_index - 1]:
        if cell["rowspan"] > 1:
            continue  # '주요재무정보'처럼 두 줄을 차지하는 항목 이름 칸은 제외
        labels.extend([cell["text"]] * cell["colspan"])

    if len(labels) < column_count:
        labels.extend([None] * (column_count - len(labels)))
    return labels[:column_count]


def _guess_kinds(columns):
    """
    제목 줄에서 '연간/분기'를 못 읽었을 때를 대비한 보조 판단입니다.
    앞뒤 기간의 간격이 12개월이면 연간, 3개월이면 분기로 봅니다.
    """
    kinds = [None] * len(columns)
    months = [
        (column["period"][0] * 12 + column["period"][1]) if column["period"] else None
        for column in columns
    ]
    for index in range(len(columns)):
        gaps = []
        if index > 0 and months[index] and months[index - 1]:
            gaps.append(months[index] - months[index - 1])
        if index + 1 < len(columns) and months[index] and months[index + 1]:
            gaps.append(months[index + 1] - months[index])
        if 12 in gaps:
            kinds[index] = "연간"
        elif 3 in gaps:
            kinds[index] = "분기"
    return kinds


def _fetch_from_html(stock_code):
    """
    종목 페이지의 '기업실적분석' 표를 읽습니다.
    돌려주는 값: (연간 dict, 분기 dict, 안내문구)
    """
    code = str(stock_code).zfill(6)
    url = NAVER_MAIN_URL.format(code=code)

    try:
        response = requests.get(url, headers=PC_HEADERS, timeout=REQUEST_TIMEOUT)
        html_text = decode_response(response)
    except Exception as e:
        return {}, {}, f"표 읽기: 연결 실패 ({type(e).__name__}: {e})"

    tables = parse_tables(html_text)
    table = _find_performance_table(tables)
    if table is None:
        has_keyword = "기업실적분석" in html_text or "주요재무정보" in html_text
        return (
            {},
            {},
            (
                f"표 읽기: 표를 못 찾음 (문서 {len(html_text):,}자, 표 {len(tables)}개, "
                f"'기업실적분석/주요재무정보' 글자 {'있음' if has_keyword else '없음'})"
            ),
        )

    period_index = _period_row_index(table)
    if period_index is None:
        return {}, {}, "표 읽기: 표는 찾았지만 기간(2025.03 등) 제목 줄을 못 찾음"

    columns = _period_columns(table[period_index])
    labels = _group_labels(table, period_index, len(columns))
    guessed = _guess_kinds(columns)

    # 항목 이름 → 그 줄의 값들
    row_values = {}
    for index, row in enumerate(table):
        if index == period_index or len(row) < 2:
            continue
        label = row[0]["text"].strip()
        if label in METRIC_NAMES:
            row_values[label] = [cell["text"] for cell in row[1:]]

    if not row_values:
        return {}, {}, "표 읽기: 표는 찾았지만 매출액/영업이익/당기순이익 줄이 없음"

    every_number = [
        _to_number(text) for values in row_values.values() for text in values
    ]
    multiplier = _unit_multiplier([n for n in every_number if n is not None])

    annual, quarterly = {}, {}
    for position, column in enumerate(columns):
        period = column["period"]
        if period is None:
            continue  # 예상치((E))거나 기간을 못 읽은 칸

        label = labels[position] or ""
        if "연간" in label:
            kind = "연간"
        elif "분기" in label:
            kind = "분기"
        else:
            kind = guessed[position]
        if kind is None:
            continue

        year, month = period
        values = _empty_metrics()
        for metric in METRIC_NAMES:
            cells = row_values.get(metric)
            if cells and position < len(cells):
                number = _to_number(cells[position])
                if number is not None:
                    values[metric] = int(round(number * multiplier))

        if kind == "연간":
            annual[year] = values
        else:
            quarter = _month_to_quarter(month)
            if quarter:
                quarterly[(year, quarter)] = values

    note = f"표 읽기: 성공 (연간 {len(annual)}개, 분기 {len(quarterly)}개)"
    return annual, quarterly, note


# ----------------------------------------------------------------------
# 바깥에서 쓰는 함수들
# ----------------------------------------------------------------------
def collect_naver_financials(stock_code):
    """
    두 가지 방법을 차례로 시도해서 재무데이터를 모읍니다(저장 기능 없음).
    돌려주는 값: (연간 dict, 분기 dict, 시도 기록 리스트)
    """
    notes = []

    annual, quarterly, note = _fetch_from_mobile_api(stock_code)
    if note:
        notes.append(note)

    if not annual and not quarterly:
        annual, quarterly, note = _fetch_from_html(stock_code)
        notes.append(note)
    else:
        # 모바일 자료가 일부만 왔으면(예: 분기만), 나머지는 표에서 보충합니다.
        if not annual or not quarterly:
            html_annual, html_quarterly, note = _fetch_from_html(stock_code)
            notes.append(note)
            for year, values in html_annual.items():
                annual.setdefault(year, values)
            for key, values in html_quarterly.items():
                quarterly.setdefault(key, values)

    return annual, quarterly, notes


@st.cache_data(ttl=900, show_spinner=False)
def fetch_naver_financials(stock_code):
    """
    종목코드를 받아서 네이버의 재무데이터를 가져옵니다.

    돌려주는 값(성공 시):
    {
      "연간": { 2024: {"매출액": 숫자, "영업이익": 숫자, "당기순이익": 숫자}, ... },
      "분기": { (2025, 1): {...}, ... },
      "경로": "어떤 방법으로 가져왔는지 설명",
    }
    실패 시: {"오류": "왜 실패했는지 (방법별로 모두)"}
    """
    if not stock_code:
        return {"오류": "종목코드가 없어서 네이버에서 조회할 수 없습니다."}

    try:
        annual, quarterly, notes = collect_naver_financials(stock_code)
    except Exception as e:
        return {"오류": f"네이버 재무데이터 처리 중 오류 ({type(e).__name__}: {e})"}

    if not annual and not quarterly:
        return {"오류": "네이버에서 재무데이터를 가져오지 못했습니다. — " + " | ".join(notes)}

    return {"연간": annual, "분기": quarterly, "경로": " | ".join(notes)}


def get_quarter_values(stock_code, year, quarter):
    """
    특정 (연도, 분기)의 매출액·영업이익·당기순이익을 네이버에서 가져옵니다.
    성공 시 {"매출액": .., "영업이익": .., "당기순이익": ..}, 실패 시 {"오류": ...}
    """
    data = fetch_naver_financials(stock_code)
    if "오류" in data:
        return data

    values = data["분기"].get((year, quarter))
    if values is None:
        available = ", ".join(f"{y}년 {q}분기" for y, q in sorted(data["분기"]))
        return {
            "오류": (
                f"네이버에는 {year}년 {quarter}분기 실적이 없습니다"
                + (f" (제공 기간: {available})" if available else "")
                + "."
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
        available = ", ".join(str(y) for y in sorted(data["연간"]))
        return {
            "오류": (
                f"네이버에는 {year}년 연간 실적이 없습니다"
                + (f" (제공 연도: {available})" if available else "")
                + "."
            )
        }
    return values


def diagnose(stock_code="005930"):
    """
    연결 진단 화면에서 쓰는 함수입니다. 방법별로 무엇이 되고 무엇이 안 되는지
    사람이 읽을 수 있는 글로 정리해서 돌려줍니다(저장된 값을 쓰지 않습니다).
    """
    lines = []

    annual, quarterly, note = _fetch_from_mobile_api(stock_code)
    lines.append(f"[방법1] 모바일 금융 자료(JSON) → {note or '시도 결과 없음'}")
    if annual:
        lines.append("        받은 연간: " + ", ".join(str(y) for y in sorted(annual)))
    if quarterly:
        lines.append(
            "        받은 분기: "
            + ", ".join(f"{y}년 {q}분기" for y, q in sorted(quarterly))
        )

    html_annual, html_quarterly, html_note = _fetch_from_html(stock_code)
    lines.append(f"[방법2] 종목 페이지 표 읽기 → {html_note}")
    if html_annual:
        lines.append("        받은 연간: " + ", ".join(str(y) for y in sorted(html_annual)))
    if html_quarterly:
        lines.append(
            "        받은 분기: "
            + ", ".join(f"{y}년 {q}분기" for y, q in sorted(html_quarterly))
        )

    merged_quarterly = dict(html_quarterly)
    merged_quarterly.update(quarterly)
    if merged_quarterly:
        key = sorted(merged_quarterly)[-1]
        revenue = merged_quarterly[key].get("매출액")
        lines.append(
            f"[확인] {key[0]}년 {key[1]}분기 매출액: "
            + (f"{revenue:,}원" if revenue else "정보 없음")
        )

    if not annual and not quarterly and not html_annual and not html_quarterly:
        raise RuntimeError("\n".join(lines))

    return "\n".join(lines)
