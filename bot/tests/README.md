# WCComps Bot Test Suite

## Overview

This directory contains the test suite for the WCComps Discord bot. Tests use pytest with async support for Discord.py commands and Django ORM operations. No live Discord connection required.

## Test Statistics

- **Total Tests**: 97
- **Code Coverage**: 59%
- **Test Framework**: pytest + pytest-asyncio + pytest-django
- **Database**: SQLite in-memory (no PostgreSQL needed for tests)

## Test Files

### Core Functionality Tests
- `test_admin_commands.py` (9 tests) - Admin slash commands (teams, unlink, remove team)
- `test_user_commands.py` (3 tests) - User-facing commands (/link, /team-info)
- `test_linking.py` (25 tests) - Discord account linking, team member limits, uniqueness
- `test_oauth_linking.py` (13 tests) - OAuth flow, link tokens, rate limiting

### Discord Integration Tests
- `test_discord_manager.py` (14 tests) - Team infrastructure (roles, categories, channels)
- `test_discord_queue.py` (14 tests) - Async queue processing, retry logic, backoff
- `test_group_roles.py` (12 tests) - Special roles (BlackTeam, WhiteTeam, OrangeTeam, RedTeam)
- `test_concurrent_operations.py` (6 tests) - Concurrent operations and race conditions

### Workflow Tests
- `test_ticket_workflows.py` (7 tests) - Ticket creation, resolution, dashboard updates
- `test_ticket_dashboard.py` (4 tests) - Ticket embed formatting
- `test_end_competition.py` (3 tests) - End-of-competition cleanup

## Running Tests

### Run All Tests
```bash
export DJANGO_SETTINGS_MODULE=wccomps.settings PYTHONPATH=web:/home/tirefire/wccomps-bot
uv run pytest
```

### Run Specific Test File
```bash
export DJANGO_SETTINGS_MODULE=wccomps.settings PYTHONPATH=web:/home/tirefire/wccomps-bot
uv run pytest tests/test_linking.py -v
```

### Run Specific Test
```bash
uv run pytest tests/test_linking.py::TestDiscordLinkUniqueness::test_one_active_link_per_discord_id -v
```

### Run Tests with Coverage
```bash
cd bot
export DJANGO_SETTINGS_MODULE=wccomps.settings PYTHONPATH=../web:/home/tirefire/wccomps-bot
uv run pytest --cov=. --cov-report=html --cov-report=term-missing
```

Coverage HTML report generated at `htmlcov/index.html`

## Test Infrastructure

### Database
Tests use **SQLite in-memory database** (configured in `web/wccomps/settings.py`). No PostgreSQL setup needed.

### Fixtures (conftest.py)
- `mock_interaction` - Mock Discord interaction
- `mock_admin_user` - Admin user with Discord link (async)
- `mock_team_user` - Team member with Discord link (async)
- `mock_bot` - Mock Discord bot client
- `mock_discord_guild` - Mock Discord guild with roles/members

### Test Isolation
Each test uses unique identifiers to prevent conflicts:
- Team numbers randomized with UUID
- Discord IDs randomly generated (18 digits)
- Usernames include unique suffixes
- Partial unique constraint (active links only)

## Writing Tests

### Example Test Structure
```python
@pytest.mark.asyncio
@pytest.mark.django_db
class TestFeature:
    """Test feature description."""

    async def test_specific_behavior(
        self, mock_interaction: Any, mock_bot: Any
    ) -> None:
        """Test that specific behavior works correctly."""
        # Arrange
        cog = FeatureCog(mock_bot)

        # Act
        await cog.command.callback(cog, mock_interaction)

        # Assert
        mock_interaction.response.send_message.assert_called_once()
```

### Best Practices
1. Use `@pytest.mark.asyncio` for async tests
2. Use `@pytest.mark.django_db` for database access
3. Use `AsyncMock` for Discord API calls
4. Use unique IDs for test data isolation
5. Call commands via `.callback(cog, interaction)`
6. Use `select_related()` for foreign keys in async

### Testing Permissions
```python
async def test_requires_admin(self, mock_interaction, mock_bot):
    mock_interaction.user.id = 999999999  # Non-admin ID

    cog = AdminCog(mock_bot)
    await cog.admin_command.callback(cog, mock_interaction)

    call_args = mock_interaction.response.send_message.call_args
    assert "permission" in call_args.args[0].lower()
```

### Mocking Settings
```python
from unittest.mock import patch

async def test_with_settings(self, mock_interaction, mock_bot):
    with patch("bot.cogs.linking.settings") as mock_settings:
        mock_settings.BASE_URL = "http://test.com"
        await cog.command.callback(cog, mock_interaction)
```

## Coverage Report

### Well-Covered Modules (>60%)
- `cogs/linking.py`: 89%
- `discord_manager.py`: 65%
- `discord_queue.py`: 62%

### Partially Covered (30-60%)
- `cogs/admin_linking.py`: 36%
- `ticket_dashboard.py`: 33%
- `utils.py`: 33%

### Need Coverage (0%)
- `authentik_manager.py`
- `cogs/ticketing.py`
- `competition_timer.py`
- `unified_dashboard.py`
- `model_helpers.py`

## Common Issues

### Django Async ORM
Use `.select_related()` for foreign keys:
```python
# Wrong - causes sync query in async context
link = await DiscordLink.objects.filter(id=1).afirst()
team_name = link.team.name  # Error!

# Correct
link = await DiscordLink.objects.filter(id=1).select_related("team").afirst()
team_name = link.team.name  # Works!
```

### Command Callback
Commands must use `.callback()`:
```python
# Wrong
await cog.link_command(mock_interaction)

# Correct
await cog.link_command.callback(cog, mock_interaction)
```

### Unique Constraint Violations
Use unique IDs per test:
```python
import uuid
unique_id = str(uuid.uuid4())[:8]
team_number = int(unique_id, 16) % 10000
```

## CI/CD Integration

Tests run automatically before deployment via `deploy.sh`:
```bash
PYTHONPATH="$(pwd)/web:$(pwd)" uv run pytest bot/tests/ -v
```

Deployment is blocked if any test fails.

## Troubleshooting

### Import Errors
Django setup is automatic via `conftest.py`. Ensure:
```python
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "wccomps.settings")
django.setup()
```

### Async Mode
`pytest.ini` sets `asyncio_mode = strict` for proper async testing.

### Database Errors
Always use `@pytest.mark.django_db` for database tests.

## Future Improvements

1. Increase coverage to 80%+ (currently 59%)
2. Add tests for ticketing.py (currently 0%)
3. Add tests for authentik_manager.py (currently 0%)
4. Add snapshot testing for embeds
5. Add integration tests with dpytest
