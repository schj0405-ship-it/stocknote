"""
로그인/회원가입 화면과, 로그인 상태를 관리하는 함수들을 모아둔 파일입니다.
다른 화면(app.py, pages/ 안의 파일들)에서 이 파일의 함수를 가져다 씁니다.

[새로고침하면 로그인이 풀리던 문제를 고친 방식]
지금까지는 로그인 정보를 st.session_state에만 저장했습니다. 그런데
st.session_state는 "화면을 이리저리 조작할 때"는 유지되지만, 브라우저에서
진짜로 새로고침(F5)을 누르거나 탭을 닫았다가 다시 열면 완전히 새 화면으로
취급되어 깨끗하게 비워집니다. 그래서 로그인이 계속 풀렸던 것입니다.

이 문제를 고치려고, 로그인 정보를 "쿠키"(그 웹사이트가 사용자의 브라우저에
남겨두는 아주 작은 저장공간 - 새로고침은 물론 브라우저를 껐다 켜도 남아있음)
에도 같이 저장해둡니다. 화면이 새로 시작될 때, session_state에 로그인 정보가
없으면 이 쿠키를 먼저 확인해서, 쿠키에 남아있는 정보로 자동으로 다시
로그인 상태를 복원합니다.
"""

import time

import streamlit as st
from datetime import datetime, timedelta, timezone
from supabase import create_client
from streamlit_cookies_controller import CookieController

# 로그인 정보를 쿠키에 얼마나 오래 남겨둘지(이 기간 동안은 다시 로그인 안 해도 됩니다).
COOKIE_MAX_AGE_DAYS = 30
COOKIE_ACCESS_NAME = "stocknote_access_token"
COOKIE_REFRESH_NAME = "stocknote_refresh_token"
COOKIE_STORE_KEY = "stocknote_cookie_store"

# 쿠키를 저장하라고 지시한 뒤, 브라우저가 실제로 그 지시를 받아서 저장할
# 때까지 기다려주는 시간(초)입니다. 아래 _save_session 설명을 참고하세요.
COOKIE_WRITE_WAIT_SECONDS = 1.2


def _get_cookie_controller():
    """
    브라우저 쿠키를 읽고 쓰는 도구를 하나 만들어 돌려줍니다. 화면이 다시
    그려질 때마다 새로 부르지만, 내부적으로 같은 화면 안에서는 재사용돼서
    성능에는 문제가 없습니다.
    """
    return CookieController(key=COOKIE_STORE_KEY)


def read_setting(name, default=None):
    """
    화면에서 사용자가 정해둔 설정값(예: 매도 경고 기준 퍼센트)을 브라우저
    쿠키에서 읽어옵니다. 로그인 정보와 같은 방식이라, 새로고침하거나
    브라우저를 껐다 켜도 값이 남아있습니다.

    아직 브라우저에서 쿠키를 받아오기 전이거나 저장된 값이 없으면
    default(기본값)를 돌려줍니다.
    """
    try:
        controller = _get_cookie_controller()
        value = controller.get(f"stocknote_setting_{name}")
    except Exception:
        return default
    return default if value is None else value


def save_setting(name, value):
    """
    설정값을 브라우저 쿠키에 저장합니다(30일 보관).
    저장에 실패해도 화면 동작은 그대로 이어지도록 조용히 넘어갑니다.
    """
    try:
        controller = _get_cookie_controller()
        expires = datetime.now(timezone.utc) + timedelta(days=COOKIE_MAX_AGE_DAYS)
        controller.set(
            f"stocknote_setting_{name}", value, expires=expires, same_site="lax"
        )
    except Exception:
        pass


def _cookies_loaded():
    """
    브라우저에 저장된 쿠키를 실제로 읽어왔는지 여부입니다.

    쿠키를 읽는 작업은 "서버에서 바로 읽는 것"이 아니라, 서버가 브라우저에게
    "네가 가진 쿠키를 알려줘"라고 요청한 뒤 브라우저의 답이 되돌아와야
    끝납니다. 그래서 화면이 처음 그려지는 순간에는 아직 답이 도착하지 않아
    쿠키가 비어 있는 것처럼 보이고, 답이 도착하면 화면이 자동으로 한 번 더
    그려집니다. 이 함수는 "지금이 그 답을 받기 전인지, 후인지"를 구분해서,
    받기 전에는 '로그인하세요' 대신 '확인 중입니다'라고 보여주는 데 씁니다.
    """
    return COOKIE_STORE_KEY in st.session_state


def get_supabase_client():
    """
    Supabase(클라우드 데이터베이스)에 접속하는 연결 객체를 새로 만듭니다.

    주의: 이 연결 객체를 여러 사용자가 공유하는 변수(예: @st.cache_resource)에
    저장하면 안 됩니다. 그렇게 하면 A가 로그인한 상태로 B의 화면에서도 보이는
    심각한 문제가 생길 수 있습니다. 그래서 화면이 새로고침될 때마다 매번
    새로 만들고, 그 대신 st.session_state(그 사람의 브라우저 탭에서만 유지되는
    저장공간)에 로그인 정보를 저장해뒀다가 다시 연결해주는 방식을 씁니다.
    """
    client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

    access_token = st.session_state.get("access_token")
    refresh_token = st.session_state.get("refresh_token")
    if access_token and refresh_token:
        try:
            client.auth.set_session(access_token, refresh_token)
        except Exception:
            # 저장해둔 로그인 정보가 만료되었거나 잘못된 경우, 로그아웃 상태로 되돌립니다.
            _clear_session()

    return client


