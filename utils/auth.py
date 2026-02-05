# -*- coding: utf-8 -*-
"""
認證工具模組
提供 JWT 認證相關功能 + Cookie 持久化登入

重構說明（2026-02-05）：
- 修復 F5 刷新後跳登入頁的問題
- CookieManager 是非同步的，需要等待頁面渲染後才能讀取
- 使用 session_state 追蹤 Cookie 初始化狀態
- 給予 Cookie 讀取最多 2 次 rerun 機會
"""
import streamlit as st
import requests
from typing import Optional, Dict
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger(__name__)

# Cookie 設定
COOKIE_NAME = "v7_auth"  # Cookie 名稱（與 V5 區分）
COOKIE_EXPIRY_DAYS = 7   # Cookie 過期天數（與 Refresh Token 同步）

# 全局 CookieManager 實例（單例）
_cookie_manager = None


def _get_cookie_manager():
    """
    獲取 Cookie Manager 實例（單例模式）

    使用 extra-streamlit-components 套件
    注意：CookieManager 是非同步的，需要等待頁面渲染
    """
    global _cookie_manager
    if _cookie_manager is not None:
        return _cookie_manager

    try:
        from extra_streamlit_components import CookieManager
        # 使用固定的 key 避免重複創建
        _cookie_manager = CookieManager(key="v7_cookie_manager")
        return _cookie_manager
    except ImportError:
        logger.warning("extra-streamlit-components 未安裝，Cookie 持久化功能將不可用")
        return None
    except Exception as e:
        logger.warning(f"CookieManager 初始化失敗: {e}")
        return None


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
    if 'remember_me' not in st.session_state:
        st.session_state.remember_me = False
    # Cookie 恢復相關狀態
    if 'cookie_restore_attempts' not in st.session_state:
        st.session_state.cookie_restore_attempts = 0
    if 'cookie_restore_done' not in st.session_state:
        st.session_state.cookie_restore_done = False


def is_authenticated() -> bool:
    """檢查用戶是否已認證"""
    return st.session_state.get('user_token') is not None


def require_auth():
    """要求用戶認證，未認證則跳轉到登入頁"""
    if not is_authenticated():
        st.warning("請先登入")
        st.info("請返回首頁進行登入")
        st.stop()


def get_headers() -> Dict[str, str]:
    """獲取 API 請求 headers"""
    if st.session_state.user_token:
        return {"Authorization": f"Bearer {st.session_state.user_token}"}
    return {}


def save_auth_cookie(email: str, refresh_token: str):
    """
    儲存認證資訊到 Cookie

    Args:
        email: 用戶 email
        refresh_token: Refresh Token（用於恢復登入）
    """
    try:
        cookie_manager = _get_cookie_manager()
        if cookie_manager is None:
            return

        # 構建 Cookie 資料
        auth_data = {
            "email": email,
            "refresh_token": refresh_token,
            "saved_at": datetime.now().isoformat()
        }

        # 儲存到 Cookie（JSON 格式）
        cookie_manager.set(
            COOKIE_NAME,
            json.dumps(auth_data),
            expires_at=datetime.now() + timedelta(days=COOKIE_EXPIRY_DAYS)
        )
        logger.info(f"認證 Cookie 已儲存: {email}")

    except Exception as e:
        logger.warning(f"儲存 Cookie 失敗: {e}")


def load_auth_cookie() -> Optional[Dict]:
    """
    從 Cookie 載入認證資訊

    注意：CookieManager 是非同步的，第一次呼叫可能返回 None

    Returns:
        認證資訊字典 {"email": str, "refresh_token": str}
        如果沒有有效 Cookie 則返回 None
    """
    try:
        cookie_manager = _get_cookie_manager()
        if cookie_manager is None:
            return None

        # 讀取 Cookie（非同步，可能需要等待）
        cookie_value = cookie_manager.get(COOKIE_NAME)
        if not cookie_value:
            return None

        # 解析 JSON
        auth_data = json.loads(cookie_value)

        # 驗證必要欄位
        if "email" not in auth_data or "refresh_token" not in auth_data:
            return None

        return auth_data

    except json.JSONDecodeError:
        logger.warning("Cookie 格式錯誤")
        return None
    except Exception as e:
        logger.warning(f"載入 Cookie 失敗: {e}")
        return None


def clear_auth_cookie():
    """清除認證 Cookie"""
    try:
        cookie_manager = _get_cookie_manager()
        if cookie_manager is None:
            return

        cookie_manager.delete(COOKIE_NAME)
        logger.info("認證 Cookie 已清除")

    except Exception as e:
        logger.warning(f"清除 Cookie 失敗: {e}")


