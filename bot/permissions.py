"""Permission checking for Discord bot commands."""

import logging
from datetime import UTC, datetime, timedelta
from typing import TypedDict

import discord
from allauth.socialaccount.models import SocialAccount

from team.models import DiscordLink

logger = logging.getLogger(__name__)


class PermissionCacheEntry(TypedDict):
    groups: list[str]
    expires_at: datetime


# Permission cache: {discord_id: {'groups': [...], 'expires_at': datetime}}
_permission_cache: dict[int, PermissionCacheEntry] = {}


def _get_authentik_groups_sync(discord_user_id: int) -> list[str]:
    """
    Get Authentik groups for a Discord user.

    Checks:
    1. Permission cache (5 minute TTL)
    2. Authentik API (via stored discord_id attribute)
    3. DiscordLink table (for team members)

    Returns empty list if user is not linked to Authentik.
    """
    try:
        # Check cache first
        now = datetime.now(UTC)
        if discord_user_id in _permission_cache:
            cached = _permission_cache[discord_user_id]
            if cached["expires_at"] > now:
                logger.debug(f"Permission cache hit for {discord_user_id}")
                return cached["groups"]
            # Cache expired, remove it
            del _permission_cache[discord_user_id]

        # Use DiscordLink table for all permission checks
        # (Authentik API discord_id attribute is unreliable)
        try:
            logger.info(f"Checking DiscordLink table for {discord_user_id}")
            discord_link = DiscordLink.objects.filter(discord_id=discord_user_id, is_active=True).first()

            if not discord_link:
                logger.info(f"No DiscordLink found for {discord_user_id}")
                return []

            logger.info(
                f"Found DiscordLink for {discord_user_id}: authentik_username={discord_link.authentik_username}"
            )

            # Get associated Django user's Authentik account
            # Query through User model instead of JSONField to avoid nested structure issues
            social_account = SocialAccount.objects.filter(
                user__username=discord_link.authentik_username,
                provider="authentik",
            ).first()

            if not social_account:
                logger.warning(f"No SocialAccount found for authentik_username={discord_link.authentik_username}")
                return []

            logger.info(f"Found SocialAccount for {discord_user_id}: user_id={social_account.user_id}")

            # Groups are nested in id_token or userinfo from OIDC response
            # Check each location deterministically
            groups = []
            if "id_token" in social_account.extra_data and "groups" in social_account.extra_data["id_token"]:
                groups = social_account.extra_data["id_token"]["groups"]
            elif "userinfo" in social_account.extra_data and "groups" in social_account.extra_data["userinfo"]:
                groups = social_account.extra_data["userinfo"]["groups"]
            elif "groups" in social_account.extra_data:
                groups = social_account.extra_data["groups"]

            logger.info(f"Found groups for {discord_user_id} via DiscordLink: {groups}")
        except Exception as db_error:
            # If we're in async context, database queries won't work
            # Fall back to API-only permission checking
            logger.exception(f"Database query failed (likely async context): {db_error}")
            return []

        # Cache the result
        _permission_cache[discord_user_id] = {
            "groups": groups,
            "expires_at": now + timedelta(minutes=5),
        }

        return groups
    except Exception as e:
        logger.warning(f"Error getting Authentik groups for Discord user {discord_user_id}: {e}")
        return []


async def get_authentik_groups_async(discord_user_id: int) -> list[str]:
    """Async version that properly handles database queries."""
    from asgiref.sync import sync_to_async

    # Wrap the sync version in sync_to_async
    return await sync_to_async(_get_authentik_groups_sync)(discord_user_id)


async def is_admin_async(interaction: discord.Interaction) -> bool:
    """
    Check if user has admin permissions via Authentik groups.

    Requires WCComps_Discord_Admin Authentik group.
    User must be linked via /link.

    Admin can:
    - All team management commands
    - All ticket management commands
    - Access Django admin interface
    """
    try:
        authentik_groups = await get_authentik_groups_async(interaction.user.id)
        return "WCComps_Discord_Admin" in authentik_groups
    except Exception as e:
        logger.exception(f"Failed to check Authentik groups for admin permission: {e}")
        return False


async def can_manage_tickets_async(interaction: discord.Interaction) -> bool:
    """
    Check if user can manage tickets via Authentik groups.

    Requires WCComps_Ticketing_Admin or WCComps_Discord_Admin group.
    User must be linked via /link.
    """
    if await is_admin_async(interaction):
        return True

    try:
        authentik_groups = await get_authentik_groups_async(interaction.user.id)
        return "WCComps_Ticketing_Admin" in authentik_groups
    except Exception as e:
        logger.exception(f"Failed to check Authentik groups for ticketing admin permission: {e}")
        return False


async def can_support_tickets_async(interaction: discord.Interaction) -> bool:
    """
    Check if user can work on tickets via Authentik groups.

    Requires WCComps_Ticketing_Support, WCComps_Ticketing_Admin, or WCComps_Discord_Admin group.
    User must be linked via /link.
    """
    if await is_admin_async(interaction) or await can_manage_tickets_async(interaction):
        return True

    try:
        authentik_groups = await get_authentik_groups_async(interaction.user.id)
        return "WCComps_Ticketing_Support" in authentik_groups
    except Exception as e:
        logger.exception(f"Failed to check Authentik groups for ticketing support permission: {e}")
        return False


