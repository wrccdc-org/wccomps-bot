#!/bin/bash
# Deployment script for wccomps-bot
# This script safely transfers code to production without overwriting sensitive files

set -e

REMOTE_HOST="root@10.0.0.10"
REMOTE_PATH="/opt/stacks/wccomps-bot/"

echo "Upgrading lock file..."
uv lock --upgrade

echo "Syncing dependencies..."
uv sync

echo "OK: Dependencies upgraded and synced"
echo ""
echo "Running ruff format..."
uv run ruff format .

echo "Running ruff check with auto-fix..."
uv run ruff check --fix .

echo "Running ruff check..."
uv run ruff check .

echo "OK: Code formatting and linting passed"
echo ""
echo "Running djlint on templates..."
uv run djlint web/templates --reformat --quiet 2>/dev/null

echo "Running djlint lint check..."
if ! uv run djlint web/templates --lint --quiet 2>/dev/null; then
    echo "FAIL: Template linting errors found"
    uv run djlint web/templates --lint
    exit 1
fi

echo "OK: Template formatting and linting passed"
echo ""
echo "Running type checks with mypy..."
MYPY_OUTPUT=$(DJANGO_SETTINGS_MODULE=wccomps.settings uv run mypy bot/ web/ --exclude 'bot/tests/.*' --exclude 'web/tests/.*' --exclude 'web/integration_tests/.*' --exclude '.*test.*\.py$' 2>&1)
MYPY_EXIT=$?

if [ $MYPY_EXIT -ne 0 ]; then
    echo "FAIL: Type errors found:"
    echo "$MYPY_OUTPUT"
    exit 1
fi

echo "OK: Type checking passed"
echo ""

# Run tests if Docker is available
if command -v docker &>/dev/null; then
    echo "Starting test database..."
    docker compose -f docker-compose.test.yml down -v 2>/dev/null || true
    if ! docker compose -f docker-compose.test.yml up -d --wait; then
        echo "FAIL: Failed to start test database"
        docker compose -f docker-compose.test.yml logs
        exit 1
    fi
    echo "OK: Test database ready"

    if [ -f .env.test ]; then
        set -a
        source .env.test
        set +a
    fi

    echo "Applying migrations to test database..."
    export USE_POSTGRES_FOR_TESTS=1
    export DB_HOST="${TEST_DB_HOST:-localhost}"
    export DB_PORT="${TEST_DB_PORT:-5433}"
    export DB_NAME="${TEST_DB_NAME:-wccomps_test}"
    export DB_USER="${TEST_DB_USER:-test_user}"
    export DB_PASSWORD="${TEST_DB_PASSWORD:-test_password}"

    if ! (cd web && DJANGO_SETTINGS_MODULE=wccomps.settings uv run python manage.py migrate --noinput 2>&1); then
        echo "FAIL: Failed to apply migrations"
        docker compose -f docker-compose.test.yml down -v
        exit 1
    fi
    echo "OK: Migrations applied"

    echo "Checking for unapplied model changes..."
    MAKEMIGRATIONS_OUTPUT=$(cd web && DJANGO_SETTINGS_MODULE=wccomps.settings uv run python manage.py makemigrations --check --dry-run 2>&1)
    MAKEMIGRATIONS_EXIT=$?
    if [ $MAKEMIGRATIONS_EXIT -ne 0 ]; then
        echo "FAIL: Model changes detected without migrations:"
        echo "$MAKEMIGRATIONS_OUTPUT"
        docker compose -f docker-compose.test.yml down -v
        exit 1
    fi
    echo "OK: No unapplied model changes"

    echo "Collecting static files..."
    COLLECTSTATIC_OUTPUT=$(cd web && DJANGO_SETTINGS_MODULE=wccomps.settings uv run python manage.py collectstatic --noinput 2>&1)
    COLLECTSTATIC_EXIT=$?
    if [ $COLLECTSTATIC_EXIT -ne 0 ]; then
        echo "FAIL: Failed to collect static files:"
        echo "$COLLECTSTATIC_OUTPUT"
        docker compose -f docker-compose.test.yml down -v
        exit 1
    fi
    echo "OK: Static files collected"

    echo "Running tests..."
    export USE_POSTGRES_FOR_TESTS=1
    PYTHONPATH="$(pwd)/web:$(pwd)"
    export PYTHONPATH
    uv run pytest web/core/tests web/scoring/tests web/ticketing/tests web/team/tests bot/tests --tb=short -v
    TESTS_EXIT=$?

    echo "Stopping test database..."
    docker compose -f docker-compose.test.yml down -v

    if [ $TESTS_EXIT -ne 0 ]; then
        echo "FAIL: Tests failed"
        exit 1
    fi
    echo "OK: Tests passed"
else
    echo "WARN: Skipping tests (Docker not available)"
fi

echo ""
echo "Deploying to $REMOTE_HOST:$REMOTE_PATH"

# Use rsync with exclude-from to read .rsyncignore
# --delete removes files from remote that don't exist locally (but respects excludes)
rsync -avz --delete \
    --exclude-from=.rsyncignore \
    -e ssh \
    . \
    "$REMOTE_HOST:$REMOTE_PATH"

echo "OK: Files transferred"
echo ""
echo "Building containers..."

# Rebuild containers
if ! ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose build bot web"; then
    echo "FAIL: Build failed"
    exit 1
fi

echo "OK: Containers built"
echo ""
echo "Verifying images exist..."

# Verify images were created successfully
if ! ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose images web bot | grep -q 'wccomps-bot'"; then
    echo "FAIL: Images not found after build"
    exit 1
fi

echo "OK: Images verified"
echo ""
echo "Restarting services..."

# Restart web and bot with new images
if ! ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose up -d web bot"; then
    echo "FAIL: Failed to start containers"
    exit 1
fi

echo "Waiting for health checks..."
RETRY_COUNT=0
MAX_RETRIES=30
until ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose ps web --format json | grep -q '\"Health\":\"healthy\"'" || [ $RETRY_COUNT -eq $MAX_RETRIES ]; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo "Health check attempt $RETRY_COUNT/$MAX_RETRIES..."
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "FAIL: Health checks did not pass in time"
    ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose ps web"
    ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose logs --tail=50 web"
    exit 1
fi

echo "OK: Services deployed"
echo ""
echo "Verifying containers..."

# Check container status
if ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose ps web bot | grep -q 'Up'"; then
    echo "OK: Containers running"
    echo ""
    echo "Deployment complete!"
else
    echo "FAIL: Containers failed to start"
    echo ""
    echo "Check logs with: docker compose logs web bot"
    exit 1
fi
