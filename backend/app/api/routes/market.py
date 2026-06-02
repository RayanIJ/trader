"""Market-regime endpoint.

Exposes the cross-asset confirmation view (SPX/SPY/QQQ/SMH/SOXX + VIX) from the
latest scan. Purely descriptive context for the dashboard.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.runtime import get_runtime

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/regime")
async def regime() -> dict:
    rt = get_runtime()
    if rt.latest_scan is None:
        result = await rt.run_scan()
        return result.regime.to_dict()
    return rt.latest_scan.regime.to_dict()


@router.get("/universe")
async def universe() -> dict:
    rt = get_runtime()
    uni = rt.config.universe
    return {
        "index_symbols": uni.index_symbols,
        "semiconductor_symbols": uni.semiconductor_symbols,
        "sector_etfs": uni.sector_etfs,
        "market_confirmation": uni.market_confirmation,
        "tech_confirmation": uni.tech_confirmation,
        "volatility_proxy": uni.volatility_proxy,
        "tradable": uni.all_tradable,
    }
