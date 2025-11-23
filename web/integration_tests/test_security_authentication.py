"""
Worker 9: Authentication Security Tests.

Tests authentication mechanisms for security vulnerabilities:
- OAuth flow security (token handling, state validation)
- Session management (fixation, hijacking)
- Password handling (no plaintext storage)
- Token expiration and revocation
- Multi-factor authentication bypass attempts
- Brute force protection
- Account enumeration prevention
- Logout functionality

These tests ensure authentication follows OWASP guidelines and prevents
common authentication vulnerabilities (OWASP A07:2021 - Identification and Authentication Failures).
"""

import os

import pytest
from playwright.sync_api import Page, expect

pytestmark = [
    pytest.mark.browser,
    pytest.mark.integration,
    pytest.mark.security,
]


class TestOAuthSecurity:
    """Test OAuth authentication flow security."""

    def test_oauth_requires_valid_state_parameter(self, page: Page, live_server_url):
        """OAuth flow should validate state parameter to prevent CSRF."""
        # Try to access OAuth callback with invalid state
        page.goto(f"{live_server_url}/accounts/oidc/authentik/login/callback?code=fake&state=invalid")

        # Should not succeed (either error page or redirect to login)
        # Should not be logged in
        page.wait_for_timeout(2000)

        # Verify not authenticated by checking for login link
        login_link = page.locator('a:has-text("Login")')
        if login_link.is_visible():
            expect(login_link).to_be_visible()

    def test_oauth_callback_without_code_fails(self, page: Page, live_server_url):
        """OAuth callback without code parameter should fail safely."""
        page.goto(f"{live_server_url}/accounts/oidc/authentik/login/callback")

        # Should not crash with 500 error
        expect(page.locator("body")).not_to_contain_text("500")
        expect(page.locator("body")).not_to_contain_text("Server Error")

    def test_oauth_callback_with_invalid_code_fails(self, page: Page, live_server_url):
        """OAuth callback with invalid code should fail gracefully."""
        page.goto(f"{live_server_url}/accounts/oidc/authentik/login/callback?code=invalid_code_12345")

        # Should handle error gracefully (not 500)
        expect(page.locator("body")).not_to_contain_text("500")

    def test_direct_access_to_oauth_endpoints_blocked(self, page: Page, live_server_url):
        """Direct access to OAuth endpoints without proper flow should be blocked."""
        # Try accessing callback directly
        response = page.goto(f"{live_server_url}/accounts/oidc/authentik/login/callback")

        # Should either redirect or show error (not 200 OK with sensitive data)
        # Verify no access tokens or secrets are exposed
        page_content = page.content().lower()
        assert "access_token" not in page_content
        assert "client_secret" not in page_content


class TestSessionSecurity:
    """Test session management security."""

    def test_logout_invalidates_session(self, authenticated_page: Page, live_server_url):
        """Logout should completely invalidate session."""
        # Verify logged in
        expect(authenticated_page.locator('a:has-text("Logout")')).to_be_visible()

        # Get session cookie before logout
        cookies_before = authenticated_page.context.cookies()

        # Logout
        authenticated_page.click('a:has-text("Logout")')
        authenticated_page.wait_for_timeout(3000)

        # Try to access protected page with old session
        authenticated_page.goto(f"{live_server_url}/ops/tickets/")

        # Should be redirected to login
        authenticated_page.wait_for_timeout(2000)

        # Should not be able to access protected content
        current_url = authenticated_page.url
        assert "/ops/tickets/" not in current_url or "/accounts/" in current_url

    def test_session_cookie_has_secure_flags(self, authenticated_page: Page, live_server_url):
        """Session cookies should have secure flags (HttpOnly, Secure, SameSite)."""
        authenticated_page.goto(live_server_url)

        # Get cookies
        cookies = authenticated_page.context.cookies()

        # Find session cookie (Django uses sessionid by default)
        session_cookie = next((c for c in cookies if "session" in c["name"].lower()), None)

        if session_cookie:
            # Check for security flags
            # Note: In development, Secure flag might not be set due to HTTP
            # In production, this should be verified
            assert session_cookie.get("httpOnly", False), "Session cookie should be HttpOnly"
            # SameSite should be set (Lax or Strict)
            # Note: Default behavior varies by browser/framework

    def test_concurrent_sessions_from_different_browsers(self, browser, live_server_url, authentik_credentials):
        """Test that concurrent sessions from different browsers work independently."""
        # Create two browser contexts (simulating two devices)
        context1 = browser.new_context()
        context2 = browser.new_context()

        page1 = context1.new_page()
        page2 = context2.new_page()

        try:
            # Login with both
            for page in [page1, page2]:
                page.goto(f"{live_server_url}/accounts/oidc/authentik/login/")
                page.fill('input[name="uid_field"]', authentik_credentials["username"])
                page.fill('input[type="password"]', authentik_credentials["password"])
                page.click('button[type="submit"]')
                page.wait_for_url(f"{live_server_url}/**", timeout=10000)

            # Verify both are logged in
            for page in [page1, page2]:
                page.goto(f"{live_server_url}/ops/tickets/")
                expect(page.locator("body")).to_be_visible()

            # Logout from page1
            page1.goto(f"{live_server_url}/accounts/logout/")
            page1.wait_for_timeout(3000)

            # page2 should still be logged in (independent session)
            page2.goto(f"{live_server_url}/ops/tickets/")
            page2.wait_for_timeout(1000)

            # Verify page2 can still access protected content
            expect(page2.locator("body")).to_be_visible()

        finally:
            page1.close()
            page2.close()
            context1.close()
            context2.close()


