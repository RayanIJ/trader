"""
Alpha Vantage API client for fetching market data.
Used for analyze-only mode when IB connection is not needed.
"""
import logging
import requests
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class AlphaVantageClient:
    """Client for fetching market data from Alpha Vantage API."""
    
    BASE_URL = "https://www.alphavantage.co/query"
    
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Alpha Vantage API key is required")
        self.api_key = api_key
    
    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get real-time quote for a symbol.
        
        Returns:
            Dict with price, change, volume, etc. or None if failed.
        """
        try:
            params = {
                "function": "GLOBAL_QUOTE",
                "symbol": symbol,
                "apikey": self.api_key
            }
            
            response = requests.get(self.BASE_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if "Global Quote" not in data or not data["Global Quote"]:
                logger.warning(f"No quote data for {symbol}: {data}")
                return None
            
            quote = data["Global Quote"]
            
            return {
                "symbol": quote.get("01. symbol", symbol),
                "price": float(quote.get("05. price", 0)),
                "open": float(quote.get("02. open", 0)),
                "high": float(quote.get("03. high", 0)),
                "low": float(quote.get("04. low", 0)),
                "volume": int(quote.get("06. volume", 0)),
                "previous_close": float(quote.get("08. previous close", 0)),
                "change": float(quote.get("09. change", 0)),
                "change_percent": quote.get("10. change percent", "0%").replace("%", ""),
            }
            
        except Exception as e:
            logger.error(f"Alpha Vantage quote error for {symbol}: {e}")
            return None
    
    def get_intraday_data(
        self, 
        symbol: str, 
        interval: str = "5min",
        outputsize: str = "compact"
    ) -> List[Dict[str, Any]]:
        """
        Get intraday OHLCV data for technical analysis.
        
        Args:
            symbol: Stock ticker
            interval: Time interval (1min, 5min, 15min, 30min, 60min)
            outputsize: 'compact' (100 points) or 'full' (full history)
            
        Returns:
            List of OHLCV bars in chronological order.
        """
        try:
            params = {
                "function": "TIME_SERIES_INTRADAY",
                "symbol": symbol,
                "interval": interval,
                "outputsize": outputsize,
                "apikey": self.api_key
            }
            
            response = requests.get(self.BASE_URL, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            # Check for error messages
            if "Error Message" in data:
                logger.error(f"Alpha Vantage error: {data['Error Message']}")
                return []
            
            if "Note" in data:
                logger.warning(f"Alpha Vantage rate limit: {data['Note']}")
                return []
            
            # Check for Information message (usually means invalid/missing API key)
            if "Information" in data:
                logger.error(f"Alpha Vantage API issue: {data['Information']}")
                return []
            
            time_series_key = f"Time Series ({interval})"
            if time_series_key not in data:
                logger.warning(f"No intraday data for {symbol}. Response keys: {list(data.keys())}")
                return []
            
            time_series = data[time_series_key]
            
            # Convert to list of bars in chronological order
            bars = []
            for timestamp, values in sorted(time_series.items()):
                bars.append({
                    "date": timestamp,
                    "open": float(values["1. open"]),
                    "high": float(values["2. high"]),
                    "low": float(values["3. low"]),
                    "close": float(values["4. close"]),
                    "volume": int(values["5. volume"]),
                    "barCount": 1,
                    "average": (float(values["2. high"]) + float(values["3. low"])) / 2
                })
            
            logger.info(f"Fetched {len(bars)} intraday bars for {symbol} from Alpha Vantage")
            return bars
            
        except Exception as e:
            logger.error(f"Alpha Vantage intraday error for {symbol}: {e}")
            return []
    
    def get_daily_data(
        self, 
        symbol: str, 
        outputsize: str = "compact"
    ) -> List[Dict[str, Any]]:
        """
        Get daily OHLCV data for technical analysis.
        Fallback when intraday is not available.
        
        Args:
            symbol: Stock ticker
            outputsize: 'compact' (100 days) or 'full' (20+ years)
            
        Returns:
            List of OHLCV bars in chronological order.
        """
        try:
            params = {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": outputsize,
                "apikey": self.api_key
            }
            
            response = requests.get(self.BASE_URL, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            if "Error Message" in data:
                logger.error(f"Alpha Vantage error: {data['Error Message']}")
                return []
            
            if "Note" in data:
                logger.warning(f"Alpha Vantage rate limit: {data['Note']}")
                return []
            
            # Check for Information message (usually means invalid/missing API key)
            if "Information" in data:
                logger.error(f"Alpha Vantage API issue: {data['Information']}")
                return []
            
            if "Time Series (Daily)" not in data:
                logger.warning(f"No daily data for {symbol}. Response keys: {list(data.keys())}")
                return []
            
            time_series = data["Time Series (Daily)"]
            
            # Convert to list of bars in chronological order
            bars = []
            for timestamp, values in sorted(time_series.items()):
                bars.append({
                    "date": timestamp,
                    "open": float(values["1. open"]),
                    "high": float(values["2. high"]),
                    "low": float(values["3. low"]),
                    "close": float(values["4. close"]),
                    "volume": int(values["5. volume"]),
                    "barCount": 1,
                    "average": (float(values["2. high"]) + float(values["3. low"])) / 2
                })
            
            logger.info(f"Fetched {len(bars)} daily bars for {symbol} from Alpha Vantage")
            return bars
            
        except Exception as e:
            logger.error(f"Alpha Vantage daily error for {symbol}: {e}")
            return []


# Convenience function for getting market data
def get_alpha_vantage_data(
    symbol: str,
    api_key: str,
    use_intraday: bool = True
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Convenience function to fetch market data from Alpha Vantage.
    Falls back to yfinance if Alpha Vantage fails.
    
    Args:
        symbol: Stock ticker
        api_key: Alpha Vantage API key
        use_intraday: If True, try intraday first, fallback to daily
        
    Returns:
        Tuple of (historical_bars, current_quote)
    """
    bars = []
    quote = None
    
    # Try Alpha Vantage first if API key is provided
    if api_key:
        try:
            client = AlphaVantageClient(api_key)
            
            # Get current quote
            quote = client.get_quote(symbol)
            
            # Get historical data
            if use_intraday:
                bars = client.get_intraday_data(symbol, interval="5min", outputsize="compact")
                if not bars:
                    # Fallback to daily if intraday fails (e.g., outside market hours)
                    logger.info(f"Intraday unavailable for {symbol}, falling back to daily data")
                    bars = client.get_daily_data(symbol, outputsize="compact")
            else:
                bars = client.get_daily_data(symbol, outputsize="compact")
        except Exception as e:
            logger.warning(f"Alpha Vantage failed: {e}")
    
    # Fallback to yfinance if Alpha Vantage didn't work
    if not bars:
        logger.info(f"Using yfinance fallback for {symbol}")
        bars, quote = _get_yfinance_data(symbol)
    
    return bars, quote


