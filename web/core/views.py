"""Views for WCComps linking and OAuth."""

import logging
from typing import Any, Protocol, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import content_disposition_header

from core.models import DiscordTask
from team.models import DiscordLink, LinkAttempt, LinkToken, SchoolInfo, Team
from ticketing.models import Ticket, TicketAttachment, TicketComment, TicketHistory

from .auth_utils import get_permissions_context, has_permission
from .tickets_config import TICKET_CATEGORIES, TicketCategoryConfig
from .utils import get_authentik_data, get_team_from_groups


class ModelWithObjects(Protocol):
    objects: Any
    __name__: str


logger = logging.getLogger(__name__)


@login_required
def home(request: HttpRequest) -> HttpResponse:
    """Home page - redirect to appropriate dashboard based on user role."""
    import os

    # Get Authentik data
    user = cast(User, request.user)
    _authentik_username, groups, _ = get_authentik_data(user)

    # Get team information
    _team, _, is_team = get_team_from_groups(groups)

    # Check if ticketing is enabled
    ticketing_enabled = os.environ.get("TICKETING_ENABLED", "false").lower() == "true"

    # Redirect team members to tickets page
    if is_team and ticketing_enabled:
        return redirect("team_tickets")

    # Everyone else goes to ops pages
    if ticketing_enabled:
        return redirect("ops_ticket_list")
    # Ticketing disabled - redirect to school info or group role mappings
    if has_permission(user, "gold_team"):
        return redirect("ops_school_info")
    return redirect("ops_group_role_mappings")


def link_initiate(request: HttpRequest) -> HttpResponse:
    """Initiate OAuth linking flow."""
    token = request.GET.get("token")

    if not token:
        return HttpResponse("Missing token parameter", status=400)

    # Validate token
    try:
        link_token = LinkToken.objects.get(token=token, used=False)
    except LinkToken.DoesNotExist:
        return render(
            request,
            "link_error.html",
            {
                "error": "Invalid or expired token",
                "message": "This link has expired or is invalid. Please use /link in Discord to generate a new one.",
            },
        )

    if link_token.is_expired():
        return render(
            request,
            "link_error.html",
            {
                "error": "Token expired",
                "message": (
                    "This link has expired (15 minute limit). Please use /link in Discord to generate a new one."
                ),
            },
        )

    # Pass token through OAuth redirect via next parameter
    # This is more reliable than session storage which django-allauth may clear
    return redirect(f"/accounts/oidc/authentik/login/?next=/auth/callback?token={link_token.token}")


