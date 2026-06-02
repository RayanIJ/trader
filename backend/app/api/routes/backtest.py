"""Backtest / replay API."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.backtest.engine import BacktestEngine
from app.runtime import get_runtime

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    seed: int = 1337
    steps: int = Field(default=12, ge=1, le=120)
    interval_minutes: int = Field(default=5, ge=1, le=60)


@router.post("/run")
async def run_backtest(body: BacktestRequest) -> dict:
    rt = get_runtime()
    engine = BacktestEngine(rt.config)
    result = await engine.run(
        seed=body.seed,
        steps=body.steps,
        interval_minutes=body.interval_minutes,
    )
    await rt.journal.record_async(
        "BACKTEST",
        result.to_dict(),
    )
    return result.to_dict()
