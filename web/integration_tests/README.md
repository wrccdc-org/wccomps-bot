# Integration Tests

Real integration tests using actual PostgreSQL, Authentik API, Discord API, and browser rendering to catch issues before deployment.

## Overview

These tests use:
- **Real PostgreSQL database** (via Docker) - no SQLite mocking
- **Real Authentik API** - actual OAuth flows
- **Real Discord API** - test in production guild (team 50)
- **Playwright browser** - full UI rendering and JavaScript execution

## Test Categories

Tests are organized by pytest markers:

- `@pytest.mark.critical` - Must pass before deployment (runs in deploy.sh)
- `@pytest.mark.integration` - API integration tests with real services
- `@pytest.mark.browser` - Browser-based UI tests with Playwright
- `@pytest.mark.load` - Stress tests, concurrency, connection pool limits

## Setup

### 1. Install Dependencies

```bash
uv sync
uv run playwright install chromium --with-deps
```

### 2. Configure Test Credentials

Copy the example file and fill in real credentials:

```bash
cp .env.test.example .env.test
```

Edit `.env.test` with:

```bash
# Discord test user credentials
TEST_DISCORD_USER_TOKEN=your_test_user_token
TEST_DISCORD_USERNAME=testuser#1234

# Authentik test user credentials
TEST_AUTHENTIK_USERNAME=test_user@example.com
TEST_AUTHENTIK_PASSWORD=your_test_password
TEST_AUTHENTIK_API_TOKEN=your_api_token

# Test configuration
TEST_TEAM_ID=50  # Team 50 is designated for testing
TEST_GUILD_ID=525435725123158026
TEST_TICKET_CATEGORY_ID=your_test_category_id
```

**IMPORTANT:** Use a real test user account, not production credentials!

### 3. Start Test Database

The test database runs in Docker on port 5433 (separate from production):

```bash
docker compose -f docker-compose.test.yml up -d
```

## Running Tests

### Quick Start

Run critical tests only (< 60 seconds):

```bash
PYTHONPATH="$(pwd)/web:$(pwd)" uv run pytest -m critical
```

### Full Test Suite

Run all integration tests:

```bash
./run_integration_tests.sh
```

Options:
- `./run_integration_tests.sh --critical` - Critical tests only
- `./run_integration_tests.sh --integration` - Integration tests
- `./run_integration_tests.sh --browser` - Browser tests
- `./run_integration_tests.sh --load` - Load/stress tests
- `./run_integration_tests.sh -v` - Verbose output

### Individual Test Files

```bash
# Critical API tests
PYTHONPATH="$(pwd)/web:$(pwd)" uv run pytest web/integration_tests/test_critical_api.py -v

# Critical browser tests
PYTHONPATH="$(pwd)/web:$(pwd)" uv run pytest web/integration_tests/test_critical_browser.py -v

# Comprehensive tests
PYTHONPATH="$(pwd)/web:$(pwd)" uv run pytest web/integration_tests/test_comprehensive.py -v

# Load tests
PYTHONPATH="$(pwd)/web:$(pwd)" uv run pytest web/integration_tests/test_load.py -v
```

## What Gets Tested

### Critical API Tests (`test_critical_api.py`)

- Health check endpoint with real database
- OAuth callback flow
- Ticket claim/resolve operations
- Concurrent ticket operations (race conditions)
- Bulk operations (transaction integrity)
- Database connection pool behavior

### Critical Browser Tests (`test_critical_browser.py`)

- Full Authentik OAuth login flow
- Ops ticket dashboard rendering
- Ticket claim from UI
- Ticket resolve with points
- JavaScript error detection
- CSRF token validation

### Comprehensive Tests (`test_comprehensive.py`)

- Complete ticket lifecycle (create → claim → comment → resolve)
- Authentik API integration
- File attachment upload/download
- Edge cases (nonexistent tickets, double claims)
- Database transaction rollback

### Load Tests (`test_load.py`)

- 50+ concurrent requests
- 100+ concurrent page loads
- Connection pool exhaustion/recovery
- Concurrent ticket operations
- Memory leak detection
- Query performance under load

## Deployment Integration

Critical tests run automatically in `deploy.sh` before deployment:

1. Start test database
2. Install Playwright browsers
3. Run `pytest -m critical`
4. Stop test database
5. If tests pass → deploy to production
6. If tests fail → abort deployment

## Test Data

- All test tickets are prefixed with `[INTEGRATION TEST]`
- Tests use **team 50** for all operations
- Test data is automatically cleaned up after each test
- Tests use dedicated Discord test category/channels

## Troubleshooting

### Tests fail with "No .env.test file found"

Copy `.env.test.example` to `.env.test` and fill in credentials.

### Tests fail with database connection errors

Make sure test database is running:

```bash
docker compose -f docker-compose.test.yml up -d
docker compose -f docker-compose.test.yml ps
```

### Browser tests fail with "Playwright not installed"

Install Playwright browsers:

```bash
uv run playwright install chromium --with-deps
```

### OAuth tests fail

- Verify Authentik credentials in `.env.test`
- Check that test user exists in Authentik
- Ensure API token has correct permissions

### Tests are slow

- Critical tests target < 60s (run on every deploy)
- Full suite can take 5-10 minutes
- Use `--critical` flag for quick validation

## Architecture

```
web/integration_tests/
├── conftest.py              # Fixtures and test configuration
├── test_critical_api.py     # Critical API tests (@pytest.mark.critical)
├── test_critical_browser.py # Critical browser tests (@pytest.mark.critical)
├── test_comprehensive.py    # Full integration tests (@pytest.mark.integration)
├── test_load.py            # Load/stress tests (@pytest.mark.load)
└── README.md               # This file
```

### Key Fixtures (conftest.py)

- `django_db_setup` - Sets up PostgreSQL test database
- `authenticated_page` - Playwright page with OAuth login completed
- `authentik_client` - Real Authentik API client
- `test_team_id` - Returns team 50 for testing
- `_cleanup_test_data` - Auto-cleanup after each test

## Best Practices

1. **Always use team 50** for test data
2. **Prefix test tickets** with `[INTEGRATION TEST]`
3. **Clean up test data** in fixtures (automatic via `_cleanup_test_data`)
4. **Mark tests appropriately**:
   - `@pytest.mark.critical` - Fast, essential tests
   - `@pytest.mark.integration` - Thorough API tests
   - `@pytest.mark.browser` - UI rendering tests
   - `@pytest.mark.load` - Slow stress tests
5. **Don't mock Authentik or Discord** - use real APIs
6. **Test failures, not just success** - verify error handling

## CI/CD Integration

These tests are designed to run in:

1. **Local development** - Before committing changes
2. **Pre-deployment** - Automatically in deploy.sh
3. **CI/CD pipeline** - Can be integrated into GitHub Actions/GitLab CI

Example CI/CD:

```yaml
test-integration:
  script:
    - docker compose -f docker-compose.test.yml up -d --wait
    - uv run playwright install chromium --with-deps
    - PYTHONPATH="$PWD/web:$PWD" uv run pytest -m critical
    - docker compose -f docker-compose.test.yml down
```

## Contributing

When adding new integration tests:

1. Add tests to appropriate file (critical, comprehensive, or load)
2. Mark with correct pytest markers
3. Use fixtures from conftest.py
4. Clean up test data
5. Test with real services (no mocking)
6. Keep critical tests fast (< 60s total)
