"""
Security tests for file upload functionality - ACTUAL bugs only.

Based on threat model analysis in THREAT_MODEL_ANALYSIS.md:
- Files stored in PostgreSQL as BLOBs
- Content-Disposition: attachment (forces download, prevents execution)
- No static file serving

REAL vulnerabilities:
1. Client-side path traversal (filename not sanitized)
2. Null byte injection
3. Authorization bypass (cross-team access)
4. Race conditions in concurrent uploads

NOT vulnerabilities (security theater):
- File extensions (.exe, .sh) - Server doesn't execute files
- MIME types - Content-Disposition: attachment prevents execution
- SVG with JavaScript - Not executed when downloaded
"""

import threading
from unittest.mock import Mock, patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from team.models import Team
from ticketing.models import Ticket, TicketAttachment
from web.core.views import ticket_attachment_download, ticket_attachment_upload


@pytest.mark.django_db
class TestFileUploadRealVulnerabilities:
    """Test ACTUAL security vulnerabilities, not security theater."""

    @pytest.fixture
    def setup_data(self):
        """Create test team and ticket."""
        team = Team.objects.create(
            team_number=1,
            team_name="Test Team",
            authentik_group="WCComps_BlueTeam1",
        )
        ticket = Ticket.objects.create(
            ticket_number="T001-001",
            team=team,
            category="other",
            title="Test Ticket",
            status="open",
        )
        return team, ticket

    def test_filename_path_traversal_sanitized(self, setup_data):
        """
        REAL BUG: Client-side path traversal.

        Attack: Upload file named "../../../.bashrc"
        Impact: User's browser writes file outside Downloads folder
        Fix: os.path.basename() strips path components
        """
        team, ticket = setup_data

        malicious_filename = "../../../etc/passwd"
        uploaded_file = SimpleUploadedFile(
            name=malicious_filename,
            content=b"test content",
            content_type="text/plain",
        )

        factory = RequestFactory()
        request = factory.post(
            f"/tickets/{ticket.id}/upload",
            {"attachment": uploaded_file},
        )
        request.user = Mock()
        request.user.is_authenticated = True

        with patch("web.core.views.get_authentik_data", return_value=("testuser", ["WCComps_BlueTeam1"], None)):
            response = ticket_attachment_upload(request, ticket.id)

        # Should succeed and sanitize filename
        assert response.status_code == 302  # Redirect on success

        attachment = TicketAttachment.objects.get(ticket=ticket)

        # CRITICAL: Filename must not contain path traversal
        assert ".." not in attachment.filename, f"Path traversal not sanitized: {attachment.filename}"
        assert "/" not in attachment.filename, f"Path separator not removed: {attachment.filename}"
        assert "\\" not in attachment.filename, f"Windows path separator not removed: {attachment.filename}"

        # Should be just the basename
        assert attachment.filename == "passwd", f"Expected 'passwd', got: {attachment.filename}"

    def test_filename_null_byte_sanitized(self, setup_data):
        """
        REAL BUG: Null byte injection.

        Attack: "file.pdf\x00.exe" could bypass checks
        Fix: Remove null bytes from filename
        """
        team, ticket = setup_data

        malicious_filename = "document.pdf\x00.exe"
        uploaded_file = SimpleUploadedFile(
            name=malicious_filename,
            content=b"test content",
        )

        factory = RequestFactory()
        request = factory.post(f"/tickets/{ticket.id}/upload", {"attachment": uploaded_file})
        request.user = Mock()
        request.user.is_authenticated = True

        with patch("web.core.views.get_authentik_data", return_value=("testuser", ["WCComps_BlueTeam1"], None)):
            response = ticket_attachment_upload(request, ticket.id)

        assert response.status_code == 302

        attachment = TicketAttachment.objects.get(ticket=ticket)
        assert "\x00" not in attachment.filename, "Null bytes should be removed"

    def test_file_size_limit_enforced(self, setup_data):
        """
        REAL CONSTRAINT: File size limit (10MB).

        This is a real resource limit, not security theater.
        """
        team, ticket = setup_data

        # Create 11MB file
        large_content = b"A" * (11 * 1024 * 1024)
        uploaded_file = SimpleUploadedFile(
            name="large.txt",
            content=large_content,
        )

        factory = RequestFactory()
        request = factory.post(f"/tickets/{ticket.id}/upload", {"attachment": uploaded_file})
        request.user = Mock()
        request.user.is_authenticated = True

        with patch("web.core.views.get_authentik_data", return_value=("testuser", ["WCComps_BlueTeam1"], None)):
            response = ticket_attachment_upload(request, ticket.id)

        # Should be rejected
        assert response.status_code == 400
        assert b"too large" in response.content.lower() or b"size" in response.content.lower()


