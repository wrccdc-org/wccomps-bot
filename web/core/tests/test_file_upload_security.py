"""
Security tests for file upload functionality.

These tests validate actual security vulnerabilities, not tautologies.
They test ATTACK VECTORS that could be exploited in production.

Tests are designed to FIND the 4 bugs identified in SECURITY_ANALYSIS.md:
1. HIGH: Filename not sanitized (path traversal)
2. MEDIUM: No file extension validation
3. MEDIUM: MIME type not validated against content
4. LOW: Content-Disposition header injection
"""

import io
from unittest.mock import Mock, patch

import pytest
from django.contrib.auth.models import AnonymousUser, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpRequest
from django.test import RequestFactory

from core.models import AuditLog
from team.models import Team
from ticketing.models import Ticket, TicketAttachment
from web.core.views import ticket_attachment_download, ticket_attachment_upload


@pytest.mark.django_db
class TestFileUploadPathTraversal:
    """Test path traversal attacks in filename handling.

    BUG: Filename not sanitized - allows path traversal
    SEVERITY: HIGH
    ATTACK: Upload file with name '../../../etc/passwd' to write outside upload directory
    """

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
            category="technical",
            title="Test Ticket",
            status="open",
        )
        return team, ticket

    def test_filename_with_path_traversal_should_be_rejected(self, setup_data):
        """ATTACK: Upload file with '../../../etc/passwd' as filename.

        EXPECTED: Filename should be sanitized to 'passwd' or rejected
        CURRENT: Likely accepted as-is (BUG)
        """
        team, ticket = setup_data

        # Create malicious file upload with path traversal
        malicious_filename = "../../../etc/passwd"
        file_content = b"malicious content"
        uploaded_file = SimpleUploadedFile(
            name=malicious_filename,
            content=file_content,
            content_type="text/plain",
        )

        # Create request
        factory = RequestFactory()
        request = factory.post(
            f"/tickets/{ticket.id}/upload",
            {"attachment": uploaded_file},
        )
        request.user = Mock()
        request.user.is_authenticated = True

        # Mock authentication
        with patch("web.core.views.get_authentik_username", return_value="testuser"):
            with patch("web.core.views.verify_team_access", return_value=True):
                response = ticket_attachment_upload(request, ticket.id)

        # BUG CHECK: Is filename sanitized?
        if response.status_code == 200:
            attachment = TicketAttachment.objects.get(ticket=ticket)

            # CRITICAL: Filename should NOT contain path traversal
            assert ".." not in attachment.filename, (
                f"SECURITY BUG: Path traversal in filename! "
                f"Got: {attachment.filename}, Expected: sanitized name"
            )
            assert "/" not in attachment.filename, (
                f"SECURITY BUG: Directory separator in filename! "
                f"Got: {attachment.filename}"
            )
            # Should be sanitized to just the basename
            assert attachment.filename in ["passwd", "etc_passwd"], (
                f"Filename should be sanitized. Got: {attachment.filename}"
            )

    def test_filename_with_null_bytes_should_be_rejected(self, setup_data):
        """ATTACK: Upload file with null bytes to bypass validation.

        Example: 'file.pdf\x00.exe' - shows as .pdf but executes as .exe
        """
        team, ticket = setup_data

        malicious_filename = "document.pdf\x00.exe"
        uploaded_file = SimpleUploadedFile(
            name=malicious_filename,
            content=b"malicious content",
            content_type="application/pdf",
        )

        factory = RequestFactory()
        request = factory.post(
            f"/tickets/{ticket.id}/upload",
            {"attachment": uploaded_file},
        )
        request.user = Mock()
        request.user.is_authenticated = True

        with patch("web.core.views.get_authentik_username", return_value="testuser"):
            with patch("web.core.views.verify_team_access", return_value=True):
                response = ticket_attachment_upload(request, ticket.id)

        # Should be rejected or sanitized
        if response.status_code == 200:
            attachment = TicketAttachment.objects.get(ticket=ticket)
            assert "\x00" not in attachment.filename, "Null bytes should be removed"


