#!/bin/bash
set -e

REMOTE_HOST="root@10.0.0.10"
REMOTE_PATH="/opt/stacks/wccomps-bot/"
SECONDS=0

fail() {
    echo ""
    echo "  ✗ $1"
    [ -n "${2:-}" ] && echo "" && echo "$2"
    echo ""
    exit 1
}
step() { echo "  ✓ $*"; }
cleanup_test_db() { docker compose -f docker-compose.test.yml down -v || true; }

# Suppress stderr noise (progress bars, docker lifecycle) — errors go via stdout
exec 3>&2 2>/dev/null

echo "deploy ── $(git branch --show-current) @ $(git rev-parse --short HEAD)"
echo ""
echo "Checks"

uv lock --upgrade --quiet
uv sync --quiet
step "deps"

uv run ruff format . --quiet
uv run ruff check --fix --quiet . || true
if ! OUT=$(uv run ruff check . --quiet); then
    fail "ruff" "$OUT"
fi
step "ruff"

uv run djlint web/templates --reformat --quiet
if ! OUT=$(uv run djlint web/templates --lint --quiet); then
    exec 2>&3
    fail "djlint" "$(uv run djlint web/templates --lint)"
fi
step "djlint"

if ! OUT=$(DJANGO_SETTINGS_MODULE=wccomps.settings uv run mypy bot/ web/ \
    --exclude 'bot/tests/.*' --exclude 'web/tests/.*' \
    --exclude 'web/integration_tests/.*' --exclude '.*test.*\.py$'); then
    fail "mypy" "$OUT"
fi
step "mypy"

if command -v docker &>/dev/null; then
    cleanup_test_db
    docker compose -f docker-compose.test.yml up -d --wait \
        || fail "test db"

    if [ -f .env.test ]; then
        set -a; source .env.test; set +a
    fi

    export USE_POSTGRES_FOR_TESTS=1
    export DB_HOST="${TEST_DB_HOST:-localhost}"
    export DB_PORT="${TEST_DB_PORT:-5433}"
    export DB_NAME="${TEST_DB_NAME:-wccomps_test}"
    export DB_USER="${TEST_DB_USER:-test_user}"
    export DB_PASSWORD="${TEST_DB_PASSWORD:-test_password}"

    if ! OUT=$(cd web && DJANGO_SETTINGS_MODULE=wccomps.settings \
        uv run python manage.py migrate --noinput --verbosity 0); then
        cleanup_test_db; fail "migrate" "$OUT"
    fi

    if ! OUT=$(cd web && DJANGO_SETTINGS_MODULE=wccomps.settings \
        uv run python manage.py makemigrations --check --dry-run --verbosity 0); then
        cleanup_test_db; fail "migrate — unapplied model changes detected"
    fi

    if ! OUT=$(cd web && DJANGO_SETTINGS_MODULE=wccomps.settings \
        uv run python manage.py collectstatic --noinput --verbosity 0); then
        cleanup_test_db; fail "collectstatic" "$OUT"
    fi
    step "migrate"

    if ! OUT=$(PYTHONPATH="$(pwd)/web:$(pwd)" uv run pytest \
        web/core/tests web/scoring/tests web/ticketing/tests \
        web/team/tests web/packets/tests bot/tests \
        --tb=short -q); then
        cleanup_test_db; fail "tests" "$OUT"
    fi
    cleanup_test_db

    SUMMARY=$(echo "$OUT" | grep . | tail -1)
    step "tests      $SUMMARY"
else
    echo "  · tests      skipped (no docker)"
fi

echo ""
echo "Deploy"

rsync -az --delete --exclude-from=.rsyncignore -e ssh . "$REMOTE_HOST:$REMOTE_PATH" --quiet \
    || fail "rsync"
step "synced"

ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose build --quiet bot web" \
    || fail "build"
step "built"

ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose up -d --quiet-pull web bot" \
    || fail "start"

for i in $(seq 1 30); do
    if ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose ps web --format json | grep -q '\"Health\":\"healthy\"'"; then
        step "healthy"
        echo ""
        echo "Done in ${SECONDS}s"
        exit 0
    fi
    sleep 2
done

echo ""
ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker compose logs --tail=30 web"
fail "health check timed out after 60s"
