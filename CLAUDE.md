# WCComps

Discord bot + Django web app for WRCCDC competition management.

## Commands

```bash
docker compose -f docker-compose.test.yml up -d --wait  # start test DB
cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest  # tests
uv run ruff format . && uv run ruff check .  # format + lint
uv run mypy                      # type check
cd web && uv run python manage.py makemigrations  # migrations
./deploy.sh                      # deploy to production
docker compose logs -f web bot  # tail logs (production: ssh to 10.0.0.10, cd /opt/stacks/wccomps-bot/)
```

## Notes

- Run `./deploy.sh` before `git push` - deploy catches errors that would break production
- Commit messages: 10 words or fewer, no Co-Authored-By
- Strict MyPy enforced - all functions need type annotations
- Bot state persists in DB via `BotState` model, not env vars
- Authentik groups are source of truth for permissions
- DiscordQueue handles rate limiting - don't call Discord API directly from cogs
- Gunicorn workers capped at 4 to stay under DB connection limit
- Templates use Cotton components (`c-button`, `c-link`, `c-slot`, etc.) - don't use raw HTML/Bootstrap for buttons, links, or form elements
- `<c-alert>` is for transient messages only (flash, error, warning) - use `.status-bar` + `<c-badge>` for status displays
