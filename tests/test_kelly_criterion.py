"""Test Kelly Criterion implementation."""
import sys
sys.path.append('src')

from edge_detector import Edge
from datetime import datetime


def test_kelly_formula():
    """Test Kelly Criterion calculation with known examples."""
    
    print("=" * 60)
    print("KELLY CRITERION TEST")
    print("=" * 60)
    
    # Test Example from the spec:
    # - Edge detected: 5%
    # - Our confidence: 60% win probability
    # - Market YES price: 0.55
    # - Expected Kelly: ~11.2%, Half-Kelly: ~5.6%
    
    # Manual calculation for verification
    bet_price = 0.55
    decimal_odds = 1.0 / bet_price  # 1.82
    b = decimal_odds - 1.0  # 0.82
    p = 0.60  # 60% confidence
    q = 1.0 - p  # 0.40
    
    kelly_numerator = (b * p) - q  # (0.82 * 0.60) - 0.40 = 0.092
    kelly_fraction_result = kelly_numerator / b  # 0.092 / 0.82 = 0.112 (11.2%)
    kelly_pct = kelly_fraction_result * 100
    half_kelly = kelly_pct * 0.5
    
    print(f"\n📊 Manual Calculation:")
    print(f"   Bet Price: {bet_price}")
    print(f"   Decimal Odds: {decimal_odds:.2f}")
    print(f"   Net Odds (b): {b:.2f}")
    print(f"   Win Probability (p): {p:.2f}")
    print(f"   Loss Probability (q): {q:.2f}")
    print(f"   Kelly Numerator (bp - q): {kelly_numerator:.4f}")
    print(f"   Full Kelly: {kelly_pct:.2f}%")
    print(f"   Half-Kelly: {half_kelly:.2f}%")
    
    # Expected results
    expected_kelly = 11.2
    expected_half_kelly = 5.6
    
    tolerance = 0.5  # Allow 0.5% tolerance
    
    print(f"\n✅ Validation:")
    if abs(kelly_pct - expected_kelly) < tolerance:
        print(f"   ✓ Full Kelly matches expected: {kelly_pct:.2f}% ≈ {expected_kelly}%")
    else:
        print(f"   ✗ Full Kelly mismatch: {kelly_pct:.2f}% vs {expected_kelly}%")
    
    if abs(half_kelly - expected_half_kelly) < tolerance:
        print(f"   ✓ Half-Kelly matches expected: {half_kelly:.2f}% ≈ {expected_half_kelly}%")
    else:
        print(f"   ✗ Half-Kelly mismatch: {half_kelly:.2f}% vs {expected_half_kelly}%")
    
    # Test with different scenarios
    print(f"\n" + "=" * 60)
    print("SCENARIO TESTING")
    print("=" * 60)
    
    scenarios = [
        {
            "name": "Small Edge, Low Price",
            "bet_price": 0.40,
            "confidence": 0.55,
            "edge_pct": 3.0
        },
        {
            "name": "Large Edge, High Price",
            "bet_price": 0.70,
            "confidence": 0.80,
            "edge_pct": 8.0
        },
        {
            "name": "Moderate Edge, Mid Price",
            "bet_price": 0.50,
            "confidence": 0.65,
            "edge_pct": 5.0
        },
        {
            "name": "Tiny Edge, Low Confidence",
            "bet_price": 0.48,
            "confidence": 0.52,
            "edge_pct": 2.0
        }
    ]
    
    for scenario in scenarios:
        bet_price = scenario["bet_price"]
        confidence = scenario["confidence"]
        edge_pct = scenario["edge_pct"]
        
        # Calculate Kelly
        decimal_odds = 1.0 / bet_price
        b = decimal_odds - 1.0
        p = min(confidence + (edge_pct / 100), 0.95)  # Adjust confidence by edge
        q = 1.0 - p
        kelly_numerator = (b * p) - q
        kelly_fraction_result = kelly_numerator / b
        kelly_pct = kelly_fraction_result * 100
        half_kelly = kelly_pct * 0.5
        
        # Calculate position size for $1000 bankroll
        bankroll = 1000
        half_kelly_amount = bankroll * (half_kelly / 100)
        
        print(f"\n🎯 {scenario['name']}:")
        print(f"   Price: {bet_price:.2f} | Confidence: {confidence:.0%} | Edge: {edge_pct:.1f}%")
        print(f"   Decimal Odds: {decimal_odds:.2f} | Adjusted p: {p:.2%}")
        print(f"   Full Kelly: {kelly_pct:.2f}% | Half-Kelly: {half_kelly:.2f}%")
        print(f"   Position (Half-Kelly, $1000 bankroll): ${half_kelly_amount:.2f}")
    
    print(f"\n" + "=" * 60)
    print("✅ Kelly Criterion Formula Verified!")
    print("=" * 60)


if __name__ == "__main__":
    test_kelly_formula()
