"""Scoring services for scorecard distribution."""

import logging
from dataclasses import dataclass

from django.utils import timezone
from registration.models import Event, RegistrationContact

from core.email import get_email_service

from .models import EventScore

logger = logging.getLogger(__name__)


@dataclass
class ScorecardSendResult:
    """Result of sending a scorecard to a team."""

    success: bool
    team_number: int
    school_name: str
    error: str | None = None


def get_scorecard_recipient_emails(event_score: EventScore) -> list[str]:
    """
    Get email addresses for scorecard distribution.

    Sends to: captain, coach, and co_captain (if exists).

    Args:
        event_score: EventScore with team_assignment

    Returns:
        List of email addresses
    """
    if not event_score.team_assignment or not event_score.team_assignment.registration:
        return []

    contacts = RegistrationContact.objects.filter(registration=event_score.team_assignment.registration)
    emails = [
        contact.email for contact in contacts if contact.role in ("captain", "coach", "co_captain") and contact.email
    ]
    return list(set(emails))


def send_scorecard_single(event_score: EventScore) -> ScorecardSendResult:
    """
    Send scorecard email to a single team.

    Args:
        event_score: EventScore to send scorecard for

    Returns:
        ScorecardSendResult with outcome
    """
    team_number = event_score.team.team_number

    # Get school name
    school_name = "Unknown School"
    if event_score.team_assignment and event_score.team_assignment.registration:
        school_name = event_score.team_assignment.registration.school_name

    # Get recipient emails
    recipients = get_scorecard_recipient_emails(event_score)
    if not recipients:
        logger.warning("No recipients found for team %d scorecard", team_number)
        return ScorecardSendResult(
            success=False,
            team_number=team_number,
            school_name=school_name,
            error="No email recipients found",
        )

    # Get total teams for context
    total_teams = EventScore.objects.filter(event=event_score.event).exclude(rank__isnull=True).count()
    if total_teams == 0:
        total_teams = EventScore.objects.filter(event=event_score.event).count()

    # Send email with PDF attachment
    email_service = get_email_service()
    email_sent = email_service.send_templated(
        to=recipients,
        template_name="scorecard",
        context={
            "event_name": event_score.event.name,
            "event_date": event_score.event.date,
            "school_name": school_name,
            "team_number": team_number,
            "service_points": event_score.service_points,
            "inject_points": event_score.inject_points,
            "orange_points": event_score.orange_points,
            "red_deductions": event_score.red_deductions,
            "incident_recovery_points": event_score.incident_recovery_points,
            "sla_penalties": event_score.sla_penalties,
            "black_adjustments": event_score.black_adjustments,
            "total_score": event_score.total_score,
            "rank": event_score.rank or "-",
            "total_teams": total_teams,
        },
    )

    if not email_sent:
        logger.error("Failed to send scorecard email for team %d", team_number)
        return ScorecardSendResult(
            success=False,
            team_number=team_number,
            school_name=school_name,
            error="Email sending failed",
        )

    # Update scorecard_sent_at
    event_score.scorecard_sent_at = timezone.now()
    event_score.save(update_fields=["scorecard_sent_at"])

    logger.info(
        "Sent scorecard to team %d (%s) for event %s",
        team_number,
        school_name,
        event_score.event.name,
    )

    return ScorecardSendResult(
        success=True,
        team_number=team_number,
        school_name=school_name,
    )


def send_scorecards_batch(event: Event) -> list[ScorecardSendResult]:
    """
    Send scorecards to all teams for a finalized event.

    Args:
        event: Event to send scorecards for (should be finalized)

    Returns:
        List of ScorecardSendResult for each team
    """
    if not event.is_finalized:
        logger.warning(
            "Attempting to send scorecards for non-finalized event %s",
            event.name,
        )

    results = []
    event_scores = EventScore.objects.filter(event=event).select_related(
        "team",
        "team_assignment",
        "team_assignment__registration",
    )

    for event_score in event_scores:
        result = send_scorecard_single(event_score)
        results.append(result)

    return results


def get_scorecard_distribution_stats(event: Event) -> dict[str, int]:
    """
    Get scorecard distribution statistics for an event.

    Args:
        event: Event to get stats for

    Returns:
        Dictionary with counts
    """
    event_scores = EventScore.objects.filter(event=event)

    return {
        "total": event_scores.count(),
        "sent": event_scores.exclude(scorecard_sent_at__isnull=True).count(),
        "pending": event_scores.filter(scorecard_sent_at__isnull=True).count(),
    }
