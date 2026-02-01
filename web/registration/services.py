"""Registration services for credential generation and distribution."""

import logging
from dataclasses import dataclass

from django.utils import timezone

from core.authentik_utils import generate_blueteam_password, reset_blueteam_password
from core.email import get_email_service

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
    email_service = get_email_service()
    email_sent = email_service.send_templated(
        to=recipients,
        template_name="credentials",
        context={
            "event_name": event.name,
            "event_date": event.date,
            "start_time": event.start_time,
            "end_time": event.end_time,
            "team_number": team_number,
            "password": password,
            "packet_attached": bool(packet_data),
        },
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

    email_service = get_email_service()
    email_sent = email_service.send_templated(
        to=recipients,
        template_name="credentials",
        context={
            "event_name": event.name,
            "event_date": event.date,
            "start_time": event.start_time,
            "end_time": event.end_time,
            "team_number": team_number,
            "password": assignment.password_generated,
            "packet_attached": False,
        },
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
