"""Scanner endpoints.

The scanner runs continuously in the runtime poll loop and pushes results over
the WebSocket (topic ``scanner``). These endpoints expose the latest cached scan
and a manual trigger for an immediate rescan.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.runtime import get_runtime

router = APIRouter(prefix="/api/scanner", tags=["scanner"])


@router.get("")
async def latest() -> dict:
    rt = get_runtime()
    if rt.latest_scan is None:
        result = await rt.run_scan()
        return result.to_dict()
    return rt.latest_scan.to_dict()


@router.post("/scan")
async def scan_now() -> dict:
    rt = get_runtime()
    result = await rt.run_scan()
    return result.to_dict()
