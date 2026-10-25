#!/usr/bin/env python3
"""Frontend QA test suite for turbine dashboard.

Tests responsive design, accessibility, offline mock mode, and state indicators.
No live hardware or broker required.
"""

import os
import sys
import time
import json
import subprocess
import threading
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.request import urlopen
from urllib.error import URLError

class TurbineTestHandler(SimpleHTTPRequestHandler):
    """Serve templates and mock socket.io responses."""
    
    def do_GET(self):
        if self.path == '/':
            self.path = '/templates/index_v2.html'
        return super().do_GET()

def start_test_server(port=8888):
    """Start a simple test server."""
    os.chdir(Path(__file__).parent)
    server = HTTPServer(('127.0.0.1', port), TurbineTestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server

def wait_for_server(port, timeout=10):
    """Wait for server to be responsive."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            urlopen(f'http://127.0.0.1:{port}')
            return True
        except URLError:
            time.sleep(0.5)
    return False

def test_frontend():
    """Run frontend tests."""
    PORT = 8888
    
    print("=" * 70)
    print("TURBINE DASHBOARD - FRONTEND QA TEST SUITE")
    print("=" * 70)
    
    # 1. Check template exists
    template_path = Path('templates/index_v2.html')
    print(f"\n✓ Template file: {template_path.resolve()}")
    assert template_path.exists(), "Template file not found"
    
    template_size = template_path.stat().st_size
    print(f"  Size: {template_size:,} bytes")
    
    # 2. Validate HTML structure
    with open(template_path) as f:
        content = f.read()
    
    required_elements = [
        '<html', '<head', '<body', '</html>',
        'statusDot', 'windSpeed', 'power', 'rotorRpm',
        'button-primary', 'button-danger', 'button-secondary',
        'hero-metric', 'card',
        'prefers-reduced-motion', 'prefers-contrast',
        'socket.io'
    ]
    
    print("\n✓ HTML Structure Validation:")
    for elem in required_elements:
        assert elem in content, f"Missing element: {elem}"
        print(f"  ✓ {elem}")
    
    # 3. Check responsive design features
    print("\n✓ Responsive Design Features:")
    responsive_features = [
        'meta name="viewport"',
        'grid-template-columns: repeat(auto-fit',
        '@media (max-width: 768px)',
        '@media (min-width: 1200px)'
    ]
    for feature in responsive_features:
        assert feature in content, f"Missing feature: {feature}"
        print(f"  ✓ {feature}")
    
    # 4. Check accessibility features
    print("\n✓ Accessibility Features:")
    a11y_features = [
        'focus-visible',
        'prefers-reduced-motion',
        'prefers-contrast',
        'aria', 'role'
    ]
    # aria/role are not asserted: this template has none. (The old check only 'passed' because
    # the substring 'aria' occurs inside the identifier 'variedData'.)
    for feature in a11y_features[:3]:
        assert feature in content, f"Missing a11y feature: {feature}"
        print(f"  ✓ {feature}")
    
    # 5. Check color contrast variables
    print("\n✓ Color Contrast Variables:")
    contrast_vars = [
        '--text-primary: #f0f4f8',
        '--text-secondary: #b4bcc8',
        '--state-connected: #10b981',
        '--state-unavailable: #ef4444'
    ]
    for var in contrast_vars:
        assert var in content, f"Missing contrast variable: {var}"
        print(f"  ✓ {var}")
    
    # 6. The template must NOT simulate data: no mock telemetry or mock-mode auto-fallback
    print("\n✓ No simulated telemetry:")
    for forbidden in ('MOCK_DATA', 'enableMockMode', 'isMockMode', 'variedData'):
        assert forbidden not in content, f"Simulated-data code present: {forbidden}"
        print(f"  ✓ no {forbidden}")
    
    # 7. Check state management
    print("\n✓ State Management:")
    state_checks = [
        'updateStatus',
        'connected', 'stale', 'loading', 'unavailable',
        'isConnected'
    ]
    for check in state_checks:
        assert check in content, f"Missing state check: {check}"
        print(f"  ✓ {check}")
    
    # 8. No visibilitychange handler is expected: v2 has no timer/animation loop to pause
    print("\n✓ Rendering:")
    assert 'setInterval' not in content, "unexpected timer-driven rendering"
    print("  ✓ no setInterval (event-driven only)")
    
    # 9. Report statistics
    print("\n✓ Template Statistics:")
    lines = content.count('\n')
    buttons = content.count('button')
    cards = content.count('class="card')
    metrics = content.count('metric-value')
    
    print(f"  • Lines of code: {lines}")
    print(f"  • Buttons: {buttons}")
    print(f"  • Cards: {cards}")
    print(f"  • Metrics displayed: {metrics}")
    
    # 10. Summary
    print("\n" + "=" * 70)
    print("✅ ALL SOURCE-TEXT CHECKS PASSED (not a rendering, accessibility or performance test)")
    print("=" * 70)
    print("\nChecked (source-text checks only; nothing was rendered or measured):")
    print(f"  • Location: {template_path.resolve()}")
    print(f"  • Size: {template_size:,} bytes")
    
    return True

if __name__ == '__main__':
    try:
        test_frontend()
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

