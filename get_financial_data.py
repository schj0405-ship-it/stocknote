import re
import time
import random
import threading
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
#
# 15초에서 8초로 줄였습니다. 이유: 지금은 "응답이 아예 안 오는" 상태라
# 오래 기다려봤자 결과가 달라지지 않는데, 기다리는 시간만 길어져서
# 화면이 몇 분씩 멈춰 있었습니다. 실패할 거면 빨리 실패하고 원인을
# 알려주는 편이 낫습니다. (한국에서 정상적으로 응답이 오는 경우는
# 보통 1~3초 안에 옵니다.)
REQUEST_TIMEOUT = 8

# 한 번 실패하면 바로 포기하지 않고 몇 번 더 시도합니다. 매번 같은 간격이
# 아니라 조금씩 더 오래 쉬면서(0.5초→1초 + 약간의 무작위 시간) 다시
# 시도합니다 - 서버가 일시적으로 바빠서 못 받아준 거라면, 똑같은 간격으로
# 계속 두드리는 것보다 이렇게 하는 게 더 잘 통하는 경우가 많습니다.
REQUEST_RETRIES = 2

# "여러 분기 비교" 화면은 최대 8개 분기까지 볼 수 있는데, 그러면 필요한
# 보고서를 여러 개(많으면 6~8개) 동시에 받아오려고 시도합니다. 문제는
# OpenDART 이용약관(제10조)에 "이용횟수에 허용량 제한이 있고, 과도한
# 접속은 서비스가 제한될 수 있다"고 명시돼 있는 점입니다. 그래서 스레드는
# 여러 개를 띄우더라도, 실제로 OpenDART 서버에 동시에 나가는 요청 개수는
# 이 값(2개)을 절대 넘지 않도록 전역으로 막아둡니다. (창구가 2개뿐인
# 은행에 사람이 아무리 많이 줄 서도, 실제 처리는 2명씩만 되는 것과 같은
# 원리입니다.)
_OPENDART_CONCURRENCY_LIMIT = 2
_opendart_semaphore = threading.BoundedSemaphore(_OPENDART_CONCURRENCY_LIMIT)

# 동시 개수를 2개로 막아도, "쉬지 않고 계속" 요청을 보내면 결과적으로
# 초당 요청 횟수 자체가 많아질 수 있습니다. OpenDART가 정확히 초당 몇 건까지
# 허용하는지는 공개돼 있지 않아서, 안전하게 "요청 하나를 보내고 나서 최소
# 이만큼(초)은 쉬었다가 다음 요청을 보낸다"는 규칙을 하나 더 추가합니다.
# (버스가 정류장마다 최소 몇 분 간격을 두고 출발하도록 정해두는 것과
# 비슷합니다 - 정류장 개수(동시 개수 제한)를 줄이는 것과는 별개로,
# 출발 자체도 너무 잦지 않게 만드는 것입니다.)
_MIN_REQUEST_INTERVAL = 0.5
_last_request_lock = threading.Lock()
_last_request_time = [0.0]


def _throttle():
    with _last_request_lock:
        now = time.monotonic()
        wait = _last_request_time[0] + _MIN_REQUEST_INTERVAL - now
        if wait > 0:
            time.sleep(wait)
        _last_request_time[0] = time.monotonic()


# 기본 requests 라이브러리는 "python-requests/2.x"라는 정체를 그대로
# 드러내는 User-Agent(어떤 프로그램이 접속했는지 서버에 알려주는 정보)를
# 보내는데, 일부 서버는 이런 값을 사람이 아닌 프로그램(봇)의 요청으로
# 보고 더 엄격하게 걸러내기도 합니다. 실제 웹 브라우저가 보내는 값과
# 비슷하게 맞춰서, 이런 이유로 막힐 가능성을 줄입니다. (다른 헤더는
# 검증되지 않은 변경이 오히려 새로운 문제를 만들 수 있어 일부러 더
# 건드리지 않았습니다 - 예전에 잘 되던 방식에서 최소한만 바꾸는 게
# 원인을 좁혀나가기에 더 안전합니다.)
_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    }
)


def _describe_error(e):
    """
    오류 메시지를 화면에 보여줘도 안전하도록 다듬습니다. requests 라이브러리가
    만드는 오류 메시지에는 가끔 요청 주소 전체가 그대로 들어있는데, 거기에
    OpenDART 인증키(crtfc_key)가 포함돼 있어서, 그 부분만 가리고 나머지
    (오류 종류 - 시간 초과인지, 연결 거부인지, 응답 코드가 이상한지 등)는
    그대로 보여줘서 다음에 똑같은 문제가 생기면 원인을 바로 알 수 있게 합니다.
    """
    text = re.sub(r"crtfc_key=[^&\s'\"]+", "crtfc_key=***", str(e))
    return f"{type(e).__name__}: {text}"[:200]


