"""Clear tickets at end of competition."""

from typing import Any

from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction

from core.models import AuditLog
from team.models import Team
from ticketing.models import Ticket, TicketAttachment, TicketComment, TicketHistory


class Command(BaseCommand):
    help = "Delete all tickets and reset counters"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Confirm that you want to delete all tickets",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not options["confirm"]:
            self.stdout.write(self.style.ERROR("This will DELETE ALL TICKETS!\nRun with --confirm to proceed."))
            return

        # Get counts before deletion
        ticket_count = Ticket.objects.count()
        attachment_count = TicketAttachment.objects.count()
        comment_count = TicketComment.objects.count()
        history_count = TicketHistory.objects.count()
        teams_to_reset = Team.objects.filter(ticket_counter__gt=0).count()

        self.stdout.write(self.style.WARNING("Clearing all tickets..."))
        self.stdout.write(f"  Tickets: {ticket_count}")
        self.stdout.write(f"  Attachments: {attachment_count}")
        self.stdout.write(f"  Comments: {comment_count}")
        self.stdout.write(f"  History: {history_count}")
        self.stdout.write(f"  Teams to reset: {teams_to_reset}\n")

        with transaction.atomic():
            # Delete all tickets (CASCADE handles related data)
            Ticket.objects.all().delete()

            # Reset team ticket counters
            Team.objects.filter(ticket_counter__gt=0).update(ticket_counter=0)

            # Create audit log
            AuditLog.objects.create(
                action="clear_tickets",
                admin_user="system:management_command",
                target_entity="tickets",
                target_id=0,
                details={
                    "tickets_deleted": ticket_count,
                    "attachments_deleted": attachment_count,
                    "comments_deleted": comment_count,
                    "history_deleted": history_count,
                    "teams_reset": teams_to_reset,
                },
            )

        self.stdout.write(self.style.SUCCESS("\nCompleted:"))
        self.stdout.write(f"  Deleted {ticket_count} tickets and all related data")
        self.stdout.write(f"  Reset {teams_to_reset} team ticket counters to 0")
        self.stdout.write(self.style.SUCCESS("\nDone!"))
