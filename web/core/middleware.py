"""Middleware to enforce Authentik authentication on all pages."""

import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from django.db import connection
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

logger = logging.getLogger("wccomps.access")
error_logger = logging.getLogger("wccomps.errors")


class SecurityHeadersMiddleware:
    """Add security headers to all responses."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)

        # Content-Security-Policy
        if "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
                "https://unpkg.com https://static.cloudflareinsights.com; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "font-src 'self'; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "form-action 'self'; "
                "base-uri 'self'"
            )

        return response


class SubdomainRedirectMiddleware:
    """Redirect subdomain root paths to their corresponding app paths."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response
        self.subdomain_redirects = {
            "register.wccomps.org": "/register/",
        }

    def __call__(self, request: HttpRequest) -> HttpResponse:
        host = request.get_host().split(":")[0]
        if request.path == "/" and host in self.subdomain_redirects:
            return redirect(self.subdomain_redirects[host])
        return self.get_response(request)


class AuthentikRequiredMiddleware:
    """Require Authentik login for all pages except OAuth flow and Discord linking."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

        # Prefix paths that don't require authentication
        self.whitelist_prefixes = [
            "/static/",  # Static files
        ]
        # Exact paths
        self.whitelist_exact = [
            "/health/",  # Health check endpoint for monitoring
            "/register/",  # Public registration form
            "/auth/login/",  # OAuth login initiation
            "/auth/callback/",  # OAuth callback
            "/auth/logout/",  # Logout
            "/auth/link",  # Discord account linking (token-based)
        ]
        # Startswith for token-based public pages
        self.whitelist_startswith = [
            "/register/edit/",  # Token-based registration editing
        ]

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Skip if path is whitelisted
        for prefix in self.whitelist_prefixes:
            if request.path.startswith(prefix):
                return self.get_response(request)
        if request.path in self.whitelist_exact:
            return self.get_response(request)
        for prefix in self.whitelist_startswith:
            if request.path.startswith(prefix):
                return self.get_response(request)

        # Require authentication for all other paths
        if not request.user.is_authenticated:
            # Validate and sanitize the next parameter to prevent open redirect
            next_url = request.path
            if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                next_url = "/"
            safe_next = quote(next_url, safe="")
            return redirect(f"/auth/login/?next={safe_next}")

        # Django admin requires Authentik admin permission
        if request.path.startswith("/admin/"):
            from .auth_utils import has_permission

            if not has_permission(request.user, "admin"):
                return HttpResponse("Forbidden", status=403)

        return self.get_response(request)


class QueryTracker:
    """Tracks database queries during a request.

    Implements Django's _ExecuteWrapper protocol from django-stubs.
    """

    def __init__(self) -> None:
        self.queries: list[float] = []  # durations in ms

    # Signature matches Django's _ExecuteWrapper type alias which uses Any
    def __call__(  # type: ignore[explicit-any]
        self,
        execute: Callable[[str, Any, bool, dict[str, Any]], Any],
        sql: str,
        params: Any,
        many: bool,
        context: dict[str, Any],
    ) -> Any:
        start = time.time()
        result = execute(sql, params, many, context)
        self.queries.append((time.time() - start) * 1000)
        return result


class AccessLoggingMiddleware:
    """Log all requests with username, response status, and query metrics."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Skip static files
        if request.path.startswith("/static/"):
            return self.get_response(request)

        start_time = time.time()
        tracker = QueryTracker()

        try:
            with connection.execute_wrapper(tracker):
                response = self.get_response(request)
        except Exception:
            duration_ms = (time.time() - start_time) * 1000
            username = request.user.username if request.user.is_authenticated else "-"
            error_logger.error(
                '%s %s %s "%s %s" 500 %.0fms (unhandled exception)',
                request.META.get("REMOTE_ADDR", "-"),
                username,
                request.META.get("HTTP_HOST", "-"),
                request.method,
                request.path,
                duration_ms,
                exc_info=True,
            )
            raise

        duration_ms = (time.time() - start_time) * 1000
        username = request.user.username if request.user.is_authenticated else "-"

        # Log with query stats: [query_count, total_db_time_ms]
        log_msg = '%s %s %s "%s %s" %d %.0fms [%dq %.0fms]'
        log_args = (
            request.META.get("REMOTE_ADDR", "-"),
            username,
            request.META.get("HTTP_HOST", "-"),
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            len(tracker.queries),
            sum(tracker.queries),
        )
        logger.info(log_msg, *log_args)

        if response.status_code >= 500:
            error_logger.error(log_msg, *log_args)

        return response
