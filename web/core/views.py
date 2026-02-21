"""Views for WCComps linking and OAuth."""

import contextlib
import logging
from typing import Protocol, cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Manager
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import content_disposition_header, url_has_allowed_host_and_scheme

from core.models import DiscordTask
from team.models import DiscordLink, LinkAttempt, LinkToken, SchoolInfo, Team
from ticketing.models import Ticket, TicketAttachment, TicketCategory, TicketComment, TicketHistory

from .auth_utils import get_authentik_groups, get_authentik_id, get_permissions_context, has_permission
from .tickets_config import TicketCategoryConfig, get_all_categories, get_category_config
from .utils import get_team_from_groups


class ModelWithObjects(Protocol):
    # Generic Protocol for iterating any model, Manager[T] requires T: Model
    objects: Manager  # type: ignore[type-arg]
    __name__: str


logger = logging.getLogger(__name__)

MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB

# MIME types safe for inline viewing (no XSS risk)
INLINE_SAFE_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/pdf",
}


def _save_attachment(ticket: Ticket, uploaded_file: UploadedFile | None, uploaded_by: str) -> HttpResponse | None:
    """
    Validate and save an attachment. Returns HttpResponse on error, None on success.
    """
    if not uploaded_file:
        return HttpResponse("No file provided", status=400)

    if uploaded_file.size is None or uploaded_file.size > MAX_ATTACHMENT_SIZE:
        uploaded_file.close()
        return HttpResponse("File too large (max 10MB)", status=400)

    if not uploaded_file.name:
        uploaded_file.close()
        return HttpResponse("File must have a name", status=400)

    try:
        TicketAttachment.objects.create(
            ticket=ticket,
            file_data=uploaded_file.read(),
            filename=uploaded_file.name,
            mime_type=uploaded_file.content_type or "application/octet-stream",
            uploaded_by=uploaded_by,
        )
    finally:
        uploaded_file.close()
    return None


def home(request: HttpRequest) -> HttpResponse:
    """Home page - redirect to appropriate dashboard based on user role."""
    user = cast(User, request.user)
    groups = get_authentik_groups(user)
    _team, _, is_team = get_team_from_groups(groups)

    # Check roles in priority order — admin/ops first, then team-specific portals
    if (
        has_permission(user, "admin")
        or has_permission(user, "ticketing_admin")
        or has_permission(user, "ticketing_support")
    ):
        return redirect("ticket_list")
    if has_permission(user, "gold_team"):
        return redirect("scoring:leaderboard")
    if has_permission(user, "red_team"):
        return redirect("scoring:submit_red_score")
    if has_permission(user, "orange_team"):
        return redirect("scoring:orange_team_portal")
    if is_team:
        return redirect("ticket_list")

    # Fallback - redirect to leaderboard (public view)
    return redirect("scoring:leaderboard")


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

    # Store token in session for CSRF protection
    request.session["pending_link_token"] = link_token.token
    request.session["pending_link_discord_id"] = link_token.discord_id

    # Pass token through OAuth redirect via next parameter
    return redirect(f"/auth/login/?next=/auth/link-callback?token={link_token.token}")


