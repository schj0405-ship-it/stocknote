"""
연결 진단 화면입니다.

왜 이 화면이 필요한가:
지금까지 "재무데이터가 안 나온다"는 문제를 고칠 때마다, 실제 원인을 볼 수
없어서 추측으로 대응해왔습니다(시간 초과 늘리기, 재시도 추가, 동시 요청
줄이기 등). 하지만 배포된 서버(미국에 있는 Streamlit Cloud) 안에서 실제로
무슨 일이 일어나는지 직접 보지 못하면, 계속 추측만 반복하게 됩니다.

이 화면은 그 서버 안에서 직접 아래 항목들을 순서대로 측정해서, 어느 단계에서
막히는지 정확히 짚어줍니다.

  1단계. 이 서버가 인터넷 자체에 연결되는가?
  2단계. 이 서버는 어느 나라에서 실행 중인가? (해외 차단 여부 판단용)
  3단계. opendart.fss.or.kr 주소를 IP로 바꿀 수 있는가? (DNS)
  4단계. 그 IP의 443번 문(포트)에 연결이 되는가? (TCP)
  5단계. 인증키 없이 보낸 요청에 OpenDART가 대답을 하는가? (서버 도달 확인)
  6단계. 실제 인증키로 삼성전자 데이터를 받아올 수 있는가?
  7단계. 네이버 금융(주가 담당)에는 연결되는가?

각 단계마다 걸린 시간과 결과를 그대로 보여줍니다. 문제를 다 고치고 나면
이 파일은 지워도 됩니다(pages 폴더에서 삭제하면 메뉴에서 사라집니다).
"""

import json
import socket
import time

import requests
import streamlit as st

st.set_page_config(page_title="스톡노트 - 연결 진단", layout="wide")

st.title("연결 진단")
st.caption(
    "배포된 서버에서 OpenDART·네이버까지 실제로 연결이 되는지 단계별로 확인합니다. "
    "인증키는 화면에 절대 표시되지 않습니다."
)

OPENDART_HOST = "opendart.fss.or.kr"
OPENDART_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
SAMSUNG_CORP_CODE = "00126380"  # 삼성전자 (OpenDART 고유번호)
SHORT_TIMEOUT = 8


def _run(label, func):
    """
    한 단계를 실행하고, 걸린 시간과 결과(또는 오류)를 화면에 보여줍니다.
    반환값: (성공 여부, 결과 또는 오류 객체)
    """
    start = time.time()
    try:
        result = func()
        elapsed = time.time() - start
        st.success(f"✅ {label} — 성공 ({elapsed:.1f}초)")
        if result:
            st.code(str(result), language="text")
        return True, result
    except Exception as e:
        elapsed = time.time() - start
        st.error(f"❌ {label} — 실패 ({elapsed:.1f}초)")
        st.code(f"{type(e).__name__}: {e}", language="text")
        return False, e


def step1_internet():
    r = requests.get("https://www.google.com/generate_204", timeout=SHORT_TIMEOUT)
    return f"응답 코드 {r.status_code}"


def step2_where_am_i():
    r = requests.get("https://ipinfo.io/json", timeout=SHORT_TIMEOUT)
    info = r.json()
    # IP 주소 뒷부분은 가려서 보여줍니다(굳이 전부 드러낼 필요가 없어서).
    ip = str(info.get("ip", ""))
    masked_ip = ".".join(ip.split(".")[:2] + ["*", "*"]) if ip.count(".") == 3 else "(확인 불가)"
    return (
        f"서버 위치: {info.get('country', '?')} / {info.get('region', '?')} / {info.get('city', '?')}\n"
        f"서버 IP(일부 가림): {masked_ip}\n"
        f"통신사(ISP): {info.get('org', '?')}"
    )


def step3_dns():
    infos = socket.getaddrinfo(OPENDART_HOST, 443, proto=socket.IPPROTO_TCP)
    ips = sorted({item[4][0] for item in infos})
    st.session_state["_diag_opendart_ips"] = ips
    return f"{OPENDART_HOST} → {', '.join(ips)}"


def step4_tcp():
    ips = st.session_state.get("_diag_opendart_ips") or []
    if not ips:
        raise RuntimeError("앞 단계(DNS)가 실패해서 연결할 IP를 모릅니다.")
    ip = ips[0]
    sock = socket.create_connection((ip, 443), timeout=SHORT_TIMEOUT)
    sock.close()
    return f"{ip}:443 연결 성공"


def step5_opendart_no_key():
    """
    일부러 잘못된 인증키로 요청을 보냅니다. 인증키가 틀렸더라도 OpenDART 서버가
    살아있고 연결이 된다면, "등록되지 않은 키입니다" 같은 답을 정상적으로
    돌려줍니다. 즉 이 단계가 성공하면 "서버까지 도달은 된다"는 뜻이고,
    실패하면 "아예 도달을 못 한다"는 뜻입니다.
    """
    params = {
        "crtfc_key": "0000000000000000000000000000000000000000",
        "corp_code": SAMSUNG_CORP_CODE,
        "bsns_year": "2025",
        "reprt_code": "11011",
        "fs_div": "CFS",
    }
    r = requests.get(OPENDART_URL, params=params, timeout=SHORT_TIMEOUT)
    body = r.json()
    return (
        f"응답 코드 {r.status_code}\n"
        f"OpenDART status: {body.get('status')}\n"
        f"OpenDART message: {body.get('message')}"
    )


