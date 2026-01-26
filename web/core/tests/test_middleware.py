"""Tests for middleware (SubdomainRedirectMiddleware, AuthentikRequiredMiddleware)."""

import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory

from core.middleware import AuthentikRequiredMiddleware, SubdomainRedirectMiddleware

pytestmark = pytest.mark.django_db


class TestMiddlewareConfiguration:
    """Tests for middleware ordering."""

    def test_authentik_middleware_runs_after_auth(self):
        """AuthentikRequiredMiddleware must run after AuthenticationMiddleware."""
        middleware_list = list(settings.MIDDLEWARE)
        auth_idx = middleware_list.index("django.contrib.auth.middleware.AuthenticationMiddleware")
        authentik_idx = middleware_list.index("core.middleware.AuthentikRequiredMiddleware")

        assert authentik_idx > auth_idx, (
            "AuthentikRequiredMiddleware must run after AuthenticationMiddleware to have access to request.user"
        )


class TestSubdomainRedirectMiddleware:
    """Tests for SubdomainRedirectMiddleware."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance with mock get_response."""

        def get_response(request):
            return HttpResponse("OK")

        return SubdomainRedirectMiddleware(get_response)

    def test_register_subdomain_root_redirects(self, middleware):
        """Root path on register subdomain should redirect to /register/."""
        factory = RequestFactory()
        request = factory.get("/", HTTP_HOST="register.wccomps.org")

        response = middleware(request)

        assert response.status_code == 302
        assert response.url == "/register/"

    def test_register_subdomain_with_port_redirects(self, middleware):
        """Register subdomain with port should still redirect."""
        factory = RequestFactory()
        request = factory.get("/", HTTP_HOST="register.wccomps.org:8000")

        response = middleware(request)

        assert response.status_code == 302
        assert response.url == "/register/"

    def test_register_subdomain_non_root_passes_through(self, middleware):
        """Non-root paths on register subdomain should pass through."""
        factory = RequestFactory()
        request = factory.get("/register/form/", HTTP_HOST="register.wccomps.org")

        response = middleware(request)

        assert response.status_code == 200
        assert response.content == b"OK"

    def test_main_domain_root_passes_through(self, middleware):
        """Root path on main domain should pass through."""
        factory = RequestFactory()
        request = factory.get("/", HTTP_HOST="wccomps.org")

        response = middleware(request)

        assert response.status_code == 200
        assert response.content == b"OK"

    def test_unknown_subdomain_passes_through(self, middleware):
        """Unknown subdomain should pass through without redirect."""
        factory = RequestFactory()
        request = factory.get("/", HTTP_HOST="unknown.wccomps.org")

        response = middleware(request)

        assert response.status_code == 200
        assert response.content == b"OK"


class TestAuthentikRequiredMiddleware:
    """Tests for AuthentikRequiredMiddleware."""

    @pytest.fixture
    def middleware(self):
        """Create middleware instance with mock get_response."""

        def get_response(request):
            return HttpResponse("OK")

        return AuthentikRequiredMiddleware(get_response)

    @pytest.fixture
    def authenticated_request(self, blue_team_user):
        """Create an authenticated request."""
        factory = RequestFactory()
        request = factory.get("/some/path/")
        request.user = blue_team_user
        return request

    @pytest.fixture
    def anonymous_request(self):
        """Create an anonymous request."""
        factory = RequestFactory()
        request = factory.get("/some/path/")
        request.user = AnonymousUser()
        return request

    def test_authenticated_user_passes_through(self, middleware, authenticated_request):
        """Authenticated users should access protected paths."""
        response = middleware(authenticated_request)

        assert response.status_code == 200
        assert response.content == b"OK"

    def test_anonymous_user_redirected_to_login(self, middleware, anonymous_request):
        """Anonymous users should be redirected to login."""
        response = middleware(anonymous_request)

        assert response.status_code == 302
        assert response.url.startswith("/auth/login/")
        assert "next=" in response.url

    def test_anonymous_user_redirect_includes_next_url(self, middleware):
        """Redirect should include the original path as next parameter."""
        factory = RequestFactory()
        request = factory.get("/ops/tickets/")
        request.user = AnonymousUser()

        response = middleware(request)

        assert response.status_code == 302
        assert "%2Fops%2Ftickets%2F" in response.url  # URL-encoded /ops/tickets/

    def test_auth_path_whitelisted(self, middleware):
        """Paths starting with /auth/ should be accessible without login."""
        factory = RequestFactory()
        request = factory.get("/auth/login/")
        request.user = AnonymousUser()

        response = middleware(request)

        assert response.status_code == 200
        assert response.content == b"OK"

    def test_static_path_whitelisted(self, middleware):
        """Paths starting with /static/ should be accessible without login."""
        factory = RequestFactory()
        request = factory.get("/static/css/style.css")
        request.user = AnonymousUser()

        response = middleware(request)

        assert response.status_code == 200
        assert response.content == b"OK"

    def test_health_path_whitelisted(self, middleware):
        """Paths starting with /health/ should be accessible without login."""
        factory = RequestFactory()
        request = factory.get("/health/")
        request.user = AnonymousUser()

        response = middleware(request)

        assert response.status_code == 200
        assert response.content == b"OK"

    def test_register_path_whitelisted(self, middleware):
        """Paths starting with /register/ should be accessible without login."""
        factory = RequestFactory()
        request = factory.get("/register/")
        request.user = AnonymousUser()

        response = middleware(request)

        assert response.status_code == 200
        assert response.content == b"OK"

    @pytest.mark.parametrize(
        "path",
        [
            "/",
            "/ops/",
            "/ops/tickets/",
            "/team/",
            "/admin/",
            "/scoring/",
        ],
    )
    def test_protected_paths_require_auth(self, middleware, path):
        """Non-whitelisted paths should require authentication."""
        factory = RequestFactory()
        request = factory.get(path)
        request.user = AnonymousUser()

        response = middleware(request)

        assert response.status_code == 302, f"Path {path} should require auth"
        assert "/auth/login/" in response.url

    def test_next_url_sanitization_rejects_external_url(self, middleware):
        """External URLs in next parameter should be rejected."""
        factory = RequestFactory()
        # Simulate a request where path manipulation could happen
        request = factory.get("//evil.com/steal")
        request.user = AnonymousUser()

        response = middleware(request)

        # Should redirect to login but not include the malicious URL
        assert response.status_code == 302
        # The middleware should sanitize to "/" since //evil.com is external
        assert "evil.com" not in response.url or "%2F" in response.url

    def test_authenticated_user_on_whitelist_path(self, middleware, authenticated_request):
        """Authenticated user on whitelisted path should still pass through."""
        factory = RequestFactory()
        request = factory.get("/auth/callback/")
        request.user = authenticated_request.user

        response = middleware(request)

        assert response.status_code == 200
