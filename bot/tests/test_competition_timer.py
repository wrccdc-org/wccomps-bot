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
            mock_task.cancel = Mock()
            mock_create_task.return_value = mock_task

            timer.start()

            assert timer.running is True
            assert timer.task is mock_task
            mock_create_task.assert_called_once()

            # Close the coroutine that was passed to the mocked create_task
            # to prevent "coroutine was never awaited" warning
            coro = mock_create_task.call_args[0][0]
            coro.close()

            timer.stop()

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
            patch.object(timer, "_check_competition_times", side_effect=mock_check),
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
            patch.object(timer, "_check_competition_times", side_effect=mock_check),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await timer._check_loop()

        assert call_count == 2

    async def test_check_competition_times_no_enable_needed(self) -> None:
        """Test _check_competition_times when applications should not be enabled."""
        bot = AsyncMock(spec=discord.Client)
        timer = CompetitionTimer(bot)

        # Use update_or_create with pk=1 to match get_config() singleton pattern
        config, _ = await CompetitionConfig.objects.aupdate_or_create(
            pk=1,
            defaults={
                "competition_start_time": timezone.now() + timedelta(hours=1),
                "applications_enabled": False,
                "controlled_applications": ["app1", "app2"],
            },
        )

        await timer._check_competition_times()

        await config.arefresh_from_db()
        assert config.applications_enabled is False
        assert config.last_check is not None

    async def test_check_competition_times_calls_start_competition(self) -> None:
        """Test _check_competition_times calls start_competition when scheduled."""
        bot = AsyncMock(spec=discord.Client)
        timer = CompetitionTimer(bot)

        # Use update_or_create with pk=1 to match get_config() singleton pattern
        await CompetitionConfig.objects.aupdate_or_create(
            pk=1,
            defaults={
                "competition_start_time": timezone.now() - timedelta(minutes=5),
                "applications_enabled": False,
                "controlled_applications": ["app1"],
                "last_check": timezone.now() - timedelta(hours=1),
            },
        )

        with patch("bot.competition_timer.start_competition", new_callable=AsyncMock) as mock_start:
            mock_start.return_value = {
                "success": True,
                "apps_enabled": ["app1"],
                "apps_failed": [],
                "accounts_enabled": 50,
                "accounts_failed": 0,
                "controlled_apps": ["app1"],
            }
            with (
                patch("bot.competition_timer.log_to_ops_channel", new_callable=AsyncMock),
                patch("bot.competition_timer.update_status_channel", new_callable=AsyncMock),
            ):
                await timer._check_competition_times()

            mock_start.assert_called_once()

    async def test_check_competition_times_exception_handling(self) -> None:
        """Test _check_competition_times handles exceptions."""
        bot = AsyncMock(spec=discord.Client)
        timer = CompetitionTimer(bot)

        # Use update_or_create with pk=1 to match get_config() singleton pattern
        await CompetitionConfig.objects.aupdate_or_create(
            pk=1,
            defaults={
                "competition_start_time": timezone.now() - timedelta(minutes=5),
                "applications_enabled": False,
                "controlled_applications": ["app1"],
                "last_check": timezone.now() - timedelta(hours=1),
            },
        )

        with patch("bot.competition_timer.start_competition", new_callable=AsyncMock) as mock_start:
            mock_start.side_effect = Exception("Start error")

            with patch("bot.competition_timer.log_to_ops_channel", new_callable=AsyncMock):
                # Should not raise exception
                await timer._check_competition_times()

    async def test_check_competition_times_with_no_config(self) -> None:
        """Test _check_competition_times handles missing config."""
        bot = AsyncMock(spec=discord.Client)
        timer = CompetitionTimer(bot)

        # Should not raise exception - get_config creates if missing
        await timer._check_competition_times()