async def is_gold_team_async(interaction: discord.Interaction) -> bool:
    """
    Check if user is member of GoldTeam via Authentik groups.

    Requires WCComps_GoldTeam or WCComps_Discord_Admin group.
    User must be linked via /link.
    """
    if await is_admin_async(interaction):
        return True

    try:
        authentik_groups = await get_authentik_groups_async(interaction.user.id)
        return "WCComps_GoldTeam" in authentik_groups
    except Exception as e:
        logger.exception(f"Failed to check Authentik groups for GoldTeam permission: {e}")
        return False


# Permission check functions for use with @app_commands.check()
async def check_admin(interaction: discord.Interaction) -> bool:
    """Check if user has admin permissions."""
    has_permission = await is_admin_async(interaction)
    if not has_permission:
        await interaction.response.send_message(
            "❌ Admin permissions required.\n\n"
            "You need the `WCComps_Discord_Admin` Authentik group.\n"
            "If you have this group, link your account with `/link`.",
            ephemeral=True,
        )
    return has_permission


async def check_ticketing_admin(interaction: discord.Interaction) -> bool:
    """Check if user can manage tickets."""
    has_permission = await can_manage_tickets_async(interaction)
    if not has_permission:
        await interaction.response.send_message(
            "❌ Ticketing admin permissions required.\n\n"
            "You need the `WCComps_Ticketing_Admin` Authentik group.\n"
            "If you have this group, link your account with `/link`.",
            ephemeral=True,
        )
    return has_permission


async def check_ticketing_support(interaction: discord.Interaction) -> bool:
    """Check if user can work on tickets."""
    has_permission = await can_support_tickets_async(interaction)
    if not has_permission:
        await interaction.response.send_message(
            "❌ Ticketing support permissions required.\n\n"
            "You need the `WCComps_Ticketing_Support` Authentik group.\n"
            "If you have this group, link your account with `/link`.",
            ephemeral=True,
        )
    return has_permission


async def check_gold_team(interaction: discord.Interaction) -> bool:
    """Check if user is member of GoldTeam."""
    has_permission = await is_gold_team_async(interaction)
    if not has_permission:
        await interaction.response.send_message(
            "❌ GoldTeam permissions required.\n\n"
            "You need the `WCComps_GoldTeam` Authentik group.\n"
            "If you have this group, link your account with `/link`.",
            ephemeral=True,
        )
    return has_permission


async def is_white_team_async(interaction: discord.Interaction) -> bool:
    """Check if user is member of WhiteTeam via Authentik groups."""
    if await is_admin_async(interaction):
        return True
    if await is_gold_team_async(interaction):
        return True

    try:
        authentik_groups = await get_authentik_groups_async(interaction.user.id)
        return "WCComps_WhiteTeam" in authentik_groups
    except Exception as e:
        logger.exception(f"Failed to check Authentik groups for WhiteTeam permission: {e}")
        return False


async def check_white_team(interaction: discord.Interaction) -> bool:
    """Check if user is member of WhiteTeam (inject graders)."""
    has_permission = await is_white_team_async(interaction)
    if not has_permission:
        await interaction.response.send_message(
            "❌ White Team permissions required.\n\n"
            "You need the `WCComps_WhiteTeam` or `WCComps_GoldTeam` Authentik group.\n"
            "If you have this group, link your account with `/link`.",
            ephemeral=True,
        )
    return has_permission


async def is_orange_team_async(interaction: discord.Interaction) -> bool:
    """Check if user is member of OrangeTeam via Authentik groups."""
    if await is_admin_async(interaction):
        return True
    if await is_gold_team_async(interaction):
        return True

    try:
        authentik_groups = await get_authentik_groups_async(interaction.user.id)
        return "WCComps_OrangeTeam" in authentik_groups
    except Exception as e:
        logger.exception(f"Failed to check Authentik groups for OrangeTeam permission: {e}")
        return False


async def check_orange_team(interaction: discord.Interaction) -> bool:
    """Check if user is member of OrangeTeam (scoring adjustments)."""
    has_permission = await is_orange_team_async(interaction)
    if not has_permission:
        await interaction.response.send_message(
            "❌ Orange Team permissions required.\n\n"
            "You need the `WCComps_OrangeTeam` or `WCComps_GoldTeam` Authentik group.\n"
            "If you have this group, link your account with `/link`.",
            ephemeral=True,
        )
    return has_permission


async def is_blue_team_async(interaction: discord.Interaction) -> bool:
    """Check if user is linked to a Blue Team."""
    try:
        from asgiref.sync import sync_to_async

        discord_link = await sync_to_async(
            lambda: DiscordLink.objects.filter(discord_id=interaction.user.id, is_active=True, team__isnull=False)
            .select_related("team")
            .first()
        )()
        return discord_link is not None and discord_link.team is not None
    except Exception as e:
        logger.exception(f"Failed to check Blue Team membership: {e}")
        return False


async def check_blue_team(interaction: discord.Interaction) -> bool:
    """Check if user is linked to a Blue Team."""
    has_permission = await is_blue_team_async(interaction)
    if not has_permission:
        await interaction.response.send_message(
            "❌ Blue Team membership required.\n\n"
            "You must be linked to a competition team to use this command.\n"
            "Use `/link` to connect your Discord account to your team.",
            ephemeral=True,
        )
    return has_permission
