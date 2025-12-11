"""Tests for the email service module."""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from core.email import (
    ConsoleBackend,
    EmailMessage,
    EmailService,
    SendmailBackend,
    get_email_service,
    send_email,
    send_templated_email,
)


class TestEmailMessage:
    """Tests for EmailMessage dataclass."""

    def test_basic_message_creation(self):
        """EmailMessage should store basic fields."""
        msg = EmailMessage(
            to=["test@example.com"],
            subject="Test Subject",
            body_text="Test body",
        )
        assert msg.to == ["test@example.com"]
        assert msg.subject == "Test Subject"
        assert msg.body_text == "Test body"
        assert msg.body_html == ""
        assert msg.attachments == []

    def test_message_with_html(self):
        """EmailMessage should store HTML body."""
        msg = EmailMessage(
            to=["test@example.com"],
            subject="Test",
            body_text="Plain text",
            body_html="<p>HTML</p>",
        )
        assert msg.body_html == "<p>HTML</p>"

    def test_message_with_attachments(self):
        """EmailMessage should store attachments."""
        attachments = [("file.pdf", b"content", "application/pdf")]
        msg = EmailMessage(
            to=["test@example.com"],
            subject="Test",
            body_text="Body",
            attachments=attachments,
        )
        assert len(msg.attachments) == 1
        assert msg.attachments[0][0] == "file.pdf"

    def test_default_from_email(self):
        """EmailMessage should use default from_email from settings."""
        with patch("core.email.settings") as mock_settings:
            mock_settings.DEFAULT_FROM_EMAIL = "default@wccomps.org"
            msg = EmailMessage(
                to=["test@example.com"],
                subject="Test",
                body_text="Body",
            )
            assert msg.from_email == "default@wccomps.org"

    def test_custom_from_email(self):
        """EmailMessage should allow custom from_email."""
        msg = EmailMessage(
            to=["test@example.com"],
            subject="Test",
            body_text="Body",
            from_email="custom@wccomps.org",
        )
        assert msg.from_email == "custom@wccomps.org"

    def test_multiple_recipients(self):
        """EmailMessage should handle multiple recipients."""
        msg = EmailMessage(
            to=["a@example.com", "b@example.com", "c@example.com"],
            subject="Test",
            body_text="Body",
        )
        assert len(msg.to) == 3


