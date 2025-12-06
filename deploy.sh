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

echo "✓ Dependencies upgraded and synced"
echo ""
echo "Running ruff format..."
uv run ruff format .

echo "Running ruff check with auto-fix..."
uv run ruff check --fix .

echo "Running ruff check..."
uv run ruff check .

echo "✓ Code formatting and linting passed"
echo ""
echo "Running type checks with mypy..."
MYPY_OUTPUT=$(DJANGO_SETTINGS_MODULE=wccomps.settings uv run mypy bot/ web/ --exclude 'bot/tests/.*' --exclude 'web/tests/.*' --exclude 'web/integration_tests/.*' --exclude '.*test.*\.py$' 2>&1)
MYPY_EXIT=$?

if [ $MYPY_EXIT -ne 0 ]; then
    echo "✗ Type errors found:"
    echo "$MYPY_OUTPUT"
    exit 1
fi

echo "✓ Type checking passed"
echo ""
echo "Starting test database..."
# Stop any existing test containers (ignore errors if none exist)
docker compose -f docker-compose.test.yml down -v 2>/dev/null || true

# Start fresh test database
if ! docker compose -f docker-compose.test.yml up -d --wait; then
    echo "✗ Failed to start test database"
    docker compose -f docker-compose.test.yml logs
    exit 1
fi

echo "✓ Test database ready"
echo ""

# Load .env.test for database connection
if [ -f .env.test ]; then
    set -a
    source .env.test
    set +a
fi

echo "Checking for unapplied model changes..."
MAKEMIGRATIONS_OUTPUT=$(cd web && DJANGO_SETTINGS_MODULE=wccomps.settings uv run python manage.py makemigrations --check --dry-run 2>&1)
MAKEMIGRATIONS_EXIT=$?

if [ $MAKEMIGRATIONS_EXIT -ne 0 ]; then
    echo "✗ Model changes detected without migrations:"
    echo "$MAKEMIGRATIONS_OUTPUT"
    echo ""
    echo "Run 'cd web && python manage.py makemigrations' to create migrations"
    docker compose -f docker-compose.test.yml down -v
    exit 1
fi

echo "✓ No unapplied model changes"
echo ""
echo "Collecting static files..."
COLLECTSTATIC_OUTPUT=$(cd web && DJANGO_SETTINGS_MODULE=wccomps.settings uv run python manage.py collectstatic --noinput 2>&1)
COLLECTSTATIC_EXIT=$?
if [ $COLLECTSTATIC_EXIT -ne 0 ]; then
    echo "✗ Failed to collect static files:"
    echo "$COLLECTSTATIC_OUTPUT"
    docker compose -f docker-compose.test.yml down -v
    exit 1
fi
echo "✓ Static files collected"

echo ""
echo "Running tests..."
export USE_POSTGRES_FOR_TESTS=1
export PYTHONPATH="$(pwd)/web:$(pwd)"

uv run pytest -m critical --tb=short -v

TESTS_EXIT=$?

echo "Stopping test database..."
docker compose -f docker-compose.test.yml down -v

if [ $TESTS_EXIT -ne 0 ]; then
    echo "✗ Tests failed"
    exit 1
fi

echo "✓ Tests passed"
echo ""
echo "Deploying to $REMOTE_HOST:$REMOTE_PATH"

# Use rsync with exclude-from to read .rsyncignore
# --delete removes files from remote that don't exist locally (but respects excludes)
rsync -avz --delete \
  --exclude-from=.rsyncignore \
  -e ssh \
  . \
  "$REMOTE_HOST:$REMOTE_PATH"

echo "✓ Files transferred"
echo ""
echo "Building containers..."

# Rebuild containers
if ! ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose build bot web"; then
    echo "✗ Build failed"
    exit 1
fi

echo "✓ Containers built"
echo ""
echo "Verifying images exist..."

# Verify images were created successfully
if ! ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose images web bot | grep -q 'wccomps-bot'"; then
    echo "✗ Images not found after build"
    exit 1
fi

echo "✓ Images verified"
echo ""
echo "Restarting services..."

# Restart web and bot with new images
if ! ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose up -d web bot"; then
    echo "✗ Failed to start containers"
    exit 1
fi

echo "Waiting for health checks..."
RETRY_COUNT=0
MAX_RETRIES=30
until ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose ps web --format json | grep -q '\"Health\":\"healthy\"'" || [ $RETRY_COUNT -eq $MAX_RETRIES ]; do
    RETRY_COUNT=$((RETRY_COUNT+1))
    echo "Health check attempt $RETRY_COUNT/$MAX_RETRIES..."
    sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    echo "✗ Health checks did not pass in time"
    ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose ps web"
    ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose logs --tail=50 web"
    exit 1
fi

echo "✓ Services deployed"
echo ""
echo "Verifying containers..."

# Check container status
if ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose ps web bot | grep -q 'Up'"; then
    echo "✓ Containers running"
    echo ""
    echo "Deployment complete!"
else
    echo "✗ Containers failed to start"
    echo ""
    echo "Check logs with: docker compose logs web bot"
    exit 1
fi
