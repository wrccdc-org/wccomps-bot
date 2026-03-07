"""Views for WCComps linking and OAuth."""

import logging
from typing import Protocol, cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Manager
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from core.models import DiscordTask
from team.models import DiscordLink, LinkAttempt, LinkToken, SchoolInfo, Team

from .auth_utils import get_authentik_groups, get_authentik_id, get_permissions_context, has_permission
from .utils import get_team_from_groups


class ModelWithObjects(Protocol):
    # Generic Protocol for iterating any model, Manager[T] requires T: Model
    objects: Manager  # type: ignore[type-arg]
    __name__: str


logger = logging.getLogger(__name__)


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
        return redirect("challenges:dashboard")
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


def _create_or_update_link(
    discord_id: int,
    discord_username: str,
    user: User,
    team: Team | None,
) -> DiscordLink:
    """Create or update a DiscordLink, deactivating any previous link for this discord_id."""
    DiscordLink.deactivate_previous_links(discord_id)
    try:
        link = DiscordLink.objects.get(discord_id=discord_id, is_active=True)
        link.discord_username = discord_username
        link.user = user
        link.team = team
        link.linked_at = timezone.now()
        link.unlinked_at = None
        link.save()
    except DiscordLink.DoesNotExist:
        link = DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username=discord_username,
            user=user,
            team=team,
            is_active=True,
        )
    return link


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
            _create_or_update_link(discord_id, discord_username, user, team)
    else:
        # Non-team linking (admins/support): no locking needed
        _create_or_update_link(discord_id, discord_username, user, team=None)

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
            "team_name": f"Team {team.team_number}" if team else None,
            "team_number": team_number,
            "discord_username": discord_username,
            "authentik_username": authentik_username,
            "is_team_account": is_team_account,
        },
    )


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
