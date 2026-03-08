"""Individual ticket action views."""

import logging
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from core.auth_utils import get_authentik_groups, get_authentik_id, has_permission
from core.models import DiscordTask
from core.tickets_config import get_category_config
from core.utils import get_team_from_groups
from team.models import DiscordLink
from ticketing.models import Ticket, TicketCategory, TicketHistory

logger = logging.getLogger(__name__)


def ticket_cancel(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Cancel an open ticket (team members only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    # Get user's team from Authentik groups
    user = cast(User, request.user)
    authentik_username = user.username
    groups = get_authentik_groups(user)
    team, _team_number, is_team = get_team_from_groups(groups)

    if not is_team or not team:
        return render(
            request,
            "error.html",
            {
                "error": "Invalid account",
                "message": "Your account is not associated with a team.",
            },
        )

    # Get ticket (must belong to user's team)
    try:
        ticket_obj = Ticket.objects.select_related("team").get(ticket_number=ticket_number, team=team)
    except Ticket.DoesNotExist:
        return render(
            request,
            "error.html",
            {
                "error": "Ticket not found",
                "message": f"Ticket {ticket_number} does not exist or does not belong to your team.",
            },
        )

    # Use shared atomic cancel function
    from ticketing.utils import cancel_ticket_atomic

    ticket, error = cancel_ticket_atomic(
        ticket_id=ticket_obj.id,
        actor_username=authentik_username,
        user=user,
    )

    if error or ticket is None:
        messages.error(request, error or "Failed to cancel ticket")
        return redirect("ticket_detail", ticket_number=ticket_number)

    logger.info(f"Ticket {ticket_number} cancelled by {authentik_username} via web")

    return redirect("ticket_list")


def ticket_claim(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Claim a ticket (operations team only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username = user.username
    get_authentik_id(user)

    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return HttpResponse("Access denied", status=403)

    # Get ticket to find ID
    try:
        ticket_obj = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    # Use shared atomic claim function
    from ticketing.utils import claim_ticket_atomic

    ticket, error = claim_ticket_atomic(
        ticket_id=ticket_obj.id,
        actor_username=authentik_username,
        user=user,
    )

    if error or ticket is None:
        messages.error(request, error or "Failed to claim ticket")
        return redirect("ticket_detail", ticket_number=ticket_number)

    # Add volunteer to thread if they have Discord linked and ticket has a thread
    if ticket.discord_thread_id:
        discord_link = DiscordLink.objects.filter(user=user, is_active=True).first()
        if discord_link:
            DiscordTask.create_add_user_to_thread(
                ticket=ticket, discord_id=discord_link.discord_id, thread_id=ticket.discord_thread_id
            )
        DiscordTask.create_post_ticket_update(ticket=ticket, action="claimed", actor=authentik_username)

    logger.info(f"Ticket {ticket_number} claimed by {authentik_username}")
    referer = request.META.get("HTTP_REFERER", "")
    if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect("ticket_list")


def ticket_unclaim(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Unclaim a ticket (operations team only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username = user.username

    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return HttpResponse("Access denied", status=403)

    # Get ticket to find ID
    try:
        ticket_obj = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    # Check if user claimed the ticket or is admin
    is_admin = has_permission(user, "ticketing_admin")
    has_claimed = ticket_obj.assigned_to and ticket_obj.assigned_to.username == authentik_username

    if not is_admin and not has_claimed:
        messages.error(request, "You can only unclaim tickets you have claimed")
        return redirect("ticket_detail", ticket_number=ticket_number)

    # Use shared atomic unclaim function
    from ticketing.utils import unclaim_ticket_atomic

    ticket, error = unclaim_ticket_atomic(
        ticket_id=ticket_obj.id,
        actor_username=authentik_username,
        user=user,
    )

    if error or ticket is None:
        messages.error(request, error or "Failed to unclaim ticket")
        return redirect("ticket_detail", ticket_number=ticket_number)

    # Post status update to Discord thread
    if ticket.discord_thread_id:
        DiscordTask.create_post_ticket_update(ticket=ticket, action="unclaimed", actor=authentik_username)

    logger.info(f"Ticket {ticket_number} unclaimed by {authentik_username}")
    referer = request.META.get("HTTP_REFERER", "")
    if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect("ticket_list")


def ticket_reassign(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Reassign a ticket to another support member (operations team only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username = user.username

    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return HttpResponse("Access denied", status=403)

    # Get ticket to find ID
    try:
        ticket_obj = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    # Get the new assignee from POST data
    new_assignee_username = request.POST.get("new_assignee_username", "").strip()
    if not new_assignee_username:
        messages.error(request, "New assignee username is required")
        return redirect("ticket_detail", ticket_number=ticket_number)

    # Find the user to assign
    new_assignee_user = User.objects.filter(username=new_assignee_username).first()
    if not new_assignee_user:
        messages.error(request, f"User '{new_assignee_username}' not found")
        return redirect("ticket_detail", ticket_number=ticket_number)

    # Use shared atomic reassign function
    from ticketing.utils import reassign_ticket_atomic

    ticket, error = reassign_ticket_atomic(
        ticket_id=ticket_obj.id,
        actor_username=authentik_username,
        user=new_assignee_user,
    )

    if error or ticket is None:
        messages.error(request, error or "Failed to reassign ticket")
        return redirect("ticket_detail", ticket_number=ticket_number)

    # Add new assignee to thread if they have Discord linked and ticket has a thread
    if ticket.discord_thread_id:
        discord_link = DiscordLink.objects.filter(user=new_assignee_user, is_active=True).first()
        if discord_link:
            DiscordTask.create_add_user_to_thread(
                ticket=ticket, discord_id=discord_link.discord_id, thread_id=ticket.discord_thread_id
            )

    logger.info(f"Ticket {ticket_number} reassigned to {new_assignee_username} by {authentik_username}")
    referer = request.META.get("HTTP_REFERER", "")
    if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect("ticket_list")


def ticket_resolve(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Resolve a ticket (operations team only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username = user.username
    get_authentik_id(user)

    is_ticketing_admin = has_permission(user, "ticketing_admin")

    if not (has_permission(user, "ticketing_support") or is_ticketing_admin):
        return HttpResponse("Access denied", status=403)

    # Get ticket to find ID
    try:
        ticket_obj = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    # Verify ownership: only the assigned user or admins can resolve
    assigned_username = ticket_obj.assigned_to.username if ticket_obj.assigned_to else None
    if not is_ticketing_admin and assigned_username != authentik_username:
        return HttpResponse(
            "Access denied: Only the assigned support member or administrators can resolve this ticket",
            status=403,
        )

    resolution_notes = request.POST.get("resolution_notes", "").strip()
    points_override_str = request.POST.get("points_override", "").strip()

    # Parse points override if provided
    points_override = None
    if points_override_str:
        try:
            points_override = int(points_override_str)
        except ValueError:
            messages.error(request, "Invalid points value. Must be a number.")
            return redirect("ticket_detail", ticket_number=ticket_number)

    # Use shared atomic resolve function
    from ticketing.utils import resolve_ticket_atomic

    ticket, error = resolve_ticket_atomic(
        ticket_id=ticket_obj.id,
        actor_username=authentik_username,
        resolution_notes=resolution_notes,
        points_override=points_override,
        user=user,
    )

    if error or ticket is None:
        messages.error(request, error or "Failed to resolve ticket")
        return redirect("ticket_detail", ticket_number=ticket_number)

    # Post resolution to Discord thread
    if ticket.discord_thread_id:
        DiscordTask.create_post_ticket_update(
            ticket=ticket,
            action="resolved",
            actor=authentik_username,
            resolution_notes=resolution_notes,
            points_charged=ticket.points_charged,
        )

    logger.info(f"Ticket {ticket_number} resolved by {authentik_username}")
    referer = request.META.get("HTTP_REFERER", "")
    if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect("ticket_list")


def ticket_reopen(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Reopen a resolved ticket (operations team only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username = user.username

    if not has_permission(user, "ticketing_admin"):
        return HttpResponse("Access denied - requires ticketing admin role", status=403)

    # Get ticket
    try:
        ticket_obj = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    reopen_reason = request.POST.get("reopen_reason", "").strip()

    # Use shared atomic reopen function
    from ticketing.utils import reopen_ticket_atomic

    ticket, error = reopen_ticket_atomic(
        ticket_id=ticket_obj.id,
        actor_username=authentik_username,
        reopen_reason=reopen_reason,
        user=user,
    )

    if error or ticket is None:
        messages.error(request, error or "Failed to reopen ticket")
        return redirect("ticket_detail", ticket_number=ticket_number)

    # Post status update to Discord thread
    if ticket.discord_thread_id:
        extra: dict[str, object] = {}
        if reopen_reason:
            extra["reason"] = reopen_reason
        DiscordTask.create_post_ticket_update(ticket=ticket, action="reopened", actor=authentik_username, **extra)

    logger.info(
        f"Ticket {ticket_number} reopened by {authentik_username}" + (f": {reopen_reason}" if reopen_reason else "")
    )
    referer = request.META.get("HTTP_REFERER", "")
    if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect("ticket_list")


def ticket_change_category(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Change ticket category."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username = user.username

    if not has_permission(user, "ticketing_support"):
        return HttpResponse("Access denied", status=403)

    # Get ticket
    try:
        ticket = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    # Check if user has claimed the ticket or is admin
    is_admin = has_permission(user, "ticketing_admin")
    has_claimed = ticket.assigned_to and ticket.assigned_to.username == authentik_username

    if not is_admin and not has_claimed:
        messages.error(request, "You must claim the ticket first")
        return redirect("ticket_detail", ticket_number=ticket_number)

    # Get new category
    try:
        new_category_id = int(request.POST.get("new_category", "0"))
    except ValueError, TypeError:
        new_category_id = 0

    if not TicketCategory.objects.filter(pk=new_category_id).exists():
        messages.error(request, "Invalid category")
        return redirect("ticket_detail", ticket_number=ticket_number)

    old_category_id = ticket.category_id
    if old_category_id == new_category_id:
        return redirect("ticket_detail", ticket_number=ticket_number)

    old_cat_info = get_category_config(old_category_id) or {}
    new_cat_info = get_category_config(new_category_id) or {}

    # Update category
    ticket.category_id = new_category_id
    ticket.save()

    # Create history entry
    TicketHistory.objects.create(
        ticket=ticket,
        action="category_changed",
        details={
            "changed_by": authentik_username,
            "old_category": old_category_id,
            "old_category_name": old_cat_info.get("display_name", "Unknown"),
            "new_category": new_category_id,
            "new_category_name": new_cat_info.get("display_name", "Unknown"),
            "old_points": old_cat_info.get("points", 0),
            "new_points": new_cat_info.get("points", 0),
        },
    )

    logger.info(
        f"Ticket {ticket_number} category changed by {authentik_username}: "
        f"{old_cat_info.get('display_name', 'Unknown')} → {new_cat_info.get('display_name', 'Unknown')}"
    )

    return redirect("ticket_detail", ticket_number=ticket_number)
