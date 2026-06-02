"""Journal writer — every signal, order, fill, exit, and rule decision."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

from app.core.events import Topic, bus
from app.core.logging import get_logger
from app.db.models import JournalEntry
from app.db.session import get_session

logger = get_logger("journal")


class JournalService:
    """Append-only audit log backed by ``journal_entries``."""

    def __init__(self, mode_fn: Callable[[], str] | None = None) -> None:
        self._mode_fn = mode_fn or (lambda: "SHADOW")

    def _write(self, kind: str, symbol: str | None, payload: dict[str, Any]) -> dict:
        mode = self._mode_fn()
        with get_session() as s:
            row = JournalEntry(
                ts=datetime.now(timezone.utc),
                kind=kind,
                symbol=symbol,
                mode=mode,
                payload=payload,
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return {
                "id": row.id,
                "ts": row.ts.isoformat(),
                "kind": kind,
                "symbol": symbol,
                "mode": mode,
                "payload": payload,
            }

    def record(self, kind: str, payload: dict[str, Any] | None = None, *, symbol: str | None = None) -> dict:
        return self._write(kind, symbol, payload or {})

    async def record_async(
        self, kind: str, payload: dict[str, Any] | None = None, *, symbol: str | None = None
    ) -> dict:
        entry = await asyncio.to_thread(self.record, kind, payload, symbol=symbol)
        await bus.publish(Topic.JOURNAL, entry)
        return entry

    async def subscribe_bus(self) -> None:
        """Mirror select bus topics into the journal (mode + execution messages)."""

        async def _mode(_topic: str, payload: dict) -> None:
            await self.record_async("MODE", payload)

        async def _execution(_topic: str, payload: dict) -> None:
            msgs = payload.get("messages") or []
            if msgs:
                await self.record_async("EXECUTION", {"messages": msgs[-3:]})

        bus.subscribe(Topic.MODE, _mode)
        bus.subscribe(Topic.EXECUTION, _execution)

    def recent(self, limit: int = 50, kind: str | None = None) -> list[dict]:
        with get_session() as s:
            q = s.query(JournalEntry).order_by(JournalEntry.ts.desc())
            if kind:
                q = q.filter(JournalEntry.kind == kind)
            rows = q.limit(limit).all()
            return [
                {
                    "id": r.id,
                    "ts": r.ts.isoformat(),
                    "kind": r.kind,
                    "symbol": r.symbol,
                    "mode": r.mode,
                    "payload": r.payload,
                }
                for r in rows
            ]
