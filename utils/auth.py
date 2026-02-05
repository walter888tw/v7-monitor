# -*- coding: utf-8 -*-
"""
認證工具模組 v2.0
提供 JWT 認證相關功能 + 雙重存儲持久化登入

重構說明（2026-02-05 v2.0）：
==================================
問題：手機切換 app 後被登出，即使勾選「7天自動登入」

根本原因分析（第一性原則）：
1. Streamlit session_state 存在於服務器端 Python 進程
2. 手機切換 app → 瀏覽器休眠/釋放頁面 → WebSocket 斷開
3. 回來時可能是新 session → session_state 被清空
4. 但瀏覽器的 Cookie/localStorage 是持久化的
5. 所以需要從瀏覽器端持久化存儲恢復登入狀態

解決方案：
1. 雙重存儲：localStorage（主要）+ Cookie（備援）
2. 智能恢復：指數退避重試 + 多源讀取
3. 頁面可見性監聽：visibilitychange 事件觸發恢復
4. Token 自動刷新：Access Token 過期前主動刷新

技術棧：
- streamlit-js-eval: 直接執行 JavaScript，讀寫 localStorage
- extra-streamlit-components: CookieManager 作為備援
- PyJWT: 解析 Token 過期時間
"""
import streamlit as st
import streamlit.components.v1 as components
import requests
from typing import Optional, Dict
from datetime import datetime, timedelta
import json
import logging
import hashlib

logger = logging.getLogger(__name__)

# === 常量配置 ===
COOKIE_NAME = "v7_auth"  # Cookie 名稱（與 V5 區分）
LOCALSTORAGE_KEY = "v7_auth_data"  # localStorage 鍵名
COOKIE_EXPIRY_DAYS = 7  # Cookie 過期天數（與 Refresh Token 同步）
MAX_RESTORE_ATTEMPTS = 5  # 最大恢復嘗試次數
BACKOFF_TIMES = [0, 0.2, 0.5, 1.0, 2.0]  # 指數退避時間（秒）
VISIBILITY_HIDDEN_THRESHOLD = 30000  # 頁面隱藏超過此毫秒數觸發重載

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
        # Cookie 恢復相關狀態
        'cookie_restore_attempts': 0,
        'cookie_restore_done': False,
        # 可見性監聽器狀態
        'visibility_listener_injected': False,
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
        st.info("請返回首頁進行登入")
        st.stop()


def get_headers() -> Dict[str, str]:
    """獲取 API 請求 headers"""
    if st.session_state.user_token:
        return {"Authorization": f"Bearer {st.session_state.user_token}"}
    return {}


# ==================== 雙重存儲層 ====================

def _compute_checksum(email: str, refresh_token: str) -> str:
    """計算校驗碼（防篡改）"""
    return hashlib.sha256(f"{email}:{refresh_token}".encode()).hexdigest()[:16]


def save_auth_dual(email: str, refresh_token: str):
    """
    雙重存儲：localStorage（優先）+ Cookie（備援）

    為什麼要雙重存儲：
    1. localStorage 更可靠，但某些瀏覽器隱私模式可能禁用
    2. Cookie 有 4KB 限制，但相容性更好
    3. 雙重存儲確保至少一個可用

    Args:
        email: 用戶 email
        refresh_token: Refresh Token（用於恢復登入）
    """
    expires_at = datetime.now() + timedelta(days=COOKIE_EXPIRY_DAYS)

    # 構建認證資料（含校驗碼）
    auth_data = {
        "email": email,
        "refresh_token": refresh_token,
        "saved_at": datetime.now().isoformat(),
        "expires_at": expires_at.isoformat(),
        "checksum": _compute_checksum(email, refresh_token)
    }
    auth_json = json.dumps(auth_data)

    # 1. 存入 localStorage（使用 streamlit-js-eval）
    try:
        from streamlit_js_eval import streamlit_js_eval
        # 使用唯一 key 避免衝突
        key = f"save_ls_{datetime.now().timestamp()}"
        # 需要轉義 JSON 字串中的特殊字符
        escaped_json = auth_json.replace("'", "\\'")
        js_code = f"localStorage.setItem('{LOCALSTORAGE_KEY}', '{escaped_json}')"
        streamlit_js_eval(js_expressions=js_code, key=key)
        logger.info(f"認證資料已存入 localStorage: {email}")
    except ImportError:
        logger.warning("streamlit-js-eval 未安裝，localStorage 存儲不可用")
    except Exception as e:
        logger.warning(f"localStorage 存儲失敗: {e}")

    # 2. 存入 Cookie（使用 CookieManager，作為備援）
    try:
        cookie_manager = _get_cookie_manager()
        if cookie_manager:
            cookie_manager.set(
                COOKIE_NAME,
                auth_json,
                expires_at=expires_at
            )
            logger.info(f"認證資料已存入 Cookie: {email}")
    except Exception as e:
        logger.warning(f"Cookie 存儲失敗: {e}")


