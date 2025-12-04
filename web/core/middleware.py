"""Middleware to enforce Authentik authentication on all pages."""

from collections.abc import Callable
from urllib.parse import quote

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


class AuthentikRequiredMiddleware:
    """Require Authentik login for all pages except OAuth flow and Discord linking."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

        # Paths that don't require authentication
        self.whitelist = [
            "/accounts/",  # Allauth OAuth endpoints
            "/static/",  # Static files
            "/auth/link",  # Discord linking entry point (redirects to OAuth)
            "/health/",  # Health check endpoint for monitoring
            "/register/",  # Public registration form
        ]

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Skip if path is whitelisted
        for path in self.whitelist:
            if request.path.startswith(path):
                return self.get_response(request)

        # Require authentication for all other paths
        if not request.user.is_authenticated:
            # Validate and sanitize the next parameter to prevent open redirect
            next_url = request.path
            if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                next_url = "/"
            safe_next = quote(next_url, safe="")
            return redirect(f"/accounts/oidc/authentik/login/?next={safe_next}")

        return self.get_response(request)
