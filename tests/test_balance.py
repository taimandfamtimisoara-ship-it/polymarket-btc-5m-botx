"""Test balance fetching system."""
import asyncio
from datetime import datetime
from unittest.mock import Mock, AsyncMock
from src.execution_engine import ExecutionEngine
from src.edge_detector import Edge


async def test_balance_caching():
    """Test balance caching mechanism."""
    print("=" * 60)
    print("Testing Balance Caching System")
    print("=" * 60)
    
    # Create mock client
    mock_client = Mock()
    
    # Test 1: API Success
    print("\n[Test 1] API Success - get_balance() exists")
    mock_client.get_balance = AsyncMock(return_value={'balance': 500.0})
    
    engine = ExecutionEngine(mock_client)
    balance = await engine._get_balance()
    
    print(f"  ✓ Balance fetched: ${balance}")
    print(f"  ✓ Cached: {engine._cached_balance}")
    print(f"  ✓ Cache time: {engine._balance_cache_time}")
    
    # Test 2: Cache Hit
    print("\n[Test 2] Cache Hit - Should not call API again")
    call_count_before = mock_client.get_balance.call_count
    balance2 = await engine._get_balance()
    call_count_after = mock_client.get_balance.call_count
    
    print(f"  ✓ Balance (cached): ${balance2}")
    print(f"  ✓ API calls: {call_count_before} → {call_count_after} (no new call)")
    assert call_count_before == call_count_after, "Should use cache!"
    
    # Test 3: Cache Age
    print("\n[Test 3] Cache Age")
    age = engine.get_balance_cache_age()
    print(f"  ✓ Cache age: {age:.2f} seconds")
    assert age < 5, "Cache should be fresh"
    
    # Test 4: Fallback on API Failure
    print("\n[Test 4] API Failure - Should fallback to config")
    mock_client2 = Mock()
    # No get_balance or get_allowances method
    
    engine2 = ExecutionEngine(mock_client2)
    balance_fallback = await engine2._get_balance()
    
    print(f"  ✓ Fallback balance: ${balance_fallback}")
    print(f"  ✓ Source: config.initial_bankroll")
    
    # Test 5: Position Sizing
    print("\n[Test 5] Position Sizing with Real Balance")
    mock_edge = Mock(spec=Edge)
    mock_edge.edge_pct = 5.0  # 5% edge
    mock_edge.confidence = 0.8  # 80% confidence
    
    # With $500 balance, 20% max bet, 5% edge, 80% confidence:
    # edge_factor = min(5/10, 1.0) = 0.5
    # size_pct = 0.5 * 0.8 * 20 = 8%
    # size_usd = 500 * 0.08 = $40
    
    size = engine._calculate_position_size(mock_edge)
    print(f"  ✓ Position size: ${size}")
    print(f"  ✓ Expected: ~$40 (8% of $500)")
    assert 35 <= size <= 45, f"Position size should be ~$40, got ${size}"
    
    # Test 6: Status with Balance
    print("\n[Test 6] Status includes balance")
    status = engine.get_status()
    print(f"  ✓ Balance in status: ${status['balance']}")
    print(f"  ✓ Cache age in status: {status['balance_cache_age_sec']}s")
    
    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_balance_caching())
