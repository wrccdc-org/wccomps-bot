"""Tests for competition timer background task."""

from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import discord
import pytest
from django.utils import timezone

from bot.competition_timer import CompetitionTimer
from core.models import CompetitionConfig


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestCompetitionTimer:
    """Test competition timer functionality."""

    async def test_initialization(self) -> None:
        """Test CompetitionTimer initialization."""
        bot = AsyncMock(spec=discord.Client)
        timer = CompetitionTimer(bot)

        assert timer.bot is bot
        assert timer.task is None
        assert timer.running is False

    async def test_start_creates_task(self) -> None:
        """Test that start() creates and runs the background task."""
        bot = AsyncMock(spec=discord.Client)
        timer = CompetitionTimer(bot)

        with patch("asyncio.create_task") as mock_create_task:
            mock_task = Mock()
            mock_create_task.return_value = mock_task

            timer.start()

            assert timer.running is True
            assert timer.task is mock_task
            mock_create_task.assert_called_once()

    async def test_stop_cancels_task(self) -> None:
        """Test that stop() cancels the background task."""
        bot = AsyncMock(spec=discord.Client)
        timer = CompetitionTimer(bot)

        mock_task = Mock()
        mock_task.cancel = Mock()
        timer.task = mock_task
        timer.running = True

        timer.stop()

        assert timer.running is False
        mock_task.cancel.assert_called_once()

    async def test_stop_when_no_task(self) -> None:
        """Test that stop() handles case when task is None."""
        bot = AsyncMock(spec=discord.Client)
        timer = CompetitionTimer(bot)
        timer.running = True

        timer.stop()

        assert timer.running is False

    async def test_check_loop_continues_while_running(self) -> None:
        """Test that _check_loop continues checking while running is True."""
        bot = AsyncMock(spec=discord.Client)
        timer = CompetitionTimer(bot)
        timer.running = True

        check_count = 0

        async def mock_check() -> None:
            nonlocal check_count
            check_count += 1
            if check_count >= 2:
                timer.running = False

        with (
            patch.object(timer, "_check_competition_start", side_effect=mock_check),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await timer._check_loop()

        assert check_count == 2

    async def test_check_loop_handles_exceptions(self) -> None:
        """Test that _check_loop handles exceptions and continues."""
        bot = AsyncMock(spec=discord.Client)
        timer = CompetitionTimer(bot)
        timer.running = True

        call_count = 0

        async def mock_check() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Test error")
            timer.running = False

        with (
            patch.object(timer, "_check_competition_start", side_effect=mock_check),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await timer._check_loop()

        assert call_count == 2

    async def test_check_competition_start_no_enable_needed(self) -> None:
        """Test _check_competition_start when applications should not be enabled."""
        bot = AsyncMock(spec=discord.Client)
        timer = CompetitionTimer(bot)

        config = await CompetitionConfig.objects.acreate(
            competition_start_time=timezone.now() + timedelta(hours=1),
            applications_enabled=False,
            controlled_applications=["app1", "app2"],
        )

        await timer._check_competition_start()

        await config.arefresh_from_db()
        assert config.applications_enabled is False
        assert config.last_check is not None

    async def test_check_competition_start_exception_handling(self) -> None:
        """Test _check_competition_start handles exceptions."""
        bot = AsyncMock(spec=discord.Client)
        timer = CompetitionTimer(bot)

        config = await CompetitionConfig.objects.acreate(
            competition_start_time=timezone.now() - timedelta(minutes=5),
            applications_enabled=False,
            controlled_applications=["app1"],
            last_check=timezone.now() - timedelta(hours=1),
        )

        with patch("bot.competition_timer.AuthentikManager") as mock_auth_manager_class:
            mock_auth_manager = Mock()
            mock_auth_manager.enable_applications.side_effect = Exception("Authentik API error")
            mock_auth_manager_class.return_value = mock_auth_manager

            with patch("bot.competition_timer.log_to_ops_channel", new_callable=AsyncMock):
                # Should not raise exception
                await timer._check_competition_start()

        # Verify config was not enabled due to exception
        await config.arefresh_from_db()
        assert config.applications_enabled is False

    async def test_check_competition_start_log_exception_handling(self) -> None:
        """Test _check_competition_start handles log_to_ops_channel failure."""
        bot = AsyncMock(spec=discord.Client)
        timer = CompetitionTimer(bot)

        await CompetitionConfig.objects.acreate(
            competition_start_time=timezone.now() - timedelta(minutes=1),
            applications_enabled=False,
            controlled_applications=["app1"],
        )

        with patch("bot.competition_timer.AuthentikManager") as mock_auth_manager_class:
            mock_auth_manager = Mock()
            mock_auth_manager.enable_applications.side_effect = Exception("Authentik API error")
            mock_auth_manager_class.return_value = mock_auth_manager

            with patch("bot.competition_timer.log_to_ops_channel", new_callable=AsyncMock) as mock_log:
                mock_log.side_effect = Exception("Discord API error")

                # Should not raise exception
                await timer._check_competition_start()

    async def test_check_competition_start_with_no_config(self) -> None:
        """Test _check_competition_start handles missing config."""
        bot = AsyncMock(spec=discord.Client)
        timer = CompetitionTimer(bot)

        # Should not raise exception
        await timer._check_competition_start()
