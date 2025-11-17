"""Admin cog for general administrative commands."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.permissions import check_admin
from bot.utils import log_to_ops_channel
from core.models import AuditLog

logger = logging.getLogger(__name__)


class AdminCog(commands.Cog):
    """General admin commands."""

    # Create admin command group as class attribute
    admin_group = app_commands.Group(name="admin", description="General administrative commands")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @admin_group.command(
        name="sync-roles",
        description="[ADMIN] Synchronize team roles from volunteer guild to competition guild",
    )
    @app_commands.check(check_admin)
    async def admin_sync_roles(self, interaction: discord.Interaction) -> None:
        """Sync roles from volunteer guild to competition guild.

        This performs one-way sync:
        - Users with team roles in volunteer guild get them in competition guild
        - Users without roles in volunteer guild lose them in competition guild
        """
        from bot.role_sync import RoleSyncManager

        await interaction.response.defer(ephemeral=True)

        try:
            # Create role sync manager
            role_sync = RoleSyncManager(self.bot)

            # Perform sync
            await interaction.followup.send("Starting role synchronization...", ephemeral=True)

            stats = await role_sync.sync_roles()

            # Build result message with detailed changes (only show non-zero metrics)
            result_parts = ["Role sync complete"]
            if stats["roles_added"]:
                result_parts.append(f"• Roles added: {stats['roles_added']}")
            if stats["roles_removed"]:
                result_parts.append(f"• Roles removed: {stats['roles_removed']}")
            if stats["errors"]:
                result_parts.append(f"• Errors: {stats['errors']}")

            result_msg = "\n".join(result_parts)

            changes = stats.get("changes", [])
            if isinstance(changes, list) and changes:
                result_msg += "\n\n**Changes:**\n"
                # Limit to 20 changes to avoid message length limits
                for change in changes[:20]:
                    result_msg += f"{change}\n"
                if len(changes) > 20:
                    result_msg += f"\n... and {len(changes) - 20} more (check logs for full list)"

            await interaction.followup.send(result_msg, ephemeral=True)

            # Create audit log
            changes_list = changes if isinstance(changes, list) else []
            await AuditLog.objects.acreate(
                action="role_sync",
                admin_user=str(interaction.user),
                target_entity="guilds",
                target_id=0,
                details={
                    "roles_added": stats["roles_added"],
                    "roles_removed": stats["roles_removed"],
                    "errors": stats["errors"],
                    "changes": changes_list[:50],  # Store first 50 changes
                },
            )

            # Log to ops channel with changes
            ops_msg = f"Role sync executed by {interaction.user.mention}\n{result_msg}"
            await log_to_ops_channel(self.bot, ops_msg)

        except Exception as e:
            logger.error(f"Role sync failed: {e}", exc_info=True)
            await interaction.followup.send(f"Role sync failed: {e!s}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Setup function to add cog to bot."""
    await bot.add_cog(AdminCog(bot))
