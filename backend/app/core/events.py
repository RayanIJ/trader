"""Tiny in-process async event bus.

Decouples producers (health monitor, broker adapter, signal/risk engines) from
consumers (WebSocket hub, journal). Topics are plain strings; payloads are
JSON-serializable dicts. This keeps modules independent without a heavyweight
message broker for the local single-user app.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Awaitable, Callable

from app.core.logging import get_logger

logger = get_logger("events")

Handler = Callable[[str, dict[str, Any]], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subscribers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        if handler in self._subscribers.get(topic, []):
            self._subscribers[topic].remove(handler)

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        handlers = list(self._subscribers.get(topic, [])) + list(self._subscribers.get("*", []))
        for handler in handlers:
            try:
                await handler(topic, payload)
            except Exception:  # never let one subscriber break the bus
                logger.exception("event handler failed for topic=%s", topic)


# Topic constants keep producers and consumers in sync.
class Topic:
    HEALTH = "health"
    MODE = "mode"
    BROKER = "broker"
    SCANNER = "scanner"
    RISK = "risk"
    POSITION = "position"
    EXECUTION = "execution"
    JOURNAL = "journal"


# Single shared bus for the process.
bus = EventBus()
