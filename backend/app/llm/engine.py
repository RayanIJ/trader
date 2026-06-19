"""LLM guidance engine — 5-minute loop that queries the LLM for market guidance.

Does NOT execute trades. Assembles context, validates chart data, calls the
LLM client, validates the response, persists everything, and publishes the
guidance to the event bus for the execution engine to consume.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.core.events import Topic, bus
from app.core.logging import get_logger
from app.llm.client import LLMClient, make_llm_client, parse_guidance_response
from app.llm.context_builder import build_guidance_request
from app.llm.models import LLMGuidanceResponse
from app.llm.prompt import build_system_prompt

if TYPE_CHECKING:
    from app.runtime import Runtime

logger = get_logger("llm_engine")


class LLMGuidanceEngine:
    """Orchestrates periodic LLM guidance cycles."""

    def __init__(self, runtime: "Runtime", provider: str = "stub") -> None:
        self._runtime = runtime
        cfg = runtime.config.llm
        self._client: LLMClient = make_llm_client(
            provider,
            model=cfg.model,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            base_url=cfg.ollama_base_url,
        )
        self._latest_guidance: LLMGuidanceResponse | None = None
        self._latest_request: dict[str, Any] | None = None
        self._tick_count: int = 0

    @property
    def latest_guidance(self) -> LLMGuidanceResponse | None:
        return self._latest_guidance

    @property
    def latest_request(self) -> dict[str, Any] | None:
        return self._latest_request

    async def tick(self, now: datetime | None = None) -> LLMGuidanceResponse:
        """Run one guidance cycle: build context → validate → call LLM → persist."""
        now = now or datetime.now(timezone.utc)
        self._tick_count += 1

        # 1. Build full context payload.
        try:
            payload = await build_guidance_request(self._runtime, now)
        except Exception:
            logger.exception("failed to build guidance context")
            return self._fallback_guidance("context build failed")

        self._latest_request = payload

        # 2. If chart data is invalid, return degraded guidance without calling LLM.
        if not payload.get("chart_valid", True):
            issues = payload.get("chart_issues", [])
            logger.warning("chart context invalid (%s) — returning no_trade", issues)
            await self._journal("LLM_CHART_INVALID", {
                "issues": issues,
                "bar_count": payload.get("bar_count", 0),
            })
            guidance = LLMGuidanceResponse(
                trade_permission="no_trade",
                reasoning=f"chart context invalid: {', '.join(issues)}",
            )
            self._latest_guidance = guidance
            await self._publish(guidance, payload)
            return guidance

        # 3. Call LLM.
        system_prompt = build_system_prompt()
        try:
            raw_output = await self._client.guidance(payload, system_prompt)
        except Exception:
            logger.exception("LLM call failed")
            await self._journal("LLM_CALL_FAILED", {"tick": self._tick_count})
            return self._fallback_guidance("LLM call failed")

        # 4. Parse and validate response.
        guidance = parse_guidance_response(raw_output)
        self._latest_guidance = guidance

        # 5. Persist.
        await self._persist(payload, guidance)

        # 6. Publish.
        await self._publish(guidance, payload)

        logger.info(
            "LLM guidance tick=%d permission=%s direction=%s confidence=%s",
            self._tick_count, guidance.trade_permission, guidance.direction,
            guidance.confidence,
        )
        return guidance

    def _fallback_guidance(self, reason: str) -> LLMGuidanceResponse:
        resp = LLMGuidanceResponse(
            trade_permission="no_trade",
            reasoning=reason,
        )
        self._latest_guidance = resp
        return resp

    async def _persist(self, request: dict, guidance: LLMGuidanceResponse) -> None:
        """Persist the LLM request and response to the journal."""
        try:
            await self._journal("LLM_REQUEST", {
                "bar_count": request.get("bar_count", 0),
                "compression_method": request.get("compression_method", "unknown"),
                "chart_valid": request.get("chart_valid", False),
                "macro_events": len(request.get("macro_context", {}).get("todays_events", [])),
                "trading_mode": request.get("request_metadata", {}).get("trading_mode", "shadow"),
            })
            await self._journal("LLM_RESPONSE", {
                "trade_permission": guidance.trade_permission,
                "direction": guidance.direction,
                "confidence": guidance.confidence,
                "risk_mode": guidance.risk_mode,
                "reasoning": guidance.reasoning,
            })
        except Exception:
            logger.exception("failed to persist LLM guidance")

    async def _publish(self, guidance: LLMGuidanceResponse, request: dict) -> None:
        """Publish guidance to the event bus."""
        await bus.publish(Topic.LLM_GUIDANCE, {
            "trade_permission": guidance.trade_permission,
            "direction": guidance.direction,
            "market_state": guidance.market_state,
            "confidence": guidance.confidence,
            "risk_mode": guidance.risk_mode,
            "bar_count": request.get("bar_count", 0),
            "compression_method": request.get("compression_method"),
            "chart_valid": request.get("chart_valid", False),
        })
        await bus.publish(Topic.CHART_CONTEXT, {
            "bar_count": request.get("bar_count", 0),
            "compression_method": request.get("compression_method"),
            "chart_valid": request.get("chart_valid", False),
            "chart_issues": request.get("chart_issues", []),
        })

    async def _journal(self, kind: str, payload: dict) -> None:
        if self._runtime.journal:
            await self._runtime.journal.record_async(kind, payload)