def load_auth_from_localstorage() -> Optional[Dict]:
    """
    從 localStorage 讀取認證資料（使用 streamlit-js-eval）

    優點：
    1. 直接執行 JavaScript，不需要等待組件渲染
    2. 同步返回結果（比 CookieManager 更可靠）

    Returns:
        認證資訊字典 {"email": str, "refresh_token": str}
        如果沒有有效資料則返回 None
    """
    try:
        from streamlit_js_eval import streamlit_js_eval

        # 使用動態 key 避免快取問題
        attempts = st.session_state.get('cookie_restore_attempts', 0)
        key = f"load_ls_{attempts}_{datetime.now().timestamp()}"

        result = streamlit_js_eval(
            js_expressions=f"localStorage.getItem('{LOCALSTORAGE_KEY}')",
            key=key
        )

        if not result:
            return None

        auth_data = json.loads(result)

        # 驗證必要欄位
        if not auth_data.get("email") or not auth_data.get("refresh_token"):
            logger.warning("localStorage 資料缺少必要欄位")
            return None

        # 驗證校驗碼（防篡改）
        if "checksum" in auth_data:
            expected = _compute_checksum(auth_data['email'], auth_data['refresh_token'])
            if auth_data["checksum"] != expected:
                logger.warning("認證資料校驗失敗，可能被篡改")
                return None

        # 驗證是否過期
        if "expires_at" in auth_data:
            expires_at = datetime.fromisoformat(auth_data["expires_at"])
            if datetime.now() > expires_at:
                logger.info("認證資料已過期")
                return None

        return auth_data

    except ImportError:
        logger.debug("streamlit-js-eval 未安裝")
        return None
    except json.JSONDecodeError:
        logger.warning("localStorage 資料格式錯誤")
        return None
    except Exception as e:
        logger.debug(f"localStorage 讀取失敗: {e}")
        return None


