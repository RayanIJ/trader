"""LLM guidance API routes."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.logging import get_logger

router = APIRouter(prefix="/api/llm", tags=["llm"])
logger = get_logger("api.llm")


@router.get("/guidance")
async def get_guidance():
    """Return the latest LLM guidance response."""
    from app.runtime import get_runtime

    rt = get_runtime()
    engine = getattr(rt, "llm_engine", None)
    if engine is None:
        return {"guidance": None, "enabled": False}

    guidance = engine.latest_guidance
    request = engine.latest_request
    return {
        "guidance": guidance.model_dump() if guidance else None,
        "request_metadata": request.get("request_metadata") if request else None,
        "bar_count": request.get("bar_count") if request else 0,
        "compression_method": request.get("compression_method") if request else None,
        "chart_valid": request.get("chart_valid") if request else None,
        "enabled": True,
    }


@router.get("/chart-context")
async def get_chart_context():
    """Return current chart context status."""
    from app.runtime import get_runtime

    rt = get_runtime()
    engine = getattr(rt, "llm_engine", None)
    if engine is None:
        return {"enabled": False, "bar_count": 0}

    request = engine.latest_request
    if not request:
        return {"enabled": True, "bar_count": 0, "status": "no_data"}

    return {
        "enabled": True,
        "bar_count": request.get("bar_count", 0),
        "compression_method": request.get("compression_method"),
        "chart_valid": request.get("chart_valid", False),
        "chart_issues": request.get("chart_issues", []),
        "session_summary": request.get("session_summary"),
    }


@router.post("/guidance/force")
async def force_guidance():
    """Trigger an immediate LLM guidance cycle."""
    from app.runtime import get_runtime

    rt = get_runtime()
    engine = getattr(rt, "llm_engine", None)
    if engine is None:
        return {"ok": False, "reason": "LLM engine not initialized"}

    guidance = await engine.tick()
    return {
        "ok": True,
        "guidance": guidance.model_dump(),
    }


@router.get("/backtest")
async def get_backtest_results():
    """Return the latest backtest results."""
    import json
    from pathlib import Path

    data_path = Path(__file__).resolve().parents[3] / "data" / "latest_backtest.json"
    if not data_path.exists():
        return {"available": False, "message": "No backtest results yet. Run: python -m tests.backtest_macro_news"}

    with open(data_path) as f:
        results = json.load(f)

    return {"available": True, "results": results}

