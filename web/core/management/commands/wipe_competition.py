"""Wipe all competition data (nuclear option)."""

from django.core.management.base import BaseCommand, CommandParser
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


class Command(BaseCommand):
    help = "Wipe all competition data (DESTRUCTIVE)"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Confirm that you want to delete all data",
        )

    def handle(self, *args: str, **options: object) -> None:
        if not options["confirm"]:
            self.stdout.write(
                self.style.ERROR("This command will DELETE ALL competition data!\nRun with --confirm to proceed.")
            )
            return

        self.stdout.write(self.style.WARNING("Wiping all competition data..."))

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
            "DiscordLink": DiscordLink.objects.all().delete()[0],
            "AuditLog": AuditLog.objects.all().delete()[0],
            "BotState": BotState.objects.all().delete()[0],
            "DashboardUpdate": DashboardUpdate.objects.all().delete()[0],
            "Team": Team.objects.all().delete()[0],
        }

        self.stdout.write(self.style.SUCCESS("\nDeleted:"))
        for model, count in counts.items():
            if count > 0:
                self.stdout.write(f"  {model}: {count}")

        self.stdout.write(self.style.SUCCESS("\nAll competition data wiped!"))
