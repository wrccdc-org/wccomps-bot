"""WCComps Discord Bot - Main entry point."""

import logging
import os
import sys
from typing import TYPE_CHECKING, Any

import discord
from discord.ext import commands

# Initialize Django before any imports that use Django models
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "wccomps.settings")
django.setup()

if TYPE_CHECKING:
    from bot.competition_timer import CompetitionTimer
    from bot.discord_queue import DiscordQueueProcessor
    from bot.unified_dashboard import UnifiedDashboard

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class WCCompsBot(commands.Bot):
    """WCComps Discord Bot."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True

        super().__init__(command_prefix="!", intents=intents)

        self.queue_processor: "DiscordQueueProcessor | None" = None
        self.competition_timer: "CompetitionTimer | None" = None
        self.unified_dashboard: "UnifiedDashboard | None" = None

    async def setup_hook(self) -> None:
        """Setup hook called when bot is ready."""
        logger.info("Loading cogs...")

        # Load cogs
        await self.load_extension("bot.cogs.linking")
        await self.load_extension("bot.cogs.ticketing")
        await self.load_extension("bot.cogs.help_panels")
        await self.load_extension("bot.cogs.admin")
        await self.load_extension("bot.cogs.admin_teams")
        await self.load_extension("bot.cogs.admin_tickets")
        await self.load_extension("bot.cogs.admin_competition")

        logger.info("Cogs loaded")

        # Log registered commands for debugging
        commands_list = self.tree.get_commands()
        logger.info(f"Registered {len(commands_list)} top-level commands:")
        for cmd in commands_list:
            if isinstance(cmd, discord.app_commands.Group):
                logger.info(
                    f"  - {cmd.name} (Group with {len(cmd.commands)} subcommands)"
                )
            else:
                logger.info(f"  - {cmd.name} (Command)")

        # Sync commands to guild
        guild_id = int(os.environ.get("DISCORD_GUILD_ID", 0))
        if guild_id:
            guild = discord.Object(id=guild_id)

            # Strategy: Fetch existing commands from Discord, delete them, then sync fresh
            # Step 1: Fetch what Discord currently has
            try:
                existing_commands = await self.tree.fetch_commands(guild=guild)
                logger.info(
                    f"Found {len(existing_commands)} existing commands on Discord"
                )

                # Delete each command individually
                for cmd in existing_commands:
                    logger.info(f"Deleting command: {cmd.name}")
                    await cmd.delete()
                logger.info("Deleted all existing commands from Discord")
            except Exception as e:
                logger.warning(f"Could not fetch/delete existing commands: {e}")

            # Step 2: Clear local tree and sync empty to ensure clean slate
            self.tree.clear_commands(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info(f"Synced empty command tree to guild {guild_id}")

            # Step 3: Re-register our commands and sync
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info(f"Command tree synced to guild {guild_id}")
        else:
            await self.tree.sync()
            logger.info("Command tree synced globally")

    async def on_ready(self) -> None:
        """Called when bot is ready."""
        from bot.competition_timer import CompetitionTimer
        from bot.discord_queue import DiscordQueueProcessor
        from bot.unified_dashboard import UnifiedDashboard

        if not self.user:
            logger.error("Bot user is None in on_ready")
            return
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guild(s)")

        for guild in self.guilds:
            logger.info(f"  - {guild.name} (ID: {guild.id})")

        # Start queue processor
        if not self.queue_processor:
            self.queue_processor = DiscordQueueProcessor(self)
            self.queue_processor.start()

        # Start competition timer
        if not self.competition_timer:
            self.competition_timer = CompetitionTimer(self)
            self.competition_timer.start()

        # Start unified dashboard
        if not self.unified_dashboard:
            self.unified_dashboard = UnifiedDashboard(self)
            self.unified_dashboard.start()

    async def on_command_error(
        self, ctx: commands.Context[Any], error: Exception
    ) -> None:
        """Handle command errors."""
        logger.error(f"Command error: {error}")

    async def close(self) -> None:
        """Cleanup on bot shutdown."""
        logger.info("Shutting down bot...")
        if self.queue_processor:
            self.queue_processor.stop()
        if self.competition_timer:
            self.competition_timer.stop()
        if self.unified_dashboard:
            self.unified_dashboard.stop()
        await super().close()


def main() -> None:
    """Main entry point."""
    # Get bot token from environment
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        logger.error("DISCORD_BOT_TOKEN environment variable not set")
        sys.exit(1)

    # Create and run bot
    bot = WCCompsBot()

    try:
        bot.run(token)
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