def try_restore_session(api_base_url: str) -> bool:
    """
    嘗試從 Cookie 恢復登入狀態

    重要：CookieManager 是非同步的，需要多次嘗試
    - 第一次頁面載入時，Cookie 可能還沒準備好
    - 手機切換 app 回來時，瀏覽器需要更多時間恢復
    - 給予最多 4 次 rerun 機會來讀取 Cookie

    流程：
    1. 檢查是否已經認證（避免重複）
    2. 檢查是否已完成 Cookie 恢復流程
    3. 從 Cookie 讀取 refresh_token
    4. 使用 refresh_token 獲取新的 access_token
    5. 恢復 session state

    Args:
        api_base_url: API 基礎 URL

    Returns:
        是否成功恢復登入
    """
    import time as pytime

    # 如果已經登入，不需要恢復
    if is_authenticated():
        st.session_state.cookie_restore_done = True
        return True

    # 如果已經完成 Cookie 恢復流程（無論成功與否）
    if st.session_state.get('cookie_restore_done'):
        return False

    # 增加嘗試次數
    attempts = st.session_state.get('cookie_restore_attempts', 0)
    st.session_state.cookie_restore_attempts = attempts + 1

    # 最大嘗試次數（手機需要更多時間）
    MAX_ATTEMPTS = 4

    # 從 Cookie 載入認證資訊
    auth_data = load_auth_cookie()

    # CookieManager 是非同步的，第一次可能讀不到
    # 給予最多 MAX_ATTEMPTS 次 rerun 機會
    if auth_data is None:
        if attempts < MAX_ATTEMPTS:
            # 顯示恢復中提示（僅在前幾次嘗試時顯示）
            if attempts >= 1:
                st.info("🔄 正在恢復登入狀態，請稍候...")
                # 給瀏覽器一點時間來初始化 Cookie
                pytime.sleep(0.3)

            logger.info(f"Cookie 讀取嘗試 {attempts + 1}/{MAX_ATTEMPTS}，等待 CookieManager 初始化...")
            st.rerun()
            return False
        else:
            # 已經嘗試 MAX_ATTEMPTS 次，放棄恢復
            st.session_state.cookie_restore_done = True
            logger.info("Cookie 恢復失敗：超過最大嘗試次數")
            return False

    # 成功讀取到 Cookie
    email = auth_data.get("email")
    refresh_token = auth_data.get("refresh_token")

    if not email or not refresh_token:
        st.session_state.cookie_restore_done = True
        return False

    # 使用 refresh_token 獲取新的 access_token
    try:
        response = requests.post(
            f"{api_base_url}/auth/refresh",
            json={"refresh_token": refresh_token},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()

            # 恢復 session state
            st.session_state.user_token = data["access_token"]
            st.session_state.refresh_token = refresh_token
            st.session_state.user_email = email
            st.session_state.remember_me = True
            st.session_state.cookie_restore_done = True

            logger.info(f"Session 已從 Cookie 恢復: {email}")
            return True
        else:
            # Refresh token 已過期或無效，清除 Cookie
            logger.info("Refresh token 已過期，清除 Cookie")
            clear_auth_cookie()
            st.session_state.cookie_restore_done = True
            return False

    except Exception as e:
        logger.warning(f"恢復 Session 失敗: {e}")
        st.session_state.cookie_restore_done = True
        return False


def login(api_base_url: str, email: str, password: str, remember_me: bool = False) -> Dict:
    """
    執行登入

    Args:
        api_base_url: API 基礎 URL
        email: 用戶 email
        password: 密碼
        remember_me: 是否記住登入狀態

    Returns:
        {"success": bool, "message": str}
    """
    try:
        response = requests.post(
            f"{api_base_url}/auth/login",
            json={"email": email, "password": password},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()

            # 儲存到 session state
            st.session_state.user_token = data["access_token"]
            st.session_state.refresh_token = data["refresh_token"]
            st.session_state.user_email = email
            st.session_state.remember_me = remember_me
            st.session_state.cookie_restore_done = True

            # 如果勾選「記住我」，儲存到 Cookie
            if remember_me:
                save_auth_cookie(email, data["refresh_token"])

            return {"success": True, "message": "登入成功"}
        else:
            error = response.json().get("detail", "登入失敗")
            return {"success": False, "message": error}

    except requests.exceptions.Timeout:
        return {"success": False, "message": "連接超時，請稍後再試"}
    except requests.exceptions.ConnectionError:
        return {"success": False, "message": "無法連接伺服器"}
    except Exception as e:
        return {"success": False, "message": f"登入失敗：{str(e)}"}


def logout(api_base_url: str):
    """登出"""
    # 通知後端登出（使 session 失效）
    if st.session_state.refresh_token:
        try:
            requests.post(
                f"{api_base_url}/auth/logout",
                json={"refresh_token": st.session_state.refresh_token},
                timeout=5
            )
        except:
            pass

    # 清除 Cookie
    clear_auth_cookie()

    # 清除 session state
    st.session_state.user_token = None
    st.session_state.user_email = None
    st.session_state.refresh_token = None
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.remember_me = False
    st.session_state.cookie_restore_attempts = 0
    st.session_state.cookie_restore_done = False

    st.success("已登出")
    st.rerun()


def refresh_access_token(api_base_url: str) -> bool:
    """
    刷新 Access Token

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
        st.error(f"Token 刷新失敗：{str(e)}")
        return False


def get_user_info() -> Optional[Dict[str, str]]:
    """
    獲取當前用戶資訊

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
        st.markdown("### 用戶資訊")

        user_info = get_user_info()
        if user_info:
            st.markdown(f"**Email**: {user_info['email']}")
            if user_info['username']:
                st.markdown(f"**用戶名**: {user_info['username']}")

            # 顯示登入狀態
            if st.session_state.get('remember_me'):
                st.caption("已啟用自動登入")

        st.markdown("---")

        if st.button("登出", use_container_width=True, key="sidebar_logout"):
            logout(api_base_url)


def render_login_form(api_base_url: str) -> bool:
    """
    渲染登入表單

    Args:
        api_base_url: API 基礎 URL

    Returns:
        是否登入成功
    """
    st.markdown("#### 用戶登入")

    email = st.text_input("Email", key="login_email")
    password = st.text_input("密碼", type="password", key="login_password")
    remember_me = st.checkbox("記住我（7天內自動登入）", key="login_remember_me")

    if st.button("登入", use_container_width=True, key="login_submit"):
        if not email or not password:
            st.error("請填寫所有欄位")
            return False

        result = login(api_base_url, email, password, remember_me)

        if result["success"]:
            st.success(result["message"])
            st.rerun()
            return True
        else:
            st.error(result["message"])
            return False

    return False