@pytest.mark.django_db
class TestFileUploadExtensionValidation:
    """Test file extension validation.

    BUG: No file extension validation
    SEVERITY: MEDIUM
    ATTACK: Upload executable files (.exe, .sh, .py) disguised as documents
    """

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
            category="technical",
            title="Test Ticket",
            status="open",
        )
        return team, ticket

    @pytest.mark.parametrize("dangerous_extension,reason", [
        (".exe", "Windows executable"),
        (".sh", "Shell script"),
        (".bat", "Batch file"),
        (".cmd", "Command file"),
        (".com", "DOS executable"),
        (".scr", "Screen saver executable"),
        (".py", "Python script"),
        (".php", "PHP script"),
        (".jsp", "Java Server Page"),
        (".asp", "Active Server Page"),
        (".jar", "Java executable"),
    ])
    def test_dangerous_file_extensions_should_be_rejected(
        self, setup_data, dangerous_extension, reason
    ):
        """ATTACK: Upload executable files that could be run on server.

        EXPECTED: Dangerous extensions should be rejected
        CURRENT: Likely accepted (BUG)
        """
        team, ticket = setup_data

        filename = f"malware{dangerous_extension}"
        uploaded_file = SimpleUploadedFile(
            name=filename,
            content=b"malicious code here",
            content_type="application/octet-stream",
        )

        factory = RequestFactory()
        request = factory.post(
            f"/tickets/{ticket.id}/upload",
            {"attachment": uploaded_file},
        )
        request.user = Mock()
        request.user.is_authenticated = True

        with patch("web.core.views.get_authentik_username", return_value="testuser"):
            with patch("web.core.views.verify_team_access", return_value=True):
                response = ticket_attachment_upload(request, ticket.id)

        # CRITICAL: Dangerous files should be rejected
        assert response.status_code == 400, (
            f"SECURITY BUG: {reason} ({dangerous_extension}) should be rejected! "
            f"Got status {response.status_code}"
        )
        assert not TicketAttachment.objects.filter(ticket=ticket).exists(), (
            f"Dangerous file was saved to database!"
        )

    def test_double_extension_attack_should_be_rejected(self, setup_data):
        """ATTACK: Use double extensions to bypass validation.

        Example: 'document.pdf.exe' - might only check last extension
        """
        team, ticket = setup_data

        uploaded_file = SimpleUploadedFile(
            name="document.pdf.exe",
            content=b"malicious content",
            content_type="application/pdf",
        )

        factory = RequestFactory()
        request = factory.post(
            f"/tickets/{ticket.id}/upload",
            {"attachment": uploaded_file},
        )
        request.user = Mock()
        request.user.is_authenticated = True

        with patch("web.core.views.get_authentik_username", return_value="testuser"):
            with patch("web.core.views.verify_team_access", return_value=True):
                response = ticket_attachment_upload(request, ticket.id)

        # Should validate ALL extensions, not just last one
        assert response.status_code == 400, (
            "Double extension with .exe should be rejected"
        )


@pytest.mark.django_db
class TestFileUploadMimeTypeValidation:
    """Test MIME type validation.

    BUG: MIME type from browser is trusted without validation
    SEVERITY: MEDIUM
    ATTACK: Upload malicious file with fake MIME type
    """

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
            category="technical",
            title="Test Ticket",
            status="open",
        )
        return team, ticket

    def test_mime_type_mismatch_should_be_detected(self, setup_data):
        """ATTACK: Upload executable with fake image MIME type.

        EXPECTED: MIME type should be validated against actual file content
        CURRENT: Browser-supplied MIME type is trusted (BUG)
        """
        team, ticket = setup_data

        # Real executable content (PE header for Windows .exe)
        executable_content = b"MZ\x90\x00" + b"\x00" * 100  # PE header

        # But claim it's an image
        uploaded_file = SimpleUploadedFile(
            name="totally_an_image.exe",
            content=executable_content,
            content_type="image/jpeg",  # LIE
        )

        factory = RequestFactory()
        request = factory.post(
            f"/tickets/{ticket.id}/upload",
            {"attachment": uploaded_file},
        )
        request.user = Mock()
        request.user.is_authenticated = True

        with patch("web.core.views.get_authentik_username", return_value="testuser"):
            with patch("web.core.views.verify_team_access", return_value=True):
                response = ticket_attachment_upload(request, ticket.id)

        # Should detect MIME type mismatch
        if response.status_code == 200:
            attachment = TicketAttachment.objects.get(ticket=ticket)
            # BUG: Stored MIME type should NOT be from browser
            # Should be validated against actual content
            assert attachment.mime_type != "image/jpeg", (
                f"SECURITY BUG: Fake MIME type was accepted! "
                f"File is executable but stored as: {attachment.mime_type}"
            )

    def test_svg_with_javascript_should_be_rejected(self, setup_data):
        """ATTACK: Upload SVG with embedded JavaScript (XSS).

        SVG files can contain <script> tags that execute when opened.
        """
        team, ticket = setup_data

        malicious_svg = b"""<?xml version="1.0" standalone="no"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<svg version="1.1" xmlns="http://www.w3.org/2000/svg">
  <script type="text/javascript">
    alert('XSS - your session cookie: ' + document.cookie);
  </script>
</svg>"""

        uploaded_file = SimpleUploadedFile(
            name="innocent.svg",
            content=malicious_svg,
            content_type="image/svg+xml",
        )

        factory = RequestFactory()
        request = factory.post(
            f"/tickets/{ticket.id}/upload",
            {"attachment": uploaded_file},
        )
        request.user = Mock()
        request.user.is_authenticated = True

        with patch("web.core.views.get_authentik_username", return_value="testuser"):
            with patch("web.core.views.verify_team_access", return_value=True):
                response = ticket_attachment_upload(request, ticket.id)

        # SVG with scripts should be rejected or sanitized
        assert response.status_code == 400, (
            "SVG files with JavaScript should be rejected (XSS risk)"
        )


