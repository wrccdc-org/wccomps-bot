"""Wipe all competition data (nuclear option)."""

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

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

    def handle(self, *args: Any, **options: Any) -> None:
        if not options["confirm"]:
            self.stdout.write(
                self.style.ERROR("This command will DELETE ALL competition data!\nRun with --confirm to proceed.")
            )
            return

        self.stdout.write(self.style.WARNING("Wiping all competition data..."))

        # Delete in order to avoid foreign key constraints
        counts = {
            "TicketAttachment": TicketAttachment.objects.all().delete()[0],
            "TicketComment": TicketComment.objects.all().delete()[0],
            "TicketHistory": TicketHistory.objects.all().delete()[0],
            "Ticket": Ticket.objects.all().delete()[0],
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
