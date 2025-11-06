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
MYPY_OUTPUT=$(DJANGO_SETTINGS_MODULE=wccomps.settings uv run mypy bot/ web/core/ --exclude 'bot/tests/.*' --exclude 'web/tests/.*' 2>&1)
MYPY_EXIT=$?

if [ $MYPY_EXIT -ne 0 ]; then
    echo "✗ Type errors found:"
    echo "$MYPY_OUTPUT"
    exit 1
fi

echo "✓ Type checking passed"
echo ""
echo "Checking for unapplied model changes..."
MAKEMIGRATIONS_OUTPUT=$(cd web && DJANGO_SETTINGS_MODULE=wccomps.settings uv run python manage.py makemigrations --check --dry-run 2>&1)
MAKEMIGRATIONS_EXIT=$?

if [ $MAKEMIGRATIONS_EXIT -ne 0 ]; then
    echo "✗ Model changes detected without migrations:"
    echo "$MAKEMIGRATIONS_OUTPUT"
    echo ""
    echo "Run 'cd web && python manage.py makemigrations' to create migrations"
    exit 1
fi

echo "✓ No unapplied model changes"
echo ""
echo "Running tests..."
PYTHONPATH="$(pwd)/web:$(pwd)" uv run pytest bot/tests/ --ignore=bot/tests/test_command_registration.py -v
if [ $? -ne 0 ]; then
    echo "✗ Tests failed"
    exit 1
fi

echo "✓ All tests passed"
echo ""
echo "Running integration tests in isolation..."
PYTHONPATH="$(pwd)/web:$(pwd)" uv run pytest bot/tests/test_command_registration.py -v
if [ $? -ne 0 ]; then
    echo "✗ Integration tests failed"
    exit 1
fi

echo "✓ Integration tests passed"
echo ""
echo "Deploying to $REMOTE_HOST:$REMOTE_PATH"

# Use rsync with exclude-from to read .rsyncignore
rsync -avz \
  --exclude-from=.rsyncignore \
  -e ssh \
  . \
  "$REMOTE_HOST:$REMOTE_PATH"

echo "✓ Files transferred"
echo ""
echo "Building containers..."

# Rebuild containers
ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose build bot web"

echo "✓ Containers built"
echo ""
echo "Restarting services..."

# Restart services
ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose up -d bot web"

echo "✓ Services restarted"
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
