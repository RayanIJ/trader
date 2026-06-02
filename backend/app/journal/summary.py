"""End-of-day summary builder from journal entries."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from app.db.models import DailySummary, JournalEntry
from app.db.session import get_session


def _day_bounds(trade_date: str) -> tuple[datetime, datetime]:
    """UTC midnight bounds for YYYY-MM-DD (session date label)."""
    start = datetime.fromisoformat(f"{trade_date}T00:00:00+00:00")
    return start, start + timedelta(days=1)


def build_daily_summary(trade_date: str | None = None) -> dict:
    trade_date = trade_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start, end = _day_bounds(trade_date)

    with get_session() as s:
        rows = (
            s.query(JournalEntry)
            .filter(JournalEntry.ts >= start, JournalEntry.ts < end)
            .order_by(JournalEntry.ts.asc())
            .all()
        )

        realized = 0.0
        trades = 0
        rejections = 0
        reject_codes: Counter[str] = Counter()
        best_trade: dict | None = None
        worst_trade: dict | None = None

        for r in rows:
            if r.kind == "EXIT":
                pnl = float(r.payload.get("realized_pnl", 0))
                realized += pnl
                trades += 1
                item = {"symbol": r.symbol, "pnl": pnl, "reason": r.payload.get("reason")}
                if best_trade is None or pnl > best_trade["pnl"]:
                    best_trade = item
                if worst_trade is None or pnl < worst_trade["pnl"]:
                    worst_trade = item
            elif r.kind == "REJECT":
                rejections += 1
                for code in r.payload.get("reject_codes", []):
                    reject_codes[code] += 1

        signals = sum(1 for r in rows if r.kind in ("SIGNAL", "ENTRY", "SCAN"))
        metrics = {
            "signals_logged": signals,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
        }
        top_rejections = dict(reject_codes.most_common(10))

        existing = s.query(DailySummary).filter(DailySummary.trade_date == trade_date).one_or_none()
        if existing:
            existing.realized_pnl = round(realized, 2)
            existing.trades = trades
            existing.rejected = rejections
            existing.top_rejections = top_rejections
            existing.metrics = metrics
        else:
            s.add(
                DailySummary(
                    trade_date=trade_date,
                    realized_pnl=round(realized, 2),
                    unrealized_pnl=0.0,
                    trades=trades,
                    rejected=rejections,
                    lockouts=sum(1 for r in rows if r.kind == "LOCKOUT"),
                    top_rejections=top_rejections,
                    metrics=metrics,
                )
            )
        s.commit()

    return {
        "trade_date": trade_date,
        "realized_pnl": round(realized, 2),
        "trades": trades,
        "rejected": rejections,
        "top_rejections": top_rejections,
        "metrics": metrics,
    }


def get_daily_summary(trade_date: str | None = None) -> dict | None:
    trade_date = trade_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_session() as s:
        row = s.query(DailySummary).filter(DailySummary.trade_date == trade_date).one_or_none()
        if not row:
            return None
        return {
            "trade_date": row.trade_date,
            "realized_pnl": row.realized_pnl,
            "unrealized_pnl": row.unrealized_pnl,
            "trades": row.trades,
            "rejected": row.rejected,
            "lockouts": row.lockouts,
            "top_rejections": row.top_rejections,
            "metrics": row.metrics,
        }
