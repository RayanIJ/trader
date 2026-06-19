"""Tests for the Ollama LLM client."""
from __future__ import annotations

import json
import re

import pytest

from app.llm.ollama_client import OllamaLLMClient


class TestJSONExtraction:
    """Test JSON extraction from Qwen3 output (unit tests, no Ollama needed)."""

    def test_clean_json(self):
        text = '{"trade_permission": "no_trade", "confidence": 0.5}'
        result = OllamaLLMClient._extract_json(text)
        assert result is not None
        assert result["trade_permission"] == "no_trade"
        assert result["confidence"] == 0.5

    def test_json_with_surrounding_text(self):
        text = 'Here is my analysis:\n{"trade_permission": "allowed", "direction": "CALL"}\nDone.'
        result = OllamaLLMClient._extract_json(text)
        assert result is not None
        assert result["trade_permission"] == "allowed"

    def test_json_in_code_fence(self):
        text = '```json\n{"trade_permission": "no_trade", "reasoning": "chop"}\n```'
        result = OllamaLLMClient._extract_json(text)
        assert result is not None
        assert result["trade_permission"] == "no_trade"

    def test_invalid_json_returns_none(self):
        text = "This is not JSON at all"
        result = OllamaLLMClient._extract_json(text)
        assert result is None

    def test_nested_json(self):
        text = '{"trade_permission": "no_trade", "levels": {"support": 5400}}'
        result = OllamaLLMClient._extract_json(text)
        assert result is not None
        assert result["levels"]["support"] == 5400


class TestThinkingExtraction:
    """Test <think>...</think> block extraction and stripping."""

    def test_extract_thinking(self):
        text = "<think>The market shows a breakout above VWAP.</think>\n{}"
        thinking = OllamaLLMClient._extract_thinking(text)
        assert thinking is not None
        assert "breakout above VWAP" in thinking

    def test_no_thinking_block(self):
        text = '{"trade_permission": "no_trade"}'
        thinking = OllamaLLMClient._extract_thinking(text)
        assert thinking is None

    def test_thinking_stripped_from_json_extraction(self):
        text = (
            '<think>Analyzing: VWAP at 5420, price at 5435 above VWAP. '
            'Bullish structure with higher highs.</think>\n'
            '{"trade_permission": "allowed", "direction": "CALL", "confidence": 0.75}'
        )
        # Strip thinking.
        from app.llm.ollama_client import _THINK_PATTERN
        clean = _THINK_PATTERN.sub("", text).strip()
        result = OllamaLLMClient._extract_json(clean)
        assert result is not None
        assert result["trade_permission"] == "allowed"
        assert result["direction"] == "CALL"
        assert result["confidence"] == 0.75

    def test_multiline_thinking_block(self):
        text = (
            "<think>\nStep 1: Check VWAP\n"
            "Step 2: Check RSI\n"
            "Step 3: Decision\n</think>\n"
            '{"trade_permission": "no_trade"}'
        )
        thinking = OllamaLLMClient._extract_thinking(text)
        assert thinking is not None
        assert "Step 1" in thinking
        assert "Step 3" in thinking


class TestFallback:
    """Test graceful degradation."""

    def test_fallback_returns_no_trade(self):
        result = OllamaLLMClient._fallback("test reason")
        assert result["trade_permission"] == "no_trade"
        assert "test reason" in result["reasoning"]
        assert result["confidence"] == 0.0
        assert result["direction"] is None


class TestClientFactory:
    """Test that the factory creates the right client."""

    def test_factory_creates_ollama(self):
        from app.llm.client import make_llm_client
        client = make_llm_client("ollama", model="qwen3:8b")
        assert isinstance(client, OllamaLLMClient)

    def test_factory_passes_config(self):
        from app.llm.client import make_llm_client
        client = make_llm_client(
            "ollama", model="qwen3:4b", temperature=0.5, max_tokens=1000,
        )
        assert isinstance(client, OllamaLLMClient)
        assert client._model == "qwen3:4b"
        assert client._temperature == 0.5
        assert client._max_tokens == 1000


class TestConfigSchema:
    """Test config schema changes."""

    def test_ollama_provider_valid(self):
        from app.config.schema import LLMConfig
        cfg = LLMConfig(provider="ollama", model="qwen3:8b")
        assert cfg.provider == "ollama"
        assert cfg.model == "qwen3:8b"

    def test_default_model_is_qwen3(self):
        from app.config.schema import LLMConfig
        cfg = LLMConfig()
        assert cfg.model == "qwen3:8b"

    def test_ollama_base_url_config(self):
        from app.config.schema import LLMConfig
        cfg = LLMConfig()
        assert cfg.ollama_base_url == "http://localhost:11434"

    def test_investing_calendar_provider_valid(self):
        from app.config.schema import MacroConfig
        cfg = MacroConfig(calendar_provider="investing")
        assert cfg.calendar_provider == "investing"


def _ollama_running() -> bool:
    """Check if Ollama is running for skip condition."""
    try:
        import httpx
        resp = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(
    not _ollama_running(),
    reason="Ollama not running — skip integration test",
)
class TestOllamaIntegration:
    """Integration tests that require a running Ollama instance with qwen3:8b."""

    @pytest.mark.asyncio
    async def test_health_check(self):
        client = OllamaLLMClient(model="qwen3:8b")
        healthy = await client.health_check()
        assert healthy is True
        await client.close()

    @pytest.mark.asyncio
    async def test_simple_guidance_call(self):
        """Real Ollama call with minimal context — verify JSON response."""
        client = OllamaLLMClient(model="qwen3:8b", temperature=0.1, max_tokens=500)
        payload = {
            "request_metadata": {
                "request_time_et": "2024-07-15T10:30:00",
                "market": "SPX",
                "trading_mode": "shadow",
            },
            "session_summary": {
                "current_price": 5430.0,
                "vwap": 5425.0,
                "ema_10": 5428.0,
                "ema_20": 5420.0,
                "rsi_14": 55.0,
                "day_open": 5415.0,
                "day_high": 5435.0,
                "day_low": 5410.0,
            },
            "macro_context": {"todays_events": [], "active_blocks": []},
        }
        from app.llm.prompt import build_system_prompt
        result = await client.guidance(payload, build_system_prompt())

        # Should return valid guidance with trade_permission.
        assert "trade_permission" in result
        assert result["trade_permission"] in ("allowed", "no_trade", "exit_only", "blocked")
        await client.close()