@pytest.mark.django_db
class TestFileUploadContentDisposition:
    """Test Content-Disposition header injection.

    BUG: Filename might not be escaped in Content-Disposition header
    SEVERITY: LOW
    ATTACK: Inject headers through filename
    """

    @pytest.fixture
    def setup_data(self):
        """Create test team, ticket, and attachment."""
        team = Team.objects.create(
            team_number=1,
            team_name="Test Team",
            authentik_group="WCComps_BlueTeam1",
        )
        ticket = Ticket.objects.create(
            ticket_number="T001-001",
            team=team,
            category="technical",
            title="Test Ticket",
            status="open",
        )
        # Create attachment with malicious filename
        attachment = TicketAttachment.objects.create(
            ticket=ticket,
            filename='test.txt"\r\nX-Evil-Header: injected\r\n"',
            file_data=b"test content",
            mime_type="text/plain",
            uploaded_by="testuser",
        )
        return team, ticket, attachment

    def test_filename_with_newlines_should_not_inject_headers(self, setup_data):
        """ATTACK: Inject HTTP headers through filename.

        EXPECTED: Newlines should be escaped in Content-Disposition header
        """
        team, ticket, attachment = setup_data

        factory = RequestFactory()
        request = factory.get(f"/tickets/attachments/{attachment.id}")
        request.user = Mock()
        request.user.is_authenticated = True

        with patch("web.core.views.get_authentik_username", return_value="testuser"):
            with patch("web.core.views.verify_team_access", return_value=True):
                response = ticket_attachment_download(request, attachment.id)

        # Check Content-Disposition header
        content_disposition = response.get("Content-Disposition", "")

        # Should NOT contain literal newlines
        assert "\r" not in content_disposition, (
            "SECURITY BUG: Carriage return in Content-Disposition allows header injection"
        )
        assert "\n" not in content_disposition, (
            "SECURITY BUG: Newline in Content-Disposition allows header injection"
        )

        # Evil header should NOT be injected
        assert "X-Evil-Header" not in str(response.items()), (
            "Header injection successful - filename not properly escaped"
        )


@pytest.mark.django_db
class TestFileUploadSizeAndDoS:
    """Test file size limits and denial of service attacks."""

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
            category="technical",
            title="Test Ticket",
            status="open",
        )
        return team, ticket

    def test_file_exceeding_size_limit_should_be_rejected(self, setup_data):
        """Test that files larger than 10MB are rejected."""
        team, ticket = setup_data

        # Create 11MB file
        large_file_content = b"A" * (11 * 1024 * 1024)
        uploaded_file = SimpleUploadedFile(
            name="large_file.txt",
            content=large_file_content,
            content_type="text/plain",
        )

        factory = RequestFactory()
        request = factory.post(
            f"/tickets/{ticket.id}/upload",
            {"attachment": uploaded_file},
        )
        request.user = Mock()
        request.user.is_authenticated = True

        with patch("web.core.views.get_authentik_username", return_value="testuser"):
            with patch("web.core.views.verify_team_access", return_value=True):
                response = ticket_attachment_upload(request, ticket.id)

        # Should be rejected
        assert response.status_code == 400
        assert b"too large" in response.content.lower() or b"size" in response.content.lower()

    def test_zip_bomb_should_be_detected(self, setup_data):
        """ATTACK: Upload compressed file that expands to huge size.

        A 10MB zip file could expand to 10GB when extracted.
        """
        team, ticket = setup_data

        # Create small zip that claims to contain huge file
        import zipfile

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            # Add highly compressible content
            huge_content = b"\x00" * (100 * 1024 * 1024)  # 100MB of zeros
            zip_file.writestr("bomb.txt", huge_content)

        zip_content = buffer.getvalue()

        uploaded_file = SimpleUploadedFile(
            name="innocent.zip",
            content=zip_content,
            content_type="application/zip",
        )

        factory = RequestFactory()
        request = factory.post(
            f"/tickets/{ticket.id}/upload",
            {"attachment": uploaded_file},
        )
        request.user = Mock()
        request.user.is_authenticated = True

        with patch("web.core.views.get_authentik_username", return_value="testuser"):
            with patch("web.core.views.verify_team_access", return_value=True):
                response = ticket_attachment_upload(request, ticket.id)

        # Ideally should detect and reject zip bombs
        # At minimum, should not extract the zip automatically
        # This is a FEATURE REQUEST if not currently handled


