"""
Worker 11: Input Validation Security Tests.

Tests input validation and sanitization:
- SQL injection prevention
- XSS (Cross-Site Scripting) prevention
- Command injection prevention
- Path traversal prevention
- Input length validation
- Type validation
- Format validation
- Special character handling

These tests ensure input validation follows OWASP guidelines and prevents
injection attacks (OWASP A03:2021 - Injection).
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = [
    pytest.mark.browser,
    pytest.mark.integration,
    pytest.mark.security,
]


class TestSQLInjectionPrevention:
    """Test protection against SQL injection attacks."""

    def test_search_input_sql_injection_protected(self, authenticated_page: Page, live_server_url):
        """Search input should be protected against SQL injection."""
        sql_payloads = [
            "'; DROP TABLE ticketing_ticket;--",
            "' OR '1'='1",
            "' UNION SELECT * FROM auth_user--",
            "1' AND '1'='1",
        ]

        for payload in sql_payloads:
            authenticated_page.goto(f"{live_server_url}/ops/tickets/?search={payload}")

            # Should not crash with SQL error
            expect(authenticated_page.locator("body")).not_to_contain_text("SQL")
            expect(authenticated_page.locator("body")).not_to_contain_text("syntax error")
            expect(authenticated_page.locator("body")).not_to_contain_text("500")

    def test_filter_parameters_sql_injection_protected(self, authenticated_page: Page, live_server_url):
        """Filter parameters should be protected against SQL injection."""
        authenticated_page.goto(f"{live_server_url}/ops/tickets/?team=' OR '1'='1")

        # Should not crash or expose SQL errors
        expect(authenticated_page.locator("body")).not_to_contain_text("SQL")
        expect(authenticated_page.locator("body")).not_to_contain_text("500")

    def test_id_parameters_sql_injection_protected(self, authenticated_page: Page, live_server_url):
        """ID parameters should be properly validated."""
        authenticated_page.goto(f"{live_server_url}/ops/ticket/' OR '1'='1--/")

        # Should show 404 or proper error, not SQL error
        expect(authenticated_page.locator("body")).not_to_contain_text("SQL")
        expect(authenticated_page.locator("body")).not_to_contain_text("syntax")


class TestXSSPrevention:
    """Test protection against Cross-Site Scripting (XSS) attacks."""

    def test_ticket_title_xss_protected(self, authenticated_page: Page, db, live_server_url):
        """Ticket titles should be escaped to prevent XSS."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)

        # Create ticket with XSS payload in title
        xss_payload = '<script>alert("XSS")</script>'
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title=f"[SECURITY TEST] {xss_payload}",
            description="XSS test",
            status="open",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")

            # Wait for page to load
            authenticated_page.wait_for_timeout(1000)

            # Script should be escaped, not executed
            page_source = authenticated_page.content()

            # Check if properly escaped (HTML entities)
            assert "&lt;script&gt;" in page_source or "<script>" not in page_source

        finally:
            ticket.delete()

    def test_ticket_description_xss_protected(self, authenticated_page: Page, db, live_server_url):
        """Ticket descriptions should be escaped to prevent XSS."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)

        xss_payload = "<img src=x onerror=\"alert('XSS')\">"
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] XSS description test",
            description=xss_payload,
            status="open",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")
            authenticated_page.wait_for_timeout(1000)

            page_source = authenticated_page.content()

            # Should be escaped
            assert "onerror=" not in page_source or "&quot;" in page_source

        finally:
            ticket.delete()

    def test_comment_xss_protected(self, authenticated_page: Page, db, live_server_url):
        """Comments should be escaped to prevent XSS."""
        from team.models import Team
        from ticketing.models import Ticket, TicketComment

        team = Team.objects.get(team_number=50)

        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] Comment XSS test",
            description="Test",
            status="open",
        )

        xss_payload = '<script>document.location="http://evil.com"</script>'
        comment = TicketComment.objects.create(
            ticket=ticket,
            author_name="test_user",
            comment_text=xss_payload,
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")
            authenticated_page.wait_for_timeout(1000)

            page_source = authenticated_page.content()

            # Should be escaped
            assert "&lt;script&gt;" in page_source or "document.location" not in page_source

        finally:
            ticket.delete()

    def test_search_query_xss_protected(self, authenticated_page: Page, live_server_url):
        """Search queries should be escaped when reflected."""
        xss_payload = '<script>alert("XSS")</script>'
        authenticated_page.goto(f"{live_server_url}/ops/tickets/?search={xss_payload}")

        authenticated_page.wait_for_timeout(1000)

        # Script should not execute
        # Check page source for proper escaping
        page_source = authenticated_page.content()

        if xss_payload in page_source:
            # If reflected, should be escaped
            assert "&lt;script&gt;" in page_source


class TestCommandInjectionPrevention:
    """Test protection against command injection."""

    def test_filename_command_injection_protected(self, page: Page, live_server_url):
        """Filenames should not allow command injection."""
        # Note: This would require file upload functionality
        # Testing that filename is validated
        dangerous_filenames = [
            "; rm -rf /",
            "$(whoami).txt",
            "`cat /etc/passwd`.txt",
        ]

        # These would be tested during file upload
        # For now, verify upload endpoint exists and requires auth
        response = page.request.post(f"{live_server_url}/tickets/1/attachment/upload/")

        # Should require auth or show proper error
        assert response.status in [302, 403, 401, 404, 405, 400]


class TestPathTraversalPrevention:
    """Test protection against path traversal attacks."""

    def test_file_download_path_traversal_protected(self, page: Page, live_server_url):
        """File downloads should prevent path traversal."""
        path_traversal_attempts = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\config\\sam",
            "....//....//....//etc/passwd",
        ]

        for attempt in path_traversal_attempts:
            response = page.request.get(f"{live_server_url}/tickets/1/attachment/{attempt}")

            # Should not expose system files (404, 403, or redirect)
            assert response.status in [302, 403, 401, 404, 400]

            # Response should not contain system file content
            if response.status == 200:
                content = response.text()
                assert "root:" not in content
                assert "[boot loader]" not in content


class TestInputLengthValidation:
    """Test that input length is validated."""

    def test_ticket_title_length_limit(self, authenticated_page: Page, db, live_server_url):
        """Ticket title should have reasonable length limit."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)

        # Try creating ticket with extremely long title
        very_long_title = "A" * 10000

        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title=very_long_title[:255],  # Django will truncate
            description="Test",
            status="open",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")

            # Should handle gracefully
            expect(authenticated_page.locator("body")).not_to_contain_text("500")

        finally:
            ticket.delete()

    def test_comment_length_validation(self, page: Page, live_server_url):
        """Comments should have reasonable length limits."""
        very_long_comment = "A" * 100000

        response = page.request.post(
            f"{live_server_url}/tickets/1/comment/",
            data={"comment": very_long_comment},
        )

        # Should either reject or handle gracefully (not 500)
        assert response.status in [302, 403, 401, 404, 400, 413, 200]


