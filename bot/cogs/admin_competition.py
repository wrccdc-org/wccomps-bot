"""Admin commands for competition and account management."""

import csv
import io
import logging
import re
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from django.conf import settings
from django.utils import timezone

from bot.authentik_utils import (
    generate_blueteam_password,
    parse_team_range,
    reset_blueteam_password,
    toggle_all_blueteam_accounts,
)
from bot.permissions import check_admin
from bot.utils import log_to_ops_channel
from core.models import AuditLog, CompetitionConfig
from team.models import DiscordLink, Team

logger = logging.getLogger(__name__)


class AdminCompetitionCog(commands.Cog):
    """Admin commands for competition and account management."""

    # Create competition command group as class attribute
    competition_group = app_commands.Group(
        name="competition",
        description="Competition management commands",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @competition_group.command(name="end-competition", description="[ADMIN] End competition and cleanup")
    @app_commands.check(check_admin)
    async def admin_end_competition(self, interaction: discord.Interaction) -> None:
        """End competition: clear channels, remove roles, deactivate links."""

        logger.info(f"admin_end_competition: Function called by {interaction.user.id}")

        await interaction.response.send_message(
            "Starting competition cleanup... This runs in background. Check ops channel for progress.",
            ephemeral=True,
        )

        logger.info(f"admin_end_competition: Sent initial response to {interaction.user.id}")

        async def cleanup() -> None:
            try:
                await log_to_ops_channel(
                    self.bot,
                    f"Competition Cleanup Started by {interaction.user.mention}",
                )

                # Deactivate team member links only (preserve admin/support links)
                # Get all links to deactivate
                links_to_deactivate = [
                    link
                    async for link in DiscordLink.objects.filter(is_active=True, team__isnull=False).select_related(
                        "team"
                    )
                ]

                # Deactivate each link individually and create audit log
                deactivated = 0
                for link in links_to_deactivate:
                    link.is_active = False
                    link.unlinked_at = timezone.now()
                    await link.asave()
                    deactivated += 1

                    # Create audit log for each unlink
                    await AuditLog.objects.acreate(
                        action="user_unlinked",
                        admin_user=str(interaction.user),
                        target_entity="discord_link",
                        target_id=link.discord_id,
                        details={
                            "discord_id": link.discord_id,
                            "team_name": link.team.team_name if link.team else "Unknown",
                            "authentik_username": link.authentik_username,
                            "reason": "competition_ended",
                        },
                    )

                await log_to_ops_channel(self.bot, f"Deactivated {deactivated} team member links")

                # Delete ALL team categories/channels (including Team 01)
                guild = interaction.guild
                if not guild:
                    await interaction.followup.send("Error: Guild not found", ephemeral=True)
                    return

                deleted_count = 0

                for category in guild.categories:
                    match = re.match(r"^team\s*(\d+)$", category.name, re.IGNORECASE)
                    if match:
                        try:
                            for channel in category.channels:
                                await channel.delete(reason="Competition ended")
                            await category.delete(reason="Competition ended")
                            deleted_count += 1
                            logger.info(f"Deleted {category.name}")
                        except Exception as e:
                            logger.exception(f"Failed to delete {category.name}: {e}")

                await log_to_ops_channel(self.bot, f"Deleted {deleted_count} team categories")

                from bot.discord_manager import DiscordManager

                discord_manager = DiscordManager(guild, self.bot)
                removed_count = await discord_manager.remove_all_team_roles()
                await log_to_ops_channel(self.bot, f"Removed roles from {removed_count} members")

                await Team.objects.all().aupdate(discord_category_id=None, discord_role_id=None)

                # Clear competition config to prevent auto-start/end on restart
                config = await CompetitionConfig.objects.afirst()
                if config:
                    config.competition_start_time = None
                    config.competition_end_time = None
                    config.applications_enabled = False
                    await config.asave()

                # Disable all team accounts in Authentik
                if settings.AUTHENTIK_TOKEN:
                    disabled_count, failed_count = await toggle_all_blueteam_accounts(is_active=False)
                    msg = f"Disabled {disabled_count} team accounts"
                    if failed_count > 0:
                        msg += f" ({failed_count} failed)"
                    await log_to_ops_channel(self.bot, msg)
                else:
                    disabled_count = 0
                    failed_count = 0

                await AuditLog.objects.acreate(
                    action="competition_ended",
                    admin_user=str(interaction.user),
                    target_entity="competition",
                    target_id=0,
                    details={
                        "deleted_categories": deleted_count,
                        "removed_roles": removed_count,
                        "disabled_accounts": disabled_count,
                        "failed_disables": failed_count,
                    },
                )

                await log_to_ops_channel(
                    self.bot,
                    f"Competition Cleanup Complete\n"
                    f"• Deleted {deleted_count} team categories\n"
                    f"• Removed {removed_count} role assignments\n"
                    f"• Disabled {disabled_count} team accounts",
                )
            except Exception as e:
                logger.exception(f"Cleanup error: {e}")
                await log_to_ops_channel(self.bot, f"Cleanup Error: {e}")

        self.bot.loop.create_task(cleanup())

    @competition_group.command(
        name="reset-blueteam-passwords",
        description="[ADMIN] Reset passwords for blueteam accounts (optionally specify teams)",
    )
    @app_commands.check(check_admin)
    async def admin_reset_blueteam_passwords(
        self, interaction: discord.Interaction, team_numbers: str | None = None
    ) -> None:
        """Reset passwords for blueteam accounts and export CSV.

        Args:
            team_numbers: Optional comma-separated team numbers or ranges (e.g., "1,3,5-10")
                         If not provided, resets all 50 teams.
        """

        if not settings.AUTHENTIK_TOKEN:
            await interaction.response.send_message("Error: AUTHENTIK_TOKEN not configured in settings", ephemeral=True)
            return

        # If resetting all 50 teams, require confirmation
        if not team_numbers:

            class PasswordResetConfirmView(discord.ui.View):
                def __init__(self) -> None:
                    super().__init__(timeout=60)
                    self.confirmed = False

                @discord.ui.button(
                    label="Confirm Reset All 50 Teams",
                    style=discord.ButtonStyle.danger,
                )
                async def confirm_button(
                    self,
                    button_interaction: discord.Interaction,
                    button: discord.ui.Button[Any],
                ) -> None:
                    self.confirmed = True
                    self.stop()
                    await button_interaction.response.defer()

                @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
                async def cancel_button(
                    self,
                    button_interaction: discord.Interaction,
                    button: discord.ui.Button[Any],
                ) -> None:
                    self.confirmed = False
                    self.stop()
                    await button_interaction.response.send_message("Password reset cancelled.", ephemeral=True)

            view = PasswordResetConfirmView()
            await interaction.response.send_message(
                "⚠️ **WARNING: You are about to reset passwords for ALL 50 blue team accounts.**\n\n"
                "This will:\n"
                "• Generate new random passwords for team01-team50\n"
                "• Invalidate all current passwords\n"
                "• Revoke active sessions\n\n"
                "Are you sure you want to continue?",
                view=view,
                ephemeral=True,
            )

            await view.wait()

            if not view.confirmed:
                return

            await interaction.followup.send("Resetting all 50 team passwords...", ephemeral=True)
        else:
            await interaction.response.defer(ephemeral=True)

        from asgiref.sync import sync_to_async

        # Parse team numbers if provided
        if team_numbers:
            try:
                teams = parse_team_range(team_numbers)
            except ValueError as e:
                await interaction.followup.send(f"Error: {e}", ephemeral=True)
                return
        else:
            teams = list(range(1, 51))  # All teams

        # Generate passwords for specified teams
        password_list = []
        for i in teams:
            username = f"team{i:02d}"
            password = generate_blueteam_password()
            password_list.append((i, username, password))

        # Reset passwords in Authentik
        failed_resets = []
        for team_num, username, password in password_list:
            success, error = await sync_to_async(reset_blueteam_password)(team_num, password)
            if not success:
                failed_resets.append((username, error))

        # Generate CSV in memory
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(["Username", "Password"])

        for _team_num, username, password in password_list:
            writer.writerow([username, password])

        csv_buffer.seek(0)

        # Create Discord file
        file = discord.File(
            fp=io.BytesIO(csv_buffer.getvalue().encode("utf-8")),
            filename="blueteam_passwords.csv",
        )

        team_count = len(password_list)

        # Create audit log
        await AuditLog.objects.acreate(
            action="blueteam_passwords_reset",
            admin_user=str(interaction.user),
            target_entity="authentik_users",
            target_id=0,
            details={
                "total_users": team_count,
                "failed_resets": len(failed_resets),
                "team_numbers": team_numbers or "all",
            },
        )

        # Log to ops
        teams_msg = f"teams {team_numbers}" if team_numbers else "all 50 accounts"
        await log_to_ops_channel(
            self.bot,
            f"BlueTeam Password Reset by {interaction.user.mention}\n"
            f"• Teams: {teams_msg}\n"
            f"• Total: {team_count} accounts\n"
            f"• Failed: {len(failed_resets)}",
        )

        success_count = team_count - len(failed_resets)
        result_msg = f"Password reset complete\n• Success: {success_count}/{team_count}\n"
        if failed_resets:
            result_msg += f"• Failed: {len(failed_resets)}/{team_count}\n"
        result_msg += "\nCSV file attached with all credentials."

        await interaction.followup.send(
            result_msg,
            file=file,
            ephemeral=True,
        )

        logger.info(f"Password reset performed by {interaction.user}. Failed: {len(failed_resets)}")

    @competition_group.command(
        name="toggle-blueteams",
        description="[ADMIN] Enable or disable all blue team accounts (team01-team50)",
    )
    @app_commands.describe(action="Enable or disable accounts")
    @app_commands.choices(
        action=[
            app_commands.Choice(name="Enable", value="enable"),
            app_commands.Choice(name="Disable", value="disable"),
        ]
    )
    @app_commands.check(check_admin)
    async def admin_toggle_blueteams(self, interaction: discord.Interaction, action: app_commands.Choice[str]) -> None:
        """Enable or disable all blue team accounts in Authentik."""
        if not settings.AUTHENTIK_TOKEN:
            await interaction.response.send_message("Error: AUTHENTIK_TOKEN not configured in settings", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        is_active = action.value == "enable"
        action_past = "enabled" if is_active else "disabled"
        action_capitalized = "Enabled" if is_active else "Disabled"

        # Toggle team01-team50
        success_count, failed_count = await toggle_all_blueteam_accounts(is_active)

        # Create audit log
        await AuditLog.objects.acreate(
            action=f"blueteam_accounts_{action_past}",
            admin_user=str(interaction.user),
            target_entity="authentik_users",
            target_id=0,
            details={
                "total_users": 50,
                "failed_toggles": failed_count,
            },
        )

        # Log to ops channel
        ops_msg = (
            f"BlueTeam Accounts {action_capitalized} by {interaction.user.mention}\n"
            f"• Total: 50 accounts\n"
            f"• Success: {success_count}"
        )
        if failed_count > 0:
            ops_msg += f"\n• Failed: {failed_count}"
        await log_to_ops_channel(self.bot, ops_msg)

        # Send response
        message = f"✅ {action_capitalized} {success_count}/50 blue team accounts"
        if failed_count > 0:
            message += f"\n❌ Failed: {failed_count}/50\n\nCheck logs for error details."

        await interaction.followup.send(message, ephemeral=True)

        logger.info(f"Blue team accounts {action_past} by {interaction.user}. Failed: {failed_count}")

    @competition_group.command(name="set-max-members", description="[ADMIN] Set maximum team members globally")
    @app_commands.describe(max_members="Maximum members per team (1-20)")
    @app_commands.check(check_admin)
    async def admin_set_max_members(self, interaction: discord.Interaction, max_members: int) -> None:
        """Set global maximum team members."""
        if max_members < 1 or max_members > 20:
            await interaction.response.send_message("Maximum members must be between 1 and 20.", ephemeral=True)
            return

        config = await CompetitionConfig.objects.afirst() or await CompetitionConfig.objects.acreate()
        old_max = config.max_team_members
        config.max_team_members = max_members
        await config.asave()

        # Update all existing team records to match the new global max
        await Team.objects.aupdate(max_members=max_members)

        # Create audit log
        await AuditLog.objects.acreate(
            action="max_team_members_updated",
            admin_user=str(interaction.user),
            target_entity="competition_config",
            target_id=config.pk,
            details={
                "old_max": old_max,
                "new_max": max_members,
            },
        )

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Max Team Members Updated by {interaction.user.mention}\n• Old: {old_max}\n• New: {max_members}",
        )

        await interaction.response.send_message(
            f"Maximum team members set to {max_members} (was {old_max}).",
            ephemeral=True,
        )

    @competition_group.command(
        name="set-start-time",
        description="[ADMIN] Set competition start time (applications will be enabled automatically)",
    )
    @app_commands.describe(
        datetime_str="Start time in format: YYYY-MM-DD HH:MM (e.g., 2025-01-15 09:00)",
        timezone_name="Timezone (defaults to Pacific Time)",
    )
    @app_commands.choices(
        timezone_name=[
            app_commands.Choice(name="Pacific Time (PT)", value="America/Los_Angeles"),
            app_commands.Choice(name="Mountain Time (MT)", value="America/Denver"),
            app_commands.Choice(name="Central Time (CT)", value="America/Chicago"),
            app_commands.Choice(name="Eastern Time (ET)", value="America/New_York"),
            app_commands.Choice(name="UTC", value="UTC"),
        ]
    )
    @app_commands.check(check_admin)
    async def admin_set_start_time(
        self,
        interaction: discord.Interaction,
        datetime_str: str,
        timezone_name: str = "America/Los_Angeles",
    ) -> None:
        """Set competition start time for automatic application enabling."""

        from datetime import datetime
        from zoneinfo import ZoneInfo

        try:
            # Parse and validate format
            dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")

            # Construct timezone-aware datetime from parsed components
            local_time = datetime(
                dt.year,
                dt.month,
                dt.day,
                dt.hour,
                dt.minute,
                tzinfo=ZoneInfo(timezone_name),
            )

            # Convert to UTC for storage
            start_time = local_time.astimezone(ZoneInfo("UTC"))

        except ValueError:
            await interaction.response.send_message(
                "Invalid datetime format. Use: YYYY-MM-DD HH:MM (e.g., 2025-01-15 09:00)",
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.response.send_message(
                f"Error parsing timezone: {e}",
                ephemeral=True,
            )
            return

        # Get or create config
        config = await CompetitionConfig.objects.afirst() or await CompetitionConfig.objects.acreate()

        # Set default controlled applications if not already set
        if not config.controlled_applications:
            config.controlled_applications = ["netbird", "scoring"]

        config.competition_start_time = start_time
        config.applications_enabled = False  # Reset to disabled
        await config.asave()

        # Create audit log
        await AuditLog.objects.acreate(
            action="competition_start_time_set",
            admin_user=str(interaction.user),
            target_entity="competition_config",
            target_id=config.pk,
            details={
                "start_time": start_time.isoformat(),
                "controlled_apps": config.controlled_applications,
            },
        )

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Competition Start Time Set by {interaction.user.mention}\n"
            f"• Start Time: {discord.utils.format_dt(start_time, style='F')}\n"
            f"• Controlled Apps: {', '.join(config.controlled_applications)}\n"
            f"• Applications will be enabled automatically at start time",
        )

        await interaction.response.send_message(
            f"Competition start time set to: {discord.utils.format_dt(start_time, style='F')}\n"
            f"Controlled applications: {', '.join(config.controlled_applications)}\n\n"
            f"Applications will be automatically enabled at start time.",
            ephemeral=True,
        )

    @competition_group.command(
        name="set-end-time",
        description="[ADMIN] Set competition end time (applications will be disabled automatically)",
    )
    @app_commands.describe(
        datetime_str="End time in format: YYYY-MM-DD HH:MM (e.g., 2025-01-15 17:00)",
        timezone_name="Timezone (defaults to Pacific Time)",
    )
    @app_commands.choices(
        timezone_name=[
            app_commands.Choice(name="Pacific Time (PT)", value="America/Los_Angeles"),
            app_commands.Choice(name="Mountain Time (MT)", value="America/Denver"),
            app_commands.Choice(name="Central Time (CT)", value="America/Chicago"),
            app_commands.Choice(name="Eastern Time (ET)", value="America/New_York"),
            app_commands.Choice(name="UTC", value="UTC"),
        ]
    )
    @app_commands.check(check_admin)
    async def admin_set_end_time(
        self,
        interaction: discord.Interaction,
        datetime_str: str,
        timezone_name: str = "America/Los_Angeles",
    ) -> None:
        """Set competition end time for automatic application disabling."""

        from datetime import datetime
        from zoneinfo import ZoneInfo

        try:
            # Parse and validate format
            dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")

            # Construct timezone-aware datetime from parsed components
            local_time = datetime(
                dt.year,
                dt.month,
                dt.day,
                dt.hour,
                dt.minute,
                tzinfo=ZoneInfo(timezone_name),
            )

            # Convert to UTC for storage
            end_time = local_time.astimezone(ZoneInfo("UTC"))

        except ValueError:
            await interaction.response.send_message(
                "Invalid datetime format. Use: YYYY-MM-DD HH:MM (e.g., 2025-01-15 17:00)",
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.response.send_message(
                f"Error parsing timezone: {e}",
                ephemeral=True,
            )
            return

        # Get or create config
        config = await CompetitionConfig.objects.afirst() or await CompetitionConfig.objects.acreate()

        # Set default controlled applications if not already set
        if not config.controlled_applications:
            config.controlled_applications = ["netbird", "scoring"]

        config.competition_end_time = end_time
        await config.asave()

        # Create audit log
        await AuditLog.objects.acreate(
            action="competition_end_time_set",
            admin_user=str(interaction.user),
            target_entity="competition_config",
            target_id=config.pk,
            details={
                "end_time": end_time.isoformat(),
                "controlled_apps": config.controlled_applications,
            },
        )

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Competition End Time Set by {interaction.user.mention}\n"
            f"• End Time: {discord.utils.format_dt(end_time, style='F')}\n"
            f"• Controlled Apps: {', '.join(config.controlled_applications)}\n"
            f"• Applications will be disabled automatically at end time",
        )

        await interaction.response.send_message(
            f"Competition end time set to: {discord.utils.format_dt(end_time, style='F')}\n"
            f"Controlled applications: {', '.join(config.controlled_applications)}\n\n"
            f"Applications will be automatically disabled at end time.",
            ephemeral=True,
        )

    @competition_group.command(
        name="start-competition",
        description="[ADMIN] Start the competition (enable applications and accounts)",
    )
    @app_commands.check(check_admin)
    async def admin_start_competition(self, interaction: discord.Interaction) -> None:
        """Start the competition by enabling applications and Authentik accounts."""

        await interaction.response.defer(ephemeral=True)

        config = await CompetitionConfig.objects.afirst() or await CompetitionConfig.objects.acreate()

        if not config.controlled_applications:
            await interaction.followup.send(
                "No controlled applications configured. Use `/competition set-apps` first.",
                ephemeral=True,
            )
            return

        from bot.authentik_manager import AuthentikManager

        auth_manager = AuthentikManager()

        # Enable applications
        app_results = auth_manager.enable_applications(config.controlled_applications)

        # Enable all blueteam accounts
        enabled_count, failed_count = await toggle_all_blueteam_accounts(is_active=True)

        # Update config and clear scheduled times (manual start)
        config.applications_enabled = True
        config.competition_start_time = None
        config.competition_end_time = None
        await config.asave()

        # Build result message with detailed errors
        success_apps = [app for app, (success, _) in app_results.items() if success]
        failed_apps = [(app, error) for app, (success, error) in app_results.items() if not success]

        # Create audit log with detailed results
        await AuditLog.objects.acreate(
            action="competition_started",
            admin_user=str(interaction.user),
            target_entity="competition_config",
            target_id=config.pk,
            details={
                "controlled_apps": config.controlled_applications,
                "apps_success_count": len(success_apps),
                "apps_failed_count": len(failed_apps),
                "accounts_enabled": enabled_count,
                "accounts_failed": failed_count,
                "errors": dict(failed_apps),
            },
        )

        result_msg = "**Competition Started!**\n\n"
        result_msg += f"Applications enabled: {len(success_apps)}/{len(config.controlled_applications)}\n"
        if success_apps:
            result_msg += f"✓ Enabled: {', '.join(success_apps)}\n"
        if failed_apps:
            result_msg += "\n✗ **Failed Applications:**\n"
            for app, error in failed_apps:
                result_msg += f"  • {app}: {error}\n"

        result_msg += f"\nAccounts enabled: {enabled_count}"
        if failed_count > 0:
            result_msg += f" ({failed_count} failed)"

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Competition Started by {interaction.user.mention}\n{result_msg}",
        )

        await interaction.followup.send(result_msg, ephemeral=True)

    @competition_group.command(
        name="set-apps",
        description="[ADMIN] Set which Authentik applications to control",
    )
    @app_commands.describe(app_slugs="Comma-separated list of application slugs (e.g., netbird,scoring)")
    @app_commands.check(check_admin)
    async def admin_competition_set_apps(self, interaction: discord.Interaction, app_slugs: str) -> None:
        """Set which applications to control."""

        # Parse slugs
        slugs = [s.strip() for s in app_slugs.split(",") if s.strip()]

        if not slugs:
            await interaction.response.send_message("Please provide at least one application slug.", ephemeral=True)
            return

        config = await CompetitionConfig.objects.afirst() or await CompetitionConfig.objects.acreate()
        config.controlled_applications = slugs
        await config.asave()

        # Create audit log
        await AuditLog.objects.acreate(
            action="competition_apps_configured",
            admin_user=str(interaction.user),
            target_entity="competition_config",
            target_id=config.pk,
            details={
                "controlled_apps": slugs,
            },
        )

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Competition Applications Configured by {interaction.user.mention}\n• Applications: {', '.join(slugs)}",
        )

        await interaction.response.send_message(f"Controlled applications set to: {', '.join(slugs)}", ephemeral=True)

    @competition_group.command(
        name="broadcast",
        description="[ADMIN] Broadcast a message to announcement channel or team channels",
    )
    @app_commands.describe(
        target="Where to broadcast: 'announcements', 'all-teams', or specific teams (e.g., '1,3,5-10')",
        message="Message to broadcast",
    )
    @app_commands.check(check_admin)
    async def admin_broadcast(self, interaction: discord.Interaction, target: str, message: str) -> None:
        """Broadcast a message to announcement channel or team channels."""

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if not guild:
            await interaction.followup.send("This command must be used in a guild", ephemeral=True)
            return

        target_lower = target.lower().strip()
        sent_count = 0
        failed_channels = []

        # Determine broadcast target
        if target_lower == "announcements":
            # Broadcast to announcements channel with @Blueteam mention
            announcement_channel_id = settings.DISCORD_ANNOUNCEMENT_CHANNEL_ID
            channel = guild.get_channel(announcement_channel_id)

            if not channel or not isinstance(channel, discord.TextChannel):
                await interaction.followup.send(
                    f"Announcements channel not found (ID: {announcement_channel_id})",
                    ephemeral=True,
                )
                return

            # Get Blueteam role
            blueteam_role = guild.get_role(settings.BLUETEAM_ROLE_ID)
            role_mention = blueteam_role.mention if blueteam_role else "@Blueteam"

            try:
                await channel.send(f"{role_mention}\n\n{message}")
                sent_count = 1

                # Log to ops
                await log_to_ops_channel(
                    self.bot,
                    f"Broadcast to Announcements by {interaction.user.mention}\nMessage: {message[:100]}...",
                )

                await interaction.followup.send("Broadcast sent to announcements channel", ephemeral=True)
            except Exception as e:
                logger.exception(f"Failed to broadcast to announcements: {e}")
                await interaction.followup.send(f"Failed to send broadcast: {e}", ephemeral=True)
            return

        if target_lower == "all-teams":
            # Broadcast to all team chat channels
            teams = [t async for t in Team.objects.filter(is_active=True).order_by("team_number")]
            team_numbers = [t.team_number for t in teams]

        else:
            # Parse specific team range
            try:
                team_numbers = parse_team_range(target)
            except ValueError as e:
                await interaction.followup.send(
                    f"Invalid team range format: {e}\n\n"
                    f"Examples:\n"
                    f"• Single teams: `1,3,5`\n"
                    f"• Range: `1-10`\n"
                    f"• Mixed: `1,3,5-10,15`\n"
                    f"• All teams: `all-teams`\n"
                    f"• Announcements: `announcements`",
                    ephemeral=True,
                )
                return

        # Send to team channels
        for team_number in team_numbers:
            try:
                team = await Team.objects.filter(team_number=team_number).afirst()
                if not team:
                    failed_channels.append(f"Team {team_number:02d} (not found)")
                    continue

                # Find team chat channel
                if not team.discord_category_id:
                    failed_channels.append(f"Team {team_number:02d} (no category)")
                    continue

                category = guild.get_channel(team.discord_category_id)
                if not category or not isinstance(category, discord.CategoryChannel):
                    failed_channels.append(f"Team {team_number:02d} (category not found)")
                    continue

                # Find chat channel in category
                chat_channel = None
                for channel in category.channels:
                    if isinstance(channel, discord.TextChannel) and "chat" in channel.name.lower():
                        chat_channel = channel
                        break

                if not chat_channel:
                    failed_channels.append(f"Team {team_number:02d} (chat channel not found)")
                    continue

                # Send message
                await chat_channel.send(f"**Announcement from {interaction.user.name}:**\n\n{message}")
                sent_count += 1

            except Exception as e:
                logger.exception(f"Failed to broadcast to team {team_number}: {e}")
                failed_channels.append(f"Team {team_number:02d} ({str(e)[:50]})")
                continue

        # Create audit log
        await AuditLog.objects.acreate(
            action="broadcast_message",
            admin_user=str(interaction.user),
            target_entity="broadcast",
            target_id=0,
            details={
                "target": target,
                "message_preview": message[:200],
                "sent_count": sent_count,
                "failed_count": len(failed_channels),
            },
        )

        # Log to ops
        ops_msg_parts = [
            f"Broadcast by {interaction.user.mention}",
            f"• Target: {target}",
            f"• Sent: {sent_count} channels",
        ]
        if failed_channels:
            ops_msg_parts.append(f"• Failed: {len(failed_channels)}")
        ops_msg_parts.append(f"Message: {message[:100]}...")

        await log_to_ops_channel(self.bot, "\n".join(ops_msg_parts))

        # Build response
        result_msg = f"Broadcast complete\n• Sent: {sent_count} channels"
        if failed_channels:
            result_msg += f"\n• Failed: {len(failed_channels)}"
            if len(failed_channels) <= 10:
                result_msg += "\n\nFailed channels:\n" + "\n".join([f"• {fc}" for fc in failed_channels])
            else:
                result_msg += "\n\nFailed channels (first 10):\n" + "\n".join(
                    [f"• {fc}" for fc in failed_channels[:10]]
                )

        await interaction.followup.send(result_msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Setup function to add cog to bot."""
    await bot.add_cog(AdminCompetitionCog(bot))
