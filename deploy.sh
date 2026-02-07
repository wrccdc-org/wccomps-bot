#!/bin/bash
# Deployment script for wccomps-bot
set -e

REMOTE_HOST="root@10.0.0.10"
REMOTE_PATH="/opt/stacks/wccomps-bot/"

fail() { echo -e "\n✗ $1\n"; exit 1; }
ok() { echo "  ✓ $1"; }

# --- Local checks ---

echo "Checking code..."

uv lock --upgrade --quiet
uv sync --quiet
ok "Dependencies synced"

uv run ruff format . --quiet
uv run ruff check --fix --quiet . 2>/dev/null || true
uv run ruff check . || fail "ruff check failed"
ok "Ruff passed"

uv run djlint web/templates --reformat --quiet 2>/dev/null
uv run djlint web/templates --lint --quiet 2>/dev/null || {
    echo ""
    uv run djlint web/templates --lint
    fail "djlint failed"
}
ok "djlint passed"

MYPY_OUTPUT=$(DJANGO_SETTINGS_MODULE=wccomps.settings uv run mypy bot/ web/ \
    --exclude 'bot/tests/.*' --exclude 'web/tests/.*' \
    --exclude 'web/integration_tests/.*' --exclude '.*test.*\.py$' 2>&1) \
    || { echo "$MYPY_OUTPUT"; fail "mypy failed"; }
ok "mypy passed"

# --- Tests (if Docker available) ---

if command -v docker &>/dev/null; then
    docker compose -f docker-compose.test.yml down -v 2>/dev/null || true
    docker compose -f docker-compose.test.yml up -d --wait 2>/dev/null \
        || fail "Failed to start test database"

    if [ -f .env.test ]; then
        set -a; source .env.test; set +a
    fi

    export USE_POSTGRES_FOR_TESTS=1
    export DB_HOST="${TEST_DB_HOST:-localhost}"
    export DB_PORT="${TEST_DB_PORT:-5433}"
    export DB_NAME="${TEST_DB_NAME:-wccomps_test}"
    export DB_USER="${TEST_DB_USER:-test_user}"
    export DB_PASSWORD="${TEST_DB_PASSWORD:-test_password}"

    (cd web && DJANGO_SETTINGS_MODULE=wccomps.settings uv run python manage.py migrate --noinput 2>&1) \
        || { docker compose -f docker-compose.test.yml down -v; fail "Migrations failed"; }

    (cd web && DJANGO_SETTINGS_MODULE=wccomps.settings uv run python manage.py makemigrations --check --dry-run 2>&1) \
        || { docker compose -f docker-compose.test.yml down -v; fail "Unapplied model changes detected"; }

    (cd web && DJANGO_SETTINGS_MODULE=wccomps.settings uv run python manage.py collectstatic --noinput 2>&1) >/dev/null \
        || { docker compose -f docker-compose.test.yml down -v; fail "collectstatic failed"; }

    PYTHONPATH="$(pwd)/web:$(pwd)" uv run pytest \
        web/core/tests web/scoring/tests web/ticketing/tests web/team/tests bot/tests \
        --tb=short -v
    TESTS_EXIT=$?

    docker compose -f docker-compose.test.yml down -v
    [ $TESTS_EXIT -ne 0 ] && fail "Tests failed"
    ok "Tests passed"
else
    echo "  - Skipping tests (no Docker)"
fi

# --- Deploy ---

echo ""
echo "Deploying to $REMOTE_HOST..."

rsync -az --delete --exclude-from=.rsyncignore -e ssh . "$REMOTE_HOST:$REMOTE_PATH" \
    || fail "rsync failed"
ok "Files transferred"

ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose build bot web" \
    || fail "Container build failed"
ok "Containers built"

ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose up -d web bot" \
    || fail "Failed to start containers"

echo "  Waiting for health checks..."
for i in $(seq 1 30); do
    if ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose ps web --format json | grep -q '\"Health\":\"healthy\"'" 2>/dev/null; then
        ok "Deployed and healthy"
        echo ""
        echo "Deployment complete!"
        exit 0
    fi
    sleep 2
done

echo ""
ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose logs --tail=30 web" 2>/dev/null
fail "Health checks timed out"
