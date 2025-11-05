#!/bin/bash
set -e

echo "Running database migrations..."
uv run --no-sync python manage.py migrate --noinput

echo "Checking for teams..."
uv run --no-sync python manage.py shell -c "
from core.models import Team
if Team.objects.count() == 0:
    print('No teams found, initializing 50 teams...')
    from django.core.management import call_command
    call_command('init_teams')
    print('✓ 50 teams initialized')
else:
    print(f'Teams already exist ({Team.objects.count()} teams)')
"

echo "Collecting static files..."
uv run --no-sync python manage.py collectstatic --noinput

echo "Starting application..."
exec "$@"
