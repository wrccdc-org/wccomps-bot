"""Utility functions for WCComps core functionality."""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from team.models import MAX_TEAMS, Team


def parse_datetime_to_utc(datetime_str: str, tz_name: str = "America/Los_Angeles") -> datetime:
    """Parse ISO 8601 datetime string and convert to UTC.

    Args:
        datetime_str: Datetime in format YYYY-MM-DDTHH:MM (ISO 8601 without seconds)
        tz_name: IANA timezone name (default: America/Los_Angeles)

    Returns:
        datetime object in UTC

    Raises:
        ValueError: If datetime_str is not in expected format
    """
    dt = datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M")
    local_time = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, tzinfo=ZoneInfo(tz_name))
    return local_time.astimezone(ZoneInfo("UTC"))


def ndjson_progress(step: str, current: int, total: int, ok: bool = True) -> str:
    """Encode a single progress line as newline-delimited JSON.

    Used by streaming views to report operation progress to the frontend.
    """
    import json

    return json.dumps({"step": step, "current": current, "total": total, "ok": ok}) + "\n"


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
            if 1 <= team_number <= MAX_TEAMS:
                try:
                    team = Team.objects.get(team_number=team_number)
                    return team, team_number, True
                except Team.DoesNotExist:
                    pass

    return None, None, False