@login_required
def link_callback(request: HttpRequest) -> HttpResponse:
    """Handle OAuth callback after Authentik authentication."""
    # Clear any django-allauth success messages (we show our own)
    list(messages.get_messages(request))

    user = cast(User, request.user)
    try:
        # Get Authentik user info first
        authentik_username, groups, authentik_user_id = get_authentik_data(user)
    except Exception as e:
        logger.error(f"link_callback: Error getting Authentik data: {e}", exc_info=True)
        raise

    if not authentik_user_id:
        return render(
            request,
            "link_error.html",
            {
                "error": "Authentication error",
                "message": "Could not retrieve your Authentik account information.",
            },
        )

    # Retrieve token from URL parameter (passed through OAuth redirect)
    url_token = request.GET.get("token")

    if not url_token:
        return render(
            request,
            "link_error.html",
            {
                "error": "Invalid request",
                "message": (
                    "Missing authentication state. Please start the linking process again with /link in Discord."
                ),
            },
        )

    # Look up the specific token from URL
    try:
        link_token = LinkToken.objects.get(token=url_token, used=False)
    except LinkToken.DoesNotExist:
        return render(
            request,
            "link_error.html",
            {
                "error": "Invalid or expired token",
                "message": (
                    "This link has expired or been used already. Please use /link in Discord to generate a new one."
                ),
            },
        )

    # Verify token hasn't expired (double-check)
    if link_token.is_expired():
        return render(
            request,
            "link_error.html",
            {
                "error": "Token expired",
                "message": (
                    "This link has expired (15 minute limit). Please use /link in Discord to generate a new one."
                ),
            },
        )

    # Extract data from token
    token = link_token.token
    discord_id = link_token.discord_id
    discord_username = link_token.discord_username

    # Get team information
    team, team_number, is_team_account = get_team_from_groups(groups)

    # Check if this Authentik account is already linked to a different Discord account
    # For team accounts, multiple Discord users can link to the same Authentik account (shared team account)
    # For non-team accounts (admins/support), enforce one-to-one mapping
    if not is_team_account:
        existing_link = DiscordLink.objects.filter(authentik_user_id=authentik_user_id, is_active=True).first()

        if existing_link and existing_link.discord_id != discord_id:
            # This Authentik account is already linked to a different Discord account
            LinkAttempt.objects.create(
                discord_id=discord_id,
                discord_username=discord_username,
                authentik_username=authentik_username,
                team=team,
                success=False,
                failure_reason=f"Authentik account already linked to Discord user {existing_link.discord_username}",
            )
            return render(
                request,
                "link_error.html",
                {
                    "error": "Account already linked",
                    "message": (
                        f"This Authentik account ({authentik_username}) is already linked to "
                        f"Discord user {existing_link.discord_username}. "
                        "Each Authentik account can only be linked to one Discord account at a time. "
                        "Please contact an administrator if you need to unlink the previous account."
                    ),
                },
            )

    # For non-team accounts (admins/support), try to store discord_id in Authentik
    # This is optional - if it fails due to permissions, we still have DiscordLink
    if not is_team_account:
        try:
            from .authentik import AuthentikManager

            auth_manager = AuthentikManager()
            auth_manager.update_user_discord_id(authentik_user_id, discord_id)
            logger.info(f"Stored discord_id {discord_id} in Authentik for user {authentik_username}")
        except Exception as e:
            logger.warning(
                f"Could not store discord_id in Authentik (permissions issue): {e}. "
                f"Discord ID will be stored in DiscordLink table only."
            )

    # For team accounts: prevent race conditions with select_for_update
    if is_team_account and team:
        with transaction.atomic():
            # Lock the team row to prevent concurrent modifications
            team = Team.objects.select_for_update().get(pk=team.pk)

            # Check if team is full
            if team.is_full():
                LinkAttempt.objects.create(
                    discord_id=discord_id,
                    discord_username=discord_username,
                    authentik_username=authentik_username,
                    team=team,
                    success=False,
                    failure_reason=f"Team full ({team.get_member_count()}/{team.max_members})",
                )
                return render(
                    request,
                    "link_error.html",
                    {
                        "error": "Team full",
                        "message": (
                            f"{team.team_name} is full ({team.get_member_count()}/{team.max_members} members). "
                            "Please contact an administrator."
                        ),
                    },
                )

            # Create or update Discord link
            # Get active link if exists, otherwise create new
            try:
                link = DiscordLink.objects.get(discord_id=discord_id, is_active=True)
                # Update existing active link
                link.discord_username = discord_username
                link.authentik_username = authentik_username
                link.authentik_user_id = authentik_user_id
                link.team = team
                link.is_active = True
                link.linked_at = timezone.now()
                link.unlinked_at = None
                link.save()
            except DiscordLink.DoesNotExist:
                # Create new link (save() will deactivate any old ones)
                link = DiscordLink.objects.create(
                    discord_id=discord_id,
                    discord_username=discord_username,
                    authentik_username=authentik_username,
                    authentik_user_id=authentik_user_id,
                    team=team,
                    is_active=True,
                )
    else:
        # Non-team linking (admins/support): no locking needed
        # Get active link if exists, otherwise create new
        try:
            link = DiscordLink.objects.get(discord_id=discord_id, is_active=True)
            # Update existing active link
            link.discord_username = discord_username
            link.authentik_username = authentik_username
            link.authentik_user_id = authentik_user_id
            link.team = None
            link.is_active = True
            link.linked_at = timezone.now()
            link.unlinked_at = None
            link.save()
        except DiscordLink.DoesNotExist:
            # Create new link (save() will deactivate any old ones)
            link = DiscordLink.objects.create(
                discord_id=discord_id,
                discord_username=discord_username,
                authentik_username=authentik_username,
                authentik_user_id=authentik_user_id,
                team=None,
                is_active=True,
            )

    # Mark token as used
    try:
        link_token = LinkToken.objects.get(token=token)
        link_token.used = True
        link_token.save()
    except LinkToken.DoesNotExist:
        pass

    # Create link attempt record
    LinkAttempt.objects.create(
        discord_id=discord_id,
        discord_username=discord_username,
        authentik_username=authentik_username,
        team=team,
        success=True,
        failure_reason="",
    )

    # Create Discord task to assign group-based roles (for all accounts)
    DiscordTask.objects.create(
        task_type="assign_group_roles",
        payload={
            "discord_id": discord_id,
            "authentik_groups": groups,
        },
        status="pending",
    )

    # Create Discord task to assign role (only for team accounts)
    if is_team_account and team:
        DiscordTask.objects.create(
            task_type="assign_role",
            payload={"discord_id": discord_id, "team_number": team_number},
            status="pending",
        )

        # Create Discord task to log team member link
        DiscordTask.objects.create(
            task_type="log_to_channel",
            payload={"message": f"User Linked: <@{discord_id}> ({discord_username}) → **{team.team_name}**"},
            status="pending",
        )
        logger.info(f"Successfully linked {discord_username} ({discord_id}) to {team.team_name}")
    else:
        # Log non-team link (support/admin)
        DiscordTask.objects.create(
            task_type="log_to_channel",
            payload={
                "message": f"User Linked: <@{discord_id}> ({discord_username}) → **{authentik_username}** (non-team)"
            },
            status="pending",
        )
        logger.info(f"Successfully linked {discord_username} ({discord_id}) to {authentik_username}")

    # Clear any session data (no longer used, but clean up just in case)
    request.session.pop("pending_link_discord_id", None)

    return render(
        request,
        "link_success.html",
        {
            "team_name": team.team_name if team else None,
            "team_number": team_number,
            "discord_username": discord_username,
            "authentik_username": authentik_username,
            "is_team_account": is_team_account,
        },
    )


@login_required
def team_tickets(request: HttpRequest) -> HttpResponse:
    """View all tickets for user's team."""
    # Get user's team from Authentik groups
    user = cast(User, request.user)
    _authentik_username, groups, _ = get_authentik_data(user)
    team, _team_number, is_team = get_team_from_groups(groups)

    if not is_team or not team:
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Invalid account",
                "message": "Your account is not associated with a team.",
            },
        )

    # Get filter parameter
    status_filter = request.GET.get("status", "all")

    # Get tickets
    query = Ticket.objects.filter(team=team)

    if status_filter != "all":
        query = query.filter(status=status_filter)

    tickets = query.order_by("-created_at")

    # Enrich tickets with category info
    tickets_with_info = []
    for ticket in tickets:
        cat_info = TICKET_CATEGORIES.get(ticket.category, {})
        tickets_with_info.append(
            {
                "ticket": ticket,
                "category_name": cat_info.get("name", ticket.category),
                "status_display": ticket.status.upper().replace("_", " "),
            }
        )

    return render(
        request,
        "team_tickets.html",
        {"team": team, "tickets": tickets_with_info, "status_filter": status_filter},
    )