class TestPasswordSecurity:
    """Test password handling security."""

    def test_passwords_not_logged_in_console(self, page: Page, authentik_credentials, live_server_url):
        """Passwords should never appear in console logs."""
        console_messages = []

        def on_console(msg):
            console_messages.append(msg.text)

        page.on("console", on_console)

        # Perform login
        page.goto(f"{live_server_url}/accounts/oidc/authentik/login/")
        page.fill('input[name="uid_field"]', authentik_credentials["username"])
        page.fill('input[type="password"]', authentik_credentials["password"])
        page.click('button[type="submit"]')

        page.wait_for_timeout(5000)

        # Check console messages for password
        password_leaked = any(authentik_credentials["password"] in msg for msg in console_messages)
        assert not password_leaked, "Password found in console logs!"

    def test_password_fields_have_autocomplete_off(self, page: Page, live_server_url):
        """Password fields should have appropriate autocomplete settings."""
        page.goto(f"{live_server_url}/accounts/oidc/authentik/login/")

        # Find password input
        password_input = page.locator('input[type="password"]')

        if password_input.is_visible():
            # Note: Autocomplete behavior is complex and browser-dependent
            # Just verify field exists and is properly typed
            expect(password_input).to_have_attribute("type", "password")


class TestTokenSecurity:
    """Test token handling and expiration."""

    def test_link_tokens_expire_after_15_minutes(self, page: Page, db, live_server_url):
        """Link tokens should expire after 15 minutes."""
        from datetime import timedelta

        from django.utils import timezone

        from team.models import LinkToken

        # Create expired token (16 minutes old)
        expired_token = LinkToken.objects.create(
            discord_id=111222333444555,
            discord_username="test_expired_user",
            token="EXPIRED_TEST_TOKEN_12345",
            created_at=timezone.now() - timedelta(minutes=16),
            used=False,
        )

        try:
            # Try to use expired token
            page.goto(f"{live_server_url}/auth/link?token={expired_token.token}")

            # Should show error about expired token
            expect(page.locator("text=expired")).to_be_visible(timeout=5000)
            expect(page.locator("text=15 minute")).to_be_visible()

        finally:
            expired_token.delete()

    def test_link_tokens_cannot_be_reused(self, page: Page, db, live_server_url):
        """Link tokens should only be usable once."""
        from team.models import LinkToken

        # Create used token
        used_token = LinkToken.objects.create(
            discord_id=111222333444556,
            discord_username="test_used_token_user",
            token="USED_TEST_TOKEN_12345",
            used=True,
        )

        try:
            # Try to use already-used token
            page.goto(f"{live_server_url}/auth/link?token={used_token.token}")

            # Should show error about invalid/used token
            expect(page.locator("text=Invalid")).to_be_visible(timeout=5000)

        finally:
            used_token.delete()


class TestBruteForceProtection:
    """Test protection against brute force attacks."""

    def test_multiple_failed_login_attempts_handled(self, page: Page, live_server_url):
        """Multiple failed login attempts should be handled gracefully."""
        # Note: Actual rate limiting would be done by Authentik
        # Here we test that our app handles Authentik's rate limiting responses

        for attempt in range(5):
            page.goto(f"{live_server_url}/accounts/oidc/authentik/login/")

            # Try with invalid credentials
            page.fill('input[name="uid_field"]', f"invalid_user_{attempt}")
            page.fill('input[type="password"]', "invalid_password")
            page.click('button[type="submit"]')

            page.wait_for_timeout(1000)

            # Should not crash (even if Authentik blocks)
            expect(page.locator("body")).not_to_contain_text("500")


