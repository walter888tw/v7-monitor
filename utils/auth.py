# -*- coding: utf-8 -*-
"""
認證工具模組 v5.0
提供 JWT 認證相關功能 + 服務端 Session ID 管理

v5.0 修復說明（2026-02-25）：
==================================
根因分析（Playwright 雲端驗證）：
- components.html() 的 srcdoc iframe 存儲與 app iframe 隔離
  （即使有 allow-same-origin，srcdoc 寫入的 sessionStorage/localStorage/cookie
   對 app iframe 不可見，已在 Streamlit Cloud 上實驗確認）
- streamlit_js_eval 的 component iframe 與 app iframe 同源
  （已驗證可互相讀寫 sessionStorage/localStorage/cookie）
- st.query_params 會暴露 sid 在 URL（造成 session 混用風險）

v5.0 解決方案：
- 統一使用 streamlit_js_eval 進行瀏覽器存儲同步（read/write/clear）
- 完全移除 st.query_params（sid 不再出現在 URL）
- 完全移除 components.html() 存儲操作
- sessionStorage（F5 安全）+ localStorage（記住我）+ Cookie（備援）
"""
import streamlit as st
import streamlit.components.v1 as components
import requests
from typing import Optional, Dict
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# === 常量配置 ===
COOKIE_NAME = "v7_sid"   # Cookie/Storage 鍵名
COOKIE_EXPIRY_DAYS = 7   # 過期天數


# ==================== 瀏覽器存儲同步（v5.0 核心）====================

def _browser_storage_sync() -> Optional[str]:
    """
    v5.0 核心：透過 streamlit_js_eval 同步瀏覽器存儲

    技術背景（Playwright 實驗驗證）：
    - streamlit_js_eval 的 component iframe 與 app iframe 共享同一 origin
      → 可以讀寫 app iframe 的 sessionStorage/localStorage/cookie
    - components.html() 的 srcdoc iframe 存儲隔離
      → 寫入的資料對 app iframe 不可見（已確認不可用）

    三種模式（依 session_state 自動判斷）：
    1. CLEAR: _sid_clear_pending=True → 清除所有存儲
    2. WRITE: 已認證 + remember_me → 同步 session_id 到瀏覽器
    3. READ: 未認證 → 從瀏覽器讀取 session_id

    Returns:
        Session ID 或 None（首次渲染返回 None，等 rerun 後回傳實際值）
    """
    try:
        from streamlit_js_eval import streamlit_js_eval
    except ImportError:
        logger.warning("streamlit_js_eval 未安裝，瀏覽器存儲同步不可用")
        return None

    clear_flag = st.session_state.get('_sid_clear_pending', False)
    current_sid = st.session_state.get('session_id') or ''
    remember = st.session_state.get('remember_me', False)

    if clear_flag:
        # === CLEAR 模式 ===
        js = f"""
        (function() {{
            var key = '{COOKIE_NAME}';
            try {{ sessionStorage.removeItem(key); }} catch(e) {{}}
            try {{ localStorage.removeItem(key); }} catch(e) {{}}
            try {{ document.cookie = key + '=; max-age=0; path=/'; }} catch(e) {{}}
            return '';
        }})()
        """
        st.session_state.pop('_sid_clear_pending', None)

    elif current_sid and len(current_sid) >= 20:
        # === WRITE 模式 ===
        # 一律寫入 sessionStorage（F5/Ctrl+R 保護）
        # 勾選「記住我」時額外寫入 localStorage + Cookie（關閉瀏覽器後仍保留）
        max_age = COOKIE_EXPIRY_DAYS * 86400
        if remember:
            js = f"""
            (function() {{
                var key = '{COOKIE_NAME}';
                var val = '{current_sid}';
                var maxAge = {max_age};
                try {{ sessionStorage.setItem(key, val); }} catch(e) {{}}
                try {{ localStorage.setItem(key, val); }} catch(e) {{}}
                try {{ document.cookie = key + '=' + encodeURIComponent(val) + '; max-age=' + maxAge + '; path=/; SameSite=Lax'; }} catch(e) {{}}
                return val;
            }})()
            """
        else:
            js = f"""
            (function() {{
                var key = '{COOKIE_NAME}';
                var val = '{current_sid}';
                try {{ sessionStorage.setItem(key, val); }} catch(e) {{}}
                return val;
            }})()
            """

    else:
        # === READ 模式 ===
        js = f"""
        (function() {{
            var key = '{COOKIE_NAME}';
            var minLen = 20;
            try {{
                var s = sessionStorage.getItem(key);
                if (s && s.length >= minLen) return s;
            }} catch(e) {{}}
            try {{
                var l = localStorage.getItem(key);
                if (l && l.length >= minLen) return l;
            }} catch(e) {{}}
            try {{
                var prefix = key + '=';
                var cookies = document.cookie.split(';');
                for (var i = 0; i < cookies.length; i++) {{
                    var c = cookies[i].trim();
                    if (c.indexOf(prefix) === 0) {{
                        var val = decodeURIComponent(c.substring(prefix.length));
                        if (val.length >= minLen) return val;
                    }}
                }}
            }} catch(e) {{}}
            return '';
        }})()
        """

    try:
        result = streamlit_js_eval(js_expressions=js, key="_sid_sync")
        if result and isinstance(result, str) and len(result) >= 20:
            return result
    except Exception as e:
        logger.debug(f"瀏覽器存儲同步失敗: {e}")

    return None


