"""Utility functions for WCComps core functionality."""

import re

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.models import User

from team.models import Team


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
