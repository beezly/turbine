.PHONY: test test-coverage test-verbose install-test-deps clean

# Install test dependencies
install-test-deps:
	pip install -r requirements-test.txt

# Run basic tests
test:
	python -m pytest test_mnet.py

# Run tests with coverage
test-coverage:
	python -m pytest --cov=mnet --cov-report=html --cov-report=term test_mnet.py

# Run tests with verbose output
test-verbose:
	python -m pytest -v test_mnet.py

# Run specific test class
test-packet:
	python -m pytest test_mnet.py::TestMnetPacket -v

test-main:
	python -m pytest test_mnet.py::TestMnet -v

test-integration:
	python -m pytest test_mnet.py::TestMnetIntegration -v

# Clean up test artifacts
clean:
	rm -rf htmlcov/
	rm -rf .pytest_cache/
	rm -rf __pycache__/
	rm -f .coverage