# ==================== Session ID 存儲介面 ====================

def save_session_id(session_id: str):
    """
    保存 Session ID（v5.0）

    v5.0: 實際寫入由 _browser_storage_sync() 自動處理。
    login() 已將 session_id 和 remember_me 設入 session_state，
    下次 rerun 時 _browser_storage_sync() 會在 WRITE 模式下同步到瀏覽器。
    """
    logger.info(f"Session ID 已標記為需持久化 (sid={session_id[:8]}...)")


def load_session_id() -> Optional[str]:
    """
    從瀏覽器存儲讀取 Session ID（v5.0）

    v5.0: 透過 _browser_storage_sync() 讀取。
    首次渲染返回 None（streamlit_js_eval 尚未回傳），等 rerun 後回傳實際值。
    """
    return _browser_storage_sync()


def clear_session_id():
    """
    清除瀏覽器存儲中的 Session ID（v5.0）

    v5.0: 設定清除標記，下次 _browser_storage_sync() 呼叫時執行清除。
    """
    st.session_state['_sid_clear_pending'] = True
    logger.info("Session ID 清除已排程")


# ==================== Session 初始化 ====================

def init_session():
    """初始化 session state"""
    defaults = {
        'user_token': None,
        'user_email': None,
        'refresh_token': None,
        'session_id': None,
        'user_id': None,
        'username': None,
        'subscription_tier': None,
        'remember_me': False,
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


# ==================== Session 驗證 ====================

def verify_session(api_base_url: str, session_id: str, refresh_token: Optional[str] = None) -> Optional[Dict]:
    """
    向後端驗證 Session ID（POST + 可選二次驗證）

    Args:
        api_base_url: API 基礎 URL
        session_id: 要驗證的 Session ID
        refresh_token: 可選的 Refresh Token

    Returns:
        成功時返回 {"success": True, "access_token": ..., "user": {...}, ...}
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


# ==================== 恢復機制（v5.0）====================

def try_restore_session(api_base_url: str) -> bool:
    """
    嘗試恢復登入狀態（v5.0 — streamlit_js_eval 瀏覽器同步）

    v5.0 核心改動：
    - 每次 rerun 都呼叫 _browser_storage_sync()（確保 read/write/clear 都正確執行）
    - 移除 st.query_params（sid 不再暴露在 URL）
    - 移除 components.html() 存儲（srcdoc iframe 隔離問題）

    流程：
    1. 同步瀏覽器存儲（_browser_storage_sync）
    2. 已完成恢復 → 直接返回
    3. 已認證（session_state 有 token）→ 快速路徑
    4. 有 browser_sid → API 驗證 → 恢復
    5. 無 session_id → 登入頁
    """
    # v5.0: 每次 rerun 都同步瀏覽器存儲
    # 這確保：登入後寫入、F5 後讀取、登出後清除
    browser_sid = _browser_storage_sync()

    # 已完成恢復流程（避免重複執行）
    if st.session_state.get('auth_restore_done'):
        return is_authenticated()

    # 第一層：已有 token（例如剛登入後的 rerun）
    if is_authenticated():
        st.session_state.auth_restore_done = True
        return True

    # 第二層：從瀏覽器讀取 session_id
    if not browser_sid:
        # streamlit_js_eval 首次渲染返回 0/None，等 rerun 後再試
        attempts = st.session_state.get('_cookie_load_attempts', 0)
        st.session_state['_cookie_load_attempts'] = attempts + 1

        if attempts < 1:
            logger.info("等待瀏覽器存儲回傳...")
            return False

        # 多次嘗試仍無 → 確實未登入
        logger.info("無 Session ID，進入登入頁")
        st.session_state.auth_restore_done = True
        return False

    # 找到 browser_sid，清除嘗試計數
    st.session_state.pop('_cookie_load_attempts', None)

    # 第三層：API 驗證
    logger.info(f"驗證 Session ID (sid={browser_sid[:8]}...)")
    refresh_token = st.session_state.get('refresh_token')
    result = verify_session(api_base_url, browser_sid, refresh_token=refresh_token)

    if result:
        st.session_state.user_token = result["access_token"]
        st.session_state.refresh_token = result.get("refresh_token")
        st.session_state.session_id = result.get("session_id", browser_sid)
        st.session_state.user_email = result["user"]["email"]
        st.session_state.username = result["user"].get("username")
        st.session_state.subscription_tier = result["user"].get("subscription_tier")
        st.session_state.remember_me = True
        st.session_state.auth_restore_done = True
        logger.info(f"登入狀態已恢復: {result['user']['email']}")
        return True
    else:
        logger.warning("Session 驗證失敗，清除存儲")
        clear_session_id()
        st.session_state.auth_restore_done = True
        return False


# ==================== 登入/登出 ====================

def login(api_base_url: str, email: str, password: str, remember_me: bool = False) -> Dict:
    """
    執行登入（v5.0）

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
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()

            # 儲存到 session state
            st.session_state.user_token = data["access_token"]
            st.session_state.refresh_token = data["refresh_token"]
            st.session_state.session_id = data["session_id"]
            st.session_state.user_email = email
            st.session_state.remember_me = remember_me
            st.session_state.auth_restore_done = True

            # v5.0: save_session_id 是 no-op
            # 實際寫入由 _browser_storage_sync() 在下次 rerun 時自動處理
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
    """登出（v5.0）"""
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

    # 清除瀏覽器存儲（排程到下次 rerun）
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


def _render_forgot_password_form(api_base_url: str):
    """渲染忘記密碼表單"""
    st.markdown("#### 忘記密碼")
    st.markdown("請輸入您的 Email，我們將發送密碼重置連結到您的信箱。")

    reset_email = st.text_input("Email", key="forgot_email")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("發送重置連結", use_container_width=True, key="forgot_submit"):
            if not reset_email:
                st.error("請輸入 Email")
                return
            try:
                import requests as req_lib
                resp = req_lib.post(
                    f"{api_base_url}/auth/forgot-password",
                    json={"email": reset_email},
                    timeout=10
                )
                if resp.status_code == 200:
                    st.success("如果該帳號存在，重置連結已發送至您的信箱。請檢查收件匣（及垃圾郵件資料夾）。")
                else:
                    st.error("發送失敗，請稍後再試")
            except Exception:
                st.error("無法連接伺服器，請稍後再試")
    with col2:
        if st.button("返回登入", use_container_width=True, key="forgot_back"):
            st.session_state.show_forgot_password = False
            st.rerun()


def render_login_form(api_base_url: str) -> bool:
    """渲染登入表單"""
    # 忘記密碼模式
    if st.session_state.get("show_forgot_password"):
        _render_forgot_password_form(api_base_url)
        return False

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

    # 忘記密碼連結
    st.markdown(
        '<div style="text-align:center;margin-top:8px;">'
        '<a href="?forgot=1" target="_self" style="color:#888;font-size:14px;">忘記密碼？</a>'
        '</div>',
        unsafe_allow_html=True
    )
    if st.query_params.get("forgot") == "1":
        st.session_state.show_forgot_password = True
        st.query_params.clear()
        st.rerun()

    return False


# ==================== 頁面可見性監聽（v4.0 簡化版） ====================

def inject_visibility_listener():
    """
    注入頁面可見性監聽器（v4.0 極簡版）
    僅用於日誌記錄，不涉及存儲操作。
    """
    if not is_authenticated():
        return

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

        console.log('[V7] 可見性監聽器已安裝 (v5.0)');
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

def save_auth_data(email: str, refresh_token: str):
    """v3.0 向後兼容：已棄用"""
    pass


def load_auth_data() -> Optional[Dict]:
    """v3.0 向後兼容：已棄用"""
    return None


def clear_auth_data():
    """v3.0 向後兼容：改用 clear_session_id"""
    clear_session_id()


def refresh_access_token(api_base_url: str, refresh_token: str) -> Optional[str]:
    """刷新 Access Token（v3.0 向後兼容）"""
    try:
        response = requests.post(
            f"{api_base_url}/auth/refresh",
            json={"refresh_token": refresh_token},
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()
            if data.get("session_id"):
                st.session_state.session_id = data["session_id"]
            return data.get("access_token")
        else:
            logger.warning(f"Token 刷新失敗: HTTP {response.status_code}")
            return None
    except Exception as e:
        logger.warning(f"Token 刷新失敗: {e}")
        return None
