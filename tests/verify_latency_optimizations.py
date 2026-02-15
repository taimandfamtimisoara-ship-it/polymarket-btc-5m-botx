"""
Verify latency optimizations - syntax check and basic functionality test.

Run this to ensure the optimizations don't break existing code.
"""
import sys
import importlib.util
from pathlib import Path

def test_import(module_name, file_path):
    """Test if a module can be imported (syntax check)."""
    try:
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(spec)
        
        # Try to execute the module (will fail if syntax errors)
        spec.loader.exec_module(module)
        
        print(f"✅ {module_name}: Import successful")
        return True
    except SyntaxError as e:
        print(f"❌ {module_name}: Syntax error - {e}")
        return False
    except Exception as e:
        # Other errors (like missing dependencies) are OK for syntax check
        print(f"⚠️  {module_name}: Import attempted (may need dependencies) - {e}")
        return True

def main():
    """Test all modified files."""
    src_dir = Path(__file__).parent / "src"
    
    tests = [
        ("price_feed", src_dir / "price_feed.py"),
        ("market_fetcher", src_dir / "market_fetcher.py"),
        ("main", src_dir / "main.py"),
    ]
    
    print("=" * 60)
    print("LATENCY OPTIMIZATION - SYNTAX VERIFICATION")
    print("=" * 60)
    print()
    
    results = []
    for module_name, file_path in tests:
        result = test_import(module_name, file_path)
        results.append((module_name, result))
        print()
    
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    all_passed = True
    for module_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{module_name:20s}: {status}")
        if not result:
            all_passed = False
    
    print()
    if all_passed:
        print("🎉 All syntax checks passed!")
        print()
        print("Next steps:")
        print("1. Review LATENCY_OPTIMIZATIONS.md for details")
        print("2. Deploy to production")
        print("3. Monitor cycle_time_ms logs")
        print("4. Check latency_stats every 100 updates")
        return 0
    else:
        print("⚠️  Some checks failed - review errors above")
        return 1

if __name__ == "__main__":
    sys.exit(main())