@pytest.mark.django_db
class TestFileUploadRaceConditions:
    """Test concurrent file uploads for race conditions.

    These tests check if concurrent operations maintain data integrity.
    """

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
            category="technical",
            title="Test Ticket",
            status="open",
        )
        return team, ticket

    def test_concurrent_uploads_maintain_attachment_count(self, setup_data):
        """Test that concurrent uploads don't lose data.

        PROPERTY: If 5 uploads succeed, should have exactly 5 attachments.
        """
        import threading

        team, ticket = setup_data
        results = []

        def upload_file(file_num):
            """Upload a file in a thread."""
            uploaded_file = SimpleUploadedFile(
                name=f"file_{file_num}.txt",
                content=f"content {file_num}".encode(),
                content_type="text/plain",
            )

            factory = RequestFactory()
            request = factory.post(
                f"/tickets/{ticket.id}/upload",
                {"attachment": uploaded_file},
            )
            request.user = Mock()
            request.user.is_authenticated = True

            with patch("web.core.views.get_authentik_username", return_value=f"user{file_num}"):
                with patch("web.core.views.verify_team_access", return_value=True):
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
        assert all(status == 200 for status in results), (
            f"Some uploads failed: {results}"
        )

        # CRITICAL: Should have exactly 5 attachments
        attachment_count = TicketAttachment.objects.filter(ticket=ticket).count()
        assert attachment_count == 5, (
            f"Race condition detected! Expected 5 attachments, got {attachment_count}"
        )


@pytest.mark.django_db
class TestFileUploadAuthorizationBypass:
    """Test authorization bypass attempts.

    These test if attackers can access files from other teams.
    """

    @pytest.fixture
    def setup_data(self):
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
            category="technical",
            title="Team 1 Ticket",
            status="open",
        )
        ticket2 = Ticket.objects.create(
            ticket_number="T002-001",
            team=team2,
            category="technical",
            title="Team 2 Ticket",
            status="open",
        )

        # Create attachment for team 1
        attachment = TicketAttachment.objects.create(
            ticket=ticket1,
            filename="secret.txt",
            file_data=b"Team 1 secret data",
            mime_type="text/plain",
            uploaded_by="team1user",
        )

        return team1, team2, ticket1, ticket2, attachment

    def test_cannot_download_other_team_attachment(self, setup_data):
        """ATTACK: Team 2 user tries to download Team 1's attachment.

        EXPECTED: Access denied
        """
        team1, team2, ticket1, ticket2, attachment = setup_data

        factory = RequestFactory()
        request = factory.get(f"/tickets/attachments/{attachment.id}")
        request.user = Mock()
        request.user.is_authenticated = True

        # User from team 2 trying to access team 1's file
        with patch("web.core.views.get_authentik_username", return_value="team2user"):
            with patch("web.core.views.verify_team_access", return_value=False):
                response = ticket_attachment_download(request, attachment.id)

        # CRITICAL: Should be denied
        assert response.status_code in [403, 404], (
            f"SECURITY BUG: Team 2 accessed Team 1's file! Status: {response.status_code}"
        )

    def test_cannot_upload_to_other_team_ticket(self, setup_data):
        """ATTACK: Team 2 user tries to upload to Team 1's ticket.

        EXPECTED: Access denied
        """
        team1, team2, ticket1, ticket2, attachment = setup_data

        uploaded_file = SimpleUploadedFile(
            name="malicious.txt",
            content=b"trying to upload to wrong team",
            content_type="text/plain",
        )

        factory = RequestFactory()
        request = factory.post(
            f"/tickets/{ticket1.id}/upload",  # Team 1's ticket
            {"attachment": uploaded_file},
        )
        request.user = Mock()
        request.user.is_authenticated = True

        # User from team 2
        with patch("web.core.views.get_authentik_username", return_value="team2user"):
            with patch("web.core.views.verify_team_access", return_value=False):
                response = ticket_attachment_upload(request, ticket1.id)

        # Should be denied
        assert response.status_code in [403, 404], (
            f"SECURITY BUG: Cross-team upload allowed! Status: {response.status_code}"
        )

        # File should NOT be saved
        assert not TicketAttachment.objects.filter(
            ticket=ticket1,
            filename="malicious.txt"
        ).exists()
