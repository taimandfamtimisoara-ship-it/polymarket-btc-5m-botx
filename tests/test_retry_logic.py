"""
Test script for retry logic implementation.
Run this after deployment to verify retry behavior.
"""
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from src.execution_engine import (
    ExecutionEngine,
    NetworkError,
    InsufficientBalanceError,
    InvalidOrderError
)


async def test_network_error_retry():
    """Test that network errors trigger retries."""
    print("Testing network error retry...")
    
    mock_client = Mock()
    
    # Simulate 2 failures then success
    mock_client.create_order = AsyncMock(
        side_effect=[
            Exception("Connection timeout"),
            Exception("Gateway timeout (504)"),
            {"orderID": "test-123", "status": "success"}
        ]
    )
    
    engine = ExecutionEngine(mock_client)
    
    # Create a dummy order
    from py_clob_client.clob_types import OrderArgs, OrderType
    from decimal import Decimal
    
    order = OrderArgs(
        token_id="test",
        price=Decimal("0.5"),
        size=Decimal("10"),
        side="BUY",
        orderType=OrderType.GTC
    )
    
    result = await engine._submit_order_with_retry(order)
    
    assert result["orderID"] == "test-123"
    assert mock_client.create_order.call_count == 3
    assert engine.retry_stats['total_retries'] == 2
    assert engine.retry_stats['successful_retries'] == 1
    assert engine.retry_stats['network_errors'] == 2
    
    print("✅ Network error retry test passed!")


async def test_balance_error_no_retry():
    """Test that balance errors don't trigger retries."""
    print("Testing balance error (no retry)...")
    
    mock_client = Mock()
    mock_client.create_order = AsyncMock(
        side_effect=Exception("Insufficient balance")
    )
    
    engine = ExecutionEngine(mock_client)
    
    from py_clob_client.clob_types import OrderArgs, OrderType
    from decimal import Decimal
    
    order = OrderArgs(
        token_id="test",
        price=Decimal("0.5"),
        size=Decimal("10"),
        side="BUY",
        orderType=OrderType.GTC
    )
    
    try:
        await engine._submit_order_with_retry(order)
        assert False, "Should have raised InsufficientBalanceError"
    except InsufficientBalanceError:
        pass
    
    assert mock_client.create_order.call_count == 1  # Only tried once
    assert engine.retry_stats['balance_errors'] == 1
    assert engine.retry_stats['total_retries'] == 0  # No retries
    
    print("✅ Balance error (no retry) test passed!")


async def test_invalid_order_no_retry():
    """Test that invalid order errors don't trigger retries."""
    print("Testing invalid order error (no retry)...")
    
    mock_client = Mock()
    mock_client.create_order = AsyncMock(
        side_effect=Exception("Invalid token_id parameter")
    )
    
    engine = ExecutionEngine(mock_client)
    
    from py_clob_client.clob_types import OrderArgs, OrderType
    from decimal import Decimal
    
    order = OrderArgs(
        token_id="test",
        price=Decimal("0.5"),
        size=Decimal("10"),
        side="BUY",
        orderType=OrderType.GTC
    )
    
    try:
        await engine._submit_order_with_retry(order)
        assert False, "Should have raised InvalidOrderError"
    except InvalidOrderError:
        pass
    
    assert mock_client.create_order.call_count == 1  # Only tried once
    assert engine.retry_stats['invalid_order_errors'] == 1
    assert engine.retry_stats['total_retries'] == 0  # No retries
    
    print("✅ Invalid order error (no retry) test passed!")


async def test_max_retries_exceeded():
    """Test that max retries limit is enforced."""
    print("Testing max retries limit...")
    
    mock_client = Mock()
    mock_client.create_order = AsyncMock(
        side_effect=Exception("Connection timeout")  # Always fails
    )
    
    engine = ExecutionEngine(mock_client)
    
    from py_clob_client.clob_types import OrderArgs, OrderType
    from decimal import Decimal
    
    order = OrderArgs(
        token_id="test",
        price=Decimal("0.5"),
        size=Decimal("10"),
        side="BUY",
        orderType=OrderType.GTC
    )
    
    try:
        await engine._submit_order_with_retry(order, max_retries=3)
        assert False, "Should have raised NetworkError"
    except NetworkError:
        pass
    
    assert mock_client.create_order.call_count == 4  # 1 initial + 3 retries
    assert engine.retry_stats['total_retries'] == 3
    assert engine.retry_stats['failed_after_retries'] == 1
    
    print("✅ Max retries limit test passed!")


async def test_exponential_backoff_timing():
    """Test that exponential backoff delays are correct."""
    print("Testing exponential backoff timing...")
    
    import time
    
    mock_client = Mock()
    mock_client.create_order = AsyncMock(
        side_effect=Exception("Connection timeout")
    )
    
    engine = ExecutionEngine(mock_client)
    
    from py_clob_client.clob_types import OrderArgs, OrderType
    from decimal import Decimal
    
    order = OrderArgs(
        token_id="test",
        price=Decimal("0.5"),
        size=Decimal("10"),
        side="BUY",
        orderType=OrderType.GTC
    )
    
    start_time = time.time()
    
    try:
        await engine._submit_order_with_retry(order, max_retries=3, initial_delay_ms=100)
    except NetworkError:
        pass
    
    elapsed = time.time() - start_time
    
    # Expected delays: 100ms + 200ms + 400ms = 700ms = 0.7s
    # Allow some tolerance for execution time
    assert elapsed >= 0.6, f"Elapsed time {elapsed}s is too short"
    assert elapsed <= 1.0, f"Elapsed time {elapsed}s is too long"
    
    print(f"✅ Exponential backoff timing test passed! (elapsed: {elapsed:.3f}s)")


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("RETRY LOGIC TEST SUITE")
    print("="*60 + "\n")
    
    try:
        await test_network_error_retry()
        await test_balance_error_no_retry()
        await test_invalid_order_no_retry()
        await test_max_retries_exceeded()
        await test_exponential_backoff_timing()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS PASSED!")
        print("="*60 + "\n")
        
    except AssertionError as e:
        print("\n" + "="*60)
        print(f"❌ TEST FAILED: {e}")
        print("="*60 + "\n")
        raise
    except Exception as e:
        print("\n" + "="*60)
        print(f"❌ UNEXPECTED ERROR: {e}")
        print("="*60 + "\n")
        raise


if __name__ == "__main__":
    asyncio.run(main())
