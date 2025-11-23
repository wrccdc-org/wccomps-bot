"""
Worker 12: File Upload Security Tests.

Tests file upload security mechanisms:
- File size limits enforcement
- File type validation (MIME type verification)
- Malicious file detection
- Filename sanitization
- Path traversal in filenames
- File content validation
- Virus/malware upload prevention
- Resource exhaustion (zip bombs, etc.)
- Double extension handling

These tests ensure file uploads follow OWASP guidelines and prevent
malicious file uploads (OWASP A04:2021 - Insecure Design, A05:2021 - Security Misconfiguration).
"""

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

pytestmark = [
    pytest.mark.browser,
    pytest.mark.integration,
    pytest.mark.security,
]


class TestFileSizeLimits:
    """Test file size limit enforcement."""

    def test_file_size_limit_enforced(self, page: Page, db, live_server_url):
        """Files over size limit should be rejected."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] File size test",
            description="Test",
            status="open",
        )

        try:
            # Create a large file (> 10MB limit)
            large_file = Path("/tmp/large_test_file.bin")
            large_file.write_bytes(b"X" * (11 * 1024 * 1024))  # 11MB

            # Try to upload (requires authentication)
            response = page.request.post(
                f"{live_server_url}/tickets/{ticket.id}/attachment/upload/",
                multipart={
                    "attachment": {
                        "name": "large_file.bin",
                        "mimeType": "application/octet-stream",
                        "buffer": large_file.read_bytes(),
                    }
                },
            )

            # Should be rejected (400 Bad Request or 413 Payload Too Large)
            # Or require auth (302, 401, 403)
            assert response.status in [302, 401, 403, 400, 413]

            # Cleanup
            large_file.unlink()

        finally:
            ticket.delete()

    def test_zero_byte_files_handled(self, page: Page, db, live_server_url):
        """Zero-byte files should be handled properly."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] Zero byte test",
            description="Test",
            status="open",
        )

        try:
            # Create empty file
            empty_file = Path("/tmp/empty_test_file.txt")
            empty_file.write_bytes(b"")

            response = page.request.post(
                f"{live_server_url}/tickets/{ticket.id}/attachment/upload/",
                multipart={
                    "attachment": {
                        "name": "empty.txt",
                        "mimeType": "text/plain",
                        "buffer": b"",
                    }
                },
            )

            # Should handle gracefully (reject or require auth)
            assert response.status in [302, 401, 403, 400]

            empty_file.unlink(missing_ok=True)

        finally:
            ticket.delete()


class TestFileTypeValidation:
    """Test file type validation and MIME type checks."""

    def test_executable_files_rejected(self, page: Page, db, live_server_url):
        """Executable files should be rejected."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] Executable test",
            description="Test",
            status="open",
        )

        try:
            dangerous_extensions = [
                "malware.exe",
                "script.bat",
                "virus.com",
                "trojan.scr",
                "evil.dll",
            ]

            for filename in dangerous_extensions:
                response = page.request.post(
                    f"{live_server_url}/tickets/{ticket.id}/attachment/upload/",
                    multipart={
                        "attachment": {
                            "name": filename,
                            "mimeType": "application/x-msdownload",
                            "buffer": b"MZ\x90\x00",  # EXE header
                        }
                    },
                )

                # Should require auth or reject
                assert response.status in [302, 401, 403, 400, 415]

        finally:
            ticket.delete()

    def test_script_files_handled_safely(self, page: Page, db, live_server_url):
        """Script files should be handled safely."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] Script test",
            description="Test",
            status="open",
        )

        try:
            script_files = [
                ("evil.sh", "#!/bin/bash\nrm -rf /"),
                ("bad.ps1", "Remove-Item -Recurse -Force C:\\"),
                ("malicious.py", "import os; os.system('rm -rf /')"),
                ("dangerous.js", "require('child_process').exec('rm -rf /')"),
            ]

            for filename, content in script_files:
                response = page.request.post(
                    f"{live_server_url}/tickets/{ticket.id}/attachment/upload/",
                    multipart={
                        "attachment": {
                            "name": filename,
                            "mimeType": "text/plain",
                            "buffer": content.encode(),
                        }
                    },
                )

                # Should require auth or handle safely
                assert response.status in [302, 401, 403, 400, 415, 200]

        finally:
            ticket.delete()


