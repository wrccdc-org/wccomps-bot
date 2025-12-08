"""
Simplified Authentik-only authorization utilities.
"""

from collections.abc import Callable
from typing import Concatenate, ParamSpec, TypeAlias

from django.contrib.auth.models import AnonymousUser, User
from django.http import HttpRequest, HttpResponse

from .models import UserGroups

P = ParamSpec("P")
ViewFunc: TypeAlias = Callable[Concatenate[HttpRequest, P], HttpResponse]


def get_authentik_groups(user: User | AnonymousUser) -> list[str]:
    """
    Get user's Authentik groups from UserGroups model.
    This is the single source of truth for permissions.
    """
    if isinstance(user, AnonymousUser):
        return []

    try:
        return list(user.usergroups.groups)
    except UserGroups.DoesNotExist:
        return []


def get_permissions_context(user: User) -> dict[str, bool]:
    """
    Get permissions dict for template context.

    Returns dict with all permission flags for use in templates.
    """
    return {
        "is_admin": has_permission(user, "admin"),
        "is_ticketing_admin": has_permission(user, "ticketing_admin"),
        "is_ticketing_support": has_permission(user, "ticketing_support"),
        "is_gold_team": has_permission(user, "gold_team"),
        "is_white_team": has_permission(user, "white_team"),
        "is_orange_team": has_permission(user, "orange_team"),
    }


PERMISSION_MAP: dict[str, list[str]] = {
    "admin": ["WCComps_Discord_Admin"],
    "ticketing_admin": ["WCComps_Ticketing_Admin"],
    "ticketing_support": ["WCComps_Ticketing_Support"],
    "gold_team": ["WCComps_GoldTeam", "WCComps_Discord_Admin"],
    "white_team": ["WCComps_WhiteTeam"],
    "orange_team": ["WCComps_OrangeTeam"],
    "helper_eligible": ["WCComps_Ticketing_Support", "WCComps_Quotient_Injects"],
}


def has_permission(user: User | AnonymousUser, permission_name: str) -> bool:
    """
    Check if user has a specific permission based on Authentik groups.

    Uses SocialAccount as source of truth.
    """
    groups = get_authentik_groups(user)
    return check_groups_for_permission(groups, permission_name)


def check_groups_for_permission(groups: list[str], permission_name: str) -> bool:
    """
    Check if a list of groups grants a permission.

    Can be used with groups from UserGroups.groups.
    """
    if permission_name == "blue_team":
        return any(g.startswith("WCComps_BlueTeam") for g in groups)

    if permission_name in PERMISSION_MAP:
        return any(g in groups for g in PERMISSION_MAP[permission_name])

    # Direct group check
    return permission_name in groups


def get_user_team_number(user: User) -> int | None:
    """
    Get user's team number from their Authentik group.
    Returns None if user is not on a team.
    """
    groups = get_authentik_groups(user)

    # Check for BlueTeam pattern
    import re

    for group in groups:
        match = re.match(r"WCComps_BlueTeam(\d+)", group)
        if match:
            return int(match.group(1))

    return None


def require_permission(
    permission_name: str,
) -> Callable[[ViewFunc[P]], ViewFunc[P]]:
    """
    Decorator to require a specific permission for a view.

    Usage:
        @require_permission('ticketing_admin')
        def my_view(request):
            ...
    """
    from functools import wraps

    from django.contrib import messages
    from django.shortcuts import redirect

    def decorator(view_func: ViewFunc[P]) -> ViewFunc[P]:
        @wraps(view_func)
        def wrapped(request: HttpRequest, *args: P.args, **kwargs: P.kwargs) -> HttpResponse:
            if not request.user.is_authenticated or not has_permission(request.user, permission_name):
                messages.error(request, "You don't have permission to access this page.")
                return redirect("/")
            return view_func(request, *args, **kwargs)

        return wrapped  # type: ignore[return-value]

    return decorator
