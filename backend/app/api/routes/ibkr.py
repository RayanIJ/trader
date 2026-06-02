"""IBKR (TWS socket) connectivity endpoints.

Connect/disconnect are explicit user actions. Authentication is NOT assumed to
be automatable: if TWS/Gateway isn't running or isn't logged in, the status
clearly reflects that and trading stays blocked.
"""
from __future__ import annotations

from fastapi import APIRouter
from app.core.logging import mask_account
from app.runtime import get_runtime

router = APIRouter(prefix="/api/ibkr", tags=["ibkr"])


@router.post("/connect")
async def connect() -> dict:
    rt = get_runtime()
    status = await rt.mode_manager.broker.connect()
    # Once the user connects, keep the session alive (auto-reconnect on drop).
    if status.session_connected:
        rt.mark_connected()
    _, report = await rt.refresh_status()
    return {
        "gateway_reachable": status.gateway_reachable,
        "session_connected": status.session_connected,
        "account_available": status.account_available,
        "data_feed": status.data_feed.value,
        "is_tradable": status.is_tradable,
        "last_error": status.last_error,
        "health": report.to_dict(),
    }


@router.post("/disconnect")
async def disconnect() -> dict:
    rt = get_runtime()
    rt.mark_disconnected()  # explicit user disconnect: stop auto-reconnect
    await rt.mode_manager.broker.disconnect()
    return {"ok": True}


@router.get("/status")
async def status() -> dict:
    rt = get_runtime()
    status = await rt.mode_manager.broker.status()
    return {
        "mode": rt.mode_manager.mode.value,
        "gateway_reachable": status.gateway_reachable,
        "session_connected": status.session_connected,
        "next_valid_id_received": status.next_valid_id_received,
        "account_available": status.account_available,
        "data_feed": status.data_feed.value,
        "market_data_type": status.market_data_type,
        "is_tradable": status.is_tradable,
        "last_error": status.last_error,
    }


@router.get("/account")
async def account() -> dict:
    rt = get_runtime()
    summary = await rt.mode_manager.broker.account_summary()
    if summary.get("account_id"):
        summary["account_id_masked"] = mask_account(summary["account_id"])
        # Never leak the raw account id to the browser.
        summary.pop("account_id", None)
    return summary


@router.get("/positions")
async def positions() -> dict:
    rt = get_runtime()
    return {"positions": await rt.mode_manager.broker.positions()}