def _request_json_with_retry(url, params):
    """
    OpenDART에 요청을 보내고 JSON으로 바꿔서 돌려줍니다.
    - 동시에 실제로 나가는 요청은 _opendart_semaphore가 최대 2개로 막아주고,
      _throttle()이 요청 사이 최소 간격도 지켜줍니다.
    - 연결 실패·시간 초과뿐 아니라, 응답 코드가 200이 아니거나(예: 403·429처럼
      접근이 막혔다는 뜻일 수 있음) 응답이 와도 JSON으로 못 바꾸는 경우도
      같은 방식으로 재시도합니다.
    - 재시도를 다 써도 실패하면, 마지막 오류를 그대로 위로 올려서 호출한
      쪽에서 "왜" 실패했는지(시간 초과/연결 거부/응답 코드 등) 알 수 있게 합니다.
    """
    last_error = None
    for attempt in range(REQUEST_RETRIES):
        with _opendart_semaphore:
            _throttle()
            try:
                response = _SESSION.get(url, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                return response.json()
            except (requests.exceptions.RequestException, ValueError) as e:
                last_error = e
        if attempt < REQUEST_RETRIES - 1:
            time.sleep(0.5 * (attempt + 1) + random.uniform(0, 0.5))
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


class OpenDartError(Exception):
    """OpenDART 조회가 실패했을 때 쓰는 전용 오류 표시입니다(아래 설명 참고)."""


def get_financial_data(corp_code, bsns_year, reprt_code, fs_div="CFS"):
    """
    OpenDART '단일회사 전체 재무제표' API를 호출해서
    매출액 / 영업이익 / 당기순이익 / 지배주주순이익만 뽑아서 돌려주는 함수

    corp_code : 회사 고유번호 (find_corp_code로 찾은 값)
    bsns_year : 사업연도, 예) "2025"
    reprt_code: 분기 코드, 예) "11011" (REPRT_CODES 참고)
    fs_div    : "CFS"(연결재무제표, 자회사 실적까지 합친 것) 또는
                "OFS"(개별재무제표, 그 회사 단독 실적만)

    [중요한 수정 - 실패한 결과를 30분 동안 기억하던 문제]
    예전에는 이 함수 자체에 @st.cache_data(ttl=1800)을 붙여놨습니다. 이건
    "같은 조건으로 다시 물어보면 30분 동안은 저장해둔 답을 그대로 돌려준다"는
    뜻인데, 문제는 성공한 결과뿐 아니라 **실패한 결과(오류 메시지)까지 똑같이
    30분간 저장**했다는 점입니다. 그래서 한 번 조회에 실패하면, 그 사이
    인터넷이 정상으로 돌아와도 30분 동안 계속 같은 실패 메시지만 나왔습니다.
    이번에 구조를 둘로 나눠서, 성공한 결과만 저장하고 실패는 저장하지 않도록
    고쳤습니다(아래 _fetch_financial_data_cached 함수가 실패하면 오류를 밖으로
    던지고, Streamlit은 오류가 난 경우는 저장하지 않습니다).
    """
    try:
        return _fetch_financial_data_cached(corp_code, bsns_year, reprt_code, fs_div)
    except OpenDartError as e:
        return {"오류": str(e)}


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_financial_data_cached(corp_code, bsns_year, reprt_code, fs_div="CFS"):
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
        "fs_div": fs_div,
    }

    try:
        data = _request_json_with_retry(url, params)
    except (requests.exceptions.RequestException, ValueError) as e:
        # OpenDART 서버에 연결이 안 되거나(네트워크 문제), 응답이 너무 늦거나,
        # 응답이 깨져서 못 읽는 경우입니다. 괄호 안 내용은 정확히 "어떤 종류"의
        # 실패인지(시간 초과/연결 거부/응답 코드 오류 등) 알려줘서 원인을
        # 좁히는 데 씁니다(인증키는 자동으로 가려집니다).
        raise OpenDartError(
            f"OpenDART 서버 응답이 오지 않습니다. ({_describe_error(e)})"
        ) from e

    # status가 "000"이 아니면 정상 응답이 아니라는 뜻
    if data.get("status") != "000":
        # 작은 회사는 연결재무제표(CFS)가 없는 경우가 있어서, 그럴 땐 개별(OFS)로 한 번 더 시도
        if fs_div == "CFS":
            return _fetch_financial_data_cached(
                corp_code, bsns_year, reprt_code, fs_div="OFS"
            )
        raise OpenDartError(data.get("message", "데이터를 가져오지 못했습니다."))

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


def get_shares_outstanding(corp_code, bsns_year, reprt_code):
    """
    OpenDART '주식의 총수 현황' API로 보통주 유통주식수를 가져옵니다.
    PER(주가수익비율)을 계산하려면 "1주당 얼마를 버는 회사인가"를 알아야 하는데,
    그러려면 순이익을 총 주식 수로 나눠야 해서 이 값이 필요합니다.

    여기도 위와 같은 이유로, 실패한 결과는 저장(캐시)하지 않도록 두 겹으로
    나눠놨습니다. (실패해도 재무데이터 자체는 보여줘야 해서, 실패하면
    그냥 None을 돌려주고 PER만 "정보 없음"으로 비워둡니다.)
    """
    try:
        return _fetch_shares_outstanding_cached(corp_code, bsns_year, reprt_code)
    except OpenDartError:
        return None


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_shares_outstanding_cached(corp_code, bsns_year, reprt_code):
    url = "https://opendart.fss.or.kr/api/stockTotqySttus.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bsns_year": bsns_year,
        "reprt_code": reprt_code,
    }

    try:
        data = _request_json_with_retry(url, params)
    except (requests.exceptions.RequestException, ValueError) as e:
        raise OpenDartError(_describe_error(e)) from e

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
