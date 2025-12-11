"""PDF score card generation for competitions."""

import logging
from io import BytesIO

from django.template.loader import render_to_string
from django.utils import timezone
from weasyprint import HTML  # type: ignore[import-untyped]

from .models import EventScore

logger = logging.getLogger(__name__)


def generate_scorecard_pdf(event_score: EventScore) -> bytes:
    """
    Generate a PDF score card for a team's event score.

    Args:
        event_score: EventScore instance with all score data

    Returns:
        PDF content as bytes
    """
    # Get school name from team assignment if available
    school_name = "Unknown School"
    if event_score.team_assignment and event_score.team_assignment.registration:
        school_name = event_score.team_assignment.registration.school_name

    # Get total teams for this event
    total_teams = EventScore.objects.filter(event=event_score.event).exclude(rank__isnull=True).count()
    if total_teams == 0:
        total_teams = EventScore.objects.filter(event=event_score.event).count()

    context = {
        "event": event_score.event,
        "school_name": school_name,
        "team_number": event_score.team.team_number,
        "rank": event_score.rank or "-",
        "total_teams": total_teams,
        "service_points": event_score.service_points,
        "inject_points": event_score.inject_points,
        "orange_points": event_score.orange_points,
        "red_deductions": event_score.red_deductions,
        "incident_recovery_points": event_score.incident_recovery_points,
        "sla_penalties": event_score.sla_penalties,
        "black_adjustments": event_score.black_adjustments,
        "total_score": event_score.total_score,
        "generated_at": timezone.now(),
    }

    html_content = render_to_string("scoring/scorecard_pdf.html", context)

    pdf_buffer = BytesIO()
    HTML(string=html_content).write_pdf(pdf_buffer)
    pdf_buffer.seek(0)

    return pdf_buffer.read()


def generate_scorecard_filename(event_score: EventScore) -> str:
    """
    Generate a filename for the score card PDF.

    Args:
        event_score: EventScore instance

    Returns:
        Filename string
    """
    event_name = event_score.event.name.replace(" ", "_").replace("/", "-")
    team_num = f"team{event_score.team.team_number:02d}"
    return f"scorecard_{event_name}_{team_num}.pdf"