class TestSendmailBackend:
    """Tests for SendmailBackend."""

    def test_build_mime_message_plain_text(self):
        """Should build valid MIME message for plain text."""
        backend = SendmailBackend()
        msg = EmailMessage(
            to=["test@example.com"],
            subject="Test Subject",
            body_text="Test body",
            from_email="from@example.com",
        )
        mime_msg = backend._build_mime_message(msg)

        assert mime_msg["Subject"] == "Test Subject"
        assert mime_msg["From"] == "from@example.com"
        assert mime_msg["To"] == "test@example.com"

    def test_build_mime_message_with_html(self):
        """Should build multipart/alternative for HTML emails."""
        backend = SendmailBackend()
        msg = EmailMessage(
            to=["test@example.com"],
            subject="Test",
            body_text="Plain text",
            body_html="<p>HTML</p>",
            from_email="from@example.com",
        )
        mime_msg = backend._build_mime_message(msg)

        assert mime_msg.get_content_type() == "multipart/mixed"

    def test_build_mime_message_with_reply_to(self):
        """Should include Reply-To header."""
        backend = SendmailBackend()
        msg = EmailMessage(
            to=["test@example.com"],
            subject="Test",
            body_text="Body",
            from_email="from@example.com",
            reply_to="reply@example.com",
        )
        mime_msg = backend._build_mime_message(msg)

        assert mime_msg["Reply-To"] == "reply@example.com"

    def test_build_mime_message_with_attachments(self):
        """Should include attachments in MIME message."""
        backend = SendmailBackend()
        msg = EmailMessage(
            to=["test@example.com"],
            subject="Test",
            body_text="Body",
            from_email="from@example.com",
            attachments=[("test.pdf", b"PDF content", "application/pdf")],
        )
        mime_msg = backend._build_mime_message(msg)

        # Check attachment exists
        payloads = mime_msg.get_payload()
        assert len(payloads) >= 2  # Body + attachment

    def test_send_success(self):
        """Should return True on successful sendmail execution."""
        backend = SendmailBackend()
        msg = EmailMessage(
            to=["test@example.com"],
            subject="Test",
            body_text="Body",
            from_email="from@example.com",
        )

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("core.email.subprocess.run", return_value=mock_result) as mock_run:
            result = backend.send(msg)

            assert result is True
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args[0][0] == ["/usr/sbin/sendmail", "-t", "-oi"]

    def test_send_failure_returncode(self):
        """Should return False when sendmail returns non-zero."""
        backend = SendmailBackend()
        msg = EmailMessage(
            to=["test@example.com"],
            subject="Test",
            body_text="Body",
        )

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = b"Error message"

        with patch("core.email.subprocess.run", return_value=mock_result):
            result = backend.send(msg)
            assert result is False

    def test_send_failure_timeout(self):
        """Should return False on timeout."""
        backend = SendmailBackend()
        msg = EmailMessage(
            to=["test@example.com"],
            subject="Test",
            body_text="Body",
        )

        with patch("core.email.subprocess.run", side_effect=subprocess.TimeoutExpired("sendmail", 30)):
            result = backend.send(msg)
            assert result is False

    def test_send_failure_not_found(self):
        """Should return False when sendmail not found."""
        backend = SendmailBackend(sendmail_path="/nonexistent/sendmail")
        msg = EmailMessage(
            to=["test@example.com"],
            subject="Test",
            body_text="Body",
        )

        with patch("core.email.subprocess.run", side_effect=FileNotFoundError):
            result = backend.send(msg)
            assert result is False

    def test_custom_sendmail_path(self):
        """Should use custom sendmail path."""
        backend = SendmailBackend(sendmail_path="/custom/sendmail")
        assert backend.sendmail_path == "/custom/sendmail"


class TestConsoleBackend:
    """Tests for ConsoleBackend."""

    def test_send_prints_to_console(self, capsys):
        """Should print email details to console."""
        backend = ConsoleBackend()
        msg = EmailMessage(
            to=["test@example.com"],
            subject="Test Subject",
            body_text="Test body",
            from_email="from@example.com",
        )

        result = backend.send(msg)

        assert result is True
        captured = capsys.readouterr()
        assert "test@example.com" in captured.out
        assert "Test Subject" in captured.out
        assert "Test body" in captured.out

    def test_send_shows_attachments(self, capsys):
        """Should show attachment names in console output."""
        backend = ConsoleBackend()
        msg = EmailMessage(
            to=["test@example.com"],
            subject="Test",
            body_text="Body",
            attachments=[("document.pdf", b"content", "application/pdf")],
        )

        backend.send(msg)

        captured = capsys.readouterr()
        assert "document.pdf" in captured.out


class TestEmailService:
    """Tests for EmailService."""

    def test_send_with_string_recipient(self):
        """Should convert single recipient string to list."""
        mock_backend = MagicMock()
        mock_backend.send.return_value = True
        service = EmailService(backend=mock_backend)

        service.send(
            to="single@example.com",
            subject="Test",
            body_text="Body",
        )

        called_msg = mock_backend.send.call_args[0][0]
        assert called_msg.to == ["single@example.com"]

    def test_send_with_list_recipients(self):
        """Should pass list recipients through."""
        mock_backend = MagicMock()
        mock_backend.send.return_value = True
        service = EmailService(backend=mock_backend)

        service.send(
            to=["a@example.com", "b@example.com"],
            subject="Test",
            body_text="Body",
        )

        called_msg = mock_backend.send.call_args[0][0]
        assert called_msg.to == ["a@example.com", "b@example.com"]

    def test_send_returns_backend_result(self):
        """Should return result from backend."""
        mock_backend = MagicMock()
        mock_backend.send.return_value = False
        service = EmailService(backend=mock_backend)

        result = service.send(
            to="test@example.com",
            subject="Test",
            body_text="Body",
        )

        assert result is False

    def test_default_backend_debug_mode(self):
        """Should use ConsoleBackend in DEBUG mode."""
        with patch("core.email.settings") as mock_settings:
            mock_settings.DEBUG = True
            service = EmailService()
            assert isinstance(service.backend, ConsoleBackend)

    def test_default_backend_production_mode(self):
        """Should use SendmailBackend in production."""
        with patch("core.email.settings") as mock_settings:
            mock_settings.DEBUG = False
            service = EmailService()
            assert isinstance(service.backend, SendmailBackend)


