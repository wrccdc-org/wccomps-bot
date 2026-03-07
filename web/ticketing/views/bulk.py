"""Bulk ticket operations views."""

import logging
from typing import cast

from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils import timezone

from core.auth_utils import get_authentik_id, has_permission
from ticketing.models import Ticket, TicketHistory

logger = logging.getLogger(__name__)


def tickets_bulk_claim(request: HttpRequest) -> HttpResponse:
    """Bulk claim tickets (operations team only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username = user.username
    get_authentik_id(user)

    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return HttpResponse("Access denied", status=403)

    ticket_numbers = request.POST.get("ticket_numbers", "").split(",")
    ticket_numbers = [tn.strip() for tn in ticket_numbers if tn.strip()]

    if not ticket_numbers:
        return HttpResponse("No tickets selected", status=400)

    claimed_count = 0
    with transaction.atomic():
        for ticket_number in ticket_numbers:
            try:
                # Use select_for_update to prevent race conditions
                ticket = Ticket.objects.select_for_update().get(ticket_number=ticket_number, status="open")
                ticket.status = "claimed"
                ticket.assigned_to = user
                ticket.assigned_at = timezone.now()
                ticket.save()

                TicketHistory.objects.create(
                    ticket=ticket,
                    action="claimed",
                    actor=user,
                    details={"claimed_by": authentik_username, "bulk": True},
                )

                claimed_count += 1
            except Ticket.DoesNotExist:
                continue

    logger.info(f"Bulk claimed {claimed_count} tickets by {authentik_username}")
    return redirect("ticket_list")


def tickets_bulk_resolve(request: HttpRequest) -> HttpResponse:
    """Bulk resolve tickets (operations team only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username = user.username
    get_authentik_id(user)

    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return HttpResponse("Access denied", status=403)

    ticket_numbers = request.POST.get("ticket_numbers", "").split(",")
    ticket_numbers = [tn.strip() for tn in ticket_numbers if tn.strip()]

    if not ticket_numbers:
        return HttpResponse("No tickets selected", status=400)

    resolved_count = 0
    with transaction.atomic():
        for ticket_number in ticket_numbers:
            try:
                # Use select_for_update to prevent race conditions
                ticket = Ticket.objects.select_for_update().get(ticket_number=ticket_number, status="claimed")
                ticket.status = "resolved"
                ticket.resolved_at = timezone.now()
                ticket.resolved_by = user
                ticket.resolution_notes = "Bulk resolved via web interface"
                ticket.save()

                TicketHistory.objects.create(
                    ticket=ticket,
                    action="resolved",
                    actor=user,
                    details={"resolved_by": authentik_username, "bulk": True},
                )

                resolved_count += 1
            except Ticket.DoesNotExist:
                continue

    logger.info(f"Bulk resolved {resolved_count} tickets by {authentik_username}")
    return redirect("ticket_list")


def tickets_clear_all(request: HttpRequest) -> HttpResponse:
    """Clear all tickets and reset counters (admin only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username = user.username

    if not has_permission(user, "ticketing_admin"):
        return HttpResponse("Access denied - admin only", status=403)

    from core.models import AuditLog
    from team.models import Team
    from ticketing.models import TicketAttachment, TicketComment, TicketHistory

    # Get counts before deletion
    ticket_count = Ticket.objects.count()
    attachment_count = TicketAttachment.objects.count()
    comment_count = TicketComment.objects.count()
    history_count = TicketHistory.objects.count()
    teams_to_reset = Team.objects.filter(ticket_counter__gt=0).count()

    with transaction.atomic():
        # Delete all tickets (CASCADE handles related data)
        Ticket.objects.all().delete()

        # Reset team ticket counters
        Team.objects.filter(ticket_counter__gt=0).update(ticket_counter=0)

        # Create audit log
        AuditLog.objects.create(
            action="clear_tickets",
            admin_user=authentik_username,
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

    logger.info(f"Cleared all tickets ({ticket_count}) by {authentik_username}")
    return redirect("ticket_list")
