"""Signals for auto-promoting Authentik users to Django staff/superuser."""

from typing import Any
from django.dispatch import receiver
from django.http import HttpRequest
from allauth.socialaccount.signals import pre_social_login
from allauth.socialaccount.models import SocialLogin
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from .utils import get_authentik_data_from_sociallogin
import logging

logger = logging.getLogger(__name__)


@receiver(pre_social_login)
def promote_authentik_admins(
    sender: Any, request: HttpRequest, sociallogin: SocialLogin, **kwargs: Any
) -> None:
    """
    Automatically set Django permissions based on Authentik group membership.

    Groups:
    - WCComps_Discord_Admin: Full superuser access to everything
    - WCComps_Ticketing_Admin: Staff access to ticket management in Django admin
    - WCComps_Ticketing_Support: Can use Discord commands only (no web admin)

    This allows Authentik to be the single source of truth for permissions.
    """
    # Only process Authentik logins
    if sociallogin.account.provider != "authentik":
        return

    # Get user's groups from Authentik
    groups = get_authentik_data_from_sociallogin(sociallogin)

    # Check group membership
    is_discord_admin = "WCComps_Discord_Admin" in groups
    is_ticketing_admin = "WCComps_Ticketing_Admin" in groups
    is_ticketing_support = "WCComps_Ticketing_Support" in groups

    # Get or create the Django user
    user = sociallogin.user

    # Update permissions based on group membership
    if is_discord_admin:
        # Full superuser access
        if not user.is_staff or not user.is_superuser:
            user.is_staff = True
            user.is_superuser = True
            user.save()
            logger.info(
                f"Promoted {user.username} to superuser (WCComps_Discord_Admin)"
            )
    elif is_ticketing_admin:
        # Staff access with ticket permissions
        if not user.is_staff:
            user.is_staff = True
            user.is_superuser = False
            user.save()

            # Grant permissions for ticket models
            from core.models import (
                Ticket,
                TicketComment,
                TicketHistory,
                DiscordTask,
            )

            ticket_models = [
                Ticket,
                TicketComment,
                TicketHistory,
                DiscordTask,
            ]
            for model in ticket_models:
                content_type = ContentType.objects.get_for_model(model)
                perms = Permission.objects.filter(content_type=content_type)
                user.user_permissions.add(*perms)

            logger.info(
                f"Promoted {user.username} to staff with ticket permissions (WCComps_Ticketing_Admin)"
            )
    elif is_ticketing_support:
        # No web access, Discord commands only
        if user.is_staff or user.is_superuser:
            user.is_staff = False
            user.is_superuser = False
            user.user_permissions.clear()
            user.save()
            logger.info(
                f"Set {user.username} to support (Discord only, WCComps_Ticketing_Support)"
            )
    else:
        # No admin groups - remove permissions
        if user.is_staff or user.is_superuser:
            user.is_staff = False
            user.is_superuser = False
            user.user_permissions.clear()
            user.save()
            logger.info(f"Removed admin access from {user.username} (no admin groups)")
