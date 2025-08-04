#!/usr/bin/env python3
"""
CRC Verification Script

Run this script before and after making CRC-related changes to ensure
CRC calculations remain identical.

Usage: python verify_crc.py
"""

import subprocess
import sys


def run_crc_tests():
    """Run CRC baseline tests and report results."""
    print("=" * 60)
    print("CRC REGRESSION TEST VERIFICATION")
    print("=" * 60)
    print("Running CRC baseline tests...")
    print()
    
    try:
        result = subprocess.run([
            'python', '-m', 'pytest', 
            'test_crc_baseline.py', 
            '-v', '--tb=short'
        ], capture_output=True, text=True)
        
        print(result.stdout)
        
        if result.returncode == 0:
            print("✅ ALL CRC TESTS PASSED")
            print("CRC calculations are identical to baseline implementation")
            return True
        else:
            print("❌ CRC TESTS FAILED")
            print("CRC calculations have changed from baseline!")
            print("\nError output:")
            print(result.stderr)
            return False
            
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        return False


def main():
    """Main entry point."""
    success = run_crc_tests()
    
    print("\n" + "=" * 60)
    if success:
        print("RESULT: CRC implementation is verified ✅")
        print("Safe to proceed with changes")
    else:
        print("RESULT: CRC implementation has changed ❌") 
        print("Review changes carefully!")
    print("=" * 60)
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())