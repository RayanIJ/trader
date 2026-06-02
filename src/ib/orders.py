"""
Order factory helpers for IB API.
"""
from ibapi.order import Order

def market_order(action: str, quantity: int, outside_rth: bool = False) -> Order:
    """Create a Market Order."""
    order = Order()
    order.action = action.upper()  # BUY, SELL
    order.orderType = "MKT"
    order.totalQuantity = float(quantity)
    order.outsideRth = outside_rth
    return order

def limit_order(action: str, quantity: int, limit_price: float) -> Order:
    """Create a Limit Order."""
    order = Order()
    order.action = action.upper()
    order.orderType = "LMT"
    order.totalQuantity = float(quantity)
    order.lmtPrice = limit_price
    return order

def stop_order(action: str, quantity: int, stop_price: float) -> Order:
    """Create a Stop Order."""
    order = Order()
    order.action = action.upper()
    order.orderType = "STP"
    order.totalQuantity = float(quantity)
    order.auxPrice = stop_price  # Stop price
    return order

def stop_limit_order(action: str, quantity: int, limit_price: float, stop_price: float) -> Order:
    """Create a Stop-Limit Order."""
    order = Order()
    order.action = action.upper()
    order.orderType = "STP LMT"
    order.totalQuantity = float(quantity)
    order.lmtPrice = limit_price
    order.auxPrice = stop_price
    return order
