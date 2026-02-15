"""
Verify survival_brain integration is working.

Run this before deploying to production.
"""
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_imports():
    """Test that all imports work."""
    print("🧪 Testing imports...")
    
    try:
        from survival_brain import SurvivalBrain, SurvivalState
        print("  ✅ SurvivalBrain import OK")
    except Exception as e:
        print(f"  ❌ Failed to import SurvivalBrain: {e}")
        return False
    
    try:
        from execution_engine import ExecutionEngine
        print("  ✅ ExecutionEngine import OK")
    except Exception as e:
        print(f"  ❌ Failed to import ExecutionEngine: {e}")
        return False
    
    try:
        import dashboard_api
        print("  ✅ dashboard_api import OK")
    except Exception as e:
        print(f"  ❌ Failed to import dashboard_api: {e}")
        return False
    
    return True


def test_survival_brain_init():
    """Test survival brain initialization."""
    print("\n🧪 Testing SurvivalBrain initialization...")
    
    try:
        from survival_brain import SurvivalBrain, SurvivalState
        
        # Initialize without telegram
        brain = SurvivalBrain(
            initial_capital=100.0,
            telegram_alerter=None
        )
        
        print(f"  ✅ Initialized with capital: ${brain.current_capital:.2f}")
        print(f"  ✅ Initial state: {brain.current_state.value}")
        
        # Check methods exist
        assert hasattr(brain, 'should_take_trade'), "Missing should_take_trade method"
        assert hasattr(brain, 'get_position_size_modifier'), "Missing get_position_size_modifier method"
        assert hasattr(brain, 'record_trade_result'), "Missing record_trade_result method"
        assert hasattr(brain, 'get_survival_status'), "Missing get_survival_status method"
        print("  ✅ All required methods present")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_survival_brain_api():
    """Test survival brain API methods."""
    print("\n🧪 Testing SurvivalBrain API...")
    
    try:
        from survival_brain import SurvivalBrain
        
        brain = SurvivalBrain(initial_capital=100.0, telegram_alerter=None)
        
        # Test should_take_trade
        should_take, reason = brain.should_take_trade(
            edge=5.0,
            market_type="btc_5m",
            hour=14
        )
        print(f"  ✅ should_take_trade: {should_take} (reason: {reason})")
        
        # Test position size modifier
        modifier = brain.get_position_size_modifier()
        print(f"  ✅ get_position_size_modifier: {modifier:.2f}x")
        
        # Test record trade result
        brain.record_trade_result({
            'timestamp': '2026-02-15T14:30:00',
            'market_type': 'btc_5m',
            'edge': 0.05,
            'amount': 10.0,
            'pnl': 0.50,
            'won': True
        })
        print(f"  ✅ record_trade_result: Capital now ${brain.current_capital:.2f}")
        
        # Test get survival status
        status = brain.get_survival_status()
        print(f"  ✅ get_survival_status: {status.state.value}")
        print(f"     - Capital: ${status.current_capital:.2f} ({status.capital_pct:.1f}%)")
        print(f"     - Kelly modifier: {status.kelly_modifier:.2f}x")
        print(f"     - Min edge: {status.min_edge_threshold:.1f}%")
        
        return True
        
    except Exception as e:
        print(f"  ❌ API test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_execution_engine_integration():
    """Test that ExecutionEngine has survival_brain parameter."""
    print("\n🧪 Testing ExecutionEngine integration...")
    
    try:
        from execution_engine import ExecutionEngine
        from survival_brain import SurvivalBrain
        import inspect
        
        # Check __init__ signature
        sig = inspect.signature(ExecutionEngine.__init__)
        params = list(sig.parameters.keys())
        
        if 'survival_brain' in params:
            print("  ✅ ExecutionEngine.__init__ has survival_brain parameter")
        else:
            print(f"  ❌ survival_brain not in __init__ parameters: {params}")
            return False
        
        # Check set_survival_brain method exists
        if hasattr(ExecutionEngine, 'set_survival_brain'):
            print("  ✅ ExecutionEngine.set_survival_brain method exists")
        else:
            print("  ❌ set_survival_brain method missing")
            return False
        
        return True
        
    except Exception as e:
        print(f"  ❌ Integration check failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_dashboard_integration():
    """Test that dashboard_api has survival endpoint."""
    print("\n🧪 Testing dashboard_api integration...")
    
    try:
        import dashboard_api
        
        # Check set_survival_brain function exists
        if hasattr(dashboard_api, 'set_survival_brain'):
            print("  ✅ dashboard_api.set_survival_brain exists")
        else:
            print("  ❌ set_survival_brain function missing")
            return False
        
        # Check global survival_brain variable exists
        if hasattr(dashboard_api, 'survival_brain'):
            print("  ✅ dashboard_api.survival_brain global exists")
        else:
            print("  ❌ survival_brain global missing")
            return False
        
        # Check /api/survival endpoint exists
        # (We can't easily test FastAPI routes without running the server,
        #  but we can check the function exists)
        if hasattr(dashboard_api, 'get_survival_status'):
            print("  ✅ get_survival_status endpoint function exists")
        else:
            print("  ⚠️  get_survival_status endpoint function not found (might be inline)")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Dashboard integration check failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all verification tests."""
    print("=" * 60)
    print("SURVIVAL BRAIN INTEGRATION VERIFICATION")
    print("=" * 60)
    
    results = []
    
    results.append(("Imports", test_imports()))
    results.append(("SurvivalBrain Init", test_survival_brain_init()))
    results.append(("SurvivalBrain API", test_survival_brain_api()))
    results.append(("ExecutionEngine Integration", test_execution_engine_integration()))
    results.append(("Dashboard Integration", test_dashboard_integration()))
    
    print("\n" + "=" * 60)
    print("VERIFICATION RESULTS")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status:10} {test_name}")
    
    all_passed = all(result[1] for result in results)
    
    print("=" * 60)
    
    if all_passed:
        print("🎉 ALL TESTS PASSED - Integration verified!")
        print("✅ Ready for deployment")
        return 0
    else:
        print("⚠️  SOME TESTS FAILED - Fix before deploying")
        return 1


if __name__ == "__main__":
    exit(main())
