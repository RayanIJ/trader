"""LLM client interface and implementations.

The abstract ``LLMClient`` lets the guidance engine work with any provider.
``StubLLMClient`` returns deterministic no-trade guidance for testing/shadow.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from app.core.logging import get_logger
from app.llm.models import LLMGuidanceResponse

logger = get_logger("llm_client")


class LLMClient(ABC):
    """Abstract LLM provider interface."""

    @abstractmethod
    async def guidance(self, payload: dict[str, Any], system_prompt: str) -> dict[str, Any]:
        """Send the guidance request and return the parsed JSON response."""
        ...

    async def close(self) -> None:
        """Close any open connections or resources."""
        pass


class StubLLMClient(LLMClient):
    """Deterministic stub — always returns no_trade guidance.

    Used for shadow mode testing and when no real LLM provider is configured.
    """

    async def guidance(self, payload: dict[str, Any], system_prompt: str) -> dict[str, Any]:
        logger.debug("stub LLM client returning no_trade guidance")
        return {
            "trade_permission": "no_trade",
            "direction": None,
            "market_state": "stub — no real LLM configured",
            "trigger_level": None,
            "invalidation_level": None,
            "target_1": None,
            "target_2": None,
            "stop_level": None,
            "risk_mode": "normal",
            "reasoning": "stub client — no real analysis performed",
            "confidence": 0.0,
        }


def parse_guidance_response(raw: dict[str, Any]) -> LLMGuidanceResponse:
    """Validate and parse a raw LLM output dict into the guidance model."""
    try:
        resp = LLMGuidanceResponse(**raw)
        resp.raw = raw
        return resp
    except Exception as exc:
        logger.warning("LLM response validation failed: %s — returning no_trade", exc)
        return LLMGuidanceResponse(
            trade_permission="no_trade",
            reasoning=f"response validation failed: {exc}",
            raw=raw,
        )


def make_llm_client(provider: str = "stub", **kwargs) -> LLMClient:
    """Factory for LLM client instances."""
    if provider == "stub":
        return StubLLMClient()
    if provider == "ollama":
        from app.llm.ollama_client import OllamaLLMClient
        return OllamaLLMClient(**kwargs)
    if provider == "mlx":
        from app.llm.mlx_client import MLXLLMClient
        return MLXLLMClient(**kwargs)
    logger.warning("unknown LLM provider '%s', falling back to stub", provider)
    return StubLLMClient()