def link_callback(request: HttpRequest) -> HttpResponse:
    """Handle OAuth callback after Authentik authentication."""
    # Clear any django-allauth success messages (we show our own)
    list(messages.get_messages(request))

    user = cast(User, request.user)
    try:
        # Get Authentik user info first
        authentik_username = user.username
        groups = get_authentik_groups(user)
        authentik_user_id = get_authentik_id(user)
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

    # Session check for additional CSRF protection (defense-in-depth)
    # Note: django-allauth cycles the session on login, so this check may fail for legitimate
    # users. The URL token already provides strong security (cryptographically random, single-use,
    # time-limited, tied to Discord user), so we log but don't block on session mismatch.
    session_token = request.session.get("pending_link_token")
    if session_token and session_token != url_token:
        # Session exists but doesn't match - this is suspicious
        logger.warning(
            f"Session token mismatch: session '{session_token}' != url '{url_token}' for user {authentik_username}"
        )
        return render(
            request,
            "link_error.html",
            {
                "error": "Security verification failed",
                "message": (
                    "The linking request could not be verified. This may be a CSRF attack attempt. "
                    "Please start the linking process again with /link in Discord."
                ),
            },
        )
    if not session_token:
        # Session was cycled during OAuth login - this is expected behavior
        logger.info(f"Session token not found (likely cycled during OAuth) for user {authentik_username}")

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
        existing_link = DiscordLink.objects.filter(user=user, is_active=True).first()

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
                link.user = user
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
                    user=user,
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
            link.user = user
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
                user=user,
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

    # Clear session data used for CSRF protection
    request.session.pop("pending_link_token", None)
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


def ticket_list(request: HttpRequest) -> HttpResponse:
    """Unified ticket list view for both team members and ops staff."""
    from datetime import timedelta

    from django.core.paginator import Paginator
    from django.db.models import Count, Max, Q

    user = cast(User, request.user)
    authentik_username = user.username

    # Determine user role
    is_ops = (
        has_permission(user, "ticketing_support")
        or has_permission(user, "ticketing_admin")
        or has_permission(user, "admin")
    )
    groups = get_authentik_groups(user)
    team, _team_number, is_team = get_team_from_groups(groups)

    # Access check
    if not is_ops and not is_team:
        return HttpResponseForbidden("You do not have permission to view tickets.")

    # Get filter parameters (always)
    status_filter = request.GET.get("status", "all") or "all"
    category_filter = request.GET.get("category", "all") or "all"
    search_query = request.GET.get("search", "").strip()
    sort_by = request.GET.get("sort", "-created_at")
    page_size_str = request.GET.get("page_size", "50")
    page = request.GET.get("page", "1")

    # Ops-only filter parameters
    team_filter = request.GET.get("team", "") if is_ops else ""
    assignee_filter = request.GET.get("assignee", "") if is_ops else ""

    try:
        page_size = int(page_size_str)
        if page_size not in [25, 50, 100, 200]:
            page_size = 50
    except ValueError:
        page_size = 50

    # Build base query
    if is_ops:
        query = (
            Ticket.objects.select_related("team")
            .exclude(ticket_number="")
            .annotate(
                comment_count=Count("comments", distinct=True),
                attachment_count=Count("attachments", distinct=True),
                last_activity=Max("history__timestamp"),
            )
        )
    else:
        query = (
            Ticket.objects.select_related("team")
            .filter(team=team)
            .annotate(
                comment_count=Count("comments", distinct=True),
                attachment_count=Count("attachments", distinct=True),
                last_activity=Max("history__timestamp"),
            )
        )

    # Apply shared filters
    if status_filter != "all":
        query = query.filter(status=status_filter)

    if category_filter != "all":
        with contextlib.suppress(ValueError):
            query = query.filter(category_id=int(category_filter))

    if search_query:
        query = query.filter(
            Q(title__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(ticket_number__icontains=search_query)
            | Q(hostname__icontains=search_query)
            | Q(service_name__icontains=search_query)
        )

    # Apply ops-only filters
    if is_ops and team_filter:
        with contextlib.suppress(ValueError):
            query = query.filter(team__team_number=int(team_filter))

    if is_ops and assignee_filter:
        if assignee_filter == "unassigned":
            query = query.filter(assigned_to__isnull=True)
        else:
            with contextlib.suppress(ValueError):
                query = query.filter(assigned_to_id=int(assignee_filter))

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
        "assigned_to__username",
        "-assigned_to__username",
    ]
    if sort_by not in valid_sort_fields:
        sort_by = "-created_at"

    query = query.order_by(sort_by)

    # Enrich tickets with category info and stale status
    thirty_minutes_ago = timezone.now() - timedelta(minutes=30)

    tickets_with_info = []
    for ticket in query:
        cat_info = get_category_config(ticket.category_id) or {}
        is_stale = (
            is_ops
            and ticket.status == "claimed"
            and ticket.assigned_at is not None
            and ticket.assigned_at < thirty_minutes_ago
        )
        tickets_with_info.append(
            {
                "ticket": ticket,
                "category_name": cat_info.get("display_name", "Unknown"),
                "is_stale": is_stale,
                "status_display": ticket.status.upper().replace("_", " "),
            }
        )

    # Paginate
    paginator = Paginator(tickets_with_info, page_size)
    page_obj = paginator.get_page(page)

    # Get unique assignees for filter dropdown (ops only)
    assignees = User.objects.filter(assigned_tickets__isnull=False).distinct().order_by("username") if is_ops else []

    is_ticketing_admin = has_permission(user, "ticketing_admin")

    context = {
        "is_ops": is_ops,
        "is_ticketing_admin": is_ticketing_admin,
        "team": team,
        "authentik_username": authentik_username,
        "page_obj": page_obj,
        "status_filter": status_filter,
        "category_filter": category_filter,
        "search_query": search_query,
        "sort_by": sort_by,
        "page_size": page_size,
        "team_filter": team_filter,
        "assignee_filter": assignee_filter,
        "assignees": assignees,
        "categories": get_all_categories(),
    }

    # Return partial for HTMX requests
    if request.headers.get("HX-Request"):
        return render(request, "cotton/ticket_list_table.html", context)

    return render(request, "ticket_list.html", context)