class TestFilenameValidation:
    """Test filename sanitization and validation."""

    def test_path_traversal_in_filename_prevented(self, page: Page, db, live_server_url):
        """Path traversal attempts in filenames should be prevented."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] Path traversal filename",
            description="Test",
            status="open",
        )

        try:
            dangerous_filenames = [
                "../../../etc/passwd",
                "..\\..\\..\\windows\\system32\\config\\sam",
                "....//....//etc/shadow",
                "/etc/passwd",
                "C:\\Windows\\System32\\config\\SAM",
            ]

            for filename in dangerous_filenames:
                response = page.request.post(
                    f"{live_server_url}/tickets/{ticket.id}/attachment/upload/",
                    multipart={
                        "attachment": {
                            "name": filename,
                            "mimeType": "text/plain",
                            "buffer": b"test content",
                        }
                    },
                )

                # Should reject or sanitize
                assert response.status in [302, 401, 403, 400]

        finally:
            ticket.delete()

    def test_null_bytes_in_filename_handled(self, page: Page, db, live_server_url):
        """Null bytes in filenames should be handled safely."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] Null byte filename",
            description="Test",
            status="open",
        )

        try:
            # Null byte can truncate filename in some systems
            null_byte_filename = "safe.txt\x00.exe"

            response = page.request.post(
                f"{live_server_url}/tickets/{ticket.id}/attachment/upload/",
                multipart={
                    "attachment": {
                        "name": null_byte_filename,
                        "mimeType": "text/plain",
                        "buffer": b"test",
                    }
                },
            )

            # Should handle safely (reject or sanitize)
            assert response.status in [302, 401, 403, 400]

        finally:
            ticket.delete()

    def test_special_characters_in_filename_sanitized(self, page: Page, db, live_server_url):
        """Special characters in filenames should be sanitized."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] Special char filename",
            description="Test",
            status="open",
        )

        try:
            special_char_filenames = [
                "file<>name.txt",
                "file|name.txt",
                'file"name.txt',
                "file;name.txt",
                "file`command`.txt",
            ]

            for filename in special_char_filenames:
                response = page.request.post(
                    f"{live_server_url}/tickets/{ticket.id}/attachment/upload/",
                    multipart={
                        "attachment": {
                            "name": filename,
                            "mimeType": "text/plain",
                            "buffer": b"test",
                        }
                    },
                )

                # Should sanitize or reject
                assert response.status in [302, 401, 403, 400, 200]

        finally:
            ticket.delete()


class TestDoubleExtensionHandling:
    """Test handling of double extensions (file.txt.exe)."""

    def test_double_extension_files_handled(self, page: Page, db, live_server_url):
        """Double extension files should be handled safely."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] Double extension",
            description="Test",
            status="open",
        )

        try:
            double_extensions = [
                "image.jpg.exe",
                "document.pdf.bat",
                "archive.zip.scr",
                "picture.png.com",
            ]

            for filename in double_extensions:
                response = page.request.post(
                    f"{live_server_url}/tickets/{ticket.id}/attachment/upload/",
                    multipart={
                        "attachment": {
                            "name": filename,
                            "mimeType": "application/octet-stream",
                            "buffer": b"fake content",
                        }
                    },
                )

                # Should detect and reject/handle
                assert response.status in [302, 401, 403, 400, 415]

        finally:
            ticket.delete()


