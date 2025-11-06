"""Utility functions for WCComps core functionality."""

from typing import Optional, Any, TYPE_CHECKING
from django.contrib.auth.models import User
from allauth.socialaccount.models import SocialAccount, SocialLogin
import re

if TYPE_CHECKING:
    from team.models import Team


def get_authentik_data(user: User) -> tuple[str, list[str], Optional[str]]:
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
        groups = extra_data.get("userinfo", {}).get("groups", []) or extra_data.get(
            "groups", []
        )

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
    groups: list[str] = extra_data.get("userinfo", {}).get(
        "groups", []
    ) or extra_data.get("groups", [])
    return groups


def get_team_from_groups(
    groups: list[str],
) -> tuple[Optional["Team"], Optional[int], bool]:
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
    from team.models import Team

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


def check_permissions(user: User, groups: list[str]) -> dict[str, bool]:
    """
    Check user permissions based on Django flags and Authentik groups.

    Args:
        user: Django User instance
        groups: List of Authentik group names

    Returns:
        dict: Dictionary with permission flags
            - is_admin: Django staff/superuser status
            - is_ticketing_admin: Has ticketing admin group
            - is_ticketing_support: Has ticketing support group
            - is_gold_team: Has GoldTeam group
    """
    return {
        "is_admin": user.is_staff or user.is_superuser,
        "is_ticketing_admin": "WCComps_Ticketing_Admin" in groups,
        "is_ticketing_support": "WCComps_Ticketing_Support" in groups,
        "is_gold_team": "WCComps_GoldTeam" in groups
        or user.is_staff
        or user.is_superuser,
    }
