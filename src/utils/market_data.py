import pandas as pd
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import logging
import yfinance as yf

logger = logging.getLogger(__name__)

class MarketDataManager:
    """Manages calculation of technical indicators for SOXL/SOXS trading."""

    @staticmethod
    def fetch_market_data(symbol: str, use_intraday: bool = True) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """
        Fetch market data using yfinance exclusively.
        
        Args:
            symbol: Stock ticker symbol
            use_intraday: If True, fetch 5-min bars, else daily bars

        Returns:
            Tuple of (historical_bars, current_quote)
        """
        logger.info(f"Fetching market data for {symbol} using yfinance")
        
        try:
            ticker = yf.Ticker(symbol)
            
            if use_intraday:
                # Get 5-day history with 5-minute bars for intraday analysis
                df = ticker.history(period="5d", interval="5m")
                if df.empty:
                    logger.warning(f"No intraday data for {symbol}, trying daily")
                    df = ticker.history(period="60d", interval="1d")
            else:
                # Get 60 days of daily data
                df = ticker.history(period="60d", interval="1d")
            
            if df.empty:
                logger.error(f"No data returned from yfinance for {symbol}")
                return [], None
            
            # Convert to list of dicts
            bars = []
            for idx, row in df.iterrows():
                bars.append({
                    'timestamp': idx.strftime('%Y-%m-%d %H:%M:%S'),
                    'open': float(row['Open']),
                    'high': float(row['High']),
                    'low': float(row['Low']),
                    'close': float(row['Close']),
                    'volume': int(row['Volume'])
                })
            
            logger.info(f"Fetched {len(bars)} bars for {symbol} from yfinance")
            return bars, None
            
        except Exception as e:
            logger.error(f"yfinance error for {symbol}: {e}")
            return [], None

    @staticmethod
    def calculate_indicators(data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculate technical indicators from OHLCV data.
        Optimized for SOXL/SOXS day trading with momentum signals.
        """
        if not data:
            return {}

        df = pd.DataFrame(data)
        # Ensure numeric columns
        cols = ['open', 'high', 'low', 'close', 'volume']
        for c in cols:
            df[c] = pd.to_numeric(df[c])

        # === PRICE DATA (from LATEST bar only) ===
        latest = df.iloc[-1]
        current_price = latest['close']
        
        # For TODAY's data, use only the last bar's OHLC
        # This is accurate for both intraday (last 5min bar) and daily (today's bar)
        high_today = latest['high']
        low_today = latest['low']
        open_today = latest['open']
        
        # Previous close for accurate day change calculation
        if len(df) >= 2:
            prev_close = df.iloc[-2]['close']
            day_change_pct = ((current_price - prev_close) / prev_close) * 100
        else:
            # Fallback: compare close to open of same bar
            day_change_pct = ((current_price - open_today) / open_today) * 100 if open_today > 0 else 0

        # === RSI (14) ===
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI_14'] = 100 - (100 / (1 + rs))
        rsi = df['RSI_14'].iloc[-1]
        
        # RSI Signal
        if pd.notna(rsi):
            if rsi > 70:
                rsi_signal = "OVERBOUGHT"
            elif rsi > 50:
                rsi_signal = "BULLISH"
            elif rsi > 30:
                rsi_signal = "BEARISH"
            else:
                rsi_signal = "OVERSOLD"
        else:
            rsi_signal = "N/A"
        
        # === MACD (12, 26, 9) ===
        exp12 = df['close'].ewm(span=12, adjust=False).mean()
        exp26 = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp12 - exp26
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
        
        macd = df['MACD'].iloc[-1]
        macd_signal = df['MACD_Signal'].iloc[-1]
        macd_hist = df['MACD_Hist'].iloc[-1]
        macd_hist_prev = df['MACD_Hist'].iloc[-2] if len(df) > 1 else 0
        
        # MACD Crossover Detection
        if pd.notna(macd_hist) and pd.notna(macd_hist_prev):
            if macd_hist > 0 and macd_hist_prev <= 0:
                macd_crossover = "BULLISH CROSSOVER (BUY SIGNAL)"
            elif macd_hist < 0 and macd_hist_prev >= 0:
                macd_crossover = "BEARISH CROSSOVER (SELL SIGNAL)"
            elif macd_hist > 0:
                macd_crossover = "BULLISH (above signal)"
            else:
                macd_crossover = "BEARISH (below signal)"
        else:
            macd_crossover = "N/A"
        
        # === ATR (14) ===
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        df['ATR_14'] = true_range.rolling(window=14).mean()
        atr = df['ATR_14'].iloc[-1]
        
        # === VWAP ===
        try:
            tp = (df['high'] + df['low'] + df['close']) / 3
            df['VWAP'] = (tp * df['volume']).cumsum() / df['volume'].cumsum()
            vwap = df['VWAP'].iloc[-1]
        except Exception:
            vwap = None
        
        # VWAP Signal
        if pd.notna(vwap) and vwap > 0:
            vwap_pct = ((current_price / vwap) - 1) * 100
            if current_price > vwap:
                vwap_signal = f"ABOVE VWAP (+{vwap_pct:.2f}%) - BULLISH"
            else:
                vwap_signal = f"BELOW VWAP ({vwap_pct:.2f}%) - BEARISH"
        else:
            vwap_signal = "N/A"

        # === SMA 20 for Trend ===
        sma_20 = df['close'].rolling(window=20).mean().iloc[-1]
        trend = "BULLISH" if pd.notna(sma_20) and current_price > sma_20 else "BEARISH"
        
        # === Volume Analysis ===
        avg_volume = df['volume'].rolling(window=20).mean().iloc[-1]
        current_volume = latest['volume']
        if pd.notna(avg_volume) and avg_volume > 0:
            vol_ratio = current_volume / avg_volume
            if vol_ratio > 1.5:
                volume_signal = f"HIGH VOLUME ({vol_ratio:.1f}x avg)"
            elif vol_ratio > 0.8:
                volume_signal = f"NORMAL VOLUME ({vol_ratio:.1f}x avg)"
            else:
                volume_signal = f"LOW VOLUME ({vol_ratio:.1f}x avg)"
        else:
            volume_signal = "N/A"

        return {
            "current_price": round(current_price, 2),
            "open_price": round(open_today, 2),
            "high": round(high_today, 2),
            "low": round(low_today, 2),
            "day_change_pct": round(day_change_pct, 2),
            "prev_close": round(prev_close, 2) if len(df) >= 2 else None,
            "rsi": round(rsi, 2) if pd.notna(rsi) else None,
            "rsi_signal": rsi_signal,
            "macd": round(macd, 4) if pd.notna(macd) else None,
            "macd_signal": round(macd_signal, 4) if pd.notna(macd_signal) else None,
            "macd_histogram": round(macd_hist, 4) if pd.notna(macd_hist) else None,
            "macd_crossover": macd_crossover,
            "atr": round(atr, 2) if pd.notna(atr) else None,
            "vwap": round(vwap, 2) if pd.notna(vwap) else None,
            "vwap_signal": vwap_signal,
            "sma_20": round(sma_20, 2) if pd.notna(sma_20) else None,
            "trend": trend,
            "volume": int(current_volume),
            "volume_signal": volume_signal
        }

    @staticmethod
    def format_market_context(ticker: str, indicators: Dict[str, Any]) -> str:
        """Format indicator data into a readable string for SOXL/SOXS trading AI."""
        if not indicators:
            return f"{ticker}: No market data available."
        
        current_price = indicators.get('current_price', 0)
        day_change = indicators.get('day_change_pct', 0) or 0
        prev_close = indicators.get('prev_close')
        open_price = indicators.get('open_price', 0)
        high = indicators.get('high', 0)
        low = indicators.get('low', 0)
        
        # Build price context
        price_context = f"PRICE: ${current_price}"
        if prev_close:
            price_context += f" (Change: {day_change:+.2f}% from prev close ${prev_close})"
        else:
            price_context += f" (Change: {day_change:+.2f}%)"
        
        # VWAP distance calculation
        vwap = indicators.get('vwap')
        vwap_pct = ""
        if vwap and vwap > 0:
            vwap_diff = ((current_price - vwap) / vwap) * 100
            vwap_pct = f" ({vwap_diff:+.1f}% from VWAP)"
        
        return f"""
=== {ticker} MARKET DATA ===
{price_context}
TODAY: Open ${open_price} | High ${high} | Low ${low}

TECHNICAL INDICATORS:
- RSI (14): {indicators.get('rsi')}
- MACD: {indicators.get('macd')} (Signal: {indicators.get('macd_signal')})
- MACD Histogram: {indicators.get('macd_histogram')}
- SMA20: ${indicators.get('sma_20')}
- VWAP: ${vwap}{vwap_pct}
- ATR (14): ${indicators.get('atr')}
"""

