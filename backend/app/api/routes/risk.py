"""Risk + macro status endpoints for the dashboard."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.macro.store import add_event, list_events, refresh_guard
from app.runtime import get_runtime

router = APIRouter(tags=["risk"])


@router.get("/api/risk/status")
async def risk_status() -> dict:
    rt = get_runtime()
    cfg = rt.config
    behavior = rt.risk_engine.behavior_governor.evaluate(rt.day_state)
    return {
        "day": rt.day_state.to_dict(cfg.risk.max_daily_loss_usd),
        "behavior": behavior.to_dict(),
        "macro": rt.macro_guard.status().to_dict(),
    }


@router.get("/api/macro/status")
async def macro_status() -> dict:
    rt = get_runtime()
    return rt.macro_guard.status().to_dict()


class MacroEventBody(BaseModel):
    name: str = Field(min_length=1, max_length=48)
    event_time: datetime
    impact: str = "HIGH"
    block_minutes_before: int | None = None
    block_minutes_after: int | None = None


@router.get("/api/macro/events")
async def macro_events(limit: int = 20) -> dict:
    return {"events": list_events(limit=limit)}


@router.post("/api/macro/events")
async def create_macro_event(body: MacroEventBody) -> dict:
    rt = get_runtime()
    event = add_event(
        name=body.name,
        event_time=body.event_time,
        impact=body.impact,
        block_minutes_before=body.block_minutes_before,
        block_minutes_after=body.block_minutes_after,
    )
    refresh_guard(rt.macro_guard)
    await rt.journal.record_async("MACRO", event)
    return {"ok": True, "event": event}
