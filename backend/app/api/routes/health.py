"""Health + status endpoints powering the System Health dashboard panel."""
from __future__ import annotations

from fastapi import APIRouter

from app.runtime import get_runtime

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness probe for the backend process itself."""
    return {"status": "ok"}


@router.get("/api/health")
async def health() -> dict:
    """Full aggregated system-health report (broker, data, db, clock)."""
    rt = get_runtime()
    broker_status, report = await rt.refresh_status()
    return {
        "mode": rt.mode_manager.mode.value,
        "locked_out": rt.mode_manager.locked_out,
        "lockout_reason": rt.mode_manager.lockout_reason,
        "health": report.to_dict(),
        "broker": {
            "gateway_reachable": broker_status.gateway_reachable,
            "session_connected": broker_status.session_connected,
            "account_available": broker_status.account_available,
            "data_feed": broker_status.data_feed.value,
            "is_tradable": broker_status.is_tradable,
            "last_error": broker_status.last_error,
        },
    }
