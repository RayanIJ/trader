"""Macro calendar + LLM guidance backtest.

Scrapes today's economic calendar, builds a simulated chart context,
runs the full LLM guidance pipeline, and outputs results as JSON
that the dashboard can display.

Usage:
    python -m tests.backtest_macro_news
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add backend to path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.schema import AppConfig, LLMConfig
from app.core.timezone import ET, RIYADH, dual_timestamp, to_et, to_riyadh, current_et_date
from app.llm.chart_serializer import serialize_chart, serialize_session_summary
from app.llm.client import make_llm_client, parse_guidance_response
from app.llm.ollama_client import OllamaLLMClient
from app.llm.prompt import build_system_prompt
from app.macro.calendar_provider import InvestingCalendarProvider, DatabaseMacroProvider
from app.macro.scraper import InvestingCalendarScraper, ScraperError, RawCalendarEvent
from app.market_data.intraday_bars import enrich_bars
from app.market_data.models import Candle


def build_simulated_chart(bar_count: int = 200) -> list[dict]:
    """Generate a realistic intraday chart for backtesting."""
    now_et = to_et(datetime.now(timezone.utc))
    session_start = now_et.replace(hour=9, minute=30, second=0, microsecond=0)

    # If market hasn't opened yet, use yesterday.
    if now_et < session_start:
        session_start -= timedelta(days=1)

    candles: list[Candle] = []
    price = 5420.0
    import random
    random.seed(42)  # Deterministic for reproducibility.

    for i in range(bar_count):
        ts = session_start + timedelta(minutes=i)
        delta = random.gauss(0, 0.3)
        price += delta
        candles.append(Candle(
            ts=ts.astimezone(timezone.utc),
            open=round(price, 2),
            high=round(price + abs(random.gauss(0, 0.2)), 2),
            low=round(price - abs(random.gauss(0, 0.2)), 2),
            close=round(price + random.gauss(0, 0.1), 2),
            volume=int(50000 + random.gauss(0, 10000)),
        ))

    enriched = enrich_bars(candles)
    bars, compression = serialize_chart(enriched, max_full_bars=30)
    summary = serialize_session_summary(candles, None, None, None)
    return bars, summary, compression, candles


async def run_backtest(provider: str = "mlx", model: str | None = None):
    """Execute the full backtest pipeline."""

    def _sample_macro_events() -> list:
        """Realistic sample of US macro events for backtest when scraper is blocked."""
        return [
            RawCalendarEvent(event_id="cpi_0830", name="Core CPI (MoM)", time_str="08:30",
                             actual="0.3%", forecast="0.2%", previous="0.4%", importance=3),
            RawCalendarEvent(event_id="cpi_yoy_0830", name="CPI (YoY)", time_str="08:30",
                             actual="3.3%", forecast="3.4%", previous="3.5%", importance=3),
            RawCalendarEvent(event_id="claims_0830", name="Initial Jobless Claims", time_str="08:30",
                             actual="242K", forecast="235K", previous="229K", importance=2),
            RawCalendarEvent(event_id="cont_claims_0830", name="Continuing Jobless Claims", time_str="08:30",
                             actual="1.820M", forecast="1.800M", previous="1.790M", importance=2),
            RawCalendarEvent(event_id="pmi_0945", name="S&P Global Manufacturing PMI", time_str="09:45",
                             forecast="51.2", previous="51.3", importance=2),
            RawCalendarEvent(event_id="fomc_1400", name="FOMC Statement", time_str="14:00",
                             importance=3),
            RawCalendarEvent(event_id="fed_rate_1400", name="Fed Interest Rate Decision", time_str="14:00",
                             forecast="5.50%", previous="5.50%", importance=3),
        ]
    results = {
        "backtest_time_et": to_et(datetime.now(timezone.utc)).isoformat(),
        "backtest_time_gmt3": to_riyadh(datetime.now(timezone.utc)).isoformat(),
        "steps": [],
        "errors": [],
    }

    # ── Step 1: Get today's macro calendar ──
    print("=" * 60)
    print("STEP 1: Loading today's economic calendar...")
    print("=" * 60)

    today = current_et_date()
    step1 = {"step": "scrape_calendar", "date": today.isoformat()}

    # Use sample data for backtest (Investing.com blocks automated requests with Cloudflare).
    # In production, the InvestingCalendarProvider handles this with proper rate limiting.
    raw_events = _sample_macro_events()
    step1["status"] = "sample_data"
    step1["source"] = "realistic_sample"
    print(f"  📋 Using {len(raw_events)} realistic sample US macro events")

    step1["event_count"] = len(raw_events)
    step1["events"] = []
    for e in raw_events:
        event_data = {
            "name": e.name,
            "time": e.time_str,
            "importance": e.importance,
            "actual": e.actual,
            "forecast": e.forecast,
            "previous": e.previous,
        }
        step1["events"].append(event_data)
        status = "✅ RELEASED" if e.actual else "⏳ PENDING"
        importance_stars = "⭐" * e.importance
        print(f"  {importance_stars} {e.time_str or 'ALL DAY'} ET — {e.name}")
        if e.actual:
            print(f"      Actual: {e.actual}  Forecast: {e.forecast}  Prior: {e.previous}  {status}")
        else:
            print(f"      Forecast: {e.forecast}  Prior: {e.previous}  {status}")

    results["steps"].append(step1)
    print()

    # ── Step 2: Build chart context ──
    print("=" * 60)
    print("STEP 2: Building simulated chart context...")
    print("=" * 60)

    bars, summary, compression, candles = build_simulated_chart(200)
    step2 = {
        "step": "chart_context",
        "bar_count": len(bars),
        "compression": compression.value,
        "current_price": summary.get("current_price"),
        "vwap": summary.get("vwap"),
        "rsi_14": summary.get("rsi_14"),
        "ema_10": summary.get("ema_10"),
        "ema_20": summary.get("ema_20"),
    }
    results["steps"].append(step2)

    payload_json = json.dumps({"bars": bars, "summary": summary}, default=str)
    estimated_tokens = len(payload_json) // 4
    print(f"  Bars: {len(bars)}")
    print(f"  Compression: {compression.value}")
    print(f"  Estimated chart tokens: ~{estimated_tokens:,}")
    print(f"  Current price: {summary.get('current_price')}")
    print(f"  VWAP: {summary.get('vwap')}")
    print(f"  RSI(14): {summary.get('rsi_14')}")
    print()

    # ── Step 3: Build macro context for LLM ──
    print("=" * 60)
    print("STEP 3: Building macro context payload...")
    print("=" * 60)

    from app.macro.scraper import normalize_event_name, importance_to_str
    macro_events = []
    for e in (raw_events if raw_events else []):
        macro_events.append({
            "event_id": f"{normalize_event_name(e.name)}_{e.time_str or 'ALLDAY'}",
            "name": normalize_event_name(e.name),
            "importance": importance_to_str(e.importance),
            "release_time_et": e.time_str,
            "status": "released" if e.actual else "scheduled",
            "actual": e.actual,
            "consensus": e.forecast,
            "prior": e.previous,
        })

    # Determine active blocks.
    now_et = to_et(datetime.now(timezone.utc))
    active_blocks = []
    for me in macro_events:
        if me["status"] == "scheduled" and me.get("release_time_et"):
            try:
                h, m = me["release_time_et"].split(":")
                event_time = now_et.replace(hour=int(h), minute=int(m))
                mins_until = (event_time - now_et).total_seconds() / 60
                if 0 <= mins_until <= 5:
                    active_blocks.append({
                        "event": me["name"],
                        "minutes_until": round(mins_until, 1),
                        "block_type": "pre_release",
                    })
                elif -5 <= mins_until < 0:
                    active_blocks.append({
                        "event": me["name"],
                        "minutes_since": round(-mins_until, 1),
                        "block_type": "post_release",
                    })
            except (ValueError, AttributeError):
                pass

    macro_context = {
        "todays_events": macro_events,
        "active_blocks": active_blocks,
        "event_count": len(macro_events),
    }

    step3 = {
        "step": "macro_context",
        "event_count": len(macro_events),
        "active_blocks": len(active_blocks),
        "high_impact_events": [e["name"] for e in macro_events if e["importance"] == "high"],
    }
    results["steps"].append(step3)
    print(f"  Events: {len(macro_events)}")
    print(f"  Active blocks: {len(active_blocks)}")
    print(f"  High-impact: {step3['high_impact_events']}")
    print()

    # ── Step 4: Call Qwen3:8b for guidance ──
    print("=" * 60)
    print("STEP 4: Calling Qwen3:8b for market guidance...")
    print("=" * 60)

    full_payload = {
        "request_metadata": {
            "request_time_et": now_et.strftime("%Y-%m-%dT%H:%M:%S"),
            "request_time_gmt3": to_riyadh(datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S"),
            "guidance_valid_for_seconds": 300,
            "market": "SPX",
            "trading_mode": "shadow",
        },
        "session_summary": summary,
        "one_minute_chart": bars,
        "macro_context": macro_context,
        "risk_context": {
            "daily_pnl": 0.0,
            "remaining_daily_loss": 100.0,
            "trades_today": 0,
            "behavior_state": "CONTROLLED",
        },
    }

    # Calculate total token estimate.
    total_payload_json = json.dumps(full_payload, default=str)
    prompt_text = build_system_prompt()
    total_tokens = (len(total_payload_json) + len(prompt_text)) // 4
    print(f"  Total payload: {len(total_payload_json):,} chars (~{total_tokens:,} tokens)")
    print(f"  Qwen3:8b context: 32,768 tokens")
    print(f"  Context utilization: {total_tokens / 32768 * 100:.1f}%")
    if total_tokens > 32768:
        print("  ⚠️  EXCEEDS CONTEXT WINDOW — response may be degraded")
    else:
        print("  ✅ Fits within context window")
    print()

    if provider == "mlx":
        client_model = model or "mlx-community/Qwen2.5-7B-Instruct-4bit"
    else:
        client_model = model or "qwen3:8b"

    client = make_llm_client(
        provider=provider,
        model=client_model,
        temperature=0.1,
        max_tokens=2000,
        timeout=300.0,
    )
    start = time.monotonic()

    try:
        raw_output = await client.guidance(full_payload, prompt_text)
        elapsed = time.monotonic() - start
        guidance = parse_guidance_response(raw_output)

        step4 = {
            "step": "llm_guidance",
            "status": "success",
            "elapsed_seconds": round(elapsed, 1),
            "total_tokens_estimate": total_tokens,
            "context_utilization_pct": round(total_tokens / 32768 * 100, 1),
            "guidance": {
                "trade_permission": guidance.trade_permission,
                "direction": guidance.direction,
                "market_state": guidance.market_state,
                "trigger_level": guidance.trigger_level,
                "invalidation_level": guidance.invalidation_level,
                "target_1": guidance.target_1,
                "target_2": guidance.target_2,
                "stop_level": guidance.stop_level,
                "risk_mode": guidance.risk_mode,
                "reasoning": guidance.reasoning,
                "confidence": guidance.confidence,
            },
        }
        results["steps"].append(step4)

        print(f"  ⏱️  Inference time: {elapsed:.1f}s")
        print(f"  📊 Trade Permission: {guidance.trade_permission}")
        print(f"  📈 Direction: {guidance.direction}")
        print(f"  💡 Market State: {guidance.market_state}")
        if guidance.trigger_level:
            print(f"  🎯 Trigger: {guidance.trigger_level}")
        if guidance.invalidation_level:
            print(f"  ❌ Invalidation: {guidance.invalidation_level}")
        if guidance.target_1:
            print(f"  🏁 Target 1: {guidance.target_1}")
        if guidance.target_2:
            print(f"  🏁 Target 2: {guidance.target_2}")
        if guidance.stop_level:
            print(f"  🛑 Stop: {guidance.stop_level}")
        print(f"  🔒 Risk Mode: {guidance.risk_mode}")
        print(f"  🧠 Reasoning: {guidance.reasoning}")
        print(f"  📏 Confidence: {guidance.confidence}")

    except Exception as exc:
        elapsed = time.monotonic() - start
        step4 = {
            "step": "llm_guidance",
            "status": "error",
            "error": str(exc),
            "elapsed_seconds": round(elapsed, 1),
        }
        results["steps"].append(step4)
        results["errors"].append(str(exc))
        print(f"  ❌ LLM call failed after {elapsed:.1f}s: {exc}")

    await client.close()
    print()

    # ── Step 5: Write results to file ──
    print("=" * 60)
    print("STEP 5: Saving backtest results...")
    print("=" * 60)

    results["completed_at_et"] = to_et(datetime.now(timezone.utc)).isoformat()
    results["completed_at_gmt3"] = to_riyadh(datetime.now(timezone.utc)).isoformat()

    output_path = Path(__file__).resolve().parent / "backtest_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"  Results saved to: {output_path}")
    print()

    # Also write to the data directory for the API to serve.
    data_dir = Path(__file__).resolve().parents[2] / "data"
    data_dir.mkdir(exist_ok=True)
    api_path = data_dir / "latest_backtest.json"
    with open(api_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  API results saved to: {api_path}")

    # ── Summary ──
    print()
    print("=" * 60)
    print("BACKTEST SUMMARY")
    print("=" * 60)
    for step in results["steps"]:
        status = step.get("status", "done")
        icon = "✅" if status == "success" else "⚠️" if status == "fallback_database" else "❌" if status == "error" else "✅"
        print(f"  {icon} {step['step']}: {status}")
    if results["errors"]:
        print(f"  Errors: {results['errors']}")

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="mlx", choices=["mlx", "ollama", "stub"])
    parser.add_argument("--model", default=None)
    args = parser.parse_args()
    asyncio.run(run_backtest(provider=args.provider, model=args.model))
