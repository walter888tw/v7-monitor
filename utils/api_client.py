"""
API 客戶端工具模組
提供統一的 API 請求介面
"""
import requests
import streamlit as st
from typing import Optional, Dict, Any
from .auth import get_headers, refresh_access_token


class APIClient:
    """API 客戶端類別"""
    
    def __init__(self, base_url: str):
        """初始化 API 客戶端
        
        Args:
            base_url: API 基礎 URL（例如：http://localhost:8000/api/v1）
        """
        self.base_url = base_url.rstrip('/')
    
    def _request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict] = None,
        params: Optional[Dict] = None,
        files: Optional[Dict] = None,
        timeout: int = 30,
        retry_on_401: bool = True
    ) -> requests.Response:
        """發送 API 請求
        
        Args:
            method: HTTP 方法（GET, POST, PUT, DELETE）
            endpoint: API 端點（例如：/auth/login）
            data: 請求 body（JSON）
            params: URL 參數
            files: 文件上傳
            timeout: 超時時間（秒）
            retry_on_401: 收到 401 時是否嘗試刷新 token 並重試
        
        Returns:
            Response 對象
        """
        url = f"{self.base_url}{endpoint}"
        headers = get_headers()
        
        try:
            response = requests.request(
                method=method,
                url=url,
                json=data,
                params=params,
                files=files,
                headers=headers,
                timeout=timeout
            )
            
            # 如果收到 401 且允許重試，嘗試刷新 token
            if response.status_code == 401 and retry_on_401:
                if refresh_access_token(self.base_url.rsplit('/api/v1', 1)[0] + '/api/v1'):
                    # Token 刷新成功，重試請求
                    headers = get_headers()
                    response = requests.request(
                        method=method,
                        url=url,
                        json=data,
                        params=params,
                        files=files,
                        headers=headers,
                        timeout=timeout
                    )
            
            return response
        
        except requests.exceptions.Timeout:
            st.error("❌ 請求超時，請稍後再試")
            raise
        except requests.exceptions.ConnectionError:
            st.error("❌ 無法連接到伺服器，請檢查網路連接")
            raise
        except Exception as e:
            st.error(f"❌ 請求失敗：{str(e)}")
            raise
    
    def get(self, endpoint: str, params: Optional[Dict] = None, **kwargs) -> requests.Response:
        """GET 請求"""
        return self._request('GET', endpoint, params=params, **kwargs)
    
    def post(self, endpoint: str, data: Optional[Dict] = None, **kwargs) -> requests.Response:
        """POST 請求"""
        return self._request('POST', endpoint, data=data, **kwargs)
    
    def put(self, endpoint: str, data: Optional[Dict] = None, **kwargs) -> requests.Response:
        """PUT 請求"""
        return self._request('PUT', endpoint, data=data, **kwargs)
    
    def delete(self, endpoint: str, **kwargs) -> requests.Response:
        """DELETE 請求"""
        return self._request('DELETE', endpoint, **kwargs)
    
    # ==================== V5 策略分析 API ====================
    
    def get_strategy_count(self) -> Optional[Dict[str, int]]:
        """獲取策略數量統計"""
        try:
            response = self.get('/strategy-count')
            if response.status_code == 200:
                return response.json()
        except:
            pass
        return None
    
    def analyze_strategy(
        self,
        csv_5min_content: str,
        csv_daily_content: str,
        target_date: str
    ) -> Optional[Dict[str, Any]]:
        """分析策略（上傳 CSV）"""
        try:
            response = self.post(
                '/analyze',
                data={
                    'csv_5min_content': csv_5min_content,
                    'csv_daily_content': csv_daily_content,
                    'target_date': target_date
                },
                timeout=60
            )
            if response.status_code == 200:
                return response.json()
            else:
                error = response.json().get('detail', '分析失敗')
                st.error(f"❌ {error}")
        except Exception as e:
            st.error(f"❌ 分析失敗：{str(e)}")
        return None

    def analyze_strategy_with_api(
        self,
        symbol: str,
        target_date: str,
        analysis_time: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """分析策略（使用 API 數據）

        Args:
            symbol: 商品代號（例如：TX, MTX）
            target_date: 分析日期（YYYY-MM-DD）
            analysis_time: 分析時間（HH:MM，可選）

        Returns:
            分析結果字典，包含策略匹配結果
        """
        try:
            data = {
                'symbol': symbol,
                'target_date': target_date
            }
            if analysis_time:
                data['analysis_time'] = analysis_time

            response = self.post(
                '/analyze',
                data=data,
                timeout=60
            )
            if response.status_code == 200:
                return response.json()
            else:
                error = response.json().get('detail', '分析失敗')
                st.error(f"❌ {error}")
        except Exception as e:
            st.error(f"❌ 分析失敗：{str(e)}")
        return None

    def get_latest_market_data(
        self,
        symbol: str,
        target_date: str
    ) -> Optional[Dict[str, Any]]:
        """獲取最新市場數據（用於預覽數據來源）

        Args:
            symbol: 商品代號
            target_date: 目標日期

        Returns:
            包含數據來源資訊的字典
        """
        try:
            response = self.get(
                '/market-data/latest',
                params={
                    'symbol': symbol,
                    'analysis_date': target_date
                },
                timeout=30
            )
            if response.status_code == 200:
                return response.json()
        except:
            pass
        return None

    def analyze_strategy_with_cache_key(
        self,
        cache_key: str,
        target_date: str,
        analysis_time: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """分析策略（使用 Cache Key）

        Args:
            cache_key: 快取鍵（格式：symbol:date）
            target_date: 分析日期（YYYY-MM-DD）
            analysis_time: 分析時間（HH:MM，可選）

        Returns:
            分析結果字典
        """
        try:
            data = {
                'cache_key': cache_key,
                'target_date': target_date
            }
            if analysis_time:
                data['analysis_time'] = analysis_time

            response = self.post('/analyze', data=data, timeout=60)
            if response.status_code == 200:
                return response.json()
            else:
                error = response.json().get('detail', '分析失敗')
                st.error(f"❌ {error}")
        except Exception as e:
            st.error(f"❌ 分析失敗：{str(e)}")
        return None

    # ==================== V7 即時監控 API ====================
    
    def get_v7_signals_today(self) -> Optional[list]:
        """獲取今日 V7 全局訊號記錄"""
        try:
            response = self.get('/v7/signals/today')
            print(f"[DEBUG] V7 signals API status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                print(f"[DEBUG] V7 signals response type: {type(data)}")
                print(f"[DEBUG] V7 signals response: {data}")

                # 後端返回格式：{"success": true, "count": 2, "signals": [...]}
                # 只返回 signals 列表
                if isinstance(data, dict) and 'signals' in data:
                    signals = data['signals']
                    print(f"[DEBUG] Extracted signals: {signals}")
                    return signals
                elif isinstance(data, list):
                    # 如果直接返回列表
                    return data
                else:
                    print(f"[DEBUG] Unexpected response format: {type(data)}")
                    return []
            else:
                print(f"[DEBUG] V7 signals API error: {response.status_code} - {response.text}")
                return []
        except Exception as e:
            print(f"獲取 V7 訊號失敗：{str(e)}")
            import traceback
            traceback.print_exc()
        return []
    
    def save_v7_signal(self, signal_data: Dict) -> bool:
        """儲存 V7 訊號記錄"""
        try:
            response = self.post('/v7/signals', data=signal_data)
            return response.status_code == 201
        except:
            return False

