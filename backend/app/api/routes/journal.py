"""Journal + daily summary API."""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.journal.summary import build_daily_summary, get_daily_summary
from app.runtime import get_runtime

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("")
async def list_entries(
    limit: int = Query(default=50, ge=1, le=200),
    kind: str | None = None,
) -> dict:
    rt = get_runtime()
    entries = rt.journal.recent(limit=limit, kind=kind)
    return {"entries": entries}


@router.get("/summary")
async def daily_summary(trade_date: str | None = None) -> dict:
    summary = get_daily_summary(trade_date)
    if summary is None:
        return {"summary": None, "trade_date": trade_date}
    return {"summary": summary}


@router.post("/summary/build")
async def build_summary(trade_date: str | None = None) -> dict:
    summary = build_daily_summary(trade_date)
    return {"summary": summary}
