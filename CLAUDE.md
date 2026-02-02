# WCComps

Discord bot + Django web app for WRCCDC competition management.

## Commands

```bash
uv run pytest                    # tests
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
