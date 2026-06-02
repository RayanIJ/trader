"""
Contract factory helpers for IB API.
"""
from ibapi.contract import Contract

def us_stock_contract(symbol: str) -> Contract:
    """Create a US Stock Contract for SMART routing."""
    contract = Contract()
    contract.symbol = symbol.upper()
    contract.secType = "STK"
    contract.currency = "USD"
    contract.exchange = "SMART"
    return contract

def us_option_contract(symbol: str, expiry: str, strike: float, right: str) -> Contract:
    """Create a US Equity Option Contract."""
    contract = Contract()
    contract.symbol = symbol.upper()
    contract.secType = "OPT"
    contract.exchange = "SMART"
    contract.currency = "USD"
    contract.lastTradeDateOrContractMonth = expiry
    contract.strike = strike
    contract.right = right  # "C" for Call, "P" for Put
    contract.multiplier = "100"
    return contract
