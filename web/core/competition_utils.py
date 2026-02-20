"""Shared competition utilities."""

from scoring.models import (
    BlackTeamAdjustment,
    FinalScore,
    IncidentReport,
    IncidentScreenshot,
    InjectGrade,
    OrangeTeamBonus,
    RedTeamFinding,
    RedTeamScreenshot,
    ServiceScore,
)

from team.models import DiscordLink
from ticketing.models import Ticket, TicketAttachment, TicketComment, TicketHistory


def wipe_competition_data() -> dict[str, int]:
    """
    Wipe competition data for a fresh start.

    Deletes:
    - All scoring data (findings, grades, scores)
    - All tickets and history
    - Blue team Discord links (staff/volunteer links preserved)

    Preserves:
    - Teams (static config, always BlueTeam01-50)
    - AuditLog (compliance/history)
    - BotState (dashboard message IDs, etc.)
    - DiscordTask (task history)
    - LinkToken/LinkAttempt (harmless)

    Returns dict of model names to deleted counts.
    """
    # Delete in order to avoid foreign key constraints
    counts = {
        # Ticketing
        "TicketAttachment": TicketAttachment.objects.all().delete()[0],
        "TicketComment": TicketComment.objects.all().delete()[0],
        "TicketHistory": TicketHistory.objects.all().delete()[0],
        "Ticket": Ticket.objects.all().delete()[0],
        # Scoring (delete children first)
        "RedTeamScreenshot": RedTeamScreenshot.objects.all().delete()[0],
        "IncidentScreenshot": IncidentScreenshot.objects.all().delete()[0],
        "IncidentReport": IncidentReport.objects.all().delete()[0],
        "RedTeamFinding": RedTeamFinding.objects.all().delete()[0],
        "InjectGrade": InjectGrade.objects.all().delete()[0],
        "OrangeTeamBonus": OrangeTeamBonus.objects.all().delete()[0],
        "ServiceScore": ServiceScore.objects.all().delete()[0],
        "BlackTeamAdjustment": BlackTeamAdjustment.objects.all().delete()[0],
        "FinalScore": FinalScore.objects.all().delete()[0],
        # Blue team Discord links only (staff/volunteer links preserved)
        "BlueTeamDiscordLink": DiscordLink.objects.filter(team__isnull=False).delete()[0],
    }
    return counts
