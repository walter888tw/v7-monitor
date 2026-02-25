# -*- coding: utf-8 -*-
"""
認證工具模組 v4.0
提供 JWT 認證相關功能 + 服務端 Session ID 管理

v4.0 重構說明（2026-02-05）：
==================================
v3.0 問題診斷：
- Streamlit Cloud WebSocket 斷開會清空 session_state
- GitHub Issue #8901（P3，至今未解決）
- localStorage/Cookie 在 Streamlit Cloud iframe 沙箱中不可靠

v4.0 解決方案：
- 引入 session_id（32字元）作為前後端橋樑
- 前端僅存儲短 session_id，不存儲完整 token
- 新增 /verify-session API，單次調用恢復登入狀態
- 移除複雜的編碼/解碼邏輯和多次重試機制

流程對比：
v3.0: 存儲 base64(email+refresh_token ~200字元) → /auth/refresh → 解析
v4.0: 存儲 session_id (32字元) → /auth/verify-session → 直接返回
"""
import streamlit as st
import streamlit.components.v1 as components
import requests
from typing import Optional, Dict
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# === 常量配置 ===
QUERY_PARAM_KEY = "sid"  # URL 參數鍵名（v4.0 改為 sid）
COOKIE_NAME = "v7_sid"   # Cookie 名稱（v4.0 改為 v7_sid）
COOKIE_EXPIRY_DAYS = 7   # Cookie 過期天數

def _get_cookie_manager():
    """
    獲取 Cookie Manager 實例（v4.3 per-tab 隔離版）

    修復 P0-5：不再使用 module-level 全域變數。
    改為 st.session_state 存放，確保每個 tab/connection 獨立。
    Streamlit Cloud 是 single-process multi-connection，
    module-level 變數會被所有用戶共享，導致帳號混用。
    """
    state_key = "_v7_cookie_manager"

    if state_key in st.session_state and st.session_state[state_key] is not None:
        return st.session_state[state_key]

    try:
        from extra_streamlit_components import CookieManager
        cm = CookieManager(key="v7_cookie_manager_v4")
        st.session_state[state_key] = cm
        return cm
    except ImportError:
        logger.warning("extra-streamlit-components 未安裝，Cookie 持久化功能將不可用")
        st.session_state[state_key] = None
        return None
    except Exception as e:
        logger.warning(f"CookieManager 初始化失敗: {e}")
        st.session_state[state_key] = None
        return None


# ==================== Session 初始化 ====================