@login_required
def ticket_detail(request: HttpRequest, ticket_id: int) -> HttpResponse:
    """View details of a specific ticket."""
    # Get user's team from Authentik groups
    user = cast(User, request.user)
    _authentik_username, groups, _ = get_authentik_data(user)
    team, _team_number, is_team = get_team_from_groups(groups)

    if not is_team or not team:
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Invalid account",
                "message": "Your account is not associated with a team.",
            },
        )

    # Get ticket (must belong to user's team)
    try:
        ticket = Ticket.objects.select_related("team").get(id=ticket_id, team=team)
    except Ticket.DoesNotExist:
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Ticket not found",
                "message": f"Ticket #{ticket_id} does not exist or does not belong to your team.",
            },
        )

    # Get category info
    cat_info = TICKET_CATEGORIES.get(ticket.category, {})

    # Get comments
    comments = TicketComment.objects.filter(ticket=ticket).order_by("posted_at")

    # Get attachments
    attachments = TicketAttachment.objects.filter(ticket=ticket).order_by("uploaded_at")

    return render(
        request,
        "ticket_detail.html",
        {
            "team": team,
            "ticket": ticket,
            "category_name": cat_info.get("name", ticket.category),
            "comments": comments,
            "attachments": attachments,
            "status_display": ticket.status.upper().replace("_", " "),
        },
    )


@login_required
def ticket_comment(request: HttpRequest, ticket_id: int) -> HttpResponse:
    """Post a comment to a ticket from web UI."""
    if request.method != "POST":
        return HttpResponse(status=405)

    # Get user's team
    user = cast(User, request.user)
    authentik_username, groups, _ = get_authentik_data(user)
    team, _team_number, is_team = get_team_from_groups(groups)

    if not is_team or not team:
        return HttpResponse("Access denied", status=403)

    # Get ticket (must belong to user's team)
    try:
        ticket = Ticket.objects.select_related("team").get(id=ticket_id, team=team)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    # Get comment text
    comment_text = request.POST.get("comment", "").strip()
    if not comment_text:
        return HttpResponse("Comment cannot be empty", status=400)

    # Check rate limit
    from ticketing.models import CommentRateLimit

    is_allowed, reason = CommentRateLimit.check_rate_limit(ticket.id, user.id)
    if not is_allowed:
        return HttpResponse(reason, status=429)

    # Record rate limit
    CommentRateLimit.objects.create(ticket=ticket, discord_id=user.id)

    # Create comment
    comment = TicketComment.objects.create(
        ticket=ticket,
        author_name=authentik_username,
        author_discord_id=None,  # Web comment, no Discord ID
        comment_text=comment_text,
    )

    # Create Discord task to post to thread
    DiscordTask.objects.create(
        task_type="post_comment",
        ticket=ticket,
        payload={
            "ticket_id": ticket.id,
            "comment_id": comment.id,
        },
        status="pending",
    )

    logger.info(f"Comment posted on ticket #{ticket.id} by {authentik_username} (web)")

    return redirect("ticket_detail", ticket_id=ticket.id)


@login_required
def create_ticket(request: HttpRequest) -> HttpResponse:
    """Create a new support ticket (web form alternative to Discord command)."""
    # Get user's team
    user = cast(User, request.user)
    authentik_username, groups, _ = get_authentik_data(user)
    team, team_number, is_team = get_team_from_groups(groups)

    if not is_team or not team:
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Access denied",
                "message": "You must be a team member to create tickets.",
            },
        )

    # Fetch infrastructure from Quotient API
    from quotient.client import get_quotient_client

    quotient_client = get_quotient_client()
    infrastructure = quotient_client.get_infrastructure()
    service_choices = quotient_client.get_service_choices()
    box_names = quotient_client.get_box_names()

    # Build box mapping for IP lookups (box_name -> ip)
    box_ip_map = {}
    if infrastructure:
        for box in infrastructure.boxes:
            box_ip_map[box.name] = box.ip

    if request.method == "POST":
        category = request.POST.get("category")
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        hostname = request.POST.get("hostname", "").strip()
        ip_address = request.POST.get("ip_address", "").strip()
        service_name = request.POST.get("service_name", "").strip()

        # Validate category
        if category not in TICKET_CATEGORIES:
            return render(
                request,
                "create_ticket.html",
                {
                    "team": team,
                    "categories": TICKET_CATEGORIES,
                    "service_choices": service_choices,
                    "box_names": box_names,
                    "box_ip_map": box_ip_map,
                    "error": "Invalid ticket category selected.",
                },
            )

        cat_info: TicketCategoryConfig = TICKET_CATEGORIES[category]

        # Validate required fields
        errors = []
        if not title:
            errors.append("Title is required.")

        required_fields = cat_info.get("required_fields", [])
        if "hostname" in required_fields and not hostname:
            errors.append("Hostname is required for this category.")

        if "ip_address" in required_fields and not ip_address:
            errors.append("IP Address is required for this category.")

        if "service_name" in required_fields and not service_name:
            errors.append("Service Name is required for this category.")

        if "description" in required_fields and not description:
            errors.append("Description is required for this category.")

        if errors:
            return render(
                request,
                "create_ticket.html",
                {
                    "team": team,
                    "categories": TICKET_CATEGORIES,
                    "service_choices": service_choices,
                    "box_names": box_names,
                    "box_ip_map": box_ip_map,
                    "error": " ".join(errors),
                    "form_data": request.POST,
                },
            )

        # For box-reset, use hostname as description
        if category == "box-reset" and hostname:
            description = hostname

        # Create ticket using shared atomic function
        from ticketing.utils import create_ticket_atomic

        try:
            ticket = create_ticket_atomic(
                team=team,
                category=category,
                title=title,
                description=description,
                hostname=hostname,
                ip_address=ip_address,
                service_name=service_name,
                actor_username=authentik_username,
            )

            # Create Discord task to notify bot (so it can create thread)
            DiscordTask.objects.create(
                task_type="ticket_created_web",
                payload={
                    "ticket_id": ticket.id,
                    "ticket_number": ticket.ticket_number,
                    "team_number": team_number,
                    "category": category,
                    "title": title,
                    "created_by": authentik_username,
                },
                status="pending",
            )

            logger.info(f"Ticket {ticket.ticket_number} created via web by {authentik_username} for {team.team_name}")

            return redirect("ticket_detail", ticket_id=ticket.id)

        except Exception as e:
            logger.error(f"Failed to create ticket: {e}", exc_info=True)

            return render(
                request,
                "create_ticket.html",
                {
                    "team": team,
                    "categories": TICKET_CATEGORIES,
                    "service_choices": service_choices,
                    "box_names": box_names,
                    "box_ip_map": box_ip_map,
                    "error": (
                        f"Failed to create ticket: {e!s}. Please try again or contact support if the problem persists."
                    ),
                    "form_data": request.POST,
                },
            )

    # GET request - show form
    return render(
        request,
        "create_ticket.html",
        {
            "team": team,
            "categories": TICKET_CATEGORIES,
            "service_choices": service_choices,
            "box_names": box_names,
            "box_ip_map": box_ip_map,
        },
    )


