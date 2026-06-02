
import logging
from typing import Optional, Dict, Any
import requests
import yfinance as yf
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class WebPriceFetcher:
    """Fetcher for real-time stock prices and today's OHLC using yfinance."""
    
    @staticmethod
    def _fetch_robinhood_price(ticker: str) -> Optional[float]:
        """Try to fetch price from Robinhood's unofficial API."""
        try:
            url = f"https://api.robinhood.com/quotes/?symbols={ticker}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            # Short timeout to avoid blocking if RH is slow/down
            resp = requests.get(url, headers=headers, timeout=5)
            
            if resp.status_code == 200:
                data = resp.json()
                if 'results' in data and data['results'] and data['results'][0]:
                    quote = data['results'][0]
                    # 'last_trade_price' is usually the most recent trade
                    price_str = quote.get('last_trade_price')
                    if price_str:
                        price = float(price_str)
                        logger.info(f"Robinhood Fetched Price for {ticker}: ${price:.2f}")
                        return price
            else:
                logger.debug(f"Robinhood API returned {resp.status_code}")
                
        except Exception as e:
            logger.warning(f"Robinhood fetch failed for {ticker}: {e}")
        return None

    @staticmethod
    def get_price(ticker: str) -> Optional[float]:
        # 1. Try Robinhood (High Priority - Realtime)
        rh_price = WebPriceFetcher._fetch_robinhood_price(ticker)
        if rh_price:
            return rh_price

        # 2. Fallback to yfinance
        try:
            ticker_obj = yf.Ticker(ticker)
            
            # Fetch fast info for real-time price
            info = ticker_obj.fast_info
            price = info.last_price
            
            if price:
                logger.info(f"yfinance Fetched Price for {ticker}: ${price:.2f}")
                return float(price)
                
            # Fallback to history (1 min interval, last 1 day)
            hist = ticker_obj.history(period="1d", interval="1m")
            if not hist.empty:
                last_close = hist['Close'].iloc[-1]
                logger.info(f"yfinance History Price for {ticker}: ${last_close:.2f}")
                return float(last_close)

            logger.warning(f"No price found in yfinance for {ticker}")
            return None
            
        except Exception as e:
            logger.error(f"yfinance Fetch Error for {ticker}: {e}")
            return None
    
    @staticmethod
    def get_realtime_data(ticker: str) -> Optional[Dict[str, Any]]:
        """
        Get real-time price AND today's OHLC data from yfinance.
        Returns dict with: price, open, high, low, prev_close, volume
        """
        try:
            ticker_obj = yf.Ticker(ticker)
            
            # Get intraday data for today (1-minute bars)
            hist = ticker_obj.history(period="1d", interval="1m")
            
            if hist.empty:
                logger.warning(f"yfinance returned no intraday data for {ticker}")
                return None
            
            # Calculate TODAY's OHLC from all intraday bars
            today_open = float(hist['Open'].iloc[0])      # First bar's open
            today_high = float(hist['High'].max())        # Max high of all bars
            today_low = float(hist['Low'].min())          # Min low of all bars
            current_price = float(hist['Close'].iloc[-1]) # Last bar's close
            today_volume = int(hist['Volume'].sum())      # Sum of all bar volumes
            
            # Get previous close from fast_info
            try:
                prev_close = float(ticker_obj.fast_info.previous_close)
            except:
                prev_close = today_open  # Fallback
            
            data = {
                "price": current_price,
                "open": today_open,
                "high": today_high,
                "low": today_low,
                "prev_close": prev_close,
                "volume": today_volume,
                "source": "YFINANCE_INTRADAY"
            }
            
            logger.info(f"yfinance REALTIME for {ticker}: ${current_price:.2f} | Open: ${today_open:.2f} | High: ${today_high:.2f} | Low: ${today_low:.2f}")
            return data
            
        except Exception as e:
            logger.error(f"yfinance Realtime Error for {ticker}: {e}")
            return None
