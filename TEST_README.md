# Mnet.py Testing Guide

This document describes the comprehensive test suite for the `mnet.py` module.

## Test Frameworks

- **unittest**: Python's built-in testing framework for test structure
- **pytest**: Enhanced test runner with better reporting and fixtures
- **unittest.mock**: Mocking framework for isolating dependencies
- **pytest-cov**: Coverage reporting integration

## Test Structure

The test suite is organized into several test classes:

### TestMnetPacket
Tests for the inner `MnetPacket` class:
- Packet creation and initialization
- Data escaping (0xFF bytes)
- CRC calculation and validation
- String and bytes representation
- Custom CRC handling

### TestMnet
Tests for the main `Mnet` class:
- Initialization and serial connection setup
- Packet creation and reading
- Serial number retrieval and encoding
- Data encoding/decoding algorithms
- Command sending functionality
- Single and multiple data requests
- Timestamp conversion
- Constant definitions

### TestMnetIntegration
Integration tests that verify complete workflows:
- Full communication cycle from initialization to data retrieval
- Serial number acquisition followed by data requests

### TestMnetErrorHandling
Error handling and edge case tests:
- Device communication failures
- Invalid data type handling
- Malformed packet handling

### CRC Regression Tests
Specialized tests to ensure CRC calculations remain unchanged:
- **test_crc_baseline.py**: Critical baseline CRC values
- **test_crc_regression.py**: Comprehensive CRC validation
- **verify_crc.py**: Simple verification script

## Running Tests

### Prerequisites
Install test dependencies:
```bash
pip install -r requirements-test.txt
```

### Basic Test Execution

#### Using pytest directly:
```bash
# Run all tests
python -m pytest test_mnet.py

# Run with verbose output
python -m pytest -v test_mnet.py

# Run specific test class
python -m pytest test_mnet.py::TestMnet -v

# Run specific test method
python -m pytest test_mnet.py::TestMnet::test_mnet_initialization -v
```

#### Using the test runner script:
```bash
# Basic test run
python run_tests.py

# With coverage report
python run_tests.py --coverage

# Verbose output
python run_tests.py --verbose

# Specific test
python run_tests.py --test TestMnet::test_encode_decode_data
```

#### Using Makefile:
```bash
# Basic tests
make test

# Tests with coverage
make test-coverage

# Verbose tests
make test-verbose

# Specific test classes
make test-packet
make test-main
make test-integration

# CRC regression verification
python verify_crc.py
```

### Coverage Reports

When running with coverage, reports are generated in:
- Terminal: Immediate coverage summary
- HTML: `htmlcov/index.html` - Detailed line-by-line coverage

## Test Features

### Simplified Testing Approach
- **No Serial Mocking Required**: Tests use mock device objects directly
- **Dependency Injection**: Serial devices are passed to Mnet constructor
- **Clean Separation**: Serial creation is external to Mnet class
- **Isolation**: Each test is independent and doesn't affect others

### Test Data
- Uses realistic packet structures and data formats
- Tests both valid and edge case scenarios
- Includes proper binary data handling

### Assertions
- Comprehensive validation of return values
- Type checking for complex data structures
- Proper error condition testing

## Key Testing Patterns

### 1. Packet Testing
```python
def test_packet_creation(self):
    packet = Mnet.MnetPacket(destination, source, packet_type, len(data), data)
    self.assertEqual(packet.destination, destination)
    # ... additional assertions
```

### 2. Device Injection Testing
```python
def test_mnet_initialization(self):
    mock_device = Mock()
    mnet_instance = Mnet(mock_device, test_id)
    # ... test assertions
```

### 3. Data Flow Testing
```python
def test_encode_decode_data(self):
    original_data = b'Hello, World!'
    encoded = mnet_instance.encode(original_data, enc_serial)
    decoded = mnet_instance.decode(encoded, enc_serial)
    self.assertEqual(decoded, original_data)
```

## Architecture Benefits

### Simplified Testing (No Serial Mocking)
- **Before**: Required `@patch('mnet.serial.Serial')` decorators
- **After**: Direct mock device injection
- **Result**: Cleaner, faster, more maintainable tests

### Dependency Injection
- Serial device creation moved to calling code
- Mnet class accepts device object in constructor
- Better separation of concerns

## Best Practices Implemented

1. **Test Isolation**: Each test is independent and uses fresh mocks
2. **Comprehensive Coverage**: Tests cover normal operation, edge cases, and error conditions
3. **Realistic Data**: Uses actual protocol data structures and formats
4. **Clear Naming**: Test names clearly describe what is being tested
5. **Setup/Teardown**: Proper test fixture management
6. **Documentation**: Each test class and complex test has docstrings
7. **CRC Protection**: Regression tests prevent unintended CRC changes
8. **Error Testing**: Explicit testing of error conditions and exception handling

## Continuous Integration

The test suite is designed to run in CI environments:
- No external hardware dependencies
- Deterministic results
- Fast execution
- Clear failure reporting

## Extending Tests

When adding new functionality to `mnet.py`:

1. Add corresponding test methods to appropriate test class
2. Use mock devices directly (no patching required)
3. Test both success and failure scenarios
4. Run CRC verification if changes affect CRC calculations
5. Update this documentation if adding new test categories
6. Ensure new tests follow the established naming conventions

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure all dependencies are installed via `requirements-test.txt`
2. **CRC Changes**: Run `python verify_crc.py` to check for CRC calculation changes
3. **Device Errors**: Tests use mock devices - no real hardware needed

### Debug Mode
Run tests with additional debugging:
```bash
python -m pytest -v -s test_mnet.py
```

The `-s` flag allows print statements to show during test execution.