def _get_yfinance_data(symbol: str) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Fallback data source using yfinance (no API key required).
    """
    try:
        # Try a simpler approach to avoid yfinance typing issues
        import yfinance as yf

        ticker = yf.Ticker(symbol)

        # Get quote info - use fast_info to avoid typing issues
        try:
            fast_info = ticker.fast_info
            quote = {
                "symbol": symbol,
                "price": float(fast_info.last_price) if fast_info.last_price else 0,
                "open": 0,  # Not available in fast_info
                "high": 0,  # Not available in fast_info
                "low": 0,   # Not available in fast_info
                "volume": 0, # Not available in fast_info
                "previous_close": 0, # Not available in fast_info
            }
        except Exception:
            # Fallback quote
            quote = {
                "symbol": symbol,
                "price": 0,
                "open": 0,
                "high": 0,
                "low": 0,
                "volume": 0,
                "previous_close": 0,
            }

        # Get historical data - use simple 1d interval to avoid issues
        hist = ticker.history(period="3mo", interval="1d")

        if hist.empty:
            logger.warning(f"yfinance returned no data for {symbol}")
            return [], quote

        # Convert to our bar format
        bars = []
        for idx, row in hist.iterrows():
            bars.append({
                "date": str(idx),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
                "barCount": 1,
                "average": (float(row["High"]) + float(row["Low"])) / 2
            })

        logger.info(f"Fetched {len(bars)} bars for {symbol} from yfinance")
        return bars, quote

    except Exception as e:
        logger.error(f"yfinance error for {symbol}: {e}")
        # Return empty data but don't crash
        return [], None

