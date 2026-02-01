"""Tests for shared competition actions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async

from core.models import CompetitionConfig


@pytest.fixture
def mock_bot():
    """Create a mock Discord bot."""
    return MagicMock()


@pytest.fixture
def config(db):
    """Create a test competition config with pk=1 (singleton pattern)."""
    # Use update_or_create to ensure we get pk=1
    config, _ = CompetitionConfig.objects.update_or_create(
        pk=1,
        defaults={
            "controlled_applications": ["netbird", "scoring"],
            "applications_enabled": False,
        },
    )
    return config


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestStartCompetition:
    """Tests for start_competition action."""

    async def test_enables_applications(self, config):
        """Should enable Authentik applications."""
        from bot.competition_actions import start_competition

        with patch("bot.competition_actions.AuthentikManager") as mock_auth:
            mock_auth.return_value.enable_applications.return_value = {
                "netbird": (True, None),
                "scoring": (True, None),
            }
            with patch("bot.competition_actions.toggle_all_blueteam_accounts", new_callable=AsyncMock) as mock_toggle:
                mock_toggle.return_value = (50, 0)

                result = await start_competition()

        assert result["success"] is True
        mock_auth.return_value.enable_applications.assert_called_once()

    async def test_enables_accounts(self, config):
        """Should enable all blueteam accounts."""
        from bot.competition_actions import start_competition

        with patch("bot.competition_actions.AuthentikManager") as mock_auth:
            mock_auth.return_value.enable_applications.return_value = {}
            with patch("bot.competition_actions.toggle_all_blueteam_accounts", new_callable=AsyncMock) as mock_toggle:
                mock_toggle.return_value = (50, 0)

                await start_competition()

        mock_toggle.assert_called_once_with(is_active=True)

    async def test_clears_start_time_only(self, config):
        """Should clear start_time but preserve end_time."""
        from django.utils import timezone

        from bot.competition_actions import start_competition

        @sync_to_async
        def setup_config():
            config.competition_start_time = timezone.now()
            config.competition_end_time = timezone.now()
            config.save()

        await setup_config()

        with patch("bot.competition_actions.AuthentikManager") as mock_auth:
            mock_auth.return_value.enable_applications.return_value = {}
            with patch("bot.competition_actions.toggle_all_blueteam_accounts", new_callable=AsyncMock) as mock_toggle:
                mock_toggle.return_value = (50, 0)

                await start_competition()

        @sync_to_async
        def check_config():
            config.refresh_from_db()
            return config.competition_start_time, config.competition_end_time

        start_time, end_time = await check_config()
        assert start_time is None
        assert end_time is not None


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestStopCompetition:
    """Tests for stop_competition action."""

    async def test_disables_applications(self, config):
        """Should disable Authentik applications."""
        from bot.competition_actions import stop_competition

        @sync_to_async
        def setup_config():
            config.applications_enabled = True
            config.save()

        await setup_config()

        with patch("bot.competition_actions.AuthentikManager") as mock_auth:
            mock_auth.return_value.disable_applications.return_value = {
                "netbird": (True, None),
                "scoring": (True, None),
            }
            with patch("bot.competition_actions.toggle_all_blueteam_accounts", new_callable=AsyncMock) as mock_toggle:
                mock_toggle.return_value = (50, 0)

                result = await stop_competition()

        assert result["success"] is True
        mock_auth.return_value.disable_applications.assert_called_once()

    async def test_disables_accounts(self, config):
        """Should disable all blueteam accounts."""
        from bot.competition_actions import stop_competition

        @sync_to_async
        def setup_config():
            config.applications_enabled = True
            config.save()

        await setup_config()

        with patch("bot.competition_actions.AuthentikManager") as mock_auth:
            mock_auth.return_value.disable_applications.return_value = {}
            with patch("bot.competition_actions.toggle_all_blueteam_accounts", new_callable=AsyncMock) as mock_toggle:
                mock_toggle.return_value = (50, 0)

                await stop_competition()

        mock_toggle.assert_called_once_with(is_active=False)

    async def test_clears_end_time_only(self, config):
        """Should clear end_time but preserve start_time."""
        from django.utils import timezone

        from bot.competition_actions import stop_competition

        @sync_to_async
        def setup_config():
            config.competition_start_time = timezone.now()
            config.competition_end_time = timezone.now()
            config.applications_enabled = True
            config.save()

        await setup_config()

        with patch("bot.competition_actions.AuthentikManager") as mock_auth:
            mock_auth.return_value.disable_applications.return_value = {}
            with patch("bot.competition_actions.toggle_all_blueteam_accounts", new_callable=AsyncMock) as mock_toggle:
                mock_toggle.return_value = (50, 0)

                await stop_competition()

        @sync_to_async
        def check_config():
            config.refresh_from_db()
            return config.competition_start_time, config.competition_end_time

        start_time, end_time = await check_config()
        assert start_time is not None
        assert end_time is None


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestUpdateStatusChannel:
    """Tests for status channel update."""

    async def test_creates_new_message_if_none_exists(self, config, mock_bot):
        """Should create a new status message if none exists."""
        import discord

        from bot.competition_actions import update_status_channel

        @sync_to_async
        def setup_config():
            config.status_channel_id = 123456789
            config.status_message_id = None
            config.save()

        await setup_config()

        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_message = MagicMock()
        mock_message.id = 987654321
        mock_channel.send = AsyncMock(return_value=mock_message)
        mock_bot.get_channel.return_value = mock_channel

        result = await update_status_channel(mock_bot)

        assert result is True
        mock_channel.send.assert_called_once()

        @sync_to_async
        def check_config():
            config.refresh_from_db()
            return config.status_message_id

        message_id = await check_config()
        assert message_id == 987654321

    async def test_edits_existing_message(self, config, mock_bot):
        """Should edit existing status message."""
        import discord

        from bot.competition_actions import update_status_channel

        @sync_to_async
        def setup_config():
            config.status_channel_id = 123456789
            config.status_message_id = 987654321
            config.save()

        await setup_config()

        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_message = AsyncMock()
        mock_channel.fetch_message = AsyncMock(return_value=mock_message)
        mock_bot.get_channel.return_value = mock_channel

        result = await update_status_channel(mock_bot)

        assert result is True
        mock_message.edit.assert_called_once()

    async def test_skips_if_no_channel_configured(self, config, mock_bot):
        """Should skip if no status channel configured."""
        from bot.competition_actions import update_status_channel

        @sync_to_async
        def setup_config():
            config.status_channel_id = None
            config.save()

        await setup_config()

        result = await update_status_channel(mock_bot)

        assert result is False
        mock_bot.get_channel.assert_not_called()