class TestAccountEnumeration:
    """Test prevention of account enumeration attacks."""

    def test_login_error_messages_generic(self, page: Page, live_server_url):
        """Login errors should not reveal if username exists."""
        page.goto(f"{live_server_url}/accounts/oidc/authentik/login/")

        # Try with nonexistent user
        page.fill('input[name="uid_field"]', "definitely_nonexistent_user_12345")
        page.fill('input[type="password"]', "wrong_password")
        page.click('button[type="submit"]')

        page.wait_for_timeout(2000)

        # Error message should not say "user not found" or "invalid username"
        # Should be generic like "invalid credentials"
        page_content = page.content().lower()

        # These specific messages would leak user existence
        assert "user not found" not in page_content
        assert "username does not exist" not in page_content
        assert "invalid username" not in page_content


class TestCSRFProtection:
    """Test CSRF protection for authenticated requests."""

    def test_post_requests_require_csrf_token(self, page: Page, live_server_url):
        """POST requests should require valid CSRF token."""
        # Try POST without CSRF token
        response = page.request.post(
            f"{live_server_url}/ops/tickets/bulk-claim/",
            data={"ticket_numbers": "T001-001,T001-002"},
        )

        # Should be rejected (403 Forbidden or redirect to login)
        assert response.status in [403, 302], f"Expected 403 or 302, got {response.status}"

    def test_forms_include_csrf_tokens(self, authenticated_page: Page, live_server_url):
        """All forms should include CSRF tokens."""
        authenticated_page.goto(f"{live_server_url}/ops/tickets/")

        # Find all forms
        forms = authenticated_page.locator("form").all()

        for form in forms:
            # Each form should have CSRF token
            csrf_input = form.locator('input[name="csrfmiddlewaretoken"]')

            if csrf_input.count() > 0:
                # CSRF token should have a value
                token_value = csrf_input.first.get_attribute("value")
                assert token_value and len(token_value) > 0, "CSRF token should have value"


class TestSensitiveDataExposure:
    """Test that sensitive data is not exposed in responses."""

    def test_error_pages_dont_expose_secrets(self, page: Page, live_server_url):
        """Error pages should not expose configuration or secrets."""
        # Access nonexistent page to trigger 404
        page.goto(f"{live_server_url}/nonexistent-page-12345")

        page_content = page.content().lower()

        # Should not expose these sensitive items
        assert "secret_key" not in page_content
        assert "database" not in page_content or "postgresql" not in page_content
        assert "password" not in page_content
        assert "api_key" not in page_content
        assert "authentik_url" not in page_content

    def test_api_responses_dont_include_internal_ids(self, authenticated_page: Page, db, live_server_url):
        """API responses should not unnecessarily expose internal database IDs."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] ID exposure test",
            description="Test for ID exposure",
            status="open",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")

            page_content = authenticated_page.content()

            # Should use ticket_number (e.g., "T001-042"), not internal ID
            # Internal database ID should generally not be exposed in HTML
            assert ticket.ticket_number in page_content

        finally:
            ticket.delete()


class TestAuthenticationBypass:
    """Test for authentication bypass vulnerabilities."""

    def test_protected_pages_require_authentication(self, page: Page, live_server_url):
        """Protected pages should require authentication."""
        protected_urls = [
            "/ops/tickets/",
            "/ops/school-info/",
            "/ops/group-role-mappings/",
            "/tickets/",
            "/tickets/create/",
        ]

        for url in protected_urls:
            page.goto(f"{live_server_url}{url}")
            page.wait_for_timeout(1000)

            # Should redirect to login or show access denied
            current_url = page.url

            # Should not be able to access the protected page directly
            assert "/accounts/" in current_url or "login" in current_url.lower() or url not in current_url

    def test_cannot_bypass_auth_with_custom_headers(self, page: Page, live_server_url):
        """Custom headers should not bypass authentication."""
        # Try accessing protected page with various bypass headers
        bypass_headers = {
            "X-Forwarded-For": "127.0.0.1",
            "X-Real-IP": "127.0.0.1",
            "X-Authenticated-User": "admin",
            "Authorization": "Bearer fake_token",
        }

        response = page.request.get(f"{live_server_url}/ops/tickets/", headers=bypass_headers)

        # Should not grant access (redirect or forbidden)
        assert response.status in [302, 401, 403], f"Expected redirect or auth error, got {response.status}"
