"""MLX-based LLM client for local GPU inference on Apple Silicon.

Uses mlx-lm to run model inference natively on Apple Silicon. Runs generation
in a background thread to prevent blocking the async event loop and uses a
global threading Lock to serialize GPU access.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from typing import Any

# Force huggingface-hub to offline mode for instant loading of cached local weights.
os.environ["HF_HUB_OFFLINE"] = "1"

from app.core.logging import get_logger
from app.llm.client import LLMClient

logger = get_logger("mlx_client")

# Regex to strip <think>...</think> blocks from output.
_THINK_PATTERN = re.compile(r"<think>.*?</think>", re.DOTALL)

# Regex to extract JSON from potentially mixed text.
_JSON_PATTERN = re.compile(r"\{[\s\S]*\}")

# Global lock to serialize GPU access for MLX inference.
_mlx_lock = threading.Lock()


class MLXLLMClient(LLMClient):
    """Local LLM via MLX-LM.

    Loads the model once and keeps it in unified RAM.
    """

    # Class-level cache to keep the model loaded across client instances
    _model_obj: Any = None
    _tokenizer: Any = None
    _loaded_model_name: str | None = None

    def __init__(
        self,
        model: str = "mlx-community/Qwen2.5-7B-Instruct-4bit",
        temperature: float = 0.1,
        max_tokens: int = 2000,
        **kwargs,
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def guidance(self, payload: dict[str, Any], system_prompt: str) -> dict[str, Any]:
        """Generate guidance using the local MLX model.

        Returns parsed JSON guidance dict. Falls back to no_trade on any error.
        """
        start = time.monotonic()

        # 1. Load model and tokenizer (lazy-loaded).
        try:
            await asyncio.to_thread(self._ensure_loaded)
        except Exception as exc:
            logger.exception("Failed to load MLX model: %s", self._model)
            return self._fallback(f"Model load failed: {exc}")

        # 2. Format the prompt using the model's chat template.
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(payload, default=str)},
        ]
        try:
            prompt = self._tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )
        except Exception as exc:
            logger.exception("Failed to apply chat template")
            return self._fallback(f"Chat template application failed: {exc}")

        # 3. Generate in a background thread to release GIL and prevent event loop blocking.
        try:
            raw_text, metrics = await asyncio.to_thread(
                self._generate_in_thread,
                prompt,
                self._max_tokens,
                self._temperature,
            )
        except Exception as exc:
            logger.exception("MLX generation failed")
            return self._fallback(f"MLX generation failed: {exc}")

        elapsed = time.monotonic() - start

        # Log model metrics if available.
        if metrics:
            logger.info(
                "MLX response: %.1fs, %d prompt_tokens, %d gen_tokens, %.1f tok/s, model=%s",
                elapsed,
                metrics.prompt_tokens,
                metrics.generation_tokens,
                metrics.generation_tps,
                self._model,
            )
        else:
            logger.info("MLX response: %.1fs, model=%s (no metrics)", elapsed, self._model)

        # 4. Strip any thinking blocks and extract JSON.
        inline_thinking = self._extract_thinking(raw_text)
        if inline_thinking:
            logger.debug("LLM thinking (inline): %s", inline_thinking[:500])

        clean_text = _THINK_PATTERN.sub("", raw_text).strip()
        result = self._extract_json(clean_text)

        if result is None:
            logger.error("Failed to extract JSON from MLX response: %s", clean_text[:300])
            return self._fallback("Failed to parse JSON from model response")

        return result

    def _ensure_loaded(self) -> None:
        """Loads the model and tokenizer into memory if not already cached.

        Must be run inside a thread-safe context or executor.
        """
        if MLXLLMClient._loaded_model_name == self._model and MLXLLMClient._model_obj is not None:
            return

        with _mlx_lock:
            # Re-check under lock.
            if MLXLLMClient._loaded_model_name == self._model and MLXLLMClient._model_obj is not None:
                return

            logger.info("Loading MLX model '%s' into Unified Memory...", self._model)
            start = time.time()
            from mlx_lm import load
            model_obj, tokenizer = load(self._model)
            logger.info("MLX model loaded in %.2fs", time.time() - start)

            MLXLLMClient._model_obj = model_obj
            MLXLLMClient._tokenizer = tokenizer
            MLXLLMClient._loaded_model_name = self._model

    def _generate_in_thread(self, prompt: str, max_tokens: int, temperature: float) -> tuple[str, Any]:
        """Runs the generation under the global GPU lock.

        Must be executed in a background thread.
        """
        with _mlx_lock:
            from mlx_lm import stream_generate
            from mlx_lm.sample_utils import make_sampler
            
            sampler = make_sampler(temp=temperature)
            text = ""
            last_response = None
            for response in stream_generate(
                MLXLLMClient._model_obj,
                MLXLLMClient._tokenizer,
                prompt,
                max_tokens=max_tokens,
                sampler=sampler,
            ):
                text += response.text
                last_response = response
            return text, last_response

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
            "reasoning": f"LLM fallback (MLX): {reason}",
            "confidence": 0.0,
        }
