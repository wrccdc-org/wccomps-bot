"""Utility functions for WCComps core functionality."""

import re
from dataclasses import dataclass
from typing import Any

from allauth.socialaccount.models import SocialAccount, SocialLogin
from django.contrib.auth.models import User

from team.models import Team


@dataclass
class AuthentikContext:
    """Context object containing Authentik user information.

    Provides a structured way to access Authentik user data throughout the application.

    Attributes:
        username: The Authentik preferred username
        groups: List of Authentik group names the user belongs to
        user_id: The Authentik user ID (sub claim), or None if not available
    """

    username: str
    groups: list[str]
    user_id: str | None


def get_authentik_context(user: User) -> AuthentikContext:
    """
    Get a structured AuthentikContext object for a user.

    Args:
        user: Django User instance

    Returns:
        AuthentikContext containing the user's Authentik data
    """
    username, groups, user_id = get_authentik_data(user)
    return AuthentikContext(username=username, groups=groups, user_id=user_id)


def get_authentik_data(user: User) -> tuple[str, list[str], str | None]:
    """
    Extract Authentik username, groups, and user ID from a Django user.

    Args:
        user: Django User instance

    Returns:
        tuple: (username, groups, authentik_user_id)
            - username: Authentik preferred_username or Django username as fallback
            - groups: List of Authentik group names
            - authentik_user_id: Authentik UID or None
    """
    try:
        social_account = SocialAccount.objects.get(user=user, provider="authentik")
        extra_data = social_account.extra_data

        # Extract username from various possible locations
        username = (
            extra_data.get("userinfo", {}).get("preferred_username")
            or extra_data.get("preferred_username")
            or extra_data.get("username")
            or extra_data.get("email")
            or user.username
        )

        # Extract groups (can be in userinfo.groups or groups)
        groups = extra_data.get("userinfo", {}).get("groups", []) or extra_data.get("groups", [])

        return username, groups, social_account.uid

    except SocialAccount.DoesNotExist:
        return user.username, [], None


def get_authentik_data_from_sociallogin(sociallogin: SocialLogin) -> list[str]:
    """
    Extract groups from a sociallogin object (used in signals).

    Args:
        sociallogin: Allauth sociallogin instance

    Returns:
        list: List of Authentik group names
    """
    extra_data: dict[str, Any] = sociallogin.account.extra_data
    groups: list[str] = extra_data.get("userinfo", {}).get("groups", []) or extra_data.get("groups", [])
    return groups


def get_team_from_groups(
    groups: list[str],
) -> tuple[Team | None, int | None, bool]:
    """
    Extract team information from Authentik groups.

    Args:
        groups: List of Authentik group names

    Returns:
        tuple: (team, team_number, is_team_account)
            - team: Team model instance or None
            - team_number: Team number (1-50) or None
            - is_team_account: Boolean indicating if user is in a team group
    """

    for group in groups:
        team_match = re.match(r"^WCComps_BlueTeam(\d+)$", group)
        if team_match:
            team_number = int(team_match.group(1))
            if 1 <= team_number <= 50:
                try:
                    team = Team.objects.get(team_number=team_number)
                    return team, team_number, True
                except Team.DoesNotExist:
                    pass

    return None, None, False


def get_discord_identity(authentik_user_id: str | None, authentik_username: str) -> tuple[int | None, str | None]:
    """
    Get Discord identity from DiscordLink.

    Looks up the Discord user ID and username associated with an Authentik account.
    For blue teams (shared Authentik accounts), this may return the first active link.

    Args:
        authentik_user_id: The Authentik user ID (preferred lookup)
        authentik_username: The Authentik username (fallback lookup)

    Returns:
        tuple: (discord_id, discord_username) or (None, None) if not found
    """
    from team.models import DiscordLink

    try:
        if authentik_user_id:
            link = DiscordLink.objects.filter(authentik_user_id=authentik_user_id, is_active=True).first()
        else:
            link = DiscordLink.objects.filter(authentik_username=authentik_username, is_active=True).first()

        if link:
            return link.discord_id, link.discord_username
        return None, None
    except Exception:
        return None, None
