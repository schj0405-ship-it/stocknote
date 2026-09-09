"""
로그인/회원가입 화면과, 로그인 상태를 관리하는 함수들을 모아둔 파일입니다.
다른 화면(app.py, pages/ 안의 파일들)에서 이 파일의 함수를 가져다 씁니다.
"""

import streamlit as st
from supabase import create_client


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


def _clear_session():
    st.session_state["user"] = None
    st.session_state["access_token"] = None
    st.session_state["refresh_token"] = None


def render_auth_ui():
    """
    화면 왼쪽 사이드바에 로그인/회원가입/로그아웃 UI를 그립니다.
    모든 페이지(app.py, pages/ 안의 파일들) 맨 위에서 한 번씩 불러주면 됩니다.
    """
    if "user" not in st.session_state:
        st.session_state["user"] = None

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
                            st.session_state["user"] = res.user
                            st.session_state["access_token"] = res.session.access_token
                            st.session_state["refresh_token"] = res.session.refresh_token
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
                                st.session_state["user"] = res.user
                                st.session_state["access_token"] = res.session.access_token
                                st.session_state["refresh_token"] = res.session.refresh_token
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
