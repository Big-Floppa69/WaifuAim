#!/usr/bin/env python3
"""
Python Environment Checker for WaifuAim
This script checks if the required Python dependencies are installed correctly.
"""
import sys
import subprocess
import importlib.util

def check_python_version():
    """Check if Python version is 3.8 or higher."""
    print(f"Python version: {sys.version}")
    if sys.version_info >= (3, 8):
        print("✓ Python version is compatible (3.8+)")
        return True
    else:
        print("✗ Python version is too old. Please install Python 3.8 or higher.")
        return False

def check_pip():
    """Check if pip is available."""
    try:
        result = subprocess.run([sys.executable, '-m', 'pip', '--version'], 
                              capture_output=True, text=True, check=True)
        print(f"✓ pip is available: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError:
        print("✗ pip is not available")
        return False

def check_package(package_name, import_name=None):
    """Check if a package is installed and can be imported."""
    if import_name is None:
        import_name = package_name
    
    try:
        spec = importlib.util.find_spec(import_name)
        if spec is not None:
            print(f"✓ {package_name} is installed")
            return True
        else:
            print(f"✗ {package_name} is not installed")
            return False
    except ImportError:
        print(f"✗ {package_name} is not installed")
        return False

def check_dependencies():
    """Check all required dependencies."""
    required_packages = [
        ('PyQt6', 'PyQt6'),
        ('keyboard', 'keyboard')
    ]
    
    print("\nChecking required packages:")
    all_good = True
    
    for package_name, import_name in required_packages:
        if not check_package(package_name, import_name):
            all_good = False
    
    return all_good

def main():
    """Main function to run all checks."""
    print("=== WaifuAim - Environment Check ===\n")
    
    checks_passed = 0
    total_checks = 3
    
    # Check Python version
    if check_python_version():
        checks_passed += 1
    
    # Check pip
    if check_pip():
        checks_passed += 1
    
    # Check dependencies
    if check_dependencies():
        checks_passed += 1
    
    print(f"\n=== Summary ===")
    print(f"Checks passed: {checks_passed}/{total_checks}")
    
    if checks_passed == total_checks:
        print("✓ All checks passed! The application should run correctly.")
        return 0
    else:
        print("✗ Some checks failed. Please install the missing dependencies.")
        print("Run 'install_dependencies.bat' to install all required packages.")
        return 1

if __name__ == "__main__":
    sys.exit(main())