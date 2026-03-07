"""Admin views for competition management."""

import csv
import io
import json
import logging
from collections.abc import Iterator
from typing import cast

from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse, HttpResponseBase, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone
from scoring.models import QuotientMetadataCache
from scoring.quotient_sync import sync_quotient_metadata

from core.authentik_manager import AuthentikManager
from core.authentik_utils import (
    generate_blueteam_password,
    parse_team_range,
    reset_blueteam_password,
    toggle_authentik_user,
)
from core.models import AuditLog, CompetitionConfig, QueuedAnnouncement
from team.models import MAX_TEAMS

from ..auth_utils import has_permission
from ..utils import parse_datetime_to_utc

logger = logging.getLogger(__name__)

TIMEZONE_CHOICES = [
    ("America/Los_Angeles", "Pacific Time (PT)"),
    ("America/Denver", "Mountain Time (MT)"),
    ("America/Chicago", "Central Time (CT)"),
    ("America/New_York", "Eastern Time (ET)"),
    ("UTC", "UTC"),
]


def _check_admin(user: User) -> bool:
    """Check if user has admin permission."""
    return has_permission(user, "admin") or has_permission(user, "gold_team")


def _action_set_max_members(request: HttpRequest, config: CompetitionConfig, authentik_username: str) -> JsonResponse:
    """Handle set_max_members action."""
    from team.models import Team

    try:
        max_members = int(request.POST.get("max_members", 10))
        if max_members < 1 or max_members > 20:
            return JsonResponse({"error": "Max members must be 1-20"}, status=400)

        old_max = config.max_team_members
        config.max_team_members = max_members
        config.save()

        Team.objects.update(max_members=max_members)

        AuditLog.objects.create(
            action="max_team_members_updated",
            admin_user=authentik_username,
            target_entity="competition_config",
            target_id=config.pk,
            details={"old_max": old_max, "new_max": max_members},
        )

        return JsonResponse({"success": True, "message": f"Max members set to {max_members}"})
    except ValueError:
        return JsonResponse({"error": "Invalid number"}, status=400)


def _action_set_apps(request: HttpRequest, config: CompetitionConfig, authentik_username: str) -> JsonResponse:
    """Handle set_apps action."""
    app_slugs = request.POST.get("app_slugs", "").strip()
    if not app_slugs:
        return JsonResponse({"error": "Please provide at least one app slug"}, status=400)

    slugs = [s.strip() for s in app_slugs.split(",") if s.strip()]
    config.controlled_applications = slugs
    config.save()

    AuditLog.objects.create(
        action="competition_apps_configured",
        admin_user=authentik_username,
        target_entity="competition_config",
        target_id=config.pk,
        details={"controlled_apps": slugs},
    )

    return JsonResponse({"success": True, "message": f"Apps set to: {', '.join(slugs)}"})


def _action_set_start_time(request: HttpRequest, config: CompetitionConfig, authentik_username: str) -> JsonResponse:
    """Handle set_start_time action."""
    datetime_str = request.POST.get("datetime", "").strip()
    tz_name = request.POST.get("timezone", "America/Los_Angeles")

    if not datetime_str:
        return JsonResponse({"error": "Please provide a datetime"}, status=400)

    try:
        start_time = parse_datetime_to_utc(datetime_str, tz_name)

        if not config.controlled_applications:
            config.ensure_controlled_applications()

        config.competition_start_time = start_time
        config.applications_enabled = False
        config.save()

        AuditLog.objects.create(
            action="competition_start_time_set",
            admin_user=authentik_username,
            target_entity="competition_config",
            target_id=config.pk,
            details={"start_time": start_time.isoformat(), "controlled_apps": config.controlled_applications},
        )

        return JsonResponse({"success": True, "message": f"Start time set to {start_time.isoformat()}"})
    except ValueError:
        return JsonResponse({"error": "Invalid datetime format"}, status=400)


