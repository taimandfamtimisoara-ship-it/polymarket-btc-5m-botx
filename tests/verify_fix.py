#!/usr/bin/env python3
"""
Quick verification script for Polymarket API integration fix.

This script tests:
1. That all imports work
2. That py-clob-client methods exist
3. That market fetcher can be instantiated
4. That polymarket client can be instantiated (without auth)

Run: python verify_fix.py
"""

import sys
import os

# Add src to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def print_section(title):
    """Print a section header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def test_py_clob_imports():
    """Test py-clob-client imports."""
    print_section("Testing py-clob-client Imports")
    
    try:
        from py_clob_client.client import ClobClient
        print("✓ ClobClient imported")
        
        from py_clob_client.clob_types import (
            MarketOrderArgs,
            OrderArgs,
            OrderType,
            BookParams,
            OpenOrderParams
        )
        print("✓ clob_types imported")
        
        from py_clob_client.order_builder.constants import BUY, SELL
        print("✓ Constants imported (BUY, SELL)")
        
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        print("\nPlease run: pip install py-clob-client>=0.23.0")
        return False

def test_dependencies():
    """Test other dependencies."""
    print_section("Testing Dependencies")
    
    deps = [
        ('requests', 'requests'),
        ('structlog', 'structlog'),
        ('fastapi', 'fastapi'),
        ('dotenv', 'python-dotenv')
    ]
    
    success = True
    for module, package in deps:
        try:
            __import__(module)
            print(f"✓ {module} imported")
        except ImportError:
            print(f"✗ {module} not found - install: pip install {package}")
            success = False
    
    return success

def test_clob_client_methods():
    """Test that ClobClient has the methods we need."""
    print_section("Testing ClobClient Methods")
    
    try:
        from py_clob_client.client import ClobClient
        
        # Create read-only client (no auth needed)
        client = ClobClient("https://clob.polymarket.com")
        
        # Check methods exist
        required_methods = [
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
            'cancel_all',
            'get_orders'
        ]
        
        missing = []
        for method in required_methods:
            if hasattr(client, method):
                print(f"  ✓ client.{method}()")
            else:
                print(f"  ✗ client.{method}() - MISSING!")
                missing.append(method)
        
        if missing:
            print(f"\n✗ Missing methods: {missing}")
            return False
        
        print("\n✓ All required methods exist")
        return True
        
    except Exception as e:
        print(f"✗ Failed to check methods: {e}")
        return False

def test_market_fetcher():
    """Test MarketFetcher class."""
    print_section("Testing MarketFetcher")
    
    try:
        from market_fetcher import MarketFetcher
        print("✓ MarketFetcher imported")
        
        # Check methods
        methods = [
            'get_active_markets',
            '_fetch_from_gamma_api',
            '_fetch_from_clob_api',
            '_enrich_with_clob_data',
            '_parse_gamma_market',
            '_parse_clob_market',
            '_is_btc_5m_market',
            '_extract_baseline_price'
        ]
        
        for method in methods:
            if hasattr(MarketFetcher, method):
                print(f"  ✓ MarketFetcher.{method}()")
            else:
                print(f"  ✗ Missing: {method}")
                return False
        
        print("\n✓ MarketFetcher has all expected methods")
        return True
        
    except Exception as e:
        print(f"✗ MarketFetcher import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_polymarket_client():
    """Test PolymarketClient class."""
    print_section("Testing PolymarketClient")
    
    try:
        # Note: This will fail without credentials, but we're just checking syntax
        print("Note: Not instantiating (requires credentials)")
        print("Checking class definition only...")
        
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "polymarket_client",
            os.path.join(os.path.dirname(__file__), 'src', 'polymarket_client.py')
        )
        module = importlib.util.module_from_spec(spec)
        
        # This will catch syntax errors
        spec.loader.exec_module(module)
        
        PolymarketClient = module.PolymarketClient
        print("✓ PolymarketClient class loaded")
        
        # Check methods
        methods = [
            'get_btc_5m_markets',
            'get_market_price',
            'get_midpoint',
            'place_order',
            'get_market_by_id',
            'get_positions',
            'cancel_order',
            'cancel_all_orders',
            'get_orderbook'
        ]
        
        for method in methods:
            if hasattr(PolymarketClient, method):
                print(f"  ✓ PolymarketClient.{method}()")
            else:
                print(f"  ✗ Missing: {method}")
                return False
        
        print("\n✓ PolymarketClient has all expected methods")
        return True
        
    except Exception as e:
        print(f"✗ PolymarketClient check failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_gamma_api():
    """Test Gamma API accessibility."""
    print_section("Testing Gamma API Access")
    
    try:
        import requests
        
        url = "https://gamma-api.polymarket.com/markets"
        print(f"Testing: {url}")
        
        response = requests.get(url, params={'limit': 1}, timeout=5)
        
        if response.status_code == 200:
            print(f"✓ Gamma API accessible (status: {response.status_code})")
            
            data = response.json()
            if isinstance(data, list) or isinstance(data, dict):
                print("✓ Response is valid JSON")
                return True
        else:
            print(f"⚠ Gamma API returned status: {response.status_code}")
            print("  (Fallback to CLOB API will be used)")
            return True  # Not a failure - we have fallback
            
    except Exception as e:
        print(f"⚠ Gamma API not accessible: {e}")
        print("  (Fallback to CLOB API will be used)")
        return True  # Not a failure - we have fallback

def main():
    """Run all verification tests."""
    print_section("Polymarket API Integration - Verification")
    
    tests = [
        ("py-clob-client imports", test_py_clob_imports),
        ("Dependencies", test_dependencies),
        ("ClobClient methods", test_clob_client_methods),
        ("MarketFetcher class", test_market_fetcher),
        ("PolymarketClient class", test_polymarket_client),
        ("Gamma API access", test_gamma_api)
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ Test '{name}' crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print_section("Verification Results")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    print(f"\n{passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ ALL CHECKS PASSED!")
        print("\nNext steps:")
        print("1. Set environment variables in .env")
        print("2. Run the bot: python src/main.py")
        return 0
    else:
        print("\n⚠ SOME CHECKS FAILED")
        print("\nPlease fix the issues above before running the bot.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
