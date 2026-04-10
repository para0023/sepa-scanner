"""
SEPA Scanner 인증 모듈
- Supabase Auth 기반 로그인/회원가입
- 세션 토큰으로 새로고침 후에도 로그인 유지
- 로컬 모드에서는 인증 건너뛰기 가능
"""

import streamlit as st
from supabase import create_client, Client


def _get_supabase() -> Client:
    """Supabase 클라이언트 (캐싱)"""
    if "supabase_client" not in st.session_state:
        url = st.secrets["connections"]["supabase"]["SUPABASE_URL"]
        key = st.secrets["connections"]["supabase"]["SUPABASE_KEY"]
        st.session_state["supabase_client"] = create_client(url, key)
    return st.session_state["supabase_client"]


def get_supabase() -> Client:
    """외부에서 사용할 Supabase 클라이언트"""
    return _get_supabase()


def _try_restore_session() -> bool:
    """Supabase 클라이언트의 기존 세션으로 인증 복원 시도"""
    if st.session_state.get("authenticated"):
        return True
    try:
        sb = _get_supabase()
        session = sb.auth.get_session()
        if session and session.user:
            st.session_state["authenticated"] = True
            st.session_state["user"] = session.user
            st.session_state["user_id"] = session.user.id
            st.session_state["user_email"] = session.user.email
            return True
    except Exception:
        pass
    return False


def login_page():
    """로그인/회원가입 페이지. 인증 성공 시 True 반환."""
    # 기존 세션 복원 시도
    if _try_restore_session():
        return True

    st.set_page_config(page_title="SEPA Scanner - Login", page_icon="📈", layout="centered")
    st.title("📈 SEPA Scanner")
    st.caption("Specific Entry Point Analysis")

    tab_login, tab_signup = st.tabs(["로그인", "회원가입"])

    sb = _get_supabase()

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("이메일")
            password = st.text_input("비밀번호", type="password")
            submitted = st.form_submit_button("로그인", type="primary", use_container_width=True)

            if submitted:
                if not email or not password:
                    st.error("이메일과 비밀번호를 입력해주세요.")
                else:
                    try:
                        res = sb.auth.sign_in_with_password({"email": email, "password": password})
                        st.session_state["authenticated"] = True
                        st.session_state["user"] = res.user
                        st.session_state["user_id"] = res.user.id
                        st.session_state["user_email"] = res.user.email
                        # access_token 저장 (세션 복원용)
                        if res.session:
                            st.session_state["access_token"] = res.session.access_token
                            st.session_state["refresh_token"] = res.session.refresh_token
                        st.rerun()
                    except Exception as e:
                        err = str(e)
                        if "Invalid login" in err or "invalid" in err.lower():
                            st.error("이메일 또는 비밀번호가 올바르지 않습니다.")
                        else:
                            st.error(f"로그인 실패: {err}")

    with tab_signup:
        with st.form("signup_form"):
            new_email = st.text_input("이메일", key="signup_email")
            new_name = st.text_input("이름 (표시명)", key="signup_name")
            new_pw = st.text_input("비밀번호", type="password", key="signup_pw")
            new_pw2 = st.text_input("비밀번호 확인", type="password", key="signup_pw2")
            signup_submitted = st.form_submit_button("회원가입", type="primary", use_container_width=True)

            if signup_submitted:
                if not new_email or not new_pw:
                    st.error("이메일과 비밀번호를 입력해주세요.")
                elif new_pw != new_pw2:
                    st.error("비밀번호가 일치하지 않습니다.")
                elif len(new_pw) < 6:
                    st.error("비밀번호는 6자 이상이어야 합니다.")
                else:
                    try:
                        res = sb.auth.sign_up({
                            "email": new_email,
                            "password": new_pw,
                            "options": {"data": {"display_name": new_name or new_email.split("@")[0]}}
                        })
                        if res.user:
                            st.success("회원가입 완료! 로그인 탭에서 로그인하세요.")
                        else:
                            st.warning("이메일 확인이 필요할 수 있습니다. 이메일을 확인해주세요.")
                    except Exception as e:
                        st.error(f"회원가입 실패: {e}")

    return False


def logout():
    """로그아웃"""
    try:
        sb = _get_supabase()
        sb.auth.sign_out()
    except Exception:
        pass
    for key in ["authenticated", "user", "user_id", "user_email",
                "supabase_client", "access_token", "refresh_token"]:
        st.session_state.pop(key, None)
    st.rerun()


def get_user_id() -> str:
    """현재 로그인된 사용자 ID 반환"""
    return st.session_state.get("user_id", "")


def is_local_mode() -> bool:
    """로컬 모드 여부. SEPA_LOCAL=1 이면 로컬 (인증 건너뜀)"""
    import os
    # 1) OS 환경변수 우선
    env_val = os.environ.get("SEPA_LOCAL")
    if env_val is not None:
        return env_val == "1"
    # 2) Streamlit secrets에서 확인
    try:
        return st.secrets.get("app", {}).get("SEPA_LOCAL", "1") == "1"
    except Exception:
        return True
