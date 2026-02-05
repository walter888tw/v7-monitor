# -*- coding: utf-8 -*-
"""
認證工具模組 v3.0
提供 JWT 認證相關功能 + 多層持久化登入

v3.0 重構說明（2026-02-05）：
==================================
根本問題發現：
1. Streamlit Cloud 在 iframe 沙箱中運行
2. localStorage 存在 iframe 內部，頁面重載可能丟失
3. streamlit-js-eval 第一次調用總是返回 None

解決方案（按優先順序）：
1. st.query_params - URL 參數存儲（不受 iframe 限制，最可靠）
2. CookieManager - Cookie 存儲（作為備援）
3. 移除 localStorage 依賴（在 Streamlit Cloud 不可靠）

參考資料：
- https://dev.to/hendrixaidev/how-i-solved-streamlit-session-persistence-after-3-failed-attempts-b4c
- https://docs.streamlit.io/develop/api-reference/caching-and-state/st.query_params
"""
import streamlit as st
import streamlit.components.v1 as components
import requests
from typing import Optional, Dict
from datetime import datetime, timedelta
import json
import logging
import hashlib
import base64

logger = logging.getLogger(__name__)

# === 常量配置 ===
COOKIE_NAME = "v7_auth"  # Cookie 名稱
QUERY_PARAM_KEY = "auth"  # URL 參數鍵名
COOKIE_EXPIRY_DAYS = 7  # Cookie 過期天數
MAX_RESTORE_ATTEMPTS = 3  # 最大恢復嘗試次數

# 全局 CookieManager 實例（單例）
_cookie_manager = None


def _get_cookie_manager():
    """獲取 Cookie Manager 實例（單例模式）"""
    global _cookie_manager
    if _cookie_manager is not None:
        return _cookie_manager

    try:
        from extra_streamlit_components import CookieManager
        _cookie_manager = CookieManager(key="v7_cookie_manager_v3")
        return _cookie_manager
    except ImportError:
        logger.warning("extra-streamlit-components 未安裝，Cookie 持久化功能將不可用")
        return None
    except Exception as e:
        logger.warning(f"CookieManager 初始化失敗: {e}")
        return None


# ==================== Session 初始化 ====================

def init_session():
    """初始化 session state"""
    defaults = {
        'user_token': None,
        'user_email': None,
        'refresh_token': None,
        'user_id': None,
        'username': None,
        'remember_me': False,
        # 恢復相關狀態
        'auth_restore_done': False,
        'auth_restore_attempts': 0,
    }
    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


def is_authenticated() -> bool:
    """檢查用戶是否已認證"""
    return st.session_state.get('user_token') is not None


def require_auth():
    """要求用戶認證，未認證則跳轉到登入頁"""
    if not is_authenticated():
        st.warning("請先登入")
        st.stop()


def get_headers() -> Dict[str, str]:
    """獲取 API 請求 headers"""
    if st.session_state.user_token:
        return {"Authorization": f"Bearer {st.session_state.user_token}"}
    return {}


# ==================== 認證數據編碼/解碼 ====================

def _encode_auth_data(email: str, refresh_token: str) -> str:
    """
    將認證數據編碼為 URL 安全字串

    格式：base64(json({email, token, checksum}))
    """
    checksum = hashlib.sha256(f"{email}:{refresh_token}".encode()).hexdigest()[:8]
    data = {
        "e": email,
        "t": refresh_token,
        "c": checksum,
        "ts": datetime.now().isoformat()
    }
    json_str = json.dumps(data, separators=(',', ':'))
    # 使用 URL 安全的 base64 編碼
    encoded = base64.urlsafe_b64encode(json_str.encode()).decode()
    return encoded


def _decode_auth_data(encoded: str) -> Optional[Dict]:
    """
    解碼認證數據

    Returns:
        {"email": str, "refresh_token": str} 或 None
    """
    try:
        json_str = base64.urlsafe_b64decode(encoded.encode()).decode()
        data = json.loads(json_str)

        email = data.get("e")
        refresh_token = data.get("t")
        checksum = data.get("c")

        if not email or not refresh_token:
            return None

        # 驗證校驗碼
        expected = hashlib.sha256(f"{email}:{refresh_token}".encode()).hexdigest()[:8]
        if checksum != expected:
            logger.warning("認證數據校驗失敗")
            return None

        return {"email": email, "refresh_token": refresh_token}
    except Exception as e:
        logger.debug(f"解碼認證數據失敗: {e}")
        return None


# ==================== 存儲層（多層備援） ====================