def _save_session(user, access_token, refresh_token, write_cookie=True):
    """
    로그인 정보를 이번 화면(session_state)과, 새로고침해도 남는 브라우저
    쿠키 양쪽에 함께 저장합니다. (session_state만 쓰면 새로고침할 때
    사라지는 게 원래 문제였습니다.)

    [지난번에 쿠키 저장이 실제로는 안 됐던 이유]
    controller.set()은 "서버가 브라우저에게 이 값을 쿠키로 저장해달라고
    지시를 보내는" 동작입니다. 지시가 화면에 실려서 브라우저까지 도착하고,
    브라우저가 그걸 실행해야 비로소 쿠키가 저장됩니다. 그런데 지난 코드는
    set()을 부른 직후에 곧바로 st.rerun()(화면 처음부터 다시 그리기)을
    실행했습니다. 화면을 다시 그리면 아직 전달되지 않은 지시는 사라져버려서,
    쿠키가 저장되기 전에 지시가 취소되는 상태였습니다. 그래서 로그인은
    되는데 새로고침하면 항상 풀렸던 것입니다.
    → 이번에는 set() 다음에 아주 잠깐(1.2초) 기다렸다가 화면을 다시 그리도록
      고쳤습니다(아래 _finish_login 함수).
    """
    st.session_state["user"] = user
    st.session_state["access_token"] = access_token
    st.session_state["refresh_token"] = refresh_token

    if not write_cookie:
        return

    controller = _get_cookie_controller()
    expires = datetime.now(timezone.utc) + timedelta(days=COOKIE_MAX_AGE_DAYS)
    try:
        controller.set(COOKIE_ACCESS_NAME, access_token, expires=expires, same_site="lax")
        controller.set(COOKIE_REFRESH_NAME, refresh_token, expires=expires, same_site="lax")
    except Exception:
        # 쿠키 저장이 실패해도(예: 브라우저가 쿠키를 막아둔 경우), 지금 이
        # 화면에서 로그인 자체는 정상 진행되도록 조용히 넘어갑니다. 다만
        # 이 경우 새로고침하면 다시 로그인해야 합니다.
        pass


def _finish_login(user, access_token, refresh_token):
    """
    로그인에 성공한 직후에 부르는 함수입니다. 순서가 중요합니다.

    1. 로그인 정보를 session_state와 쿠키에 저장하라고 지시합니다.
    2. 브라우저가 그 지시를 받아 쿠키를 실제로 저장할 시간을 잠깐 줍니다.
       (이 기다림이 없으면 쿠키가 저장되기 전에 화면이 다시 그려져서,
        새로고침했을 때 로그인이 풀립니다.)
    3. 그 다음에 화면을 다시 그려서 로그인된 상태로 바꿉니다.
    """
    _save_session(user, access_token, refresh_token)
    with st.spinner("로그인 상태를 저장하는 중입니다..."):
        time.sleep(COOKIE_WRITE_WAIT_SECONDS)
    st.rerun()


def _clear_session():
    st.session_state["user"] = None
    st.session_state["access_token"] = None
    st.session_state["refresh_token"] = None

    try:
        controller = _get_cookie_controller()
        controller.remove(COOKIE_ACCESS_NAME)
        controller.remove(COOKIE_REFRESH_NAME)
    except Exception:
        pass


def _restore_session_from_cookie():
    """
    화면이 새로 시작됐는데(예: 새로고침) session_state에 로그인 정보가 없으면,
    브라우저 쿠키에 저장해둔 로그인 정보로 다시 로그인 상태를 복원해봅니다.
    쿠키가 아예 없으면(로그인한 적이 없거나, 로그아웃한 상태) 아무 일도
    하지 않고 조용히 넘어갑니다.
    """
    if st.session_state.get("user"):
        return  # 이미 로그인돼 있으면 다시 할 필요 없음

    try:
        controller = _get_cookie_controller()
        access_token = controller.get(COOKIE_ACCESS_NAME)
        refresh_token = controller.get(COOKIE_REFRESH_NAME)
    except Exception:
        return

    if not access_token or not refresh_token:
        return

    client = create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])
    try:
        res = client.auth.set_session(access_token, refresh_token)
    except Exception:
        # 쿠키에 남아있던 로그인 정보가 만료됐거나 잘못된 경우입니다.
        # 다시 로그인해달라고 해야 하므로, 남아있는 쿠키를 정리합니다.
        _clear_session()
        return

    if res and res.user and res.session:
        # set_session이 access_token을 새로 갱신해줬을 수도 있어서(원래
        # access_token은 유효기간이 짧습니다), 값이 바뀐 경우에만 쿠키를
        # 다시 저장합니다. 바뀌지 않았는데도 매번 저장을 지시하면 화면이
        # 그려질 때마다 불필요한 작업이 반복됩니다.
        changed = (
            res.session.access_token != access_token
            or res.session.refresh_token != refresh_token
        )
        _save_session(
            res.user,
            res.session.access_token,
            res.session.refresh_token,
            write_cookie=changed,
        )


