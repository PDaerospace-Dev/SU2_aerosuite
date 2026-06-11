"""
Test script to verify all modules can be imported correctly.
"""

print("Testing AeroSuite Pro modular structure...")
print("-" * 50)

try:
    # Test package import
    import aerosuite
    print("✓ aerosuite package imported")
    print(f"  Version: {aerosuite.__version__}")
    
    # Test core modules
    from aerosuite.core import ISACalculator, SU2Generator, SU2Monitor
    print("✓ core.ISACalculator imported")
    print("✓ core.SU2Generator imported")
    print("✓ core.SU2Monitor imported")
    
    # Test utility modules
    from aerosuite.utils import validators, file_handlers
    print("✓ utils.validators imported")
    print("✓ utils.file_handlers imported")
    
    # Test UI modules (PyQt5 required)
    try:
        from aerosuite.ui import ISATab, SU2Tab, MonitorTab
        print("✓ ui.ISATab imported")
        print("✓ ui.SU2Tab imported")
        print("✓ ui.MonitorTab imported")
    except ImportError as e:
        print(f"✗ UI modules require PyQt5: {e}")
    
    # Test main module
    from aerosuite import main
    print("✓ main module imported")
    
    print("-" * 50)
    print("All imports successful!")
    print("\nModule structure verified ✓")
    
except ImportError as e:
    print(f"\n✗ Import error: {e}")
    print("\nPlease ensure all dependencies are installed:")
    print("  pip install -r aerosuite/requirements.txt")
