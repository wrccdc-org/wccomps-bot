"""Custom OAuth views for Authentik OIDC authentication."""

import logging
import secrets
from datetime import UTC
from urllib.parse import urlencode

import httpx
from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .auth_utils import check_groups_for_permission
from .models import UserGroups

logger = logging.getLogger(__name__)

# OAuth state expiry in seconds (5 minutes)
STATE_EXPIRY_SECONDS = 300


def _get_oauth_config() -> dict[str, str]:
    """Get OAuth configuration from settings."""
    client_id = getattr(settings, "AUTHENTIK_CLIENT_ID", None)
    client_secret = getattr(settings, "AUTHENTIK_SECRET", None)
    server_url = getattr(
        settings,
        "AUTHENTIK_OIDC_URL",
        "https://auth.wccomps.org/application/o/discord-bot/",
    )

    # Authentik uses shared endpoints (not per-application)
    # The application slug is only in the issuer and end-session URLs
    base_url = server_url.rstrip("/")
    auth_base = base_url.rsplit("/", 1)[0]  # Remove application slug
    return {
        "client_id": client_id or "",
        "client_secret": client_secret or "",
        "authorization_endpoint": f"{auth_base}/authorize/",
        "token_endpoint": f"{auth_base}/token/",
        "userinfo_endpoint": f"{auth_base}/userinfo/",
        "end_session_endpoint": f"{base_url}/end-session/",
    }


def oauth_login(request: HttpRequest) -> HttpResponse:
    """Initiate OAuth login flow."""
    config = _get_oauth_config()

    if not config["client_id"]:
        logger.error("AUTHENTIK_CLIENT_ID not configured")
        return render(
            request,
            "core/oauth_error.html",
            {"error_title": "Configuration Error", "error_message": "OAuth is not configured."},
            status=500,
        )

    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    request.session["oauth_state_created"] = timezone.now().isoformat()

    # Store next URL for redirect after login
    next_url = request.GET.get("next", "/")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = "/"
    request.session["oauth_next"] = next_url

    # Build authorization URL
    redirect_uri = request.build_absolute_uri("/auth/callback/")
    params = {
        "client_id": config["client_id"],
        "response_type": "code",
        "scope": "openid profile email groups",
        "redirect_uri": redirect_uri,
        "state": state,
    }

    auth_url = f"{config['authorization_endpoint']}?{urlencode(params)}"
    return redirect(auth_url)


