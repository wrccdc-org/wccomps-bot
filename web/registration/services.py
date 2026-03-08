"""Registration services for credential generation and distribution."""

import contextlib
import logging
from dataclasses import dataclass

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from core.authentik_utils import generate_blueteam_password, reset_blueteam_password

from .models import Event, EventTeamAssignment, RegistrationContact

logger = logging.getLogger(__name__)


@dataclass
class CredentialSendResult:
    """Result of sending credentials to a team."""

    success: bool
    team_number: int
    school_name: str
    password: str | None = None
    error: str | None = None


def get_recipient_emails(assignment: EventTeamAssignment) -> list[str]:
    """
    Get all email addresses that should receive credentials.

    Sends to: captain, coach, and co_captain (if exists).

    Args:
        assignment: EventTeamAssignment with registration

    Returns:
        List of email addresses
    """
    contacts = RegistrationContact.objects.filter(registration=assignment.registration)
    emails = [
        contact.email for contact in contacts if contact.role in ("captain", "coach", "co_captain") and contact.email
    ]
    return list(set(emails))  # Remove duplicates


def send_credentials_for_assignment(
    assignment: EventTeamAssignment,
    packet_data: bytes | None = None,
    packet_filename: str = "competition_packet.pdf",
) -> CredentialSendResult:
    """
    Generate password, reset in Authentik, and send credentials email.

    Args:
        assignment: EventTeamAssignment to send credentials for
        packet_data: Optional PDF packet to attach
        packet_filename: Filename for the packet attachment

    Returns:
        CredentialSendResult with outcome
    """
    team_number = assignment.team.team_number
    school_name = assignment.registration.school_name
    event = assignment.event

    # Generate new password
    password = generate_blueteam_password()

    # Reset password in Authentik
    success, error = reset_blueteam_password(team_number, password)
    if not success:
        logger.error("Failed to reset password for team %d: %s", team_number, error)
        return CredentialSendResult(
            success=False,
            team_number=team_number,
            school_name=school_name,
            error=f"Password reset failed: {error}",
        )

    # Store password in assignment for potential re-send
    assignment.password_generated = password
    assignment.save(update_fields=["password_generated"])

    # Get recipient emails
    recipients = get_recipient_emails(assignment)
    if not recipients:
        logger.error("No recipients found for team %d", team_number)
        return CredentialSendResult(
            success=False,
            team_number=team_number,
            school_name=school_name,
            password=password,
            error="No email recipients found",
        )

    # Prepare attachments
    attachments = []
    if packet_data:
        attachments.append((packet_filename, packet_data, "application/pdf"))

    # Send credentials email
    template_context = {
        "event_name": event.name,
        "event_date": event.date,
        "start_time": event.start_time,
        "end_time": event.end_time,
        "team_number": team_number,
        "password": password,
        "packet_attached": bool(packet_data),
    }
    email_sent = _send_templated_email(
        to=recipients,
        template_name="credentials",
        context=template_context,
        attachments=attachments,
    )

    if not email_sent:
        logger.error("Failed to send credentials email for team %d", team_number)
        return CredentialSendResult(
            success=False,
            team_number=team_number,
            school_name=school_name,
            password=password,
            error="Email sending failed",
        )

    # Update credentials_sent_at
    assignment.credentials_sent_at = timezone.now()
    assignment.save(update_fields=["credentials_sent_at"])

    logger.info(
        "Sent credentials to team %d (%s) for event %s",
        team_number,
        school_name,
        event.name,
    )

    return CredentialSendResult(
        success=True,
        team_number=team_number,
        school_name=school_name,
        password=password,
    )


def send_credentials_batch(
    event: Event,
    packet_data: bytes | None = None,
    packet_filename: str = "competition_packet.pdf",
) -> list[CredentialSendResult]:
    """
    Send credentials to all teams assigned to an event.

    Args:
        event: Event to send credentials for
        packet_data: Optional PDF packet to attach to all emails
        packet_filename: Filename for the packet attachment

    Returns:
        List of CredentialSendResult for each team
    """
    results = []
    assignments = EventTeamAssignment.objects.filter(event=event).select_related("team", "registration")

    for assignment in assignments:
        result = send_credentials_for_assignment(
            assignment,
            packet_data=packet_data,
            packet_filename=packet_filename,
        )
        results.append(result)

    return results


def resend_credentials_for_assignment(assignment: EventTeamAssignment) -> CredentialSendResult:
    """
    Resend credentials email using stored password.

    Does NOT generate a new password - uses the previously generated one.

    Args:
        assignment: EventTeamAssignment to resend credentials for

    Returns:
        CredentialSendResult with outcome
    """
    team_number = assignment.team.team_number
    school_name = assignment.registration.school_name
    event = assignment.event

    if not assignment.password_generated:
        return CredentialSendResult(
            success=False,
            team_number=team_number,
            school_name=school_name,
            error="No password on file - use send_credentials_for_assignment instead",
        )

    recipients = get_recipient_emails(assignment)
    if not recipients:
        return CredentialSendResult(
            success=False,
            team_number=team_number,
            school_name=school_name,
            password=assignment.password_generated,
            error="No email recipients found",
        )

    template_context = {
        "event_name": event.name,
        "event_date": event.date,
        "start_time": event.start_time,
        "end_time": event.end_time,
        "team_number": team_number,
        "password": assignment.password_generated,
        "packet_attached": False,
    }
    email_sent = _send_templated_email(
        to=recipients,
        template_name="credentials",
        context=template_context,
    )

    if not email_sent:
        return CredentialSendResult(
            success=False,
            team_number=team_number,
            school_name=school_name,
            password=assignment.password_generated,
            error="Email sending failed",
        )

    return CredentialSendResult(
        success=True,
        team_number=team_number,
        school_name=school_name,
        password=assignment.password_generated,
    )


def _send_templated_email(
    *,
    to: list[str],
    template_name: str,
    context: dict[str, object],
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> bool:
    """Send an email using Django templates and SMTP backend.

    Looks for templates at:
    - emails/{template_name}.txt (required, plain text body)
    - emails/{template_name}.html (optional, HTML body)
    - emails/{template_name}_subject.txt (subject line)
    """
    try:
        body_text = render_to_string(f"emails/{template_name}.txt", context)

        # Subject from template
        try:
            subject = render_to_string(f"emails/{template_name}_subject.txt", context).strip()
        except Exception:
            subject = template_name.replace("_", " ").title()

        msg = EmailMultiAlternatives(
            subject=subject,
            body=body_text,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=to,
        )

        # Attach HTML version if available
        with contextlib.suppress(Exception):
            body_html = render_to_string(f"emails/{template_name}.html", context)
            if body_html:
                msg.attach_alternative(body_html, "text/html")

        # Add file attachments
        if attachments:
            for filename, data, mime_type in attachments:
                msg.attach(filename, data, mime_type)

        msg.send()
        return True
    except Exception:
        logger.exception("Failed to send templated email '%s'", template_name)
        return False
