"""
Simplified Authentik-only authorization utilities.
"""

from collections.abc import Callable
from typing import Any

from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.models import AnonymousUser, User
from django.http import HttpRequest


def get_authentik_groups(user: User | AnonymousUser) -> list[str]:
    """
    Get user's Authentik groups directly from their SocialAccount.
    This is the single source of truth - no Django flags needed.
    """
    if isinstance(user, AnonymousUser):
        return []

    try:
        # Get the user's Authentik social account
        social_account = SocialAccount.objects.get(user=user, provider="authentik")
        # Groups can be in userinfo.groups or groups (depends on OAuth flow)
        extra_data = social_account.extra_data
        groups: list[str] = extra_data.get("userinfo", {}).get("groups", []) or extra_data.get("groups", [])
        return groups
    except SocialAccount.DoesNotExist:
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


def has_permission(user: User | AnonymousUser, permission_name: str) -> bool:
    """
    Check if user has a specific permission based on Authentik groups.

    Permission mappings:
    - 'admin' -> WCComps_Discord_Admin
    - 'ticketing_admin' -> WCComps_Ticketing_Admin
    - 'ticketing_support' -> WCComps_Ticketing_Support
    - 'gold_team' -> WCComps_GoldTeam
    - 'blue_team' -> WCComps_BlueTeam* (pattern match)
    - 'white_team' -> WCComps_WhiteTeam
    - 'orange_team' -> WCComps_OrangeTeam
    """
    groups = get_authentik_groups(user)

    # Define permission to group mappings
    permission_map = {
        "admin": lambda g: "WCComps_Discord_Admin" in g,
        "ticketing_admin": lambda g: "WCComps_Ticketing_Admin" in g,
        "ticketing_support": lambda g: "WCComps_Ticketing_Support" in g,
        "gold_team": lambda g: "WCComps_GoldTeam" in g or "WCComps_Discord_Admin" in g,
        "blue_team": lambda g: any(group.startswith("WCComps_BlueTeam") for group in g),
        "white_team": lambda g: "WCComps_WhiteTeam" in g,
        "orange_team": lambda g: "WCComps_OrangeTeam" in g,
    }

    # Check if user has the permission
    if permission_name in permission_map:
        return permission_map[permission_name](groups)

    # Direct group check for any other group name
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
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
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

    def decorator(view_func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view_func)
        def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
            if not request.user.is_authenticated or not has_permission(request.user, permission_name):
                messages.error(request, "You don't have permission to access this page.")
                return redirect("/")
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
