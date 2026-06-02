"""Execution status + automation controls."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.enums import ExitReason
from app.runtime import get_runtime

router = APIRouter(prefix="/api/execution", tags=["execution"])


class AutomationBody(BaseModel):
    enabled: bool


@router.get("/status")
async def status() -> dict:
    rt = get_runtime()
    snap = rt.execution.snapshot
    pos = rt.position_manager.position
    mark = None
    if pos and rt.latest_scan:
        from app.core.enums import OptionRight

        right = OptionRight.CALL if pos.right in ("C", "CALL") else OptionRight.PUT
        q = await rt.market_data.get_option_quote(pos.underlying, pos.expiry, pos.strike, right)
        if q:
            mark = q.bid or q.ask or q.last
    return {
        **snap.to_dict(),
        "active_position": pos.to_dict(mark=mark) if pos and mark else (pos.to_dict() if pos else None),
        "automation_enabled": rt.execution.enabled,
    }


@router.post("/automation")
async def set_automation(body: AutomationBody) -> dict:
    rt = get_runtime()
    rt.execution.set_enabled(body.enabled)
    return {"ok": True, "enabled": rt.execution.enabled}


@router.post("/emergency-close")
async def emergency_close() -> dict:
    rt = get_runtime()
    await rt.execution.emergency_close(ExitReason.MANUAL_EMERGENCY)
    await rt.mode_manager.force_safe_mode("manual emergency close")
    await rt.journal.record_async("LOCKOUT", {"reason": "manual emergency close"})
    return {"ok": True}
