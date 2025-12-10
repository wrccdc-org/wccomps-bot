"""Utility functions for WCComps core functionality."""

import re

from django.contrib.auth.models import User

from core.models import UserGroups
from team.models import Team


def get_authentik_data(user: User) -> tuple[str, list[str], str | None]:
    """
    Extract Authentik username, groups, and user ID from a Django user.

    Args:
        user: Django User instance

    Returns:
        tuple: (username, groups, authentik_user_id)
            - username: Django username (synced from Authentik on login)
            - groups: List of Authentik group names from UserGroups
            - authentik_user_id: Authentik UID from UserGroups or None
    """
    try:
        user_groups = user.usergroups
        return user.username, user_groups.groups, user_groups.authentik_id
    except UserGroups.DoesNotExist:
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
