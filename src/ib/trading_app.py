"""
IB Trading Application wrapper using EClient and EWrapper.
Handles connection, data retrieval, and order operations.
"""
import sys
import queue
import time
import logging
from threading import Thread
from typing import Dict, List, Optional
from decimal import Decimal

# Add IB SDK to path
sys.path.insert(0, 'IB.1037.02/IBJts/source/pythonclient')

from src.ib import contracts

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.common import OrderId, TickerId

from src.models.trading import Position, AccountSummary, PortfolioSnapshot
from src.config.settings import settings

logger = logging.getLogger(__name__)

class TradingApp(EWrapper, EClient):
    """
    Main IB Application class.
    Inherits from EWrapper (callbacks) and EClient (requests).
    """
    def __init__(self):
        EClient.__init__(self, self)
        
        # Connection state
        self.next_valid_order_id = None
        self.is_connected = False
        self.msg_queue = queue.Queue()
        
        # Portfolio data store
        self.positions: Dict[str, Position] = {}
        self.account_summary: Dict[str, str] = {}
        self.account_id = None
        
        # Synchronization events
        self._positions_event = threading.Event()
        self._summary_event = threading.Event()
        
        # Historical Data state
        self.historical_data = {} # reqId -> List[dict]
        self._history_events = {} # reqId -> threading.Event()
        
        # Market Data (real-time prices)
        self._market_prices = {}  # symbol -> price
        self._price_req_map = {}  # reqId -> symbol
        self._price_events = {}   # symbol -> threading.Event()
        
        # Open Orders tracking
        self._open_orders = {}  # orderId -> {symbol, action, quantity, order_type, limit_price, status}
        self._open_orders_event = threading.Event()
        
        self.thread = None

    def connect_and_start(self, host: str, port: int, client_id: int):
        """Connect to IB and start the message loop thread."""
        # DEBUG: Verify types and raw connectivity
        logger.info(f"DEBUG: Host type: {type(host)}, Port type: {type(port)}")
        import socket
        try:
            s = socket.socket()
            s.settimeout(2)
            s.connect((host, port))
            logger.info("DEBUG: Raw socket connection SUCCESS")
            s.close()
        except Exception as e:
            logger.error(f"DEBUG: Raw socket connection FAILED: {e}")

        # Retry loop for connection
        max_retries = 30
        for i in range(max_retries):
            try:
                if not self.isConnected():
                    self.connect(host, port, client_id)
                    
                    # Launch the message loop thread
                    if self.thread is None or not self.thread.is_alive():
                        self.thread = Thread(target=self.run, daemon=True)
                        self.thread.start()
            except Exception as e:
                logger.warning(f"Connection attempt {i+1} failed: {e}")

            # Wait for connection ack (nextValidId sets is_connected=True)
            # We check in short bursts to allow early exit
            for _ in range(20): # 2 seconds wait per attempt
                if self.is_connected:
                    break
                time.sleep(0.1)
                
            if self.is_connected:
                logger.info("Connected to IB!")
                break
                
            logger.info(f"Waiting for IB Gateway... ({i+1}/{max_retries})")
            
        if not self.is_connected:
            raise ConnectionError("Timeout waiting for IB connection after multiple retries")

    # --------------------------------------------------------------------------
    # EWrapper Callback Overrides
    # --------------------------------------------------------------------------
    
    def error(self, reqId: TickerId, errorTime: int, errorCode: int, errorString: str, advancedOrderRejectJson=""):
        """Handle errors."""
        # Log common notification codes as info, actual errors as error
        if errorCode in [2104, 2106, 2158]:
            logger.info(f"IB Info: {errorCode} - {errorString}")
        elif errorCode == 10089:
            logger.warning(f"IB Error {errorCode}: Real-time data unavailable. Switching to Delayed Data (Type 3).")
            # Switch to delayed data
            self.reqMarketDataType(3)
            
            # Re-request the specific ticker that failed
            if reqId in self._price_req_map:
                symbol = self._price_req_map[reqId]
                logger.info(f"Attempting to re-request Delayed Data for {symbol} (reqId={reqId})...")
                contract = contracts.us_stock_contract(symbol)
                self.reqMktData(reqId, contract, "", False, False, [])
        else:
            logger.error(f"IB Error: {reqId} {errorCode} {errorString}")

    def nextValidId(self, orderId: int):
        """Receive next valid order ID on connection."""
        super().nextValidId(orderId)
        self.next_valid_order_id = orderId
        self.is_connected = True
        logger.info(f"Next Valid Order ID: {orderId}")

    # --- Position Callbacks ---

    def position(self, account: str, contract: Contract, position: Decimal, avgCost: float):
        """Handle position data."""
        super().position(account, contract, position, avgCost)
        
        # Get multiplier (default 1.0 for stocks, 100 for many options)
        multiplier = 1.0
        try:
            if contract.multiplier and str(contract.multiplier).strip():
                multiplier = float(contract.multiplier)
        except (ValueError, TypeError):
            pass

        pos = Position(
            con_id=contract.conId,
            symbol=contract.symbol,
            sec_type=contract.secType,
            primary_exchange=contract.primaryExchange or contract.exchange,
            quantity=position,
            avg_cost=avgCost,
            multiplier=multiplier,
            cost_basis=float(position) * avgCost * multiplier
        )
        # Use conId as unique key instead of symbol
        self.positions[contract.conId] = pos
        logger.info(f"Position [{contract.conId}]: {contract.symbol} ({contract.secType}) {position} @ ${avgCost:.2f} (mult: {multiplier})")

    def updatePortfolio(self, contract: Contract, position: Decimal, marketPrice: float, marketValue: float, averageCost: float, unrealizedPNL: float, realizedPNL: float, accountName: str):
        """Handle portfolio updates (with market value and PNL)."""
        super().updatePortfolio(contract, position, marketPrice, marketValue, averageCost, unrealizedPNL, realizedPNL, accountName)
        
        # Update our positions store using conId lookup
        if contract.conId in self.positions:
            pos = self.positions[contract.conId]
            pos.market_price = marketPrice
            pos.market_value = marketValue
            pos.unrealized_pnl = unrealizedPNL
            pos.realized_pnl = realizedPNL
            logger.debug(f"Updated Portfolio for {contract.symbol} (conId:{contract.conId}): MktVal=${marketValue:.2f}, PnL=${unrealizedPNL:.2f}")

    def positionEnd(self):
        """End of position download."""
        super().positionEnd()
        self._positions_event.set()
        logger.info("Position download complete")

    # --- Account Summary Callbacks ---

    def accountSummary(self, reqId: int, account: str, tag: str, value: str, currency: str):
        """Handle account summary data."""
        super().accountSummary(reqId, account, tag, value, currency)
        self.account_id = account
        self.account_summary[tag] = value
        
    def accountSummaryEnd(self, reqId: int):
        """End of account summary download."""
        super().accountSummaryEnd(reqId)
        self._summary_event.set()
        logger.info("Account summary download complete")

    # --- Market Data Callbacks ---

    def tickPrice(self, reqId, tickType, price, attrib):
        """Handle real-time and delayed price ticks."""
        super().tickPrice(reqId, tickType, price, attrib)
        # tickType 4 = Last price (real-time)
        # tickType 68 = Delayed Last price
        # tickType 1 = Bid, 2 = Ask, 66 = Delayed Bid, 67 = Delayed Ask
        if tickType in [4, 68] and price > 0:  # Last price (real-time or delayed)
            symbol = self._price_req_map.get(reqId)
            if symbol:
                self._market_prices[symbol] = price
                if symbol in self._price_events:
                    self._price_events[symbol].set()
                delayed_tag = " (delayed)" if tickType == 68 else ""
                logger.info(f"Market price for {symbol}: ${price:.2f}{delayed_tag}")

    # --- Order Status Callbacks ---

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        """Handle order status updates."""
        super().orderStatus(orderId, status, filled, remaining, avgFillPrice, permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice)
        logger.info(f"Order Status {orderId}: {status}, Filled: {filled}, Remaining: {remaining}")
        
        # Update open orders tracking
        if orderId in self._open_orders:
            self._open_orders[orderId]['status'] = status
            self._open_orders[orderId]['filled'] = filled
            self._open_orders[orderId]['remaining'] = remaining
            self._open_orders[orderId]['avg_fill_price'] = avgFillPrice
            
            # Remove completed orders
            if status in ['Filled', 'Cancelled', 'Inactive']:
                logger.info(f"Order {orderId} completed with status {status}, removing from open orders")
                del self._open_orders[orderId]

    def openOrder(self, orderId, contract, order, orderState):
        """Handle open order info."""
        super().openOrder(orderId, contract, order, orderState)
        logger.info(f"Open Order {orderId}: {contract.symbol} {order.action} {order.totalQuantity} @ {order.lmtPrice} [{orderState.status}]")
        
        # Store open order
        self._open_orders[orderId] = {
            'order_id': orderId,
            'symbol': contract.symbol,
            'action': order.action,
            'quantity': order.totalQuantity,
            'order_type': order.orderType,
            'limit_price': order.lmtPrice if order.orderType == 'LMT' else None,
            'stop_price': order.auxPrice if order.orderType in ['STP', 'STP LMT'] else None,
            'status': orderState.status,
            'filled': 0,
            'remaining': order.totalQuantity,
            'avg_fill_price': 0.0
        }
    
    def openOrderEnd(self):
        """Called when all open orders have been received."""
        super().openOrderEnd()
        logger.info(f"Open orders received: {len(self._open_orders)} pending orders")
        self._open_orders_event.set()

    # --- Historical Data Callbacks ---

    def historicalData(self, reqId: int, bar):
        """Handle historical data bars."""
        if reqId not in self.historical_data:
            self.historical_data[reqId] = []
        
        self.historical_data[reqId].append({
            "date": bar.date,
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "barCount": bar.barCount,
            "average": bar.wap
        })

    def historicalDataEnd(self, reqId: int, start: str, end: str):
        """End of historical data."""
        super().historicalDataEnd(reqId, start, end)
        if reqId in self._history_events:
            self._history_events[reqId].set()

    # --------------------------------------------------------------------------
    # Public Methods
    # --------------------------------------------------------------------------

    def get_portfolio_snapshot(self) -> PortfolioSnapshot:
        """Fetch current portfolio state synchronously."""
        # 1. Clear old data
        self.positions.clear()
        self.account_summary.clear()
        self._positions_event.clear()
        self._summary_event.clear()
        
        # 2. Request new data
        self.account_id = settings.ib_account # Ensure we have account ID
        self.reqPositions()
        # Tags: NetLiquidation, TotalCashValue, BuyingPower, GrossPositionValue
        self.reqAccountSummary(9001, "All", "NetLiquidation,TotalCashValue,BuyingPower,GrossPositionValue")
        
        # Request account updates to get MarketPrice, MarketValue, and PNL for positions
        if self.account_id:
            self.reqAccountUpdates(True, self.account_id)
        
        # 3. Wait for data
        self._positions_event.wait(timeout=3)
        self._summary_event.wait(timeout=3)
        
        # Give a small buffer for updatePortfolio callbacks to stream in
        time.sleep(1.0)
        
        # Stop account updates to avoid flooding after we have what we need
        if self.account_id:
            self.reqAccountUpdates(False, self.account_id)
        
        # 4. Build snapshot model
        summary = AccountSummary(
            account_id=self.account_id or "Unknown",
            net_liquidation=float(self.account_summary.get("NetLiquidation", 0)),
            total_cash_value=float(self.account_summary.get("TotalCashValue", 0)),
            buying_power=float(self.account_summary.get("BuyingPower", 0)),
            gross_position_value=float(self.account_summary.get("GrossPositionValue", 0)),
        )
        
        # 5. Build list from cache (now enriched by updatePortfolio)
        return PortfolioSnapshot(
            account=summary,
            positions=list(self.positions.values())
        )
    
    def get_open_orders(self) -> List[Dict]:
        """Fetch all open/pending orders from IB."""
        # Clear and request fresh open orders
        self._open_orders.clear()
        self._open_orders_event.clear()
        
        self.reqAllOpenOrders()
        
        # Wait for response (timeout 3s)
        self._open_orders_event.wait(timeout=3)
        
        return list(self._open_orders.values())
    
    def has_pending_order_for(self, symbol: str, action: str = None) -> bool:
        """
        Check if there's already a pending order for a symbol.
        
        Args:
            symbol: Ticker symbol to check
            action: Optional action filter ('BUY' or 'SELL')
        
        Returns:
            True if a pending order exists for this symbol
        """
        for order in self._open_orders.values():
            if order['symbol'] == symbol:
                if action is None or order['action'] == action:
                    return True
        return False
    
    def get_pending_order_symbols(self) -> List[str]:
        """Get list of symbols with pending orders."""
        return list(set(order['symbol'] for order in self._open_orders.values()))

    def get_historical_data(self, contract: Contract, duration: str = "2 D", bar_size: str = "5 mins") -> List[Dict]:
        """Fetch historical data for a contract."""
        if not self.is_connected or self.next_valid_order_id is None:
            raise RuntimeError("Not connected to IB")
            
        req_id = self.next_valid_order_id
        self.next_valid_order_id += 1
        
        # Setup event and storage
        event = threading.Event()
        self._history_events[req_id] = event
        self.historical_data[req_id] = []
        
        # Request data
        # whatToShow='TRADES', useRTH=1, formatDate=1
        self.reqHistoricalData(req_id, contract, "", duration, bar_size, "TRADES", 1, 1, False, [])
        
        # Wait
        if not event.wait(timeout=10):
            logger.warning(f"Timeout waiting for historical data for {contract.symbol}")
            return []
            
        # Cleanup
        data = self.historical_data.pop(req_id, [])
        self._history_events.pop(req_id, None)
        
        return data

    def request_market_prices(self, symbols: List[str]):
        """Request real-time market data for given symbols."""
        from src.ib import contracts
        
        # Request real-time data (type 1) for live accounts
        # Type 1 = Live, Type 2 = Frozen, Type 3 = Delayed, Type 4 = Delayed Frozen
        self.reqMarketDataType(1)  # Request LIVE real-time data
        logger.info("Requesting REAL-TIME market data")
        
        for symbol in symbols:
            if symbol in self._market_prices:
                continue  # Already have data
                
            req_id = self.next_valid_order_id
            self.next_valid_order_id += 1
            
            self._price_req_map[req_id] = symbol
            self._price_events[symbol] = threading.Event()
            
            contract = contracts.us_stock_contract(symbol)
            # Request streaming data (snapshot=False)
            self.reqMktData(req_id, contract, "", False, False, [])
            logger.info(f"Requested REAL-TIME STREAMING data for {symbol} (reqId={req_id})")
        
        # Wait briefly for first tick
        import time
        time.sleep(2)

    def get_live_price(self, symbol: str) -> Optional[float]:
        """Get the latest real-time price for a symbol. 
        Falls back to 5-second historical bar snapshot if streaming is unavailable (Error 10089).
        """
        # 1. Try streaming cache first
        price = self._market_prices.get(symbol)
        if price:
            return price
            
        # 2. Fallback: Request micro-history (last 60s, 5s bars)
        # This often works even when streaming is restricted
        try:
            from src.ib import contracts
            contract = contracts.us_stock_contract(symbol)
            
            # Fetch last 60 seconds in 5-second chunks
            history = self.get_historical_data(contract, duration="60 S", bar_size="5 secs")
            
            if history:
                latest_bar = history[-1]
                close_price = latest_bar.get('close')
                if close_price:
                    logger.info(f"Fetched micro-history snapshot for {symbol}: ${close_price}")
                    self._market_prices[symbol] = close_price # Cache it
                    return close_price
        except Exception as e:
            logger.warning(f"Failed to fetch real-time snapshot for {symbol}: {e}")
            
        # 3. Fallback: Web Search (Ultimate Failover)
        try:
            from src.utils.web_price_fetcher import WebPriceFetcher
            web_price = WebPriceFetcher.get_price(symbol)
            if web_price:
                logger.info(f"Fetched REAL-TIME WEB PRICE for {symbol}: ${web_price}")
                self._market_prices[symbol] = web_price
                return web_price
        except ImportError:
            logger.warning("WebPriceFetcher not available (missing dependency?)")
        except Exception as e:
            logger.error(f"Web price fetch failed: {e}")
            
        return None

    def place_trade(self, contract: Contract, order: Order) -> int:
        """Place an order and return the order ID."""
        if not self.is_connected or self.next_valid_order_id is None:
            raise RuntimeError("Not connected to IB")
            
        oid = self.next_valid_order_id
        self.next_valid_order_id += 1
        
        self.placeOrder(oid, contract, order)
        logger.info(f"Placed order {oid}: {order.action} {order.totalQuantity} {contract.symbol}")
        return oid

import threading