@pytest.mark.django_db
class TestFileUploadAuthorizationBypass:
    """Test cross-team access (REAL security concern)."""

    @pytest.fixture
    def setup_teams(self):
        """Create two teams with tickets."""
        team1 = Team.objects.create(
            team_number=1,
            team_name="Team 1",
            authentik_group="WCComps_BlueTeam1",
        )
        team2 = Team.objects.create(
            team_number=2,
            team_name="Team 2",
            authentik_group="WCComps_BlueTeam2",
        )

        ticket1 = Ticket.objects.create(
            ticket_number="T001-001",
            team=team1,
            category="other",
            title="Team 1 Ticket",
        )
        ticket2 = Ticket.objects.create(
            ticket_number="T002-001",
            team=team2,
            category="other",
            title="Team 2 Ticket",
        )

        attachment1 = TicketAttachment.objects.create(
            ticket=ticket1,
            filename="team1_secret.txt",
            file_data=b"Team 1 secret data",
            mime_type="text/plain",
            uploaded_by="team1user",
        )

        return team1, team2, ticket1, ticket2, attachment1

    def test_cannot_download_other_team_attachment(self, setup_teams):
        """
        REAL BUG: Authorization bypass (IDOR).

        Attack: Team 2 user tries to download Team 1's attachment
        Expected: Access denied
        """
        team1, team2, ticket1, ticket2, attachment1 = setup_teams

        factory = RequestFactory()
        request = factory.get(f"/tickets/{ticket1.id}/attachments/{attachment1.id}")
        request.user = Mock()
        request.user.is_authenticated = True

        # Team 2 user trying to access Team 1's file
        with patch("web.core.views.get_authentik_data", return_value=("team2user", ["WCComps_BlueTeam2"], None)):
            response = ticket_attachment_download(request, ticket1.id, attachment1.id)

        # CRITICAL: Should be denied
        assert response.status_code in [403, 404], (
            f"AUTHORIZATION BUG: Team 2 accessed Team 1's file! Status: {response.status_code}"
        )

    def test_cannot_upload_to_other_team_ticket(self, setup_teams):
        """
        REAL BUG: Authorization bypass.

        Attack: Team 2 user tries to upload to Team 1's ticket
        Expected: Access denied
        """
        team1, team2, ticket1, ticket2, attachment1 = setup_teams

        uploaded_file = SimpleUploadedFile(
            name="malicious.txt",
            content=b"trying to upload to wrong team",
        )

        factory = RequestFactory()
        request = factory.post(
            f"/tickets/{ticket1.id}/upload",  # Team 1's ticket
            {"attachment": uploaded_file},
        )
        request.user = Mock()
        request.user.is_authenticated = True

        # Team 2 user
        with patch("web.core.views.get_authentik_data", return_value=("team2user", ["WCComps_BlueTeam2"], None)):
            response = ticket_attachment_upload(request, ticket1.id)

        # Should be denied
        assert response.status_code in [403, 404], f"Cross-team upload allowed! Status: {response.status_code}"

        # File should NOT be saved
        assert not TicketAttachment.objects.filter(ticket=ticket1, filename="malicious.txt").exists()


@pytest.mark.django_db
class TestFileUploadRaceConditions:
    """Test concurrent uploads (potential race conditions)."""

    @pytest.fixture
    def setup_data(self):
        """Create test team and ticket."""
        team = Team.objects.create(
            team_number=1,
            team_name="Test Team",
            authentik_group="WCComps_BlueTeam1",
        )
        ticket = Ticket.objects.create(
            ticket_number="T001-001",
            team=team,
            category="other",
            title="Test Ticket",
        )
        return team, ticket

    def test_concurrent_uploads_maintain_count(self, setup_data):
        """
        REAL BUG POTENTIAL: Race conditions in concurrent uploads.

        Property: If 5 uploads succeed, should have exactly 5 attachments.
        """
        team, ticket = setup_data
        results = []

        def upload_file(file_num):
            """Upload a file in a thread."""
            uploaded_file = SimpleUploadedFile(
                name=f"file_{file_num}.txt",
                content=f"content {file_num}".encode(),
            )

            factory = RequestFactory()
            request = factory.post(
                f"/tickets/{ticket.id}/upload",
                {"attachment": uploaded_file},
            )
            request.user = Mock()
            request.user.is_authenticated = True

            with patch("web.core.views.get_authentik_data", return_value=(f"user{file_num}", ["WCComps_BlueTeam1"], None)):
                response = ticket_attachment_upload(request, ticket.id)
                results.append(response.status_code)

        # Upload 5 files concurrently
        threads = []
        for i in range(5):
            thread = threading.Thread(target=upload_file, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # All uploads should succeed
        assert all(status == 302 for status in results), f"Some uploads failed: {results}"

        # CRITICAL: Should have exactly 5 attachments
        attachment_count = TicketAttachment.objects.filter(ticket=ticket).count()
        assert attachment_count == 5, (
            f"Race condition detected! Expected 5 attachments, got {attachment_count}"
        )
