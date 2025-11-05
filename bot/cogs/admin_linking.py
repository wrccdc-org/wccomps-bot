"""Admin commands for team management."""

import discord
from discord import app_commands
from discord.ext import commands
import logging
import re
from typing import Any, Optional, cast
from django.conf import settings
from django.utils import timezone
from core.models import (
    Team,
    DiscordLink,
    AuditLog,
    Ticket,
    TicketHistory,
    CompetitionConfig,
)
from core.tickets_config import TICKET_CATEGORIES
from bot.utils import (
    log_to_ops_channel,
    get_team_or_respond,
    safe_remove_role,
    remove_blueteam_role,
)
from bot.ticket_dashboard import post_ticket_to_dashboard, update_ticket_dashboard
from bot.permissions import (
    require_admin,
    require_ticketing_admin,
    require_ticketing_support,
)

logger = logging.getLogger(__name__)


def toggle_authentik_user(username: str, is_active: bool) -> tuple[bool, str]:
    """
    Enable or disable a team account in Authentik with safety checks.

    Args:
        username: Authentik username (e.g., "team01")
        is_active: True to enable, False to disable

    Returns:
        (success: bool, error_message: str)
    """
    import requests

    headers = {
        "Authorization": f"Bearer {settings.AUTHENTIK_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(
            f"{settings.AUTHENTIK_URL}/api/v3/core/users/?username={username}",
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        users = response.json().get("results", [])

        if not users:
            return (False, "User not found")

        user = users[0]

        # Safety check: Verify this is actually a team account
        is_valid, error = validate_team_account(user, username)
        if not is_valid:
            return (False, error)

        response = requests.patch(
            f"{settings.AUTHENTIK_URL}/api/v3/core/users/{user['pk']}/",
            headers=headers,
            json={"is_active": is_active},
            timeout=10,
        )
        response.raise_for_status()
        return (True, "")
    except Exception as e:
        logger.error(f"Failed to toggle {username}: {e}")
        return (False, str(e))


async def toggle_all_blueteam_accounts(is_active: bool) -> tuple[int, int]:
    """
    Enable or disable all team01-team50 accounts in Authentik.

    Args:
        is_active: True to enable, False to disable

    Returns:
        (success_count, failed_count)
    """
    from asgiref.sync import sync_to_async

    success_count = 0
    failed_count = 0
    for i in range(1, 51):
        username = f"team{i:02d}"
        success, _ = await sync_to_async(toggle_authentik_user)(username, is_active)
        if success:
            success_count += 1
        else:
            failed_count += 1

    return (success_count, failed_count)


def parse_team_range(range_str: str) -> list[int]:
    """
    Parse team range string like "1,3,5-10,15" into list of team numbers.

    Args:
        range_str: String with comma-separated numbers and ranges (e.g., "1,3,5-10,15")

    Returns:
        List of unique team numbers, sorted

    Examples:
        "1,3,5" -> [1, 3, 5]
        "1-5" -> [1, 2, 3, 4, 5]
        "1,3,5-10,15" -> [1, 3, 5, 6, 7, 8, 9, 10, 15]
    """
    team_numbers: set[int] = set()

    for part in range_str.split(","):
        part = part.strip()
        if not part:
            continue

        if "-" in part:
            # Range like "5-10"
            try:
                start_str, end_str = part.split("-", 1)
                start_num = int(start_str.strip())
                end_num = int(end_str.strip())

                if start_num > end_num:
                    raise ValueError(f"Invalid range: {part} (start > end)")
                if start_num < 1 or end_num > 50:
                    raise ValueError(f"Team numbers must be 1-50, got: {part}")

                team_numbers.update(range(start_num, end_num + 1))
            except ValueError as e:
                raise ValueError(f"Invalid range format: {part}") from e
        else:
            # Single number
            try:
                num = int(part)
                if num < 1 or num > 50:
                    raise ValueError(f"Team number must be 1-50, got: {num}")
                team_numbers.add(num)
            except ValueError:
                raise ValueError(f"Invalid team number: {part}")

    return sorted(list(team_numbers))


def generate_blueteam_password() -> str:
    """Generate a readable password for blue team accounts using EFF wordlist.

    Returns:
        str: Password in format like "Correct-Horse-742!" or "Battery-@199-Staple"
    """
    import secrets
    from xkcdpass import xkcd_password as xp

    # Get EFF long wordlist (7,776 words)
    wordlist = xp.generate_wordlist(wordfile=xp.locate_wordfile())

    # Generate 2 random words
    words = xp.generate_xkcdpassword(
        wordlist, numwords=2, delimiter="-", case="capitalize"
    )

    # Generate random number (100-999)
    number = secrets.randbelow(900) + 100

    # Select random special character
    special_chars = "!@#$%&*+"
    special_char = secrets.choice(special_chars)

    # Combine number and symbol (randomly choose order)
    if secrets.choice([True, False]):
        insert_value = f"{number}{special_char}"
    else:
        insert_value = f"{special_char}{number}"

    # Randomly choose position (0=before, 1=middle, 2=after)
    position = secrets.randbelow(3)

    # Insert number+symbol at chosen position
    word_parts = words.split("-")
    if position == 0:
        result = f"{insert_value}-{words}"
    elif position == 1:
        result = f"{word_parts[0]}-{insert_value}-{word_parts[1]}"
    else:  # position == 2
        result = f"{words}-{insert_value}"

    return result


def validate_team_account(
    user_data: dict[str, Any], expected_username: str
) -> tuple[bool, str]:
    """Validate that a user account is a legitimate team account.

    Args:
        user_data: User data from Authentik API
        expected_username: Expected username (e.g., "team01")

    Returns:
        Tuple of (is_valid: bool, error_message: str)
    """
    retrieved_username = user_data.get("username", "")

    # Check username starts with "team"
    if not retrieved_username.startswith("team"):
        return (
            False,
            f"Security error: User {retrieved_username} is not a team account",
        )

    # Check it matches expected username
    if retrieved_username != expected_username:
        return (
            False,
            f"Security error: Username mismatch (expected {expected_username}, got {retrieved_username})",
        )

    return (True, "")


def reset_blueteam_password(team_number: int, password: str) -> tuple[bool, str]:
    """Reset a blue team account's password in Authentik and enable the account.

    Args:
        team_number: Team number (1-50)
        password: New password to set

    Returns:
        Tuple of (success: bool, error_message: str or None)
    """
    import requests

    if team_number < 1 or team_number > 50:
        return (False, "Team number must be between 1 and 50")

    username = f"team{team_number:02d}"

    headers = {
        "Authorization": f"Bearer {settings.AUTHENTIK_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        # Get user by username
        response = requests.get(
            f"{settings.AUTHENTIK_URL}/api/v3/core/users/?username={username}",
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        users = response.json().get("results", [])

        if not users:
            return (False, f"User {username} not found")

        user = users[0]
        user_pk = user["pk"]

        # Safety check: Verify this is actually a team account
        is_valid, error = validate_team_account(user, username)
        if not is_valid:
            return (False, error)

        # Set password
        response = requests.post(
            f"{settings.AUTHENTIK_URL}/api/v3/core/users/{user_pk}/set_password/",
            headers=headers,
            json={"password": password},
            timeout=10,
        )
        response.raise_for_status()

        # Enable user account (set is_active=True)
        response = requests.patch(
            f"{settings.AUTHENTIK_URL}/api/v3/core/users/{user_pk}/",
            headers=headers,
            json={"is_active": True},
            timeout=10,
        )
        response.raise_for_status()

        return (True, "")

    except Exception as e:
        logger.error(f"Failed to reset password for {username}: {e}")
        return (False, str(e))


class AdminLinkingCog(commands.Cog):
    """Admin commands for team linking management."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    admin_group = app_commands.Group(name="admin", description="Admin commands")
    ticket_group = app_commands.Group(
        name="ticket", description="Ticket management commands", parent=admin_group
    )
    competition_group = app_commands.Group(
        name="competition",
        description="Competition application management commands",
        parent=admin_group,
    )

    @admin_group.command(name="teams", description="[ADMIN] List all teams with status")
    @require_admin
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
            embed.description = (
                f"{len(team_statuses)} teams total (use /admin team-info for details)"
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(
        name="team-info", description="[ADMIN] Get detailed info about a specific team"
    )
    @app_commands.describe(team_number="Team number (1-50)")
    @require_admin
    async def admin_team_info(
        self, interaction: discord.Interaction, team_number: int
    ) -> None:
        """Get detailed information about a team."""
        team = await get_team_or_respond(interaction, team_number)
        if not team:
            return

        member_count = await team.members.filter(is_active=True).acount()
        # Fetch all members
        members = [
            m async for m in team.members.filter(is_active=True).order_by("linked_at")
        ]

        embed = discord.Embed(
            title=f"{team.team_name} Details", color=discord.Color.blue()
        )
        embed.add_field(name="Team Number", value=f"#{team.team_number}", inline=True)
        embed.add_field(
            name="Members", value=f"{member_count}/{team.max_members}", inline=True
        )
        embed.add_field(
            name="Authentik Group", value=team.authentik_group, inline=False
        )

        if members:
            # Build member list, respecting Discord's 1024 char field limit
            member_lines = [
                f"• {m.discord_username} (ID: {m.discord_id}) - via `{m.authentik_username}`"
                for m in members
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

            embed.add_field(
                name="Team Members", value=member_list.strip(), inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(
        name="unlink",
        description="[ADMIN] Unlink one or more Discord users from their teams",
    )
    @app_commands.describe(
        users="User mention(s), ID(s), or space-separated list of multiple users"
    )
    @require_admin
    async def admin_unlink(self, interaction: discord.Interaction, users: str) -> None:
        """Unlink one or more Discord users from their teams."""
        await interaction.response.defer(ephemeral=True)

        if not interaction.guild:
            await interaction.followup.send(
                "This command must be used in a guild", ephemeral=True
            )
            return

        # Parse user IDs from the input string (mentions or raw IDs)
        import re

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

                # Check if user is linked
                link = await (
                    DiscordLink.objects.filter(discord_id=user_id, is_active=True)
                    .select_related("team")
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
                logger.error(f"Error unlinking user {user_id}: {e}")
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
                f"Bulk Unlink: {interaction.user.mention} unlinked {success_count} user(s) (Processed: {len(user_ids)}, Failed: {error_count})",
            )

    @admin_group.command(
        name="remove-team",
        description="[ADMIN] Remove team infrastructure and unlink all members",
    )
    @app_commands.describe(team_number="Team number (1-50)")
    @require_admin
    async def admin_remove_team(
        self, interaction: discord.Interaction, team_number: int
    ) -> None:
        """Remove a team's Discord infrastructure and unlink all members."""
        # Note: can't use get_team_or_respond here because we defer() before validation
        if team_number < 1 or team_number > 50:
            await interaction.response.send_message(
                "Team number must be between 1 and 50", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        team = await Team.objects.filter(team_number=team_number).afirst()
        if not team:
            await interaction.followup.send(
                f"Team {team_number} not found", ephemeral=True
            )
            return

        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(
                "This command must be used in a guild", ephemeral=True
            )
            return

        removed_items = []

        # Get all team members
        members = [m async for m in team.members.filter(is_active=True)]
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

        # Delete category and all channels
        if team.discord_category_id:
            category = guild.get_channel(team.discord_category_id)
            if category and isinstance(category, discord.CategoryChannel):
                # Delete all channels in category first
                for channel in category.channels:
                    try:
                        await channel.delete(
                            reason=f"Team {team_number} removed by {interaction.user}"
                        )
                    except Exception as e:
                        logger.error(f"Failed to delete channel {channel.name}: {e}")

                # Delete category
                try:
                    await category.delete(
                        reason=f"Team {team_number} removed by {interaction.user}"
                    )
                    removed_items.append("category")
                except Exception as e:
                    logger.error(f"Failed to delete category: {e}")

        # Delete role
        if team.discord_role_id:
            role = guild.get_role(team.discord_role_id)
            if role:
                try:
                    await role.delete(
                        reason=f"Team {team_number} removed by {interaction.user}"
                    )
                    removed_items.append("role")
                except Exception as e:
                    logger.error(f"Failed to delete role: {e}")

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

    @admin_group.command(
        name="reset-team",
        description="[ADMIN] Comprehensive team reset: unlink users, reset password, revoke sessions, recreate channels",
    )
    @app_commands.describe(
        team_number="Team number (1-50)",
        recreate_channels="Whether to recreate Discord channels and role (default: True)",
    )
    @require_admin
    async def admin_reset_team(
        self,
        interaction: discord.Interaction,
        team_number: int,
        recreate_channels: bool = True,
    ) -> None:
        """Comprehensive team reset: unlinks users, resets password, revokes sessions, and optionally recreates infrastructure."""
        if team_number < 1 or team_number > 50:
            await interaction.response.send_message(
                "Team number must be between 1 and 50", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        if not interaction.guild:
            await interaction.followup.send(
                "This command must be used in a guild", ephemeral=True
            )
            return

        team = await Team.objects.filter(team_number=team_number).afirst()
        if not team:
            await interaction.followup.send(
                f"Team {team_number} not found", ephemeral=True
            )
            return

        results = []
        guild = interaction.guild

        # Step 1: Unlink all Discord users
        members = [m async for m in team.members.filter(is_active=True)]
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

        results.append(f"✓ Unlinked {unlinked_count} Discord user(s)")

        # Step 2: Generate and reset Authentik password
        from asgiref.sync import sync_to_async

        generated_password = generate_blueteam_password()
        success, error = await sync_to_async(reset_blueteam_password)(
            team_number, generated_password
        )
        new_password = None
        if success:
            results.append("✓ Reset Authentik password")
            new_password = generated_password
        else:
            results.append(f"❌ Failed to reset password: {error}")

        # Step 3: Revoke all sessions
        from bot.authentik_manager import AuthentikManager

        auth_manager = AuthentikManager()
        username = f"team{team_number:02d}"
        session_success, session_error, sessions_revoked = await sync_to_async(
            auth_manager.revoke_user_sessions
        )(username)
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
                            await channel.delete(
                                reason=f"Team {team_number} reset by {interaction.user}"
                            )
                        except Exception as e:
                            logger.error(
                                f"Failed to delete channel {channel.name}: {e}"
                            )

                    try:
                        await category.delete(
                            reason=f"Team {team_number} reset by {interaction.user}"
                        )
                        deleted_items.append("category")
                    except Exception as e:
                        logger.error(f"Failed to delete category: {e}")

            # Delete role
            if team.discord_role_id:
                role = guild.get_role(team.discord_role_id)
                if role:
                    try:
                        await role.delete(
                            reason=f"Team {team_number} reset by {interaction.user}"
                        )
                        deleted_items.append("role")
                    except Exception as e:
                        logger.error(f"Failed to delete role: {e}")

            # Clear Discord IDs
            team.discord_role_id = None
            team.discord_category_id = None
            await team.asave()

            if deleted_items:
                results.append(f"✓ Deleted {', '.join(deleted_items)}")

            # Recreate infrastructure
            from bot.discord_manager import DiscordManager

            discord_manager = DiscordManager(guild)
            role, category = await discord_manager.setup_team_infrastructure(
                team_number
            )

            if role and category:
                results.append(
                    f"✓ Recreated role and category with {len(category.channels)} channels"
                )
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

    @admin_group.command(
        name="end-competition", description="[ADMIN] End competition and cleanup"
    )
    @require_admin
    async def admin_end_competition(self, interaction: discord.Interaction) -> None:
        """End competition: clear channels, remove roles, deactivate links."""

        await interaction.response.send_message(
            "Starting competition cleanup... This runs in background. Check ops channel for progress.",
            ephemeral=True,
        )

        async def cleanup() -> None:
            try:
                await log_to_ops_channel(
                    self.bot,
                    f"Competition Cleanup Started by {interaction.user.mention}",
                )

                # Deactivate team member links only (preserve admin/support links)
                deactivated = await DiscordLink.objects.filter(
                    is_active=True, team__isnull=False
                ).aupdate(is_active=False, unlinked_at=timezone.now())
                await log_to_ops_channel(
                    self.bot, f"Deactivated {deactivated} team member links"
                )

                # Delete ALL team categories/channels (including Team 01)
                guild = interaction.guild
                if not guild:
                    await interaction.followup.send(
                        "Error: Guild not found", ephemeral=True
                    )
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
                            logger.error(f"Failed to delete {category.name}: {e}")

                await log_to_ops_channel(
                    self.bot, f"Deleted {deleted_count} team categories"
                )

                from bot.discord_manager import DiscordManager

                discord_manager = DiscordManager(guild)
                removed_count = await discord_manager.remove_all_team_roles()
                await log_to_ops_channel(
                    self.bot, f"Removed roles from {removed_count} members"
                )

                await Team.objects.all().aupdate(
                    discord_category_id=None, discord_role_id=None
                )

                # Disable all team accounts in Authentik
                if settings.AUTHENTIK_TOKEN:
                    disabled_count, failed_count = await toggle_all_blueteam_accounts(
                        is_active=False
                    )
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
                logger.error(f"Cleanup error: {e}")
                await log_to_ops_channel(self.bot, f"Cleanup Error: {e}")

        self.bot.loop.create_task(cleanup())

    @ticket_group.command(
        name="create", description="[ADMIN] Create a ticket for a team"
    )
    @app_commands.describe(
        team_number="Team number (1-50)",
        category="Ticket category",
        description="Description of the issue",
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name=cat["display_name"], value=cat_id)
            for cat_id, cat in TICKET_CATEGORIES.items()
        ]
    )
    @require_ticketing_admin
    async def admin_ticket_create(
        self,
        interaction: discord.Interaction,
        team_number: int,
        category: str,
        description: str,
    ) -> None:
        """Create a ticket as admin."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command must be used in a guild", ephemeral=True
            )
            return

        team = await get_team_or_respond(interaction, team_number)
        if not team:
            return

        cat_info = TICKET_CATEGORIES.get(category)
        if not cat_info:
            await interaction.response.send_message(
                "Invalid ticket category.", ephemeral=True
            )
            return

        # For box-reset, use description as hostname
        hostname = description if category == "box-reset" else ""

        # Generate ticket number
        latest_ticket = (
            await Ticket.objects.filter(team=team).order_by("-created_at").afirst()
        )
        if latest_ticket:
            try:
                last_seq = int(latest_ticket.ticket_number.split("-")[1])
                sequence = last_seq + 1
            except (IndexError, ValueError):
                sequence = 1
        else:
            sequence = 1

        ticket_number = f"T{team.team_number:03d}-{sequence:03d}"

        # Create ticket
        ticket = await Ticket.objects.acreate(
            ticket_number=ticket_number,
            team=team,
            category=category,
            title=cat_info["display_name"],
            description=description,
            hostname=hostname,
            status="open",
            points_charged=cat_info.get("points", 0),
        )

        # Create history entry
        await TicketHistory.objects.acreate(
            ticket=ticket,
            action="created",
            actor_username=str(interaction.user),
            details=f"Ticket created by admin {interaction.user}",
        )

        # Create thread in team's category
        if team.discord_category_id:
            try:
                category_channel = (
                    interaction.guild.get_channel(team.discord_category_id)
                    if interaction.guild
                    else None
                )
                if category_channel and isinstance(
                    category_channel, discord.CategoryChannel
                ):
                    # Find the team's text channel within the category
                    chat_channel = None
                    for channel in category_channel.channels:
                        if (
                            isinstance(channel, discord.TextChannel)
                            and "chat" in channel.name.lower()
                        ):
                            chat_channel = channel
                            break

                    if not chat_channel:
                        logger.warning(
                            f"No text channel found in category {category_channel.name}"
                        )
                        raise Exception("No text channel found in team category")

                    thread = await chat_channel.create_thread(
                        name=f"{ticket.ticket_number} - Team {team.team_number:02d} - {ticket.title[:60]}",
                        auto_archive_duration=10080,  # 7 days
                    )

                    # Store thread ID
                    from asgiref.sync import sync_to_async

                    @sync_to_async
                    def save_thread_id() -> None:
                        ticket.discord_thread_id = thread.id
                        ticket.discord_channel_id = category_channel.id
                        ticket.save()

                    await save_thread_id()

                    # Add all linked team members to thread
                    from bot.utils import get_team_member_discord_ids

                    team_member_ids = await get_team_member_discord_ids(team)
                    for member_id in team_member_ids:
                        try:
                            member = interaction.guild.get_member(member_id)
                            if member:
                                await thread.add_user(member)
                        except Exception as e:
                            logger.warning(
                                f"Failed to add member {member_id} to thread: {e}"
                            )

                    # Send initial message in thread with action buttons
                    from bot.ticket_dashboard import (
                        format_ticket_embed,
                        TicketActionView,
                    )

                    embed_thread = format_ticket_embed(ticket)
                    view = TicketActionView(ticket.id)

                    await thread.send(
                        f"**Ticket #{ticket.ticket_number}** - Use buttons below to manage this ticket.",
                        embed=embed_thread,
                        view=view,
                    )

                    logger.info(
                        f"Created thread {thread.id} for ticket #{ticket.ticket_number} (admin)"
                    )
            except Exception as e:
                logger.error(
                    f"Failed to create thread for ticket {ticket.ticket_number}: {e}"
                )

        # Post to dashboard
        try:
            await post_ticket_to_dashboard(self.bot, ticket)
        except Exception as e:
            logger.error(f"Failed to post ticket to dashboard: {e}")

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Admin Ticket Created: {ticket.ticket_number} - {cat_info['display_name']} for **{team.team_name}** by {interaction.user.mention}",
        )

        await interaction.response.send_message(
            f"Created ticket **{ticket.ticket_number}** for **{team.team_name}**\n"
            f"Category: {cat_info['display_name']}\n"
            f"Point cost: {cat_info.get('points', 0)} points",
            ephemeral=True,
        )

    @ticket_group.command(name="list", description="[ADMIN] List open tickets")
    @app_commands.describe(
        status="Filter by status", team_number="Filter by team number"
    )
    @app_commands.choices(
        status=[
            app_commands.Choice(name="Open", value="open"),
            app_commands.Choice(name="Claimed", value="claimed"),
            app_commands.Choice(name="Resolved", value="resolved"),
            app_commands.Choice(name="All", value="all"),
        ]
    )
    @require_ticketing_support
    async def admin_ticket_list(
        self,
        interaction: discord.Interaction,
        status: str = "open",
        team_number: Optional[int] = None,
    ) -> None:
        """List tickets with optional filters."""

        # Build query
        query = Ticket.objects.select_related("team")
        if status != "all":
            query = query.filter(status=status)
        if team_number:
            query = query.filter(team__team_number=team_number)

        # Get total count first
        total_count = await query.acount()

        if total_count == 0:
            await interaction.response.send_message(
                "No tickets found matching criteria", ephemeral=True
            )
            return

        # Fetch tickets (limit to 25 due to Discord embed field limit)
        display_limit = 25
        tickets = [t async for t in query.order_by("-created_at")[:display_limit]]

        # Build title showing count
        if total_count > display_limit:
            title = f"Tickets ({status}) - Showing {display_limit} of {total_count}"
        else:
            title = f"Tickets ({status}) - {total_count} total"

        embed = discord.Embed(title=title, color=discord.Color.blue())

        for ticket in tickets:
            cat_info = TICKET_CATEGORIES.get(ticket.category, {})
            value = (
                f"Team: {ticket.team.team_name}\n"
                f"Category: {cat_info.get('display_name', ticket.category)}\n"
                f"Status: {ticket.status}\n"
                f"Created: {discord.utils.format_dt(ticket.created_at, style='R')}"
            )
            if ticket.assigned_to_discord_username:
                value += f"\nAssigned: {ticket.assigned_to_discord_username}"

            embed.add_field(
                name=f"#{ticket.id}: {ticket.title}", value=value, inline=False
            )

        if total_count > display_limit:
            embed.set_footer(text=f"Use web interface to see all {total_count} tickets")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ticket_group.command(
        name="resolve", description="[ADMIN] Resolve a ticket and apply points"
    )
    @app_commands.describe(
        ticket_id="Ticket ID number",
        notes="Resolution notes",
        points="Point adjustment (for variable point categories)",
    )
    @require_ticketing_support
    async def admin_ticket_resolve(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
        notes: str = "",
        points: Optional[int] = None,
    ) -> None:
        """Resolve a ticket and apply point adjustments."""

        ticket = (
            await Ticket.objects.select_related("team").filter(id=ticket_id).afirst()
        )
        if not ticket:
            await interaction.response.send_message(
                f"Ticket #{ticket_id} not found", ephemeral=True
            )
            return

        if ticket.status == "resolved":
            await interaction.response.send_message(
                f"Ticket #{ticket_id} is already resolved", ephemeral=True
            )
            return

        cat_info = TICKET_CATEGORIES.get(ticket.category, {})

        # Determine point penalty
        if cat_info.get("variable_points", False):
            if points is None:
                min_pts = cat_info.get("min_points", 0)
                max_pts = cat_info.get("max_points", 0)
                await interaction.response.send_message(
                    f"This category requires a point value between {min_pts} and {max_pts}",
                    ephemeral=True,
                )
                return

            min_pts = cast(int, cat_info.get("min_points", 0))
            max_pts = cast(int, cat_info.get("max_points", 0))
            if points < min_pts or points > max_pts:
                await interaction.response.send_message(
                    f"Point value must be between {min_pts} and {max_pts}",
                    ephemeral=True,
                )
                return

            point_penalty = points
        else:
            point_penalty = cat_info.get("points", 0)

        # Update ticket
        from datetime import timedelta

        ticket.status = "resolved"
        ticket.resolved_at = timezone.now()
        ticket.resolved_by_discord_id = interaction.user.id
        ticket.resolved_by_discord_username = str(interaction.user)
        ticket.resolution_notes = notes
        ticket.points_charged = point_penalty
        if not ticket.assigned_to_discord_id:
            ticket.assigned_to_discord_id = interaction.user.id
            ticket.assigned_to_discord_username = str(interaction.user)

        # Schedule thread archiving after 60 seconds
        if ticket.discord_thread_id:
            ticket.thread_archive_scheduled_at = timezone.now() + timedelta(seconds=60)

        await ticket.asave()

        # Create history entry
        await TicketHistory.objects.acreate(
            ticket=ticket,
            action="resolved",
            actor_username=str(interaction.user),
            details={"notes": notes, "point_penalty": point_penalty},
        )

        # Update dashboard
        try:
            await update_ticket_dashboard(self.bot, ticket)
        except Exception as e:
            logger.error(f"Failed to update dashboard: {e}")

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Ticket Resolved: #{ticket.id} for **{ticket.team.team_name}** by {interaction.user.mention}\n"
            f"Point Penalty: {point_penalty} points",
        )

        await interaction.response.send_message(
            f"Resolved ticket #{ticket.id}\n"
            f"Point Penalty: {point_penalty} points applied to {ticket.team.team_name}",
            ephemeral=True,
        )

    @ticket_group.command(
        name="cancel", description="[ADMIN] Cancel a ticket without applying points"
    )
    @app_commands.describe(
        ticket_id="Ticket ID number", reason="Reason for cancellation"
    )
    @require_ticketing_admin
    async def admin_ticket_cancel(
        self, interaction: discord.Interaction, ticket_id: int, reason: str = ""
    ) -> None:
        """Cancel a ticket without point penalty."""

        ticket = (
            await Ticket.objects.select_related("team").filter(id=ticket_id).afirst()
        )
        if not ticket:
            await interaction.response.send_message(
                f"Ticket #{ticket_id} not found", ephemeral=True
            )
            return

        if ticket.status == "resolved" or ticket.status == "cancelled":
            await interaction.response.send_message(
                f"Ticket #{ticket_id} is already {ticket.status}", ephemeral=True
            )
            return

        # Update ticket
        ticket.status = "cancelled"
        ticket.resolved_at = timezone.now()
        ticket.resolution_notes = reason or "Cancelled by admin"
        if not ticket.assigned_to_discord_id:
            ticket.assigned_to_discord_id = interaction.user.id
            ticket.assigned_to_discord_username = str(interaction.user)
        await ticket.asave()

        # Create history entry
        await TicketHistory.objects.acreate(
            ticket=ticket,
            action="cancelled",
            actor_username=str(interaction.user),
            details={"reason": reason},
        )

        # Update dashboard
        try:
            await update_ticket_dashboard(self.bot, ticket)
        except Exception as e:
            logger.error(f"Failed to update dashboard: {e}")

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Ticket Cancelled: #{ticket.id} for **{ticket.team.team_name}** by {interaction.user.mention}\n"
            f"Reason: {reason or 'No reason provided'}",
        )

        await interaction.response.send_message(
            f"Cancelled ticket #{ticket.id} (no point penalty applied)", ephemeral=True
        )

    @admin_group.command(
        name="reset-blueteam-passwords",
        description="[ADMIN] Reset passwords for blueteam accounts (optionally specify teams)",
    )
    @require_admin
    async def admin_reset_blueteam_passwords(
        self, interaction: discord.Interaction, team_numbers: Optional[str] = None
    ) -> None:
        """Reset passwords for blueteam accounts and export CSV.

        Args:
            team_numbers: Optional comma-separated team numbers or ranges (e.g., "1,3,5-10")
                         If not provided, resets all 50 teams.
        """

        if not settings.AUTHENTIK_TOKEN:
            await interaction.response.send_message(
                "Error: AUTHENTIK_TOKEN not configured in settings", ephemeral=True
            )
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
                    await button_interaction.response.send_message(
                        "Password reset cancelled.", ephemeral=True
                    )

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

            await interaction.followup.send(
                "Resetting all 50 team passwords...", ephemeral=True
            )
        else:
            await interaction.response.defer(ephemeral=True)

        import csv
        import io
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
            success, error = await sync_to_async(reset_blueteam_password)(
                team_num, password
            )
            if not success:
                failed_resets.append((username, error))

        # Generate CSV in memory
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(["Username", "Password"])

        for team_num, username, password in password_list:
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
        result_msg = (
            f"Password reset complete\n• Success: {success_count}/{team_count}\n"
        )
        if failed_resets:
            result_msg += f"• Failed: {len(failed_resets)}/{team_count}\n"
        result_msg += "\nCSV file attached with all credentials."

        await interaction.followup.send(
            result_msg,
            file=file,
            ephemeral=True,
        )

        logger.info(
            f"Password reset performed by {interaction.user}. Failed: {len(failed_resets)}"
        )

    @admin_group.command(
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
    @require_admin
    async def admin_toggle_blueteams(
        self, interaction: discord.Interaction, action: app_commands.Choice[str]
    ) -> None:
        """Enable or disable all blue team accounts in Authentik."""
        if not settings.AUTHENTIK_TOKEN:
            await interaction.response.send_message(
                "Error: AUTHENTIK_TOKEN not configured in settings", ephemeral=True
            )
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
            message += (
                f"\n❌ Failed: {failed_count}/50\n\nCheck logs for error details."
            )

        await interaction.followup.send(message, ephemeral=True)

        logger.info(
            f"Blue team accounts {action_past} by {interaction.user}. Failed: {failed_count}"
        )

    @admin_group.command(
        name="set-max-members", description="[ADMIN] Set maximum team members globally"
    )
    @app_commands.describe(max_members="Maximum members per team (1-20)")
    @require_admin
    async def admin_set_max_members(
        self, interaction: discord.Interaction, max_members: int
    ) -> None:
        """Set global maximum team members."""
        if max_members < 1 or max_members > 20:
            await interaction.response.send_message(
                "Maximum members must be between 1 and 20.", ephemeral=True
            )
            return

        config = (
            await CompetitionConfig.objects.afirst()
            or await CompetitionConfig.objects.acreate()
        )
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
            f"Max Team Members Updated by {interaction.user.mention}\n"
            f"• Old: {old_max}\n"
            f"• New: {max_members}",
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
    @require_admin
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
            # Parse datetime string as naive
            naive_time = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")

            # Apply the specified timezone
            local_time = naive_time.replace(tzinfo=ZoneInfo(timezone_name))

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
        config = (
            await CompetitionConfig.objects.afirst()
            or await CompetitionConfig.objects.acreate()
        )

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
        name="enable", description="[ADMIN] Enable competition applications immediately"
    )
    @require_admin
    async def admin_enable_applications_now(
        self, interaction: discord.Interaction
    ) -> None:
        """Manually enable competition applications (emergency override)."""

        await interaction.response.defer(ephemeral=True)

        config = (
            await CompetitionConfig.objects.afirst()
            or await CompetitionConfig.objects.acreate()
        )

        if not config.controlled_applications:
            await interaction.followup.send(
                "No controlled applications configured. Use `/admin competition-set-apps` first.",
                ephemeral=True,
            )
            return

        from bot.authentik_manager import AuthentikManager

        auth_manager = AuthentikManager()

        # Enable applications
        results = auth_manager.enable_applications(config.controlled_applications)

        # Update config
        config.applications_enabled = True
        await config.asave()

        # Build result message with detailed errors
        success_apps = [app for app, (success, _) in results.items() if success]
        failed_apps = [
            (app, error) for app, (success, error) in results.items() if not success
        ]

        # Create audit log with detailed results
        await AuditLog.objects.acreate(
            action="competition_apps_enabled_manually",
            admin_user=str(interaction.user),
            target_entity="competition_config",
            target_id=config.pk,
            details={
                "controlled_apps": config.controlled_applications,
                "success_count": len(success_apps),
                "failed_count": len(failed_apps),
                "errors": {app: error for app, error in failed_apps},
            },
        )

        result_msg = f"Applications enabled: {len(success_apps)}/{len(config.controlled_applications)}\n"
        if success_apps:
            result_msg += f"✓ Enabled: {', '.join(success_apps)}\n"
        if failed_apps:
            result_msg += "\n✗ **Failed Applications:**\n"
            for app, error in failed_apps:
                result_msg += f"  • {app}: {error}\n"

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Competition Applications Enabled Manually by {interaction.user.mention}\n{result_msg}",
        )

        await interaction.followup.send(result_msg, ephemeral=True)

    @competition_group.command(
        name="disable", description="[ADMIN] Disable competition applications"
    )
    @require_admin
    async def admin_competition_disable_apps(
        self, interaction: discord.Interaction
    ) -> None:
        """Manually disable competition applications."""

        await interaction.response.defer(ephemeral=True)

        config = (
            await CompetitionConfig.objects.afirst()
            or await CompetitionConfig.objects.acreate()
        )

        if not config.controlled_applications:
            await interaction.followup.send(
                "No controlled applications configured.", ephemeral=True
            )
            return

        from bot.authentik_manager import AuthentikManager

        auth_manager = AuthentikManager()

        # Disable applications
        results = auth_manager.disable_applications(config.controlled_applications)

        # Update config
        config.applications_enabled = False
        await config.asave()

        # Build result message with detailed errors
        success_apps = [app for app, (success, _) in results.items() if success]
        failed_apps = [
            (app, error) for app, (success, error) in results.items() if not success
        ]

        # Create audit log with detailed results
        await AuditLog.objects.acreate(
            action="competition_apps_disabled_manually",
            admin_user=str(interaction.user),
            target_entity="competition_config",
            target_id=config.pk,
            details={
                "controlled_apps": config.controlled_applications,
                "success_count": len(success_apps),
                "failed_count": len(failed_apps),
                "errors": {app: error for app, error in failed_apps},
            },
        )

        result_msg = f"Applications disabled: {len(success_apps)}/{len(config.controlled_applications)}\n"
        if success_apps:
            result_msg += f"✓ Disabled: {', '.join(success_apps)}\n"
        if failed_apps:
            result_msg += "\n✗ **Failed Applications:**\n"
            for app, error in failed_apps:
                result_msg += f"  • {app}: {error}\n"

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Competition Applications Disabled Manually by {interaction.user.mention}\n{result_msg}",
        )

        await interaction.followup.send(result_msg, ephemeral=True)

    @competition_group.command(
        name="set-apps",
        description="[ADMIN] Set which Authentik applications to control",
    )
    @app_commands.describe(
        app_slugs="Comma-separated list of application slugs (e.g., netbird,scoring)"
    )
    @require_admin
    async def admin_competition_set_apps(
        self, interaction: discord.Interaction, app_slugs: str
    ) -> None:
        """Set which applications to control."""

        # Parse slugs
        slugs = [s.strip() for s in app_slugs.split(",") if s.strip()]

        if not slugs:
            await interaction.response.send_message(
                "Please provide at least one application slug.", ephemeral=True
            )
            return

        config = (
            await CompetitionConfig.objects.afirst()
            or await CompetitionConfig.objects.acreate()
        )
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
            f"Competition Applications Configured by {interaction.user.mention}\n"
            f"• Applications: {', '.join(slugs)}",
        )

        await interaction.response.send_message(
            f"Controlled applications set to: {', '.join(slugs)}", ephemeral=True
        )

    @admin_group.command(
        name="broadcast",
        description="[ADMIN] Broadcast a message to announcement channel or team channels",
    )
    @app_commands.describe(
        target="Where to broadcast: 'announcements', 'all-teams', or specific teams (e.g., '1,3,5-10')",
        message="Message to broadcast",
    )
    @require_admin
    async def admin_broadcast(
        self, interaction: discord.Interaction, target: str, message: str
    ) -> None:
        """Broadcast a message to announcement channel or team channels."""

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        if not guild:
            await interaction.followup.send(
                "This command must be used in a guild", ephemeral=True
            )
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
                    f"Broadcast to Announcements by {interaction.user.mention}\n"
                    f"Message: {message[:100]}...",
                )

                await interaction.followup.send(
                    "Broadcast sent to announcements channel", ephemeral=True
                )
            except Exception as e:
                logger.error(f"Failed to broadcast to announcements: {e}")
                await interaction.followup.send(
                    f"Failed to send broadcast: {e}", ephemeral=True
                )
            return

        elif target_lower == "all-teams":
            # Broadcast to all team chat channels
            teams = [
                t
                async for t in Team.objects.filter(is_active=True).order_by(
                    "team_number"
                )
            ]
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
                    failed_channels.append(
                        f"Team {team_number:02d} (category not found)"
                    )
                    continue

                # Find chat channel in category
                chat_channel = None
                for channel in category.channels:
                    if (
                        isinstance(channel, discord.TextChannel)
                        and "chat" in channel.name.lower()
                    ):
                        chat_channel = channel
                        break

                if not chat_channel:
                    failed_channels.append(
                        f"Team {team_number:02d} (chat channel not found)"
                    )
                    continue

                # Send message
                await chat_channel.send(
                    f"**Announcement from {interaction.user.name}:**\n\n{message}"
                )
                sent_count += 1

            except Exception as e:
                logger.error(f"Failed to broadcast to team {team_number}: {e}")
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
                result_msg += "\n\nFailed channels:\n" + "\n".join(
                    [f"• {fc}" for fc in failed_channels]
                )
            else:
                result_msg += "\n\nFailed channels (first 10):\n" + "\n".join(
                    [f"• {fc}" for fc in failed_channels[:10]]
                )

        await interaction.followup.send(result_msg, ephemeral=True)

    @ticket_group.command(
        name="reassign",
        description="[ADMIN] Reassign a ticket to a different volunteer",
    )
    @app_commands.describe(
        ticket_id="Ticket ID number",
        volunteer="Discord user to assign (leave empty to unassign)",
    )
    @require_ticketing_admin
    async def admin_ticket_reassign(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
        volunteer: Optional[discord.User] = None,
    ) -> None:
        """Reassign a ticket to a different volunteer."""
        await interaction.response.defer(ephemeral=True)

        ticket = (
            await Ticket.objects.select_related("team").filter(id=ticket_id).afirst()
        )
        if not ticket:
            await interaction.followup.send(
                f"Ticket #{ticket_id} not found", ephemeral=True
            )
            return

        if ticket.status in ["resolved", "cancelled"]:
            await interaction.followup.send(
                f"Cannot reassign {ticket.status} ticket", ephemeral=True
            )
            return

        old_assignee = ticket.assigned_to_discord_username or "Unassigned"

        if volunteer:
            ticket.assigned_to_discord_id = volunteer.id
            ticket.assigned_to_discord_username = str(volunteer)
            ticket.assigned_at = timezone.now()

            # Update status if open
            if ticket.status == "open":
                ticket.status = "claimed"

            new_assignee = str(volunteer)
        else:
            # Unassign
            ticket.assigned_to_discord_id = None
            ticket.assigned_to_discord_username = ""
            ticket.assigned_at = None
            ticket.status = "open"
            new_assignee = "Unassigned"

        await ticket.asave()

        # Create history
        await TicketHistory.objects.acreate(
            ticket=ticket,
            action="reassigned",
            actor_discord_id=interaction.user.id,
            actor_username=str(interaction.user),
            details={"old_assignee": old_assignee, "new_assignee": new_assignee},
        )

        # Update dashboard
        from core.models import DiscordTask

        await DiscordTask.objects.acreate(task_type="update_dashboard", ticket=ticket)

        await interaction.followup.send(
            f"Ticket #{ticket_id} reassigned\n• From: {old_assignee}\n• To: {new_assignee}",
            ephemeral=True,
        )

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Ticket reassigned by {interaction.user.mention}\n"
            f"• Ticket: #{ticket_id} ({ticket.team.team_name})\n"
            f"• From: {old_assignee}\n"
            f"• To: {new_assignee}",
        )

    @ticket_group.command(name="reopen", description="[ADMIN] Reopen a resolved ticket")
    @app_commands.describe(ticket_id="Ticket ID number", reason="Reason for reopening")
    @require_ticketing_admin
    async def admin_ticket_reopen(
        self, interaction: discord.Interaction, ticket_id: int, reason: str
    ) -> None:
        """Reopen a resolved ticket."""
        await interaction.response.defer(ephemeral=True)

        ticket = (
            await Ticket.objects.select_related("team").filter(id=ticket_id).afirst()
        )
        if not ticket:
            await interaction.followup.send(
                f"Ticket #{ticket_id} not found", ephemeral=True
            )
            return

        if ticket.status != "resolved":
            await interaction.followup.send(
                f"Cannot reopen - ticket is {ticket.status}", ephemeral=True
            )
            return

        # Reopen ticket (only change status and clear resolved timestamp)
        old_status = ticket.status
        ticket.status = "open"
        ticket.resolved_at = None
        await ticket.asave()

        # Create history
        await TicketHistory.objects.acreate(
            ticket=ticket,
            action="reopened",
            actor_discord_id=interaction.user.id,
            actor_username=str(interaction.user),
            details={
                "reason": reason,
                "old_status": old_status,
            },
        )

        # Update dashboard
        from core.models import DiscordTask

        await DiscordTask.objects.acreate(task_type="update_dashboard", ticket=ticket)

        refund_msg = ""
        if ticket.points_charged > 0:
            refund_msg = f"\n• Refunded: {ticket.points_charged} points"

        await interaction.followup.send(
            f"Ticket #{ticket_id} reopened\n• Reason: {reason}{refund_msg}",
            ephemeral=True,
        )

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Ticket reopened by {interaction.user.mention}\n"
            f"• Ticket: #{ticket_id} ({ticket.team.team_name})\n"
            f"• Reason: {reason}{refund_msg}",
        )

    @admin_group.command(
        name="sync-roles",
        description="[ADMIN] Synchronize team roles from volunteer guild to competition guild",
    )
    @require_admin
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
            await interaction.followup.send(
                "Starting role synchronization...", ephemeral=True
            )

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
                    result_msg += (
                        f"\n... and {len(changes) - 20} more (check logs for full list)"
                    )

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
            await interaction.followup.send(
                f"Role sync failed: {str(e)}", ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    """Setup function to add cog to bot."""
    await bot.add_cog(AdminLinkingCog(bot))
