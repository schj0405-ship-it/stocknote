import time
import concurrent.futures

import requests
import pandas as pd
import streamlit as st
from stock_price import get_current_price

# API 키는 이제 config.py 파일이 아니라 .streamlit/secrets.toml에서 읽어옵니다.
# (내 컴퓨터에서만 쓸 땐 파일 하나로 충분했지만, 인터넷에 배포하려면
#  키가 그대로 코드에 딸려 GitHub에 올라가면 안 되기 때문입니다.)
DART_API_KEY = st.secrets["DART_API_KEY"]

# OpenDART 서버에 요청을 보내고 이 시간(초)이 지나도 응답이 없으면
# 무한정 기다리지 않고 포기합니다. (timeout을 안 정해두면 서버가 응답을
# 안 줄 때 화면이 "조회중" 상태로 영원히 멈춰버립니다.)
REQUEST_TIMEOUT = 15

# Streamlit Community Cloud는 미국에서만 앱을 실행하는데, 그러다 보니
# 물리적으로 먼 한국 서버(OpenDART)로 나가는 요청이 가끔 유독 늦게 오거나
# 아예 응답이 안 오는 경우가 있습니다(Streamlit 쪽 커뮤니티에도 같은 증상이
# 보고돼 있음). 그래서 한 번 실패하면 잠깐 쉬었다가 한 번 더 시도합니다.
REQUEST_RETRIES = 2


def _request_with_retry(url, params):
    last_error = None
    for attempt in range(REQUEST_RETRIES):
        try:
            return requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < REQUEST_RETRIES - 1:
                time.sleep(1)
    raise last_error

# 분기(보고서) 코드 - OpenDART가 정해놓은 규칙
REPRT_CODES = {
    "1분기": "11013",
    "반기": "11012",
    "3분기": "11014",
    "사업보고서(연간)": "11011",
}

# 매출액을 찾을 때 쓰는 기준들입니다.
#
# account_id는 회사마다 다르게 붙이는 "계정명(글자)"과 달리, OpenDART가
# 회계기준(IFRS)에 맞춰 표준으로 매겨주는 "계정 코드"입니다. 예를 들어
# 제조업 회사는 손익계산서에 "매출액"이라고 쓰지만, 알테오젠 같은
# 바이오·라이선스 회사는 같은 항목을 "수익(매출액)"이나 "영업수익"이라고
# 쓰는 경우가 있습니다. 글자(계정명)만 보고 "매출액"인지 판단하면 이런
# 회사는 놓치게 되어서, 먼저 표준 코드(account_id)로 확인하고, 표준
# 코드가 없는 회사를 위해 알려진 계정명 목록도 같이 확인합니다.
REVENUE_ACCOUNT_IDS = {
    "ifrs-full_Revenue",
    "ifrs-full_RevenueFromContractsWithCustomers",
}
REVENUE_ACCOUNT_NAMES = {"매출액", "수익(매출액)", "영업수익", "매출"}


def _is_revenue_item(item):
    """이 손익계산서 항목이 '매출액'에 해당하는 항목인지 판단합니다."""
    account_id = (item.get("account_id") or "").strip()
    if account_id in REVENUE_ACCOUNT_IDS:
        return True
    name = (item.get("account_nm") or "").strip()
    return name in REVENUE_ACCOUNT_NAMES


def find_corp_code(company_name):
    """
    1-3단계에서 만든 corp_codes.csv 안에서 회사 이름으로 고유번호를 찾는 함수
    (전화번호부에서 이름으로 전화번호 찾는 것과 같음)
    """
    df = pd.read_csv("corp_codes.csv", dtype=str)
    matched = df[df["corp_name"] == company_name]
    if matched.empty:
        matched = df[df["corp_name"].str.contains(company_name, na=False)]
    if matched.empty:
        return None
    return matched.iloc[0]["corp_code"]


def find_stock_code(company_name):
    """
    corp_codes.csv 안에서 회사 이름으로 "종목코드"(주식시장에서 쓰는 6자리 코드,
    예: 삼성전자 005930)를 찾는 함수. 네이버 금융에서 주가를 조회할 때 이 코드가 필요합니다.
    """
    df = pd.read_csv("corp_codes.csv", dtype=str)
    matched = df[df["corp_name"] == company_name]
    if matched.empty:
        matched = df[df["corp_name"].str.contains(company_name, na=False)]
    if matched.empty:
        return None
    stock_code = matched.iloc[0]["stock_code"]
    if pd.isna(stock_code) or not str(stock_code).strip():
        return None
    return str(stock_code).strip().zfill(6)


