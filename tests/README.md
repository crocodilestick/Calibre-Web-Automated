# CWA Testing Quick Start Guide

## Installation & Setup

### 1. Install test dependencies:

```bash
pip install -r requirements-dev.txt
```

### 2. Generate test fixtures (first time only):

```bash
cd tests/fixtures
python download_gutenberg.py    # Download public domain ebooks (~5MB)
python generate_synthetic.py    # Create synthetic test files
cd ../..
```

## Running Tests

### Quick Feedback Loop (< 2 minutes) 
```bash
# Smoke + Unit tests only (no Docker)
pytest -m "smoke or unit" -n auto -v
```

### Run All Smoke Tests (Fastest - ~30 seconds)
```bash
pytest tests/smoke/ -v
```

### Run All Unit Tests (No Docker, can parallelize)
```bash
pytest tests/unit/ -n auto -v
```

### Run Docker Integration Tests (Requires Docker, ~15-20 min)
```bash
# These spin up actual CWA container - must run sequentially
pytest tests/integration/ -v
pytest tests/docker/ -v

# IMPORTANT: Do NOT use -n flag with Docker tests!
```

### Skip Docker Tests
```bash
pytest -m "not docker_integration" -n auto -v
```

### Run Specific Test Category
```bash
pytest -m smoke -v              # Smoke tests only
pytest -m unit -n auto -v       # Unit tests (parallel)
pytest -m docker_integration -v # Docker integration tests
pytest -m "slow" -v             # Only slow tests
pytest -m "not slow" -v         # Skip slow tests
```

### Run Specific Test File
```bash
pytest tests/unit/test_cwa_db.py -v
```

### Run Specific Test Function
```bash
pytest tests/unit/test_cwa_db.py::TestCWADBInitialization::test_database_creates_successfully -v
```

### Run Tests Matching Pattern
```bash
pytest -k "test_database" -v
```

### Run Tests with Coverage Report
```bash
pytest tests/unit/ --cov=scripts --cov=cps --cov-report=html
# Open htmlcov/index.html in browser to see coverage
```

### Run Tests in Parallel (Faster)
```bash
pytest tests/unit/ -n auto
```

### Run with More Verbose Output
```bash
pytest tests/smoke/ -vv --tb=long
```

## Continuous Integration

Tests are automatically run on:
- Every pull request
- Every push to main/develop branches
- Nightly for comprehensive E2E tests

See `.github/workflows/tests.yml` for CI configuration.

## Writing New Tests

1. Create test file in appropriate directory:
   - `tests/smoke/` - Fast verification tests
   - `tests/unit/` - Isolated component tests
   - `tests/integration/` - Multi-component tests
   - `tests/e2e/` - Full workflow tests

2. Use fixtures from `conftest.py`:
   ```python
   def test_something(temp_cwa_db, sample_book_data):
       # temp_cwa_db and sample_book_data are automatically available
       pass
   ```

3. Mark tests appropriately:
   ```python
   @pytest.mark.smoke     # Fast smoke test
   @pytest.mark.unit      # Unit test
   @pytest.mark.slow      # Takes >5 seconds
   @pytest.mark.requires_docker   # Needs Docker
   @pytest.mark.requires_calibre  # Needs Calibre CLI
   ```

4. Run your new tests:
   ```bash
   pytest path/to/your/test.py -v
   ```

## Troubleshooting

### Tests fail with "module not found"
```bash
# Make sure you're in the project root
cd /app/calibre-web-automated

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Tests timeout
```bash
# Increase timeout
pytest --timeout=60 tests/
```

### Tests fail in Docker but pass locally
```bash
# Run tests inside Docker container
docker exec -it calibre-web-automated pytest tests/smoke/ -v
```

### Database locked errors
```bash
# Clear any lock files
rm /tmp/*.lock

# Or use fresh test database (automatic with fixtures)
pytest tests/unit/test_cwa_db.py -v
```

## Test Coverage Goals

Current coverage status:
```bash
pytest --cov=cps --cov=scripts --cov-report=term
```

Target coverage:
- **Critical modules** (ingest, db, helpers): 80%+
- **Core application**: 70%+
- **Overall project**: 50%+

## Pre-Commit Checklist

Before committing code:
1. ✅ Run smoke tests: `pytest tests/smoke/ -v`
2. ✅ Run relevant unit tests: `pytest tests/unit/ -v`
3. ✅ Check code coverage: `pytest --cov=. --cov-report=term`
4. ✅ Fix any failing tests
5. ✅ Add tests for new functionality

## Getting Help

- Review `TESTING_STRATEGY.md` for comprehensive documentation
- Check existing tests for examples
- Ask in Discord: https://discord.gg/EjgSeek94R
- Open an issue on GitHub

## Next Steps

See `TESTING_STRATEGY.md` for:
- Integration test implementation
- Docker E2E test setup
- CI/CD configuration
- Advanced testing patterns