def step6_opendart_real_key():
    """실제 인증키로 삼성전자 2025년 사업보고서를 요청합니다(데이터는 개수만 표시)."""
    params = {
        "crtfc_key": st.secrets["DART_API_KEY"],
        "corp_code": SAMSUNG_CORP_CODE,
        "bsns_year": "2025",
        "reprt_code": "11011",
        "fs_div": "CFS",
    }
    r = requests.get(OPENDART_URL, params=params, timeout=SHORT_TIMEOUT)
    body = r.json()
    status = body.get("status")
    message = body.get("message")
    count = len(body.get("list", []) or [])
    return (
        f"응답 코드 {r.status_code}\n"
        f"OpenDART status: {status} ({message})\n"
        f"받아온 계정 항목 수: {count}개"
    )


def step7_naver():
    url = f"https://finance.naver.com/item/sise_day.naver?code=005930&page=1"
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(url, headers=headers, timeout=SHORT_TIMEOUT)
    return f"응답 코드 {r.status_code} / 받은 문서 길이 {len(r.text):,}자"


st.info(
    "아래 버튼을 누르면 진단이 시작됩니다. 전부 합쳐 최대 1분 정도 걸릴 수 있습니다."
)

if st.button("진단 시작", type="primary"):
    results = {}

    st.subheader("1단계. 인터넷 연결 (구글)")
    results["internet"] = _run("인터넷 연결", step1_internet)[0]

    st.subheader("2단계. 이 서버가 어디에서 실행 중인지")
    results["location"] = _run("서버 위치 확인", step2_where_am_i)[0]

    st.subheader("3단계. OpenDART 주소 찾기 (DNS)")
    results["dns"] = _run("DNS 조회", step3_dns)[0]

    st.subheader("4단계. OpenDART 서버에 연결 (TCP 443)")
    results["tcp"] = _run("TCP 연결", step4_tcp)[0]

    st.subheader("5단계. OpenDART 응답 확인 (인증키 없이)")
    results["reachable"] = _run("OpenDART 응답", step5_opendart_no_key)[0]

    st.subheader("6단계. 실제 인증키로 삼성전자 데이터 요청")
    results["real"] = _run("실제 조회", step6_opendart_real_key)[0]

    st.subheader("7단계. 네이버 금융 연결 (주가)")
    results["naver"] = _run("네이버 금융", step7_naver)[0]

    # ------------------------------------------------------------------
    # 결과 해석: 어느 단계에서 막혔는지에 따라 원인이 달라집니다.
    # ------------------------------------------------------------------
    st.divider()
    st.subheader("진단 결과 해석")

    if not results["internet"]:
        st.error(
            "이 서버가 인터넷 자체에 연결되지 않고 있습니다. Streamlit Cloud 쪽 "
            "장애일 가능성이 큽니다. 잠시 후 다시 시도하거나 앱을 재시작(Reboot)해보세요."
        )
    elif not results["dns"]:
        st.error(
            "opendart.fss.or.kr 주소를 IP로 바꾸는 단계(DNS)에서 실패했습니다. "
            "이건 코드 문제가 아니라 서버의 이름 조회 설정 문제입니다."
        )
    elif not results["tcp"]:
        st.error(
            "OpenDART 서버의 IP까지는 알아냈지만, 연결 자체가 안 됩니다.\n\n"
            "가장 유력한 원인은 **OpenDART(금융감독원) 쪽에서 해외 서버의 접속을 "
            "막고 있는 것**입니다. 한국 공공기관 서비스는 해외 IP를 차단하는 경우가 "
            "흔하고, 이 앱은 미국에 있는 Streamlit Cloud에서 실행됩니다.\n\n"
            "이 경우 코드를 어떻게 고쳐도 해결되지 않습니다. 해결 방향은 "
            "①내 컴퓨터에서 실행해서 쓰기 ②한국에 있는 서버로 옮기기 "
            "③한국에 있는 중계 서버(프록시)를 거치기 중 하나입니다."
        )
    elif not results["reachable"]:
        st.error(
            "연결은 되는데 OpenDART가 정상적인 답을 주지 않습니다. 방화벽이나 "
            "보안 장비가 요청을 중간에서 차단하고 있을 가능성이 큽니다."
        )
    elif not results["real"]:
        st.warning(
            "서버까지 연결은 잘 되는데, 실제 인증키로 보낸 요청만 실패했습니다. "
            "인증키가 만료됐거나 하루 사용량을 초과했을 수 있습니다. "
            "OpenDART 홈페이지에서 인증키 상태를 확인해보세요."
        )
    else:
        st.success(
            "모든 단계가 정상입니다. 지금 이 순간에는 OpenDART 연결에 문제가 없습니다.\n\n"
            "그런데도 재무데이터 조회가 실패한다면, 원인은 '연결 자체'가 아니라 "
            "짧은 시간에 요청이 몰릴 때만 생기는 문제(속도 제한)일 가능성이 큽니다. "
            "이 경우 '비교할 분기 개수'를 2~3개로 줄여서 조회해보세요."
        )

    st.caption(
        "이 결과 화면을 그대로 캡처해서 보여주시면, 남은 조치를 정확하게 결정할 수 있습니다."
    )
