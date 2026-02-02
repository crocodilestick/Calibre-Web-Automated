# Test Execution Optimization Guide

## Test Execution Strategy

### Quick Feedback Loop (< 2 minutes)
```bash
# Smoke + Unit tests only (no Docker)
pytest -m "smoke or unit" -v

# Run in parallel for speed
pytest -m "smoke or unit" -n auto
```

### Pre-Commit Validation (~ 3-5 minutes)
```bash
# Smoke + Unit + Fast integration tests
pytest -m "smoke or unit" -n auto
pytest -m "docker_integration and not slow" -v
```

### Full Integration Testing (~ 15-20 minutes)
```bash
# All tests including slow integration tests
pytest tests/smoke/ tests/unit/ -n auto  # Parallel
pytest tests/docker/ tests/integration/ -v  # Sequential (Docker constraint)
```

### Complete Test Suite (~ 25-30 minutes)
```bash
# Everything including E2E
pytest --cov=cps --cov=scripts --cov-report=html
```

---

## Parallel Execution

### Unit Tests (Safe for Parallel)
```bash
# Run unit tests with max parallelization
pytest tests/unit/ -n auto --dist=loadscope

# Or specify worker count
pytest tests/unit/ -n 4
```

### Docker Integration Tests (Must Run Sequential)
Docker tests **cannot run in parallel** because:
- testcontainers uses a shared Docker daemon
- Multiple containers would conflict on port 8083
- Volume mounts would overlap

```bash
# Always run Docker tests sequentially
pytest tests/docker/ tests/integration/ -v
# DO NOT use -n flag with Docker tests!
```

---

## Test Grouping for CI/CD

### Job 1: Fast Feedback (Every PR)
**Runtime**: ~2 minutes
```bash
pytest -m "smoke or unit" -n auto --tb=short
```

### Job 2: Integration Tests (On Merge)
**Runtime**: ~15-20 minutes
```bash
# Unit tests first (parallel)
pytest tests/unit/ -n auto

# Docker tests (sequential)
pytest tests/docker/ tests/integration/ -v
```

### Job 3: Nightly Full Suite
**Runtime**: ~30 minutes
```bash
pytest --cov=cps --cov=scripts \
       --cov-report=html \
       --cov-report=term \
       --junitxml=test-results.xml
```

---

## Optimizing Individual Tests

### Use Fixtures Wisely
- **Session-scoped** for Docker container (start once)
- **Function-scoped** for temporary files
- **Module-scoped** for shared test data

### Skip Expensive Operations
```python
@pytest.mark.skipif(not os.path.exists("expensive_file"), 
                   reason="Expensive file not available")
def test_something_expensive():
    pass
```

### Timeout Protection
```python
@pytest.mark.timeout(60)  # Fail if test takes >60s
def test_something_that_might_hang():
    pass
```

---

## Test Execution Times (Measured)

| Test Category | Count | Sequential | Parallel | Speedup |
|---------------|-------|------------|----------|---------|
| Smoke tests   | 19    | ~30s       | ~15s     | 2x      |
| Unit tests    | 20    | ~2min      | ~30s     | 4x      |
| Docker startup| 9     | ~5min      | N/A      | -       |
| Integration   | 21    | ~20min     | N/A      | -       |
| **Total**     | 69    | ~27min     | ~15min   | 1.8x    |

*Note: Docker tests cannot be parallelized*

---

## CI/CD Optimization Tips

### 1. Cache Dependencies
```yaml
- name: Cache pip packages
  uses: actions/cache@v3
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-${{ hashFiles('requirements*.txt') }}
```

### 2. Cache Docker Images
```yaml
- name: Pull Docker image
  run: docker pull crocodilestick/calibre-web-automated:latest
  
- name: Cache Docker layers
  uses: actions/cache@v3
  with:
    path: /var/lib/docker
    key: ${{ runner.os }}-docker-${{ hashFiles('Dockerfile') }}
```

### 3. Fail Fast
```yaml
strategy:
  fail-fast: true  # Stop all jobs if one fails
  matrix:
    python-version: [3.11, 3.12]
```

### 4. Split Jobs by Speed
```yaml
jobs:
  fast-tests:
    # Runs in ~2 min
    steps:
      - run: pytest -m "smoke or unit" -n auto
  
  slow-tests:
    needs: fast-tests  # Only run if fast tests pass
    # Runs in ~15 min
    steps:
      - run: pytest tests/integration/ -v
```

---

## Local Development Workflow

### During Active Development
```bash
# Test just what you're working on
pytest tests/unit/test_helper.py::TestSpecificFunction -v

# Watch mode (requires pytest-watch)
ptw tests/unit/test_helper.py -- -v
```

### Before Committing
```bash
# Quick validation
pytest -m "smoke or unit" -n auto

# If touching ingest code, run integration tests
pytest tests/integration/test_ingest_pipeline.py -v -k "test_mobi_to_epub"
```

### Before Creating PR
```bash
# Run full test suite
pytest tests/smoke/ tests/unit/ -n auto
pytest tests/integration/ -v --tb=short
```

---

## Troubleshooting Slow Tests

### Identify Slowest Tests
```bash
pytest --durations=20  # Show 20 slowest tests
```

### Profile Individual Test
```bash
pytest tests/integration/test_ingest_pipeline.py::TestFormatConversion::test_mobi_to_epub_conversion -v --durations=0
```

### Skip Slow Tests During Development
```bash
pytest -m "not slow" -v
```

---

## Best Practices

### ✅ DO:
- Run smoke + unit tests before every commit
- Use `-n auto` for unit tests
- Group related assertions in one test
- Use descriptive test names
- Clean up test data in fixtures

### ❌ DON'T:
- Don't use `-n` flag with Docker tests
- Don't run full suite locally every time
- Don't leave debug `print()` statements
- Don't commit commented-out tests
- Don't chain too many operations in one test

---

## Test Execution Matrix

| Scenario | Command | Time | When to Use |
|----------|---------|------|-------------|
| **Quick check** | `pytest -m smoke` | 30s | After small changes |
| **Unit validation** | `pytest -m unit -n auto` | 1min | Before commit |
| **Full local test** | `pytest -m "not docker_integration" -n auto` | 2min | Before PR |
| **Integration test** | `pytest tests/integration/ -v` | 15min | Testing ingest changes |
| **Complete suite** | `pytest --cov=. --cov-report=html` | 25min | Release validation |

---

## Measuring Test Coverage

### Generate HTML Report
```bash
pytest --cov=cps --cov=scripts \
       --cov-report=html \
       --cov-report=term-missing

# Open in browser
open htmlcov/index.html
```

### Coverage by Module
```bash
pytest --cov=scripts/ingest_processor --cov-report=term
```

### Missing Lines Report
```bash
pytest --cov=cps/helper --cov-report=term-missing
```

---

## Future Optimizations

### Potential Improvements:
1. **Container reuse**: Keep container running between test classes
2. **Fixture caching**: Cache converted books for format tests
3. **Database seeding**: Pre-populate test database instead of importing
4. **Mock external services**: Mock GDrive sync, metadata providers
5. **Smaller test files**: Use even smaller synthetic EPUBs

### Expected Gains:
- Container reuse: Save ~30s per test class
- Fixture caching: Save ~60s per conversion test
- Database seeding: Save ~10s per import test
- **Total potential savings**: ~5-8 minutes off integration suite
