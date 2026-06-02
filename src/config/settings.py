"""
Application settings loaded from environment variables.
"""
import os
from typing import Optional
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

# Load .env file from project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Settings(BaseSettings):
    """Application configuration from environment variables."""
    
    # IB Gateway/TWS Connection
    ib_host: str = Field(default="127.0.0.1", alias="IB_HOST")
    ib_port: int = Field(default=7497, alias="IB_PORT")  # 7497=paper, 7496=live
    ib_client_id: int = Field(default=1, alias="IB_CLIENT_ID")
    ib_account: Optional[str] = Field(default=None, alias="IB_ACCOUNT")
    
    # AI Provider
    openai_api_key: str = Field(alias="OPENAI_API_KEY")
    use_mock_ai: bool = Field(default=False, alias="USE_MOCK_AI")
    
    # Market Data
    alpha_vantage_api_key: Optional[str] = Field(default=None, alias="ALPHA_VANTAGE_API_KEY")
    
    # IB Credentials (for Gateway Container)
    tws_userid: Optional[str] = Field(default=None, alias="TWS_USERID")
    tws_password: Optional[str] = Field(default=None, alias="TWS_PASSWORD")

    # Trading Settings
    dry_run: bool = Field(default=True, alias="DRY_RUN")
    max_dollars_per_trade: float = Field(default=1000.0, alias="MAX_DOLLARS_PER_TRADE")
    confidence_threshold: float = Field(default=0.7, alias="CONFIDENCE_THRESHOLD")
    trading_interval_seconds: int = Field(default=60, alias="TRADING_INTERVAL_SECONDS")
    news_refresh_minutes: int = Field(default=30, alias="NEWS_REFRESH_MINUTES")
    
    # Strategy Config
    trading_strategy: Optional[str] = Field(default=None, alias="TRADING_STRATEGY")
    exit_strategy: Optional[str] = Field(default=None, alias="EXIT_STRATEGY")
    target_tickers: Optional[str] = Field(default=None, alias="TARGET_TICKERS")
    strategy_context: Optional[str] = Field(default=None, alias="STRATEGY_CONTEXT")
    
    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        populate_by_name = True
        extra = "ignore"


# Singleton instance
settings = Settings()
