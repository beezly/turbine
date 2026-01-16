#!/usr/bin/env python3
"""
Test runner script for mnet.py tests.
Usage: python run_tests.py [options]
"""

import sys
import subprocess
import argparse


def run_tests(coverage=False, verbose=False, specific_test=None):
    """Run the test suite with optional coverage and verbosity."""
    cmd = ['python', '-m', 'pytest']
    
    if coverage:
        cmd.extend(['--cov=mnet', '--cov-report=html', '--cov-report=term'])
    
    if verbose:
        cmd.append('-v')
    
    if specific_test:
        cmd.append(specific_test)
    else:
        cmd.append('tests')
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description='Run mnet.py tests')
    parser.add_argument('--coverage', '-c', action='store_true',
                       help='Run tests with coverage report')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose output')
    parser.add_argument('--test', '-t', type=str,
                       help='Run specific test (e.g., TestMnet::test_initialization)')
    
    args = parser.parse_args()
    
    return run_tests(
        coverage=args.coverage,
        verbose=args.verbose,
        specific_test=args.test
    )


if __name__ == '__main__':
    sys.exit(main())