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

    def analyze_v7(self, analysis_date: str, analysis_time: str) -> Optional[Dict[str, Any]]:
        """執行 V7 雙策略分析

        Args:
            analysis_date: 分析日期 (YYYY-MM-DD)
            analysis_time: 分析時間 (HH:MM)

        Returns:
            分析結果字典（包含 success, original, optimized, market_data），
            如果失敗則返回 None
        """
        try:
            response = self._request(
                'POST',
                '/v7/analyze',
                data={
                    'analysis_date': analysis_date,
                    'analysis_time': analysis_time
                },
                timeout=30
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 400:
                try:
                    error = response.json().get('detail', '請求參數錯誤')
                except Exception:
                    error = f'HTTP {response.status_code}'
                st.warning(f"⚠️ {error}")
            elif response.status_code == 422:
                st.warning("⚠️ 分析參數格式錯誤，請確認日期和時間格式")
            else:
                try:
                    error = response.json().get('detail', f'HTTP {response.status_code}')
                except Exception:
                    error = f'HTTP {response.status_code}'
                st.error(f"❌ 分析失敗：{error}")
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                Exception):
            # _request() 已經顯示了錯誤訊息，這裡只需靜默返回 None
            pass
        return None

    def get_v7_signals_today(self) -> Optional[list]:
        """獲取今日 V7 全局訊號記錄

        Returns:
            訊號列表，如果失敗則返回空列表
        """
        try:
            response = self._request('GET', '/v7/signals/today')

            if response.status_code == 200:
                data = response.json()

                # 後端返回格式：{"success": true, "count": 2, "signals": [...]}
                if isinstance(data, dict) and 'signals' in data:
                    return data['signals']
                elif isinstance(data, list):
                    return data
                else:
                    return []
            else:
                return []
        except Exception:
            pass
        return []

    def save_v7_signal(self, signal_data: Dict) -> bool:
        """儲存 V7 訊號記錄"""
        try:
            response = self.post('/v7/signals', data=signal_data)
            return response.status_code == 201
        except Exception:
            return False

    # ==================== VIX 數據 API ====================

    def get_vix_today(self) -> Optional[Dict[str, Any]]:
        """獲取今日 VIX 分鐘級數據

        Returns:
            包含 success, count, latest, data 的字典，失敗返回 None
        """
        try:
            response = self._request('GET', '/vix/today', timeout=15)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return None

    def get_treasury_yield(self) -> Optional[Dict[str, Any]]:
        """獲取美國 10 年期公債殖利率

        Returns:
            包含 success, yield_pct, change, change_pct, source 的字典，失敗返回 None
        """
        try:
            response = self._request('GET', '/v7/treasury', timeout=10)
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return None

    def get_vix_history(self, days: int = 30) -> Optional[Dict[str, Any]]:
        """獲取歷史日線 VIX 數據

        Args:
            days: 查詢天數

        Returns:
            包含 success, count, data 的字典，失敗返回 None
        """
        try:
            response = self._request(
                'GET', '/vix/history',
                params={'days': days},
                timeout=15
            )
            if response.status_code == 200:
                return response.json()
        except Exception:
            pass
        return None