@login_required
def ticket_cancel(request: HttpRequest, ticket_id: int) -> HttpResponse:
    """Cancel an open ticket (team members only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    # Get user's team from Authentik groups
    user = cast(User, request.user)
    authentik_username, groups, _ = get_authentik_data(user)
    team, _team_number, is_team = get_team_from_groups(groups)

    if not is_team or not team:
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Invalid account",
                "message": "Your account is not associated with a team.",
            },
        )

    # Get ticket (must belong to user's team)
    try:
        ticket = Ticket.objects.select_related("team").get(id=ticket_id, team=team)
    except Ticket.DoesNotExist:
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Ticket not found",
                "message": f"Ticket #{ticket_id} does not exist or does not belong to your team.",
            },
        )

    # Only allow cancellation if unclaimed
    if ticket.status != "open":
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Cannot cancel",
                "message": f"Ticket #{ticket_id} is already {ticket.status}. Only open tickets can be cancelled.",
            },
        )

    # Cancel ticket
    ticket.status = "cancelled"
    ticket.resolved_at = timezone.now()
    ticket.resolution_notes = f"Cancelled by {authentik_username} via web interface"
    ticket.save()

    # Create history entry
    TicketHistory.objects.create(
        ticket=ticket,
        action="cancelled",
        actor_username=authentik_username,
        details={"reason": "Cancelled by team member via web (unclaimed)"},
    )

    logger.info(f"Ticket #{ticket_id} cancelled by {authentik_username} via web")

    return redirect("team_tickets")


@login_required
def ticket_attachment_upload(request: HttpRequest, ticket_id: int) -> HttpResponse:
    """Upload an attachment to a ticket (team members only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    # Get user's team
    user = cast(User, request.user)
    authentik_username, groups, _ = get_authentik_data(user)
    team, _, is_team = get_team_from_groups(groups)

    if not is_team or not team:
        return HttpResponse("Access denied", status=403)

    # Get ticket (must belong to user's team)
    try:
        ticket = Ticket.objects.select_related("team").get(id=ticket_id, team=team)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    uploaded_file = request.FILES.get("attachment")
    if not uploaded_file:
        return HttpResponse("No file provided", status=400)

    # Check file size (limit to 10MB)
    max_size = 10 * 1024 * 1024  # 10MB
    if uploaded_file.size is None or uploaded_file.size > max_size:
        return HttpResponse("File too large (max 10MB)", status=400)

    # Validate filename
    if not uploaded_file.name:
        return HttpResponse("File must have a name", status=400)

    # Read file data
    file_data = uploaded_file.read()

    # Create attachment
    TicketAttachment.objects.create(
        ticket=ticket,
        file_data=file_data,
        filename=uploaded_file.name,
        mime_type=uploaded_file.content_type or "application/octet-stream",
        uploaded_by=authentik_username,
    )

    logger.info(f"Attachment {uploaded_file.name} uploaded to ticket #{ticket_id} by {authentik_username}")

    return redirect("ticket_detail", ticket_id=ticket_id)


@login_required
def ticket_attachment_download(request: HttpRequest, ticket_id: int, attachment_id: int) -> HttpResponse:
    """Download an attachment from a ticket (team members only)."""
    # Get user's team
    user = cast(User, request.user)
    _, groups, _ = get_authentik_data(user)
    team, _, is_team = get_team_from_groups(groups)

    if not is_team or not team:
        return HttpResponse("Access denied", status=403)

    # Get attachment (ticket must belong to user's team)
    try:
        attachment = TicketAttachment.objects.select_related("ticket", "ticket__team").get(
            id=attachment_id, ticket_id=ticket_id, ticket__team=team
        )
    except TicketAttachment.DoesNotExist:
        return HttpResponse("Attachment not found", status=404)

    response = HttpResponse(bytes(attachment.file_data), content_type=attachment.mime_type)
    response["Content-Disposition"] = str(content_disposition_header(as_attachment=True, filename=attachment.filename))
    return response


@login_required
def ops_ticket_list(request: HttpRequest) -> HttpResponse:
    """List all tickets with filtering for operations team."""
    from django.core.paginator import Paginator

    # Get user's permissions
    user = cast(User, request.user)
    authentik_username, _groups, _ = get_authentik_data(user)

    # Check permissions
    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Access denied",
                "message": "You do not have permission to access the ticket list.",
            },
        )

    # Get filter parameters
    status_filter = request.GET.get("status", "all") or "all"
    team_filter = request.GET.get("team", "")
    category_filter = request.GET.get("category", "all") or "all"
    assignee_filter = request.GET.get("assignee", "")
    search_query = request.GET.get("search", "").strip()
    sort_by = request.GET.get("sort", "-created_at")
    page_size_str = request.GET.get("page_size", "50")
    page = request.GET.get("page", "1")

    try:
        page_size = int(page_size_str)
        if page_size not in [25, 50, 100, 200]:
            page_size = 50
    except ValueError:
        page_size = 50

    # Build query
    from django.db.models import Count, Max

    query = Ticket.objects.select_related("team").annotate(
        comment_count=Count("comments"),
        attachment_count=Count("attachments"),
        last_activity=Max("history__timestamp"),
    )

    if status_filter != "all":
        query = query.filter(status=status_filter)

    if team_filter:
        try:
            team_number = int(team_filter)
            query = query.filter(team__team_number=team_number)
        except ValueError:
            pass

    if category_filter != "all":
        query = query.filter(category=category_filter)

    if assignee_filter:
        if assignee_filter == "unassigned":
            query = query.filter(assigned_to_discord_username="")
        else:
            query = query.filter(assigned_to_discord_username=assignee_filter)

    if search_query:
        from django.db.models import Q

        query = query.filter(
            Q(title__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(ticket_number__icontains=search_query)
            | Q(hostname__icontains=search_query)
            | Q(service_name__icontains=search_query)
        )

    # Validate and apply sort
    valid_sort_fields = [
        "created_at",
        "-created_at",
        "status",
        "-status",
        "team__team_number",
        "-team__team_number",
        "category",
        "-category",
        "assigned_to_discord_username",
        "-assigned_to_discord_username",
    ]
    if sort_by not in valid_sort_fields:
        sort_by = "-created_at"

    query = query.order_by(sort_by)

    # Enrich tickets with category info and stale status
    from datetime import timedelta

    thirty_minutes_ago = timezone.now() - timedelta(minutes=30)

    tickets_with_info = []
    for ticket in query:
        cat_info = TICKET_CATEGORIES.get(ticket.category, {})

        # Check if ticket is stale (claimed >30min)
        is_stale = ticket.status == "claimed" and ticket.assigned_at and ticket.assigned_at < thirty_minutes_ago

        tickets_with_info.append(
            {
                "ticket": ticket,
                "category_name": cat_info.get("display_name", ticket.category),
                "is_stale": is_stale,
                "status_display": ticket.status.upper().replace("_", " "),
            }
        )

    # Paginate
    paginator = Paginator(tickets_with_info, page_size)
    page_obj = paginator.get_page(page)

    # Get unique assignees for filter dropdown
    assignees = (
        Ticket.objects.exclude(assigned_to_discord_username="")
        .values_list("assigned_to_discord_username", flat=True)
        .distinct()
        .order_by("assigned_to_discord_username")
    )

    # Build permissions dict for template
    permissions = get_permissions_context(user)

    return render(
        request,
        "ops_ticket_list.html",
        {
            "authentik_username": authentik_username,
            "page_obj": page_obj,
            "status_filter": status_filter,
            "team_filter": team_filter,
            "category_filter": category_filter,
            "assignee_filter": assignee_filter,
            "assignees": assignees,
            "search_query": search_query,
            "sort_by": sort_by,
            "page_size": page_size,
            "categories": TICKET_CATEGORIES,
            "show_ops_nav": True,
            "nav_active": "tickets",
            **permissions,
        },
    )


@login_required
def ops_ticket_detail(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """View detailed ticket information for operations team."""
    # Get user's permissions
    user = cast(User, request.user)
    authentik_username, _groups, _ = get_authentik_data(user)

    # Check permissions
    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Access denied",
                "message": "You do not have permission to access ticket details.",
            },
        )

    # Get ticket by ticket_number (e.g., "T001-042")
    try:
        ticket = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Ticket not found",
                "message": f"Ticket {ticket_number} does not exist.",
            },
        )

    # Get category info
    cat_info = TICKET_CATEGORIES.get(ticket.category, {})

    # Get comments
    comments = TicketComment.objects.filter(ticket=ticket).order_by("posted_at")

    # Get history
    history = TicketHistory.objects.filter(ticket=ticket).order_by("-timestamp")[:20]

    # Get attachments
    attachments = TicketAttachment.objects.filter(ticket=ticket).order_by("uploaded_at")

    # Preserve filter state from referrer
    status_filter = request.GET.get("status", "")
    category_filter = request.GET.get("category", "")
    team_filter = request.GET.get("team", "")
    assignee_filter = request.GET.get("assignee", "")
    search_filter = request.GET.get("search", "")
    sort_filter = request.GET.get("sort", "")
    page_filter = request.GET.get("page", "")
    page_size = request.GET.get("page_size", "")

    # Build permissions dict for template
    permissions = get_permissions_context(user)

    return render(
        request,
        "ops_ticket_detail.html",
        {
            "authentik_username": authentik_username,
            "auto_refresh": True,
            "ticket": ticket,
            "category_name": cat_info.get("display_name", ticket.category),
            "comments": comments,
            "history": history,
            "attachments": attachments,
            "status_display": ticket.status.upper().replace("_", " "),
            "status_filter": status_filter,
            "category_filter": category_filter,
            "team_filter": team_filter,
            "assignee_filter": assignee_filter,
            "search_filter": search_filter,
            "sort_filter": sort_filter,
            "page_filter": page_filter,
            "page_size": page_size,
            "show_ops_nav": True,
            "nav_active": "tickets",
            **permissions,
        },
    )


