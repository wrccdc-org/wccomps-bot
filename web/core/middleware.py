"""Middleware to enforce Authentik authentication on all pages."""

from typing import Callable
from django.shortcuts import redirect
from django.http import HttpRequest, HttpResponse


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
        ]

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Skip if path is whitelisted
        for path in self.whitelist:
            if request.path.startswith(path):
                return self.get_response(request)

        # Require authentication for all other paths
        if not request.user.is_authenticated:
            # Redirect to Authentik login
            return redirect(f"/accounts/oidc/authentik/login/?next={request.path}")

        return self.get_response(request)
