# 📡 V7 即時監控系統 - Public App

台指期貨選擇權策略即時監控系統

## ⚠️ 重要聲明

**本 Repository 為 PUBLIC**，僅包含前端 UI 代碼。

- ✅ 前端 UI 渲染邏輯
- ✅ JWT 認證保護
- ❌ 無策略引擎代碼
- ❌ 無業務邏輯
- ❌ 無敏感資訊

所有策略計算和業務邏輯都在後端 API 執行，前端只負責顯示結果。

## 🚀 功能特色

### 雙策略監控
- **原始 V7 策略**：40 個歷史樣本，72.5% 勝率
- **Phase3 優化策略**：23 個歷史樣本，87% 勝率

### 即時數據
- 30 秒自動刷新（交易時段）
- 8 個市場指標即時監控
- 訊號窗口：09:00-09:30

### 安全保護
- JWT 雙 Token 認證
- 未登入用戶無法訪問任何功能
- 所有 API 請求需要認證

## 📋 系統需求

- Python 3.11+
- Streamlit 1.29.0+
- 後端 API 連接

## 🔧 本地開發

### 1. 克隆 Repository

```bash
git clone https://github.com/walter888tw/v7-monitor.git
cd v7-monitor
```

### 2. 安裝依賴

```bash
pip install -r requirements.txt
```

### 3. 配置環境變數

創建 `.streamlit/secrets.toml`：

```toml
API_BASE_URL = "http://localhost:8000/api/v1"
```

### 4. 啟動應用

```bash
streamlit run app.py
```

應用將在 http://localhost:8501 啟動

## 🌐 生產環境部署

### Streamlit Cloud 部署

1. Fork 本 Repository
2. 前往 https://share.streamlit.io/
3. 創建新應用：
   - Repository: `your-username/v7-monitor`
   - Branch: `main`
   - Main file: `app.py`
   - App visibility: **Public**

4. 配置 Secrets：
```toml
API_BASE_URL = "https://your-backend-api.com/api/v1"
```

5. 部署完成！

## 🔐 安全性

### 認證機制
- 所有頁面都需要 `require_auth()` 保護
- 未登入用戶只看到登入提示
- JWT Token 存儲在 session_state

### 數據保護
- 前端不包含任何策略參數
- 所有計算在後端執行
- 用戶數據隔離（user_id 過濾）

### 搜尋引擎
- 已添加 `noindex, nofollow` meta 標籤
- 防止搜尋引擎索引

## 📊 架構說明

```
用戶瀏覽器
    ↓ (HTTPS)
V7 Public App (Streamlit Cloud)
    ↓ (HTTPS + JWT)
Backend API (Render.com)
    ↓
PostgreSQL Database
```

### 三層保護
1. **前端認證**：`require_auth()` 檢查
2. **Backend JWT**：所有 API 請求驗證
3. **資料庫權限**：user_id 過濾

## 📁 文件結構

```
v7-monitor/
├── app.py                 # 主應用入口
├── requirements.txt       # Python 依賴
├── .gitignore            # Git 忽略文件
├── README.md             # 本文件
└── utils/                # 工具模組
    ├── __init__.py
    ├── auth.py           # 認證模組
    └── api_client.py     # API 客戶端
```

## 🛠️ 技術棧

- **前端框架**：Streamlit 1.29.0+
- **HTTP 客戶端**：requests
- **認證**：PyJWT
- **數據處理**：pandas, numpy
- **技術指標**：ta (Technical Analysis Library)

## ⚠️ 風險提示

本系統僅供教育和研究用途，不構成投資建議。

- ❌ 不保證策略有效性
- ❌ 不保證歷史勝率延續
- ❌ 不承擔任何投資損失
- ✅ 請謹慎決策，風險自負

## 📞 支援

如有問題，請聯繫系統管理員。

## 📄 授權

本專案僅供授權用戶使用，未經許可不得複製或分發。

---

**版本**: 1.0  
**最後更新**: 2026-01-28  
**狀態**: ✅ 生產就緒