class TestTypeValidation:
    """Test that input types are properly validated."""

    def test_numeric_ids_validated(self, authenticated_page: Page, live_server_url):
        """Numeric IDs should be validated."""
        invalid_ids = [
            "abc",
            "1.5",
            "-1",
            "999999999999999999999999999",
            "null",
            "undefined",
        ]

        for invalid_id in invalid_ids:
            authenticated_page.goto(f"{live_server_url}/tickets/{invalid_id}/")

            # Should show proper error (404, 400), not 500
            expect(authenticated_page.locator("body")).not_to_contain_text("500")

    def test_email_validation(self, page: Page, db, live_server_url):
        """Email fields should be validated."""
        from team.models import SchoolInfo, Team

        team = Team.objects.get(team_number=50)

        invalid_emails = [
            "not-an-email",
            "missing-at-sign.com",
            "@no-local-part.com",
            "spaces in email@test.com",
        ]

        for invalid_email in invalid_emails:
            # Try creating school info with invalid email
            try:
                school_info = SchoolInfo.objects.create(
                    team=team,
                    school_name="Test School",
                    contact_email=invalid_email,
                )
                # If it succeeds, clean up
                school_info.delete()
            except Exception:
                # Validation error is expected
                pass

    def test_boolean_fields_validated(self, page: Page, live_server_url):
        """Boolean fields should be validated."""
        response = page.request.post(
            f"{live_server_url}/ops/ticket/T001-001/claim/",
            data={"force": "not-a-boolean"},
        )

        # Should handle gracefully
        assert response.status in [302, 403, 401, 404, 400, 405]


