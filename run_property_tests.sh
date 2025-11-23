#!/bin/bash
# Script to run property-based tests

set -e

echo "=== Installing test dependencies ==="
uv sync --group dev

echo ""
echo "=== Running property-based tests ==="
echo ""

# Run all property-based tests
uv run pytest bot/tests/test_team_number_properties.py \
            bot/tests/test_discord_id_properties.py \
            bot/tests/test_ticket_category_properties.py \
            -v --tb=short

echo ""
echo "=== Property-based test results ==="
echo "✓ All property-based tests completed"
