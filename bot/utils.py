"""Utility functions for the bot."""

import logging
import discord
from typing import Optional, Tuple
from django.conf import settings
from asgiref.sync import sync_to_async
from core.models import AuditLog
from team.models import Team
from ticketing.models import Ticket, TicketHistory

logger = logging.getLogger(__name__)


async def log_to_ops_channel(
    bot: discord.Client, message: str, embed: Optional[discord.Embed] = None
) -> None:
    """Log a message to the operations channel."""
    try:
        channel_id = settings.DISCORD_LOG_CHANNEL_ID
        if not channel_id:
            logger.warning("DISCORD_LOG_CHANNEL_ID not configured")
            return

        channel = bot.get_channel(channel_id)
        if not channel:
            logger.error(f"Operations channel {channel_id} not found")
            return

        # Type guard: only TextChannel and Thread have send()
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            if embed:
                await channel.send(message, embed=embed)
            else:
                await channel.send(message)
            logger.info(f"Logged to ops channel: {message}")
        else:
            logger.error(f"Channel {channel_id} is not a text channel or thread")
    except Exception as e:
        logger.error(f"Failed to log to ops channel: {e}")


def format_team_name(team_number: int) -> str:
    """Format team name consistently."""
    return f"BlueTeam{team_number:02d}"


def format_role_name(team_number: int) -> str:
    """Format role name consistently."""
    return f"Team {team_number:02d}"


def format_category_name(team_number: int) -> str:
    """Format category name consistently."""
    return f"team {team_number:02d}"


async def get_team_or_respond(
    interaction: discord.Interaction, team_number: int, validate_range: bool = True
) -> Optional["Team"]:
    """
    Get team by number or respond with error message.

    Args:
        interaction: Discord interaction to respond to
        team_number: Team number to look up
        validate_range: If True, validate team_number is between 1-50

    Returns:
        Team object if found, None if not found (error sent to user)
    """
    from team.models import Team

    if validate_range and (team_number < 1 or team_number > 50):
        await interaction.response.send_message(
            "Team number must be between 1 and 50", ephemeral=True
        )
        return None

    team = await Team.objects.filter(team_number=team_number).afirst()
    if not team:
        await interaction.response.send_message(
            f"Team {team_number} not found", ephemeral=True
        )
        return None
    return team


async def safe_remove_role(
    member: discord.Member, role: discord.Role, reason: Optional[str] = None
) -> bool:
    """
    Safely remove a role from a member, catching permission errors.

    Returns:
        True if role was removed or member didn't have it, False on error
    """
    if role not in member.roles:
        return True

    try:
        await member.remove_roles(role, reason=reason)
        return True
    except discord.errors.Forbidden:
        logger.warning(f"Permission denied removing role {role.name} from {member}")
        return False
    except Exception as e:
        logger.error(f"Error removing role {role.name} from {member}: {e}")
        return False


async def safe_add_role(
    member: discord.Member, role: discord.Role, reason: Optional[str] = None
) -> bool:
    """
    Safely add a role to a member, catching permission errors.

    Returns:
        True if role was added or member already had it, False on error
    """
    if role in member.roles:
        return True

    try:
        await member.add_roles(role, reason=reason)
        return True
    except discord.errors.Forbidden:
        logger.warning(f"Permission denied adding role {role.name} to {member}")
        return False
    except Exception as e:
        logger.error(f"Error adding role {role.name} to {member}: {e}")
        return False


async def remove_blueteam_role(
    member: discord.Member, guild: discord.Guild, reason: Optional[str] = None
) -> bool:
    """
    Remove Blueteam role from a member if they have it.

    Returns:
        True if removed or not present, False on error
    """
    blueteam_role = discord.utils.get(guild.roles, name="Blueteam")
    if not blueteam_role:
        return True

    return await safe_remove_role(member, blueteam_role, reason)


def log_action(
    actor_username: str,
    action: str,
    details: str | dict[str, str],
    ticket: Optional["Ticket"] = None,
    team: Optional["Team"] = None,
) -> Tuple["AuditLog", Optional["TicketHistory"]]:
    """
    Create audit log and optionally ticket history for an action.

    Args:
        actor_username: Username performing the action
        action: Action type (e.g., 'resolved', 'cancelled')
        details: Detailed description
        ticket: Optional ticket object for ticket-related actions
        team: Optional team object for team-related actions

    Returns:
        Tuple of (AuditLog, TicketHistory or None)
    """
    from core.models import AuditLog
    from ticketing.models import TicketHistory

    # Determine target entity and ID
    if ticket:
        target_entity = "ticket"
        target_id = ticket.id
    elif team:
        target_entity = "team"
        target_id = team.id
    else:
        target_entity = "system"
        target_id = 0

    audit_log = AuditLog.objects.create(
        action=action,
        admin_user=actor_username,
        target_entity=target_entity,
        target_id=target_id,
        details=details if isinstance(details, dict) else {"message": details},
    )

    ticket_history = None
    if ticket:
        ticket_history = TicketHistory.objects.create(
            ticket=ticket,
            action=action,
            actor_username=actor_username,
            details=details if isinstance(details, dict) else {"message": details},
        )

    return audit_log, ticket_history


async def safe_post_to_dashboard(bot: discord.Client, ticket: "Ticket") -> bool:
    """
    Post ticket to dashboard, catching and logging errors.

    Returns:
        True if posted successfully, False on error
    """
    from bot.ticket_dashboard import post_ticket_to_dashboard

    try:
        await post_ticket_to_dashboard(bot, ticket)
        return True
    except Exception as e:
        logger.error(f"Failed to post ticket to dashboard: {e}")
        return False


@sync_to_async
def get_team_member_discord_ids(team: Team) -> list[int]:
    """
    Get list of Discord IDs for all active team members.

    Args:
        team: Team object to get members from

    Returns:
        List of Discord IDs as integers
    """
    return list(
        team.members.filter(is_active=True).values_list("discord_id", flat=True)
    )
