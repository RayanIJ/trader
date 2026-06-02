"""FastAPI application entry point.

Wires the runtime container, routes, and the WebSocket hub. Services bind to
localhost by default (see run_server / uvicorn invocation in the README). CORS
is restricted to the local Next.js dev origin.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

import app.runtime as runtime_module
from app.api.routes import backtest as backtest_routes
from app.api.routes import config as config_routes
from app.api.routes import execution as execution_routes
from app.api.routes import journal as journal_routes
from app.api.routes import health as health_routes
from app.api.routes import ibkr as ibkr_routes
from app.api.routes import market as market_routes
from app.api.routes import mode as mode_routes
from app.api.routes import risk as risk_routes
from app.api.routes import scanner as scanner_routes
from app.api.ws import websocket_endpoint
from app.core.logging import configure_logging, get_logger
from app.runtime import REPO_ROOT, Runtime

load_dotenv(REPO_ROOT / ".env")
configure_logging(os.environ.get("LOG_LEVEL", "INFO"))
logger = get_logger("main")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    runtime_module.runtime = Runtime()
    await runtime_module.runtime.startup()
    try:
        yield
    finally:
        await runtime_module.runtime.shutdown()
        runtime_module.runtime = None


app = FastAPI(
    title="Automated Options Trading Cockpit",
    version="0.1.0",
    description="Local, risk-first SPX + semiconductor 0DTE options cockpit (Phase 1).",
    lifespan=lifespan,
)

# Local-only CORS for the Next.js dev server / Docker dashboard.
def _cors_origins() -> list[str]:
    raw = os.environ.get(
        "FRONTEND_ORIGIN",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    origins = {o.strip().rstrip("/") for o in raw.split(",") if o.strip()}
    # Browsers treat localhost and 127.0.0.1 as different origins — always allow both.
    for port in ("3000",):
        origins.add(f"http://localhost:{port}")
        origins.add(f"http://127.0.0.1:{port}")
    return sorted(origins)


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_routes.router)
app.include_router(ibkr_routes.router)
app.include_router(mode_routes.router)
app.include_router(config_routes.router)
app.include_router(scanner_routes.router)
app.include_router(market_routes.router)
app.include_router(risk_routes.router)
app.include_router(execution_routes.router)
app.include_router(journal_routes.router)
app.include_router(backtest_routes.router)


@app.websocket("/ws")
async def ws_route(websocket: WebSocket) -> None:
    await websocket_endpoint(websocket)


def run_server() -> None:
    import uvicorn

    host = os.environ.get("BACKEND_HOST", "127.0.0.1")  # localhost by default
    port = int(os.environ.get("BACKEND_PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run_server()
