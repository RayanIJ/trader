"""Ollama-based LLM client for local Qwen 3 inference.

Connects to a local Ollama instance (default http://localhost:11434) and uses
the Qwen3:8b model with structured JSON output. Thinking mode is disabled
via 'think: false' in the API payload for faster inference (~1s vs ~5min).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from app.core.logging import get_logger
from app.llm.client import LLMClient

logger = get_logger("ollama_client")

# Regex to strip <think>...</think> blocks from Qwen3 output.
_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)

# Regex to extract JSON from potentially mixed text.
_JSON_PATTERN = re.compile(r"\{[\s\S]*\}")


class OllamaLLMClient(LLMClient):
    """Local LLM via Ollama REST API.

    Uses /api/chat with JSON mode for structured output.
    Supports Qwen3 thinking mode — thinking blocks are logged but stripped
    from the guidance response.
    """

    def __init__(
        self,
        model: str = "qwen3:8b",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.1,
        max_tokens: int = 2000,
        timeout: float = 300.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=2),
        )
        self._last_health_check: float = 0.0
        self._healthy: bool = False

    async def guidance(self, payload: dict[str, Any], system_prompt: str) -> dict[str, Any]:
        """Send guidance request to local Ollama model.

        Returns parsed JSON guidance dict. Falls back to no_trade on any error.
        """
        start = time.monotonic()

        # Health check (cached for 60s).
        if not await self._ensure_healthy():
            logger.warning("Ollama not healthy — returning no_trade fallback")
            return self._fallback("Ollama is not running or model not available")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, default=str)},
        ]

        try:
            resp = await self._client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self._model,
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                    "think": False,  # Disable thinking — saves ~5min of inference time.
                    "options": {
                        "temperature": self._temperature,
                        "num_predict": self._max_tokens,
                    },
                },
            )
            resp.raise_for_status()
        except httpx.ConnectError:
            logger.error("cannot connect to Ollama at %s", self._base_url)
            self._healthy = False
            return self._fallback("Ollama connection refused")
        except httpx.TimeoutException:
            logger.error("Ollama request timed out after %.0fs", time.monotonic() - start)
            return self._fallback("Ollama request timed out")
        except httpx.HTTPStatusError as exc:
            logger.error("Ollama HTTP error: %s", exc)
            return self._fallback(f"Ollama HTTP {exc.response.status_code}")

        elapsed = time.monotonic() - start
        body = resp.json()
        msg = body.get("message", {})
        raw_text = msg.get("content", "")

        # Log model metrics.
        eval_count = body.get("eval_count", 0)
        eval_duration_ns = body.get("eval_duration", 0)
        prompt_eval_count = body.get("prompt_eval_count", 0)
        tokens_per_sec = (eval_count / (eval_duration_ns / 1e9)) if eval_duration_ns > 0 else 0
        logger.info(
            "Ollama response: %.1fs, %d prompt_tokens, %d gen_tokens, %.1f tok/s, model=%s",
            elapsed, prompt_eval_count, eval_count, tokens_per_sec, self._model,
        )

        # Check for thinking in the separate 'thinking' field (Ollama API).
        thinking_text = msg.get("thinking", "")
        if thinking_text:
            logger.debug("LLM thinking (separate field): %s", thinking_text[:500])

        # Also check for inline <think> blocks (legacy).
        inline_thinking = self._extract_thinking(raw_text)
        if inline_thinking:
            logger.debug("LLM thinking (inline): %s", inline_thinking[:500])

        # Strip any thinking blocks and extract JSON.
        clean_text = _THINK_PATTERN.sub("", raw_text).strip()
        result = self._extract_json(clean_text)

        if result is None:
            logger.error("failed to extract JSON from Ollama response: %s", clean_text[:300])
            return self._fallback("failed to parse JSON from model response")

        return result

    async def health_check(self) -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            resp = await self._client.get(
                f"{self._base_url}/api/tags",
                timeout=5.0,
            )
            if resp.status_code != 200:
                return False
            tags = resp.json()
            models = [m.get("name", "") for m in tags.get("models", [])]
            # Check if our model (or a variant) is available.
            model_base = self._model.split(":")[0]
            available = any(model_base in m for m in models)
            if not available:
                logger.warning(
                    "model '%s' not found in Ollama (available: %s)",
                    self._model, ", ".join(models[:5]),
                )
            return available
        except (httpx.ConnectError, httpx.TimeoutException):
            return False
        except Exception:
            logger.debug("health check failed", exc_info=True)
            return False

    async def _ensure_healthy(self) -> bool:
        """Cached health check — re-checks every 60 seconds."""
        now = time.monotonic()
        if now - self._last_health_check < 60.0 and self._healthy:
            return True
        self._healthy = await self.health_check()
        self._last_health_check = now
        return self._healthy

    @staticmethod
    def _extract_thinking(text: str) -> str | None:
        """Extract the <think>...</think> block content if present."""
        match = _THINK_PATTERN.search(text)
        if match:
            inner = match.group(0)
            inner = inner.replace("<think>", "").replace("</think>", "").strip()
            return inner if inner else None
        return None

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """Extract JSON object from potentially mixed text."""
        text = text.strip()

        # Try direct parse first.
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in text.
        match = _JSON_PATTERN.search(text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        # Try removing markdown code fences.
        cleaned = re.sub(r"```(?:json)?\s*", "", text)
        cleaned = re.sub(r"```\s*$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        return None

    @staticmethod
    def _fallback(reason: str) -> dict[str, Any]:
        """Return safe no_trade guidance on any failure."""
        return {
            "trade_permission": "no_trade",
            "direction": None,
            "market_state": None,
            "trigger_level": None,
            "invalidation_level": None,
            "target_1": None,
            "target_2": None,
            "stop_level": None,
            "risk_mode": "normal",
            "reasoning": f"LLM fallback: {reason}",
            "confidence": 0.0,
        }

    async def close(self) -> None:
        await self._client.aclose()
