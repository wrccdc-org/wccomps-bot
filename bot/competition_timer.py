"""Competition timer background task to enable applications at start time."""

import asyncio
import logging
from typing import Optional
from django.utils import timezone
from core.models import CompetitionConfig
from bot.authentik_manager import AuthentikManager
from bot.utils import log_to_ops_channel
from asgiref.sync import sync_to_async
import discord

logger = logging.getLogger(__name__)


class CompetitionTimer:
    """Background task to monitor competition start time and enable applications."""

    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot
        self.task: Optional[asyncio.Task[None]] = None
        self.running = False

    def start(self) -> None:
        """Start the competition timer task."""
        if not self.running:
            self.running = True
            self.task = asyncio.create_task(self._check_loop())
            logger.info("Competition timer started")

    def stop(self) -> None:
        """Stop the competition timer task."""
        self.running = False
        if self.task:
            self.task.cancel()
            logger.info("Competition timer stopped")

    async def _check_loop(self) -> None:
        """Main loop to check competition start time."""
        while self.running:
            try:
                await self._check_competition_start()
            except Exception as e:
                logger.error(f"Error in competition timer check: {e}")

            # Check every minute
            await asyncio.sleep(60)

    async def _check_competition_start(self) -> None:
        """Check if competition should start/end and enable/disable applications if needed."""

        @sync_to_async
        def check_and_update() -> tuple[bool, bool, Optional[CompetitionConfig]]:
            try:
                config = CompetitionConfig.get_config()

                # Update last check time
                config.last_check = timezone.now()
                config.save(update_fields=["last_check"])

                # Check if applications should be enabled or disabled
                should_enable = config.should_enable_applications()
                should_disable = config.should_disable_applications()
                return should_enable, should_disable, config
            except Exception as e:
                logger.error(f"Error checking competition config: {e}")
                return False, False, None

        try:
            should_enable, should_disable, config = await check_and_update()

            if not config:
                return

            # Handle competition start (enable applications)
            if should_enable:
                logger.info(
                    f"Competition start time reached! Enabling applications: {config.controlled_applications}"
                )

                # Enable applications via Authentik API
                auth_manager = AuthentikManager()
                results = auth_manager.enable_applications(
                    config.controlled_applications
                )

                # Update config
                @sync_to_async
                def save_config_enabled() -> None:
                    config.applications_enabled = True
                    config.save()

                await save_config_enabled()

                # Build result message with detailed error information
                success_apps = [app for app, (success, _) in results.items() if success]
                failed_apps = [
                    (app, error)
                    for app, (success, error) in results.items()
                    if not success
                ]

                result_msg = "**Competition Started!**\n\n"
                result_msg += f"Applications enabled: {len(success_apps)}/{len(config.controlled_applications)}\n"
                if success_apps:
                    result_msg += f"✓ Enabled: {', '.join(success_apps)}\n"
                if failed_apps:
                    result_msg += "\n✗ **Failed Applications:**\n"
                    for app, error in failed_apps:
                        result_msg += f"  • {app}: {error}\n"
                result_msg += f"\nStart Time: {config.competition_start_time}"

                # Log to ops channel
                await log_to_ops_channel(self.bot, result_msg)

                logger.info(
                    f"Competition applications enabled. Success: {len(success_apps)}, Failed: {len(failed_apps)}"
                )

            # Handle competition end (disable applications)
            elif should_disable:
                logger.info(
                    f"Competition end time reached! Disabling applications: {config.controlled_applications}"
                )

                # Disable applications via Authentik API
                auth_manager = AuthentikManager()
                results = auth_manager.disable_applications(
                    config.controlled_applications
                )

                # Update config
                @sync_to_async
                def save_config_disabled() -> None:
                    config.applications_enabled = False
                    config.save()

                await save_config_disabled()

                # Build result message with detailed error information
                success_apps = [app for app, (success, _) in results.items() if success]
                failed_apps = [
                    (app, error)
                    for app, (success, error) in results.items()
                    if not success
                ]

                result_msg = "**Competition Ended!**\n\n"
                result_msg += f"Applications disabled: {len(success_apps)}/{len(config.controlled_applications)}\n"
                if success_apps:
                    result_msg += f"✓ Disabled: {', '.join(success_apps)}\n"
                if failed_apps:
                    result_msg += "\n✗ **Failed Applications:**\n"
                    for app, error in failed_apps:
                        result_msg += f"  • {app}: {error}\n"
                result_msg += f"\nEnd Time: {config.competition_end_time}"

                # Log to ops channel
                await log_to_ops_channel(self.bot, result_msg)

                logger.info(
                    f"Competition applications disabled. Success: {len(success_apps)}, Failed: {len(failed_apps)}"
                )

        except Exception as e:
            logger.error(f"Failed to enable/disable competition applications: {e}")
            try:
                await log_to_ops_channel(
                    self.bot,
                    f"**Error enabling/disabling competition applications:** {e}",
                )
            except Exception:
                pass
