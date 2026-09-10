"""
"여러 분기 비교" 화면에서 쓰는 함수들을 모아둔 파일입니다.

OpenDART(전자공시)가 알려주는 보고서는 1분기/반기/3분기/사업보고서(연간)
이렇게 네 가지뿐이고, 각각 "그 시점까지 누적된" 금액입니다.
그래서 "2분기 한 분기만" 같은 순수 분기 금액은 누적 금액끼리 빼서 직접
계산해야 합니다.

예)
- 1분기 매출액 = 1분기 보고서의 매출액 (1~3월, 그 자체가 이미 한 분기 값)
- 2분기 매출액 = 반기(1~6월 누적) 매출액 - 1분기(1~3월) 매출액
- 3분기 매출액 = 3분기(1~9월 누적) 매출액 - 반기(1~6월 누적) 매출액
- 4분기 매출액 = 사업보고서(1~12월 누적) 매출액 - 3분기(1~9월 누적) 매출액

get_financial_data.py에 있는 get_financial_data / REPRT_CODES 함수는
전혀 수정하지 않고, 여기서는 그 결과를 가져다 빼기만 합니다.
"""

from get_financial_data import get_financial_data, REPRT_CODES

# 이 화면에서 비교할 지표 3가지 (사용자 요청: 매출액·영업이익·당기순이익)
METRICS = ["매출액", "영업이익", "당기순이익"]


def _to_int(value):
    """
    API가 돌려주는 금액은 문자열입니다(예: "1234567" 또는 손실이면 "-1234567").
    숫자로 못 바꾸면(정보 없음 등) None으로 처리해서 이후 계산에서 안전하게 걸러냅니다.
    """
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _subtract(later, earlier):
    """
    later(더 긴 누적 기간)에서 earlier(더 짧은 누적 기간)를 빼서,
    그 사이 한 분기만의 금액을 구합니다. 둘 중 하나라도 숫자로 못 바꾸면
    결과도 None(정보 없음)으로 처리합니다.
    """
    result = {}
    for metric in METRICS:
        a = _to_int(later.get(metric)) if later else None
        b = _to_int(earlier.get(metric)) if earlier else None
        result[metric] = None if (a is None or b is None) else a - b
    return result


def _fetch_report(cache, corp_code, year, reprt_label):
    """
    같은 (연도, 보고서 종류) 조합은 API를 한 번만 호출하고 재사용합니다.
    예를 들어 "반기" 보고서는 2분기 계산에도, 3분기 계산에도 쓰이기 때문에
    두 번 API를 부르지 않도록 캐시(임시 저장소)에 담아둡니다.
    """
    key = (year, reprt_label)
    if key not in cache:
        reprt_code = REPRT_CODES[reprt_label]
        cache[key] = get_financial_data(corp_code, str(year), reprt_code)
    return cache[key]


def get_single_quarter(cache, corp_code, year, quarter):
    """
    특정 연도의 특정 분기(1~4) 하나만의 매출액/영업이익/당기순이익을 계산합니다.

    반환값:
    - 성공 시: {"매출액": 숫자 또는 None, "영업이익": ..., "당기순이익": ...}
    - 실패 시: {"오류": "안내 문구"}
    """
    if quarter == 1:
        rep = _fetch_report(cache, corp_code, year, "1분기")
        if "오류" in rep:
            return {"오류": rep["오류"]}
        return {m: _to_int(rep.get(m)) for m in METRICS}

    if quarter == 2:
        half = _fetch_report(cache, corp_code, year, "반기")
        q1 = _fetch_report(cache, corp_code, year, "1분기")
        if "오류" in half:
            return {"오류": half["오류"]}
        if "오류" in q1:
            return {"오류": q1["오류"]}
        return _subtract(half, q1)

    if quarter == 3:
        q3 = _fetch_report(cache, corp_code, year, "3분기")
        half = _fetch_report(cache, corp_code, year, "반기")
        if "오류" in q3:
            return {"오류": q3["오류"]}
        if "오류" in half:
            return {"오류": half["오류"]}
        return _subtract(q3, half)

    if quarter == 4:
        annual = _fetch_report(cache, corp_code, year, "사업보고서(연간)")
        q3 = _fetch_report(cache, corp_code, year, "3분기")
        if "오류" in annual:
            return {"오류": annual["오류"]}
        if "오류" in q3:
            return {"오류": q3["오류"]}
        return _subtract(annual, q3)

    raise ValueError("quarter는 1~4 사이의 값이어야 합니다.")


def build_quarter_list(start_year, start_quarter, count):
    """
    시작 연도/분기부터 시간 순서대로 count개의 (연도, 분기)를 만들어 돌려줍니다.
    예) start_year=2024, start_quarter=3, count=4
        -> [(2024,3), (2024,4), (2025,1), (2025,2)]
    """
    quarters = []
    year, quarter = start_year, start_quarter
    for _ in range(count):
        quarters.append((year, quarter))
        quarter += 1
        if quarter > 4:
            quarter = 1
            year += 1
    return quarters


def build_comparison_data(corp_code, quarters):
    """
    quarters: [(연도, 분기), ...] (시간 순서)

    반환값: (values, errors)
    - values: {(연도, 분기): {"매출액": .., "영업이익": .., "당기순이익": ..}}
      (오류가 난 분기는 세 지표 모두 None으로 채워서, 표를 그릴 때 예외 처리를 안 해도 되게 함)
    - errors: {(연도, 분기): "오류 안내 문구"}  (오류 없으면 빈 딕셔너리)
    """
    cache = {}
    values = {}
    errors = {}
    for year, quarter in quarters:
        result = get_single_quarter(cache, corp_code, year, quarter)
        if "오류" in result:
            errors[(year, quarter)] = result["오류"]
            values[(year, quarter)] = {m: None for m in METRICS}
        else:
            values[(year, quarter)] = result
    return values, errors


def compute_growth(previous, current):
    """
    직전 분기 대비 증감률을 계산합니다.
    - 계산할 수 없으면(둘 중 하나가 None, 또는 직전 값이 0) None
    - 적자였다가 흑자로 바뀌면 "흑자전환", 흑자였다가 적자로 바뀌면 "적자전환"
    - 그 외에는 증감률(%) 숫자
    """
    if previous is None or current is None:
        return None
    if previous == 0:
        return None
    if previous < 0 and current >= 0:
        return "흑자전환"
    if previous >= 0 and current < 0:
        return "적자전환"
    return (current - previous) / abs(previous) * 100
