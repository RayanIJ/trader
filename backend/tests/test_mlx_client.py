"""Tests for the MLX LLM client."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.llm.client import make_llm_client
from app.llm.mlx_client import MLXLLMClient


class TestJSONExtraction:
    """Test JSON extraction from model output."""

    def test_clean_json(self):
        text = '{"trade_permission": "no_trade", "confidence": 0.5}'
        result = MLXLLMClient._extract_json(text)
        assert result is not None
        assert result["trade_permission"] == "no_trade"
        assert result["confidence"] == 0.5

    def test_json_with_surrounding_text(self):
        text = 'Here is my analysis:\n{"trade_permission": "allowed", "direction": "CALL"}\nDone.'
        result = MLXLLMClient._extract_json(text)
        assert result is not None
        assert result["trade_permission"] == "allowed"

    def test_json_in_code_fence(self):
        text = '```json\n{"trade_permission": "no_trade", "reasoning": "chop"}\n```'
        result = MLXLLMClient._extract_json(text)
        assert result is not None
        assert result["trade_permission"] == "no_trade"

    def test_invalid_json_returns_none(self):
        text = "This is not JSON at all"
        result = MLXLLMClient._extract_json(text)
        assert result is None


class TestThinkingExtraction:
    """Test <think>...</think> block extraction and stripping."""

    def test_extract_thinking(self):
        text = "<think>The market shows a breakout above VWAP.</think>\n{}"
        thinking = MLXLLMClient._extract_thinking(text)
        assert thinking is not None
        assert "breakout above VWAP" in thinking

    def test_no_thinking_block(self):
        text = '{"trade_permission": "no_trade"}'
        thinking = MLXLLMClient._extract_thinking(text)
        assert thinking is None

    def test_thinking_stripped_from_json_extraction(self):
        text = (
            '<think>Analyzing: Bullish structure.</think>\n'
            '{"trade_permission": "allowed", "direction": "CALL"}'
        )
        from app.llm.mlx_client import _THINK_PATTERN
        clean = _THINK_PATTERN.sub("", text).strip()
        result = MLXLLMClient._extract_json(clean)
        assert result is not None
        assert result["trade_permission"] == "allowed"


class TestFallback:
    """Test graceful degradation."""

    def test_fallback_returns_no_trade(self):
        result = MLXLLMClient._fallback("test reason")
        assert result["trade_permission"] == "no_trade"
        assert "test reason" in result["reasoning"]
        assert result["confidence"] == 0.0
        assert result["direction"] is None


class TestClientFactory:
    """Test that the factory creates the right client."""

    def test_factory_creates_mlx(self):
        client = make_llm_client("mlx", model="mlx-community/Qwen2.5-7B-Instruct-4bit")
        assert isinstance(client, MLXLLMClient)
        assert client._model == "mlx-community/Qwen2.5-7B-Instruct-4bit"
        assert client._temperature == 0.1
        assert client._max_tokens == 2000


@pytest.mark.asyncio
async def test_guidance_calls_generate():
    """Test that guidance calls the MLX model generation."""
    client = MLXLLMClient(model="mlx-community/Qwen2.5-7B-Instruct-4bit")

    # Mock the lazy loader and generation methods
    mock_tokenizer = MagicMock()
    mock_tokenizer.apply_chat_template.return_value = "formatted_prompt"

    mock_response = MagicMock()
    mock_response.text = '{"trade_permission": "no_trade", "reasoning": "mocked"}'
    mock_response.prompt_tokens = 10
    mock_response.generation_tokens = 5
    mock_response.generation_tps = 50.0

    def mock_generate_in_thread(*args, **kwargs):
        return '{"trade_permission": "no_trade", "reasoning": "mocked"}', mock_response

    with patch.object(client, "_ensure_loaded", return_value=None), \
         patch.object(client, "_tokenizer", mock_tokenizer), \
         patch.object(client, "_generate_in_thread", side_effect=mock_generate_in_thread):

        payload = {"dummy": "data"}
        res = await client.guidance(payload, "system prompt")

        assert res["trade_permission"] == "no_trade"
        assert res["reasoning"] == "mocked"
        mock_tokenizer.apply_chat_template.assert_called_once()
