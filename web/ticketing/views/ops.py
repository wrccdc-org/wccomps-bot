"""Operations/admin review views."""

import logging
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from core.auth_utils import require_permission
from core.tickets_config import get_all_categories, get_category_config
from ticketing.models import Ticket, TicketHistory

logger = logging.getLogger(__name__)


@require_permission(
    "ticketing_admin", "gold_team", error_message="Only Ticketing Admins or Gold Team can review tickets"
)
def ops_review_tickets(request: HttpRequest) -> HttpResponse:
    """Review resolved tickets for point approval."""
    # Get filter parameters
    status_filter = request.GET.get("status", "pending") or "pending"
    team_filter = request.GET.get("team", "")
    search_query = request.GET.get("search", "").strip()
    category_filter = request.GET.get("category", "")
    sort_by = request.GET.get("sort", "-resolved_at")
    if sort_by == "default":
        sort_by = ""
    page = request.GET.get("page", "1")

    # Build query - only show resolved tickets
    query = Ticket.objects.filter(status="resolved").select_related("team", "approved_by")

    if status_filter == "approved":
        query = query.filter(is_approved=True)
    elif status_filter == "pending":
        query = query.filter(is_approved=False)

    if category_filter:
        query = query.filter(category_id=category_filter)

    if team_filter:
        try:
            team_number = int(team_filter)
            query = query.filter(team__team_number=team_number)
        except ValueError:
            pass

    if search_query:
        query = query.filter(
            Q(title__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(ticket_number__icontains=search_query)
            | Q(hostname__icontains=search_query)
            | Q(service_name__icontains=search_query)
        )

    # Validate and apply sort
    valid_sort_fields = [
        "resolved_at",
        "-resolved_at",
        "points_charged",
        "-points_charged",
        "team__team_number",
        "-team__team_number",
        "category",
        "-category",
    ]
    if sort_by and sort_by not in valid_sort_fields:
        sort_by = "-resolved_at"

    if sort_by:
        query = query.order_by(sort_by)

    # Enrich tickets with category info
    tickets_with_info = []
    for ticket in query:
        cat_info = get_category_config(ticket.category_id) or {}
        tickets_with_info.append(
            {
                "ticket": ticket,
                "category_name": cat_info.get("display_name", "Unknown"),
                "expected_points": cat_info.get("points", 0),
            }
        )

    # Paginate
    paginator = Paginator(tickets_with_info, 50)
    page_obj = paginator.get_page(page)

    context = {
        "page_obj": page_obj,
        "status_filter": status_filter,
        "team_filter": team_filter,
        "category_filter": category_filter,
        "search_query": search_query,
        "sort_by": sort_by,
        "categories": get_all_categories(),
        "has_pending": Ticket.objects.filter(status="resolved", is_approved=False).exists(),
        "show_ops_nav": True,
    }

    # Return partial for htmx requests
    if request.headers.get("HX-Request"):
        return render(request, "cotton/review_tickets_table.html", context)

    return render(request, "ops_review_tickets.html", context)


@require_permission(
    "ticketing_admin", "gold_team", error_message="Only Ticketing Admins or Gold Team can verify tickets"
)
def ops_verify_ticket(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Verify ticket points (admin only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username = user.username

    # Get ticket
    try:
        ticket = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    # Only allow verifying resolved tickets
    if ticket.status != "resolved":
        messages.error(request, f"Cannot verify - ticket is {ticket.status}, must be resolved")
        return redirect("ticket_detail", ticket_number=ticket_number)

    # Get form data
    points_adjustment_str = request.POST.get("points_adjustment", "").strip()
    approval_notes = request.POST.get("verification_notes", "").strip()

    # Parse points adjustment if provided
    if points_adjustment_str:
        try:
            adjusted_points = int(points_adjustment_str)
            ticket.points_charged = adjusted_points
        except ValueError:
            messages.error(request, "Invalid points value. Must be a number.")
            return redirect("ticket_detail", ticket_number=ticket_number)

    # Mark as verified
    ticket.is_approved = True
    ticket.approved_by = user
    ticket.approved_at = timezone.now()
    ticket.approval_notes = approval_notes
    ticket.save()

    # Create history entry
    TicketHistory.objects.create(
        ticket=ticket,
        action="points_verified",
        details={
            "verified_by": authentik_username,
            "points_charged": ticket.points_charged,
            "approval_notes": approval_notes,
        },
    )

    logger.info(f"Ticket {ticket_number} points verified by {authentik_username}: {ticket.points_charged} points")

    referer = request.META.get("HTTP_REFERER", "")
    if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect("ops_review_tickets")


@require_permission(
    "ticketing_admin", "gold_team", error_message="Only Ticketing Admins or Gold Team can batch verify tickets"
)
@require_http_methods(["POST"])
def ops_batch_verify_tickets(request: HttpRequest) -> HttpResponse:
    """Bulk approve selected ticket points."""
    user = cast(User, request.user)
    authentik_username = user.username
    ticket_ids = request.POST.getlist("ticket_ids")

    if not ticket_ids:
        messages.info(request, "No tickets selected for approval")
        return redirect("ops_review_tickets")

    valid_ids = []
    for tid in ticket_ids:
        try:
            valid_ids.append(int(tid))
        except ValueError, TypeError:
            continue

    if not valid_ids:
        messages.warning(request, "No valid ticket IDs provided")
        return redirect("ops_review_tickets")

    now = timezone.now()
    approved_count = 0
    for ticket in Ticket.objects.filter(id__in=valid_ids, is_approved=False, status="resolved"):
        ticket.is_approved = True
        ticket.approved_by = user
        ticket.approved_at = now
        ticket.save()

        TicketHistory.objects.create(
            ticket=ticket,
            action="points_verified",
            details={
                "verified_by": authentik_username,
                "points_charged": ticket.points_charged,
                "batch": True,
            },
        )
        approved_count += 1

    if approved_count > 0:
        messages.success(request, f"Successfully approved {approved_count} ticket(s)")
    else:
        messages.info(request, "No unapproved tickets found to approve")

    logger.info(f"Batch approved {approved_count} tickets by {authentik_username}")
    return redirect("ops_review_tickets")
