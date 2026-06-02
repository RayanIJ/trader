#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.main import get_trading_bot

def test_docker():
    print("🧪 Testing Docker container functionality...")
    bot = get_trading_bot()

    # Test analyze-only cycle
    result = bot.run_manual_cycle('AAPL', analyze_only=True)

    print(f"✅ Analyze cycle result: {result.success}")
    if result.indicators:
        print(f"✅ Price: ${result.indicators.get('current_price'):.2f}")
        print(f"✅ RSI: {result.indicators.get('rsi'):.2f}")
        print(f"✅ MACD: {result.indicators.get('macd_crossover')}")
        print(f"✅ Data source: {result.indicators.get('price_source')}")
    else:
        print("❌ No indicators returned")

    if result.recommendation:
        print(f"✅ AI recommendation: {result.recommendation.action} ({result.recommendation.confidence:.2f})")
    else:
        print("❌ No recommendation returned")

if __name__ == "__main__":
    test_docker()