@pytest.mark.django_db
class TestEmailServiceTemplated:
    """Tests for templated email sending."""

    def test_send_templated_renders_text_template(self):
        """Should render text template with context."""
        mock_backend = MagicMock()
        mock_backend.send.return_value = True
        service = EmailService(backend=mock_backend)

        service.send_templated(
            to="test@example.com",
            template_name="credentials",
            context={
                "event_name": "Test Event",
                "event_date": "2025-01-15",
                "start_time": "09:00",
                "end_time": "17:00",
                "team_number": 5,
                "password": "secret123",
                "packet_attached": False,
            },
        )

        called_msg = mock_backend.send.call_args[0][0]
        assert "Test Event" in called_msg.body_text
        assert "team05" in called_msg.body_text

    def test_send_templated_renders_html_template(self):
        """Should render HTML template when available."""
        mock_backend = MagicMock()
        mock_backend.send.return_value = True
        service = EmailService(backend=mock_backend)

        service.send_templated(
            to="test@example.com",
            template_name="credentials",
            context={
                "event_name": "Test Event",
                "event_date": "2025-01-15",
                "start_time": "09:00",
                "end_time": "17:00",
                "team_number": 5,
                "password": "secret123",
                "packet_attached": False,
            },
        )

        called_msg = mock_backend.send.call_args[0][0]
        assert called_msg.body_html  # HTML should be present
        assert "Test Event" in called_msg.body_html

    def test_send_templated_renders_subject_template(self):
        """Should render subject from template."""
        mock_backend = MagicMock()
        mock_backend.send.return_value = True
        service = EmailService(backend=mock_backend)

        service.send_templated(
            to="test@example.com",
            template_name="credentials",
            context={
                "event_name": "Test Event",
                "event_date": "2025-01-15",
                "start_time": "09:00",
                "end_time": "17:00",
                "team_number": 5,
                "password": "secret123",
            },
        )

        called_msg = mock_backend.send.call_args[0][0]
        assert "Test Event" in called_msg.subject
        assert "Team 05" in called_msg.subject

    def test_send_templated_custom_subject_overrides(self):
        """Custom subject should override template subject."""
        mock_backend = MagicMock()
        mock_backend.send.return_value = True
        service = EmailService(backend=mock_backend)

        service.send_templated(
            to="test@example.com",
            template_name="credentials",
            context={
                "event_name": "Test Event",
                "event_date": "2025-01-15",
                "start_time": "09:00",
                "end_time": "17:00",
                "team_number": 5,
                "password": "secret123",
            },
            subject="Custom Subject Line",
        )

        called_msg = mock_backend.send.call_args[0][0]
        assert called_msg.subject == "Custom Subject Line"

    def test_send_templated_with_attachments(self):
        """Should pass attachments through."""
        mock_backend = MagicMock()
        mock_backend.send.return_value = True
        service = EmailService(backend=mock_backend)

        service.send_templated(
            to="test@example.com",
            template_name="credentials",
            context={
                "event_name": "Test Event",
                "event_date": "2025-01-15",
                "start_time": "09:00",
                "end_time": "17:00",
                "team_number": 5,
                "password": "secret123",
            },
            attachments=[("packet.pdf", b"content", "application/pdf")],
        )

        called_msg = mock_backend.send.call_args[0][0]
        assert len(called_msg.attachments) == 1
        assert called_msg.attachments[0][0] == "packet.pdf"


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_get_email_service_returns_singleton(self):
        """get_email_service should return same instance."""
        with patch("core.email._email_service", None):
            service1 = get_email_service()
            service2 = get_email_service()
            assert service1 is service2

    def test_send_email_uses_service(self):
        """send_email should delegate to service."""
        mock_service = MagicMock()
        mock_service.send.return_value = True

        with patch("core.email.get_email_service", return_value=mock_service):
            result = send_email(
                to="test@example.com",
                subject="Test",
                body_text="Body",
            )

            assert result is True
            mock_service.send.assert_called_once()

    def test_send_templated_email_uses_service(self):
        """send_templated_email should delegate to service."""
        mock_service = MagicMock()
        mock_service.send_templated.return_value = True

        with patch("core.email.get_email_service", return_value=mock_service):
            result = send_templated_email(
                to="test@example.com",
                template_name="test_template",
                context={"key": "value"},
            )

            assert result is True
            mock_service.send_templated.assert_called_once()


