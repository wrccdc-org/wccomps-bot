"""Shared competition utilities."""

from scoring.models import (
    BlackTeamAdjustment,
    EventScore,
    FinalScore,
    IncidentReport,
    IncidentScreenshot,
    InjectGrade,
    OrangeTeamBonus,
    RedTeamFinding,
    RedTeamScreenshot,
    ServiceScore,
)

from core.models import AuditLog, BotState, DashboardUpdate, DiscordTask
from team.models import DiscordLink, LinkAttempt, LinkToken, Team
from ticketing.models import Ticket, TicketAttachment, TicketComment, TicketHistory


def wipe_competition_data() -> dict[str, int]:
    """
    Wipe all competition data.

    Returns dict of model names to deleted counts.
    Preserves staff/volunteer Discord links (those without a team).
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
        "EventScore": EventScore.objects.all().delete()[0],
        # Core/Discord
        "DiscordTask": DiscordTask.objects.all().delete()[0],
        "LinkAttempt": LinkAttempt.objects.all().delete()[0],
        "LinkToken": LinkToken.objects.all().delete()[0],
        # Only delete blue team links, preserve staff/volunteer links
        "BlueTeamDiscordLink": DiscordLink.objects.filter(team__isnull=False).delete()[0],
        "AuditLog": AuditLog.objects.all().delete()[0],
        "BotState": BotState.objects.all().delete()[0],
        "DashboardUpdate": DashboardUpdate.objects.all().delete()[0],
        "Team": Team.objects.all().delete()[0],
    }
    return counts
