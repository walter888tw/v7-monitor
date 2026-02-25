# -*- coding: utf-8 -*-
"""
認證工具模組 v4.5
提供 JWT 認證相關功能 + 服務端 Session ID 管理

v4.5 修復說明（2026-02-25）：
==================================
v4.4 問題診斷：
- CookieManager 在 Streamlit Cloud iframe 中讀取不可靠
- _reset_cookie_manager() 每次 rerun 銷毀已收到資料的 CM
- 導致 F5 重整後 Cookie 永遠讀不到 → 跳回登入頁

v4.5 解決方案：
- 使用 JavaScript 直接存取 sessionStorage + localStorage + Cookie（三重存儲）
- sessionStorage: F5 重整安全（同分頁持續）
- localStorage: 跨會話持續（「記住我」功能）
- Cookie: 備援（CookieManager 仍可用時）
- 讀取使用 streamlit_js_eval 直接回傳結果給 Python
- 移除 _reset_cookie_manager()（不再需要）
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
    獲取 Cookie Manager 實例（備援用途）

    v4.5 說明：
    - CookieManager 僅作為寫入備援（save/clear 時額外調用）
    - 讀取改用 streamlit_js_eval 直接從瀏覽器取值（更可靠）
    - 使用 session_state 快取避免 DuplicateWidgetID
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


def _save_session_js(session_id: str):
    """
    使用 JavaScript 直接保存 Session ID（v4.6 修正）

    v4.6 修正：
    - components.html() 的 srcdoc iframe 有 opaque origin，
      其 sessionStorage/localStorage 對 app iframe 不可見。
    - 必須透過 window.parent / window.top 寫入 app iframe 的 storage。
    - 同時嘗試 window / window.parent / window.top，以 try-catch 容錯。
    """
    max_age = COOKIE_EXPIRY_DAYS * 86400  # 秒
    js = f"""
    <script>
    (function() {{
        var key = '{COOKIE_NAME}';
        var val = '{session_id}';
        var maxAge = {max_age};
        var targets = [window];
        try {{ if (window.parent && window.parent !== window) targets.push(window.parent); }} catch(e) {{}}
        try {{ if (window.top && window.top !== window && window.top !== window.parent) targets.push(window.top); }} catch(e) {{}}
        for (var i = 0; i < targets.length; i++) {{
            var w = targets[i];
            try {{ w.sessionStorage.setItem(key, val); }} catch(e) {{}}
            try {{ w.localStorage.setItem(key, val); }} catch(e) {{}}
            try {{ w.document.cookie = key + '=' + encodeURIComponent(val) + '; max-age=' + maxAge + '; path=/; SameSite=Lax'; }} catch(e) {{}}
        }}
    }})();
    </script>
    """
    components.html(js, height=0)


def _read_session_id_js() -> Optional[str]:
    """
    使用 JavaScript 直接從瀏覽器讀取 Session ID（v4.6 修正）

    v4.6 修正：
    - streamlit_js_eval 也在 component iframe 中執行，
      其 sessionStorage/localStorage 可能是隔離的 opaque origin。
    - 必須同時嘗試 window / window.parent / window.top 讀取。
    """
    try:
        from streamlit_js_eval import streamlit_js_eval

        js_code = f"""
        (function() {{
            var key = '{COOKIE_NAME}';
            var minLen = 20;
            var targets = [window];
            try {{ if (window.parent && window.parent !== window) targets.push(window.parent); }} catch(e) {{}}
            try {{ if (window.top && window.top !== window && window.top !== window.parent) targets.push(window.top); }} catch(e) {{}}
            for (var t = 0; t < targets.length; t++) {{
                var w = targets[t];
                try {{
                    var s = w.sessionStorage.getItem(key);
                    if (s && s.length >= minLen) return s;
                }} catch(e) {{}}
                try {{
                    var l = w.localStorage.getItem(key);
                    if (l && l.length >= minLen) return l;
                }} catch(e) {{}}
                try {{
                    var prefix = key + '=';
                    var cookies = w.document.cookie.split(';');
                    for (var i = 0; i < cookies.length; i++) {{
                        var c = cookies[i].trim();
                        if (c.indexOf(prefix) === 0) {{
                            var val = decodeURIComponent(c.substring(prefix.length));
                            if (val.length >= minLen) return val;
                        }}
                    }}
                }} catch(e) {{}}
            }}
            return '';
        }})()
        """

        result = streamlit_js_eval(js_expressions=js_code, key="_v7_sid_reader")

        if result and isinstance(result, str) and len(result) >= 20:
            logger.info("從 JS 讀取 Session ID 成功（sessionStorage/localStorage/Cookie）")
            return result

        return None
    except ImportError:
        logger.debug("streamlit_js_eval 未安裝，跳過 JS 讀取")
        return None
    except Exception as e:
        logger.debug(f"JS 讀取失敗: {e}")
        return None


def _clear_session_js():
    """
    使用 JavaScript 清除所有 Session 存儲（v4.6 修正）
    """
    js = f"""
    <script>
    (function() {{
        var key = '{COOKIE_NAME}';
        var targets = [window];
        try {{ if (window.parent && window.parent !== window) targets.push(window.parent); }} catch(e) {{}}
        try {{ if (window.top && window.top !== window && window.top !== window.parent) targets.push(window.top); }} catch(e) {{}}
        for (var i = 0; i < targets.length; i++) {{
            var w = targets[i];
            try {{ w.sessionStorage.removeItem(key); }} catch(e) {{}}
            try {{ w.localStorage.removeItem(key); }} catch(e) {{}}
            try {{ w.document.cookie = key + '=; max-age=0; path=/'; }} catch(e) {{}}
        }}
    }})();
    </script>
    """
    components.html(js, height=0)


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
    保存 Session ID（v4.7 — st.query_params 為主）

    v4.7 修正：
    - Streamlit Cloud 的 component iframe 有 sandbox 限制（opaque origin），
      無法透過 JS 寫入 app iframe 的 sessionStorage/localStorage/Cookie。
    - 改用 st.query_params 作為主要持久化機制（Streamlit 原生，F5 安全）。
    - JS 和 CookieManager 保留作為輔助（某些環境仍有效）。
    """
    # 1. st.query_params — 最可靠（Streamlit 原生，不受 iframe sandbox 限制）
    try:
        st.query_params[QUERY_PARAM_KEY] = session_id
        logger.info("Session ID 已存入 st.query_params")
    except Exception as e:
        logger.warning(f"st.query_params 存儲失敗: {e}")

    # 2. JavaScript 輔助存儲（本地環境有效）
    _save_session_js(session_id)

    # 3. CookieManager 備援
    try:
        cookie_manager = _get_cookie_manager()
        if cookie_manager:
            expires_at = datetime.now() + timedelta(days=COOKIE_EXPIRY_DAYS)
            cookie_manager.set(COOKIE_NAME, session_id, expires_at=expires_at)
    except Exception as e:
        logger.debug(f"CookieManager 存儲失敗: {e}")


