"""Trading-mode endpoints + emergency kill switch.

Switching to LIVE requires ``confirm_live=true`` AND a tradable broker session.
The emergency stop forces SHADOW and raises a session lockout immediately.
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.enums import TradingMode
from app.runtime import get_runtime

router = APIRouter(prefix="/api/mode", tags=["mode"])


class SwitchModeRequest(BaseModel):
    mode: TradingMode
    confirm_live: bool = False


@router.get("")
async def get_mode() -> dict:
    rt = get_runtime()
    return {
        "mode": rt.mode_manager.mode.value,
        "locked_out": rt.mode_manager.locked_out,
        "lockout_reason": rt.mode_manager.lockout_reason,
    }


@router.post("/switch")
async def switch_mode(req: SwitchModeRequest) -> dict:
    rt = get_runtime()
    broker_status = await rt.mode_manager.broker.status()
    result = await rt.mode_manager.switch_mode(
        req.mode, confirm_live=req.confirm_live, broker_status=broker_status
    )
    return {"ok": result.ok, "mode": result.mode.value, "reason": result.reason}


@router.post("/emergency-stop")
async def emergency_stop() -> dict:
    """Kill switch: flatten open position, force Shadow + session lockout."""
    rt = get_runtime()
    await rt.execution.emergency_close()
    await rt.mode_manager.force_safe_mode("manual emergency stop")
    await rt.journal.record_async("LOCKOUT", {"reason": "manual emergency stop"})
    return {"ok": True, "mode": rt.mode_manager.mode.value, "locked_out": True}


@router.post("/clear-lockout")
async def clear_lockout() -> dict:
    rt = get_runtime()
    rt.mode_manager.clear_lockout()
    return {"ok": True, "locked_out": rt.mode_manager.locked_out}