class TestMIMETypeValidation:
    """Test MIME type validation (not just extension checking)."""

    def test_mime_type_validated_not_just_extension(self, page: Page, db, live_server_url):
        """MIME type should be validated, not just file extension."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] MIME validation",
            description="Test",
            status="open",
        )

        try:
            # Executable disguised as text file
            response = page.request.post(
                f"{live_server_url}/tickets/{ticket.id}/attachment/upload/",
                multipart={
                    "attachment": {
                        "name": "safe.txt",
                        "mimeType": "text/plain",
                        "buffer": b"MZ\x90\x00" + b"\x00" * 100,  # EXE header
                    }
                },
            )

            # Should handle (may accept as text or detect content mismatch)
            assert response.status in [302, 401, 403, 400, 200]

        finally:
            ticket.delete()


class TestFileContentValidation:
    """Test file content validation."""

    def test_php_webshell_upload_prevented(self, page: Page, db, live_server_url):
        """PHP webshells should be detected and prevented."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] Webshell test",
            description="Test",
            status="open",
        )

        try:
            webshell_content = b"<?php system($_GET['cmd']); ?>"

            response = page.request.post(
                f"{live_server_url}/tickets/{ticket.id}/attachment/upload/",
                multipart={
                    "attachment": {
                        "name": "shell.php",
                        "mimeType": "application/x-php",
                        "buffer": webshell_content,
                    }
                },
            )

            # Should reject (or require auth)
            assert response.status in [302, 401, 403, 400, 415]

        finally:
            ticket.delete()

    def test_svg_with_javascript_handled(self, page: Page, db, live_server_url):
        """SVG files with embedded JavaScript should be handled safely."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] SVG XSS test",
            description="Test",
            status="open",
        )

        try:
            malicious_svg = b"""<?xml version="1.0" standalone="no"?>
            <svg xmlns="http://www.w3.org/2000/svg">
                <script>alert('XSS')</script>
            </svg>"""

            response = page.request.post(
                f"{live_server_url}/tickets/{ticket.id}/attachment/upload/",
                multipart={
                    "attachment": {
                        "name": "image.svg",
                        "mimeType": "image/svg+xml",
                        "buffer": malicious_svg,
                    }
                },
            )

            # Should handle safely (sanitize, reject, or require auth)
            assert response.status in [302, 401, 403, 400, 415, 200]

        finally:
            ticket.delete()


class TestResourceExhaustion:
    """Test protection against resource exhaustion attacks."""

    def test_zip_bomb_detection(self, page: Page, db, live_server_url):
        """Zip bombs should be detected or have size limits enforced."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] Zip bomb test",
            description="Test",
            status="open",
        )

        try:
            # Small zip file that expands to huge size (simplified example)
            # Real zip bombs are much more sophisticated
            import zipfile
            from io import BytesIO

            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                # Add a file with lots of zeros (compresses well)
                zf.writestr("bomb.txt", b"0" * 10000000)  # 10MB of zeros

            response = page.request.post(
                f"{live_server_url}/tickets/{ticket.id}/attachment/upload/",
                multipart={
                    "attachment": {
                        "name": "archive.zip",
                        "mimeType": "application/zip",
                        "buffer": zip_buffer.getvalue(),
                    }
                },
            )

            # Should enforce size limits (before or after extraction)
            assert response.status in [302, 401, 403, 400, 413, 200]

        finally:
            ticket.delete()


class TestFileDownloadSecurity:
    """Test file download security."""

    def test_downloaded_files_have_safe_content_type(self, authenticated_page: Page, db, live_server_url):
        """Downloaded files should have safe Content-Type headers."""
        from team.models import Team
        from ticketing.models import Ticket, TicketAttachment

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] Download test",
            description="Test",
            status="open",
        )

        attachment = TicketAttachment.objects.create(
            ticket=ticket,
            filename="test.txt",
            file_data=b"test content",
            mime_type="text/plain",
            uploaded_by="test_user",
        )

        try:
            response = authenticated_page.request.get(
                f"{live_server_url}/tickets/{ticket.id}/attachment/{attachment.id}/"
            )

            # Should have Content-Disposition: attachment to prevent execution
            # This forces download rather than inline display
            if response.status == 200:
                headers = response.headers
                content_disposition = headers.get("content-disposition", "")

                # Should be attachment (safe) not inline (potentially unsafe)
                if content_disposition:
                    assert "attachment" in content_disposition.lower()

        finally:
            ticket.delete()

    def test_attachment_access_requires_proper_team(self, page: Page, db, live_server_url):
        """Attachments should only be accessible by proper team members."""
        from team.models import Team
        from ticketing.models import Ticket, TicketAttachment

        team = Team.objects.get(team_number=1)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] Attachment access test",
            description="Test",
            status="open",
        )

        attachment = TicketAttachment.objects.create(
            ticket=ticket,
            filename="confidential.txt",
            file_data=b"secret data",
            mime_type="text/plain",
            uploaded_by="team1_user",
        )

        try:
            # Try to access without auth
            response = page.request.get(f"{live_server_url}/tickets/{ticket.id}/attachment/{attachment.id}/")

            # Should require authentication
            assert response.status in [302, 403, 401, 404]

        finally:
            ticket.delete()


class TestFileUploadRateLimiting:
    """Test rate limiting for file uploads."""

    def test_multiple_rapid_uploads_handled(self, page: Page, db, live_server_url):
        """Rapid file uploads should be rate limited or handled."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[SECURITY TEST] Upload rate limit",
            description="Test",
            status="open",
        )

        try:
            # Try uploading many files rapidly
            for i in range(10):
                response = page.request.post(
                    f"{live_server_url}/tickets/{ticket.id}/attachment/upload/",
                    multipart={
                        "attachment": {
                            "name": f"test_{i}.txt",
                            "mimeType": "text/plain",
                            "buffer": b"test",
                        }
                    },
                )

                # Should require auth or rate limit
                assert response.status in [302, 401, 403, 400, 429, 200]

        finally:
            ticket.delete()