def load_session_id() -> Optional[str]:
    """
    讀取 Session ID（v4.7 — st.query_params 優先）

    v4.7 讀取優先順序：
    1. st.query_params（Streamlit 原生，F5 安全，Streamlit Cloud 最可靠）
    2. JavaScript（sessionStorage/localStorage/Cookie，本地環境有效）
    3. CookieManager（備援）

    Returns:
        Session ID 或 None
    """
    # 1. st.query_params — 最可靠
    try:
        sid = st.query_params.get(QUERY_PARAM_KEY)
        if sid and len(sid) >= 20:
            logger.info("從 st.query_params 讀取 Session ID 成功")
            return sid
    except Exception as e:
        logger.debug(f"st.query_params 讀取失敗: {e}")

    # 2. JavaScript 輔助讀取
    sid = _read_session_id_js()
    if sid:
        return sid

    # 3. CookieManager 備援
    try:
        cookie_manager = _get_cookie_manager()
        if cookie_manager:
            sid = cookie_manager.get(COOKIE_NAME)
            if sid and len(sid) >= 20:
                logger.info("從 CookieManager 讀取 Session ID 成功（備援）")
                return sid
    except Exception as e:
        logger.debug(f"CookieManager 讀取失敗: {e}")

    return None


def clear_session_id():
    """清除所有 Session ID 存儲（v4.5 多重清除）"""
    # 1. JavaScript 清除所有存儲
    _clear_session_js()

    # 2. URL 參數清除
    try:
        if QUERY_PARAM_KEY in st.query_params:
            del st.query_params[QUERY_PARAM_KEY]
    except Exception as e:
        logger.debug(f"URL 參數清除失敗: {e}")

    # 3. CookieManager 備援清除
    try:
        cookie_manager = _get_cookie_manager()
        if cookie_manager:
            cookie_manager.delete(COOKIE_NAME)
    except Exception as e:
        logger.debug(f"CookieManager 清除失敗: {e}")


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
    嘗試恢復登入狀態（v4.5 JavaScript 直接讀取）

    v4.5 修正：
    - 使用 streamlit_js_eval 直接從瀏覽器讀取 sessionStorage/localStorage/Cookie
    - 首次 render 時 JS 尚未執行（返回 0），不標記完成，等 rerun 後再試
    - 移除 _reset_cookie_manager()（不再需要，JS 讀取不依賴 CookieManager）

    流程（三層驗證）：
    1. 檢查 st.session_state 中是否有 user_token
    2. 如果有，比對 session_state 中的 session_id
    3. 如果沒有 user_token，透過 JS 讀取 session_id 並調用 API 驗證

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
            logger.info(f"身份驗證通過（快速路徑）: {st.session_state.get('user_email', 'N/A')}")
            st.session_state.auth_restore_done = True
            return True
        else:
            logger.warning(f"Session ID 不一致！stored={stored_sid[:8] if stored_sid else 'None'}..., current={current_sid[:8] if current_sid else 'None'}...")
            logger.warning("清空 session_state 並重新驗證")
            for key in ['user_token', 'session_id', 'user_email', 'username', 'subscription_tier', 'refresh_token']:
                if key in st.session_state:
                    del st.session_state[key]

    # 第三層：讀取 Session ID 並調用 API 驗證
    session_id = load_session_id()

    if not session_id:
        # v4.5: streamlit_js_eval 首次 render 返回 0（JS 尚未執行）
        # 真正的值要等瀏覽器執行 JS 後觸發 rerun 才能拿到
        # 第一次嘗試：不標記 auth_restore_done，讓 JS 組件 rerun 後再試
        attempts = st.session_state.get('_cookie_load_attempts', 0)
        st.session_state['_cookie_load_attempts'] = attempts + 1

        if attempts < 1:
            logger.info("JS 組件首次載入，等待瀏覽器 rerun...")
            return False

        # 多次嘗試仍無 Session ID → 確實未登入
        logger.info("無 Session ID，進入登入頁")
        st.session_state.auth_restore_done = True
        return False

    # 找到 session_id，清除嘗試計數
    st.session_state.pop('_cookie_load_attempts', None)

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
        logger.warning("Session 驗證失敗，清除存儲")
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
