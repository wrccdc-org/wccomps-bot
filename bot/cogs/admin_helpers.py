"""Admin commands for managing student helpers."""

import logging
from typing import Literal

import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands
from django.contrib.auth.models import User
from django.utils import timezone

from bot.permissions import check_admin, check_gold_team
from bot.utils import log_to_ops_channel
from competition.models import StudentHelper
from core.models import AuditLog
from person.models import Person

logger = logging.getLogger(__name__)


class AdminHelpersCog(commands.Cog):
    """Admin commands for student helper management."""

    # Create helpers command group as class attribute
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
            # Get Person for this Discord user
            @sync_to_async
            def get_person():  # type: ignore[no-untyped-def]
                try:
                    person = Person.objects.get(discord_id=discord_user.id)
                except Person.DoesNotExist:
                    return None, "User must link their Discord account first with `/link`"

                # Check if user has required group (either WCComps_Ticketing_Support OR WCComps_Quotient_Injects)
                has_support = person.has_group("WCComps_Ticketing_Support")
                has_injects = person.has_group("WCComps_Quotient_Injects")

                if not (has_support or has_injects):
                    return (
                        None,
                        "User must have either WCComps_Ticketing_Support or WCComps_Quotient_Injects group in Authentik",
                    )

                # Check if helper already exists
                existing = StudentHelper.objects.filter(person=person, status="active").first()
                if existing:
                    return None, f"Helper already has an active role assigned: {existing.discord_role_name}"

                return person, None

            person, error = await get_person()
            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            # Create or get Discord role
            guild = interaction.guild
            if not guild:
                await interaction.followup.send("❌ Could not find guild", ephemeral=True)
                return

            role = discord.utils.get(guild.roles, name=role_name)
            if not role:
                # Create the role
                role = await guild.create_role(name=role_name, reason=f"Student helper role created by {interaction.user}")
                logger.info(f"Created new role: {role_name}")

            # Assign role to user
            await discord_user.add_roles(role, reason=f"Student helper added by {interaction.user}")

            # Create helper assignment in database
            @sync_to_async
            def create_helper():  # type: ignore[no-untyped-def]
                django_user = User.objects.filter(person=person).first()
                helper = StudentHelper.objects.create(
                    person=person,
                    discord_id=person.discord_id,
                    discord_username=person.discord_username,
                    authentik_username=person.authentik_username,
                    discord_role_name=role_name,
                    discord_role_id=role.id,
                    status="active",
                    activated_at=timezone.now(),
                    created_by=django_user if django_user else None,
                )

                # Create audit log
                AuditLog.objects.create(
                    action="helper_added",
                    admin_user=str(interaction.user),
                    target_entity="student_helper",
                    target_id=helper.id,
                    details={
                        "discord_id": helper.discord_id,
                        "discord_username": helper.discord_username,
                        "authentik_username": helper.authentik_username,
                        "role_name": role_name,
                    },
                )

                return helper

            helper = await create_helper()

            # Build response message
            msg = f"✅ **Student helper added successfully!**\n\n"
            msg += f"**Helper:** {discord_user.mention} ({helper.authentik_username})\n"
            msg += f"**Role:** {role_name}\n"
            msg += f"**Status:** Active\n\n"
            msg += "The role will be removed when `/competition end-competition` is run."

            await interaction.followup.send(msg, ephemeral=True)
            await log_to_ops_channel(
                self.bot,
                f"**Student Helper Added**\n{interaction.user.mention} added {discord_user.mention} with role '{role_name}'",
            )

        except Exception as e:
            logger.exception(f"Error adding student helper: {e}")
            await interaction.followup.send(f"❌ Error adding helper: {e}", ephemeral=True)

    @helpers_group.command(name="list", description="[ADMIN] List all student helpers")
    @app_commands.check(check_gold_team)
    @app_commands.describe(
        status="Filter by status (optional)",
    )
    async def list_helpers(
        self,
        interaction: discord.Interaction,
        status: Literal["active", "removed", "all"] = "all",
    ) -> None:
        """List all student helpers."""
        await interaction.response.defer(ephemeral=True)

        try:

            @sync_to_async
            def get_helpers():  # type: ignore[no-untyped-def]
                query = StudentHelper.objects.select_related("person").all()

                if status != "all":
                    query = query.filter(status=status)

                helpers = list(query.order_by("-created_at"))
                return helpers

            helpers = await get_helpers()

            if not helpers:
                await interaction.followup.send(
                    f"No helpers found" + (f" with status '{status}'" if status != "all" else ""),
                    ephemeral=True,
                )
                return

            # Build response with embed
            embed = discord.Embed(
                title="Student Helpers",
                description=f"Found {len(helpers)} helper(s)" + (f" with status '{status}'" if status != "all" else ""),
                color=discord.Color.blue(),
            )

            for helper in helpers[:25]:  # Discord embed field limit
                status_emoji = {
                    "active": "✅",
                    "removed": "⏹️",
                }.get(helper.status, "❓")

                field_name = f"{status_emoji} {helper.discord_username}"
                field_value = f"**Role:** {helper.discord_role_name}\n" f"**Status:** {helper.get_status_display()}\n"

                if helper.status == "active":
                    field_value += f"**Activated:** {helper.activated_at.strftime('%m/%d %H:%M') if helper.activated_at else 'N/A'}\n"
                elif helper.status == "removed":
                    field_value += f"**Removed:** {helper.deactivated_at.strftime('%m/%d %H:%M') if helper.deactivated_at else 'N/A'}\n"
                    if helper.removal_reason:
                        field_value += f"**Reason:** {helper.removal_reason[:50]}\n"

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
            def remove_helper_db():  # type: ignore[no-untyped-def]
                try:
                    person = Person.objects.get(discord_id=discord_user.id)
                except Person.DoesNotExist:
                    return None, "User not found in database"

                try:
                    helper = StudentHelper.objects.get(person=person, status="active")
                except StudentHelper.DoesNotExist:
                    return None, "No active helper assignment found for this user"

                # Get Django user for audit
                django_user = User.objects.filter(person__discord_id=interaction.user.id).first()

                # Remove in database
                if django_user:
                    helper.remove(django_user, reason)
                else:
                    # Fallback: manually update status
                    helper.status = "removed"
                    helper.removal_reason = reason
                    helper.deactivated_at = timezone.now()
                    helper.save()

                # Create audit log
                AuditLog.objects.create(
                    action="helper_removed",
                    admin_user=str(interaction.user),
                    target_entity="student_helper",
                    target_id=helper.id,
                    details={
                        "discord_id": helper.discord_id,
                        "discord_username": helper.discord_username,
                        "reason": reason,
                    },
                )

                return helper, None

            helper, error = await remove_helper_db()
            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            # Remove Discord role if currently assigned
            if helper.discord_role_id and interaction.guild:
                try:
                    guild = interaction.guild
                    role = guild.get_role(helper.discord_role_id)
                    if role and role in discord_user.roles:
                        await discord_user.remove_roles(role, reason=f"Helper removed: {reason}")
                        logger.info(f"Removed role {role.name} from {discord_user}")
                except Exception as e:
                    logger.warning(f"Could not remove role from user: {e}")

            msg = f"✅ **Helper access removed**\n\n"
            msg += f"**User:** {discord_user.mention}\n"
            msg += f"**Role:** {helper.discord_role_name}\n"
            msg += f"**Reason:** {reason}"

            await interaction.followup.send(msg, ephemeral=True)
            await log_to_ops_channel(
                self.bot,
                f"**Helper Removed**\n{interaction.user.mention} removed helper access for {discord_user.mention}\n**Reason:** {reason}",
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
            def get_helper_status():  # type: ignore[no-untyped-def]
                try:
                    person = Person.objects.get(discord_id=discord_user.id)
                except Person.DoesNotExist:
                    return None, None, "User not found in database", False, False

                # Get all helper assignments for this person
                helpers = list(StudentHelper.objects.filter(person=person).order_by("-created_at"))

                # Check if user has required groups
                has_support_group = person.has_group("WCComps_Ticketing_Support")
                has_injects_group = person.has_group("WCComps_Quotient_Injects")

                return person, helpers, None, has_support_group, has_injects_group

            person, helpers, error, has_support_group, has_injects_group = await get_helper_status()
            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"Helper Status - {discord_user.display_name}",
                description=f"**Authentik Username:** {person.authentik_username}\n**Discord ID:** {person.discord_id}",
                color=discord.Color.green() if (has_support_group or has_injects_group) else discord.Color.red(),
            )

            # Add permission status
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

            if not helpers:
                embed.add_field(name="Helper Assignments", value="No helper assignments found", inline=False)
            else:
                for helper in helpers[:10]:  # Limit to 10 most recent
                    status_emoji = {
                        "active": "✅",
                        "removed": "⏹️",
                    }.get(helper.status, "❓")

                    field_value = (
                        f"**Status:** {status_emoji} {helper.get_status_display()}\n"
                        f"**Role:** {helper.discord_role_name}\n"
                    )

                    if helper.status == "active" and helper.activated_at:
                        field_value += f"**Activated:** {helper.activated_at.strftime('%Y-%m-%d %H:%M')}\n"
                    elif helper.status == "removed":
                        if helper.deactivated_at:
                            field_value += f"**Removed:** {helper.deactivated_at.strftime('%Y-%m-%d %H:%M')}\n"
                        if helper.removal_reason:
                            field_value += f"**Reason:** {helper.removal_reason[:100]}\n"

                    embed.add_field(name=f"Assignment #{helper.id}", value=field_value, inline=False)

                if len(helpers) > 10:
                    embed.set_footer(text=f"Showing 10 of {len(helpers)} assignments")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.exception(f"Error checking helper status: {e}")
            await interaction.followup.send(f"❌ Error checking status: {e}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Setup function called by Discord.py when loading the cog."""
    await bot.add_cog(AdminHelpersCog(bot))