@login_required
def ops_ticket_comment(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Post a comment to a ticket from ops UI."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username, _groups, _ = get_authentik_data(user)

    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return HttpResponse("Access denied", status=403)

    try:
        ticket = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    comment_text = request.POST.get("comment", "").strip()
    if not comment_text:
        return HttpResponse("Comment cannot be empty", status=400)

    # Check rate limit
    from ticketing.models import CommentRateLimit

    is_allowed, reason = CommentRateLimit.check_rate_limit(ticket.id, user.id)
    if not is_allowed:
        return HttpResponse(reason, status=429)

    CommentRateLimit.objects.create(ticket=ticket, discord_id=user.id)

    # Create comment
    comment = TicketComment.objects.create(
        ticket=ticket,
        author_name=authentik_username,
        author_discord_id=None,
        comment_text=comment_text,
    )

    # Create Discord task to post to thread
    DiscordTask.objects.create(
        task_type="post_comment",
        ticket=ticket,
        payload={
            "ticket_id": ticket.id,
            "comment_id": comment.id,
        },
        status="pending",
    )

    logger.info(f"Comment posted on ticket {ticket_number} by {authentik_username} (ops)")

    return redirect("ops_ticket_detail", ticket_number=ticket_number)


@login_required
def ops_ticket_claim(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Claim a ticket (operations team only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username, _groups, authentik_user_id = get_authentik_data(user)

    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return HttpResponse("Access denied", status=403)

    # Get ticket to find ID
    try:
        ticket_obj = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    # Try to find Discord link (optional for web UI)
    try:
        if authentik_user_id:
            discord_link = DiscordLink.objects.get(authentik_user_id=authentik_user_id, is_active=True)
        else:
            discord_link = DiscordLink.objects.get(authentik_username=authentik_username, is_active=True)
        discord_id = discord_link.discord_id
        discord_username = discord_link.discord_username
    except DiscordLink.DoesNotExist:
        discord_id = None
        discord_username = None

    # Use shared atomic claim function
    from ticketing.utils import claim_ticket_atomic

    ticket, error = claim_ticket_atomic(
        ticket_id=ticket_obj.id,
        actor_username=authentik_username,
        discord_id=discord_id,
        discord_username=discord_username,
        authentik_username=authentik_username,
        authentik_user_id=authentik_user_id,
    )

    if error or ticket is None:
        return HttpResponse(error or "Failed to claim ticket", status=400)

    # Add volunteer to thread if they have Discord linked and ticket has a thread
    if discord_id and ticket.discord_thread_id:
        DiscordTask.objects.create(
            task_type="add_user_to_thread",
            ticket=ticket,
            payload={
                "discord_id": discord_id,
                "thread_id": ticket.discord_thread_id,
            },
            status="pending",
        )

    logger.info(f"Ticket {ticket_number} claimed by {authentik_username}")
    return redirect(request.META.get("HTTP_REFERER", "ops_ticket_list"))


@login_required
def ops_ticket_unclaim(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Unclaim a ticket (operations team only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username, _groups, _authentik_user_id = get_authentik_data(user)

    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return HttpResponse("Access denied", status=403)

    # Get ticket to find ID
    try:
        ticket_obj = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    # Use shared atomic unclaim function
    from ticketing.utils import unclaim_ticket_atomic

    ticket, error = unclaim_ticket_atomic(
        ticket_id=ticket_obj.id,
        actor_username=authentik_username,
    )

    if error or ticket is None:
        return HttpResponse(error or "Failed to unclaim ticket", status=400)

    logger.info(f"Ticket {ticket_number} unclaimed by {authentik_username}")
    return redirect(request.META.get("HTTP_REFERER", "ops_ticket_list"))


@login_required
def ops_ticket_resolve(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Resolve a ticket (operations team only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username, _groups, authentik_user_id = get_authentik_data(user)

    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return HttpResponse("Access denied", status=403)

    # Get ticket to find ID
    try:
        ticket_obj = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    resolution_notes = request.POST.get("resolution_notes", "").strip()
    points_override_str = request.POST.get("points_override", "").strip()

    # Parse points override if provided
    points_override = None
    if points_override_str:
        try:
            points_override = int(points_override_str)
        except ValueError:
            return HttpResponse("Invalid points value. Must be a number.", status=400)

    # Try to find Discord link (optional for web UI)
    try:
        if authentik_user_id:
            discord_link = DiscordLink.objects.get(authentik_user_id=authentik_user_id, is_active=True)
        else:
            discord_link = DiscordLink.objects.get(authentik_username=authentik_username, is_active=True)
        discord_id = discord_link.discord_id
        discord_username = discord_link.discord_username
    except DiscordLink.DoesNotExist:
        discord_id = None
        discord_username = None

    # Use shared atomic resolve function
    from ticketing.utils import resolve_ticket_atomic

    ticket, error = resolve_ticket_atomic(
        ticket_id=ticket_obj.id,
        actor_username=authentik_username,
        resolution_notes=resolution_notes,
        points_override=points_override,
        discord_id=discord_id,
        discord_username=discord_username,
        authentik_username=authentik_username,
        authentik_user_id=authentik_user_id,
    )

    if error or ticket is None:
        return HttpResponse(error or "Failed to resolve ticket", status=400)

    logger.info(f"Ticket {ticket_number} resolved by {authentik_username}")
    return redirect(request.META.get("HTTP_REFERER", "ops_ticket_list"))


@login_required
def ops_ticket_reopen(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Reopen a resolved ticket (operations team only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username, _groups, _authentik_user_id = get_authentik_data(user)

    if not has_permission(user, "ticketing_admin"):
        return HttpResponse("Access denied - requires ticketing admin role", status=403)

    # Get ticket
    try:
        ticket = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    # Only allow reopening resolved tickets
    if ticket.status != "resolved":
        return HttpResponse(f"Cannot reopen - ticket is {ticket.status}", status=400)

    reopen_reason = request.POST.get("reopen_reason", "").strip()

    # Reopen ticket
    old_status = ticket.status
    ticket.status = "open"
    ticket.resolved_at = None
    ticket.save()

    # Create history entry
    details = {"old_status": old_status}
    if reopen_reason:
        details["reason"] = reopen_reason

    TicketHistory.objects.create(
        ticket=ticket,
        action="reopened",
        actor_username=authentik_username,
        details=details,
    )

    logger.info(
        f"Ticket {ticket_number} reopened by {authentik_username}" + (f": {reopen_reason}" if reopen_reason else "")
    )
    return redirect(request.META.get("HTTP_REFERER", "ops_ticket_list"))


@login_required
def ops_tickets_bulk_claim(request: HttpRequest) -> HttpResponse:
    """Bulk claim tickets (operations team only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username, _groups, authentik_user_id = get_authentik_data(user)

    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return HttpResponse("Access denied", status=403)

    ticket_numbers = request.POST.get("ticket_numbers", "").split(",")
    ticket_numbers = [tn.strip() for tn in ticket_numbers if tn.strip()]

    if not ticket_numbers:
        return HttpResponse("No tickets selected", status=400)

    # Try to find Discord link (optional for web UI)
    try:
        if authentik_user_id:
            discord_link = DiscordLink.objects.get(authentik_user_id=authentik_user_id, is_active=True)
        else:
            discord_link = DiscordLink.objects.get(authentik_username=authentik_username, is_active=True)
        discord_id = discord_link.discord_id
        discord_username = discord_link.discord_username
    except DiscordLink.DoesNotExist:
        # No Discord link - use Authentik identity only
        discord_id = None
        discord_username = None

    claimed_count = 0
    for ticket_number in ticket_numbers:
        try:
            ticket = Ticket.objects.get(ticket_number=ticket_number, status="open")
            ticket.status = "claimed"
            ticket.assigned_to_discord_id = discord_id
            ticket.assigned_to_discord_username = discord_username or ""
            ticket.assigned_to_authentik_username = authentik_username
            ticket.assigned_to_authentik_user_id = authentik_user_id or ""
            ticket.assigned_at = timezone.now()
            ticket.save()

            TicketHistory.objects.create(
                ticket=ticket,
                action="claimed",
                actor_username=authentik_username,
                details={"claimed_by": discord_username, "bulk": True},
            )

            claimed_count += 1
        except Ticket.DoesNotExist:
            continue

    logger.info(f"Bulk claimed {claimed_count} tickets by {authentik_username}")
    return redirect("ops_ticket_list")


@login_required
def ops_tickets_bulk_resolve(request: HttpRequest) -> HttpResponse:
    """Bulk resolve tickets (operations team only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username, _groups, authentik_user_id = get_authentik_data(user)

    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return HttpResponse("Access denied", status=403)

    ticket_numbers = request.POST.get("ticket_numbers", "").split(",")
    ticket_numbers = [tn.strip() for tn in ticket_numbers if tn.strip()]

    if not ticket_numbers:
        return HttpResponse("No tickets selected", status=400)

    # Try to find Discord link (optional for web UI)
    try:
        if authentik_user_id:
            discord_link = DiscordLink.objects.get(authentik_user_id=authentik_user_id, is_active=True)
        else:
            discord_link = DiscordLink.objects.get(authentik_username=authentik_username, is_active=True)
        discord_id = discord_link.discord_id
        discord_username = discord_link.discord_username
    except DiscordLink.DoesNotExist:
        # No Discord link - use Authentik identity only
        discord_id = None
        discord_username = None

    resolved_count = 0
    for ticket_number in ticket_numbers:
        try:
            ticket = Ticket.objects.get(ticket_number=ticket_number, status="claimed")
            ticket.status = "resolved"
            ticket.resolved_at = timezone.now()
            ticket.resolved_by_discord_id = discord_id
            ticket.resolved_by_discord_username = discord_username or ""
            ticket.resolved_by_authentik_username = authentik_username
            ticket.resolved_by_authentik_user_id = authentik_user_id or ""
            ticket.resolution_notes = "Bulk resolved via web interface"
            ticket.save()

            TicketHistory.objects.create(
                ticket=ticket,
                action="resolved",
                actor_username=authentik_username,
                details={"resolved_by": discord_username, "bulk": True},
            )

            resolved_count += 1
        except Ticket.DoesNotExist:
            continue

    logger.info(f"Bulk resolved {resolved_count} tickets by {authentik_username}")
    return redirect("ops_ticket_list")


@login_required
def ops_ticket_attachment_upload(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Upload an attachment to a ticket (operations team only)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username, _groups, _ = get_authentik_data(user)

    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return HttpResponse("Access denied", status=403)

    try:
        ticket = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    uploaded_file = request.FILES.get("attachment")
    if not uploaded_file:
        return HttpResponse("No file provided", status=400)

    # Check file size (limit to 10MB)
    max_size = 10 * 1024 * 1024  # 10MB
    if uploaded_file.size is None or uploaded_file.size > max_size:
        return HttpResponse("File too large (max 10MB)", status=400)

    # Validate filename
    if not uploaded_file.name:
        return HttpResponse("File must have a name", status=400)

    # Read file data
    file_data = uploaded_file.read()

    # Create attachment
    TicketAttachment.objects.create(
        ticket=ticket,
        file_data=file_data,
        filename=uploaded_file.name,
        mime_type=uploaded_file.content_type or "application/octet-stream",
        uploaded_by=authentik_username,
    )

    logger.info(f"Attachment {uploaded_file.name} uploaded to ticket {ticket_number} by {authentik_username}")

    return redirect("ops_ticket_detail", ticket_number=ticket_number)


@login_required
def ops_ticket_attachment_download(request: HttpRequest, ticket_number: str, attachment_id: int) -> HttpResponse:
    """Download an attachment from a ticket (operations team only)."""
    user = cast(User, request.user)

    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return HttpResponse("Access denied", status=403)

    try:
        attachment = TicketAttachment.objects.select_related("ticket").get(
            id=attachment_id, ticket__ticket_number=ticket_number
        )
    except TicketAttachment.DoesNotExist:
        return HttpResponse("Attachment not found", status=404)

    response = HttpResponse(bytes(attachment.file_data), content_type=attachment.mime_type)
    response["Content-Disposition"] = str(content_disposition_header(as_attachment=True, filename=attachment.filename))
    return response


@login_required
def ops_school_info(request: HttpRequest) -> HttpResponse:
    """View and edit school information (GoldTeam only)."""
    # Get user's permissions
    user = cast(User, request.user)
    authentik_username, _groups, _ = get_authentik_data(user)

    # Check if user is GoldTeam
    if not has_permission(user, "gold_team"):
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Access denied",
                "message": (
                    "You do not have permission to access school information. This requires WCComps_GoldTeam role."
                ),
            },
        )

    # Get all teams with their school info
    teams = Team.objects.filter(is_active=True).order_by("team_number")

    # Enrich teams with school info
    teams_with_info = []
    for team in teams:
        try:
            school_info = team.school_info
        except SchoolInfo.DoesNotExist:
            school_info = None

        teams_with_info.append({"team": team, "school_info": school_info})

    # Build permissions dict for template
    permissions = get_permissions_context(user)

    return render(
        request,
        "ops_school_info.html",
        {
            "authentik_username": authentik_username,
            "teams": teams_with_info,
            "show_ops_nav": True,
            "nav_active": "school",
            **permissions,
        },
    )


@login_required
def ops_school_info_edit(request: HttpRequest, team_number: int) -> HttpResponse:
    """Edit school information for a team (GoldTeam only)."""
    # Get user's permissions
    user = cast(User, request.user)
    authentik_username, _groups, _ = get_authentik_data(user)

    # Check if user is GoldTeam
    if not has_permission(user, "gold_team"):
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Access denied",
                "message": "You do not have permission to edit school information.",
            },
        )

    # Get team
    try:
        team = Team.objects.get(team_number=team_number, is_active=True)
    except Team.DoesNotExist:
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Team not found",
                "message": f"Team {team_number} does not exist.",
            },
        )

    # Get or create school info
    try:
        school_info = team.school_info
    except SchoolInfo.DoesNotExist:
        school_info = None

    # Build permissions dict for template
    permissions = get_permissions_context(user)

    if request.method == "POST":
        school_name = request.POST.get("school_name", "").strip()
        contact_email = request.POST.get("contact_email", "").strip()
        secondary_email = request.POST.get("secondary_email", "").strip()
        notes = request.POST.get("notes", "").strip()

        # Validate required fields
        if not school_name:
            return render(
                request,
                "ops_school_info_edit.html",
                {
                    "authentik_username": authentik_username,
                    "team": team,
                    "school_info": school_info,
                    "error": "School name is required.",
                    **permissions,
                },
            )

        if not contact_email:
            return render(
                request,
                "ops_school_info_edit.html",
                {
                    "authentik_username": authentik_username,
                    "team": team,
                    "school_info": school_info,
                    "error": "Contact email is required.",
                    **permissions,
                },
            )

        # Create or update school info
        if school_info:
            school_info.school_name = school_name
            school_info.contact_email = contact_email
            school_info.secondary_email = secondary_email
            school_info.notes = notes
            school_info.updated_by = authentik_username
            school_info.save()
        else:
            school_info = SchoolInfo.objects.create(
                team=team,
                school_name=school_name,
                contact_email=contact_email,
                secondary_email=secondary_email,
                notes=notes,
                updated_by=authentik_username,
            )

        logger.info(f"School info updated for Team {team_number} by {authentik_username}")

        return redirect("ops_school_info")

    return render(
        request,
        "ops_school_info_edit.html",
        {
            "authentik_username": authentik_username,
            "team": team,
            "school_info": school_info,
            "show_ops_nav": True,
            "nav_active": "school",
            **permissions,
        },
    )


def custom_logout(request: HttpRequest) -> HttpResponse:
    """Custom logout view that ends both Django and Authentik SSO sessions."""
    from urllib.parse import urlencode

    from django.conf import settings
    from django.contrib.auth import logout

    # Clear Django session
    logout(request)

    # Build Authentik logout URL with post_logout_redirect_uri
    providers = cast(dict[str, Any], settings.SOCIALACCOUNT_PROVIDERS)
    apps_list = cast(list[dict[str, Any]], providers["openid_connect"]["APPS"])
    app_settings = cast(dict[str, Any], apps_list[0]["settings"])
    authentik_logout_url = cast(
        str,
        app_settings.get(
            "end_session_endpoint",
            "https://auth.wccomps.org/application/o/discord-bot/end-session/",
        ),
    )

    # Add redirect parameter so Authentik sends user back to our homepage after logout
    redirect_uri = request.build_absolute_uri("/")
    logout_params = urlencode({"post_logout_redirect_uri": redirect_uri})
    full_logout_url = f"{authentik_logout_url}?{logout_params}"

    return redirect(full_logout_url)


@login_required
def ops_group_role_mappings(request: HttpRequest) -> HttpResponse:
    """View team membership status and linked users (GoldTeam only)."""
    # Get user's permissions
    user = cast(User, request.user)
    authentik_username, _groups, _ = get_authentik_data(user)

    # Check if user is GoldTeam
    if not has_permission(user, "gold_team"):
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Access denied",
                "message": "You do not have permission to access team mappings. This requires WCComps_GoldTeam role.",
            },
        )

    # Get all active teams with their linked members
    teams = Team.objects.filter(is_active=True).order_by("team_number")

    team_status = []
    for team in teams:
        # Get active links for this team
        links = DiscordLink.objects.filter(team=team, is_active=True).select_related("team")

        # Format member list
        members = [
            {
                "discord_id": link.discord_id,
                "discord_username": link.discord_username or "Unknown",
                "authentik_username": link.authentik_username,
            }
            for link in links
        ]

        team_status.append(
            {
                "team": team,
                "current_count": len(members),
                "max_count": team.max_members,
                "members": members,
                "is_full": len(members) >= team.max_members,
            }
        )

    # Build permissions dict for template
    permissions = get_permissions_context(user)

    return render(
        request,
        "ops_group_role_mappings.html",
        {
            "authentik_username": authentik_username,
            "team_status": team_status,
            "show_ops_nav": True,
            "nav_active": "mappings",
            **permissions,
        },
    )


def health_check(request: HttpRequest) -> HttpResponse:
    """Health check endpoint for monitoring - tests database connectivity and model queries."""
    import json

    from django.apps import apps
    from django.db import connection

    errors = []

    # Check database connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as e:
        errors.append(f"Database connection: {e!s}")

    # Check all models are queryable
    core_models = apps.get_app_config("core").get_models()
    for model_class in core_models:
        try:
            # Cast to ModelWithObjects protocol to access objects manager
            # django-stubs doesn't expose objects on type[Model]
            typed_model = cast("ModelWithObjects", model_class)
            typed_model.objects.exists()
        except Exception as e:
            errors.append(f"{model_class.__name__}: {str(e)[:100]}")

    if errors:
        return HttpResponse(
            json.dumps({"status": "unhealthy", "errors": errors}),
            content_type="application/json",
            status=503,
        )

    return HttpResponse(
        json.dumps({"status": "healthy"}),
        content_type="application/json",
        status=200,
    )
