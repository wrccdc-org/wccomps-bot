"""Context processors for making data available to all templates."""

from django.contrib.auth.models import User
from django.http import HttpRequest

from .auth_utils import get_permissions_context
from .utils import get_authentik_data


def permissions(request: HttpRequest) -> dict[str, bool | str]:
    """Add permission flags to all template contexts."""
    if not request.user.is_authenticated:
        return {
            "is_ticketing_admin": False,
            "is_ticketing_support": False,
            "is_gold_team": False,
            "is_blue_team": False,
            "is_red_team": False,
            "is_white_team": False,
            "is_orange_team": False,
            "is_admin": False,
            "authentik_username": "",
        }

    user: User = request.user

    # Get Authentik data
    authentik_username, _groups, _ = get_authentik_data(user)

    # Get permissions
    perms = get_permissions_context(user)

    # Check team membership via person
    is_blue_team = False
    is_red_team = False
    if hasattr(user, "person"):
        is_blue_team = user.person.is_blue_team()
        is_red_team = user.person.is_red_team()

    return {
        **perms,
        "is_blue_team": is_blue_team,
        "is_red_team": is_red_team,
        "authentik_username": authentik_username,
    }