def _action_set_end_time(request: HttpRequest, config: CompetitionConfig, authentik_username: str) -> JsonResponse:
    """Handle set_end_time action."""
    datetime_str = request.POST.get("datetime", "").strip()
    tz_name = request.POST.get("timezone", "America/Los_Angeles")

    if not datetime_str:
        return JsonResponse({"error": "Please provide a datetime"}, status=400)

    try:
        end_time = parse_datetime_to_utc(datetime_str, tz_name)

        if not config.controlled_applications:
            config.ensure_controlled_applications()

        config.competition_end_time = end_time
        config.save()

        AuditLog.objects.create(
            action="competition_end_time_set",
            admin_user=authentik_username,
            target_entity="competition_config",
            target_id=config.pk,
            details={"end_time": end_time.isoformat(), "controlled_apps": config.controlled_applications},
        )

        return JsonResponse({"success": True, "message": f"End time set to {end_time.isoformat()}"})
    except ValueError:
        return JsonResponse({"error": "Invalid datetime format"}, status=400)


from core.utils import ndjson_progress as _progress


def _stream_start_competition(config: CompetitionConfig, authentik_username: str) -> Iterator[str]:
    """Stream progress for starting the competition."""
    apps = config.controlled_applications
    total = len(apps) + 50 + 1  # apps + accounts + quotient sync
    auth_manager = AuthentikManager()

    # Phase 1: Enable applications
    app_ok = 0
    app_fail = 0
    for i, slug in enumerate(apps, 1):
        success, error = auth_manager.enable_application(slug)
        if success:
            app_ok += 1
            yield _progress(f"Enabled {slug}", i, total)
        else:
            app_fail += 1
            yield _progress(f"Failed {slug}: {error}", i, total, ok=False)

    # Phase 2: Enable team accounts
    acct_ok = 0
    acct_fail = 0
    for i in range(1, MAX_TEAMS + 1):
        username = f"team{i:02d}"
        success, _ = toggle_authentik_user(username, is_active=True)
        idx = len(apps) + i
        if success:
            acct_ok += 1
            yield _progress(f"Enabled {username}", idx, total)
        else:
            acct_fail += 1
            yield _progress(f"Failed {username}", idx, total, ok=False)

    # Phase 3: Quotient sync
    try:
        sync_quotient_metadata()
        quotient_synced = True
        yield _progress("Quotient metadata synced", total, total)
    except Exception as e:
        logger.warning(f"Failed to sync Quotient metadata: {e}")
        quotient_synced = False
        yield _progress(f"Quotient sync failed: {e}", total, total, ok=False)

    # Update config
    config.applications_enabled = True
    config.competition_start_time = None
    config.save()

    AuditLog.objects.create(
        action="competition_started",
        admin_user=authentik_username,
        target_entity="competition_config",
        target_id=config.pk,
        details={
            "apps_success": app_ok,
            "apps_failed": app_fail,
            "accounts_enabled": acct_ok,
            "accounts_failed": acct_fail,
            "quotient_synced": quotient_synced,
        },
    )

    quotient_msg = ", Quotient synced" if quotient_synced else ", Quotient sync failed"
    yield (
        json.dumps(
            {
                "done": True,
                "success": True,
                "message": f"Competition started. Apps: {app_ok}/{len(apps)}, Accounts: {acct_ok}/50{quotient_msg}",
            }
        )
        + "\n"
    )


def _action_start_competition(
    request: HttpRequest, config: CompetitionConfig, authentik_username: str
) -> StreamingHttpResponse:
    """Handle start_competition action with streaming progress."""
    if not config.controlled_applications:
        return StreamingHttpResponse(
            json.dumps({"done": True, "success": False, "message": "No controlled applications configured"}) + "\n",
            content_type="application/x-ndjson",
        )
    return StreamingHttpResponse(
        _stream_start_competition(config, authentik_username),
        content_type="application/x-ndjson",
    )


def _stream_stop_competition(config: CompetitionConfig, authentik_username: str) -> Iterator[str]:
    """Stream progress for stopping the competition."""
    apps = config.controlled_applications
    total = len(apps) + 50  # apps + accounts
    auth_manager = AuthentikManager()

    # Phase 1: Disable applications
    app_ok = 0
    app_fail = 0
    for i, slug in enumerate(apps, 1):
        success, error = auth_manager.disable_application(slug)
        if success:
            app_ok += 1
            yield _progress(f"Disabled {slug}", i, total)
        else:
            app_fail += 1
            yield _progress(f"Failed {slug}: {error}", i, total, ok=False)

    # Phase 2: Disable team accounts
    acct_ok = 0
    acct_fail = 0
    for i in range(1, MAX_TEAMS + 1):
        username = f"team{i:02d}"
        success, _ = toggle_authentik_user(username, is_active=False)
        idx = len(apps) + i
        if success:
            acct_ok += 1
            yield _progress(f"Disabled {username}", idx, total)
        else:
            acct_fail += 1
            yield _progress(f"Failed {username}", idx, total, ok=False)

    # Update config
    config.applications_enabled = False
    config.competition_end_time = None
    config.save()

    AuditLog.objects.create(
        action="competition_stopped",
        admin_user=authentik_username,
        target_entity="competition_config",
        target_id=config.pk,
        details={
            "apps_disabled": app_ok,
            "apps_failed": app_fail,
            "accounts_disabled": acct_ok,
            "accounts_failed": acct_fail,
        },
    )

    yield (
        json.dumps(
            {
                "done": True,
                "success": True,
                "message": f"Competition stopped. Apps: {app_ok}/{len(apps)}, Accounts disabled: {acct_ok}/50",
            }
        )
        + "\n"
    )


