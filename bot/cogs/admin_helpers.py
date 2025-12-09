"""Admin commands for managing student helpers."""

import logging
from typing import Literal

import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands

from bot.permissions import check_admin, check_gold_team
from bot.utils import log_to_ops_channel
from core.models import AuditLog
from team.models import DiscordLink

logger = logging.getLogger(__name__)


class AdminHelpersCog(commands.Cog):
    """Admin commands for student helper management."""

    helpers_group = app_commands.Group(
        name="helpers",
        description="Student helper management commands",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @helpers_group.command(name="add", description="[ADMIN] Add student helper with Discord role")
    @app_commands.check(check_admin)
    @app_commands.describe(
        discord_user="Discord user to add as helper",
        role_name="Discord role name (e.g., 'UCI Invitationals 2026')",
    )
    async def add_helper(
        self,
        interaction: discord.Interaction,
        discord_user: discord.Member,
        role_name: str,
    ) -> None:
        """Add a student helper and assign them a Discord role."""
        await interaction.response.defer(ephemeral=True)

        try:

            @sync_to_async
            def get_discord_link() -> tuple[DiscordLink | None, str | None]:
                try:
                    discord_link = DiscordLink.objects.select_related("user__usergroups").get(
                        discord_id=discord_user.id, is_active=True
                    )
                except DiscordLink.DoesNotExist:
                    return None, "User must link their Discord account first with `/link`"

                from core.auth_utils import check_groups_for_permission

                try:
                    groups = discord_link.user.usergroups.groups
                except Exception:
                    groups = []

                if not check_groups_for_permission(groups, "helper_eligible"):
                    return (
                        None,
                        "User must have WCComps_Ticketing_Support or WCComps_Quotient_Injects group in Authentik",
                    )

                if discord_link.is_student_helper:
                    return None, f"User is already a helper with role: {discord_link.helper_role_name}"

                return discord_link, None

            discord_link, error = await get_discord_link()
            if error or discord_link is None:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            guild = interaction.guild
            if not guild:
                await interaction.followup.send("❌ Could not find guild", ephemeral=True)
                return

            role = discord.utils.get(guild.roles, name=role_name)
            if not role:
                role = await guild.create_role(
                    name=role_name, reason=f"Student helper role created by {interaction.user}"
                )
                logger.info(f"Created new role: {role_name}")

            await discord_user.add_roles(role, reason=f"Student helper added by {interaction.user}")

            @sync_to_async
            def set_helper() -> None:
                discord_link.set_helper(role_name, role.id)
                AuditLog.objects.create(
                    action="helper_added",
                    admin_user=str(interaction.user),
                    target_entity="discordlink",
                    target_id=discord_link.id,
                    details={
                        "discord_id": discord_link.discord_id,
                        "discord_username": discord_link.discord_username,
                        "authentik_username": discord_link.user.username,
                        "role_name": role_name,
                    },
                )

            await set_helper()

            msg = "✅ **Student helper added successfully!**\n\n"
            msg += f"**Helper:** {discord_user.mention} ({discord_link.user.username})\n"
            msg += f"**Role:** {role_name}\n"
            msg += "**Status:** Active\n\n"
            msg += "The role will be removed when `/competition end-competition` is run."

            await interaction.followup.send(msg, ephemeral=True)
            await log_to_ops_channel(
                self.bot,
                f"**Student Helper Added**\n{interaction.user.mention} added "
                f"{discord_user.mention} with role '{role_name}'",
            )

        except Exception as e:
            logger.exception(f"Error adding student helper: {e}")
            await interaction.followup.send(f"❌ Error adding helper: {e}", ephemeral=True)

    @helpers_group.command(name="import", description="[ADMIN] Import all users with a Discord role as helpers")
    @app_commands.check(check_admin)
    @app_commands.describe(role="Discord role to import members from")
    async def import_helpers(
        self,
        interaction: discord.Interaction,
        role: discord.Role,
    ) -> None:
        """Import all members with a specific Discord role as student helpers."""
        await interaction.response.defer(ephemeral=True)

        try:
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("❌ Could not find guild", ephemeral=True)
                return

            members_with_role = [member for member in guild.members if role in member.roles]

            if not members_with_role:
                await interaction.followup.send(f"❌ No members found with role '{role.name}'", ephemeral=True)
                return

            imported = 0
            skipped = []
            errors = []

            for member in members_with_role:
                try:

                    @sync_to_async
                    def check_and_import(member_id: int) -> tuple[str, str | None]:
                        try:
                            discord_link = DiscordLink.objects.select_related("user__usergroups").get(
                                discord_id=member_id, is_active=True
                            )
                        except DiscordLink.DoesNotExist:
                            return "not_linked", None

                        from core.auth_utils import check_groups_for_permission

                        try:
                            groups = discord_link.user.usergroups.groups
                        except Exception:
                            groups = []

                        if not check_groups_for_permission(groups, "helper_eligible"):
                            return "no_permission", None

                        if discord_link.is_student_helper:
                            return "already_exists", discord_link.helper_role_name

                        discord_link.set_helper(role.name, role.id)
                        AuditLog.objects.create(
                            action="helper_imported",
                            admin_user=str(interaction.user),
                            target_entity="discordlink",
                            target_id=discord_link.id,
                            details={
                                "discord_id": discord_link.discord_id,
                                "discord_username": discord_link.discord_username,
                                "authentik_username": discord_link.user.username,
                                "role_name": role.name,
                                "import_source": "bulk_role_import",
                            },
                        )

                        return "success", None

                    result, existing_role = await check_and_import(member.id)

                    if result == "success":
                        imported += 1
                    elif result == "not_linked":
                        skipped.append(f"{member.display_name}: Not linked")
                    elif result == "no_permission":
                        skipped.append(f"{member.display_name}: Missing Authentik group")
                    elif result == "already_exists":
                        skipped.append(f"{member.display_name}: Already has role '{existing_role}'")

                except Exception as e:
                    logger.exception(f"Error importing {member.display_name}: {e}")
                    errors.append(f"{member.display_name}: {str(e)[:50]}")

            msg = "✅ **Bulk Import Complete**\n\n"
            msg += f"**Role:** {role.name}\n"
            msg += f"**Members with role:** {len(members_with_role)}\n"
            msg += f"**Imported:** {imported}\n"
            msg += f"**Skipped:** {len(skipped)}\n"

            if errors:
                msg += f"**Errors:** {len(errors)}\n"

            if skipped:
                msg += "\n**Skipped Details (showing first 10):**\n"
                for skip in skipped[:10]:
                    msg += f"• {skip}\n"
                if len(skipped) > 10:
                    msg += f"• ... and {len(skipped) - 10} more\n"

            await interaction.followup.send(msg, ephemeral=True)

            if imported > 0:
                await log_to_ops_channel(
                    self.bot,
                    f"**Bulk Helper Import**\n{interaction.user.mention} imported "
                    f"{imported} helpers with role '{role.name}'\n"
                    f"Skipped: {len(skipped)} | Errors: {len(errors)}",
                )

        except Exception as e:
            logger.exception(f"Error importing helpers: {e}")
            await interaction.followup.send(f"❌ Error importing helpers: {e}", ephemeral=True)

    @helpers_group.command(name="list", description="[ADMIN] List all student helpers")
    @app_commands.check(check_gold_team)
    @app_commands.describe(status="Filter by status (optional)")
    async def list_helpers(
        self,
        interaction: discord.Interaction,
        status: Literal["active", "inactive", "all"] = "all",
    ) -> None:
        """List all student helpers."""
        await interaction.response.defer(ephemeral=True)

        try:

            @sync_to_async
            def get_helpers() -> list[DiscordLink]:
                query = DiscordLink.objects.filter(helper_role_name__isnull=False, is_active=True).exclude(
                    helper_role_name=""
                )

                if status == "active":
                    query = query.filter(is_student_helper=True)
                elif status == "inactive":
                    query = query.filter(is_student_helper=False)

                return list(query.order_by("-helper_activated_at"))

            helpers = await get_helpers()

            if not helpers:
                await interaction.followup.send(
                    "No helpers found" + (f" with status '{status}'" if status != "all" else ""),
                    ephemeral=True,
                )
                return

            embed = discord.Embed(
                title="Student Helpers",
                description=f"Found {len(helpers)} helper(s)" + (f" with status '{status}'" if status != "all" else ""),
                color=discord.Color.blue(),
            )

            for discord_link in helpers[:25]:
                status_emoji = "✅" if discord_link.is_student_helper else "⏹️"

                field_name = f"{status_emoji} {discord_link.discord_username or discord_link.user.username}"
                field_value = f"**Role:** {discord_link.helper_role_name}\n"
                field_value += f"**Status:** {'Active' if discord_link.is_student_helper else 'Inactive'}\n"

                if discord_link.is_student_helper and discord_link.helper_activated_at:
                    field_value += f"**Activated:** {discord_link.helper_activated_at.strftime('%m/%d %H:%M')}\n"
                elif not discord_link.is_student_helper and discord_link.helper_deactivated_at:
                    field_value += f"**Removed:** {discord_link.helper_deactivated_at.strftime('%m/%d %H:%M')}\n"
                    if discord_link.helper_removal_reason:
                        field_value += f"**Reason:** {discord_link.helper_removal_reason[:50]}\n"

                embed.add_field(name=field_name, value=field_value, inline=False)

            if len(helpers) > 25:
                embed.set_footer(text=f"Showing first 25 of {len(helpers)} helpers")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.exception(f"Error listing student helpers: {e}")
            await interaction.followup.send(f"❌ Error listing helpers: {e}", ephemeral=True)

    @helpers_group.command(name="remove", description="[ADMIN] Remove student helper access")
    @app_commands.check(check_admin)
    @app_commands.describe(
        discord_user="Discord user to remove helper access from",
        reason="Reason for removal",
    )
    async def remove_helper(
        self,
        interaction: discord.Interaction,
        discord_user: discord.Member,
        reason: str = "Manually removed by admin",
    ) -> None:
        """Remove a student helper's access."""
        await interaction.response.defer(ephemeral=True)

        try:

            @sync_to_async
            def remove_helper_db() -> tuple[dict[str, str | int | None] | None, str | None]:
                try:
                    discord_link = DiscordLink.objects.get(discord_id=discord_user.id, is_active=True)
                except DiscordLink.DoesNotExist:
                    return None, "User not found in database"

                if not discord_link.is_student_helper:
                    return None, "User is not currently a helper"

                role_name = discord_link.helper_role_name
                role_id = discord_link.helper_role_id
                discord_link.remove_helper(reason)

                AuditLog.objects.create(
                    action="helper_removed",
                    admin_user=str(interaction.user),
                    target_entity="discordlink",
                    target_id=discord_link.id,
                    details={
                        "discord_id": discord_link.discord_id,
                        "discord_username": discord_link.discord_username,
                        "reason": reason,
                    },
                )

                return {"role_name": role_name, "role_id": role_id}, None

            result, error = await remove_helper_db()
            if error or result is None:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            role_id = result["role_id"]
            if role_id and interaction.guild and isinstance(role_id, int):
                try:
                    role = interaction.guild.get_role(role_id)
                    if role and role in discord_user.roles:
                        await discord_user.remove_roles(role, reason=f"Helper removed: {reason}")
                        logger.info(f"Removed role {role.name} from {discord_user}")
                except Exception as e:
                    logger.warning(f"Could not remove role from user: {e}")

            msg = "✅ **Helper access removed**\n\n"
            msg += f"**User:** {discord_user.mention}\n"
            msg += f"**Role:** {result['role_name']}\n"
            msg += f"**Reason:** {reason}"

            await interaction.followup.send(msg, ephemeral=True)
            await log_to_ops_channel(
                self.bot,
                f"**Helper Removed**\n{interaction.user.mention} removed helper access "
                f"for {discord_user.mention}\n**Reason:** {reason}",
            )

        except Exception as e:
            logger.exception(f"Error removing student helper: {e}")
            await interaction.followup.send(f"❌ Error removing helper: {e}", ephemeral=True)

    @helpers_group.command(name="status", description="[ADMIN] Check student helper status")
    @app_commands.check(check_gold_team)
    @app_commands.describe(discord_user="Discord user to check status for")
    async def helper_status(
        self,
        interaction: discord.Interaction,
        discord_user: discord.Member,
    ) -> None:
        """Check the status of a student helper."""
        await interaction.response.defer(ephemeral=True)

        try:

            @sync_to_async
            def get_helper_status() -> tuple[DiscordLink | None, str | None, bool, bool]:
                try:
                    discord_link = DiscordLink.objects.select_related("user__usergroups").get(
                        discord_id=discord_user.id, is_active=True
                    )
                except DiscordLink.DoesNotExist:
                    return None, "User not found in database", False, False

                from core.auth_utils import PERMISSION_MAP

                try:
                    groups = discord_link.user.usergroups.groups
                except Exception:
                    groups = []

                has_support_group = PERMISSION_MAP["helper_eligible"][0] in groups
                has_injects_group = PERMISSION_MAP["helper_eligible"][1] in groups

                return discord_link, None, has_support_group, has_injects_group

            discord_link, error, has_support_group, has_injects_group = await get_helper_status()
            if error or discord_link is None:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            desc = (
                f"**Authentik Username:** {discord_link.user.username}\n**Discord ID:** {discord_link.discord_id}"
            )
            embed = discord.Embed(
                title=f"Helper Status - {discord_user.display_name}",
                description=desc,
                color=discord.Color.green() if (has_support_group or has_injects_group) else discord.Color.red(),
            )

            perm_value = ""
            if has_support_group:
                perm_value += "✅ WCComps_Ticketing_Support\n"
            else:
                perm_value += "❌ WCComps_Ticketing_Support\n"

            if has_injects_group:
                perm_value += "✅ WCComps_Quotient_Injects\n"
            else:
                perm_value += "❌ WCComps_Quotient_Injects\n"

            if not (has_support_group or has_injects_group):
                perm_value += "\n⚠️ User needs at least one of these groups"

            embed.add_field(name="Authentik Groups", value=perm_value, inline=False)

            if discord_link.helper_role_name:
                status_emoji = "✅" if discord_link.is_student_helper else "⏹️"
                field_value = (
                    f"**Status:** {status_emoji} {'Active' if discord_link.is_student_helper else 'Inactive'}\n"
                    f"**Role:** {discord_link.helper_role_name}\n"
                )

                if discord_link.is_student_helper and discord_link.helper_activated_at:
                    field_value += f"**Activated:** {discord_link.helper_activated_at.strftime('%Y-%m-%d %H:%M')}\n"
                elif not discord_link.is_student_helper and discord_link.helper_deactivated_at:
                    field_value += f"**Removed:** {discord_link.helper_deactivated_at.strftime('%Y-%m-%d %H:%M')}\n"
                    if discord_link.helper_removal_reason:
                        field_value += f"**Reason:** {discord_link.helper_removal_reason[:100]}\n"

                embed.add_field(name="Helper Assignment", value=field_value, inline=False)
            else:
                embed.add_field(name="Helper Assignment", value="No helper assignment", inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.exception(f"Error checking helper status: {e}")
            await interaction.followup.send(f"❌ Error checking status: {e}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Setup function called by Discord.py when loading the cog."""
    await bot.add_cog(AdminHelpersCog(bot))
