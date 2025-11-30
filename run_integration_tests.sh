#!/bin/bash
# Run full integration test suite
# This includes critical, integration, browser, and load tests

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "WCComps Integration Test Suite"
echo "=========================================="
echo ""

# Check for .env.test file
if [ ! -f .env.test ]; then
    echo -e "${RED}✗ No .env.test file found${NC}"
    echo "  Copy .env.test.example to .env.test and fill in credentials"
    exit 1
fi

echo -e "${GREEN}✓ Found .env.test file${NC}"
echo ""

# Start test database
echo "Starting test database (fresh)..."
# Always recreate database for clean state
docker compose -f docker-compose.test.yml down -v 2>/dev/null || true
docker compose -f docker-compose.test.yml up -d --wait

if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Failed to start test database${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Test database ready${NC}"
echo ""

# Install Playwright browsers
echo "Installing Playwright browsers..."
uv run playwright install chromium --with-deps 2>/dev/null || true
echo -e "${GREEN}✓ Playwright setup complete${NC}"

echo ""

# Collect static files for Django templates
echo "Collecting static files..."
cd web && DJANGO_SETTINGS_MODULE=wccomps.settings uv run python manage.py collectstatic --noinput > /dev/null 2>&1
cd ..

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Static files collected${NC}"
else
    echo -e "${YELLOW}⚠ Failed to collect static files (may not be needed)${NC}"
fi

echo ""

# Load .env.test file
if [ -f .env.test ]; then
    set -a  # automatically export all variables
    source .env.test
    set +a
fi

# Set environment variables for integration tests
export USE_POSTGRES_FOR_TESTS=1
export DJANGO_ALLOW_ASYNC_UNSAFE=1
export PYTHONPATH="$(pwd)/web:$(pwd)"

# Trap to ensure database is stopped on exit
cleanup() {
    echo ""
    echo "Stopping test database..."
    docker compose -f docker-compose.test.yml down
    echo -e "${GREEN}✓ Test database stopped${NC}"
}

trap cleanup EXIT

# Parse command line arguments
TEST_SUITE="all"
VERBOSE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --critical)
            TEST_SUITE="critical"
            shift
            ;;
        --integration)
            TEST_SUITE="integration"
            shift
            ;;
        --browser)
            TEST_SUITE="browser"
            shift
            ;;
        --load)
            TEST_SUITE="load"
            shift
            ;;
        -v|--verbose)
            VERBOSE="-vv"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--critical|--integration|--browser|--load] [-v|--verbose]"
            exit 1
            ;;
    esac
done

# Run tests based on suite selection
case $TEST_SUITE in
    critical)
        echo "Running critical tests only..."
        uv run pytest -m critical --tb=short $VERBOSE
        ;;
    integration)
        echo "Running integration tests..."
        uv run pytest -m integration --tb=short $VERBOSE
        ;;
    browser)
        echo "Running browser tests..."
        uv run pytest -m browser --tb=short -p no:asyncio -p no:playwright $VERBOSE
        ;;
    load)
        echo "Running load/stress tests..."
        uv run pytest -m load --tb=short $VERBOSE
        ;;
    all)
        echo "Running full integration test suite..."
        echo ""

        echo -e "${YELLOW}[1/4] Critical Tests${NC}"
        uv run pytest -m critical --tb=short $VERBOSE
        CRITICAL_EXIT=$?

        echo ""
        echo -e "${YELLOW}[2/4] Integration Tests${NC}"
        uv run pytest -m integration --tb=short $VERBOSE
        INTEGRATION_EXIT=$?

        echo ""
        echo -e "${YELLOW}[3/4] Browser Tests${NC}"
        uv run pytest -m browser --tb=short -p no:asyncio -p no:playwright $VERBOSE
        BROWSER_EXIT=$?

        echo ""
        echo -e "${YELLOW}[4/4] Load Tests${NC}"
        uv run pytest -m load --tb=short $VERBOSE
        LOAD_EXIT=$?

        # Summary
        echo ""
        echo "=========================================="
        echo "Test Summary"
        echo "=========================================="

        if [ $CRITICAL_EXIT -eq 0 ]; then
            echo -e "${GREEN}✓ Critical Tests: PASSED${NC}"
        else
            echo -e "${RED}✗ Critical Tests: FAILED${NC}"
        fi

        if [ $INTEGRATION_EXIT -eq 0 ]; then
            echo -e "${GREEN}✓ Integration Tests: PASSED${NC}"
        else
            echo -e "${RED}✗ Integration Tests: FAILED${NC}"
        fi

        if [ $BROWSER_EXIT -eq 0 ]; then
            echo -e "${GREEN}✓ Browser Tests: PASSED${NC}"
        else
            echo -e "${RED}✗ Browser Tests: FAILED${NC}"
        fi

        if [ $LOAD_EXIT -eq 0 ]; then
            echo -e "${GREEN}✓ Load Tests: PASSED${NC}"
        else
            echo -e "${RED}✗ Load Tests: FAILED${NC}"
        fi

        echo ""

        # Exit with failure if any suite failed
        if [ $CRITICAL_EXIT -ne 0 ] || [ $INTEGRATION_EXIT -ne 0 ] || [ $BROWSER_EXIT -ne 0 ] || [ $LOAD_EXIT -ne 0 ]; then
            exit 1
        fi
        ;;
esac

TEST_EXIT=$?

echo ""
if [ $TEST_EXIT -eq 0 ]; then
    echo -e "${GREEN}=========================================="
    echo -e "All tests passed!"
    echo -e "==========================================${NC}"
else
    echo -e "${RED}=========================================="
    echo -e "Some tests failed!"
    echo -e "==========================================${NC}"
    exit 1
fi