def init_session():
    """初始化 session state"""
    defaults = {
        'user_token': None,
        'user_email': None,
        'refresh_token': None,
        'session_id': None,  # v4.0 新增
        'user_id': None,
        'username': None,
        'subscription_tier': None,  # v4.0 新增
        'remember_me': False,
        # 恢復相關狀態
        'auth_restore_done': False,
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


# ==================== Session ID 存儲層（v4.0 簡化版） ====================

def save_session_id(session_id: str):
    """
    保存 Session ID（v4.2 安全修復版）

    存儲位置：Cookie 唯一持久化存儲
    ⚠️ 不再寫入 URL 參數 —— URL 中的 sid 相當於 Bearer Token，
       任何人複製 URL 即可冒充該用戶，是嚴重安全漏洞。

    修復說明（2026-02-23）：
    - 移除 st.query_params 寫入（v4.0 設計缺陷）
    - 改為 Cookie 唯一持久化（僅當前瀏覽器可讀）
    - 如果 URL 中殘留舊版 sid，同時清除它
    """
    # 清除 URL 中殘留的 sid（防止舊版本留下的安全漏洞）
    try:
        if QUERY_PARAM_KEY in st.query_params:
            del st.query_params[QUERY_PARAM_KEY]
    except Exception:
        pass

    # 唯一存儲：Cookie（7 天，瀏覽器本地，不可被 URL 分享）
    try:
        cookie_manager = _get_cookie_manager()
        if cookie_manager:
            expires_at = datetime.now() + timedelta(days=COOKIE_EXPIRY_DAYS)
            cookie_manager.set(COOKIE_NAME, session_id, expires_at=expires_at)
            logger.info("Session ID 已存入 Cookie（URL 已清除）")
    except Exception as e:
        logger.warning(f"Cookie 存儲失敗: {e}")


def load_session_id() -> Optional[str]:
    """
    讀取 Session ID（v4.2 安全修復版）

    讀取位置（按優先順序）：
    1. Cookie（主要）
    2. URL 參數（向後兼容舊版本，讀完立即刪除）

    安全設計（2026-02-23 修復）：
    - Cookie 為唯一持久化存儲，不回寫 URL
    - URL 中如有 sid（舊版殘留或人工植入），讀後立即刪除
    - 防止攻擊者複製 URL 冒充他人身份

    Returns:
        Session ID 或 None
    """
    # 1. 從 Cookie 讀取（主要，安全的）
    try:
        cookie_manager = _get_cookie_manager()
        if cookie_manager:
            sid = cookie_manager.get(COOKIE_NAME)
            if sid and len(sid) >= 20:
                logger.info("從 Cookie 讀取 Session ID 成功")
                return sid
    except Exception as e:
        logger.debug(f"Cookie 讀取失敗: {e}")

    # 2. 從 URL 參數讀取（向後兼容，讀完立即銷毀）
    # ⚠️ 這裡處理舊版本遺留的 ?sid=xxx —— 讀取後立即從 URL 移除，
    #    然後存入 Cookie，確保下次走 Cookie 路徑（不再暴露於 URL）
    try:
        sid = st.query_params.get(QUERY_PARAM_KEY)
        if sid and len(sid) >= 20:
            logger.info("從 URL 參數讀取 Session ID（將立即清除 URL）")

            # 立即從 URL 移除（防止 URL 被分享/截圖洩漏）
            try:
                del st.query_params[QUERY_PARAM_KEY]
            except Exception:
                pass

            # 移入 Cookie 持久化（下次直接走 Cookie 路徑）
            try:
                cookie_manager = _get_cookie_manager()
                if cookie_manager:
                    expires_at = datetime.now() + timedelta(days=COOKIE_EXPIRY_DAYS)
                    cookie_manager.set(COOKIE_NAME, sid, expires_at=expires_at)
            except Exception:
                pass

            return sid
    except Exception as e:
        logger.debug(f"URL 參數讀取失敗: {e}")

    return None


def clear_session_id():
    """清除所有 Session ID 存儲"""
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


# ==================== v4.0 核心：Session 驗證 ====================

def verify_session(api_base_url: str, session_id: str, refresh_token: Optional[str] = None) -> Optional[Dict]:
    """
    向後端驗證 Session ID（v4.3 POST + 二次驗證）

    v4.3 改進：
    - 改為 POST 方法（敏感資訊不在 URL/日誌中）
    - 支援 refresh_token 二次驗證（可選）

    Args:
        api_base_url: API 基礎 URL
        session_id: 要驗證的 Session ID
        refresh_token: 可選的 Refresh Token（提供時做二次驗證）

    Returns:
        成功時返回 {"success": True, "access_token": ..., "refresh_token": ..., "user": {...}, ...}
        失敗時返回 None
    """
    try:
        body = {"session_id": session_id}
        if refresh_token:
            body["refresh_token"] = refresh_token

        response = requests.post(
            f"{api_base_url}/auth/verify-session",
            json=body,
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            if data.get("success"):
                logger.info("Session 驗證成功")
                return data
            else:
                logger.warning(f"Session 驗證失敗: {data.get('error')}")
                return None
        else:
            logger.warning(f"Session 驗證失敗: HTTP {response.status_code}")
            return None

    except requests.exceptions.Timeout:
        logger.warning("Session 驗證超時")
        return None
    except requests.exceptions.ConnectionError:
        logger.warning("無法連接伺服器")
        return None
    except Exception as e:
        logger.warning(f"Session 驗證失敗: {e}")
        return None


# ==================== 恢復機制（v4.0 簡化版） ====================

def try_restore_session(api_base_url: str) -> bool:
    """
    嘗試恢復登入狀態（v4.1 安全增強版）

    流程（三層驗證）：
    1. 檢查 st.session_state 中是否有 user_token
    2. 如果有，比對 session_state 中的 session_id 和 cookie 中的 session_id
       - 一致 → 快速返回（不調用 API，避免頻繁登出）
       - 不一致 → 可能被污染，清空後重新驗證
    3. 如果沒有 user_token，讀取 cookie/URL 中的 session_id 並調用 API 驗證

    安全保證：
    - 防止 session_state 被污染導致身份混淆
    - 避免頻繁 API 調用影響用戶體驗
    - 只有身份不一致時才強制重新驗證

    Args:
        api_base_url: API 基礎 URL

    Returns:
        是否成功恢復
    """
    # 如果已完成恢復流程（避免重複執行）
    if st.session_state.get('auth_restore_done'):
        return st.session_state.get('user_token') is not None

    # 第一層：檢查是否已有 token
    if is_authenticated():
        # 第二層：驗證 session_id 一致性（防止污染）
        stored_sid = st.session_state.get('session_id')
        current_sid = load_session_id()

        if stored_sid and current_sid and stored_sid == current_sid:
            # ✅ 身份一致，快速返回（不調用 API）
            logger.info(f"身份驗證通過（快速路徑）: {st.session_state.get('user_email', 'N/A')}")
            st.session_state.auth_restore_done = True
            return True
        else:
            # ⚠️ 身份不一致，可能被污染
            logger.warning(f"Session ID 不一致！stored={stored_sid[:8] if stored_sid else 'None'}..., current={current_sid[:8] if current_sid else 'None'}...")
            logger.warning("清空 session_state 並重新驗證")
            # 清空可能被污染的狀態
            for key in ['user_token', 'session_id', 'user_email', 'username', 'subscription_tier', 'refresh_token']:
                if key in st.session_state:
                    del st.session_state[key]
            # 繼續執行下方的重新驗證流程

    # 第三層：讀取 Session ID 並調用 API 驗證
    session_id = load_session_id()

    if not session_id:
        logger.info("無 Session ID，進入登入頁")
        st.session_state.auth_restore_done = True
        return False

    # 調用後端驗證（v4.3: POST + 可選二次驗證）
    logger.info(f"調用 /verify-session API (sid={session_id[:8]}...)")
    refresh_token = st.session_state.get('refresh_token')
    result = verify_session(api_base_url, session_id, refresh_token=refresh_token)

    if result:
        # 恢復成功
        st.session_state.user_token = result["access_token"]
        st.session_state.refresh_token = result.get("refresh_token")
        st.session_state.session_id = result.get("session_id", session_id)
        st.session_state.user_email = result["user"]["email"]
        st.session_state.username = result["user"].get("username")
        st.session_state.subscription_tier = result["user"].get("subscription_tier")
        st.session_state.remember_me = True
        st.session_state.auth_restore_done = True
        logger.info(f"登入狀態已恢復: {result['user']['email']}")
        return True
    else:
        # 驗證失敗，清除存儲
        logger.warning("❌ Session 驗證失敗，清除存儲")
        clear_session_id()
        st.session_state.auth_restore_done = True
        return False


# ==================== 登入/登出 ====================

def login(api_base_url: str, email: str, password: str, remember_me: bool = False) -> Dict:
    """
    執行登入（v4.0）

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
            timeout=30  # 增加到 30 秒：後端 DB pool 壓力大時 15 秒可能不夠
        )

        if response.status_code == 200:
            data = response.json()

            # 儲存到 session state
            st.session_state.user_token = data["access_token"]
            st.session_state.refresh_token = data["refresh_token"]
            st.session_state.session_id = data["session_id"]  # v4.0 新增
            st.session_state.user_email = email
            st.session_state.remember_me = remember_me
            st.session_state.auth_restore_done = True

            # 如果勾選「記住我」，保存 session_id 到持久化存儲
            if remember_me:
                save_session_id(data["session_id"])

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
    登出（v4.0）

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
    clear_session_id()

    # 清除 session state
    st.session_state.user_token = None
    st.session_state.user_email = None
    st.session_state.refresh_token = None
    st.session_state.session_id = None
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.subscription_tier = None
    st.session_state.remember_me = False
    st.session_state.auth_restore_done = False

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
        'user_id': st.session_state.user_id,
        'subscription_tier': st.session_state.subscription_tier
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


# ==================== 頁面可見性監聽（v4.0 簡化版） ====================

def inject_visibility_listener():
    """
    注入頁面可見性監聯器（v4.0 極簡版）

    v4.0 改進：
    - 不再依賴 localStorage
    - 不自動 reload
    - 只記錄日誌，讓 Streamlit 的 15 秒自動刷新處理
    """
    # 已認證時才注入
    if not is_authenticated():
        return

    # 只注入一次
    if st.session_state.get('visibility_listener_injected'):
        return

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

        console.log('[V7] 可見性監聽器已安裝 (v4.0)');
    })();
    </script>
    """

    components.html(js_code, height=0)
    st.session_state.visibility_listener_injected = True


# ==================== 載入中畫面 ====================

def render_loading_screen():
    """渲染恢復登入狀態的載入畫面"""
    st.markdown("""
    <div style="display: flex; justify-content: center; align-items: center; height: 200px;">
        <div style="text-align: center;">
            <div class="auth-spinner"></div>
            <p style="color: #666; margin-top: 16px;">正在恢復登入狀態...</p>
        </div>
    </div>
    <style>
    .auth-spinner {
        width: 40px;
        height: 40px;
        border: 4px solid #f3f3f3;
        border-top: 4px solid #3498db;
        border-radius: 50%;
        animation: auth-spin 1s linear infinite;
        margin: 0 auto;
    }
    @keyframes auth-spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    </style>
    """, unsafe_allow_html=True)


# ==================== 向後兼容（v3.0 遷移） ====================

# 保留舊函式名稱，避免 app.py 報錯
def save_auth_data(email: str, refresh_token: str):
    """v3.0 向後兼容：改用 save_session_id"""
    logger.warning("save_auth_data() 已棄用，請使用 save_session_id()")
    # 在 v4.0 中，這個函式不再有意義，因為我們不存儲 refresh_token
    pass


def load_auth_data() -> Optional[Dict]:
    """v3.0 向後兼容：改用 load_session_id"""
    logger.warning("load_auth_data() 已棄用，請使用 load_session_id()")
    return None


def clear_auth_data():
    """v3.0 向後兼容：改用 clear_session_id"""
    clear_session_id()


def refresh_access_token(api_base_url: str, refresh_token: str) -> Optional[str]:
    """
    刷新 Access Token（v3.0 向後兼容）

    v4.0 說明：此函式保留用於向後兼容，新代碼應使用 verify_session()
    """
    try:
        response = requests.post(
            f"{api_base_url}/auth/refresh",
            json={"refresh_token": refresh_token},
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()
            # v4.0: 同時更新 session_id
            if data.get("session_id"):
                st.session_state.session_id = data["session_id"]
            return data.get("access_token")
        else:
            logger.warning(f"Token 刷新失敗: HTTP {response.status_code}")
            return None
    except Exception as e:
        logger.warning(f"Token 刷新失敗: {e}")
        return None
