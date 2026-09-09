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
REQUEST_TIMEOUT = 10

# 분기(보고서) 코드 - OpenDART가 정해놓은 규칙
REPRT_CODES = {
    "1분기": "11013",
    "반기": "11012",
    "3분기": "11014",
    "사업보고서(연간)": "11011",
}


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
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        data = response.json()
    except requests.exceptions.RequestException:
        # OpenDART 서버에 연결이 안 되거나(네트워크 문제), 응답이 너무 늦는 경우입니다.
        return {"오류": "OpenDART 서버에 연결하지 못했습니다. 잠시 후 다시 시도해주세요."}

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

        if name == "매출액" and result["매출액"] is None:
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
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
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
    """
    financial = get_financial_data(corp_code, bsns_year, reprt_code)
    if "오류" in financial:
        return financial

    result = dict(financial)
    result["현재가"] = None
    result["유통주식수"] = None
    result["PER"] = None

    if stock_code:
        result["현재가"] = get_current_price(stock_code)

    result["유통주식수"] = get_shares_outstanding(corp_code, bsns_year, reprt_code)

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