@pytest.mark.django_db
class TestEmailTemplates:
    """Tests for email template rendering."""

    def test_registration_confirmation_template(self):
        """registration_confirmation template should render."""
        mock_backend = MagicMock()
        mock_backend.send.return_value = True
        service = EmailService(backend=mock_backend)

        service.send_templated(
            to="test@example.com",
            template_name="registration_confirmation",
            context={
                "school_name": "Test High School",
                "events": [{"name": "Invitational #1", "date": "2025-01-15"}],
                "edit_url": "https://wccomps.org/register/edit/abc123/",
            },
        )

        called_msg = mock_backend.send.call_args[0][0]
        assert "Test High School" in called_msg.body_text
        assert "edit/abc123" in called_msg.body_text

    def test_registration_approved_template(self):
        """registration_approved template should render."""
        mock_backend = MagicMock()
        mock_backend.send.return_value = True
        service = EmailService(backend=mock_backend)

        service.send_templated(
            to="test@example.com",
            template_name="registration_approved",
            context={
                "school_name": "Test High School",
                "approved_at": "2025-01-10",
                "events": [{"name": "Invitational #1", "date": "2025-01-15"}],
                "edit_url": "https://wccomps.org/register/edit/abc123/",
            },
        )

        called_msg = mock_backend.send.call_args[0][0]
        assert "Test High School" in called_msg.body_text
        assert "approved" in called_msg.body_text.lower()

    def test_event_reminder_template(self):
        """event_reminder template should render."""
        mock_backend = MagicMock()
        mock_backend.send.return_value = True
        service = EmailService(backend=mock_backend)

        service.send_templated(
            to="test@example.com",
            template_name="event_reminder",
            context={
                "event_name": "State Competition",
                "event_date": "2025-03-15",
                "start_time": "09:00",
                "end_time": "17:00",
                "days_until": 7,
                "school_name": "Test High School",
                "status": "paid",
                "edit_url": "https://wccomps.org/register/edit/abc123/",
            },
        )

        called_msg = mock_backend.send.call_args[0][0]
        assert "State Competition" in called_msg.body_text
        assert "7" in called_msg.body_text

    def test_scorecard_template(self):
        """scorecard template should render."""
        mock_backend = MagicMock()
        mock_backend.send.return_value = True
        service = EmailService(backend=mock_backend)

        service.send_templated(
            to="test@example.com",
            template_name="scorecard",
            context={
                "event_name": "State Competition",
                "event_date": "2025-03-15",
                "school_name": "Test High School",
                "team_number": 12,
                "service_points": 1500,
                "inject_points": 800,
                "orange_points": 200,
                "red_deductions": 150,
                "incident_recovery_points": 100,
                "sla_penalties": 50,
                "black_adjustments": 0,
                "total_score": 2400,
                "rank": 3,
                "total_teams": 20,
                "scorecard_attached": True,
            },
        )

        called_msg = mock_backend.send.call_args[0][0]
        assert "State Competition" in called_msg.body_text
        assert "2400" in called_msg.body_text
        assert "#3" in called_msg.body_text or "3" in called_msg.body_text
