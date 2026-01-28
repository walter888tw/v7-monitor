"""
認證工具模組
提供 JWT 認證相關功能
"""
import streamlit as st
import requests
from typing import Optional, Dict


def init_session():
    """初始化 session state"""
    if 'user_token' not in st.session_state:
        st.session_state.user_token = None
    if 'user_email' not in st.session_state:
        st.session_state.user_email = None
    if 'refresh_token' not in st.session_state:
        st.session_state.refresh_token = None
    if 'user_id' not in st.session_state:
        st.session_state.user_id = None
    if 'username' not in st.session_state:
        st.session_state.username = None


def is_authenticated() -> bool:
    """檢查用戶是否已認證"""
    return st.session_state.get('user_token') is not None


def require_auth():
    """要求用戶認證，未認證則跳轉到登入頁"""
    if not is_authenticated():
        st.warning("⚠️ 請先登入")
        st.info("👉 請返回首頁進行登入")
        st.stop()


def get_headers() -> Dict[str, str]:
    """獲取 API 請求 headers"""
    if st.session_state.user_token:
        return {"Authorization": f"Bearer {st.session_state.user_token}"}
    return {}


def logout(api_base_url: str):
    """登出"""
    if st.session_state.refresh_token:
        try:
            requests.post(
                f"{api_base_url}/auth/logout",
                json={"refresh_token": st.session_state.refresh_token},
                timeout=5
            )
        except:
            pass

    # 清除 session state
    st.session_state.user_token = None
    st.session_state.user_email = None
    st.session_state.refresh_token = None
    st.session_state.user_id = None
    st.session_state.username = None
    
    st.success("✅ 已登出")
    st.rerun()


def refresh_access_token(api_base_url: str) -> bool:
    """刷新 Access Token
    
    Returns:
        bool: 刷新成功返回 True，失敗返回 False
    """
    if not st.session_state.refresh_token:
        return False
    
    try:
        response = requests.post(
            f"{api_base_url}/auth/refresh",
            json={"refresh_token": st.session_state.refresh_token},
            timeout=5
        )
        
        if response.status_code == 200:
            data = response.json()
            st.session_state.user_token = data["access_token"]
            return True
        else:
            # Refresh token 過期或無效，需要重新登入
            logout(api_base_url)
            return False
    except Exception as e:
        st.error(f"❌ Token 刷新失敗：{str(e)}")
        return False


def get_user_info() -> Optional[Dict[str, str]]:
    """獲取當前用戶資訊
    
    Returns:
        Dict: 用戶資訊字典，包含 email, username, user_id
        None: 未登入
    """
    if not is_authenticated():
        return None
    
    return {
        'email': st.session_state.user_email,
        'username': st.session_state.username,
        'user_id': st.session_state.user_id
    }


def render_user_info_sidebar(api_base_url: str):
    """在側邊欄渲染用戶資訊和登出按鈕"""
    with st.sidebar:
        st.markdown("### 👤 用戶資訊")
        
        user_info = get_user_info()
        if user_info:
            st.markdown(f"**Email**: {user_info['email']}")
            if user_info['username']:
                st.markdown(f"**用戶名**: {user_info['username']}")
        
        st.markdown("---")
        
        if st.button("🚪 登出", use_container_width=True):
            logout(api_base_url)

