"""Market-data source factory.

Selects the concrete :class:`MarketDataSource` from config. ``simulated`` is the
default (offline, deterministic, testable); ``tws`` ingests live candles, quotes,
and option chains from TWS/IB Gateway. The TWS source is imported lazily so the
backend boots without ibapi when running simulated.
"""
from __future__ import annotations

from app.config.schema import AppConfig
from app.market_data.simulated import SimulatedMarketDataSource
from app.market_data.source import MarketDataSource


def make_market_data_source(cfg: AppConfig) -> MarketDataSource:
    source = cfg.market_data.source
    if source == "tws":
        from app.market_data.tws_source import TwsMarketDataSource

        return TwsMarketDataSource(cfg.broker, cfg.market_data)
    return SimulatedMarketDataSource(seed=cfg.market_data.simulated_seed)