def ticket_detail(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Unified ticket detail view for both team members and ops staff."""
    user = cast(User, request.user)
    authentik_username = user.username

    # Determine user role
    is_ops = (
        has_permission(user, "ticketing_support")
        or has_permission(user, "ticketing_admin")
        or has_permission(user, "admin")
    )
    groups = get_authentik_groups(user)
    team, _team_number, is_team = get_team_from_groups(groups)
    is_ticketing_admin = has_permission(user, "ticketing_admin")
    is_ticketing_support = has_permission(user, "ticketing_support")

    # Look up ticket by ticket_number
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

    # Access check
    if is_ops:
        pass  # ops can view any ticket
    elif is_team and team and ticket.team == team:
        pass  # team member can view own team's tickets
    else:
        return HttpResponseForbidden("You do not have permission to view this ticket.")

    # Fetch common data
    cat_info = get_category_config(ticket.category_id) or {}
    comments = TicketComment.objects.filter(ticket=ticket).order_by("posted_at")
    attachments = TicketAttachment.objects.filter(ticket=ticket).order_by("uploaded_at")

    context: dict[str, object] = {
        "is_ops": is_ops,
        "is_ticketing_admin": is_ticketing_admin,
        "is_ticketing_support": is_ticketing_support,
        "authentik_username": authentik_username,
        "team": team,
        "ticket": ticket,
        "category_name": cat_info.get("display_name", "Unknown"),
        "comments": comments,
        "attachments": attachments,
        "status_display": ticket.status.upper().replace("_", " "),
    }

    # Ops-specific data
    if is_ops:
        history = TicketHistory.objects.filter(ticket=ticket).order_by("-timestamp")[:20]
        context["variable_points"] = cat_info.get("variable_points", False)
        context["categories"] = get_all_categories()
        context["history"] = history

        # Preserve filter state from referrer for back navigation
        context["status_filter"] = request.GET.get("status", "")
        context["category_filter"] = request.GET.get("category", "")
        context["team_filter"] = request.GET.get("team", "")
        context["assignee_filter"] = request.GET.get("assignee", "")
        context["search_filter"] = request.GET.get("search", "")
        context["sort_filter"] = request.GET.get("sort", "")
        context["page_filter"] = request.GET.get("page", "")
        context["page_size"] = request.GET.get("page_size", "")

    return render(request, "ticket_detail.html", context)


def ticket_comment(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Post a comment to a ticket (team members on own tickets, ops on any)."""
    if request.method != "POST":
        return HttpResponse(status=405)

    user = cast(User, request.user)
    authentik_username = user.username
    groups = get_authentik_groups(user)
    get_authentik_id(user)
    team, _team_number, is_team = get_team_from_groups(groups)
    is_ops = has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")

    if not is_team and not is_ops:
        return HttpResponse("Access denied", status=403)

    # Look up ticket by ticket_number
    try:
        ticket = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    # Access check: ops can access any ticket, team can only access their own
    if not is_ops and (not is_team or not team or ticket.team != team):
        return HttpResponse("Access denied", status=403)

    # Get comment text
    comment_text = request.POST.get("comment", "").strip()
    if not comment_text:
        messages.error(request, "Comment cannot be empty")
        return redirect("ticket_detail", ticket_number=ticket.ticket_number)

    # Check rate limit
    from ticketing.models import CommentRateLimit

    is_allowed, reason = CommentRateLimit.check_rate_limit(ticket.id, user.id)
    if not is_allowed:
        return JsonResponse({"error": reason}, status=429)

    CommentRateLimit.objects.create(ticket=ticket, discord_id=user.id)

    comment = TicketComment.objects.create(
        ticket=ticket,
        author=user,
        comment_text=comment_text,
    )

    DiscordTask.objects.create(
        task_type="post_comment",
        ticket=ticket,
        payload={
            "ticket_id": ticket.id,
            "comment_id": comment.id,
        },
        status="pending",
    )

    logger.info(f"Comment posted on ticket {ticket.ticket_number} by {authentik_username} (web)")

    return redirect("ticket_detail", ticket_number=ticket.ticket_number)


def create_ticket(request: HttpRequest) -> HttpResponse:
    """Create a new support ticket (web form alternative to Discord command)."""
    # Get user's team
    user = cast(User, request.user)
    authentik_username = user.username
    groups = get_authentik_groups(user)
    team, team_number, is_team = get_team_from_groups(groups)

    # Allow admins to create tickets for any team
    is_admin = has_permission(user, "gold_team") or has_permission(user, "admin")
    teams = None

    if is_admin:
        teams = Team.objects.filter(is_active=True).order_by("team_number")
        # If admin submitted form with team selection, use that team
        if request.method == "POST":
            team_id = request.POST.get("team_id")
            if team_id:
                with contextlib.suppress(Team.DoesNotExist, ValueError):
                    team = Team.objects.get(id=team_id, is_active=True)
                    team_number = team.team_number

    if not is_admin and not team:
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Access denied",
                "message": "You must be a team member to create tickets.",
            },
        )

    # Fetch infrastructure from Quotient API (graceful degradation if unavailable)
    from quotient.client import QuotientAPIError, get_quotient_client

    infrastructure = None
    service_choices: list[dict[str, str]] = []
    box_names: list[str] = []
    box_ip_map: dict[str, str] = {}

    try:
        quotient_client = get_quotient_client()
        infrastructure = quotient_client.get_infrastructure()
        service_choices = quotient_client.get_service_choices()
        box_names = quotient_client.get_box_names()
        if infrastructure:
            for box in infrastructure.boxes:
                box_ip_map[box.name] = box.ip
    except QuotientAPIError:
        logger.warning("Quotient API unavailable, ticket form will have limited functionality")

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        hostname = request.POST.get("hostname", "").strip()
        ip_address = request.POST.get("ip_address", "").strip()
        service_name = request.POST.get("service_name", "").strip()

        # Parse category as integer PK
        category_id_str = request.POST.get("category", "")
        try:
            category_id = int(category_id_str)
        except (ValueError, TypeError):
            category_id = 0

        # Admins must select a team
        if is_admin and not team:
            return render(
                request,
                "create_ticket.html",
                {
                    "team": team,
                    "teams": teams,
                    "categories": get_all_categories(),
                    "service_choices": service_choices,
                    "box_names": box_names,
                    "box_ip_map": box_ip_map,
                    "error": "Please select a team.",
                    "form_data": request.POST,
                },
            )

        # Validate category
        if not TicketCategory.objects.filter(pk=category_id).exists():
            return render(
                request,
                "create_ticket.html",
                {
                    "team": team,
                    "teams": teams,
                    "categories": get_all_categories(),
                    "service_choices": service_choices,
                    "box_names": box_names,
                    "box_ip_map": box_ip_map,
                    "error": "Invalid ticket category selected.",
                },
            )

        category_obj = TicketCategory.objects.get(pk=category_id)
        cat_info: TicketCategoryConfig = get_category_config(category_id) or {}

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
                    "teams": teams,
                    "categories": get_all_categories(),
                    "service_choices": service_choices,
                    "box_names": box_names,
                    "box_ip_map": box_ip_map,
                    "error": " ".join(errors),
                    "form_data": request.POST,
                },
            )

        # For box-reset, use hostname as description
        if cat_info.get("display_name", "").lower() == "box reset" and hostname:
            description = hostname

        if not team:
            return HttpResponse("Team required", status=400)

        # Create ticket using shared atomic function
        from ticketing.utils import create_ticket_atomic

        try:
            ticket = create_ticket_atomic(
                team=team,
                category=category_obj,
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
                    "category": category_obj.display_name,
                    "title": title,
                    "created_by": authentik_username,
                },
                status="pending",
            )

            logger.info(f"Ticket {ticket.ticket_number} created via web by {authentik_username} for {team.team_name}")

            return redirect("ticket_detail", ticket_number=ticket.ticket_number)

        except Exception as e:
            logger.error(f"Failed to create ticket: {e}", exc_info=True)

            return render(
                request,
                "create_ticket.html",
                {
                    "team": team,
                    "teams": teams,
                    "categories": get_all_categories(),
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
            "teams": teams,
            "categories": get_all_categories(),
            "service_choices": service_choices,
            "box_names": box_names,
            "box_ip_map": box_ip_map,
        },
    )


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
            "tickets_error.html",
            {
                "error": "Invalid account",
                "message": "Your account is not associated with a team.",
            },
        )

    # Get ticket (must belong to user's team)
    try:
        ticket = Ticket.objects.select_related("team").get(ticket_number=ticket_number, team=team)
    except Ticket.DoesNotExist:
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Ticket not found",
                "message": f"Ticket {ticket_number} does not exist or does not belong to your team.",
            },
        )

    # Only allow cancellation if unclaimed
    if ticket.status != "open":
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Cannot cancel",
                "message": f"Ticket {ticket_number} is already {ticket.status}. Only open tickets can be cancelled.",
            },
        )

    # Cancel ticket
    ticket.status = "cancelled"
    ticket.resolved_at = timezone.now()
    ticket.resolution_notes = f"Cancelled by {authentik_username} via web interface"
    ticket.points_charged = 0
    ticket.save()

    # Create history entry
    TicketHistory.objects.create(
        ticket=ticket,
        action="cancelled",
        details={"reason": "Cancelled by team member via web (unclaimed)", "cancelled_by": authentik_username},
    )

    logger.info(f"Ticket {ticket_number} cancelled by {authentik_username} via web")

    return redirect("ticket_list")


