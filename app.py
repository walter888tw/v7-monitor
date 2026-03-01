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
from typing import Optional, Dict, List
import plotly.graph_objects as go
import html as html_module

# 添加 utils 到路徑
sys.path.insert(0, str(Path(__file__).parent))

# 導入認證和 API 客戶端
from utils.auth import (
    init_session, is_authenticated, render_user_info_sidebar,
    try_restore_session, login, inject_visibility_listener,
    render_loading_screen
)
from utils.api_client import APIClient

# API 基礎 URL（從 Streamlit Secrets 讀取，無 secrets 時使用環境變數或預設值）
try:
    API_BASE_URL = st.secrets.get("API_BASE_URL", "http://localhost:8000/api/v1")
except Exception:
    API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")
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
        remember_me = st.checkbox("記住我（7天內自動登入）", key="login_remember_me")

        if st.button("登入", use_container_width=True):
            if not email or not password:
                st.error("❌ 請填寫所有欄位")
                return

            # 使用 Cookie 持久化登入
            result = login(API_BASE_URL, email, password, remember_me)

            if result["success"]:
                st.success("✅ 登入成功！")
                st.rerun()
            else:
                st.error(f"❌ {result['message']}")

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

    **V7 即時監控系統** 提供三策略即時監控：

    #### 🎯 核心功能
    - 📊 三策略監控（原始 V7 + Phase3 優化 + 盤中動態）
    - ⏱️ 15 秒自動刷新（交易時段）
    - 📈 8 個市場指標即時監控
    - 🎯 訊號窗口：09:00-09:30（原始/優化）+ 09:00-13:25（盤中動態）
    - 📜 今日訊號歷史記錄

    #### 📊 策略特色
    - **原始 V7 策略**：40 個歷史樣本，72.5% 勝率
    - **Phase3 優化策略**：23 個歷史樣本，87% 勝率
    - **盤中動態策略**：31 個歷史樣本，96.8% 勝率（第三引擎）

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
REFRESH_INTERVAL = 15  # 秒（與 VIX 數據更新頻率同步）
SIGNAL_WINDOW_START = time(9, 0)
SIGNAL_WINDOW_END = time(9, 30)
INTRADAY_WINDOW_START = time(9, 0)
INTRADAY_WINDOW_END = time(13, 25)
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
.signal-intraday-call {
    background: linear-gradient(135deg, #f6d365 0%, #fda085 100%);
    color: #333;
}
.signal-intraday-put {
    background: linear-gradient(135deg, #fbc2eb 0%, #f6d365 100%);
    color: #333;
}
.signal-intraday-none {
    background: linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%);
    color: #999;
}
.intraday-detail {
    padding: 8px 12px;
    border-radius: 8px;
    margin: 4px 0;
    background: rgba(246, 211, 101, 0.1);
    border-left: 3px solid #f6d365;
    font-size: 14px;
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

/* 信用風險預警面板 v3.0 — 五級燈號 + WCAG AA + 色盲友善 */
.cr-header {
    padding: 18px 20px;
    border-radius: 12px;
    margin: 10px 0;
    text-align: center;
    font-weight: bold;
}
.cr-header.double_red { background: linear-gradient(135deg, #8b0000 0%, #ff0000 100%); color: white; }
.cr-header.red { background: linear-gradient(135deg, #ff416c 0%, #ff4b2b 100%); color: white; }
.cr-header.orange { background: linear-gradient(135deg, #f7971e 0%, #ffd200 100%); color: #333; }
.cr-header.yellow { background: linear-gradient(135deg, #f5c842 0%, #e6a817 100%); color: #333; }
.cr-header.green { background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); color: white; }

.cr-card {
    padding: 12px 16px;
    border-radius: 10px;
    margin: 6px 0;
}
/* P0 色盲友善: border-style 區分燈號 (solid/dashed/double) */
.cr-card.green { background: rgba(56,239,125,0.08); border-left: 4px solid #38ef7d; }
.cr-card.yellow { background: rgba(245,200,66,0.08); border-left: 4px solid #e6a817; }
.cr-card.orange { background: rgba(247,151,30,0.08); border-left: 4px dashed #f7971e; }
.cr-card.red { background: rgba(255,65,108,0.08); border-left: 4px double #ff416c; }
.cr-card.double_red { background: rgba(139,0,0,0.10); border-left: 6px double #8b0000; }
.cr-card.pending { background: rgba(150,150,150,0.06); border-left: 4px dotted #999; }
.cr-card.unknown { background: rgba(150,150,150,0.04); border-left: 4px dotted #ccc; }

.cr-title {
    font-size: 14px; font-weight: 600; margin-bottom: 6px;
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.cr-badge {
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 11px; font-weight: 600; line-height: 1.4;
}
.cr-badge.green { background: rgba(56,239,125,0.15); color: #0a8f3f; }
.cr-badge.yellow { background: rgba(245,200,66,0.18); color: #8a6d00; }
.cr-badge.orange { background: rgba(247,151,30,0.15); color: #c26200; }
.cr-badge.red { background: rgba(255,65,108,0.15); color: #d32f2f; }
.cr-badge.double_red { background: rgba(139,0,0,0.18); color: #8b0000; }
.cr-badge.pending { background: rgba(150,150,150,0.10); color: #888; }
.cr-badge.unknown { background: rgba(150,150,150,0.08); color: #aaa; }

/* P0 WCAG AA: #555 on white = 7.46:1 */
.cr-tree {
    font-family: 'Cascadia Code', 'Consolas', 'Monaco', monospace;
    font-size: 12px; color: #555; line-height: 1.7; white-space: pre-wrap;
}
.cr-tree .val-up { color: #0a8f3f; font-weight: 600; }
.cr-tree .val-dn { color: #d32f2f; font-weight: 600; }
.cr-tree .val-neutral { color: #666; }

.cr-trigger {
    font-size: 12px; color: #b8860b; margin-top: 6px;
    background: rgba(245,200,66,0.08); border-left: 3px solid #e6a817;
    padding: 4px 8px; border-radius: 0 4px 4px 0;
}

.cr-ticker {
    display: inline-block; padding: 2px 7px; border-radius: 5px;
    font-size: 11px; font-weight: 500; margin: 1px;
}
.cr-ticker.up { background: rgba(56,239,125,0.12); color: #0a8f3f; }
.cr-ticker.down { background: rgba(255,65,108,0.12); color: #d32f2f; }
.cr-ticker.flat { background: rgba(150,150,150,0.08); color: #888; }

.cr-news {
    padding: 6px 10px; border-radius: 6px; margin: 3px 0;
    background: rgba(47,128,237,0.04); border-left: 3px solid #2f80ed; font-size: 12px;
}
.cr-news a { color: #2f80ed; text-decoration: none; }
.cr-news-meta { font-size: 10px; color: #888; }

/* P2 概覽列 */
.cr-summary-bar {
    display: flex; justify-content: center; gap: 12px;
    padding: 8px 0; margin-bottom: 4px;
}
.cr-summary-dot {
    width: 14px; height: 14px; border-radius: 50%;
    display: inline-block; border: 2px solid rgba(255,255,255,0.3);
}
.cr-summary-dot.green { background: #38ef7d; }
.cr-summary-dot.yellow { background: #e6a817; }
.cr-summary-dot.orange { background: #f7971e; }
.cr-summary-dot.red { background: #ff416c; }
.cr-summary-dot.double_red { background: #8b0000; }
.cr-summary-dot.pending { background: #999; }

/* P2 手機端 */
@media (max-width: 640px) {
    .cr-header { padding: 12px 14px; }
    .cr-header > div:first-child { font-size: 15px !important; }
    .cr-card { padding: 10px 12px; }
    .cr-tree { font-size: 11px; }
    .cr-trigger { font-size: 11px; }
    .cr-title { font-size: 13px; }
}

/* P1 暗色模式 */
@media (prefers-color-scheme: dark) {
    .cr-tree { color: #ccc; }
    .cr-tree .val-up { color: #4cdf8f; }
    .cr-tree .val-dn { color: #ff7b7b; }
    .cr-trigger { color: #e6c55a; background: rgba(245,200,66,0.12); }
    .cr-card.green { background: rgba(56,239,125,0.12); }
    .cr-card.yellow { background: rgba(245,200,66,0.12); }
    .cr-card.orange { background: rgba(247,151,30,0.12); }
    .cr-card.red { background: rgba(255,65,108,0.12); }
    .cr-card.double_red { background: rgba(139,0,0,0.15); }
    .cr-news { background: rgba(47,128,237,0.08); }
    .cr-news-meta { color: #aaa; }
    .cr-badge.green { background: rgba(56,239,125,0.20); color: #4cdf8f; }
    .cr-badge.yellow { background: rgba(245,200,66,0.22); color: #e6c55a; }
    .cr-badge.orange { background: rgba(247,151,30,0.20); color: #f7971e; }
    .cr-badge.red { background: rgba(255,65,108,0.20); color: #ff7b7b; }
    .cr-badge.double_red { background: rgba(139,0,0,0.22); color: #ff5555; }
}
</style>
""", unsafe_allow_html=True)

# ==================== Session State 初始化 ====================
if 'last_refresh' not in st.session_state:
    st.session_state.last_refresh = datetime.now()
if 'prev_scores' not in st.session_state:
    st.session_state.prev_scores = {'original': 0, 'optimized': 0, 'intraday': 0}
if 'signal_history' not in st.session_state:
    st.session_state.signal_history = []
if 'auto_refresh_enabled' not in st.session_state:
    st.session_state.auto_refresh_enabled = True
if 'credit_risk_cache' not in st.session_state:
    st.session_state.credit_risk_cache = None

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

def is_intraday_signal_window(now: datetime) -> bool:
    """檢查是否在盤中動態訊號窗口"""
    current_time = now.time()
    return INTRADAY_WINDOW_START <= current_time <= INTRADAY_WINDOW_END

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
def render_countdown_update(placeholder, seconds: int):
    """更新倒數計時器佔位符"""
    if seconds > 0:
        placeholder.markdown(f"""
        <div class="countdown-timer">
            ⏱️ 下次更新: {seconds} 秒
        </div>
        """, unsafe_allow_html=True)
    else:
        placeholder.markdown("""
        <div class="countdown-timer">
            ⏱️ 更新中...
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

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.caption(f"開盤: {TRADING_START.strftime('%H:%M')}")
    with col2:
        st.caption(f"原始/優化: {SIGNAL_WINDOW_START.strftime('%H:%M')}-{SIGNAL_WINDOW_END.strftime('%H:%M')}")
    with col3:
        st.caption(f"盤中動態: {INTRADAY_WINDOW_START.strftime('%H:%M')}-{INTRADAY_WINDOW_END.strftime('%H:%M')}")
    with col4:
        st.caption(f"收盤: {TRADING_END.strftime('%H:%M')}")

def render_dual_strategy_status(result: Dict, prev_scores: Dict):
    """渲染雙策略狀態"""
    # 取得分析時間（顯示於訊號盒中，避免用戶誤判訊號時效性）
    analysis_time_str = result.get('analysis_time', '')

    # 檢查是否在訊號保存窗口內（09:00-09:30）
    in_window = result.get('dual_strategy_in_window', True)

    # 根據當前時間決定窗口狀態訊息
    now = get_taiwan_now()
    current_time = now.time()
    if current_time < SIGNAL_WINDOW_START:
        window_status_msg = f"⏰ 訊號窗口 {SIGNAL_WINDOW_START.strftime('%H:%M')} 開始"
    elif current_time > SIGNAL_WINDOW_END:
        window_status_msg = "✅ 今日訊號窗口已結束"
    else:
        window_status_msg = ""

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

        # 非窗口時間：不顯示訊號方向，僅顯示窗口狀態
        if not in_window:
            st.markdown(f"""
            <div class="signal-box signal-none">
                <h2>{window_status_msg}</h2>
                <p style="font-size:14px;color:#666;">訊號窗口: {SIGNAL_WINDOW_START.strftime('%H:%M')}-{SIGNAL_WINDOW_END.strftime('%H:%M')}</p>
                <p style="font-size:12px;opacity:0.7;">分析時間: {analysis_time_str}</p>
            </div>
            """, unsafe_allow_html=True)
        elif matched:
            st.markdown(f"""
            <div class="signal-box signal-{'call' if direction == 'CALL' else 'put'}">
                <h2>{'🟢 CALL' if direction == 'CALL' else '🔴 PUT'}</h2>
                <p>分數: {score} {change_icon} ({score_change:+d})</p>
                <p>勝率: {original.get('win_rate', 0):.1%}</p>
                <p>樣本: {original.get('samples', 0)} 筆</p>
                <p style="font-size:12px;opacity:0.7;">分析時間: {analysis_time_str}</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="signal-box signal-none">
                <h2>⚪ 無訊號</h2>
                <p>分數: {score} {change_icon} ({score_change:+d})</p>
                <p style="font-size:12px;opacity:0.7;">分析時間: {analysis_time_str}</p>
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

        # 非窗口時間：不顯示訊號方向，僅顯示窗口狀態
        if not in_window:
            st.markdown(f"""
            <div class="signal-box signal-none">
                <h2>{window_status_msg}</h2>
                <p style="font-size:14px;color:#666;">訊號窗口: {SIGNAL_WINDOW_START.strftime('%H:%M')}-{SIGNAL_WINDOW_END.strftime('%H:%M')}</p>
                <p style="font-size:12px;opacity:0.7;">分析時間: {analysis_time_str}</p>
            </div>
            """, unsafe_allow_html=True)
        elif matched:
            st.markdown(f"""
            <div class="signal-box signal-{'call' if direction == 'CALL' else 'put'}">
                <h2>{'🟢 CALL' if direction == 'CALL' else '🔴 PUT'}</h2>
                <p>分數: {score} {change_icon} ({score_change:+d})</p>
                <p>勝率: {optimized.get('win_rate', 0):.1%}</p>
                <p>樣本: {optimized.get('samples', 0)} 筆</p>
                <p style="font-size:12px;opacity:0.7;">分析時間: {analysis_time_str}</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="signal-box signal-none">
                <h2>⚪ 無訊號</h2>
                <p>分數: {score} {change_icon} ({score_change:+d})</p>
                <p style="font-size:12px;opacity:0.7;">分析時間: {analysis_time_str}</p>
            </div>
            """, unsafe_allow_html=True)

            # 顯示不符合原因
            if optimized.get('unmatch_reasons'):
                with st.expander("查看不符合原因"):
                    for reason in optimized['unmatch_reasons']:
                        st.write(f"- {reason}")

def render_intraday_status(result: Dict, prev_scores: Dict):
    """渲染盤中動態引擎狀態"""
    intraday = result.get('intraday')
    if intraday is None:
        return

    st.subheader("🟡 盤中動態引擎（第三引擎）")

    # 取得分析時間
    analysis_time_str = result.get('analysis_time', '')

    # 檢查是否在訊號保存窗口內（09:00-13:25）
    in_window = result.get('intraday_in_window', True)
    window_warning = "" if in_window else '<p style="font-size:11px;color:#ff9800;font-weight:bold;">⚠️ 窗口外（僅供參考，不保存）</p>'

    has_signal = intraday.get('has_signal', False)
    best_score = intraday.get('best_score', 0)
    best_direction = intraday.get('best_direction')
    best_entry_time = intraday.get('best_entry_time')
    signals = intraday.get('signals', [])

    # 統計所有匹配的訊號數量
    matched_count = sum(1 for s in signals if s.get('matched') and s.get('direction'))

    # 計算分數變化
    score_change = best_score - prev_scores.get('intraday', 0)
    change_icon = "↗️" if score_change > 0 else ("↘️" if score_change < 0 else "→")

    # 最佳訊號摘要
    if has_signal and best_direction:
        css_class = f"signal-intraday-{'call' if best_direction == 'CALL' else 'put'}"
        dir_icon = '🟢 CALL' if best_direction == 'CALL' else '🔴 PUT'
        matched_info = f" | 共 {matched_count} 個窗口匹配" if matched_count > 1 else ""
        st.markdown(f"""
        <div class="signal-box {css_class}">
            <h2>🟡 盤中動態 — {dir_icon}</h2>
            <p>最佳進場時間: {best_entry_time} | 分數: {best_score} {change_icon} ({score_change:+d}){matched_info}</p>
            <p style="font-size:12px;opacity:0.7;">分析時間: {analysis_time_str}</p>
            {window_warning}
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="signal-box signal-intraday-none">
            <h2>⚪ 盤中無訊號</h2>
            <p>最高分數: {best_score} {change_icon} ({score_change:+d})</p>
            <p style="font-size:12px;opacity:0.7;">分析時間: {analysis_time_str}</p>
            {window_warning}
        </div>
        """, unsafe_allow_html=True)

    # 各時間窗口明細
    if signals:
        with st.expander(f"查看各時間窗口明細（{len(signals)} 個窗口）", expanded=has_signal):
            for sig in signals:
                entry_time = sig.get('entry_time', '')
                matched = sig.get('matched', False)
                direction = sig.get('direction')
                score = sig.get('score', 0)
                win_rate = sig.get('win_rate', 0)
                samples = sig.get('samples', 0)
                morning_range = sig.get('morning_range', 0)
                vwap_distance = sig.get('vwap_distance', 0)
                trend_points = sig.get('trend_points', 0)
                reasons = sig.get('signal_reasons', [])

                if matched and direction:
                    dir_icon = '🟢' if direction == 'CALL' else '🔴'
                    st.markdown(f"""
                    <div class="intraday-detail">
                        <strong>{entry_time}</strong> {dir_icon} {direction}
                        — 分數: {score} | 勝率: {win_rate:.1%} | 樣本: {samples}
                        <br>振幅: {morning_range:.0f}點 | VWAP距離: {vwap_distance:.0f}點 | 趨勢: {trend_points:+.0f}點
                    </div>
                    """, unsafe_allow_html=True)
                    if reasons:
                        st.caption(f"  訊號原因: {' / '.join(reasons)}")
                else:
                    st.markdown(f"""
                    <div class="intraday-detail" style="opacity: 0.5;">
                        <strong>{entry_time}</strong> ⚪ 未觸發 — 分數: {score}
                        <br>振幅: {morning_range:.0f}點 | VWAP距離: {vwap_distance:.0f}點 | 趨勢: {trend_points:+.0f}點
                    </div>
                    """, unsafe_allow_html=True)


def render_treasury_yield(market_data: Optional[Dict] = None):
    """渲染美國 10 年期公債殖利率（獨立區塊，不依賴分析結果）"""
    # 優先從分析結果的 market_data 取得
    us10y = None
    treasury_info = {}

    if market_data:
        us10y = market_data.get('us10y_yield')
        if us10y is not None:
            treasury_info = {
                'change': market_data.get('us10y_change', 0),
                'change_pct': market_data.get('us10y_change_pct', 0),
                'source': market_data.get('us10y_source', 'N/A'),
                'timestamp': market_data.get('us10y_timestamp', ''),
            }

    # 如果分析結果沒有，單獨呼叫 API
    if us10y is None:
        try:
            treasury_data = api_client.get_treasury_yield()
            if treasury_data and treasury_data.get('success'):
                us10y = treasury_data.get('yield_pct')
                treasury_info = {
                    'change': treasury_data.get('change', 0),
                    'change_pct': treasury_data.get('change_pct', 0),
                    'source': treasury_data.get('source', 'N/A'),
                    'timestamp': treasury_data.get('timestamp', ''),
                }
        except Exception:
            pass

    if us10y is None:
        st.caption("🇺🇸 美債10Y 殖利率：暫無數據")
        return

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        change = treasury_info.get('change', 0)
        change_pct = treasury_info.get('change_pct', 0)
        delta_str = f"{change:+.3f} ({change_pct:+.2f}%)" if change else None
        st.metric(
            "🇺🇸 美債10Y",
            f"{us10y:.3f}%",
            delta=delta_str,
            delta_color="inverse"
        )
    with col2:
        source = treasury_info.get('source', 'N/A')
        source_label = "Yahoo即時" if source == "yahoo" else "FRED日線" if source == "fred" else source
        st.caption(f"來源: {source_label}")
        # 殖利率等級判斷
        if us10y < 4.0:
            st.success(f"低利率環境 ({us10y:.2f}%)")
        elif us10y < 4.5:
            st.info(f"正常利率 ({us10y:.2f}%)")
        elif us10y < 5.0:
            st.warning(f"偏高利率 ({us10y:.2f}%)")
        else:
            st.error(f"高利率警戒 ({us10y:.2f}%)")
    with col3:
        # 顯示最後抓取時間
        timestamp = treasury_info.get('timestamp', '')
        if timestamp:
            st.caption(f"🕐 最後更新: {timestamp}")
        else:
            st.caption("🕐 最後更新: N/A")
    with col4:
        st.empty()


def render_credit_risk_panel():
    """渲染全球信用風險預警面板 v3.0 — 五級燈號 + XSS 防護 + 快取 fallback"""
    _esc = html_module.escape

    # ==================== 取得數據（區分錯誤類型）====================
    data = None
    error_type = None
    try:
        data = api_client.get_credit_risk()
    except requests.exceptions.Timeout:
        error_type = "timeout"
    except requests.exceptions.ConnectionError:
        error_type = "connection"
    except Exception as e:
        error_type = "unknown"
        print(f"[credit-risk] exception: {type(e).__name__}: {e}")

    # 快取 fallback
    if data and data.get('success'):
        st.session_state['credit_risk_cache'] = data
    elif st.session_state.get('credit_risk_cache'):
        data = st.session_state['credit_risk_cache']
        error_type = "cached"

    if not data or not data.get('success'):
        if error_type == "timeout":
            st.caption("⏳ 信用風險預警：API 回應超時，稍後重試...")
        elif error_type == "connection":
            st.caption("🔌 信用風險預警：連線失敗，請檢查網路...")
        else:
            st.caption("📡 信用風險預警：資料載入中...")
        return

    scorecard = data.get('scorecard', {})
    indicators = data.get('indicators', {})
    news = data.get('news', [])
    timestamp = data.get('timestamp', '')

    overall_status = scorecard.get('overall_status', 'green')
    overall_label = scorecard.get('overall_label', '🟢 綠燈')
    overall_msg = scorecard.get('overall_message', '')

    # ==================== 概覽圓點 ====================
    dot_order = ["treasury", "banks", "loans", "bdc", "cockroach", "tsm_adr"]
    dot_labels = {"treasury": "美債", "banks": "銀行", "loans": "貸款", "bdc": "BDC", "cockroach": "蟑螂", "tsm_adr": "ADR"}
    dots_html = ""
    for dk in dot_order:
        ds = indicators.get(dk, {}).get('status', 'pending')
        dl = dot_labels.get(dk, dk)
        dots_html += f'<span class="cr-summary-dot {ds}" title="{dl}"></span>'

    cached_tag = ' <span style="font-size:10px;opacity:0.7;">(快取)</span>' if error_type == "cached" else ""

    # ==================== 頂部警戒橫幅 ====================
    st.markdown(f"""
    <div class="cr-header {overall_status}">
        <div style="font-size: 18px;">🚨 私募信貸危機監控 — 阿水週報</div>
        <div style="font-size: 15px; margin-top: 4px;">
            {_esc(overall_label)} — {_esc(overall_msg)}
        </div>
        <div class="cr-summary-bar">{dots_html}</div>
        <div style="font-size: 12px; opacity: 0.85;">
            ⑤PIK ⑥13F 待季報 | 🕐 {_esc(timestamp)}{cached_tag}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ==================== 五大活躍指標（明確分欄）====================
    left_keys = [
        ("treasury", "① 美債10Y殖利率"),
        ("banks",    "② KBW銀行指數"),
        ("loans",    "④ 軟體貸款壓力"),
    ]
    right_keys = [
        ("bdc",       "③ BDC壓力指標"),
        ("cockroach", "⑦ 信貸蟑螂追蹤"),
        ("tsm_adr",   "⑧ 台積電ADR溢價"),
    ]

    col_left, col_right = st.columns(2)

    for col, keys in [(col_left, left_keys), (col_right, right_keys)]:
        with col:
            for key, title in keys:
                ind = indicators.get(key, {})
                status = ind.get('status', 'unknown')
                label = ind.get('label', '—')
                triggers = ind.get('triggers', [])
                metrics = ind.get('metrics', {})

                tree_html = _build_tree_lines_html(key, metrics)

                trigger_html = ""
                if triggers:
                    trigger_text = " | ".join(_esc(str(t)) for t in triggers[:3])
                    trigger_html = f'<div class="cr-trigger">▸ {trigger_text}</div>'

                badge_html = f'<span class="cr-badge {status}">{_esc(label)}</span>'

                card_html = f"""
                <div class="cr-card {status}">
                    <div class="cr-title"><span>{title}</span>{badge_html}</div>
                    <div class="cr-tree">{tree_html}</div>
                    {trigger_html}
                </div>
                """
                st.markdown(card_html, unsafe_allow_html=True)

    # ==================== ⑤⑥ 待審指標合併為一行 ====================
    pik_label = indicators.get('pik', {}).get('label', '待季報')
    f13_label = indicators.get('13f', {}).get('label', '待季報')
    st.caption(f"⑤ PIK比率：{pik_label} | ⑥ 13F持倉：{f13_label}")

    # ==================== 信用利差獨立顯示 ====================
    loan_m = indicators.get('loans', {}).get('metrics', {})
    hy_bps = loan_m.get('hy_oas_bps')
    ccc_bps = loan_m.get('ccc_oas_bps')
    if hy_bps is not None or ccc_bps is not None:
        spread_parts = []
        if hy_bps is not None:
            spread_parts.append(f"HY OAS: {hy_bps:.0f} bps")
        if ccc_bps is not None:
            spread_parts.append(f"CCC OAS: {ccc_bps:.0f} bps")
        st.caption(f"📊 信用利差 — {' | '.join(spread_parts)}")

    # ==================== 蟑螂事件明細（近30天展開）====================
    cockroach_metrics = indicators.get('cockroach', {}).get('metrics', {})
    events = cockroach_metrics.get('events', [])
    if events:
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        recent = [e for e in events if e.get('date', '') >= cutoff]
        older = [e for e in events if e.get('date', '') < cutoff]

        def _render_event_html(ev_list):
            parts = []
            for ev in ev_list:
                type_icon = {"A": "🔴", "B": "🟠", "C": "🟡"}.get(ev.get("type", "C"), "⚪")
                parts.append(f'<div class="cr-news">'
                    f'{type_icon} [{_esc(str(ev.get("date","")))}] '
                    f'<b>{_esc(str(ev.get("entity","")))}</b>'
                    f'（{_esc(str(ev.get("country","")))}）'
                    f'— Type {_esc(str(ev.get("type","")))}（權重{ev.get("weight",0)}）'
                    f'<div class="cr-news-meta">{_esc(str(ev.get("desc","")))}</div>'
                    f'</div>')
            return "\n".join(parts)

        if recent:
            st.markdown(f"**🪳 近30天事件（{len(recent)} 起）**")
            st.markdown(_render_event_html(recent), unsafe_allow_html=True)
        if older:
            with st.expander(f"🪳 較早事件（{len(older)} 起，30天前）", expanded=False):
                st.markdown(_render_event_html(older), unsafe_allow_html=True)

    # ==================== 信貸風險新聞（合併 markdown）====================
    if news:
        with st.expander(f"📰 信貸風險新聞（{len(news)} 則）", expanded=False):
            news_parts = []
            for item in news:
                link = _esc(str(item.get('link', '')))
                title_text = _esc(str(item.get('title', '')))
                source = _esc(str(item.get('source', '')))
                published = _esc(str(item.get('published', '')))
                news_parts.append(
                    f'<div class="cr-news">'
                    f'<a href="{link}" target="_blank">{title_text}</a>'
                    f'<div class="cr-news-meta">{source} · {published}</div>'
                    f'</div>')
            st.markdown("\n".join(news_parts), unsafe_allow_html=True)


def _fmt_val(val, fmt="+.1f", suffix="%", invert=False):
    """格式化數值並加上漲跌顏色 span。invert=True 表示上升為負面（如殖利率上升）"""
    if val is None:
        return '<span class="val-neutral">—</span>'
    s = f"{val:{fmt}}{suffix}"
    if invert:
        cls = "val-dn" if val > 0 else "val-up" if val < 0 else "val-neutral"
    else:
        cls = "val-up" if val > 0 else "val-dn" if val < 0 else "val-neutral"
    arrow = "↑" if val > 0 else "↓" if val < 0 else ""
    return f'<span class="{cls}">{arrow}{s}</span>'


def _ticker_span(ticker, change_pct):
    """建構 ticker badge HTML"""
    if change_pct is None:
        return f'<span class="cr-ticker flat">{ticker}:—</span>'
    cls = "up" if change_pct > 0 else "down" if change_pct < 0 else "flat"
    return f'<span class="cr-ticker {cls}">{ticker}:{change_pct:+.1f}%</span>'


def _tree_auto(items):
    """自動為樹狀行加上 ├─/└─ 前綴"""
    if not items:
        return ""
    result = []
    for i, item in enumerate(items):
        prefix = "└─" if i == len(items) - 1 else "├─"
        result.append(f"{prefix} {item}")
    return "\n".join(result)


def _build_tree_lines_html(key: str, m: Dict) -> str:
    """根據指標類型建構 HTML 樹狀顯示（含漲跌顏色+箭頭）"""
    items = []

    if key == "treasury":
        y10 = m.get("yield_10y")
        if y10 is not None:
            items.append(f"10Y殖利率：{y10:.2f}%")
        cpi = m.get("core_cpi_yoy")
        ry = m.get("real_yield")
        if cpi is not None and ry is not None:
            items.append(f"核心CPI：{cpi:.1f}% → 實質利率：{_fmt_val(ry, '+.2f')}")
        sp = m.get("spread_2s10s")
        if sp is not None:
            desc = "正斜率" if sp > 0.3 else "趨平" if sp > 0 else "倒掛"
            items.append(f"2s10s利差：{_fmt_val(sp, '+.2f')}（{desc}）")
        chg = m.get("yield_change_30d")
        if chg is not None:
            items.append(f"30日變動：{_fmt_val(chg, '+.2f', invert=True)}")

    elif key == "banks":
        p = m.get("bkx_price")
        if p:
            items.append(f"BKX：{p:.1f}")
        c20 = m.get("bkx_change_20d")
        if c20 is not None:
            items.append(f"20日漲跌：{_fmt_val(c20)}")
        vs = m.get("bkx_vs_sp500_20d")
        if vs is not None:
            tag = "落後" if vs < 0 else "領先"
            items.append(f"vs S&amp;P500：{_fmt_val(vs)}（{tag}大盤）")
        h52 = m.get("bkx_from_52w_high")
        if h52 is not None:
            items.append(f"距52週高點：{_fmt_val(h52)}")
        exposed = m.get("exposed_banks", {})
        if exposed:
            parts = [_ticker_span(t, d.get("change_5d_pct")) for t, d in exposed.items()]
            items.append(f"曝險5日：{' '.join(parts)}")

    elif key == "bdc":
        bp = m.get("bizd_price")
        c20 = m.get("bizd_change_20d")
        h52 = m.get("bizd_from_52w_high")
        if bp:
            parts = [f"BIZD ${bp:.2f}"]
            if c20 is not None:
                parts.append(f"20日{_fmt_val(c20)}")
            if h52 is not None:
                parts.append(f"52高{_fmt_val(h52)}")
            items.append(" | ".join(parts))
        avg = m.get("pe_avg_20d")
        if avg is not None:
            items.append(f"PE巨頭20日平均：{_fmt_val(avg)}")
        pe_stocks = m.get("pe_stocks", {})
        if pe_stocks:
            parts = [_ticker_span(t, d.get("change_1d_pct")) for t, d in pe_stocks.items()]
            items.append(f"  {' '.join(parts)}")
        rc = m.get("redemption_count", 0)
        ac = m.get("activist_count", 0)
        items.append(f"贖回事件：{rc}起 | 激進投資者：{ac}起")

    elif key == "loans":
        igv_p = m.get("igv_price")
        igv_ytd = m.get("igv_change_ytd")
        igv_20d = m.get("igv_change_20d")
        if igv_p:
            parts = [f"IGV ${igv_p:.2f}"]
            if igv_ytd is not None:
                parts.append(f"YTD{_fmt_val(igv_ytd)}")
            if igv_20d is not None:
                parts.append(f"20日{_fmt_val(igv_20d)}")
            items.append(" | ".join(parts))
        igv_52 = m.get("igv_from_52w_high")
        if igv_52 is not None:
            items.append(f"IGV距52週高點：{_fmt_val(igv_52)}")
        bkln = m.get("bkln_price")
        if bkln:
            items.append(f"BKLN：${bkln:.2f}")
        hy = m.get("hy_oas_bps")
        ccc = m.get("ccc_oas_bps")
        if hy is not None or ccc is not None:
            parts = []
            if hy is not None:
                parts.append(f"HY:{hy:.0f}bps")
            if ccc is not None:
                parts.append(f"CCC:{ccc:.0f}bps")
            items.append(f"信用利差：{' | '.join(parts)}")

    elif key == "cockroach":
        cnt = m.get("cockroach_count", 0)
        sc = m.get("cockroach_score", 0)
        items.append(f"180天事件：{cnt}起（加權分數：{sc}）")
        r30 = m.get("recent_30d_count", 0)
        items.append(f"近30天：{r30}起")
        geo = m.get("geography_spread", 0)
        countries = m.get("countries", [])
        items.append(f"地理分布：{geo}個（{', '.join(countries)}）")

    elif key == "tsm_adr":
        prem = m.get("premium_pct")
        hi = m.get("premium_high_90d")
        lo = m.get("premium_low_90d")
        if prem is not None:
            rng = f"（90天：{lo:.1f}% ~ {hi:.1f}%）" if (hi is not None and lo is not None) else ""
            items.append(f"ADR 溢價：{_fmt_val(prem, '+.1f', '%', invert=True)} {rng}")
        tsm_p = m.get("tsm_adr_price")
        implied = m.get("adr_implied_twd")
        fx = m.get("usdtwd_rate")
        if tsm_p is not None and implied is not None and fx is not None:
            items.append(f"TSM ${tsm_p:.2f} → NT${implied:,.0f}（÷5×{fx:.2f}）")
        chg30 = m.get("premium_change_30d")
        if chg30 is not None:
            items.append(f"30日溢價變動：{_fmt_val(chg30, '+.1f', 'pp', invert=True)}")
        chg60 = m.get("premium_change_60d")
        if chg60 is not None:
            items.append(f"60日溢價變動：{_fmt_val(chg60, '+.1f', 'pp', invert=True)}")
        adr_chg = m.get("tsm_adr_change_20d")
        tw_chg = m.get("tw_2330_change_20d")
        div = m.get("divergence_ratio")
        if adr_chg is not None and tw_chg is not None:
            div_str = f"（{div:.1f}倍）" if div is not None else ""
            items.append(f"跌幅分歧：ADR {_fmt_val(adr_chg)} vs 台股 {_fmt_val(tw_chg)} {div_str}")

    elif key == "pik":
        items.append("數據源：BDC季報（Q1數據4-5月公布）")

    elif key == "13f":
        items.append("數據源：SEC EDGAR（截止日2026-05-15）")

    return _tree_auto(items)


def render_market_data(market_data: Dict):
    """渲染市場數據"""
    st.subheader("📈 市場數據")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("當前價格", f"{market_data.get('current_price', 0):.0f}")
    with col2:
        st.metric("VWAP", f"{market_data.get('vwap', 0):.0f}")
    with col3:
        st.metric("日線 MA20", f"{market_data.get('ma20', 0):.0f}")
    with col4:
        st.metric("日線 MA5", f"{market_data.get('ma5', 0):.0f}")

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
                    if strategy == "ORIGINAL":
                        st.write("🔵 原始V7")
                    elif strategy == "OPTIMIZED":
                        st.write("🟢 優化策略")
                    elif strategy == "INTRADAY":
                        st.write("🟡 盤中動態")
                    else:
                        st.write(strategy)
                with col3:
                    direction = signal.get('direction', '')
                    if direction == 'CALL':
                        st.write("🟢 CALL")
                    else:
                        st.write("🔴 PUT")
                with col4:
                    score = signal.get('score', 0)
                    previous_score = signal.get('previous_score')
                    win_rate = signal.get('win_rate', 0)
                    # 如果有上次分數，顯示分數變化
                    if previous_score is not None and previous_score != score:
                        score_change = score - previous_score
                        change_icon = "↗️" if score_change > 0 else "↘️"
                        st.write(f"分數: {score} {change_icon} (上次: {previous_score}) | 勝率: {win_rate:.1%}")
                    else:
                        st.write(f"分數: {score} | 勝率: {win_rate:.1%}")
        else:
            st.info("今日尚無訊號記錄")

    except Exception as e:
        st.error(f"載入訊號歷史失敗：{str(e)}")
        import traceback
        st.code(traceback.format_exc())

def render_vix_chart():
    """渲染台指 VIX 波動率指數圖表區塊（Plotly 互動圖表）"""
    st.subheader("📊 台指 VIX 波動率指數")

    try:
        # 防禦性檢查：確保 API 客戶端方法存在（Streamlit Cloud 快取可能導致缺失）
        if not hasattr(api_client, 'get_vix_today'):
            st.info("📭 VIX 功能正在部署中，請重新整理頁面")
            return

        vix_data = api_client.get_vix_today()

        if vix_data and vix_data.get('success'):
            latest = vix_data.get('latest')
            data_points = vix_data.get('data', [])

            # 顯示最新 VIX 值和日內統計
            if latest:
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    change = latest.get('change', 0)
                    change_pct = latest.get('change_pct', 0)
                    st.metric(
                        "VIX 當前值",
                        f"{latest['vix_value']:.2f}",
                        delta=f"{change:+.2f} ({change_pct:+.1f}%)"
                    )
                with col2:
                    st.metric("開盤", f"{latest.get('open', 0):.2f}")
                with col3:
                    st.metric("日內高", f"{latest.get('high', 0):.2f}")
                with col4:
                    st.metric("日內低", f"{latest.get('low', 0):.2f}")

                # VIX 等級判斷
                vix_val = latest['vix_value']
                if vix_val < 15:
                    st.success(f"🟢 低波動（VIX {vix_val:.2f}）— 市場平靜")
                elif vix_val < 20:
                    st.info(f"🔵 正常波動（VIX {vix_val:.2f}）— 市場穩定")
                elif vix_val < 25:
                    st.warning(f"🟡 中等波動（VIX {vix_val:.2f}）— 需要關注")
                elif vix_val < 30:
                    st.warning(f"🟠 高波動（VIX {vix_val:.2f}）— 市場緊張")
                else:
                    st.error(f"🔴 極高波動（VIX {vix_val:.2f}）— 市場恐慌")

            # 繪製 Plotly 日內走勢圖
            if data_points and len(data_points) > 1:
                import pandas as pd
                df = pd.DataFrame(data_points)

                times = df['time'].tolist()
                values = df['vix_value'].tolist()

                # 找出高低點
                max_val = max(values)
                min_val = min(values)
                max_idx = values.index(max_val)
                min_idx = values.index(min_val)

                fig = go.Figure()

                # VIX 等級背景色帶
                vix_levels = [
                    (0, 15, 'rgba(76, 175, 80, 0.08)', '低波動'),
                    (15, 20, 'rgba(33, 150, 243, 0.08)', '正常'),
                    (20, 25, 'rgba(255, 235, 59, 0.10)', '中等'),
                    (25, 30, 'rgba(255, 152, 0, 0.10)', '高波動'),
                    (30, 50, 'rgba(244, 67, 54, 0.10)', '極高'),
                ]
                y_min_chart = max(0, min_val - 2)
                y_max_chart = max_val + 2
                for low, high, color, label in vix_levels:
                    if high > y_min_chart and low < y_max_chart:
                        fig.add_hrect(
                            y0=max(low, y_min_chart), y1=min(high, y_max_chart),
                            fillcolor=color, line_width=0,
                            annotation_text=label if low >= y_min_chart else "",
                            annotation_position="top left",
                            annotation_font_size=10,
                            annotation_font_color="rgba(150,150,150,0.7)",
                        )

                # 漸層面積 + 線條
                fig.add_trace(go.Scatter(
                    x=times, y=values,
                    mode='lines',
                    name='VIX',
                    line=dict(color='#ff6b6b', width=2.5),
                    fill='tozeroy',
                    fillcolor='rgba(255, 107, 107, 0.15)',
                    hovertemplate='時間: %{x}<br>VIX: %{y:.2f}<extra></extra>',
                ))

                # 當前值水平線
                if latest:
                    current_val = latest['vix_value']
                    fig.add_hline(
                        y=current_val,
                        line_dash="dot",
                        line_color="rgba(255, 107, 107, 0.5)",
                        line_width=1,
                        annotation_text=f"當前 {current_val:.2f}",
                        annotation_position="top right",
                        annotation_font_size=11,
                        annotation_font_color="#ff6b6b",
                    )

                # 高點標記
                fig.add_annotation(
                    x=times[max_idx], y=max_val,
                    text=f"高 {max_val:.2f}",
                    showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1.5,
                    arrowcolor="#f44336",
                    font=dict(size=11, color="#f44336"),
                    ax=0, ay=-30,
                )
                # 低點標記
                fig.add_annotation(
                    x=times[min_idx], y=min_val,
                    text=f"低 {min_val:.2f}",
                    showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1.5,
                    arrowcolor="#4caf50",
                    font=dict(size=11, color="#4caf50"),
                    ax=0, ay=30,
                )

                # 佈局
                fig.update_layout(
                    height=350,
                    margin=dict(l=0, r=0, t=10, b=0),
                    xaxis=dict(
                        title="",
                        showgrid=True,
                        gridcolor='rgba(128,128,128,0.1)',
                        tickangle=-45,
                    ),
                    yaxis=dict(
                        title="VIX",
                        showgrid=True,
                        gridcolor='rgba(128,128,128,0.1)',
                        range=[y_min_chart, y_max_chart],
                    ),
                    plot_bgcolor='rgba(0,0,0,0)',
                    paper_bgcolor='rgba(0,0,0,0)',
                    showlegend=False,
                    hovermode='x unified',
                )

                st.plotly_chart(fig, use_container_width=True)
                st.caption(f"今日 VIX 數據點: {len(data_points)} 筆 | 更新時間: {latest.get('time', '') if latest else ''}")
            elif latest:
                st.info(f"📌 目前僅有 1 筆數據（VIX: {latest['vix_value']:.2f}），圖表將在累積更多數據後顯示")
            else:
                st.info("📭 今日尚無 VIX 數據（非交易時段或數據尚未收集）")
        else:
            st.info("📭 VIX 數據暫時無法取得（服務初始化中或非交易時段）")

    except Exception as e:
        st.warning(f"VIX 數據載入失敗: {str(e)}")


# ==================== V7 監控頁面 ====================
def v7_monitor_page():
    """V7 即時監控主頁面（需要認證）"""
    # 標題
    st.title("📡 V7 即時監控系統")

    # 身份確認提示（防止身份混淆）
    user_email = st.session_state.get('user_email', '')
    username = st.session_state.get('username', '')
    if user_email:
        display_name = username if username else user_email.split('@')[0]
        st.caption(f"👤 歡迎回來，**{display_name}**")

    # 側邊欄顯示用戶資訊
    render_user_info_sidebar(API_BASE_URL)

    # 獲取當前時間
    now = get_taiwan_now()

    # 顯示當前時間和交易狀態
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info(f"🕐 當前時間: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    with col2:
        if is_trading_hours(now):
            if is_signal_window(now):
                st.success("✅ 原始/優化窗口開啟中")
            else:
                st.info("📊 交易時段")
        else:
            st.warning("💤 非交易時段")
    with col3:
        if is_intraday_signal_window(now):
            st.success("🟡 盤中動態窗口開啟中")
        elif is_trading_hours(now):
            st.info("⏳ 盤中動態窗口已結束")
        else:
            st.warning("💤 非交易時段")

    # 自動刷新開關
    auto_refresh = st.checkbox(
        "啟用自動刷新（15秒）",
        value=st.session_state.auto_refresh_enabled,
        key="auto_refresh_toggle"
    )
    st.session_state.auto_refresh_enabled = auto_refresh

    st.markdown("---")

    # 渲染時間軸
    render_timeline(now)

    # 倒數計時器佔位符（由底部循環即時更新）
    countdown_placeholder = st.empty()

    st.markdown("---")

    # 手動刷新按鈕
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🔄 立即刷新", type="primary", use_container_width=True):
            st.session_state.last_refresh = now
            st.rerun()

    st.markdown("---")

    # VIX 波動率指數圖表（在雙策略監控區塊上方）
    render_vix_chart()

    st.markdown("---")

    # 準備 API 請求參數（使用當前台灣時間）
    analysis_date = now.strftime('%Y-%m-%d')
    analysis_time = now.strftime('%H:%M')

    # 調用後端 API 獲取策略分析
    with st.spinner("🔄 正在分析策略..."):
        result = api_client.analyze_v7(analysis_date, analysis_time)

    if result and result.get('success'):
        # 渲染雙策略狀態
        render_dual_strategy_status(result, st.session_state.prev_scores)

        # 更新分數記錄
        st.session_state.prev_scores = {
            'original': result.get('original', {}).get('score', 0),
            'optimized': result.get('optimized', {}).get('score', 0),
            'intraday': result.get('intraday', {}).get('best_score', 0) if result.get('intraday') else 0,
        }

        st.markdown("---")

        # 渲染盤中動態引擎狀態
        render_intraday_status(result, st.session_state.prev_scores)

        st.markdown("---")

        # 渲染市場數據
        if 'market_data' in result:
            render_market_data(result['market_data'])
    else:
        if result is not None:
            st.error(f"❌ 分析失敗：{result.get('error', '未知錯誤')}")
        # result is None 時，analyze_v7() 已經顯示了具體錯誤訊息

    st.markdown("---")

    # 美債殖利率（始終顯示，不依賴分析結果）
    analysis_market_data = result.get('market_data') if (result and result.get('success')) else None
    render_treasury_yield(analysis_market_data)

    st.markdown("---")

    # 全球信用風險預警面板（始終顯示，不依賴分析結果）
    render_credit_risk_panel()

    st.markdown("---")

    # 訊號歷史（無論分析是否成功都顯示）
    render_signal_history()

    st.markdown("---")

    # 風險提示
    st.caption("⚠️ 本系統僅供教育和研究用途，不構成投資建議。投資有風險，請謹慎決策。")

    # 自動刷新倒數循環（放在所有內容渲染之後）
    # 使用 st.empty() + sleep 逐秒更新倒數，到 0 時觸發 rerun
    if auto_refresh and is_trading_hours(now):
        for i in range(REFRESH_INTERVAL, 0, -1):
            render_countdown_update(countdown_placeholder, i)
            pytime.sleep(1)
        render_countdown_update(countdown_placeholder, 0)
        st.rerun()

# ==================== 主程式 ====================
def main():
    """
    主程式入口

    認證流程（v3.0）：
    1. 初始化 session state
    2. 嘗試恢復登入狀態（從 URL 參數 + Cookie 雙層讀取）
    3. 注入頁面可見性監聽器
    4. 顯示對應頁面

    v3.0 改進（2026-02-05）：
    - 使用 st.query_params 作為主要存儲（不受 iframe 限制）
    - Cookie 作為備援存儲
    - 移除 localStorage 依賴（在 Streamlit Cloud iframe 中不可靠）
    - 最多 3 次重試（有上限保護，避免無限循環）
    - 解決「網站轉向太多次」問題
    """
    init_session()

    # 嘗試恢復登入狀態（v4.4: 支援 Cookie 組件非同步載入）
    try_restore_session(API_BASE_URL)

    # 檢查登入狀態
    if not is_authenticated():
        if not st.session_state.get('auth_restore_done'):
            # Cookie 組件尚未從瀏覽器載入，顯示載入畫面
            # 組件載入完成後會自動觸發 rerun
            render_loading_screen()
            st.stop()
        auth_page()
    else:
        # 注入頁面可見性監聯器（在恢復完成後注入）
        inject_visibility_listener()
        v7_monitor_page()

# ==================== 主程式入口 ====================
if __name__ == "__main__":
    main()

