# -*- coding: utf-8 -*-
"""
V7 即時監控系統 - Public App 版本
台指期貨選擇權策略即時監控

本應用為 Public App，但所有功能都需要 JWT 認證保護
"""
import streamlit as st
import os
import sys
import requests
from pathlib import Path
from datetime import datetime, time, timedelta
import time as pytime
from typing import Optional, Dict

# 添加 utils 到路徑
sys.path.insert(0, str(Path(__file__).parent))

# 導入認證和 API 客戶端
from utils.auth import init_session, is_authenticated, render_user_info_sidebar
from utils.api_client import APIClient

# API 基礎 URL（從 Streamlit Secrets 讀取）
API_BASE_URL = st.secrets.get("API_BASE_URL", "http://localhost:8000/api/v1")
if not API_BASE_URL.endswith('/api/v1'):
    API_BASE_URL = API_BASE_URL + '/api/v1'

# ==================== 頁面配置 ====================
st.set_page_config(
    page_title="V7 即時監控系統",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== 阻止搜尋引擎索引 ====================
st.markdown("""
<meta name="robots" content="noindex, nofollow">
""", unsafe_allow_html=True)

# ==================== 登入/註冊頁面 ====================
def auth_page():
    """登入/註冊頁面"""
    st.title("📡 V7 即時監控系統")
    st.markdown("### 台指期貨選擇權策略即時監控")

    tab1, tab2 = st.tabs(["🔑 登入", "📝 註冊"])

    with tab1:
        st.markdown("#### 用戶登入")

        email = st.text_input("Email", key="login_email")
        password = st.text_input("密碼", type="password", key="login_password")

        if st.button("登入", use_container_width=True):
            if not email or not password:
                st.error("❌ 請填寫所有欄位")
                return

            try:
                response = requests.post(
                    f"{API_BASE_URL}/auth/login",
                    json={"email": email, "password": password}
                )

                if response.status_code == 200:
                    data = response.json()
                    st.session_state.user_token = data["access_token"]
                    st.session_state.refresh_token = data["refresh_token"]
                    st.session_state.user_email = email
                    st.success("✅ 登入成功！")
                    st.rerun()
                else:
                    error = response.json().get("detail", "登入失敗")
                    st.error(f"❌ {error}")
            except Exception as e:
                st.error(f"❌ 連接失敗：{str(e)}")

    with tab2:
        st.markdown("#### 新用戶註冊")

        reg_email = st.text_input("Email", key="reg_email")
        reg_username = st.text_input("用戶名", key="reg_username")
        reg_password = st.text_input("密碼（至少8位，包含字母和數字）", type="password", key="reg_password")
        reg_password2 = st.text_input("確認密碼", type="password", key="reg_password2")
        invite_code = st.text_input("邀請碼", key="invite_code")

        st.info("💡 請向管理員索取邀請碼")

        if st.button("註冊", use_container_width=True):
            # 驗證
            if not all([reg_email, reg_username, reg_password, invite_code]):
                st.error("❌ 請填寫所有欄位")
                return

            if reg_password != reg_password2:
                st.error("❌ 兩次密碼不一致")
                return

            if len(reg_password) < 8:
                st.error("❌ 密碼至少8位")
                return

            try:
                response = requests.post(
                    f"{API_BASE_URL}/auth/register",
                    json={
                        "email": reg_email,
                        "username": reg_username,
                        "password": reg_password,
                        "invite_code": invite_code
                    }
                )

                if response.status_code == 201:
                    st.success("✅ 註冊成功！請使用Email和密碼登入")
                else:
                    error = response.json().get("detail", "註冊失敗")
                    st.error(f"❌ {error}")
            except Exception as e:
                st.error(f"❌ 連接失敗：{str(e)}")

    st.markdown("---")
    st.markdown("""
    ### 📚 系統說明

    **V7 即時監控系統** 提供雙策略即時監控：

    #### 🎯 核心功能
    - 📊 雙策略監控（原始 V7 + Phase3 優化）
    - ⏱️ 30 秒自動刷新（交易時段）
    - 📈 8 個市場指標即時監控
    - 🎯 訊號窗口：09:00-09:30
    - 📜 今日訊號歷史記錄

    #### 📊 策略特色
    - **原始 V7 策略**：40 個歷史樣本，72.5% 勝率
    - **Phase3 優化策略**：23 個歷史樣本，87% 勝率

    #### 🎓 教育免責聲明
    ⚠️ **本系統僅供教育研究用途**
    - 所有策略基於歷史數據回測，不代表未來表現
    - 期貨交易存在高度風險，可能導致本金全部損失
    - 使用者應自行評估風險，本系統不提供投資建議
    - 任何交易決策由使用者自行負責
    """)

# ==================== 初始化 API 客戶端 ====================
api_client = APIClient(API_BASE_URL)

# ==================== 常數定義 ====================
REFRESH_INTERVAL = 30  # 秒
SIGNAL_WINDOW_START = time(9, 0)
SIGNAL_WINDOW_END = time(9, 30)
TRADING_START = time(8, 45)
TRADING_END = time(13, 45)

# ==================== 自定義 CSS ====================
st.markdown("""
<style>
/* 訊號盒樣式 */
.signal-box {
    padding: 20px;
    border-radius: 10px;
    margin: 10px 0;
    text-align: center;
}
.signal-call {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
}
.signal-put {
    background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
    color: white;
}
.signal-none {
    background: linear-gradient(135deg, #e0e0e0 0%, #bdbdbd 100%);
    color: #666;
}

/* 倒數計時器樣式 */
.countdown-timer {
    background: #1e1e1e;
    border: 2px solid #ff6b6b;
    border-radius: 10px;
    padding: 15px;
    text-align: center;
    color: #ff6b6b;
    font-size: 24px;
    font-weight: bold;
    margin: 20px 0;
}

/* 時間軸樣式 */
.timeline {
    position: relative;
    height: 40px;
    background: #f0f0f0;
    border-radius: 20px;
    margin: 20px 0;
}
.timeline-progress {
    height: 100%;
    background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
    border-radius: 20px;
    transition: width 0.3s ease;
}
.timeline-marker {
    position: absolute;
    top: -5px;
    width: 4px;
    height: 50px;
    background: #ff6b6b;
}
</style>
""", unsafe_allow_html=True)

# ==================== Session State 初始化 ====================
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = datetime.now()
if 'prev_scores' not in st.session_state:
    st.session_state.prev_scores = {'original': 0, 'optimized': 0}
if 'signal_history' not in st.session_state:
    st.session_state.signal_history = []
if 'auto_refresh_enabled' not in st.session_state:
    st.session_state.auto_refresh_enabled = True

# ==================== 工具函數 ====================
def get_taiwan_now() -> datetime:
    """獲取台灣時間（UTC+8）"""
    return datetime.now() + timedelta(hours=8)

def is_trading_hours(now: datetime) -> bool:
    """檢查是否在交易時段"""
    current_time = now.time()
    return TRADING_START <= current_time <= TRADING_END

def is_signal_window(now: datetime) -> bool:
    """檢查是否在訊號窗口"""
    current_time = now.time()
    return SIGNAL_WINDOW_START <= current_time <= SIGNAL_WINDOW_END

def get_trading_progress(now: datetime) -> float:
    """計算交易時段進度百分比（返回 0.0 到 1.0）"""
    if not is_trading_hours(now):
        return 0.0

    current_time = now.time()
    start_seconds = TRADING_START.hour * 3600 + TRADING_START.minute * 60
    end_seconds = TRADING_END.hour * 3600 + TRADING_END.minute * 60
    current_seconds = current_time.hour * 3600 + current_time.minute * 60

    # 計算進度（0.0 到 1.0）
    total_seconds = end_seconds - start_seconds
    elapsed_seconds = current_seconds - start_seconds

    if total_seconds <= 0:
        return 0.0

    progress = elapsed_seconds / total_seconds
    # 確保進度在 0.0 到 1.0 之間
    return max(0.0, min(1.0, progress))


# ==================== UI 渲染函數 ====================
def render_countdown_timer(seconds_until_refresh: int):
    """渲染倒數計時器"""
    st.markdown(f"""
    <div class="countdown-timer">
        ⏱️ 下次更新: {seconds_until_refresh} 秒
    </div>
    """, unsafe_allow_html=True)

def render_timeline(now: datetime):
    """渲染交易時段時間軸"""
    progress = get_trading_progress(now)

    # 防禦性檢查：確保 progress 是有效的數字
    if progress is None or not isinstance(progress, (int, float)):
        progress = 0.0

    progress_pct = progress * 100

    st.markdown(f"""
    <div class="timeline">
        <div class="timeline-progress" style="width: {progress_pct}%"></div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.caption(f"開盤: {TRADING_START.strftime('%H:%M')}")
    with col2:
        st.caption(f"訊號窗口: {SIGNAL_WINDOW_START.strftime('%H:%M')}-{SIGNAL_WINDOW_END.strftime('%H:%M')}")
    with col3:
        st.caption(f"收盤: {TRADING_END.strftime('%H:%M')}")

def render_dual_strategy_status(result: Dict, prev_scores: Dict):
    """渲染雙策略狀態"""
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📊 原始 V7 策略")
        original = result.get('original', {})
        score = original.get('score', 0)
        matched = original.get('matched', False)
        direction = original.get('direction', 'NONE')

        # 計算分數變化
        score_change = score - prev_scores.get('original', 0)
        change_icon = "↗️" if score_change > 0 else ("↘️" if score_change < 0 else "→")

        if matched:
            st.markdown(f"""
            <div class="signal-box signal-{'call' if direction == 'CALL' else 'put'}">
                <h2>{'🟢 CALL' if direction == 'CALL' else '🔴 PUT'}</h2>
                <p>分數: {score} {change_icon} ({score_change:+d})</p>
                <p>勝率: {original.get('win_rate', 0):.1%}</p>
                <p>樣本: {original.get('samples', 0)} 筆</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="signal-box signal-none">
                <h2>⚪ 無訊號</h2>
                <p>分數: {score} {change_icon} ({score_change:+d})</p>
            </div>
            """, unsafe_allow_html=True)

            # 顯示不符合原因
            if original.get('unmatch_reasons'):
                with st.expander("查看不符合原因"):
                    for reason in original['unmatch_reasons']:
                        st.write(f"- {reason}")

    with col2:
        st.subheader("🎯 Phase3 優化策略")
        optimized = result.get('optimized', {})
        score = optimized.get('score', 0)
        matched = optimized.get('matched', False)
        direction = optimized.get('direction', 'NONE')

        # 計算分數變化
        score_change = score - prev_scores.get('optimized', 0)
        change_icon = "↗️" if score_change > 0 else ("↘️" if score_change < 0 else "→")

        if matched:
            st.markdown(f"""
            <div class="signal-box signal-{'call' if direction == 'CALL' else 'put'}">
                <h2>{'🟢 CALL' if direction == 'CALL' else '🔴 PUT'}</h2>
                <p>分數: {score} {change_icon} ({score_change:+d})</p>
                <p>勝率: {optimized.get('win_rate', 0):.1%}</p>
                <p>樣本: {optimized.get('samples', 0)} 筆</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="signal-box signal-none">
                <h2>⚪ 無訊號</h2>
                <p>分數: {score} {change_icon} ({score_change:+d})</p>
            </div>
            """, unsafe_allow_html=True)

            # 顯示不符合原因
            if optimized.get('unmatch_reasons'):
                with st.expander("查看不符合原因"):
                    for reason in optimized['unmatch_reasons']:
                        st.write(f"- {reason}")

def render_market_data(market_data: Dict):
    """渲染市場數據"""
    st.subheader("📈 市場數據")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("當前價格", f"{market_data.get('current_price', 0):.0f}")
    with col2:
        st.metric("VWAP", f"{market_data.get('vwap', 0):.0f}")
    with col3:
        st.metric("MA20", f"{market_data.get('ma20', 0):.0f}")
    with col4:
        st.metric("MA5", f"{market_data.get('ma5', 0):.0f}")

    col5, col6, col7, col8 = st.columns(4)

    with col5:
        st.metric("60分K值", f"{market_data.get('kd_k', 0):.1f}")
    with col6:
        st.metric("60分D值", f"{market_data.get('kd_d', 0):.1f}")
    with col7:
        st.metric("盤中趨勢", f"{market_data.get('intraday_trend', 0):.0f}")
    with col8:
        st.metric("距MA5", f"{market_data.get('price_vs_ma5', 0):.0f}")

def render_signal_history():
    """渲染訊號歷史記錄（全局訊號）"""
    st.subheader("📜 今日訊號歷史")
    st.caption("📡 全市場訊號 — 所有用戶看到相同內容")

    try:
        # 從後端 API 獲取今日全局訊號記錄
        response = api_client.get_v7_signals_today()

        # 處理不同的響應格式
        signals = []
        if response:
            # 如果響應是字典且包含 'signals' 鍵（API client 應該已經提取了）
            if isinstance(response, dict) and 'signals' in response:
                signals = response['signals']
            # 如果響應直接是列表（正常情況）
            elif isinstance(response, list):
                signals = response
            # 其他情況
            else:
                st.warning(f"未預期的響應格式: {type(response)}")
                signals = []

        if signals and len(signals) > 0:
            for signal in signals:
                # 確保 signal 是字典
                if not isinstance(signal, dict):
                    st.warning(f"訊號格式錯誤: {type(signal)}")
                    continue

                col1, col2, col3, col4 = st.columns([1, 1, 1, 2])

                with col1:
                    st.write(signal.get('signal_time', ''))
                with col2:
                    strategy = signal.get('strategy_version', '')
                    st.write("原始V7" if strategy == "ORIGINAL" else "優化策略")
                with col3:
                    direction = signal.get('direction', '')
                    if direction == 'CALL':
                        st.write("🟢 CALL")
                    else:
                        st.write("🔴 PUT")
                with col4:
                    score = signal.get('score', 0)
                    win_rate = signal.get('win_rate', 0)
                    st.write(f"分數: {score} | 勝率: {win_rate:.1%}")
        else:
            st.info("今日尚無訊號記錄")

    except Exception as e:
        st.error(f"載入訊號歷史失敗：{str(e)}")
        import traceback
        st.code(traceback.format_exc())

# ==================== V7 監控頁面 ====================
def v7_monitor_page():
    """V7 即時監控主頁面（需要認證）"""
    # 標題
    st.title("📡 V7 即時監控系統")

    # 側邊欄顯示用戶資訊
    render_user_info_sidebar(API_BASE_URL)

    # 獲取當前時間
    now = get_taiwan_now()

    # 顯示當前時間和交易狀態
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"🕐 當前時間: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    with col2:
        if is_trading_hours(now):
            if is_signal_window(now):
                st.success("✅ 訊號窗口開啟中")
            else:
                st.info("📊 交易時段")
        else:
            st.warning("💤 非交易時段")

    # 自動刷新開關
    auto_refresh = st.checkbox(
        "啟用自動刷新（30秒）",
        value=st.session_state.auto_refresh_enabled,
        key="auto_refresh_toggle"
    )
    st.session_state.auto_refresh_enabled = auto_refresh

    st.markdown("---")

    # 渲染時間軸
    render_timeline(now)

    # 計算距離下次刷新的時間
    elapsed = (now - st.session_state.last_refresh).total_seconds()
    seconds_until_refresh = max(0, int(REFRESH_INTERVAL - elapsed))

    # 渲染倒數計時器
    if auto_refresh and is_trading_hours(now):
        render_countdown_timer(seconds_until_refresh)

    st.markdown("---")

    # 手動刷新按鈕
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🔄 立即刷新", type="primary", use_container_width=True):
            st.session_state.last_refresh = now
            st.rerun()

    st.markdown("---")

    # 準備 API 請求參數（使用當前台灣時間）
    analysis_date = now.strftime('%Y-%m-%d')
    analysis_time = now.strftime('%H:%M')

    # 調用後端 API 獲取策略分析
    try:
        with st.spinner("🔄 正在分析策略..."):
            response = api_client.post('/v7/analyze', data={
                'analysis_date': analysis_date,
                'analysis_time': analysis_time
            })

            # 檢查 HTTP 狀態碼
            if response.status_code == 200:
                result = response.json()

                if result and result.get('success'):
                    # 渲染雙策略狀態
                    render_dual_strategy_status(result, st.session_state.prev_scores)

                    # 更新分數記錄
                    st.session_state.prev_scores = {
                        'original': result.get('original', {}).get('score', 0),
                        'optimized': result.get('optimized', {}).get('score', 0)
                    }

                    st.markdown("---")

                    # 渲染市場數據
                    if 'market_data' in result:
                        render_market_data(result['market_data'])

                    st.markdown("---")

                    # 渲染訊號歷史
                    render_signal_history()
                else:
                    st.error(f"❌ 分析失敗：{result.get('error', '未知錯誤')}")
            elif response.status_code == 422:
                # Pydantic 驗證錯誤 - 提供更友善的錯誤訊息
                try:
                    error_data = response.json()
                    error_detail = error_data.get('detail', [])
                    if isinstance(error_detail, list):
                        missing_fields = [e.get('loc', ['', ''])[-1] for e in error_detail if e.get('type') == 'missing']
                        if missing_fields:
                            error_msg = f"缺少必要參數：{', '.join(missing_fields)}"
                        else:
                            error_msg = "請求參數驗證失敗"
                    else:
                        error_msg = str(error_detail)
                except:
                    error_msg = "請求參數驗證失敗"
                st.error(f"❌ 分析失敗：{error_msg}")
            else:
                # 處理其他 HTTP 錯誤
                try:
                    error_data = response.json()
                    error_msg = error_data.get('detail', '未知錯誤')
                except:
                    error_msg = f"HTTP {response.status_code}"
                st.error(f"❌ 分析失敗：{error_msg}")

    except Exception as e:
        st.error(f"❌ 系統錯誤：{str(e)}")

    st.markdown("---")

    # 自動刷新邏輯
    if auto_refresh and is_trading_hours(now) and seconds_until_refresh <= 0:
        st.session_state.last_refresh = now
        pytime.sleep(1)
        st.rerun()

    # 風險提示
    st.caption("⚠️ 本系統僅供教育和研究用途，不構成投資建議。投資有風險，請謹慎決策。")

# ==================== 主程式 ====================
def main():
    """主程式入口"""
    init_session()

    # 檢查登入狀態
    if not is_authenticated():
        auth_page()
    else:
        v7_monitor_page()

# ==================== 主程式入口 ====================
if __name__ == "__main__":
    main()

