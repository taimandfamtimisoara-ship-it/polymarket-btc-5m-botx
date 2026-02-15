"""Test PnL calculation logic (unit test)."""

def calculate_pnl(entry_price: float, current_price: float, size: float, direction: str) -> float:
    """
    Calculate P&L for a position.
    
    Args:
        entry_price: Price paid (0.0-1.0)
        current_price: Current market price (0.0-1.0)
        size: Position size in USD
        direction: "YES" or "NO"
    
    Returns:
        Unrealized P&L in USD
    """
    # Calculate shares bought
    shares = size / entry_price
    
    # Calculate current value
    current_value = shares * current_price
    
    # For YES: profit if price went up
    # For NO: profit if price went down (inverse)
    if direction == "YES":
        pnl = current_value - size
    else:  # NO position
        # NO token: if we bought NO @ 0.48, and price goes to 0.42, we profit
        # Because YES went down means NO went up in value
        pnl = current_value - size
    
    return pnl


def test_yes_position_profit():
    """Test YES position with profit."""
    # Bought YES @ $0.52 for $100
    # Current price: $0.58
    pnl = calculate_pnl(0.52, 0.58, 100.0, "YES")
    
    # Expected: (100/0.52) * 0.58 - 100 = 192.31 * 0.58 - 100 = 111.54 - 100 = +11.54
    assert abs(pnl - 11.54) < 0.01, f"Expected ~11.54, got {pnl}"
    print(f"✅ YES profit: entry=0.52, current=0.58, size=$100 → PnL=${pnl:.2f}")


def test_yes_position_loss():
    """Test YES position with loss."""
    # Bought YES @ $0.52 for $100
    # Current price: $0.45
    pnl = calculate_pnl(0.52, 0.45, 100.0, "YES")
    
    # Expected: (100/0.52) * 0.45 - 100 = 192.31 * 0.45 - 100 = 86.54 - 100 = -13.46
    assert abs(pnl - (-13.46)) < 0.01, f"Expected ~-13.46, got {pnl}"
    print(f"✅ YES loss: entry=0.52, current=0.45, size=$100 → PnL=${pnl:.2f}")


def test_no_position_profit():
    """Test NO position with profit."""
    # Bought NO @ $0.48 for $100
    # Current price: $0.55 (NO price increased)
    pnl = calculate_pnl(0.48, 0.55, 100.0, "NO")
    
    # Expected: (100/0.48) * 0.55 - 100 = 208.33 * 0.55 - 100 = 114.58 - 100 = +14.58
    assert abs(pnl - 14.58) < 0.01, f"Expected ~14.58, got {pnl}"
    print(f"✅ NO profit: entry=0.48, current=0.55, size=$100 → PnL=${pnl:.2f}")


def test_no_position_loss():
    """Test NO position with loss."""
    # Bought NO @ $0.48 for $100
    # Current price: $0.40 (NO price decreased)
    pnl = calculate_pnl(0.48, 0.40, 100.0, "NO")
    
    # Expected: (100/0.48) * 0.40 - 100 = 208.33 * 0.40 - 100 = 83.33 - 100 = -16.67
    assert abs(pnl - (-16.67)) < 0.01, f"Expected ~-16.67, got {pnl}"
    print(f"✅ NO loss: entry=0.48, current=0.40, size=$100 → PnL=${pnl:.2f}")


def test_break_even():
    """Test position at break-even."""
    pnl = calculate_pnl(0.50, 0.50, 100.0, "YES")
    assert abs(pnl) < 0.01, f"Expected ~0, got {pnl}"
    print(f"✅ Break-even: entry=0.50, current=0.50, size=$100 → PnL=${pnl:.2f}")


def test_portfolio_total():
    """Test total portfolio PnL calculation."""
    # Position 1: YES profit
    pnl1 = calculate_pnl(0.52, 0.58, 100.0, "YES")  # +11.54
    
    # Position 2: NO loss
    pnl2 = calculate_pnl(0.48, 0.40, 100.0, "NO")   # -16.67
    
    # Realized PnL from closed positions
    realized_pnl = 25.00  # Previous wins
    
    # Total PnL
    total_unrealized = pnl1 + pnl2  # -5.13
    total_pnl = total_unrealized + realized_pnl  # 19.87
    
    print(f"✅ Portfolio: unrealized=${total_unrealized:.2f}, realized=${realized_pnl:.2f}, total=${total_pnl:.2f}")


if __name__ == "__main__":
    print("Testing PnL Calculation Logic")
    print("=" * 60)
    
    test_yes_position_profit()
    test_yes_position_loss()
    test_no_position_profit()
    test_no_position_loss()
    test_break_even()
    test_portfolio_total()
    
    print("=" * 60)
    print("✅ All PnL calculation tests passed!")