@st.cache_data(ttl=1800, show_spinner=False)
def get_financial_data(corp_code, bsns_year, reprt_code, fs_div="CFS"):
    """
    OpenDART '단일회사 전체 재무제표' API를 호출해서
    매출액 / 영업이익 / 당기순이익 / 지배주주순이익만 뽑아서 돌려주는 함수

    corp_code : 회사 고유번호 (find_corp_code로 찾은 값)
    bsns_year : 사업연도, 예) "2025"
    reprt_code: 분기 코드, 예) "11011" (REPRT_CODES 참고)
    fs_div    : "CFS"(연결재무제표, 자회사 실적까지 합친 것) 또는
                "OFS"(개별재무제표, 그 회사 단독 실적만)
    """
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
        "fs_div": fs_div,
    }

    try:
        response = _request_with_retry(url, params)
        data = response.json()
    except requests.exceptions.RequestException:
        # OpenDART 서버에 연결이 안 되거나(네트워크 문제), 응답이 너무 늦는 경우입니다.
        # 재시도까지 했는데도 안 되면, 배포 서버와 OpenDART 사이 네트워크가
        # 일시적으로 불안정한 상태일 가능성이 큽니다.
        return {"오류": "OpenDART 서버 응답이 오지 않습니다. 잠시 후 다시 시도해주세요."}

    # status가 "000"이 아니면 정상 응답이 아니라는 뜻
    if data.get("status") != "000":
        # 작은 회사는 연결재무제표(CFS)가 없는 경우가 있어서, 그럴 땐 개별(OFS)로 한 번 더 시도
        if fs_div == "CFS":
            return get_financial_data(corp_code, bsns_year, reprt_code, fs_div="OFS")
        return {"오류": data.get("message", "데이터를 가져오지 못했습니다.")}

    items = data["list"]

    result = {
        "매출액": None,
        "영업이익": None,
        "당기순이익": None,
        "지배주주순이익": None,
    }

    def pick_amount(item):
        """
        분기·반기보고서의 손익계산서 항목은 thstrm_amount(당기금액)가
        '이번 3개월'만의 금액이고, 그 기간 전체 누적 금액은 thstrm_add_amount에
        따로 들어있습니다. 누적 금액이 있으면 그걸 쓰고, 없으면(연간 보고서 등)
        thstrm_amount를 씁니다.
        """
        add_amount = item.get("thstrm_add_amount")
        if add_amount not in (None, "", "-"):
            return add_amount
        return item.get("thstrm_amount", "")

    # 1차: 손익계산서(IS)·포괄손익계산서(CIS)만 봅니다.
    # 자본변동표(SCE)·재무상태표(BS)·현금흐름표(CF)에도 같은 이름의 계정이
    # 나올 수 있는데, 그건 우리가 찾는 손익 항목이 아니라서 제외합니다.
    for item in items:
        if item.get("sj_div") not in ("IS", "CIS"):
            continue

        name = item.get("account_nm", "")
        detail = item.get("account_detail") or ""

        if result["매출액"] is None and _is_revenue_item(item):
            result["매출액"] = pick_amount(item)

        elif "영업이익" in name and result["영업이익"] is None:
            result["영업이익"] = pick_amount(item)

        elif "순이익" in name:
            # 반기보고서는 "반기순이익(손실)", 분기보고서는 "분기순이익(손실)"처럼
            # 이름이 조금씩 달라서 "순이익"이 들어가는지만 확인합니다.
            if "비지배" in detail:
                continue  # 비지배지분(다른 주주) 몫은 건너뜁니다.
            elif "지배기업" in detail:
                if result["지배주주순이익"] is None:
                    result["지배주주순이익"] = pick_amount(item)
            elif result["당기순이익"] is None:
                # detail이 없는 줄 = 지배주주+비지배지분 다 합친 전체 당기순이익
                result["당기순이익"] = pick_amount(item)

    # 2차 보완: 반기·분기보고서는 손익계산서 안에 지배주주 몫이 따로
    # 안 나오는 경우가 있습니다. 그럴 땐 자본변동표(SCE)의
    # "지배기업 소유주지분 - 이익잉여금" 항목 금액이 같은 값이라 그걸로 대신 찾습니다.
    if result["지배주주순이익"] is None:
        for item in items:
            detail = item.get("account_detail") or ""
            if (
                item.get("sj_div") == "SCE"
                and "순이익" in item.get("account_nm", "")
                and "지배기업" in detail
                and "이익잉여금" in detail
            ):
                result["지배주주순이익"] = item.get("thstrm_amount", "")
                break

    return result


