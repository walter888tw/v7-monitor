# -*- coding: utf-8 -*-
"""
V7 即時監控系統 - Public App 版本
台指期貨選擇權策略即時監控

本應用為 Public App，但所有功能都需要 JWT 認證保護
"""
import streamlit as st
import os
import sys
from pathlib import Path
from datetime import datetime, time, timedelta
import time as pytime
from typing import Optional, Dict

# 添加 utils 到路徑
sys.path.insert(0, str(Path(__file__).parent))

# 導入認證和 API 客戶端
from utils.auth import require_auth, render_user_info_sidebar
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

# ==================== 認證檢查 ====================
require_auth()

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
    """計算交易時段進度百分比"""
    if not is_trading_hours(now):
        return 0.0

    current_time = now.time()
    start_seconds = TRADING_START.hour * 3600 + TRADING_START.minute * 60
    end_seconds = TRADING_END.hour * 3600 + TRADING_END.minute * 60
    current_seconds = current_time.hour * 3600 + current_time.minute * 60


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
    """渲染訊號歷史記錄"""
    st.subheader("📜 今日訊號歷史")

    try:
        # 從後端 API 獲取今日訊號記錄
        signals = api_client.get_v7_signals_today()

        if signals and len(signals) > 0:
            for signal in signals:
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

# ==================== 主函數 ====================
def main():
    """主程式"""
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

    # 調用後端 API 獲取策略分析
    try:
        with st.spinner("🔄 正在分析策略..."):
            result = api_client.post('/v7/analyze', data={})

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

# ==================== 主程式入口 ====================
if __name__ == "__main__":
    main()

