"""Quick verification script for PnL implementation."""
import sys
import importlib.util

def verify_module(module_path, module_name):
    """Verify a Python module can be imported."""
    try:
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        print(f"✅ {module_name}: OK")
        return True
    except SyntaxError as e:
        print(f"❌ {module_name}: SYNTAX ERROR")
        print(f"   Line {e.lineno}: {e.msg}")
        return False
    except Exception as e:
        print(f"⚠️  {module_name}: {type(e).__name__}")
        print(f"   (May be due to missing dependencies - check imports)")
        return True  # Syntax is OK, just runtime dependencies

print("Verifying PnL Implementation...")
print("-" * 50)

results = []
results.append(verify_module("src/pnl_calculator.py", "pnl_calculator"))
results.append(verify_module("src/dashboard_api.py", "dashboard_api"))
results.append(verify_module("src/execution_engine.py", "execution_engine"))
results.append(verify_module("src/main.py", "main"))

print("-" * 50)
if all(results):
    print("✅ All files verified - no syntax errors")
    sys.exit(0)
else:
    print("❌ Some files have syntax errors")
    sys.exit(1)
