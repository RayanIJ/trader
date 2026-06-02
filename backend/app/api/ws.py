"""WebSocket hub.

Bridges the in-process event bus to connected browser clients. On connect we
push the latest health + mode snapshot so the dashboard renders immediately,
then stream every bus event (health, mode, broker, scanner, risk, ...).
"""
from __future__ import annotations

import asyncio

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.core.events import bus
from app.core.logging import get_logger

logger = get_logger("ws")


class WsHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        # Subscribe once to all topics and fan out to clients.
        bus.subscribe("*", self._on_event)

    async def _on_event(self, topic: str, payload: dict) -> None:
        await self.broadcast({"topic": topic, "data": payload})

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)
        logger.info("ws client connected (total=%d)", len(self._clients))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
        logger.info("ws client disconnected (total=%d)", len(self._clients))

    async def broadcast(self, message: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                if ws.application_state == WebSocketState.CONNECTED:
                    await ws.send_json(message)
                else:
                    dead.append(ws)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


hub = WsHub()


async def websocket_endpoint(ws: WebSocket) -> None:
    from app.runtime import get_runtime

    await hub.connect(ws)
    try:
        # Push an initial snapshot.
        rt = get_runtime()
        broker_status, report = await rt.refresh_status()
        await ws.send_json({"topic": "snapshot", "data": {
            "mode": rt.mode_manager.mode.value,
            "locked_out": rt.mode_manager.locked_out,
            "health": report.to_dict(),
        }})
        # Keep the socket open; the hub pushes events. We still read to detect close.
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("ws loop ended", exc_info=True)
    finally:
        await hub.disconnect(ws)
