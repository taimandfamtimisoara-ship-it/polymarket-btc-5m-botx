"""Test script to verify Polymarket API integration fixes."""
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_imports():
    """Test that all imports work."""
    print("Testing imports...")
    
    try:
        from py_clob_client.client import ClobClient
        print("✓ py_clob_client.client imported")
    except ImportError as e:
        print(f"✗ Failed to import py_clob_client.client: {e}")
        return False
    
    try:
        from py_clob_client.clob_types import MarketOrderArgs, OrderArgs, OrderType
        print("✓ py_clob_client.clob_types imported")
    except ImportError as e:
        print(f"✗ Failed to import py_clob_client.clob_types: {e}")
        return False
    
    try:
        from py_clob_client.order_builder.constants import BUY, SELL
        print("✓ py_clob_client.order_builder.constants imported")
    except ImportError as e:
        print(f"✗ Failed to import constants: {e}")
        return False
    
    try:
        import requests
        print("✓ requests imported")
    except ImportError as e:
        print(f"✗ Failed to import requests: {e}")
        return False
    
    try:
        import structlog
        print("✓ structlog imported")
    except ImportError as e:
        print(f"✗ Failed to import structlog: {e}")
        return False
    
    print("\nAll imports successful!")
    return True


def test_market_fetcher_syntax():
    """Test that MarketFetcher loads without syntax errors."""
    print("\nTesting MarketFetcher syntax...")
    
    try:
        from market_fetcher import MarketFetcher
        print("✓ MarketFetcher imported successfully")
        
        # Check key methods exist
        assert hasattr(MarketFetcher, 'get_active_markets')
        assert hasattr(MarketFetcher, '_fetch_from_gamma_api')
        assert hasattr(MarketFetcher, '_fetch_from_clob_api')
        assert hasattr(MarketFetcher, '_is_btc_5m_market')
        assert hasattr(MarketFetcher, '_extract_baseline_price')
        print("✓ All expected methods exist")
        
        return True
        
    except Exception as e:
        print(f"✗ Failed to load MarketFetcher: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_polymarket_client_syntax():
    """Test that PolymarketClient loads without syntax errors."""
    print("\nTesting PolymarketClient syntax...")
    
    try:
        from polymarket_client import PolymarketClient
        print("✓ PolymarketClient imported successfully")
        
        # Check key methods exist
        assert hasattr(PolymarketClient, 'get_btc_5m_markets')
        assert hasattr(PolymarketClient, 'get_market_price')
        assert hasattr(PolymarketClient, 'get_midpoint')
        assert hasattr(PolymarketClient, 'place_order')
        assert hasattr(PolymarketClient, 'get_orderbook')
        print("✓ All expected methods exist")
        
        return True
        
    except Exception as e:
        print(f"✗ Failed to load PolymarketClient: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_clob_client_methods():
    """Test that ClobClient has expected methods."""
    print("\nTesting ClobClient methods...")
    
    try:
        from py_clob_client.client import ClobClient
        
        # Create a read-only client (no credentials needed)
        client = ClobClient("https://clob.polymarket.com")
        
        # Check methods exist
        expected_methods = [
            'get_simplified_markets',
            'get_markets',
            'get_market',
            'get_order_book',
            'get_midpoint',
            'get_price',
            'create_order',
            'create_market_order',
            'post_order',
            'cancel',
            'cancel_all'
        ]
        
        for method in expected_methods:
            assert hasattr(client, method), f"Missing method: {method}"
            print(f"  ✓ client.{method} exists")
        
        print("✓ All expected ClobClient methods exist")
        return True
        
    except Exception as e:
        print(f"✗ ClobClient method check failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("Polymarket API Integration Tests")
    print("=" * 60)
    
    tests = [
        test_imports,
        test_market_fetcher_syntax,
        test_polymarket_client_syntax,
        test_clob_client_methods
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"\n✗ Test failed with exception: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)
    
    print("\n" + "=" * 60)
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    
    if all(results):
        print("✓ All tests passed!")
        return 0
    else:
        print("✗ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