def _action_stop_competition(
    request: HttpRequest, config: CompetitionConfig, authentik_username: str
) -> StreamingHttpResponse:
    """Handle stop_competition action with streaming progress."""
    if not config.controlled_applications:
        return StreamingHttpResponse(
            json.dumps({"done": True, "success": False, "message": "No controlled applications configured"}) + "\n",
            content_type="application/x-ndjson",
        )
    return StreamingHttpResponse(
        _stream_stop_competition(config, authentik_username),
        content_type="application/x-ndjson",
    )


def _action_cleanup_competition(
    request: HttpRequest, config: CompetitionConfig, authentik_username: str
) -> JsonResponse:
    """Handle cleanup_competition action."""
    from team.models import DiscordLink, Team

    if config.applications_enabled:
        return JsonResponse({"error": "Competition must be stopped before cleanup"}, status=400)

    # Deactivate team member links
    links = DiscordLink.objects.filter(is_active=True, team__isnull=False)
    deactivated = 0
    for link in links:
        link.is_active = False
        link.unlinked_at = timezone.now()
        link.save()
        deactivated += 1

        AuditLog.objects.create(
            action="user_unlinked",
            admin_user=authentik_username,
            target_entity="discord_link",
            target_id=link.discord_id,
            details={
                "discord_id": link.discord_id,
                "team_name": link.team.team_name if link.team else "Unknown",
                "authentik_username": link.user.username,
                "reason": "competition_cleanup",
            },
        )

    # Clear team Discord IDs
    Team.objects.all().update(discord_category_id=None, discord_role_id=None)

    # Clear competition times
    config.competition_start_time = None
    config.competition_end_time = None
    config.save()

    # Clear queued announcements
    deleted_count = QueuedAnnouncement.objects.all().delete()[0]

    # Clear Quotient metadata cache
    QuotientMetadataCache.objects.all().delete()

    AuditLog.objects.create(
        action="competition_cleanup",
        admin_user=authentik_username,
        target_entity="competition",
        target_id=0,
        details={
            "deactivated_links": deactivated,
            "cleared_announcements": deleted_count,
            "cleared_quotient_metadata": True,
        },
    )

    return JsonResponse(
        {
            "success": True,
            "message": f"Cleanup complete. Deactivated {deactivated} links, cleared {deleted_count} announcements, "
            "cleared Quotient metadata. Discord cleanup requires bot commands.",
        }
    )


def _action_wipe_competition(request: HttpRequest, config: CompetitionConfig, authentik_username: str) -> JsonResponse:
    """Handle wipe_competition action - nuclear option to delete all competition data."""
    from core.competition_utils import wipe_competition_data

    if config.applications_enabled:
        return JsonResponse({"error": "Competition must be stopped before wiping"}, status=400)

    counts = wipe_competition_data()

    # Clear competition config times
    config.competition_start_time = None
    config.competition_end_time = None
    config.save()

    # Summarize what was deleted
    deleted_items = {k: v for k, v in counts.items() if v > 0}
    total_deleted = sum(counts.values())

    # Create a new audit log entry (after wiping, so it's the first entry)
    AuditLog.objects.create(
        action="competition_wiped",
        admin_user=authentik_username,
        target_entity="competition",
        target_id=0,
        details={"deleted_counts": deleted_items, "total_deleted": total_deleted},
    )

    summary_parts = [f"{v} {k}" for k, v in deleted_items.items()]
    summary = ", ".join(summary_parts) if summary_parts else "No data to delete"

    return JsonResponse(
        {
            "success": True,
            "message": f"Competition wiped! Deleted: {summary}",
        }
    )


