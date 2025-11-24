"""Admin commands for managing student helpers."""

import logging
from datetime import datetime
from typing import Literal

import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from bot.permissions import check_admin, check_gold_team
from bot.utils import log_to_ops_channel
from competition.models import Competition, StudentHelper
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

    @helpers_group.command(name="add", description="[ADMIN] Add student helper to a competition")
    @app_commands.check(check_admin)
    @app_commands.describe(
        discord_user="Discord user to add as helper",
        competition_slug="Competition slug (e.g., 'swccdc-2025')",
        role_name="Discord role name (e.g., 'UCI Invitationals 2026')",
        custom_start="Optional: Custom start time (YYYY-MM-DD HH:MM)",
        custom_end="Optional: Custom end time (YYYY-MM-DD HH:MM)",
    )
    async def add_helper(
        self,
        interaction: discord.Interaction,
        discord_user: discord.Member,
        competition_slug: str,
        role_name: str,
        custom_start: str | None = None,
        custom_end: str | None = None,
    ) -> None:
        """Add a student helper to a competition."""
        await interaction.response.defer(ephemeral=True)

        try:
            # Get Person for this Discord user
            @sync_to_async
            def get_person_and_competition():  # type: ignore[no-untyped-def]
                try:
                    person = Person.objects.get(discord_id=discord_user.id)
                except Person.DoesNotExist:
                    return None, None, "User must link their Discord account first with `/link`"

                # Check if user has WCComps_Ticketing_Support
                if not person.has_group("WCComps_Ticketing_Support"):
                    return (
                        None,
                        None,
                        "User must have WCComps_Ticketing_Support group in Authentik first",
                    )

                try:
                    competition = Competition.objects.get(slug=competition_slug)
                except Competition.DoesNotExist:
                    return None, None, f"Competition '{competition_slug}' not found"

                # Check if helper already exists
                existing = StudentHelper.objects.filter(
                    person=person, competition=competition, status__in=["pending", "active"]
                ).first()
                if existing:
                    return None, None, f"Helper assignment already exists (status: {existing.get_status_display()})"

                return person, competition, None

            person, competition, error = await get_person_and_competition()
            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            # Parse custom times if provided
            custom_start_time = None
            custom_end_time = None
            if custom_start:
                try:
                    custom_start_time = datetime.strptime(custom_start, "%Y-%m-%d %H:%M")
                    custom_start_time = timezone.make_aware(custom_start_time)
                except ValueError:
                    await interaction.followup.send(
                        "❌ Invalid start time format. Use YYYY-MM-DD HH:MM", ephemeral=True
                    )
                    return

            if custom_end:
                try:
                    custom_end_time = datetime.strptime(custom_end, "%Y-%m-%d %H:%M")
                    custom_end_time = timezone.make_aware(custom_end_time)
                except ValueError:
                    await interaction.followup.send("❌ Invalid end time format. Use YYYY-MM-DD HH:MM", ephemeral=True)
                    return

            # Create helper assignment
            @sync_to_async
            def create_helper():  # type: ignore[no-untyped-def]
                django_user = User.objects.filter(person=person).first()
                helper = StudentHelper.objects.create(
                    competition=competition,
                    person=person,
                    discord_id=person.discord_id,
                    discord_username=person.discord_username,
                    authentik_username=person.authentik_username,
                    discord_role_name=role_name,
                    custom_start_time=custom_start_time,
                    custom_end_time=custom_end_time,
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
                        "competition": competition.name,
                        "role_name": role_name,
                        "start_time": str(helper.get_start_time()),  # type: ignore[no-untyped-call]
                        "end_time": str(helper.get_end_time()),  # type: ignore[no-untyped-call]
                    },
                )

                return helper

            helper = await create_helper()

            # Build response message
            msg = f"✅ **Student helper added successfully!**\n\n"
            msg += f"**Helper:** {discord_user.mention} ({helper.authentik_username})\n"
            msg += f"**Competition:** {competition.name}\n"
            msg += f"**Role:** {role_name}\n"
            msg += f"**Start:** {helper.get_start_time().strftime('%Y-%m-%d %H:%M %Z')}\n"
            msg += f"**End:** {helper.get_end_time().strftime('%Y-%m-%d %H:%M %Z')}\n"
            msg += f"**Status:** {helper.get_status_display()}\n\n"
            msg += "The helper role will be automatically assigned at the start time."

            await interaction.followup.send(msg, ephemeral=True)
            await log_to_ops_channel(
                self.bot,
                f"**Student Helper Added**\n{interaction.user.mention} added {discord_user.mention} as helper for {competition.name}",
            )

        except Exception as e:
            logger.exception(f"Error adding student helper: {e}")
            await interaction.followup.send(f"❌ Error adding helper: {e}", ephemeral=True)

    @helpers_group.command(name="list", description="[ADMIN] List student helpers for a competition")
    @app_commands.check(check_gold_team)
    @app_commands.describe(
        competition_slug="Competition slug (e.g., 'swccdc-2025')",
        status="Filter by status (optional)",
    )
    async def list_helpers(
        self,
        interaction: discord.Interaction,
        competition_slug: str,
        status: Literal["pending", "active", "expired", "revoked", "all"] = "all",
    ) -> None:
        """List student helpers for a competition."""
        await interaction.response.defer(ephemeral=True)

        try:

            @sync_to_async
            def get_helpers():  # type: ignore[no-untyped-def]
                try:
                    competition = Competition.objects.get(slug=competition_slug)
                except Competition.DoesNotExist:
                    return None, f"Competition '{competition_slug}' not found"

                query = StudentHelper.objects.filter(competition=competition).select_related("person", "competition")

                if status != "all":
                    query = query.filter(status=status)

                helpers = list(query.order_by("-created_at"))
                return helpers, None

            helpers, error = await get_helpers()
            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            if not helpers:
                await interaction.followup.send(
                    f"No helpers found for competition '{competition_slug}'" + (f" with status '{status}'" if status != "all" else ""),
                    ephemeral=True,
                )
                return

            # Build response with embed
            competition_obj = helpers[0].competition
            embed = discord.Embed(
                title=f"Student Helpers - {competition_obj.name}",
                description=f"Found {len(helpers)} helper(s)" + (f" with status '{status}'" if status != "all" else ""),
                color=discord.Color.blue(),
            )

            for helper in helpers[:25]:  # Discord embed field limit
                status_emoji = {
                    "pending": "⏳",
                    "active": "✅",
                    "expired": "⏹️",
                    "revoked": "❌",
                }.get(helper.status, "❓")

                field_name = f"{status_emoji} {helper.discord_username}"
                field_value = (
                    f"**Role:** {helper.discord_role_name}\n"
                    f"**Status:** {helper.get_status_display()}\n"
                    f"**Period:** {helper.get_start_time().strftime('%m/%d %H:%M')} - {helper.get_end_time().strftime('%m/%d %H:%M')}\n"
                )

                if helper.status == "active":
                    field_value += f"**Activated:** {helper.activated_at.strftime('%m/%d %H:%M') if helper.activated_at else 'N/A'}\n"
                elif helper.status == "revoked":
                    field_value += f"**Revoked:** {helper.revoke_reason or 'No reason provided'}\n"

                embed.add_field(name=field_name, value=field_value, inline=False)

            if len(helpers) > 25:
                embed.set_footer(text=f"Showing first 25 of {len(helpers)} helpers")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.exception(f"Error listing student helpers: {e}")
            await interaction.followup.send(f"❌ Error listing helpers: {e}", ephemeral=True)

    @helpers_group.command(name="revoke", description="[ADMIN] Revoke student helper access")
    @app_commands.check(check_admin)
    @app_commands.describe(
        discord_user="Discord user to revoke helper access from",
        competition_slug="Competition slug (e.g., 'swccdc-2025')",
        reason="Reason for revocation",
    )
    async def revoke_helper(
        self,
        interaction: discord.Interaction,
        discord_user: discord.Member,
        competition_slug: str,
        reason: str = "Manually revoked by admin",
    ) -> None:
        """Revoke a student helper's access before expiration."""
        await interaction.response.defer(ephemeral=True)

        try:

            @sync_to_async
            def revoke_helper_db():  # type: ignore[no-untyped-def]
                try:
                    person = Person.objects.get(discord_id=discord_user.id)
                except Person.DoesNotExist:
                    return None, "User not found in database"

                try:
                    competition = Competition.objects.get(slug=competition_slug)
                except Competition.DoesNotExist:
                    return None, f"Competition '{competition_slug}' not found"

                try:
                    helper = StudentHelper.objects.get(
                        person=person, competition=competition, status__in=["pending", "active"]
                    )
                except StudentHelper.DoesNotExist:
                    return None, "No active helper assignment found for this user and competition"

                # Get Django user for audit
                django_user = User.objects.filter(person__discord_id=interaction.user.id).first()

                # Revoke in database - only if we have a valid user
                if django_user:
                    helper.revoke(django_user, reason)
                else:
                    # Fallback: manually update status
                    helper.status = "revoked"
                    helper.revoke_reason = reason
                    helper.deactivated_at = timezone.now()
                    helper.save()

                # Create audit log
                AuditLog.objects.create(
                    action="helper_revoked",
                    admin_user=str(interaction.user),
                    target_entity="student_helper",
                    target_id=helper.id,
                    details={
                        "discord_id": helper.discord_id,
                        "discord_username": helper.discord_username,
                        "competition": competition.name,
                        "reason": reason,
                    },
                )

                return helper, None

            helper, error = await revoke_helper_db()
            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            # Remove Discord role if currently assigned
            if helper.discord_role_id and interaction.guild:
                try:
                    guild = interaction.guild
                    role = guild.get_role(helper.discord_role_id)
                    if role and role in discord_user.roles:
                        await discord_user.remove_roles(role, reason=f"Helper revoked: {reason}")
                        logger.info(f"Removed role {role.name} from {discord_user}")
                except Exception as e:
                    logger.warning(f"Could not remove role from user: {e}")

            msg = f"✅ **Helper access revoked**\n\n"
            msg += f"**User:** {discord_user.mention}\n"
            msg += f"**Competition:** {helper.competition.name}\n"
            msg += f"**Reason:** {reason}"

            await interaction.followup.send(msg, ephemeral=True)
            await log_to_ops_channel(
                self.bot,
                f"**Helper Revoked**\n{interaction.user.mention} revoked helper access for {discord_user.mention}\n**Reason:** {reason}",
            )

        except Exception as e:
            logger.exception(f"Error revoking student helper: {e}")
            await interaction.followup.send(f"❌ Error revoking helper: {e}", ephemeral=True)

    @helpers_group.command(name="status", description="[ADMIN] Check student helper status")
    @app_commands.check(check_gold_team)
    @app_commands.describe(discord_user="Discord user to check status for")
    async def helper_status(
        self,
        interaction: discord.Interaction,
        discord_user: discord.Member,
    ) -> None:
        """Check the status of a student helper across all competitions."""
        await interaction.response.defer(ephemeral=True)

        try:

            @sync_to_async
            def get_helper_status():  # type: ignore[no-untyped-def]
                try:
                    person = Person.objects.get(discord_id=discord_user.id)
                except Person.DoesNotExist:
                    return None, None, "User not found in database"

                # Get all helper assignments for this person
                helpers = list(
                    StudentHelper.objects.filter(person=person).select_related("competition").order_by("-created_at")
                )

                # Check if user has required group
                has_support_group = person.has_group("WCComps_Ticketing_Support")

                return person, helpers, None, has_support_group

            person, helpers, error, has_support_group = await get_helper_status()
            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"Helper Status - {discord_user.display_name}",
                description=f"**Authentik Username:** {person.authentik_username}\n**Discord ID:** {person.discord_id}",
                color=discord.Color.green() if has_support_group else discord.Color.red(),
            )

            # Add support group status
            embed.add_field(
                name="WCComps_Ticketing_Support",
                value="✅ Has permission" if has_support_group else "❌ Missing permission (required)",
                inline=False,
            )

            if not helpers:
                embed.add_field(name="Helper Assignments", value="No helper assignments found", inline=False)
            else:
                for helper in helpers[:10]:  # Limit to 10 most recent
                    status_emoji = {
                        "pending": "⏳",
                        "active": "✅",
                        "expired": "⏹️",
                        "revoked": "❌",
                    }.get(helper.status, "❓")

                    field_value = (
                        f"**Status:** {status_emoji} {helper.get_status_display()}\n"
                        f"**Role:** {helper.discord_role_name}\n"
                        f"**Period:** {helper.get_start_time().strftime('%Y-%m-%d %H:%M')} - {helper.get_end_time().strftime('%Y-%m-%d %H:%M')}\n"
                    )

                    if helper.status == "active" and helper.activated_at:
                        field_value += f"**Activated:** {helper.activated_at.strftime('%Y-%m-%d %H:%M')}\n"
                    elif helper.status == "revoked":
                        field_value += f"**Revoked:** {helper.revoke_reason or 'No reason'}\n"

                    embed.add_field(name=helper.competition.name, value=field_value, inline=False)

                if len(helpers) > 10:
                    embed.set_footer(text=f"Showing 10 of {len(helpers)} assignments")

            await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.exception(f"Error checking helper status: {e}")
            await interaction.followup.send(f"❌ Error checking status: {e}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Setup function called by Discord.py when loading the cog."""
    await bot.add_cog(AdminHelpersCog(bot))
