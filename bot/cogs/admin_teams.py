"""Admin commands for team management."""

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands
from django.utils import timezone

from bot.authentik_manager import AuthentikManager
from bot.authentik_utils import (
    generate_blueteam_password,
    parse_team_range,
    reset_blueteam_password,
)
from bot.permissions import check_admin
from bot.utils import (
    get_team_or_respond,
    log_to_ops_channel,
    remove_blueteam_role,
    safe_remove_role,
)
from core.models import AuditLog
from team.models import DiscordLink, Team

logger = logging.getLogger(__name__)


class AdminTeamsCog(commands.Cog):
    """Admin commands for team management."""

    # Create teams command group as class attribute
    teams_group = app_commands.Group(name="teams", description="Team management commands")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @teams_group.command(name="list", description="[ADMIN] List all teams with status")
    @app_commands.check(check_admin)
    async def admin_teams(self, interaction: discord.Interaction) -> None:
        """List all teams with member counts."""
        teams = [team async for team in Team.objects.all().order_by("team_number")]
        team_statuses = []

        for team in teams:
            member_count = await team.members.filter(is_active=True).acount()
            status = f"#{team.team_number:02d} {team.team_name}: {member_count}/{team.max_members} members"
            team_statuses.append(status)

        embed = discord.Embed(title="Team Status", color=discord.Color.blue())

        if len(team_statuses) <= 25:
            embed.add_field(
                name=f"All Teams ({len(team_statuses)})",
                value="\n".join(team_statuses),
                inline=False,
            )
        else:
            embed.description = f"{len(team_statuses)} teams total (use /teams info for details)"

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @teams_group.command(name="info", description="[ADMIN] Get detailed info about a specific team")
    @app_commands.describe(team_number="Team number (1-50)")
    @app_commands.check(check_admin)
    async def admin_team_info(self, interaction: discord.Interaction, team_number: int) -> None:
        """Get detailed information about a team."""
        team = await get_team_or_respond(interaction, team_number)
        if not team:
            return

        member_count = await team.members.filter(is_active=True).acount()
        # Fetch all members (select_related for authentik_username property)
        members = [m async for m in team.members.filter(is_active=True).select_related("user").order_by("linked_at")]

        embed = discord.Embed(title=f"{team.team_name} Details", color=discord.Color.blue())
        embed.add_field(name="Team Number", value=f"#{team.team_number}", inline=True)
        embed.add_field(name="Members", value=f"{member_count}/{team.max_members}", inline=True)
        embed.add_field(name="Authentik Group", value=team.authentik_group, inline=False)

        if members:
            # Build member list, respecting Discord's 1024 char field limit
            member_lines = [
                f"• {m.discord_username} (ID: {m.discord_id}) - via `{m.authentik_username}`" for m in members
            ]

            member_list = ""
            shown_count = 0
            for line in member_lines:
                test_list = member_list + line + "\n"
                # Leave room for "... and N more" message
                if len(test_list) > 950:
                    break
                member_list = test_list
                shown_count += 1

            # Add overflow message if needed
            if shown_count < len(members):
                remaining = len(members) - shown_count
                member_list += f"... and {remaining} more"

            embed.add_field(name="Team Members", value=member_list.strip(), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @teams_group.command(
        name="unlink",
        description="[ADMIN] Unlink one or more Discord users from their teams",
    )
    @app_commands.describe(users="User mention(s), ID(s), or space-separated list of multiple users")
    @app_commands.check(check_admin)
    async def admin_unlink(self, interaction: discord.Interaction, users: str) -> None:
        """Unlink one or more Discord users from their teams."""
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild:
            await interaction.followup.send("This command must be used in a guild", ephemeral=True)
            return

        # Parse user IDs from the input string (mentions or raw IDs)
        user_ids = []
        # Match Discord user mentions <@123456789> or <@!123456789> or raw IDs
        mention_pattern = r"<@!?(\d+)>|\b(\d{17,20})\b"
        matches = re.findall(mention_pattern, users)
        for match in matches:
            # match is a tuple of groups, get the non-empty one
            user_id = int(match[0] if match[0] else match[1])
            user_ids.append(user_id)

        if not user_ids:
            await interaction.followup.send(
                "No valid user mentions or IDs found. Please provide user mention(s) or ID(s).",
                ephemeral=True,
            )
            return

        # Remove duplicates
        user_ids = list(set(user_ids))

        results = []
        success_count = 0
        error_count = 0

        for user_id in user_ids:
            try:
                # Get member from guild
                member = interaction.guild.get_member(user_id)
                user_display = member.mention if member else f"User ID {user_id}"

                # Check if user is linked (select_related for authentik_username property)
                link = await (
                    DiscordLink.objects.filter(discord_id=user_id, is_active=True)
                    .select_related("team", "user")
                    .afirst()
                )

                if not link:
                    results.append(f"❌ {user_display}: Not linked to any team")
                    error_count += 1
                    continue

                team = link.team
                if not team:
                    results.append(f"❌ {user_display}: Link has no associated team")
                    error_count += 1
                    continue

                # Deactivate link
                link.is_active = False
                link.unlinked_at = timezone.now()
                await link.asave()

                # Remove roles if member is in server
                if member:
                    if team.discord_role_id:
                        role = interaction.guild.get_role(team.discord_role_id)
                        if role:
                            await safe_remove_role(
                                member,
                                role,
                                reason=f"Unlinked by {interaction.user}",
                            )

                    await remove_blueteam_role(
                        member,
                        interaction.guild,
                        reason=f"Unlinked by {interaction.user}",
                    )

                # Create audit log
                await AuditLog.objects.acreate(
                    action="user_unlinked",
                    admin_user=str(interaction.user),
                    target_entity="discord_link",
                    target_id=user_id,
                    details={
                        "discord_username": str(member) if member else f"ID:{user_id}",
                        "team_name": team.team_name,
                        "authentik_username": link.authentik_username,
                        "multiple_users": len(user_ids) > 1,
                    },
                )

                results.append(f"✓ {user_display}: Unlinked from **{team.team_name}**")
                success_count += 1

            except Exception as e:
                logger.exception(f"Error unlinking user {user_id}: {e}")
                results.append(f"❌ User ID {user_id}: Error - {str(e)[:50]}")
                error_count += 1

        # Build response message
        if len(user_ids) == 1:
            # Single user - use simple format
            await interaction.followup.send(results[0], ephemeral=True)
            if success_count > 0:
                await log_to_ops_channel(
                    self.bot,
                    f"User Unlinked: {results[0].split(':')[0].replace('✓ ', '')} by {interaction.user.mention}",
                )
        else:
            # Multiple users - use summary format
            summary = "**Unlink Results**\n\n"
            summary += f"✓ Successfully unlinked: {success_count}\n"
            if error_count > 0:
                summary += f"❌ Failed: {error_count}\n"
            summary += f"Total processed: {len(user_ids)}\n\n"

            # Show results (limit to first 20 to avoid message length issues)
            if len(results) <= 20:
                summary += "**Details:**\n" + "\n".join(results)
            else:
                summary += "**Details (first 20):**\n" + "\n".join(results[:20])
                summary += f"\n... and {len(results) - 20} more"

            await interaction.followup.send(summary, ephemeral=True)
            await log_to_ops_channel(
                self.bot,
                f"Bulk Unlink: {interaction.user.mention} unlinked {success_count} user(s) "
                f"(Processed: {len(user_ids)}, Failed: {error_count})",
            )

    @teams_group.command(
        name="remove",
        description="[ADMIN] Remove team infrastructure and unlink all members",
    )
    @app_commands.describe(team_number="Team number (1-50)")
    @app_commands.check(check_admin)
    async def admin_remove_team(self, interaction: discord.Interaction, team_number: int) -> None:
        """Remove a team's Discord infrastructure and unlink all members."""
        # Note: can't use get_team_or_respond here because we defer() before validation
        if team_number < 1 or team_number > 50:
            await interaction.response.send_message("Team number must be between 1 and 50", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        team = await Team.objects.filter(team_number=team_number).afirst()
        if not team:
            await interaction.followup.send(f"Team {team_number} not found", ephemeral=True)
            return

        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("This command must be used in a guild", ephemeral=True)
            return

        removed_items = []

        # Get all team members (select_related for authentik_username property)
        members = [m async for m in team.members.filter(is_active=True).select_related("user")]
        unlinked_count = 0

        # Remove roles BEFORE deactivating links
        for link in members:
            member = guild.get_member(link.discord_id)

            # Remove team role and Blueteam role if member is in server
            if member:
                roles_to_remove = []
                if team.discord_role_id:
                    role = guild.get_role(team.discord_role_id)
                    if role and role in member.roles:
                        roles_to_remove.append(role)

                if roles_to_remove:
                    for role in roles_to_remove:
                        await safe_remove_role(
                            member,
                            role,
                            reason=f"Team {team_number} removed by {interaction.user}",
                        )

                await remove_blueteam_role(
                    member,
                    guild,
                    reason=f"Team {team_number} removed by {interaction.user}",
                )

            # Deactivate link after roles removed
            link.is_active = False
            link.unlinked_at = timezone.now()
            await link.asave()
            unlinked_count += 1

            # Create individual audit log for each unlink
            await AuditLog.objects.acreate(
                action="user_unlinked",
                admin_user=str(interaction.user),
                target_entity="discord_link",
                target_id=link.discord_id,
                details={
                    "discord_username": str(member) if member else f"ID:{link.discord_id}",
                    "team_name": team.team_name,
                    "authentik_username": link.authentik_username,
                    "reason": "team_removed",
                },
            )

        # Delete category and all channels
        if team.discord_category_id:
            category = guild.get_channel(team.discord_category_id)
            if category and isinstance(category, discord.CategoryChannel):
                # Delete all channels in category first
                for channel in category.channels:
                    try:
                        await channel.delete(reason=f"Team {team_number} removed by {interaction.user}")
                    except Exception as e:
                        logger.exception(f"Failed to delete channel {channel.name}: {e}")

                # Delete category
                try:
                    await category.delete(reason=f"Team {team_number} removed by {interaction.user}")
                    removed_items.append("category")
                except Exception as e:
                    logger.exception(f"Failed to delete category: {e}")

        # Delete role
        if team.discord_role_id:
            role = guild.get_role(team.discord_role_id)
            if role:
                try:
                    await role.delete(reason=f"Team {team_number} removed by {interaction.user}")
                    removed_items.append("role")
                except Exception as e:
                    logger.exception(f"Failed to delete role: {e}")

        # Clear Discord IDs from database
        team.discord_role_id = None
        team.discord_category_id = None
        await team.asave()

        # Create audit log
        await AuditLog.objects.acreate(
            action="team_removed",
            admin_user=str(interaction.user),
            target_entity="team",
            target_id=team_number,
            details={
                "team_name": team.team_name,
                "unlinked_members": unlinked_count,
                "removed_items": removed_items,
            },
        )

        await log_to_ops_channel(
            self.bot,
            f"Team Removed: **{team.team_name}** by {interaction.user.mention}\n"
            f"• Unlinked {unlinked_count} members\n"
            f"• Removed {', '.join(removed_items) if removed_items else 'nothing'}",
        )

        await interaction.followup.send(
            f"Removed **{team.team_name}**\n"
            f"• Unlinked {unlinked_count} members\n"
            f"• Removed {', '.join(removed_items) if removed_items else 'nothing'}",
            ephemeral=True,
        )

    @teams_group.command(
        name="reset",
        description="[ADMIN] Team reset: unlink users, reset password, revoke sessions, recreate channels",
    )
    @app_commands.describe(
        team_number="Team number (1-50)",
        recreate_channels="Whether to recreate Discord channels and role (default: True)",
    )
    @app_commands.check(check_admin)
    async def admin_reset_team(
        self,
        interaction: discord.Interaction,
        team_number: int,
        recreate_channels: bool = True,
    ) -> None:
        """Team reset: unlinks users, resets password, revokes sessions, and optionally recreates infrastructure."""
        if team_number < 1 or team_number > 50:
            await interaction.response.send_message("Team number must be between 1 and 50", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        if not interaction.guild:
            await interaction.followup.send("This command must be used in a guild", ephemeral=True)
            return

        team = await Team.objects.filter(team_number=team_number).afirst()
        if not team:
            await interaction.followup.send(f"Team {team_number} not found", ephemeral=True)
            return

        results = []
        guild = interaction.guild

        # Step 1: Unlink all Discord users (select_related for authentik_username property)
        members = [m async for m in team.members.filter(is_active=True).select_related("user")]
        unlinked_count = 0

        for link in members:
            member = guild.get_member(link.discord_id)

            # Remove roles if member is in server
            if member:
                if team.discord_role_id:
                    role = guild.get_role(team.discord_role_id)
                    if role and role in member.roles:
                        await safe_remove_role(
                            member,
                            role,
                            reason=f"Team {team_number} reset by {interaction.user}",
                        )

                await remove_blueteam_role(
                    member,
                    guild,
                    reason=f"Team {team_number} reset by {interaction.user}",
                )

            # Deactivate link
            link.is_active = False
            link.unlinked_at = timezone.now()
            await link.asave()
            unlinked_count += 1

            # Create individual audit log for each unlink
            await AuditLog.objects.acreate(
                action="user_unlinked",
                admin_user=str(interaction.user),
                target_entity="discord_link",
                target_id=link.discord_id,
                details={
                    "discord_username": str(member) if member else f"ID:{link.discord_id}",
                    "team_name": team.team_name,
                    "authentik_username": link.authentik_username,
                    "reason": "team_reset",
                },
            )

        results.append(f"✓ Unlinked {unlinked_count} Discord user(s)")

        # Step 2: Generate and reset Authentik password
        from asgiref.sync import sync_to_async

        generated_password = generate_blueteam_password()
        success, error = await sync_to_async(reset_blueteam_password)(team_number, generated_password)
        new_password = None
        if success:
            results.append("✓ Reset Authentik password")
            new_password = generated_password
        else:
            results.append(f"❌ Failed to reset password: {error}")

        # Step 3: Revoke all sessions
        auth_manager = AuthentikManager()
        username = f"team{team_number:02d}"
        session_success, session_error, sessions_revoked = await sync_to_async(auth_manager.revoke_user_sessions)(
            username
        )
        if session_success:
            results.append(f"✓ Revoked {sessions_revoked} active session(s)")
        else:
            results.append(f"❌ Failed to revoke sessions: {session_error}")

        # Step 4: Optionally recreate channels and role
        if recreate_channels:
            # Delete existing infrastructure
            deleted_items = []

            # Delete category and channels
            if team.discord_category_id:
                category = guild.get_channel(team.discord_category_id)
                if category and isinstance(category, discord.CategoryChannel):
                    for channel in category.channels:
                        try:
                            await channel.delete(reason=f"Team {team_number} reset by {interaction.user}")
                        except Exception as e:
                            logger.exception(f"Failed to delete channel {channel.name}: {e}")

                    try:
                        await category.delete(reason=f"Team {team_number} reset by {interaction.user}")
                        deleted_items.append("category")
                    except Exception as e:
                        logger.exception(f"Failed to delete category: {e}")

            # Delete role
            if team.discord_role_id:
                role = guild.get_role(team.discord_role_id)
                if role:
                    try:
                        await role.delete(reason=f"Team {team_number} reset by {interaction.user}")
                        deleted_items.append("role")
                    except Exception as e:
                        logger.exception(f"Failed to delete role: {e}")

            # Clear Discord IDs
            team.discord_role_id = None
            team.discord_category_id = None
            await team.asave()

            if deleted_items:
                results.append(f"✓ Deleted {', '.join(deleted_items)}")

            # Recreate infrastructure
            from bot.discord_manager import DiscordManager

            discord_manager = DiscordManager(guild, self.bot)
            role, category = await discord_manager.setup_team_infrastructure(team_number)

            if role and category:
                results.append(f"✓ Recreated role and category with {len(category.channels)} channels")
            elif role:
                results.append("✓ Recreated role (category creation failed)")
            elif category:
                results.append("✓ Recreated category (role creation failed)")
            else:
                results.append("❌ Failed to recreate infrastructure")
        else:
            results.append("⊘ Skipped channel recreation (recreate_channels=False)")

        # Create audit log
        await AuditLog.objects.acreate(
            action="team_reset",
            admin_user=str(interaction.user),
            target_entity="team",
            target_id=team_number,
            details={
                "team_name": team.team_name,
                "unlinked_members": unlinked_count,
                "sessions_revoked": sessions_revoked if session_success else 0,
                "recreated_channels": recreate_channels,
            },
        )

        # Log to ops channel
        await log_to_ops_channel(
            self.bot,
            f"Team Reset: **{team.team_name}** by {interaction.user.mention}\n"
            + "\n".join([f"• {r}" for r in results]),
        )

        # Send response
        response = f"**Team {team_number} Reset Complete**\n\n" + "\n".join(results)
        if new_password:
            response += f"\n\n**New Team Password:** `{new_password}`"
            response += "\n\n⚠️ Make sure to securely share this password with the team."
        await interaction.followup.send(response, ephemeral=True)

    @teams_group.command(
        name="activate",
        description="[ADMIN] Activate multiple teams in database",
    )
    @app_commands.describe(teams="Team numbers (e.g., '1,3,5-10,15')")
    @app_commands.check(check_admin)
    async def admin_activate_teams(self, interaction: discord.Interaction, teams: str) -> None:
        """Activate multiple teams in database (sets is_active=True)."""
        await interaction.response.defer(ephemeral=True)

        # Parse team numbers
        try:
            team_numbers = parse_team_range(teams)
        except ValueError as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)
            return

        if not team_numbers:
            await interaction.followup.send("No teams specified", ephemeral=True)
            return

        # Activate teams
        results = []
        success_count = 0
        for team_number in team_numbers:
            team = await Team.objects.filter(team_number=team_number).afirst()
            if not team:
                results.append(f"❌ Team {team_number:02d}: Not found")
                continue

            if team.is_active:
                results.append(f"⊘ Team {team_number:02d}: Already active")
                continue

            team.is_active = True
            await team.asave()
            results.append(f"✓ Team {team_number:02d}: Activated")
            success_count += 1

        # Create audit log
        await AuditLog.objects.acreate(
            action="teams_activated",
            admin_user=str(interaction.user),
            target_entity="teams",
            target_id=0,
            details={
                "team_numbers": team_numbers,
                "success_count": success_count,
                "total_count": len(team_numbers),
            },
        )

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Team Activation by {interaction.user.mention}\n"
            f"• Teams: {teams}\n"
            f"• Activated: {success_count}/{len(team_numbers)}",
        )

        # Build response
        summary = "**Team Activation Results**\n\n"
        summary += f"✓ Activated: {success_count}/{len(team_numbers)}\n\n"

        if len(results) <= 20:
            summary += "**Details:**\n" + "\n".join(results)
        else:
            summary += "**Details (first 20):**\n" + "\n".join(results[:20])
            summary += f"\n... and {len(results) - 20} more"

        await interaction.followup.send(summary, ephemeral=True)

    @teams_group.command(
        name="deactivate",
        description="[ADMIN] Deactivate multiple teams in database",
    )
    @app_commands.describe(teams="Team numbers (e.g., '1,3,5-10,15')")
    @app_commands.check(check_admin)
    async def admin_deactivate_teams(self, interaction: discord.Interaction, teams: str) -> None:
        """Deactivate multiple teams in database (sets is_active=False)."""
        await interaction.response.defer(ephemeral=True)

        # Parse team numbers
        try:
            team_numbers = parse_team_range(teams)
        except ValueError as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)
            return

        if not team_numbers:
            await interaction.followup.send("No teams specified", ephemeral=True)
            return

        # Deactivate teams
        results = []
        success_count = 0
        for team_number in team_numbers:
            team = await Team.objects.filter(team_number=team_number).afirst()
            if not team:
                results.append(f"❌ Team {team_number:02d}: Not found")
                continue

            if not team.is_active:
                results.append(f"⊘ Team {team_number:02d}: Already inactive")
                continue

            team.is_active = False
            await team.asave()
            results.append(f"✓ Team {team_number:02d}: Deactivated")
            success_count += 1

        # Create audit log
        await AuditLog.objects.acreate(
            action="teams_deactivated",
            admin_user=str(interaction.user),
            target_entity="teams",
            target_id=0,
            details={
                "team_numbers": team_numbers,
                "success_count": success_count,
                "total_count": len(team_numbers),
            },
        )

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Team Deactivation by {interaction.user.mention}\n"
            f"• Teams: {teams}\n"
            f"• Deactivated: {success_count}/{len(team_numbers)}",
        )

        # Build response
        summary = "**Team Deactivation Results**\n\n"
        summary += f"✓ Deactivated: {success_count}/{len(team_numbers)}\n\n"

        if len(results) <= 20:
            summary += "**Details:**\n" + "\n".join(results)
        else:
            summary += "**Details (first 20):**\n" + "\n".join(results[:20])
            summary += f"\n... and {len(results) - 20} more"

        await interaction.followup.send(summary, ephemeral=True)

    @teams_group.command(
        name="recreate",
        description="[ADMIN] Recreate Discord infrastructure for multiple teams",
    )
    @app_commands.describe(teams="Team numbers (e.g., '1,3,5-10,15')")
    @app_commands.check(check_admin)
    async def admin_recreate_teams(self, interaction: discord.Interaction, teams: str) -> None:
        """Recreate Discord infrastructure (roles, channels) for multiple teams."""
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild:
            await interaction.followup.send("This command must be used in a guild", ephemeral=True)
            return

        # Parse team numbers
        try:
            team_numbers = parse_team_range(teams)
        except ValueError as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)
            return

        if not team_numbers:
            await interaction.followup.send("No teams specified", ephemeral=True)
            return

        from bot.discord_manager import DiscordManager

        discord_manager = DiscordManager(interaction.guild, self.bot)
        guild = interaction.guild

        results = []
        success_count = 0
        failed_count = 0

        for team_number in team_numbers:
            team = await Team.objects.filter(team_number=team_number).afirst()
            if not team:
                results.append(f"❌ Team {team_number:02d}: Not found")
                failed_count += 1
                continue

            # Delete existing infrastructure if present
            deleted_items = []

            # Delete category and channels
            if team.discord_category_id:
                category = guild.get_channel(team.discord_category_id)
                if category and isinstance(category, discord.CategoryChannel):
                    for channel in category.channels:
                        try:
                            await channel.delete(reason=f"Bulk recreate by {interaction.user}")
                        except Exception as e:
                            logger.exception(f"Failed to delete channel {channel.name}: {e}")

                    try:
                        await category.delete(reason=f"Bulk recreate by {interaction.user}")
                        deleted_items.append("category")
                    except Exception as e:
                        logger.exception(f"Failed to delete category: {e}")

            # Delete role
            if team.discord_role_id:
                role = guild.get_role(team.discord_role_id)
                if role:
                    try:
                        await role.delete(reason=f"Bulk recreate by {interaction.user}")
                        deleted_items.append("role")
                    except Exception as e:
                        logger.exception(f"Failed to delete role: {e}")

            # Clear Discord IDs
            team.discord_role_id = None
            team.discord_category_id = None
            await team.asave()

            # Recreate infrastructure
            role, category = await discord_manager.setup_team_infrastructure(team_number)

            if role and category:
                results.append(f"✓ Team {team_number:02d}: Recreated (role + {len(category.channels)} channels)")
                success_count += 1
            elif role or category:
                results.append(f"⚠ Team {team_number:02d}: Partially recreated")
                failed_count += 1
            else:
                results.append(f"❌ Team {team_number:02d}: Failed to recreate")
                failed_count += 1

        # Create audit log
        await AuditLog.objects.acreate(
            action="teams_recreated",
            admin_user=str(interaction.user),
            target_entity="teams",
            target_id=0,
            details={
                "team_numbers": team_numbers,
                "success_count": success_count,
                "failed_count": failed_count,
                "total_count": len(team_numbers),
            },
        )

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Team Infrastructure Recreate by {interaction.user.mention}\n"
            f"• Teams: {teams}\n"
            f"• Success: {success_count}\n"
            f"• Failed: {failed_count}",
        )

        # Build response
        summary = "**Team Recreation Results**\n\n"
        summary += f"✓ Success: {success_count}/{len(team_numbers)}\n"
        if failed_count > 0:
            summary += f"❌ Failed: {failed_count}/{len(team_numbers)}\n"
        summary += "\n"

        if len(results) <= 20:
            summary += "**Details:**\n" + "\n".join(results)
        else:
            summary += "**Details (first 20):**\n" + "\n".join(results[:20])
            summary += f"\n... and {len(results) - 20} more"

        await interaction.followup.send(summary, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Setup function to add cog to bot."""
    await bot.add_cog(AdminTeamsCog(bot))
