# V7 即時監控前端 Dockerfile — 適用於 Render.com 部署
FROM python:3.11-slim

WORKDIR /app

# 安裝依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式碼
COPY . .

# Streamlit 設定：關閉 CORS（由 Render 反向代理處理）+ 關閉使用統計
RUN mkdir -p ~/.streamlit && \
    printf '[server]\nheadless = true\nenableCORS = false\nenableXsrfProtection = false\n\n[browser]\ngatherUsageStats = false\n' > ~/.streamlit/config.toml

# Render 使用 PORT 環境變數（預設 8501）
EXPOSE 8501

CMD sh -c "streamlit run app.py --server.port ${PORT:-8501} --server.address 0.0.0.0"