def load_auth_cookie() -> Optional[Dict]:
    """
    從 Cookie 載入認證資訊（備援方案）

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

        # 驗證校驗碼（如果有）
        if "checksum" in auth_data:
            expected = _compute_checksum(auth_data['email'], auth_data['refresh_token'])
            if auth_data["checksum"] != expected:
                logger.warning("Cookie 認證資料校驗失敗")
                return None

        # 驗證是否過期
        if "expires_at" in auth_data:
            expires_at = datetime.fromisoformat(auth_data["expires_at"])
            if datetime.now() > expires_at:
                logger.info("Cookie 認證資料已過期")
                return None

        return auth_data

    except json.JSONDecodeError:
        logger.warning("Cookie 格式錯誤")
        return None
    except Exception as e:
        logger.warning(f"載入 Cookie 失敗: {e}")
        return None


def clear_auth_storage():
    """清除所有認證存儲（localStorage + Cookie）"""
    # 清除 localStorage
    try:
        from streamlit_js_eval import streamlit_js_eval
        streamlit_js_eval(
            js_expressions=f"localStorage.removeItem('{LOCALSTORAGE_KEY}')",
            key=f"clear_ls_{datetime.now().timestamp()}"
        )
        logger.info("localStorage 認證資料已清除")
    except Exception as e:
        logger.debug(f"localStorage 清除失敗: {e}")

    # 清除 Cookie
    try:
        cookie_manager = _get_cookie_manager()
        if cookie_manager:
            cookie_manager.delete(COOKIE_NAME)
            logger.info("Cookie 認證資料已清除")
    except Exception as e:
        logger.debug(f"Cookie 清除失敗: {e}")


# ==================== 頁面可見性監聽 ====================

def inject_visibility_listener():
    """
    注入頁面可見性監聽器

    當用戶從其他 app 切回時（visibilitychange 事件），
    如果隱藏時間超過閾值，主動觸發頁面重新載入，
    確保 Streamlit 執行恢復邏輯

    這是解決手機切換 app 後登出問題的關鍵！
    """
    # 只注入一次
    if st.session_state.get('visibility_listener_injected'):
        return

    js_code = f"""
    <script>
    (function() {{
        // 防止重複注入
        if (window._v7_visibility_listener) return;
        window._v7_visibility_listener = true;

        // 記錄最後活動時間
        let lastActiveTime = Date.now();

        document.addEventListener('visibilitychange', function() {{
            if (document.hidden) {{
                // 頁面隱藏，記錄時間
                lastActiveTime = Date.now();
                console.log('[V7 Auth] 頁面隱藏');
            }} else {{
                // 頁面可見
                const hiddenDuration = Date.now() - lastActiveTime;
                console.log('[V7 Auth] 頁面可見，隱藏時長: ' + hiddenDuration + 'ms');

                // 如果隱藏超過閾值，觸發重新載入以恢復 session
                if (hiddenDuration > {VISIBILITY_HIDDEN_THRESHOLD}) {{
                    console.log('[V7 Auth] 隱藏超過 {VISIBILITY_HIDDEN_THRESHOLD/1000} 秒，觸發重新載入');
                    // 標記需要恢復（可選，用於調試）
                    localStorage.setItem('v7_need_restore', 'true');
                    // 重新載入頁面
                    window.location.reload();
                }}
            }}
        }});

        // 檢查是否需要恢復（由上一次 reload 觸發）
        if (localStorage.getItem('v7_need_restore') === 'true') {{
            localStorage.removeItem('v7_need_restore');
            console.log('[V7 Auth] 頁面已重載，執行登入恢復');
        }}

        console.log('[V7 Auth] 可見性監聽器已安裝');
    }})();
    </script>
    """

    components.html(js_code, height=0)
    st.session_state.visibility_listener_injected = True


# ==================== Token 管理 ====================

def ensure_valid_token(api_base_url: str) -> bool:
    """
    確保 Access Token 有效

    在每次 API 請求前呼叫，自動處理 Token 刷新
    如果 Token 即將過期（< 5 分鐘），主動刷新

    Args:
        api_base_url: API 基礎 URL

    Returns:
        bool: Token 是否有效
    """
    if not st.session_state.get('user_token'):
        return False

    try:
        import jwt

        # 解析 Token（不驗證簽名，只讀取 payload）
        payload = jwt.decode(
            st.session_state.user_token,
            options={"verify_signature": False}
        )

        exp = payload.get('exp')
        if exp:
            exp_time = datetime.fromtimestamp(exp)
            now = datetime.now()

            # 如果還有超過 5 分鐘，Token 有效
            remaining = (exp_time - now).total_seconds()
            if remaining > 300:
                return True

            # 即將過期，嘗試刷新
            logger.info(f"Access Token 即將過期（剩餘 {remaining:.0f} 秒），嘗試刷新")
            return refresh_access_token(api_base_url)

        return True

    except ImportError:
        logger.debug("PyJWT 未安裝，跳過 Token 過期檢查")
        return True
    except Exception as e:
        logger.warning(f"Token 檢查失敗: {e}")
        # 嘗試刷新
        return refresh_access_token(api_base_url)


def refresh_access_token(api_base_url: str) -> bool:
    """
    刷新 Access Token

    Args:
        api_base_url: API 基礎 URL

    Returns:
        bool: 刷新成功返回 True，失敗返回 False
    """
    if not st.session_state.get('refresh_token'):
        return False

    try:
        response = requests.post(
            f"{api_base_url}/auth/refresh",
            json={"refresh_token": st.session_state.refresh_token},
            timeout=10
        )

        if response.status_code == 200:
            data = response.json()
            st.session_state.user_token = data["access_token"]
            logger.info("Access Token 已刷新")
            return True
        else:
            # Refresh token 過期或無效，需要重新登入
            logger.warning(f"Token 刷新失敗: {response.status_code}")
            return False

    except Exception as e:
        logger.warning(f"Token 刷新失敗: {e}")
        return False


# ==================== 智能恢復機制 ====================

def try_restore_session(api_base_url: str) -> bool:
    """
    智能恢復登入狀態（指數退避 + 多源讀取）

    策略：
    1. 優先從 localStorage 讀取（更可靠，使用 streamlit-js-eval）
    2. 回退到 Cookie 讀取（CookieManager，作為備援）
    3. 使用指數退避重試（最多 5 次，間隔遞增）
    4. 成功讀取後使用 refresh_token 獲取新的 access_token

    流程：
    1. 檢查是否已經認證（避免重複）
    2. 檢查是否已完成恢復流程
    3. 多源讀取認證資料
    4. 使用 refresh_token 恢復 session

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

    # 如果已經完成恢復流程（無論成功與否）
    if st.session_state.get('cookie_restore_done'):
        return False

    # 取得當前嘗試次數
    attempts = st.session_state.get('cookie_restore_attempts', 0)
    st.session_state.cookie_restore_attempts = attempts + 1

    # 等待（第一次不等待，之後指數退避）
    if attempts > 0 and attempts < len(BACKOFF_TIMES):
        wait_time = BACKOFF_TIMES[attempts]
        if wait_time > 0:
            # 顯示恢復中提示
            st.info(f"🔄 正在恢復登入狀態... ({attempts}/{MAX_RESTORE_ATTEMPTS})")
            pytime.sleep(wait_time)

    # === 多源讀取策略 ===
    auth_data = None
    source = None

    # 嘗試 1: localStorage（優先，更可靠）
    auth_data = load_auth_from_localstorage()
    if auth_data:
        source = "localStorage"
        logger.info("從 localStorage 讀取成功")

    # 嘗試 2: Cookie（備援）
    if auth_data is None:
        auth_data = load_auth_cookie()
        if auth_data:
            source = "Cookie"
            logger.info("從 Cookie 讀取成功")

    # 如果都讀不到，繼續重試
    if auth_data is None:
        if attempts < MAX_RESTORE_ATTEMPTS:
            logger.info(f"嘗試 {attempts + 1}/{MAX_RESTORE_ATTEMPTS} 失敗，繼續重試...")
            st.rerun()
            return False
        else:
            st.session_state.cookie_restore_done = True
            logger.info("認證恢復失敗：超過最大嘗試次數")
            return False

    # === 使用 refresh_token 恢復 session ===
    email = auth_data.get("email")
    refresh_token = auth_data.get("refresh_token")

    if not email or not refresh_token:
        st.session_state.cookie_restore_done = True
        return False

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

            logger.info(f"Session 已從 {source} 恢復: {email}")
            return True
        else:
            # Token 無效，清除存儲
            logger.info(f"Refresh token 已過期或無效（HTTP {response.status_code}），清除存儲")
            clear_auth_storage()
            st.session_state.cookie_restore_done = True
            return False

    except requests.exceptions.Timeout:
        logger.warning("API 請求超時")
        if attempts < MAX_RESTORE_ATTEMPTS:
            st.rerun()
            return False
        st.session_state.cookie_restore_done = True
        return False
    except requests.exceptions.ConnectionError:
        logger.warning("無法連接伺服器")
        if attempts < MAX_RESTORE_ATTEMPTS:
            st.rerun()
            return False
        st.session_state.cookie_restore_done = True
        return False
    except Exception as e:
        logger.warning(f"恢復 Session 失敗: {e}")
        st.session_state.cookie_restore_done = True
        return False