def save_auth_data(email: str, refresh_token: str):
    """
    保存認證數據（多層存儲）

    優先順序：
    1. st.query_params - URL 參數（最可靠，不受 iframe 限制）
    2. Cookie - 作為備援
    """
    encoded = _encode_auth_data(email, refresh_token)

    # 1. 保存到 URL 參數（主要）
    try:
        st.query_params[QUERY_PARAM_KEY] = encoded
        logger.info(f"認證數據已存入 URL 參數: {email}")
    except Exception as e:
        logger.warning(f"URL 參數存儲失敗: {e}")

    # 2. 保存到 Cookie（備援）
    try:
        cookie_manager = _get_cookie_manager()
        if cookie_manager:
            expires_at = datetime.now() + timedelta(days=COOKIE_EXPIRY_DAYS)
            cookie_manager.set(COOKIE_NAME, encoded, expires_at=expires_at)
            logger.info(f"認證數據已存入 Cookie: {email}")
    except Exception as e:
        logger.warning(f"Cookie 存儲失敗: {e}")


def load_auth_data() -> Optional[Dict]:
    """
    讀取認證數據（多層讀取）

    優先順序：
    1. st.query_params - URL 參數
    2. Cookie

    Returns:
        {"email": str, "refresh_token": str} 或 None
    """
    # 1. 從 URL 參數讀取（優先）
    try:
        encoded = st.query_params.get(QUERY_PARAM_KEY)
        if encoded:
            auth_data = _decode_auth_data(encoded)
            if auth_data:
                logger.info("從 URL 參數讀取認證數據成功")
                return auth_data
    except Exception as e:
        logger.debug(f"URL 參數讀取失敗: {e}")

    # 2. 從 Cookie 讀取（備援）
    try:
        cookie_manager = _get_cookie_manager()
        if cookie_manager:
            encoded = cookie_manager.get(COOKIE_NAME)
            if encoded:
                auth_data = _decode_auth_data(encoded)
                if auth_data:
                    logger.info("從 Cookie 讀取認證數據成功")
                    # 同步到 URL 參數
                    try:
                        st.query_params[QUERY_PARAM_KEY] = encoded
                    except:
                        pass
                    return auth_data
    except Exception as e:
        logger.debug(f"Cookie 讀取失敗: {e}")

    return None


def clear_auth_data():
    """清除所有認證存儲"""
    # 清除 URL 參數
    try:
        if QUERY_PARAM_KEY in st.query_params:
            del st.query_params[QUERY_PARAM_KEY]
        logger.info("URL 參數已清除")
    except Exception as e:
        logger.debug(f"URL 參數清除失敗: {e}")

    # 清除 Cookie
    try:
        cookie_manager = _get_cookie_manager()
        if cookie_manager:
            cookie_manager.delete(COOKIE_NAME)
            logger.info("Cookie 已清除")
    except Exception as e:
        logger.debug(f"Cookie 清除失敗: {e}")


# ==================== Token 管理 ====================