def ticket_attachment_upload(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Upload an attachment to a ticket."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username = user.username
    groups = get_authentik_groups(user)
    team, _, is_team = get_team_from_groups(groups)
    is_ops = has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")

    if not is_team and not is_ops:
        return HttpResponse("Access denied", status=403)

    try:
        ticket = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    # Access check: ops can access any ticket, team can only access their own
    if not is_ops and (not is_team or not team or ticket.team != team):
        return HttpResponse("Access denied", status=403)

    if error := _save_attachment(ticket, request.FILES.get("attachment"), authentik_username):
        return error

    logger.info(f"Attachment uploaded to ticket {ticket.ticket_number} by {authentik_username}")

    return redirect("ticket_detail", ticket_number=ticket.ticket_number)


def ticket_attachment_download(
    request: HttpRequest,
    attachment_id: int,
    ticket_number: str,
) -> HttpResponse:
    """Download an attachment from a ticket."""
    user = cast(User, request.user)
    groups = get_authentik_groups(user)
    team, _, is_team = get_team_from_groups(groups)
    is_ops = has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")

    if not is_team and not is_ops:
        return HttpResponse("Access denied", status=403)

    try:
        attachment = TicketAttachment.objects.select_related("ticket", "ticket__team").get(
            id=attachment_id, ticket__ticket_number=ticket_number
        )
    except TicketAttachment.DoesNotExist:
        return HttpResponse("Attachment not found", status=404)

    # Access check: ops can access any ticket, team can only access their own
    if not is_ops and (not is_team or not team or attachment.ticket.team != team):
        return HttpResponse("Access denied", status=403)

    # Only allow inline viewing for safe MIME types (images, PDFs)
    # Force download for everything else to prevent XSS via HTML/SVG
    inline_requested = request.GET.get("inline") == "1"
    is_safe_for_inline = attachment.mime_type in INLINE_SAFE_MIME_TYPES
    as_attachment = not (inline_requested and is_safe_for_inline)

    response = HttpResponse(bytes(attachment.file_data), content_type=attachment.mime_type)
    response["Content-Disposition"] = str(
        content_disposition_header(as_attachment=as_attachment, filename=attachment.filename)
    )
    return response


def ticket_detail_dynamic(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """Return dynamic ticket content (comments/history) for HTMX polling."""
    user = cast(User, request.user)

    if not (has_permission(user, "ticketing_support") or has_permission(user, "ticketing_admin")):
        return HttpResponse("Access denied", status=403)

    try:
        ticket = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    comments = TicketComment.objects.filter(ticket=ticket).order_by("posted_at")
    history = TicketHistory.objects.filter(ticket=ticket).order_by("-timestamp")[:20]

    return render(
        request,
        "ops_ticket_detail_dynamic.html",
        {
            "ticket": ticket,
            "comments": comments,
            "history": history,
        },
    )


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
            DiscordTask.objects.create(
                task_type="add_user_to_thread",
                ticket=ticket,
                payload={
                    "discord_id": discord_link.discord_id,
                    "thread_id": ticket.discord_thread_id,
                },
                status="pending",
            )
        DiscordTask.objects.create(
            task_type="post_ticket_update",
            ticket=ticket,
            payload={"action": "claimed", "actor": authentik_username},
        )

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
        DiscordTask.objects.create(
            task_type="post_ticket_update",
            ticket=ticket,
            payload={"action": "unclaimed", "actor": authentik_username},
        )

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
            DiscordTask.objects.create(
                task_type="add_user_to_thread",
                ticket=ticket,
                payload={
                    "discord_id": discord_link.discord_id,
                    "thread_id": ticket.discord_thread_id,
                },
                status="pending",
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
        DiscordTask.objects.create(
            task_type="post_ticket_update",
            ticket=ticket,
            payload={
                "action": "resolved",
                "actor": authentik_username,
                "resolution_notes": resolution_notes,
                "points_charged": ticket.points_charged,
            },
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
        ticket = Ticket.objects.select_related("team").get(ticket_number=ticket_number)
    except Ticket.DoesNotExist:
        return HttpResponse("Ticket not found", status=404)

    # Only allow reopening resolved tickets
    if ticket.status != "resolved":
        messages.error(request, f"Cannot reopen - ticket is {ticket.status}")
        return redirect("ticket_detail", ticket_number=ticket_number)

    reopen_reason = request.POST.get("reopen_reason", "").strip()

    # Reopen ticket - clear assignee so it goes back to queue
    old_status = ticket.status
    old_assignee = ticket.assigned_to
    ticket.status = "open"
    ticket.assigned_to = None
    ticket.resolved_at = None
    ticket.save()

    # Create history entry
    details = {"old_status": old_status, "reopened_by": authentik_username}
    if old_assignee:
        details["previous_assignee"] = old_assignee.username
    if reopen_reason:
        details["reason"] = reopen_reason

    TicketHistory.objects.create(
        ticket=ticket,
        action="reopened",
        details=details,
    )

    # Post status update to Discord thread
    if ticket.discord_thread_id:
        payload: dict[str, object] = {"action": "reopened", "actor": authentik_username}
        if reopen_reason:
            payload["reason"] = reopen_reason
        DiscordTask.objects.create(
            task_type="post_ticket_update",
            ticket=ticket,
            payload=payload,
        )

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
    except (ValueError, TypeError):
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

    from django.db import transaction

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


def school_info(request: HttpRequest) -> HttpResponse:
    """View and edit school information (GoldTeam only)."""
    # Get user's permissions
    user = cast(User, request.user)

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

    return render(
        request,
        "school_info.html",
        {
            "teams": teams_with_info,
            "show_ops_nav": True,
        },
    )


def school_info_edit(request: HttpRequest, team_number: int) -> HttpResponse:
    """Edit school information for a team (GoldTeam only)."""
    # Get user's permissions
    user = cast(User, request.user)
    authentik_username = user.username

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

    if request.method == "POST":
        school_name = request.POST.get("school_name", "").strip()
        contact_email = request.POST.get("contact_email", "").strip()
        secondary_email = request.POST.get("secondary_email", "").strip()
        notes = request.POST.get("notes", "").strip()

        # Validate required fields
        if not school_name:
            return render(
                request,
                "school_info_edit.html",
                {
                    "team": team,
                    "school_info": school_info,
                    "error": "School name is required.",
                },
            )

        if not contact_email:
            return render(
                request,
                "school_info_edit.html",
                {
                    "team": team,
                    "school_info": school_info,
                    "error": "Contact email is required.",
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

        return redirect("school_info")

    return render(
        request,
        "school_info_edit.html",
        {
            "team": team,
            "school_info": school_info,
            "show_ops_nav": True,
        },
    )


def school_info_import(request: HttpRequest) -> HttpResponse:
    """Import school information from CSV file (GoldTeam only)."""
    from team.forms import CSVUploadForm, apply_csv_import, parse_csv_file, validate_csv_data

    # Get user's permissions
    user = cast(User, request.user)
    authentik_username = user.username

    # Check if user is GoldTeam
    if not has_permission(user, "gold_team"):
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Access denied",
                "message": "You do not have permission to import school information.",
            },
        )

    # Build permissions dict for template
    permissions = get_permissions_context(user)

    form = CSVUploadForm()
    preview_data: dict[str, object] | None = None
    import_results = None

    if request.method == "POST":
        if "upload" in request.POST:
            # Step 1: Upload and preview
            form = CSVUploadForm(request.POST, request.FILES)
            if form.is_valid():
                csv_file = cast(UploadedFile, request.FILES["csv_file"])

                # Parse CSV
                parse_result = parse_csv_file(csv_file)

                if parse_result["errors"]:
                    # Show errors
                    preview_data = {
                        "errors": parse_result["errors"],
                        "warnings": parse_result["warnings"],
                        "rows": [],
                    }
                else:
                    # Validate against database
                    validation_result = validate_csv_data(parse_result["rows"])

                    preview_data = {
                        "errors": validation_result["errors"],
                        "warnings": parse_result["warnings"] + validation_result["warnings"],
                        "teams_to_create": validation_result["teams_to_create"],
                        "can_import": not validation_result["errors"],
                    }

                    # Store data in session for confirmation (including assigned team numbers)
                    if preview_data["can_import"]:
                        request.session["csv_import_data"] = {
                            "teams_to_create": [
                                {
                                    "team_number": row["team_number"],
                                    "school_name": row["school_name"],
                                    "contact_email": row["contact_email"],
                                    "secondary_email": row.get("secondary_email", ""),
                                    "notes": row.get("notes", ""),
                                    "team_name": row.get("team_name", ""),
                                }
                                for row in validation_result["teams_to_create"]
                            ],
                        }

        elif "confirm" in request.POST:
            # Step 2: Confirm and import
            import_data = request.session.get("csv_import_data")
            if import_data:
                from team.models import Team

                teams_to_create = import_data["teams_to_create"]

                # Verify teams are still available and add _team references
                team_numbers = [row["team_number"] for row in teams_to_create]
                teams_by_number = {
                    t.team_number: t for t in Team.objects.filter(team_number__in=team_numbers, is_active=True)
                }

                errors = []
                for row in teams_to_create:
                    team_number = row["team_number"]
                    if team_number not in teams_by_number:
                        errors.append(f"Team {team_number} is no longer available")
                    else:
                        row["_team"] = teams_by_number[team_number]

                if errors:
                    preview_data = {
                        "errors": errors,
                        "warnings": ["Please re-upload the CSV file."],
                        "can_import": False,
                    }
                else:
                    # Apply import
                    result = apply_csv_import(teams_to_create, authentik_username)

                    import_results = {"created": result["created"], "assigned": result["assigned"]}

                    # Clear session data
                    del request.session["csv_import_data"]

    return render(
        request,
        "school_info_import.html",
        {
            "authentik_username": authentik_username,
            "form": form,
            "preview_data": preview_data,
            "import_results": import_results,
            "show_ops_nav": True,
            **permissions,
        },
    )


def ops_group_role_mappings(request: HttpRequest) -> HttpResponse:
    """View team membership status and linked users (GoldTeam only)."""
    # Get user's permissions
    user = cast(User, request.user)

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
                "authentik_username": link.user.username,
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

    from django.contrib.admin.sites import site

    context = {
        **site.each_context(request),
        "team_status": team_status,
        "title": "Team Mappings",
    }
    return render(request, "ops_group_role_mappings.html", context)


def ops_review_tickets(request: HttpRequest) -> HttpResponse:
    """Review resolved tickets for point verification (admin only)."""
    from django.core.paginator import Paginator

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
        "resolved_at",
        "-resolved_at",
        "points_charged",
        "-points_charged",
        "team__team_number",
        "-team__team_number",
        "category",
        "-category",
    ]
    if sort_by not in valid_sort_fields:
        sort_by = "-resolved_at"

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


def ticket_notifications(request: HttpRequest) -> JsonResponse:
    """JSON endpoint for ticket notification polling (ops staff only)."""
    user = cast(User, request.user)
    if not (
        has_permission(user, "admin")
        or has_permission(user, "ticketing_support")
        or has_permission(user, "ticketing_admin")
    ):
        return JsonResponse({"error": "forbidden"}, status=403)

    try:
        since_id = int(request.GET.get("since_id", "0"))
    except (ValueError, TypeError):
        since_id = 0

    open_count = Ticket.objects.filter(status="open").count()
    raw_tickets = (
        Ticket.objects.filter(status="open", id__gt=since_id)
        .order_by("id")
        .values("id", "ticket_number", "title", "category_id")[:10]
    )

    new_tickets = []
    for t in raw_tickets:
        cat_config = get_category_config(t["category_id"])
        new_tickets.append(
            {
                "id": t["id"],
                "number": t["ticket_number"],
                "title": t["title"],
                "category_display": cat_config["display_name"] if cat_config else "Unknown",
            }
        )

    return JsonResponse({"open_count": open_count, "new_tickets": new_tickets})
