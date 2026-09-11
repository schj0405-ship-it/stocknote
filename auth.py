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

import streamlit as st
from datetime import datetime, timedelta, timezone
from supabase import create_client
from streamlit_cookies_controller import CookieController

# 로그인 정보를 쿠키에 얼마나 오래 남겨둘지(이 기간 동안은 다시 로그인 안 해도 됩니다).
COOKIE_MAX_AGE_DAYS = 30
COOKIE_ACCESS_NAME = "stocknote_access_token"
COOKIE_REFRESH_NAME = "stocknote_refresh_token"


def _get_cookie_controller():
    """
    브라우저 쿠키를 읽고 쓰는 도구를 하나 만들어 돌려줍니다. 화면이 다시
    그려질 때마다 새로 부르지만, 내부적으로 같은 스레드 안에서는 캐시돼서
    성능에는 문제가 없습니다.
    """
    return CookieController(key="stocknote_cookie_store")


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


def _save_session(user, access_token, refresh_token):
    """
    로그인 정보를 이번 화면(session_state)과, 새로고침해도 남는 브라우저
    쿠키 양쪽에 함께 저장합니다. (session_state만 쓰면 새로고침할 때
    사라지는 게 원래 문제였습니다.)
    """
    st.session_state["user"] = user
    st.session_state["access_token"] = access_token
    st.session_state["refresh_token"] = refresh_token

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
        # access_token은 유효기간이 짧습니다), 최신 값으로 다시 저장해서
        # 로그인이 오래 유지되도록 합니다.
        _save_session(res.user, res.session.access_token, res.session.refresh_token)


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
            if st.button("로그아웃"):
                client = get_supabase_client()
                try:
                    client.auth.sign_out()
                except Exception:
                    pass  # 이미 만료된 세션이어도 어차피 아래에서 로그아웃 처리하므로 무시합니다.
                _clear_session()
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
                            _save_session(
                                res.user, res.session.access_token, res.session.refresh_token
                            )
                            st.rerun()
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
                                _save_session(
                                    res.user, res.session.access_token, res.session.refresh_token
                                )
                                st.success("회원가입이 완료되어 바로 로그인되었습니다.")
                                st.rerun()
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
        st.warning("이 기능은 로그인 후 사용할 수 있습니다. 왼쪽 사이드바에서 로그인하거나 회원가입해주세요.")
        st.stop()

    return st.session_state["user"]
