"""
Pydantic models for trading recommendations and portfolio data.
"""
from enum import Enum
from typing import Optional, List
from decimal import Decimal
from datetime import datetime
from pydantic import BaseModel, Field


class TradeAction(str, Enum):
    """Trading action types."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class OrderType(str, Enum):
    """Supported order types."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class TradingRecommendation(BaseModel):
    """
    AI-generated trading recommendation.
    This model is used as the response schema for OpenAI API.
    """
    action: TradeAction = Field(
        description="The recommended trading action: BUY, SELL, or HOLD"
    )
    symbol: str = Field(
        description="The stock ticker symbol (e.g., AAPL, GOOGL)"
    )
    quantity: int = Field(
        default=0,
        ge=0,
        description="Number of shares to trade"
    )
    order_type: OrderType = Field(
        default=OrderType.LIMIT,
        description="Type of order to place (LIMIT preferred)"
    )
    limit_price: Optional[float] = Field(
        default=None,
        description="Limit price for LIMIT or STOP_LIMIT orders"
    )
    stop_price: Optional[float] = Field(
        default=None,
        description="Stop price for STOP or STOP_LIMIT orders"
    )
    reasoning: str = Field(
        default="No reasoning provided",
        description="Detailed rationale tying data and indicators to the decision"
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="Confidence level from 0.0 to 1.0"
    )
    market_regime: str = Field(
        default="Unknown",
        description="Summary of index trend, volatility and sector strength"
    )
    news_catalysts: Optional[List[str]] = Field(
        default=None,
        description="Key news or catalysts identified"
    )
    risk_level: str = Field(
        default="Medium",
        description="Low, Medium, or High"
    )
    target_price: Optional[float] = Field(
        default=None,
        description="Take profit target"
    )
    setup: Optional[str] = Field(
        default="NO_SETUP",
        description="Setup type: VWAP_CONTINUATION, VWAP_RECLAIM, VWAP_REJECT, OVERSOLD_BOUNCE, OVERBOUGHT_FADE, MOMENTUM_SURGE, NO_SETUP"
    )
    invalidation_condition: Optional[str] = Field(
        default=None,
        description="Condition that invalidates this trade setup"
    )
    
    @classmethod
    def model_validate(cls, obj, *args, **kwargs):
        """Override to apply defaults for None values."""
        if isinstance(obj, dict):
            # Replace None with defaults for key fields
            if obj.get('risk_level') is None:
                obj['risk_level'] = "Medium"
            if obj.get('market_regime') is None:
                obj['market_regime'] = "Unknown"
            if obj.get('reasoning') is None:
                obj['reasoning'] = "No reasoning provided"
            if obj.get('quantity') is None:
                obj['quantity'] = 0
        return super().model_validate(obj, *args, **kwargs)


class Position(BaseModel):
    """Represents a portfolio portfolio position."""
    con_id: Optional[int] = None
    symbol: str
    sec_type: str = "STK"
    primary_exchange: Optional[str] = None
    quantity: Decimal
    avg_cost: float
    multiplier: float = 1.0
    market_price: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    realized_pnl: Optional[float] = None
    cost_basis: Optional[float] = None


class AccountSummary(BaseModel):
    """Account summary information."""
    account_id: str
    net_liquidation: Optional[float] = None
    total_cash_value: Optional[float] = None
    buying_power: Optional[float] = None
    gross_position_value: Optional[float] = None
    available_funds: Optional[float] = None
    currency: str = "USD"


class PortfolioSnapshot(BaseModel):
    """Complete portfolio snapshot for AI context."""
    timestamp: datetime = Field(default_factory=datetime.now)
    account: AccountSummary
    positions: List[Position] = []
    
    def to_context_string(self) -> str:
        """Convert portfolio to a string for AI prompt context."""
        lines = [
            f"Portfolio Snapshot at {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Account: {self.account.account_id}",
            f"Net Liquidation: ${self.account.net_liquidation:,.2f}" if self.account.net_liquidation else "",
            f"Cash Available: ${self.account.total_cash_value:,.2f}" if self.account.total_cash_value else "",
            f"Buying Power: ${self.account.buying_power:,.2f}" if self.account.buying_power else "",
            "",
            "Current Positions:",
        ]
        
        if not self.positions:
            lines.append("  No open positions")
        else:
            for pos in self.positions:
                pnl_str = f", P&L: ${pos.unrealized_pnl:,.2f}" if pos.unrealized_pnl else ""
                lines.append(
                    f"  {pos.symbol}: {pos.quantity} shares @ ${pos.avg_cost:.2f}{pnl_str}"
                )
        
        return "\n".join(line for line in lines if line is not None)


class OrderResult(BaseModel):
    """Result of an order execution attempt."""
    success: bool
    order_id: Optional[int] = None
    symbol: str
    action: str
    quantity: int
    order_type: str
    status: str = "PENDING"
    filled_quantity: int = 0
    avg_fill_price: Optional[float] = None
    error_message: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)