def refresh_access_token(api_base_url: str, refresh_token: str) -> Optional[str]:
    """
    刷新 Access Token

    Args:
        api_base_url: API 基礎 URL
        refresh_token: Refresh Token

    Returns:
        新的 Access Token，失敗返回 None
    """
    try:
        response = requests.post(
            f"{api_base_url}/auth/refresh",
            json={"refresh_token": refresh_token},
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()
            return data.get("access_token")
        else:
            logger.warning(f"Token 刷新失敗: HTTP {response.status_code}")
            return None
    except requests.exceptions.Timeout:
        logger.warning("Token 刷新超時")
        return None
    except requests.exceptions.ConnectionError:
        logger.warning("無法連接伺服器")
        return None
    except Exception as e:
        logger.warning(f"Token 刷新失敗: {e}")
        return None


# ==================== 恢復機制 ====================

def try_restore_session(api_base_url: str) -> bool:
    """
    嘗試恢復登入狀態（v3.0）

    流程：
    1. 檢查是否已登入
    2. 從多層存儲讀取認證數據
    3. 使用 refresh_token 獲取新的 access_token
    4. 恢復 session state

    設計原則：
    - 最多嘗試 3 次（使用 session_state 計數）
    - 每次嘗試都完整執行讀取 + API 調用
    - 失敗後直接進入登入頁，不無限循環

    Args:
        api_base_url: API 基礎 URL

    Returns:
        是否成功恢復
    """
    # 如果已經登入，不需要恢復
    if is_authenticated():
        st.session_state.auth_restore_done = True
        return True

    # 如果已完成恢復流程
    if st.session_state.get('auth_restore_done'):
        return False

    # 檢查嘗試次數
    attempts = st.session_state.get('auth_restore_attempts', 0)
    st.session_state.auth_restore_attempts = attempts + 1

    if attempts >= MAX_RESTORE_ATTEMPTS:
        logger.info(f"恢復嘗試已達上限 ({MAX_RESTORE_ATTEMPTS})")
        st.session_state.auth_restore_done = True
        return False

    # 讀取認證數據
    auth_data = load_auth_data()

    if auth_data is None:
        # 第一次可能讀不到（CookieManager 非同步）
        # 使用 st.rerun() 觸發第二次嘗試，但有上限保護
        if attempts < MAX_RESTORE_ATTEMPTS - 1:
            logger.info(f"嘗試 {attempts + 1}/{MAX_RESTORE_ATTEMPTS}：等待數據載入...")
            import time
            time.sleep(0.3)  # 短暫等待
            st.rerun()
            return False
        else:
            logger.info("無法讀取認證數據，進入登入頁")
            st.session_state.auth_restore_done = True
            return False

    # 獲取 email 和 refresh_token
    email = auth_data.get("email")
    refresh_token = auth_data.get("refresh_token")

    if not email or not refresh_token:
        st.session_state.auth_restore_done = True
        return False

    # 調用 API 刷新 token
    access_token = refresh_access_token(api_base_url, refresh_token)

    if access_token:
        # 恢復成功
        st.session_state.user_token = access_token
        st.session_state.refresh_token = refresh_token
        st.session_state.user_email = email
        st.session_state.remember_me = True
        st.session_state.auth_restore_done = True
        logger.info(f"登入狀態已恢復: {email}")
        return True
    else:
        # Token 過期或無效，清除存儲
        logger.info("Refresh token 已過期，清除存儲")
        clear_auth_data()
        st.session_state.auth_restore_done = True
        return False


# ==================== 登入/登出 ====================

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
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()

            # 儲存到 session state
            st.session_state.user_token = data["access_token"]
            st.session_state.refresh_token = data["refresh_token"]
            st.session_state.user_email = email
            st.session_state.remember_me = remember_me
            st.session_state.auth_restore_done = True

            # 如果勾選「記住我」，保存到持久化存儲
            if remember_me:
                save_auth_data(email, data["refresh_token"])

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
    """
    登出

    Args:
        api_base_url: API 基礎 URL
    """
    # 通知後端登出
    if st.session_state.get('refresh_token'):
        try:
            requests.post(
                f"{api_base_url}/auth/logout",
                json={"refresh_token": st.session_state.refresh_token},
                timeout=5
            )
        except Exception:
            pass

    # 清除持久化存儲
    clear_auth_data()

    # 清除 session state
    st.session_state.user_token = None
    st.session_state.user_email = None
    st.session_state.refresh_token = None
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.remember_me = False
    st.session_state.auth_restore_done = False
    st.session_state.auth_restore_attempts = 0

    st.success("已登出")
    st.rerun()


# ==================== UI 元件 ====================

def get_user_info() -> Optional[Dict[str, str]]:
    """獲取當前用戶資訊"""
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

            if st.session_state.get('remember_me'):
                st.caption("✅ 已啟用自動登入（7 天）")

        st.markdown("---")

        if st.button("登出", use_container_width=True, key="sidebar_logout"):
            logout(api_base_url)


def render_login_form(api_base_url: str) -> bool:
    """渲染登入表單"""
    st.markdown("#### 用戶登入")

    email = st.text_input("Email", key="login_email")
    password = st.text_input("密碼", type="password", key="login_password")
    remember_me = st.checkbox("記住我（7天內自動登入）", key="login_remember_me", value=True)

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


# ==================== 頁面可見性監聽（簡化版） ====================

def inject_visibility_listener():
    """
    注入頁面可見性監聽器（v3.0 簡化版）

    v3.0 改進：
    - 不再依賴 localStorage（不可靠）
    - 不再自動 reload（避免循環）
    - 只記錄日誌，讓 Streamlit 的 15 秒自動刷新處理
    """
    # 已認證時才注入，避免在登入頁增加複雜度
    if not is_authenticated():
        return

    # 只注入一次
    if st.session_state.get('visibility_listener_injected'):
        return

    # 簡化版：只記錄可見性變化，不自動 reload
    js_code = """
    <script>
    (function() {
        if (window._v7_visibility_listener) return;
        window._v7_visibility_listener = true;

        document.addEventListener('visibilitychange', function() {
            if (document.hidden) {
                console.log('[V7] 頁面隱藏');
            } else {
                console.log('[V7] 頁面可見 - Streamlit 自動刷新會處理');
            }
        });

        console.log('[V7] 可見性監聽器已安裝 (v3.0 簡化版)');
    })();
    </script>
    """

    components.html(js_code, height=0)
    st.session_state.visibility_listener_injected = True


# ==================== 載入中畫面 ====================

def render_loading_screen():
    """渲染恢復登入狀態的載入畫面"""
    attempts = st.session_state.get('auth_restore_attempts', 0)
    st.markdown(f"""
    <div style="display: flex; justify-content: center; align-items: center; height: 200px;">
        <div style="text-align: center;">
            <div class="auth-spinner"></div>
            <p style="color: #666; margin-top: 16px;">正在恢復登入狀態... ({attempts}/{MAX_RESTORE_ATTEMPTS})</p>
        </div>
    </div>
    <style>
    .auth-spinner {{
        width: 40px;
        height: 40px;
        border: 4px solid #f3f3f3;
        border-top: 4px solid #3498db;
        border-radius: 50%;
        animation: auth-spin 1s linear infinite;
        margin: 0 auto;
    }}
    @keyframes auth-spin {{
        0% {{ transform: rotate(0deg); }}
        100% {{ transform: rotate(360deg); }}
    }}
    </style>
    """, unsafe_allow_html=True)