def _action_reset_passwords(request: HttpRequest, config: CompetitionConfig, authentik_username: str) -> JsonResponse:
    """Handle reset_passwords action."""
    team_numbers_str = request.POST.get("team_numbers", "").strip()

    try:
        team_numbers = parse_team_range(team_numbers_str) if team_numbers_str else list(range(1, MAX_TEAMS + 1))
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)

    password_list = []
    failed_resets = []

    for team_num in team_numbers:
        username = f"team{team_num:02d}"
        password = generate_blueteam_password()
        success, error = reset_blueteam_password(team_num, password)
        if success:
            password_list.append((team_num, username, password))
        else:
            failed_resets.append((username, error))

    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(["Username", "Password"])
    for _team_num, username, password in password_list:
        writer.writerow([username, password])

    csv_content = csv_buffer.getvalue()

    AuditLog.objects.create(
        action="blueteam_passwords_reset",
        admin_user=authentik_username,
        target_entity="authentik_users",
        target_id=0,
        details={
            "total_users": len(team_numbers),
            "success_count": len(password_list),
            "failed_count": len(failed_resets),
            "team_numbers": team_numbers_str or "all",
        },
    )

    return JsonResponse(
        {
            "success": True,
            "message": f"Reset {len(password_list)}/{len(team_numbers)} passwords",
            "csv": csv_content,
        }
    )


def _action_sync_quotient(request: HttpRequest, config: CompetitionConfig, authentik_username: str) -> JsonResponse:
    """Handle sync_quotient action."""
    try:
        sync_quotient_metadata()
        AuditLog.objects.create(
            action="quotient_metadata_synced",
            admin_user=authentik_username,
            target_entity="quotient",
            target_id=0,
            details={},
        )
        return JsonResponse({"success": True, "message": "Quotient metadata synced"})
    except Exception as e:
        logger.error(f"Failed to sync Quotient metadata: {e}")
        return JsonResponse({"error": f"Sync failed: {e}"}, status=500)


_COMPETITION_ACTION_HANDLERS = {
    "set_max_members": _action_set_max_members,
    "set_apps": _action_set_apps,
    "set_start_time": _action_set_start_time,
    "set_end_time": _action_set_end_time,
    "start_competition": _action_start_competition,
    "stop_competition": _action_stop_competition,
    "cleanup_competition": _action_cleanup_competition,
    "wipe_competition": _action_wipe_competition,
    "reset_passwords": _action_reset_passwords,
    "sync_quotient": _action_sync_quotient,
}


def admin_competition(request: HttpRequest) -> HttpResponse:
    """Competition management dashboard."""
    from team.models import DiscordLink, Team

    user = cast(User, request.user)

    if not _check_admin(user):
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Access denied",
                "message": "You do not have permission to access competition management.",
            },
        )

    config = CompetitionConfig.get_config()

    # Get team counts
    active_teams = Team.objects.filter(is_active=True).count()
    total_teams = Team.objects.count()
    linked_users = DiscordLink.objects.filter(is_active=True, team__isnull=False).count()

    # Get available apps from Authentik
    auth_manager = AuthentikManager()
    available_apps = auth_manager.list_applications()

    # Get Quotient metadata
    quotient_metadata = QuotientMetadataCache.objects.first()

    context = {
        "config": config,
        "active_teams": active_teams,
        "total_teams": total_teams,
        "linked_users": linked_users,
        "available_apps": available_apps,
        "timezone_choices": TIMEZONE_CHOICES,
        "quotient_metadata": quotient_metadata,
        "show_ops_nav": True,
        "nav_active": "ops_admin",
    }

    return render(request, "admin/competition.html", context)


def admin_competition_action(request: HttpRequest) -> HttpResponseBase:
    """Handle competition management actions via dispatch."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    if not _check_admin(user):
        return JsonResponse({"error": "Access denied"}, status=403)

    action = request.POST.get("action")
    if not action:
        return JsonResponse({"error": "No action specified"}, status=400)
    handler = _COMPETITION_ACTION_HANDLERS.get(action)
    if not handler:
        return JsonResponse({"error": "Unknown action"}, status=400)

    config = CompetitionConfig.get_config()
    return handler(request, config, user.username)
