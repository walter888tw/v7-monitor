# 🚀 V7 即時監控系統 - 部署指南

## 📋 部署前準備

### ✅ 已完成項目

- ✅ 創建獨立的 Public Repository
- ✅ 所有 V7 相關文件已準備
- ✅ 無硬編碼敏感資訊
- ✅ JWT 認證保護完整
- ✅ 本地 Git 已初始化並提交

### 📁 Repository 文件結構

```
v7-monitor-public/
├── app.py                 # 主應用入口（412 行）
├── requirements.txt       # Python 依賴
├── README.md             # 專案說明
├── .gitignore            # Git 忽略規則
├── DEPLOYMENT_GUIDE.md   # 本文件
└── utils/                # 工具模組
    ├── __init__.py
    ├── auth.py           # 認證模組（129 行）
    └── api_client.py     # API 客戶端（262 行）
```

---

## 🌐 Step 1: 創建 GitHub Public Repository

### 1.1 前往 GitHub

訪問：https://github.com/new

### 1.2 填寫 Repository 資訊

```
Repository name: v7-monitor
Description: V7 即時監控系統 - 台指期貨選擇權策略分析（Public App）
Visibility: ✅ Public
```

**重要**：
- ❌ 不要勾選 "Initialize this repository with a README"
- ❌ 不要添加 .gitignore
- ❌ 不要選擇 License

### 1.3 創建 Repository

點擊 "Create repository" 按鈕

---

## 📤 Step 2: 推送代碼到 GitHub

### 2.1 添加 Remote

在 `v7-monitor-public` 目錄執行：

```bash
git remote add origin https://github.com/walter888tw/v7-monitor.git
```

### 2.2 推送代碼

```bash
git branch -M main
git push -u origin main
```

### 2.3 驗證

訪問 https://github.com/walter888tw/v7-monitor 確認文件已上傳

---

## ☁️ Step 3: 部署到 Streamlit Cloud

### 3.1 登入 Streamlit Cloud

1. 訪問：https://share.streamlit.io/
2. 使用 GitHub 帳號登入（walter888tw）
3. 授權 Streamlit 訪問 `v7-monitor` repository

### 3.2 創建新應用

點擊 "New app" 按鈕

### 3.3 配置應用

**Repository, branch, and file**:
```
Repository: walter888tw/v7-monitor
Branch: main
Main file path: app.py
```

**App URL** (可選自訂):
```
建議: v7-monitor-taiwan-futures
```

**App visibility**:
```
✅ Public
```

### 3.4 Advanced Settings

點擊 "Advanced settings" 展開：

**Python version**:
```
3.11
```

**Secrets**:
```toml
API_BASE_URL = "https://stock-strategy-backend.onrender.com/api/v1"
```

### 3.5 部署

點擊 "Deploy!" 按鈕，等待 5-10 分鐘

---

## 🔧 Step 4: 更新 Backend CORS

### 4.1 獲取 V7 URL

部署完成後，複製 Streamlit App URL，例如：
```
https://v7-monitor-taiwan-futures.streamlit.app
```

### 4.2 登入 Render Dashboard

訪問：https://dashboard.render.com

### 4.3 更新 CORS_ORIGINS

1. 選擇 `stock-strategy-backend` Service
2. 點擊 "Environment" 標籤
3. 找到 `CORS_ORIGINS` 變數，點擊 "Edit"
4. 添加 V7 URL：

```json
["https://option-zs8r5vd7neblrl5zw6vsza.streamlit.app","https://option-emk3nc7sumcnyskkt2sk5a.streamlit.app","https://v7-monitor-taiwan-futures.streamlit.app","http://localhost:8501"]
```

5. 點擊 "Save Changes"
6. 等待 Render 自動重新部署（3-5 分鐘）

---

## ✅ Step 5: 測試部署

### 5.1 未登入測試

1. 打開無痕視窗
2. 訪問 V7 URL
3. 確認看到 "⚠️ 請先登入" 訊息
4. 確認無法看到任何數據

### 5.2 已登入測試

1. 使用測試帳號登入：
   - Email: waterstock888@gmail.com
   - Password: admin123

2. 訪問 V7 URL

3. 確認功能正常：
   - ✅ 雙策略狀態顯示
   - ✅ 市場數據更新
   - ✅ 訊號歷史記錄
   - ✅ 自動刷新功能
   - ✅ 倒數計時器

### 5.3 API 測試

```bash
# 測試無 token 訪問（應返回 401）
curl -X POST https://stock-strategy-backend.onrender.com/api/v1/v7/analyze \
  -H "Content-Type: application/json" -d '{}'
```

預期結果：
```json
{"detail": "Not authenticated"}
```

---

## 📝 Step 6: 更新文檔

### 6.1 記錄 V7 URL

在原始 private repo (`walter888tw/option`) 中更新：

**README.md**:
```markdown
## 應用 URL

- V5 用戶前端: https://option-zs8r5vd7neblrl5zw6vsza.streamlit.app
- V5 管理後台: https://option-emk3nc7sumcnyskkt2sk5a.streamlit.app
- V7 即時監控: https://v7-monitor-taiwan-futures.streamlit.app
- Backend API: https://stock-strategy-backend.onrender.com
```

**CLAUDE.md**:
```markdown
## V7 Public Repository

V7 系統已獨立部署到 Public Repository：
- GitHub: https://github.com/walter888tw/v7-monitor
- Streamlit: https://v7-monitor-taiwan-futures.streamlit.app
- 類型: Public App with JWT Authentication
```

---

## 🎉 部署完成檢查清單

- [ ] GitHub Public Repository 已創建
- [ ] 代碼已推送到 GitHub
- [ ] Streamlit Cloud 應用已部署
- [ ] V7 URL 已記錄
- [ ] Backend CORS 已更新
- [ ] 未登入測試通過
- [ ] 已登入測試通過
- [ ] API 保護測試通過
- [ ] 文檔已更新

---

## 🔍 故障排除

### 問題 1: 部署失敗 - 依賴錯誤

**解決方案**:
- 檢查 `requirements.txt` 格式
- 確認 Python 版本為 3.11
- 查看 Streamlit Logs

### 問題 2: CORS 錯誤

**解決方案**:
- 確認 CORS_ORIGINS 包含 V7 URL
- 確認 URL 格式正確（無尾部斜線）
- 等待 Render 重新部署完成

### 問題 3: 認證失敗

**解決方案**:
- 檢查 Secrets 中的 API_BASE_URL
- 測試 Backend API 是否正常
- 檢查 JWT Token 是否過期

---

**預估總時間**: 30-40 分鐘  
**難度**: ⭐⭐ 中等  
**風險**: 🟢 低風險（可隨時回滾）

