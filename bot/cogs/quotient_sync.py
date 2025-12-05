"""Background task to sync Quotient metadata and clear stale data."""

import logging

from asgiref.sync import sync_to_async
from discord.ext import commands, tasks
from scoring.quotient_sync import sync_quotient_metadata

logger = logging.getLogger(__name__)


class QuotientSyncCog(commands.Cog):
    """Background sync for Quotient integration."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.sync_quotient_task.start()

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded."""
        self.sync_quotient_task.cancel()

    @tasks.loop(minutes=5)
    async def sync_quotient_task(self) -> None:
        """Sync Quotient metadata every 5 minutes, clear cache if unavailable."""
        try:
            await sync_to_async(sync_quotient_metadata)()
            logger.debug("Quotient metadata synced")
        except ValueError as e:
            logger.warning(f"Quotient sync failed: {e}")
        except Exception as e:
            logger.exception(f"Error syncing Quotient metadata: {e}")

    @sync_quotient_task.before_loop
    async def before_sync_quotient(self) -> None:
        """Wait for bot to be ready before starting task."""
        if self.bot.is_closed():
            return
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    """Load the cog."""
    await bot.add_cog(QuotientSyncCog(bot))