def oauth_callback(request: HttpRequest) -> HttpResponse:
    """Handle OAuth callback from Authentik."""
    config = _get_oauth_config()

    # Check for error response
    error = request.GET.get("error")
    if error:
        error_description = request.GET.get("error_description", "Unknown error")
        if error == "access_denied":
            return render(
                request,
                "core/oauth_error.html",
                {"error_title": "Login Cancelled", "error_message": "You cancelled the login."},
            )
        logger.warning(f"OAuth error: {error} - {error_description}")
        return render(
            request,
            "core/oauth_error.html",
            {"error_title": "Login Failed", "error_message": "Please try again."},
        )

    # Verify state parameter
    state = request.GET.get("state")
    session_state = request.session.get("oauth_state")

    if not state or not session_state:
        logger.warning("OAuth state missing")
        return render(
            request,
            "core/oauth_error.html",
            {"error_title": "Session Expired", "error_message": "Please try again."},
        )

    if not secrets.compare_digest(state, session_state):
        logger.warning("OAuth state mismatch")
        return render(
            request,
            "core/oauth_error.html",
            {"error_title": "Security Error", "error_message": "Please try again."},
        )

    # Check state expiry
    state_created = request.session.get("oauth_state_created")
    if state_created:
        from datetime import datetime

        created_time = datetime.fromisoformat(state_created)
        now = timezone.now()
        if hasattr(created_time, "tzinfo") and created_time.tzinfo is None:
            created_time = created_time.replace(tzinfo=UTC)
        age = (now - created_time).total_seconds()
        if age > STATE_EXPIRY_SECONDS:
            logger.warning(f"OAuth state expired (age: {age}s)")
            return render(
                request,
                "core/oauth_error.html",
                {"error_title": "Session Expired", "error_message": "Please try again."},
            )

    # Clear state (single-use)
    del request.session["oauth_state"]
    if "oauth_state_created" in request.session:
        del request.session["oauth_state_created"]

    # Get authorization code
    code = request.GET.get("code")
    if not code:
        logger.warning("OAuth code missing")
        return render(
            request,
            "core/oauth_error.html",
            {"error_title": "Login Failed", "error_message": "Please try again."},
        )

    # Exchange code for tokens
    redirect_uri = request.build_absolute_uri("/auth/callback/")
    try:
        with httpx.Client(timeout=10.0) as client:
            token_response = client.post(
                config["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "client_id": config["client_id"],
                    "client_secret": config["client_secret"],
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
            token_response.raise_for_status()
            tokens = token_response.json()
    except httpx.HTTPError as e:
        logger.error(f"Token exchange failed: {e}")
        return render(
            request,
            "core/oauth_error.html",
            {"error_title": "Authentication Failed", "error_message": "Please try again."},
        )

    # Fetch userinfo
    access_token = tokens.get("access_token")
    if not access_token:
        logger.error("No access token in response")
        return render(
            request,
            "core/oauth_error.html",
            {"error_title": "Authentication Failed", "error_message": "Please try again."},
        )

    try:
        with httpx.Client(timeout=10.0) as client:
            userinfo_response = client.get(
                config["userinfo_endpoint"],
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_response.raise_for_status()
            userinfo = userinfo_response.json()
    except httpx.HTTPError as e:
        logger.error(f"Userinfo fetch failed: {e}")
        return render(
            request,
            "core/oauth_error.html",
            {"error_title": "Authentication Failed", "error_message": "Please try again."},
        )

    # Extract user data
    authentik_id = userinfo.get("sub")
    username = userinfo.get("preferred_username") or userinfo.get("email", "")
    groups = userinfo.get("groups", [])
    email = userinfo.get("email", "")

    if not authentik_id:
        logger.error("No sub claim in userinfo")
        return render(
            request,
            "core/oauth_error.html",
            {"error_title": "Authentication Failed", "error_message": "Invalid user data."},
        )

    # Find or create user by authentik_id (handles username changes)
    try:
        user_groups = UserGroups.objects.select_related("user").get(authentik_id=authentik_id)
        user = user_groups.user
        # Update username if changed in Authentik
        if user.username != username:
            # Check if another user has this username
            conflicting_user = User.objects.filter(username=username).exclude(pk=user.pk).first()
            if conflicting_user:
                logger.error(
                    f"Username conflict: authentik_id={authentik_id} wants username '{username}' "
                    f"but it's taken by user id={conflicting_user.pk}"
                )
                # Continue with old username rather than crash
            else:
                user.username = username
                user.save(update_fields=["username"])
    except UserGroups.DoesNotExist:
        # Check if user exists with this username (edge case)
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email},
        )
        if not created and email:
            user.email = email
            user.save(update_fields=["email"])
        user_groups = UserGroups.objects.create(
            user=user,
            authentik_id=authentik_id,
            groups=groups,
        )

    # Always update groups on login
    user_groups.groups = groups
    user_groups.save(update_fields=["groups"])

    # Log user in
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    # Get next URL - use role-based default if going to root
    next_url = request.session.pop("oauth_next", "/")
    if next_url == "/":
        next_url = _get_role_based_landing(groups)

    return redirect(next_url)


def _get_role_based_landing(groups: list[str]) -> str:
    """Determine landing page based on user's Authentik groups."""
    from django.urls import reverse

    # Check roles in priority order — admin/ops first, then team-specific portals
    if (
        check_groups_for_permission(groups, "admin")
        or check_groups_for_permission(groups, "ticketing_admin")
        or check_groups_for_permission(groups, "ticketing_support")
    ):
        return reverse("ticket_list")
    if check_groups_for_permission(groups, "gold_team"):
        return reverse("scoring:leaderboard")
    if check_groups_for_permission(groups, "red_team"):
        return reverse("scoring:submit_red_finding")
    if check_groups_for_permission(groups, "orange_team"):
        return reverse("scoring:orange_team_portal")
    if check_groups_for_permission(groups, "blue_team"):
        return reverse("scoring:submit_incident_report")

    return "/"


def oauth_logout(request: HttpRequest) -> HttpResponse:
    """Log out user and redirect to Authentik end session."""
    config = _get_oauth_config()

    # Clear Django session
    logout(request)

    # Redirect to Authentik logout
    redirect_uri = request.build_absolute_uri("/")
    params = {"post_logout_redirect_uri": redirect_uri}
    logout_url = f"{config['end_session_endpoint']}?{urlencode(params)}"

    return redirect(logout_url)
