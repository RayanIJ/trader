"""
Main entry point for the AI Trading Application.
"""
import sys
import os
import logging
import time
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

# Ensure project root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import settings
from src.ib.trading_app import TradingApp
from src.ib import contracts, orders
from src.ai.openai_client import OpenAIClient
from src.scheduler.market_scheduler import MarketScheduler
from src.models.trading import TradingRecommendation, PortfolioSnapshot
from src.utils.cycle_logger import CycleLogger
from src.utils.market_data import MarketDataManager

# Configure Logging
logging.basicConfig(
    level=settings.log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("trader.log")
    ]
)

logger = logging.getLogger("Trader")


@dataclass
class ManualCycleResult:
    """Result of a manual trading cycle for a single ticker."""
    ticker: str
    success: bool
    indicators: Dict[str, Any]
    recommendation: Optional[TradingRecommendation]
    ai_context: Dict[str, Any]
    action_taken: Optional[str]
    error: Optional[str] = None
    portfolio_snapshot: Optional[Dict[str, Any]] = None

class TradingBot:
    def __init__(self, init_scheduler: bool = True):
        """
        Initialize the trading bot.
        
        Args:
            init_scheduler: If True, initialize the scheduler (requires main thread).
                           Set to False when using from UI/non-main threads.
        """
        self.ib_app = TradingApp()
        self.openai_client = OpenAIClient()
        self.cycle_logger = CycleLogger()
        self._scheduler = None
        self._init_scheduler = init_scheduler

    @property
    def scheduler(self) -> MarketScheduler:
        """Lazy initialization of scheduler (only when needed)."""
        if self._scheduler is None:
            self._scheduler = MarketScheduler(self.execute_trading_cycle)
        return self._scheduler

    def start(self):
        """Start the trading bot."""
        logger.info(f"Starting Trading Bot (Dry Run: {settings.dry_run})")
        
        # 1. Connect to IB
        try:
            self.ib_app.connect_and_start(
                host=settings.ib_host,
                port=settings.ib_port,
                client_id=settings.ib_client_id
            )
        except Exception as e:
            logger.critical(f"Failed to connect to IB: {e}")
            return

        # Verification Trade (Executed once on startup if enabled)
        # We manually trigger this before the scheduler loop
        if os.getenv("EXECUTE_TEST_TRADE", "false").lower() == "true":
            ticker = os.getenv("TEST_TICKER", "SIRI")
            logger.info(f">>> Executing TEST TRADE ({ticker}, 1 share, Outside RTH) <<<")
            try:
                # Stock: Liquid symbol
                contract = contracts.us_stock_contract(ticker)
                # Order: Market, 1 share, Allow Outside RTH
                order = orders.market_order("BUY", 1, outside_rth=True)
                
                if settings.dry_run:
                    logger.info(f"[DRY RUN] Would place test trade: BUY 1 {ticker}")
                else:
                    oid = self.ib_app.place_trade(contract, order)
                    logger.info(f"Test Trade Placed! OrderId: {oid}")
            except Exception as e:
                logger.error(f"Test Trade Failed: {e}")

        if os.getenv("SINGLE_RUN", "false").lower() == "true":
            logger.info("SINGLE_RUN enabled. Executing one cycle immediately (bypassing scheduler)...")
            self.execute_trading_cycle()
            return
            
        # 2. Start Scheduler Loop
        self.scheduler.run()
        
        # 3. Cleanup on exit
        logger.info("Disconnecting from IB...")
        self.ib_app.disconnect()

    def execute_trading_cycle(self):
        """One complete trading iteration."""
        logger.info("--- New Trading Cycle ---")
        
        # 1. Get Portfolio State
        portfolio = self.ib_app.get_portfolio_snapshot()
        logger.info(f"Portfolio loaded: {len(portfolio.positions)} positions")
        
        # 2. Fetch pending orders to prevent duplicates
        pending_orders = self.ib_app.get_open_orders()
        pending_symbols = self.ib_app.get_pending_order_symbols()
        if pending_orders:
            logger.info(f"Pending orders: {len(pending_orders)} orders for {pending_symbols}")
            for order in pending_orders:
                logger.info(f"  → {order['action']} {order['quantity']} {order['symbol']} @ ${order.get('limit_price', 'MKT')} [{order['status']}]")
        
        # 3. Request real-time streaming prices for SOXL/SOXS
        target_list = ["SOXL", "SOXS"]
        logger.info("Requesting REAL-TIME STREAMING prices for: SOXL, SOXS")
        self.ib_app.request_market_prices(target_list)
        
        # --- TIME-BASED SESSION FILTER ---
        # Skip first 2 minutes (9:30-9:32 ET) and last 5 minutes (3:55-4:00 ET)
        # These periods are choppy and prone to false signals
        from src.config.market_calendar import get_current_et_time
        now_et = get_current_et_time()
        market_open_minute = 9 * 60 + 30  # 9:30 AM = 570 minutes
        current_minute = now_et.hour * 60 + now_et.minute
        
        # Skip first 2 minutes after open (9:30-9:32)
        if current_minute >= market_open_minute and current_minute < market_open_minute + 2:
            logger.warning(f"SESSION FILTER: Skipping {now_et.strftime('%H:%M')} ET - first 2 minutes after open")
            return
        
        # --- EOD SAFETY CHECK ---
        # Force close everything if it's past 3:55 PM ET (also skips last 5 min for new trades)
        if now_et.time().hour == 15 and now_et.time().minute >= 55:
            logger.critical(f"EOD WARNING: It is {now_et.strftime('%H:%M')} ET. FORCING CLOSE ALL POSITIONS.")
            for p in portfolio.positions:
                if float(p.quantity) != 0:
                    logger.info(f"EOD CLOSE: Selling {p.quantity} {p.symbol}")
                    contract = contracts.us_stock_contract(p.symbol)
                    # Use MARKET order for reliable EOD exit (overrides strict limit rule)
                    order = orders.market_order("SELL", float(p.quantity))
                    self.ib_app.place_trade(contract, order)
            return # Stop cycle
        # ------------------------
        
        # --- DAILY PnL CIRCUIT BREAKER (Goal: 2.0%) ---
        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            history = self.cycle_logger.load_history()
            today_records = [r for r in history if r['timestamp'].startswith(today_str)]
            
            if today_records:
                # Find the first record of the day to set baseline
                first_record = min(today_records, key=lambda x: x['timestamp'])
                # Start equity is stored in string in snapshot, convert carefully
                start_net_liq = float(first_record['portfolio']['account']['net_liquidation'])
                current_net_liq = float(portfolio.account.net_liquidation)
                
                daily_pnl = current_net_liq - start_net_liq
                daily_pnl_pct = (daily_pnl / start_net_liq) * 100
                
                logger.info(f"DAILY PnL: ${daily_pnl:.2f} ({daily_pnl_pct:.2f}%)")
                
                if daily_pnl_pct >= 2.0:
                    logger.critical("DAILY TARGET HIT (+2%): Stopping Trading for the day! 🎯")
                    return # Stop cycle
                
                if daily_pnl_pct <= -1.5:
                    logger.critical("DAILY STOP HIT (-1.5%): Stopping Trading for the day! 🛡️")
                    return # Stop cycle
        except Exception as e:
            logger.error(f"Error calculating Daily PnL: {e}")
        # ----------------------------------------------
        
        # 3. Log current state (Audit)
        self._log_portfolio_summary(portfolio)
        
        # 4. Target Identification
        logger.info(f"Analyzing {len(target_list)} tickers: {target_list}")
            
        # 5. Per-Ticker Analysis Loop
        for ticker in target_list:
            if not ticker: continue
            
            logger.info(f">>> Analyzing {ticker} <<<")
            
            # A. Fetch historical data for indicator calculation (Alpha Vantage/yfinance)
            history, quote = MarketDataManager.fetch_market_data(ticker, use_intraday=True)

            if not history:
                logger.warning(f"No market data found for {ticker}. Skipping.")
                continue

            indicators = MarketDataManager.calculate_indicators(history)
            
            # B. Get REAL-TIME price and TODAY's OHLC from yfinance (most accurate)
            try:
                from src.utils.web_price_fetcher import WebPriceFetcher
                realtime_data = WebPriceFetcher.get_realtime_data(ticker)
                if realtime_data:
                    # Override with real-time data
                    indicators['current_price'] = realtime_data['price']
                    indicators['open_price'] = realtime_data['open']
                    indicators['high'] = realtime_data['high']
                    indicators['low'] = realtime_data['low']
                    indicators['prev_close'] = realtime_data['prev_close']
                    indicators['volume'] = realtime_data['volume']
                    indicators['price_source'] = 'YFINANCE REALTIME'
                    # Recalculate day change with accurate data
                    if realtime_data['prev_close'] > 0:
                        indicators['day_change_pct'] = round(
                            ((realtime_data['price'] - realtime_data['prev_close']) / realtime_data['prev_close']) * 100, 2
                        )
                    logger.info(f"REALTIME {ticker}: ${realtime_data['price']:.2f} | Open: ${realtime_data['open']:.2f} | High: ${realtime_data['high']:.2f} | Low: ${realtime_data['low']:.2f}")
                else:
                    indicators['price_source'] = 'HISTORICAL'
                    logger.warning(f"yfinance realtime failed for {ticker}, using historical data")
            except Exception as e:
                indicators['price_source'] = 'HISTORICAL'
                logger.warning(f"WebPriceFetcher failed for {ticker}: {e}")

            # Log current status
            logger.info(f"{ticker} Analysis: ${indicators.get('current_price')} | RSI: {indicators.get('rsi')} | MACD: {indicators.get('macd_crossover')}")
            
            market_context = MarketDataManager.format_market_context(ticker, indicators)
            
            # --- HARD RULE: SCALPING AUTO-EXECUTION (TP 0.8% / SL 0.4%) ---
            position = next((p for p in portfolio.positions if p.symbol == ticker and float(p.quantity) > 0), None)
            if position:
                try:
                    current_price = float(indicators.get('current_price', 0))
                    avg_cost = float(position.avg_cost)
                    qty = float(position.quantity)
                    
                    if avg_cost > 0:
                        pnl_pct = ((current_price - avg_cost) / avg_cost) * 100
                        logger.info(f"HARD RULE CHECK {ticker}: PnL={pnl_pct:.2f}% (Price: {current_price}, Cost: {avg_cost})")
                        
                        # TAKE PROFIT: +0.8%
                        if pnl_pct >= 0.8:
                            logger.info(f"SCALP TP HIT (+0.8%): Selling {qty} {ticker} at LIMIT {current_price}")
                            contract = contracts.us_stock_contract(ticker)
                            # Limit order to capture spread
                            order = orders.limit_order("SELL", qty, current_price) 
                            self.ib_app.place_trade(contract, order)
                            continue # Skip AI

                        # STOP LOSS: -0.4% (STOP MARKET)
                        if pnl_pct <= -0.4:
                            logger.warning(f"SCALP SL HIT (-0.4%): STOP MARKET Sell {qty} {ticker}")
                            contract = contracts.us_stock_contract(ticker)
                            # STOP MARKET Order for guaranteed exit
                            # Note: IB uses 'STP' order type for Stop Market. 
                            # We place a Market order here directly because we are reacting to LIVE price
                            # and want immediate exit. A 'STP' order is usually placed in advance.
                            # Since we are probing in real-time, sending a MKT order now is effectively a 'Stop Market' trigger.
                            order = orders.market_order("SELL", qty)
                            self.ib_app.place_trade(contract, order)
                            continue # Skip AI
                            
                except Exception as e:
                    logger.error(f"Error in TP/SL Logic: {e}")
            # -----------------------------------------------------------
            
            # B. AI Decision (Agentic Tool Use)
            # We no longer manually fetch news. The AI will call 'web_search' if it needs it.
            recommendation, ai_context = self.openai_client.get_trading_recommendation(
                portfolio=portfolio,
                market_context=market_context,
                ticker=ticker  # Pass current ticker for focused context
            )
            
            # C. Execute
            
            # D. Execute
            actions_taken = []
            if recommendation:
                action_result = self.process_recommendation(recommendation, portfolio)
                if action_result:
                    actions_taken.append(action_result)
            
            # E. Log Cycle (Per Ticker) - but skip if AI failed with error
            if "error" in ai_context:
                logger.warning(f"Skipping cycle log due to AI error: {ai_context.get('error', 'Unknown')}")
            else:
                self.cycle_logger.log_cycle(
                    cycle_id=datetime.now().strftime("%Y%m%d-%H%M%S"),
                    portfolio_snapshot=portfolio.model_dump(),
                    ai_context=ai_context,
                    recommendation=recommendation.model_dump() if recommendation else {},
                    actions_taken=actions_taken
                )
            
            # Rate limiting to avoid hitting OpenAI/IB limits
            time.sleep(2)

        if os.getenv("SINGLE_RUN", "false").lower() == "true":
            logger.info("SINGLE_RUN enabled. Exiting after analysis.")
            sys.exit(0)

    def process_recommendation(self, rec: TradingRecommendation, portfolio: PortfolioSnapshot) -> Optional[str]:
        """Validate and execute a trading recommendation. Returns a summary string of action taken."""
        logger.info(f"Processing Recommendation: {rec.action} {rec.symbol} ({rec.confidence*100:.1f}%)")
        logger.info(f"Reasoning: {rec.reasoning}")
        
        # Validation checks
        if rec.action == "HOLD":
            logger.info("Action is HOLD. No trade executed.")
            return "HOLD"

        # Force LIMIT orders
        if rec.order_type == "MARKET":
            msg = "Error: MARKET orders are forbidden. AI must use LIMIT."
            logger.error(msg)
            return msg
        
        # Check for duplicate BUY - only if already holding position
        if rec.action == "BUY":
            held_symbols = [p.symbol for p in portfolio.positions if float(p.quantity) > 0]
            if rec.symbol in held_symbols:
                msg = f"Skipped: Already holding {rec.symbol} in portfolio. No additional BUY allowed."
                logger.warning(msg)
                return msg
            
            # Check for pending orders to prevent duplicate submissions
            if self.ib_app.has_pending_order_for(rec.symbol, "BUY"):
                msg = f"Skipped: Pending BUY order already exists for {rec.symbol}."
                logger.warning(msg)
                return msg
            
        if rec.confidence < settings.confidence_threshold:
            msg = f"Skipped: Confidence {rec.confidence:.2f} < {settings.confidence_threshold}"
            logger.warning(msg)
            return msg
        
        # ALWAYS calculate quantity based on max_dollars_per_trade (ignore AI's quantity)
        if not rec.limit_price or rec.limit_price <= 0:
            msg = f"Skipped: Invalid limit price {rec.limit_price}"
            logger.warning(msg)
            return msg
        
        # Calculate quantity = max_dollars / price (use full allocation)
        calculated_qty = int(settings.max_dollars_per_trade / rec.limit_price)
        logger.info(f"Calculated quantity: {calculated_qty} shares (${settings.max_dollars_per_trade:.0f} / ${rec.limit_price:.2f})")
        rec.quantity = calculated_qty
        
        if rec.quantity <= 0:
            msg = f"Skipped: Calculated quantity is 0 (price ${rec.limit_price:.2f} exceeds max trade ${settings.max_dollars_per_trade:.0f})"
            logger.warning(msg)
            return msg
        
        # Log final trade value
        trade_value = rec.quantity * rec.limit_price
        logger.info(f"Trade value: ${trade_value:.2f} ({rec.quantity} shares @ ${rec.limit_price:.2f})")

        # Create IB Objects
        contract = contracts.us_stock_contract(rec.symbol)
        
        if rec.order_type == "MARKET":
            order = orders.market_order(rec.action, rec.quantity)
        elif rec.order_type == "LIMIT":
            order = orders.limit_order(rec.action, rec.quantity, rec.limit_price)
        elif rec.order_type == "STOP":
            order = orders.stop_order(rec.action, rec.quantity, rec.stop_price)
        else:
            msg = f"Error: Unsupported order type {rec.order_type}"
            logger.error(msg)
            return msg

        # Execution
        if settings.dry_run:
            msg = f"[DRY RUN] Would execute: {order.action} {order.totalQuantity} {contract.symbol}"
            logger.info(msg)
            return msg
        else:
            try:
                order_id = self.ib_app.place_trade(contract, order)
                msg = f"Trade placed: {order.action} {order.totalQuantity} {contract.symbol}. Order ID: {order_id}"
                logger.info(msg)
                return msg
            except Exception as e:
                msg = f"Trade failed: {e}"
                logger.error(msg)
                return msg

    def _log_portfolio_summary(self, p: PortfolioSnapshot):
        """Helper to log portfolio stats."""
        total_value = p.account.net_liquidation or 0.0
        cash = p.account.total_cash_value or 0.0
        logger.info(f"Net Liq: ${total_value:,.2f} | Cash: ${cash:,.2f}")

    def run_manual_cycle(
        self, 
        ticker: str, 
        analyze_only: bool = False,
        skip_safety_checks: bool = False
    ) -> ManualCycleResult:
        """
        Run a single trading cycle for a specific ticker.
        
        Args:
            ticker: Stock ticker symbol (e.g., "AAPL", "SOXL")
            analyze_only: If True, only analyze using Alpha Vantage - don't connect to IB
            skip_safety_checks: If True, skip EOD and TP/SL auto-execution
            
        Returns:
            ManualCycleResult with analysis details and any actions taken
        """
        ticker = ticker.upper().strip()
        logger.info(f"=== MANUAL CYCLE: {ticker} ===")
        logger.info(f"Mode: {'ANALYZE ONLY (Alpha Vantage)' if analyze_only else 'FULL EXECUTION (IB)'}")
        
        try:
            # =====================================================================
            # ANALYZE ONLY MODE - Use Alpha Vantage, no IB connection
            # =====================================================================
            if analyze_only:
                return self._run_analyze_only_cycle(ticker)
            
            # =====================================================================
            # FULL EXECUTION MODE - Use IB for data and trading
            # =====================================================================
            
            # 1. Ensure IB connection
            if not self.ib_app.is_connected:
                logger.info("Connecting to IB for manual cycle...")
                self.ib_app.connect_and_start(
                    host=settings.ib_host,
                    port=settings.ib_port,
                    client_id=settings.ib_client_id
                )
            
            # 2. Get Portfolio State
            portfolio = self.ib_app.get_portfolio_snapshot()
            logger.info(f"Portfolio loaded: {len(portfolio.positions)} positions")
            
            # 3. Request real-time price for this ticker
            logger.info(f"Requesting market data for {ticker}...")
            self.ib_app.request_market_prices([ticker])
            
            # 4. EOD Safety Check (optional)
            if not skip_safety_checks:
                from src.config.market_calendar import get_current_et_time
                now_et = get_current_et_time()
                if now_et.time().hour == 15 and now_et.time().minute >= 55:
                    return ManualCycleResult(
                        ticker=ticker,
                        success=False,
                        indicators={},
                        recommendation=None,
                        ai_context={},
                        action_taken=None,
                        error="EOD Safety: Cannot run manual cycle after 3:55 PM ET",
                        portfolio_snapshot=portfolio.model_dump()
                    )
            
            # 5. Fetch Market Data (Alpha Vantage first, yfinance fallback - NEVER IB)
            history, quote = MarketDataManager.fetch_market_data(ticker, use_intraday=True)

            if not history:
                return ManualCycleResult(
                    ticker=ticker,
                    success=False,
                    indicators={},
                    recommendation=None,
                    ai_context={},
                    action_taken=None,
                    error=f"No market data found for {ticker}. Check if symbol is valid or API rate limit.",
                    portfolio_snapshot=portfolio.model_dump()
                )

            # 6. Calculate Indicators
            indicators = MarketDataManager.calculate_indicators(history)
            
            # Get REAL-TIME price and TODAY's OHLC from yfinance
            try:
                from src.utils.web_price_fetcher import WebPriceFetcher
                realtime_data = WebPriceFetcher.get_realtime_data(ticker)
                if realtime_data:
                    indicators['current_price'] = realtime_data['price']
                    indicators['open_price'] = realtime_data['open']
                    indicators['high'] = realtime_data['high']
                    indicators['low'] = realtime_data['low']
                    indicators['prev_close'] = realtime_data['prev_close']
                    indicators['volume'] = realtime_data['volume']
                    indicators['price_source'] = 'YFINANCE REALTIME'
                    if realtime_data['prev_close'] > 0:
                        indicators['day_change_pct'] = round(
                            ((realtime_data['price'] - realtime_data['prev_close']) / realtime_data['prev_close']) * 100, 2
                        )
                    logger.info(f"REALTIME {ticker}: ${realtime_data['price']:.2f} | Open: ${realtime_data['open']:.2f} | High: ${realtime_data['high']:.2f} | Low: ${realtime_data['low']:.2f}")
                else:
                    indicators['price_source'] = 'HISTORICAL'
                    logger.warning(f"yfinance realtime failed for {ticker}, using historical data")
            except Exception as e:
                indicators['price_source'] = 'HISTORICAL'
                logger.warning(f"WebPriceFetcher failed for {ticker}: {e}")
            
            logger.info(f"{ticker} | Price: ${indicators.get('current_price')} | RSI: {indicators.get('rsi')} | MACD: {indicators.get('macd_crossover')}")
            
            market_context = MarketDataManager.format_market_context(ticker, indicators)
            
            # 7. Check for existing position and TP/SL (optional)
            action_taken = None
            position = next((p for p in portfolio.positions if p.symbol == ticker and float(p.quantity) > 0), None)
            
            if position and not skip_safety_checks:
                current_price = float(indicators.get('current_price', 0))
                avg_cost = float(position.avg_cost)
                qty = float(position.quantity)
                
                if avg_cost > 0:
                    pnl_pct = ((current_price - avg_cost) / avg_cost) * 100
                    logger.info(f"Position P/L: {pnl_pct:.2f}% (Price: {current_price}, Cost: {avg_cost})")
                    
                    # Take Profit: +0.8%
                    if pnl_pct >= 0.8:
                        logger.info(f"SCALP TP HIT (+0.8%): Selling {qty} {ticker}")
                        order = orders.limit_order("SELL", qty, current_price)
                        if not settings.dry_run:
                            self.ib_app.place_trade(contract, order)
                        action_taken = f"AUTO TP: Sold {qty} @ ${current_price:.2f} (+{pnl_pct:.2f}%)"
                    
                    # Stop Loss: -0.4%
                    elif pnl_pct <= -0.4:
                        logger.warning(f"SCALP SL HIT (-0.4%): Selling {qty} {ticker}")
                        order = orders.market_order("SELL", qty)
                        if not settings.dry_run:
                            self.ib_app.place_trade(contract, order)
                        action_taken = f"AUTO SL: Sold {qty} @ MARKET ({pnl_pct:.2f}%)"
                    
                    if action_taken:
                        return ManualCycleResult(
                            ticker=ticker,
                            success=True,
                            indicators=indicators,
                            recommendation=None,
                            ai_context={"auto_action": True},
                            action_taken=action_taken,
                            portfolio_snapshot=portfolio.model_dump()
                        )
            
            # 8. Get AI Recommendation
            logger.info(f"Requesting AI recommendation for {ticker}...")
            recommendation, ai_context = self.openai_client.get_trading_recommendation(
                portfolio=portfolio,
                market_context=market_context,
                ticker=ticker
            )
            
            # 9. Execute trade
            if recommendation:
                action_taken = self.process_recommendation(recommendation, portfolio)
            
            # 10. Log to history
            self.cycle_logger.log_cycle(
                cycle_id=f"MANUAL-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                portfolio_snapshot=portfolio.model_dump(),
                ai_context=ai_context,
                recommendation=recommendation.model_dump() if recommendation else {},
                actions_taken=[action_taken] if action_taken else []
            )
            
            return ManualCycleResult(
                ticker=ticker,
                success=True,
                indicators=indicators,
                recommendation=recommendation,
                ai_context=ai_context,
                action_taken=action_taken,
                portfolio_snapshot=portfolio.model_dump()
            )
            
        except Exception as e:
            logger.error(f"Manual cycle error for {ticker}: {e}", exc_info=True)
            return ManualCycleResult(
                ticker=ticker,
                success=False,
                indicators={},
                recommendation=None,
                ai_context={},
                action_taken=None,
                error=str(e)
            )

    def _run_analyze_only_cycle(self, ticker: str) -> ManualCycleResult:
        """
        Run analysis-only cycle using Alpha Vantage data with yfinance fallback.
        Does NOT connect to Interactive Brokers.

        Args:
            ticker: Stock ticker symbol

        Returns:
            ManualCycleResult with analysis details
        """
        logger.info(f"Running ANALYZE ONLY cycle for {ticker} (Alpha Vantage + yfinance fallback)")

        try:
            # 1. Fetch market data using unified fetcher
            logger.info(f"Fetching market data for {ticker}...")
            history, quote = MarketDataManager.fetch_market_data(ticker, use_intraday=True)
            
            if not history:
                return ManualCycleResult(
                    ticker=ticker,
                    success=False,
                    indicators={},
                    recommendation=None,
                    ai_context={},
                    action_taken=None,
                    error=f"No market data found for {ticker}. Check if symbol is valid or API rate limit."
                )
            
            # 2. Calculate Indicators
            indicators = MarketDataManager.calculate_indicators(history)
            
            # Get REAL-TIME price and TODAY's OHLC from yfinance
            try:
                from src.utils.web_price_fetcher import WebPriceFetcher
                realtime_data = WebPriceFetcher.get_realtime_data(ticker)
                if realtime_data:
                    indicators['current_price'] = realtime_data['price']
                    indicators['open_price'] = realtime_data['open']
                    indicators['high'] = realtime_data['high']
                    indicators['low'] = realtime_data['low']
                    indicators['prev_close'] = realtime_data['prev_close']
                    indicators['volume'] = realtime_data['volume']
                    indicators['price_source'] = 'YFINANCE REALTIME'
                    if realtime_data['prev_close'] > 0:
                        indicators['day_change_pct'] = round(
                            ((realtime_data['price'] - realtime_data['prev_close']) / realtime_data['prev_close']) * 100, 2
                        )
                    logger.info(f"REALTIME {ticker}: ${realtime_data['price']:.2f} | Open: ${realtime_data['open']:.2f} | High: ${realtime_data['high']:.2f} | Low: ${realtime_data['low']:.2f}")
                else:
                    indicators['price_source'] = 'HISTORICAL'
                    logger.warning(f"yfinance realtime failed for {ticker}, using historical data")
            except Exception as e:
                indicators['price_source'] = 'HISTORICAL'
                logger.warning(f"WebPriceFetcher failed for {ticker}: {e}")
            
            logger.info(f"{ticker} | Price: ${indicators.get('current_price')} | RSI: {indicators.get('rsi')} | MACD: {indicators.get('macd_crossover')}")
            
            market_context = MarketDataManager.format_market_context(ticker, indicators)
            
            # 3. Create mock portfolio for AI context (no IB connection)
            from src.models.trading import AccountSummary, PortfolioSnapshot
            mock_portfolio = PortfolioSnapshot(
                account=AccountSummary(
                    account_id="ANALYZE_ONLY",
                    net_liquidation=0,
                    total_cash_value=0,
                    buying_power=0,
                ),
                positions=[]
            )
            
            # 4. Get AI Recommendation
            logger.info(f"Requesting AI recommendation for {ticker}...")
            recommendation, ai_context = self.openai_client.get_trading_recommendation(
                portfolio=mock_portfolio,
                market_context=market_context,
                ticker=ticker
            )
            
            # 5. Log to history
            self.cycle_logger.log_cycle(
                cycle_id=f"ANALYZE-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                portfolio_snapshot=mock_portfolio.model_dump(),
                ai_context=ai_context,
                recommendation=recommendation.model_dump() if recommendation else {},
                actions_taken=["ANALYZE ONLY - No IB connection"]
            )
            
            return ManualCycleResult(
                ticker=ticker,
                success=True,
                indicators=indicators,
                recommendation=recommendation,
                ai_context=ai_context,
                action_taken="ANALYZE ONLY - Data from Alpha Vantage",
                portfolio_snapshot=mock_portfolio.model_dump()
            )
            
        except Exception as e:
            logger.error(f"Analyze-only cycle error for {ticker}: {e}", exc_info=True)
            return ManualCycleResult(
                ticker=ticker,
                success=False,
                indicators={},
                recommendation=None,
                ai_context={},
                action_taken=None,
                error=str(e)
            )


# Singleton instance for UI to use
_trading_bot_instance: Optional[TradingBot] = None

def get_trading_bot() -> TradingBot:
    """
    Get or create the singleton TradingBot instance for UI use.
    
    Note: This creates the bot with init_scheduler=False to avoid
    signal handler issues when running from Streamlit threads.
    """
    global _trading_bot_instance
    if _trading_bot_instance is None:
        _trading_bot_instance = TradingBot(init_scheduler=False)
    return _trading_bot_instance


if __name__ == "__main__":
    bot = TradingBot()
    bot.start()