# ==================== 登入/登出 ====================

def login(api_base_url: str, email: str, password: str, remember_me: bool = False) -> Dict:
    """
    執行登入

    改進點（v2.0）：
    1. 成功後同時存入 localStorage 和 Cookie（雙重存儲）
    2. 重置所有恢復狀態標記

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

            # 如果勾選「記住我」，使用雙重存儲
            if remember_me:
                save_auth_dual(email, data["refresh_token"])

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

    改進點（v2.0）：
    1. 清除 localStorage
    2. 清除 Cookie
    3. 通知後端使 session 失效
    4. 重置所有狀態標記

    Args:
        api_base_url: API 基礎 URL
    """
    # 通知後端登出（使 session 失效）
    if st.session_state.get('refresh_token'):
        try:
            requests.post(
                f"{api_base_url}/auth/logout",
                json={"refresh_token": st.session_state.refresh_token},
                timeout=5
            )
        except Exception:
            pass  # 即使後端通知失敗，也繼續清除本地狀態

    # 清除雙重存儲
    clear_auth_storage()

    # 清除 session state
    st.session_state.user_token = None
    st.session_state.user_email = None
    st.session_state.refresh_token = None
    st.session_state.user_id = None
    st.session_state.username = None
    st.session_state.remember_me = False
    st.session_state.cookie_restore_attempts = 0
    st.session_state.cookie_restore_done = False
    st.session_state.visibility_listener_injected = False

    st.success("已登出")
    st.rerun()


# ==================== UI 元件 ====================

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
                st.caption("✅ 已啟用自動登入（7 天）")

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
