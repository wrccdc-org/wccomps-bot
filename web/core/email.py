"""Email service abstraction with sendmail backend."""

import contextlib
import logging
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from django.conf import settings
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    """Email message data class."""

    to: list[str]
    subject: str
    body_text: str
    body_html: str = ""
    from_email: str = ""
    reply_to: str = ""
    attachments: list[tuple[str, bytes, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.from_email:
            self.from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@wccomps.org")


class EmailBackend(ABC):
    """Abstract base class for email backends."""

    @abstractmethod
    def send(self, message: EmailMessage) -> bool:
        """Send an email message. Returns True on success."""
        ...


class SendmailBackend(EmailBackend):
    """Email backend using sendmail subprocess."""

    def __init__(self, sendmail_path: str = "/usr/sbin/sendmail") -> None:
        self.sendmail_path = sendmail_path

    def _build_mime_message(self, message: EmailMessage) -> MIMEMultipart:
        """Build a MIME message from EmailMessage."""
        msg = MIMEMultipart("mixed") if message.attachments or message.body_html else MIMEMultipart()

        msg["Subject"] = message.subject
        msg["From"] = message.from_email
        msg["To"] = ", ".join(message.to)

        if message.reply_to:
            msg["Reply-To"] = message.reply_to

        # Add body
        if message.body_html:
            body_part = MIMEMultipart("alternative")
            body_part.attach(MIMEText(message.body_text, "plain", "utf-8"))
            body_part.attach(MIMEText(message.body_html, "html", "utf-8"))
            msg.attach(body_part)
        else:
            msg.attach(MIMEText(message.body_text, "plain", "utf-8"))

        # Add attachments
        for filename, content, mime_type in message.attachments:
            attachment = MIMEApplication(content)
            attachment.add_header("Content-Disposition", "attachment", filename=filename)
            if mime_type:
                attachment.set_type(mime_type)
            msg.attach(attachment)

        return msg

    def send(self, message: EmailMessage) -> bool:
        """Send email via sendmail subprocess."""
        try:
            mime_msg = self._build_mime_message(message)
            msg_bytes = mime_msg.as_bytes()

            # Call sendmail (path is hardcoded, not user input)
            process = subprocess.run(  # noqa: S603
                [self.sendmail_path, "-t", "-oi"],
                input=msg_bytes,
                capture_output=True,
                timeout=30,
            )

            if process.returncode != 0:
                logger.error(
                    "Sendmail failed with code %d: %s",
                    process.returncode,
                    process.stderr.decode("utf-8", errors="replace"),
                )
                return False

            logger.info("Email sent to %s: %s", ", ".join(message.to), message.subject)
            return True

        except subprocess.TimeoutExpired:
            logger.error("Sendmail timed out sending to %s", ", ".join(message.to))
            return False
        except FileNotFoundError:
            logger.error("Sendmail not found at %s", self.sendmail_path)
            return False
        except Exception:
            logger.exception("Failed to send email to %s", ", ".join(message.to))
            return False


class ConsoleBackend(EmailBackend):
    """Email backend that prints to console (for development)."""

    def send(self, message: EmailMessage) -> bool:
        """Print email to console."""
        print("=" * 60)
        print(f"TO: {', '.join(message.to)}")
        print(f"FROM: {message.from_email}")
        print(f"SUBJECT: {message.subject}")
        print("-" * 60)
        print(message.body_text)
        if message.attachments:
            print("-" * 60)
            print(f"ATTACHMENTS: {[a[0] for a in message.attachments]}")
        print("=" * 60)
        return True


class EmailService:
    """High-level email service with template support."""

    def __init__(self, backend: EmailBackend | None = None) -> None:
        if backend is None:
            # Use console backend in DEBUG mode, sendmail otherwise
            backend = ConsoleBackend() if getattr(settings, "DEBUG", False) else SendmailBackend()
        self.backend = backend

    def send(
        self,
        *,
        to: list[str] | str,
        subject: str,
        body_text: str,
        body_html: str = "",
        from_email: str = "",
        reply_to: str = "",
        attachments: list[tuple[str, bytes, str]] | None = None,
    ) -> bool:
        """Send an email."""
        if isinstance(to, str):
            to = [to]

        message = EmailMessage(
            to=to,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            from_email=from_email,
            reply_to=reply_to,
            attachments=attachments or [],
        )
        return self.backend.send(message)

    def send_templated(
        self,
        *,
        to: list[str] | str,
        template_name: str,
        context: dict[str, object],
        subject: str = "",
        from_email: str = "",
        reply_to: str = "",
        attachments: list[tuple[str, bytes, str]] | None = None,
    ) -> bool:
        """Send an email using templates.

        Looks for templates at:
        - emails/{template_name}.txt (required)
        - emails/{template_name}.html (optional)
        - emails/{template_name}_subject.txt (optional, if subject not provided)
        """
        # Render text body (required)
        body_text = render_to_string(f"emails/{template_name}.txt", context)

        # Try to render HTML body (optional)
        body_html = ""
        with contextlib.suppress(Exception):
            body_html = render_to_string(f"emails/{template_name}.html", context)

        # Get subject from template if not provided
        if not subject:
            try:
                subject = render_to_string(f"emails/{template_name}_subject.txt", context).strip()
            except Exception:
                subject = template_name.replace("_", " ").title()

        return self.send(
            to=to,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            from_email=from_email,
            reply_to=reply_to,
            attachments=attachments,
        )


# Singleton instance
_email_service: EmailService | None = None


def get_email_service() -> EmailService:
    """Get the singleton email service instance."""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service


def send_email(
    *,
    to: list[str] | str,
    subject: str,
    body_text: str,
    body_html: str = "",
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> bool:
    """Convenience function to send an email."""
    return get_email_service().send(
        to=to,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        attachments=attachments,
    )


def send_templated_email(
    *,
    to: list[str] | str,
    template_name: str,
    context: dict[str, object],
    subject: str = "",
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> bool:
    """Convenience function to send a templated email."""
    return get_email_service().send_templated(
        to=to,
        template_name=template_name,
        context=context,
        subject=subject,
        attachments=attachments,
    )
