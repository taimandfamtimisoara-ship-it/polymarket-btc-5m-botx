"""Quick test of momentum indicators implementation."""
import sys
sys.path.insert(0, 'src')

from indicators import momentum_indicators
import numpy as np


def test_rsi():
    """Test RSI calculation."""
    print("\n=== Testing RSI ===")
    
    # Uptrend prices (should have low RSI initially, then high)
    uptrend = [100, 102, 104, 103, 105, 107, 106, 108, 110, 112, 111, 113, 115, 117, 119]
    rsi_up = momentum_indicators.calculate_rsi(uptrend)
    print(f"Uptrend RSI: {rsi_up:.2f} (should be >50, likely >70 = overbought)")
    
    # Downtrend prices (should have high RSI initially, then low)
    downtrend = [100, 98, 96, 97, 95, 93, 94, 92, 90, 88, 89, 87, 85, 83, 81]
    rsi_down = momentum_indicators.calculate_rsi(downtrend)
    print(f"Downtrend RSI: {rsi_down:.2f} (should be <50, likely <30 = oversold)")
    
    # Sideways (should be near 50)
    sideways = [100, 101, 99, 100, 101, 99, 100, 101, 99, 100, 101, 99, 100, 101, 100]
    rsi_sideways = momentum_indicators.calculate_rsi(sideways)
    print(f"Sideways RSI: {rsi_sideways:.2f} (should be ~50 = neutral)")
    
    assert rsi_up > 70, "Uptrend RSI should be overbought"
    assert rsi_down < 30, "Downtrend RSI should be oversold"
    assert 45 < rsi_sideways < 55, "Sideways RSI should be neutral"
    
    print("✅ RSI tests passed!")


def test_macd():
    """Test MACD calculation."""
    print("\n=== Testing MACD ===")
    
    # Need at least 35 data points for MACD
    # Generate uptrend
    uptrend = [100 + i*0.5 for i in range(40)]
    macd_result = momentum_indicators.calculate_macd(uptrend)
    
    if macd_result:
        macd_line, signal_line, histogram = macd_result
        print(f"Uptrend MACD line: {macd_line:.4f}")
        print(f"Uptrend Signal line: {signal_line:.4f}")
        print(f"Uptrend Histogram: {histogram:.4f}")
        print(f"Should be positive (bullish)")
        assert macd_line > 0, "Uptrend MACD should be positive"
    
    # Downtrend
    downtrend = [100 - i*0.5 for i in range(40)]
    macd_result = momentum_indicators.calculate_macd(downtrend)
    
    if macd_result:
        macd_line, signal_line, histogram = macd_result
        print(f"\nDowntrend MACD line: {macd_line:.4f}")
        print(f"Downtrend Signal line: {signal_line:.4f}")
        print(f"Downtrend Histogram: {histogram:.4f}")
        print(f"Should be negative (bearish)")
        assert macd_line < 0, "Downtrend MACD should be negative"
    
    print("✅ MACD tests passed!")


def test_signals():
    """Test combined signals and alignment."""
    print("\n=== Testing Combined Signals ===")
    
    # Bullish scenario
    bullish_prices = [100 + i*0.3 for i in range(40)]
    signals = momentum_indicators.get_signals(bullish_prices)
    
    print(f"\nBullish scenario:")
    print(f"  RSI: {signals.rsi:.2f} ({signals.rsi_signal})")
    print(f"  MACD: {signals.macd_trend}")
    print(f"  Alignment: {signals.alignment_score:.2f}")
    print(f"  Should be positive alignment (bullish)")
    
    assert signals.alignment_score > 0, "Bullish scenario should have positive alignment"
    
    # Bearish scenario
    bearish_prices = [100 - i*0.3 for i in range(40)]
    signals = momentum_indicators.get_signals(bearish_prices)
    
    print(f"\nBearish scenario:")
    print(f"  RSI: {signals.rsi:.2f} ({signals.rsi_signal})")
    print(f"  MACD: {signals.macd_trend}")
    print(f"  Alignment: {signals.alignment_score:.2f}")
    print(f"  Should be negative alignment (bearish)")
    
    assert signals.alignment_score < 0, "Bearish scenario should have negative alignment"
    
    print("✅ Signals tests passed!")


def test_confidence_boost():
    """Test confidence adjustment."""
    print("\n=== Testing Confidence Boost ===")
    
    # Bullish signals
    bullish_prices = [100 + i*0.3 for i in range(40)]
    signals = momentum_indicators.get_signals(bullish_prices)
    
    # YES direction (bullish) with bullish indicators → should boost
    base_confidence = 0.5
    boosted = momentum_indicators.boost_confidence(base_confidence, "YES", signals)
    print(f"\nBullish indicators + YES edge:")
    print(f"  Base confidence: {base_confidence:.2f}")
    print(f"  Boosted: {boosted:.2f}")
    print(f"  Change: +{(boosted - base_confidence)*100:.1f}%")
    assert boosted > base_confidence, "Should boost confidence"
    
    # NO direction (bearish) with bullish indicators → should reduce
    reduced = momentum_indicators.boost_confidence(base_confidence, "NO", signals)
    print(f"\nBullish indicators + NO edge (conflict):")
    print(f"  Base confidence: {base_confidence:.2f}")
    print(f"  Reduced: {reduced:.2f}")
    print(f"  Change: {(reduced - base_confidence)*100:.1f}%")
    assert reduced < base_confidence, "Should reduce confidence on conflict"
    
    print("✅ Confidence boost tests passed!")


if __name__ == "__main__":
    print("Testing Momentum Indicators Implementation")
    print("=" * 50)
    
    try:
        test_rsi()
        test_macd()
        test_signals()
        test_confidence_boost()
        
        print("\n" + "=" * 50)
        print("🎉 All tests passed!")
        print("=" * 50)
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
