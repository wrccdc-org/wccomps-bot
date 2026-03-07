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

from core.auth_utils import has_permission
from core.tickets_config import get_all_categories, get_category_config
from ticketing.models import Ticket, TicketHistory

logger = logging.getLogger(__name__)


def ops_review_tickets(request: HttpRequest) -> HttpResponse:
    """Review resolved tickets for point verification (admin only)."""
    # Get user's permissions
    user = cast(User, request.user)

    # Check if user is ticketing admin
    if not has_permission(user, "ticketing_admin"):
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Access denied",
                "message": "You do not have permission to review tickets. This requires ticketing admin role.",
            },
        )

    # Get filter parameters
    verified_filter = request.GET.get("verified", "unverified") or "unverified"
    team_filter = request.GET.get("team", "")
    search_query = request.GET.get("search", "").strip()
    sort_by = request.GET.get("sort", "-resolved_at")
    if sort_by == "default":
        sort_by = ""
    page_size_str = request.GET.get("page_size", "50")
    page = request.GET.get("page", "1")

    try:
        page_size = int(page_size_str)
        if page_size not in [25, 50, 100, 200]:
            page_size = 50
    except ValueError:
        page_size = 50

    # Build query - only show resolved tickets
    query = Ticket.objects.filter(status="resolved").select_related("team", "points_verified_by")

    if verified_filter == "verified":
        query = query.filter(points_verified=True)
    elif verified_filter == "unverified":
        query = query.filter(points_verified=False)

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
    paginator = Paginator(tickets_with_info, page_size)
    page_obj = paginator.get_page(page)

    context = {
        "page_obj": page_obj,
        "verified_filter": verified_filter,
        "team_filter": team_filter,
        "search_query": search_query,
        "sort_by": sort_by,
        "page_size": page_size,
        "categories": get_all_categories(),
        "show_ops_nav": True,
    }

    # Return partial for htmx requests
    if request.headers.get("HX-Request"):
        return render(request, "cotton/review_tickets_table.html", context)

    return render(request, "ops_review_tickets.html", context)


def ops_verify_ticket(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Verify ticket points (admin only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username = user.username

    if not has_permission(user, "ticketing_admin"):
        return HttpResponse("Access denied - requires ticketing admin role", status=403)

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
    verification_notes = request.POST.get("verification_notes", "").strip()

    # Parse points adjustment if provided
    if points_adjustment_str:
        try:
            adjusted_points = int(points_adjustment_str)
            ticket.points_charged = adjusted_points
        except ValueError:
            messages.error(request, "Invalid points value. Must be a number.")
            return redirect("ticket_detail", ticket_number=ticket_number)

    # Mark as verified
    ticket.points_verified = True
    ticket.points_verified_by = user
    ticket.points_verified_at = timezone.now()
    ticket.verification_notes = verification_notes
    ticket.save()

    # Create history entry
    TicketHistory.objects.create(
        ticket=ticket,
        action="points_verified",
        details={
            "verified_by": authentik_username,
            "points_charged": ticket.points_charged,
            "verification_notes": verification_notes,
        },
    )

    logger.info(f"Ticket {ticket_number} points verified by {authentik_username}: {ticket.points_charged} points")

    referer = request.META.get("HTTP_REFERER", "")
    if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect("ops_review_tickets")


def ops_batch_verify_tickets(request: HttpRequest) -> HttpResponse:
    """Batch verify all unverified resolved ticket points (admin only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username = user.username

    if not has_permission(user, "ticketing_admin"):
        return HttpResponse("Access denied - requires ticketing admin role", status=403)

    # Get all unverified resolved tickets
    unverified_tickets = Ticket.objects.filter(status="resolved", points_verified=False).select_related("team")

    verified_count = 0
    for ticket in unverified_tickets:
        # Mark as verified
        ticket.points_verified = True
        ticket.points_verified_by = user
        ticket.points_verified_at = timezone.now()
        ticket.save()

        # Create history entry
        TicketHistory.objects.create(
            ticket=ticket,
            action="points_verified",
            details={
                "verified_by": authentik_username,
                "points_charged": ticket.points_charged,
                "batch": True,
            },
        )

        verified_count += 1

    logger.info(f"Batch verified {verified_count} tickets by {authentik_username}")
    return redirect("ops_review_tickets")