@st.cache_data(ttl=1800, show_spinner=False)
def get_shares_outstanding(corp_code, bsns_year, reprt_code):
    """
    OpenDART '주식의 총수 현황' API로 보통주 유통주식수를 가져옵니다.
    PER(주가수익비율)을 계산하려면 "1주당 얼마를 버는 회사인가"를 알아야 하는데,
    그러려면 순이익을 총 주식 수로 나눠야 해서 이 값이 필요합니다.
    """
    url = "https://opendart.fss.or.kr/api/stockTotqySttus.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
    }

    try:
        response = _request_with_retry(url, params)
        data = response.json()
    except requests.exceptions.RequestException:
        # 여기서 실패해도 재무데이터(매출액 등)는 이미 받아온 뒤라,
        # 유통주식수·PER만 "정보 없음"으로 비워두고 나머지는 정상적으로 보여줍니다.
        return None

    if data.get("status") != "000":
        return None

    for item in data.get("list", []):
        se = item.get("se", "")
        if "보통주" in se:
            raw = item.get("distb_stock_co") or item.get("istc_totqy")
            try:
                return int(str(raw).replace(",", ""))
            except (TypeError, ValueError):
                return None

    return None


def get_per(corp_code, stock_code, bsns_year, reprt_code):
    """
    PER(주가수익비율, 주가가 1주당 순이익의 몇 배인지 보여주는 지표)을 계산합니다.
    PER = 현재 주가 / 주당순이익(EPS)
    주당순이익(EPS) = 지배주주순이익 / 유통주식수

    주의: 사업보고서(연간)가 아닌 분기·반기를 선택하면 지배주주순이익이
    "그 기간까지의 누적" 금액이라, 1년 치가 아니라서 PER이 실제보다
    크게 나올 수 있습니다. PER은 사업보고서(연간) 기준으로 보시는 걸 권장합니다.

    재무데이터·유통주식수·현재가는 서로 다른 서버(OpenDART, 네이버 금융)에
    독립적으로 요청하는 것들이라, 하나씩 순서대로 기다리지 않고 동시에
    요청을 보내서(병렬 처리) 전체 대기 시간을 줄입니다. (셋 중 가장
    느린 응답 하나만큼만 기다리면 되므로, 순서대로 하나씩 기다릴 때보다
    최대 3배 가까이 빨라집니다.)
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        financial_future = executor.submit(
            get_financial_data, corp_code, bsns_year, reprt_code
        )
        shares_future = executor.submit(
            get_shares_outstanding, corp_code, bsns_year, reprt_code
        )
        price_future = (
            executor.submit(get_current_price, stock_code) if stock_code else None
        )

        financial = financial_future.result()
        shares = shares_future.result()
        price = price_future.result() if price_future is not None else None

    if "오류" in financial:
        return financial

    result = dict(financial)
    result["현재가"] = price
    result["유통주식수"] = shares
    result["PER"] = None

    net_income = financial.get("지배주주순이익")
    price = result["현재가"]
    shares = result["유통주식수"]

    try:
        eps = int(net_income) / int(shares)
        if price is not None and eps != 0:
            result["PER"] = round(price / eps, 2)
    except (TypeError, ValueError, ZeroDivisionError):
        pass

    return result


def format_amount(amount):
    """숫자 문자열에 천 단위 콤마를 넣어서 보기 좋게 만드는 함수"""
    try:
        return f"{int(amount):,}원"
    except (TypeError, ValueError):
        return "정보 없음"


if __name__ == "__main__":
    회사이름 = "삼성전자"
    corp_code = find_corp_code(회사이름)

    if corp_code is None:
        print(f"'{회사이름}'을(를) corp_codes.csv에서 찾지 못했습니다.")
    else:
        result = get_financial_data(
            corp_code,
            bsns_year="2025",
            reprt_code=REPRT_CODES["사업보고서(연간)"],
        )

        if "오류" in result:
            print("조회 실패:", result["오류"])
        else:
            print(f"[{회사이름} 2025년 사업보고서]")
            for 항목, 값 in result.items():
                print(f"- {항목}: {format_amount(값)}")
