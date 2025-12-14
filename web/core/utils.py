"""Utility functions for WCComps core functionality."""

import re

from team.models import Team


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