def render_auth_ui():
    """
    화면 왼쪽 사이드바에 로그인/회원가입/로그아웃 UI를 그립니다.
    모든 페이지(app.py, pages/ 안의 파일들) 맨 위에서 한 번씩 불러주면 됩니다.
    """
    if "user" not in st.session_state:
        st.session_state["user"] = None

    # 새로고침으로 session_state가 비어있는 경우, 쿠키로 로그인 상태를 먼저 복원해봅니다.
    _restore_session_from_cookie()

    with st.sidebar:
        st.divider()

        if st.session_state["user"]:
            st.write(f"👤 {st.session_state['user'].email}")
            st.caption("이 브라우저에서는 30일 동안 로그인이 유지됩니다.")
            if st.button("로그아웃"):
                client = get_supabase_client()
                try:
                    client.auth.sign_out()
                except Exception:
                    pass  # 이미 만료된 세션이어도 어차피 아래에서 로그아웃 처리하므로 무시합니다.
                _clear_session()
                # 로그인할 때와 같은 이유로, 브라우저가 "쿠키를 지우라"는
                # 지시를 실제로 받아서 처리할 시간을 잠깐 줘야 합니다.
                # 안 그러면 쿠키가 남아있어서 새로고침 시 다시 로그인됩니다.
                with st.spinner("로그아웃하는 중입니다..."):
                    time.sleep(COOKIE_WRITE_WAIT_SECONDS)
                st.rerun()
        else:
            st.subheader("로그인 / 회원가입")
            tab_login, tab_signup = st.tabs(["로그인", "회원가입"])

            with tab_login:
                login_email = st.text_input("이메일", key="login_email_input")
                login_password = st.text_input(
                    "비밀번호", type="password", key="login_password_input"
                )
                if st.button("로그인", key="login_button"):
                    if not login_email or not login_password:
                        st.error("이메일과 비밀번호를 모두 입력해주세요.")
                    else:
                        client = get_supabase_client()
                        try:
                            res = client.auth.sign_in_with_password(
                                {"email": login_email, "password": login_password}
                            )
                            _finish_login(
                                res.user, res.session.access_token, res.session.refresh_token
                            )
                        except Exception as e:
                            st.error(f"로그인 실패: 이메일 또는 비밀번호를 확인해주세요. ({e})")

            with tab_signup:
                signup_email = st.text_input("이메일", key="signup_email_input")
                signup_password = st.text_input(
                    "비밀번호 (6자 이상)", type="password", key="signup_password_input"
                )
                if st.button("회원가입", key="signup_button"):
                    if not signup_email or not signup_password:
                        st.error("이메일과 비밀번호를 모두 입력해주세요.")
                    elif len(signup_password) < 6:
                        st.error("비밀번호는 6자 이상이어야 합니다.")
                    else:
                        client = get_supabase_client()
                        try:
                            res = client.auth.sign_up(
                                {"email": signup_email, "password": signup_password}
                            )
                            if res.session:
                                # Supabase 프로젝트 설정에서 "이메일 인증"이 꺼져있는 경우,
                                # 회원가입과 동시에 바로 로그인까지 됩니다.
                                st.success("회원가입이 완료되어 바로 로그인되었습니다.")
                                _finish_login(
                                    res.user, res.session.access_token, res.session.refresh_token
                                )
                            else:
                                st.success(
                                    "회원가입 신청이 완료되었습니다. "
                                    "받으신 이메일의 인증 링크를 눌러야 로그인할 수 있어요."
                                )
                        except Exception as e:
                            st.error(f"회원가입 실패: {e}")


def require_login():
    """
    로그인이 꼭 필요한 화면의 맨 위에서 불러주는 함수입니다.
    - 사이드바에 로그인/회원가입 UI를 그리고,
    - 로그인이 안 되어 있으면 안내 문구만 보여주고 화면 실행을 그 자리에서 멈춥니다(st.stop()).
    - 로그인이 되어 있으면 로그인한 사용자 정보를 돌려줍니다.
    """
    render_auth_ui()

    if not st.session_state.get("user"):
        if not _cookies_loaded():
            # 아직 브라우저에서 쿠키를 읽어오기 전(화면이 막 열린 직후)입니다.
            # 이때 "로그인하세요"라고 하면, 실제로는 로그인 유지 중인데도
            # 잠깐 로그아웃된 것처럼 보여서 헷갈립니다.
            st.info("로그인 상태를 확인하는 중입니다... 잠시만 기다려주세요.")
        else:
            st.warning(
                "이 기능은 로그인 후 사용할 수 있습니다. 왼쪽 사이드바에서 로그인하거나 회원가입해주세요."
            )
        st.stop()

    return st.session_state["user"]