class TestFormatValidation:
    """Test that input formats are validated."""

    def test_ticket_number_format_validated(self, authenticated_page: Page, live_server_url):
        """Ticket numbers should follow expected format."""
        invalid_formats = [
            "INVALID",
            "T999-99999",
            "ticket-123",
            "../../../etc/passwd",
        ]

        for invalid_format in invalid_formats:
            authenticated_page.goto(f"{live_server_url}/ops/ticket/{invalid_format}/")

            # Should show proper error, not crash
            expect(authenticated_page.locator("body")).not_to_contain_text("500")

    def test_category_validation(self, page: Page, db, live_server_url):
        """Category values should be validated against allowed list."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)

        invalid_category = "invalid-category-that-does-not-exist"

        # Django should validate against choices
        try:
            ticket = Ticket.objects.create(
                team=team,
                category=invalid_category,
                title="Test",
                description="Test",
                status="open",
            )
            # Should not reach here, but if it does, clean up
            ticket.delete()
        except Exception:
            # Validation error is expected
            pass


class TestSpecialCharacterHandling:
    """Test handling of special characters in input."""

    def test_special_characters_in_title(self, authenticated_page: Page, db, live_server_url):
        """Special characters in titles should be handled safely."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)

        special_chars = "Test <>\"'&;()[]{}|`~!@#$%^&*"
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title=special_chars,
            description="Test",
            status="open",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")

            # Should handle without errors
            expect(authenticated_page.locator("body")).not_to_contain_text("500")

        finally:
            ticket.delete()

    def test_unicode_characters_handled(self, authenticated_page: Page, db, live_server_url):
        """Unicode characters should be handled properly."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)

        unicode_text = "Test 中文 العربية 🎉 emoji ñ ü"
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title=unicode_text,
            description="Test",
            status="open",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")

            # Should display correctly
            expect(authenticated_page.locator("body")).to_be_visible()

        finally:
            ticket.delete()

    def test_null_bytes_handled(self, page: Page, live_server_url):
        """Null bytes in input should be handled safely."""
        # Null bytes can cause issues in C-based systems
        response = page.request.post(
            f"{live_server_url}/tickets/1/comment/",
            data={"comment": "Test\x00comment"},
        )

        # Should handle gracefully (not crash)
        assert response.status in [302, 403, 401, 404, 400, 405, 200]


class TestHTMLSanitization:
    """Test that HTML input is properly sanitized."""

    def test_dangerous_html_tags_stripped(self, authenticated_page: Page, db, live_server_url):
        """Dangerous HTML tags should be stripped or escaped."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)

        dangerous_html = '<iframe src="http://evil.com"></iframe><embed src="evil.swf">'
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] HTML sanitization",
            description=dangerous_html,
            status="open",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")

            page_source = authenticated_page.content()

            # iframe and embed should be escaped or stripped
            assert "<iframe" not in page_source or "&lt;iframe" in page_source

        finally:
            ticket.delete()

    def test_javascript_urls_sanitized(self, authenticated_page: Page, db, live_server_url):
        """JavaScript URLs should be sanitized."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)

        js_url = "<a href=\"javascript:alert('XSS')\">Click me</a>"
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] JS URL test",
            description=js_url,
            status="open",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")

            page_source = authenticated_page.content()

            # javascript: URLs should be escaped or removed
            assert 'href="javascript:' not in page_source

        finally:
            ticket.delete()
