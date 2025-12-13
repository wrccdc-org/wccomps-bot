"""Admin views for competition, team, and helper management."""

import csv
import io
import logging
from typing import cast
from zoneinfo import ZoneInfo

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone

from core.authentik_manager import AuthentikManager
from core.authentik_utils import (
    generate_blueteam_password,
    parse_team_range,
    reset_blueteam_password,
    toggle_authentik_user,
)
from core.models import AuditLog, CompetitionConfig, DiscordTask
from team.models import DiscordLink, Team

from .auth_utils import has_permission
from .utils import get_authentik_data

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


@login_required
def admin_competition(request: HttpRequest) -> HttpResponse:
    """Competition management dashboard."""
    user = cast(User, request.user)
    authentik_username, _groups, _ = get_authentik_data(user)

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

    context = {
        "config": config,
        "active_teams": active_teams,
        "total_teams": total_teams,
        "linked_users": linked_users,
        "timezone_choices": TIMEZONE_CHOICES,
        "show_ops_nav": True,
        "nav_active": "ops_admin",
    }

    return render(request, "admin/competition.html", context)


@login_required
def admin_competition_action(request: HttpRequest) -> HttpResponse:
    """Handle competition management actions."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username, _groups, _ = get_authentik_data(user)

    if not _check_admin(user):
        return JsonResponse({"error": "Access denied"}, status=403)

    action = request.POST.get("action")
    config = CompetitionConfig.get_config()

    if action == "set_max_members":
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

    elif action == "set_apps":
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

    elif action == "set_start_time":
        datetime_str = request.POST.get("datetime", "").strip()
        tz_name = request.POST.get("timezone", "America/Los_Angeles")

        if not datetime_str:
            return JsonResponse({"error": "Please provide a datetime"}, status=400)

        try:
            from datetime import datetime

            dt = datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M")
            local_time = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, tzinfo=ZoneInfo(tz_name))
            start_time = local_time.astimezone(ZoneInfo("UTC"))

            if not config.controlled_applications:
                config.controlled_applications = ["netbird", "scoring", "competitions-public", "competitions"]

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

    elif action == "set_end_time":
        datetime_str = request.POST.get("datetime", "").strip()
        tz_name = request.POST.get("timezone", "America/Los_Angeles")

        if not datetime_str:
            return JsonResponse({"error": "Please provide a datetime"}, status=400)

        try:
            from datetime import datetime

            dt = datetime.strptime(datetime_str, "%Y-%m-%dT%H:%M")
            local_time = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, tzinfo=ZoneInfo(tz_name))
            end_time = local_time.astimezone(ZoneInfo("UTC"))

            if not config.controlled_applications:
                config.controlled_applications = ["netbird", "scoring", "competitions-public", "competitions"]

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

    elif action == "start_competition":
        if not config.controlled_applications:
            return JsonResponse({"error": "No controlled applications configured"}, status=400)

        auth_manager = AuthentikManager()
        app_results = auth_manager.enable_applications(config.controlled_applications)

        # Enable blueteam accounts
        success_count = 0
        failed_count = 0
        for i in range(1, 51):
            username = f"team{i:02d}"
            success, _ = toggle_authentik_user(username, is_active=True)
            if success:
                success_count += 1
            else:
                failed_count += 1

        config.applications_enabled = True
        config.competition_start_time = None
        config.competition_end_time = None
        config.save()

        success_apps = [app for app, (success, _) in app_results.items() if success]
        failed_apps = [(app, error) for app, (success, error) in app_results.items() if not success]

        AuditLog.objects.create(
            action="competition_started",
            admin_user=authentik_username,
            target_entity="competition_config",
            target_id=config.pk,
            details={
                "apps_success": len(success_apps),
                "apps_failed": len(failed_apps),
                "accounts_enabled": success_count,
                "accounts_failed": failed_count,
            },
        )

        app_msg = f"Apps: {len(success_apps)}/{len(config.controlled_applications)}"
        return JsonResponse(
            {"success": True, "message": f"Competition started. {app_msg}, Accounts: {success_count}/50"}
        )

    elif action == "toggle_blueteams":
        enable = request.POST.get("enable") == "true"
        action_word = "enabled" if enable else "disabled"

        success_count = 0
        failed_count = 0
        for i in range(1, 51):
            username = f"team{i:02d}"
            success, _ = toggle_authentik_user(username, is_active=enable)
            if success:
                success_count += 1
            else:
                failed_count += 1

        AuditLog.objects.create(
            action=f"blueteam_accounts_{action_word}",
            admin_user=authentik_username,
            target_entity="authentik_users",
            target_id=0,
            details={"success_count": success_count, "failed_count": failed_count},
        )

        return JsonResponse({"success": True, "message": f"{action_word.capitalize()} {success_count}/50 accounts"})

    elif action == "reset_passwords":
        team_numbers_str = request.POST.get("team_numbers", "").strip()

        try:
            team_numbers = parse_team_range(team_numbers_str) if team_numbers_str else list(range(1, 51))
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

        # Generate CSV
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

    elif action == "end_competition":
        results = []

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
                    "reason": "competition_ended",
                },
            )

        results.append(f"Deactivated {deactivated} links")

        # Clear Discord IDs from teams (channels will need to be deleted via bot)
        Team.objects.all().update(discord_category_id=None, discord_role_id=None)

        # Deactivate helpers
        helpers = DiscordLink.objects.filter(is_student_helper=True, is_active=True)
        helpers_removed = 0
        for discord_link in helpers:
            discord_link.is_student_helper = False
            discord_link.helper_removal_reason = "Competition ended"
            discord_link.helper_deactivated_at = timezone.now()
            discord_link.save()
            helpers_removed += 1

        if helpers_removed:
            results.append(f"Deactivated {helpers_removed} helpers")

        # Clear config
        config.competition_start_time = None
        config.competition_end_time = None
        config.applications_enabled = False
        config.save()

        # Disable accounts
        success_count = 0
        failed_count = 0
        for i in range(1, 51):
            username = f"team{i:02d}"
            success, _ = toggle_authentik_user(username, is_active=False)
            if success:
                success_count += 1
            else:
                failed_count += 1

        results.append(f"Disabled {success_count}/50 accounts")

        # Create task for bot to delete channels
        msg = f"Competition ended by {authentik_username}. Run /competition end-competition to delete channels."
        DiscordTask.objects.create(
            task_type="broadcast_message",
            payload={"message": msg},
            status="pending",
        )

        AuditLog.objects.create(
            action="competition_ended",
            admin_user=authentik_username,
            target_entity="competition",
            target_id=0,
            details={
                "deactivated_links": deactivated,
                "helpers_removed": helpers_removed,
                "accounts_disabled": success_count,
            },
        )

        return JsonResponse({"success": True, "message": ". ".join(results)})

    return JsonResponse({"error": "Unknown action"}, status=400)


@login_required
def admin_teams(request: HttpRequest) -> HttpResponse:
    """Teams management dashboard."""
    user = cast(User, request.user)
    authentik_username, _groups, _ = get_authentik_data(user)

    if not _check_admin(user):
        return render(
            request,
            "tickets_error.html",
            {
                "error": "Access denied",
                "message": "You do not have permission to access team management.",
            },
        )

    teams = Team.objects.all().order_by("team_number")

    teams_with_info = []
    for team in teams:
        member_count = DiscordLink.objects.filter(team=team, is_active=True).count()
        teams_with_info.append(
            {
                "team": team,
                "member_count": member_count,
            }
        )

    context = {
        "teams": teams_with_info,
        "show_ops_nav": True,
        "nav_active": "ops_admin",
    }

    return render(request, "admin/teams.html", context)


@login_required
def admin_team_detail(request: HttpRequest, team_number: int) -> HttpResponse:
    """View detailed team info."""
    user = cast(User, request.user)

    if not _check_admin(user):
        return render(
            request,
            "tickets_error.html",
            {"error": "Access denied", "message": "You do not have permission to view team details."},
        )

    try:
        team = Team.objects.get(team_number=team_number)
    except Team.DoesNotExist:
        return render(
            request, "tickets_error.html", {"error": "Not found", "message": f"Team {team_number} not found."}
        )

    members = DiscordLink.objects.filter(team=team, is_active=True).order_by("linked_at")

    context = {
        "team": team,
        "members": members,
        "show_ops_nav": True,
        "nav_active": "ops_admin",
    }

    return render(request, "admin/team_detail.html", context)


@login_required
def admin_team_action(request: HttpRequest, team_number: int) -> HttpResponse:
    """Handle team management actions."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username, _groups, _ = get_authentik_data(user)

    if not _check_admin(user):
        return JsonResponse({"error": "Access denied"}, status=403)

    try:
        team = Team.objects.get(team_number=team_number)
    except Team.DoesNotExist:
        return JsonResponse({"error": f"Team {team_number} not found"}, status=404)

    action = request.POST.get("action")

    if action == "activate":
        team.is_active = True
        team.save()
        AuditLog.objects.create(
            action="team_activated",
            admin_user=authentik_username,
            target_entity="team",
            target_id=team_number,
            details={"team_name": team.team_name},
        )
        return JsonResponse({"success": True, "message": f"Team {team_number} activated"})

    elif action == "deactivate":
        team.is_active = False
        team.save()
        AuditLog.objects.create(
            action="team_deactivated",
            admin_user=authentik_username,
            target_entity="team",
            target_id=team_number,
            details={"team_name": team.team_name},
        )
        return JsonResponse({"success": True, "message": f"Team {team_number} deactivated"})

    elif action == "unlink_user":
        discord_id = request.POST.get("discord_id")
        if not discord_id:
            return JsonResponse({"error": "Discord ID required"}, status=400)

        try:
            link = DiscordLink.objects.get(discord_id=int(discord_id), team=team, is_active=True)
            link.is_active = False
            link.unlinked_at = timezone.now()
            link.save()

            AuditLog.objects.create(
                action="user_unlinked",
                admin_user=authentik_username,
                target_entity="discord_link",
                target_id=int(discord_id),
                details={
                    "discord_username": link.discord_username,
                    "team_name": team.team_name,
                    "authentik_username": link.user.username,
                },
            )

            return JsonResponse({"success": True, "message": f"User {link.discord_username} unlinked"})
        except DiscordLink.DoesNotExist:
            return JsonResponse({"error": "User not found or not linked to this team"}, status=404)

    elif action == "reset":
        # Unlink all users
        links = DiscordLink.objects.filter(team=team, is_active=True)
        unlinked = 0
        for link in links:
            link.is_active = False
            link.unlinked_at = timezone.now()
            link.save()
            unlinked += 1

        # Reset password
        password = generate_blueteam_password()
        success, error = reset_blueteam_password(team_number, password)

        # Revoke sessions
        auth_manager = AuthentikManager()
        username = f"team{team_number:02d}"
        session_success, session_error, sessions_revoked = auth_manager.revoke_user_sessions(username)

        AuditLog.objects.create(
            action="team_reset",
            admin_user=authentik_username,
            target_entity="team",
            target_id=team_number,
            details={
                "team_name": team.team_name,
                "unlinked_members": unlinked,
                "password_reset": success,
                "sessions_revoked": sessions_revoked,
            },
        )

        if success:
            return JsonResponse(
                {
                    "success": True,
                    "message": f"Team reset: {unlinked} unlinked, {sessions_revoked} sessions revoked",
                    "password": password,
                }
            )
        else:
            return JsonResponse(
                {
                    "success": False,
                    "message": f"Team partially reset: {unlinked} unlinked, but password reset failed: {error}",
                }
            )

    elif action == "recreate_channels":
        # Create Discord task for bot to handle
        DiscordTask.objects.create(
            task_type="setup_team_infrastructure",
            payload={"team_number": team_number},
            status="pending",
        )

        AuditLog.objects.create(
            action="team_channels_recreate_requested",
            admin_user=authentik_username,
            target_entity="team",
            target_id=team_number,
            details={"team_name": team.team_name},
        )

        return JsonResponse({"success": True, "message": "Channel recreation task queued for Discord bot"})

    return JsonResponse({"error": "Unknown action"}, status=400)


@login_required
def admin_teams_bulk_action(request: HttpRequest) -> HttpResponse:
    """Handle bulk team actions."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username, _groups, _ = get_authentik_data(user)

    if not _check_admin(user):
        return JsonResponse({"error": "Access denied"}, status=403)

    action = request.POST.get("action")
    team_numbers_str = request.POST.get("team_numbers", "").strip()

    if not team_numbers_str:
        return JsonResponse({"error": "Team numbers required"}, status=400)

    try:
        team_numbers = parse_team_range(team_numbers_str)
    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)

    if action == "activate":
        updated = Team.objects.filter(team_number__in=team_numbers).update(is_active=True)
        AuditLog.objects.create(
            action="teams_activated",
            admin_user=authentik_username,
            target_entity="teams",
            target_id=0,
            details={"team_numbers": team_numbers, "updated_count": updated},
        )
        return JsonResponse({"success": True, "message": f"Activated {updated} teams"})

    elif action == "deactivate":
        updated = Team.objects.filter(team_number__in=team_numbers).update(is_active=False)
        AuditLog.objects.create(
            action="teams_deactivated",
            admin_user=authentik_username,
            target_entity="teams",
            target_id=0,
            details={"team_numbers": team_numbers, "updated_count": updated},
        )
        return JsonResponse({"success": True, "message": f"Deactivated {updated} teams"})

    elif action == "recreate":
        for team_number in team_numbers:
            DiscordTask.objects.create(
                task_type="setup_team_infrastructure",
                payload={"team_number": team_number},
                status="pending",
            )

        AuditLog.objects.create(
            action="teams_recreate_requested",
            admin_user=authentik_username,
            target_entity="teams",
            target_id=0,
            details={"team_numbers": team_numbers},
        )

        return JsonResponse({"success": True, "message": f"Queued {len(team_numbers)} channel recreation tasks"})

    return JsonResponse({"error": "Unknown action"}, status=400)


@login_required
def admin_helpers(request: HttpRequest) -> HttpResponse:
    """Helpers management dashboard."""
    user = cast(User, request.user)

    if not _check_admin(user):
        return render(
            request,
            "tickets_error.html",
            {"error": "Access denied", "message": "You do not have permission to manage helpers."},
        )

    helpers = (
        DiscordLink.objects.filter(helper_role_name__isnull=False, is_active=True)
        .exclude(helper_role_name="")
        .order_by("-helper_activated_at")
    )

    context = {
        "helpers": helpers,
        "show_ops_nav": True,
        "nav_active": "ops_admin",
    }

    return render(request, "admin/helpers.html", context)


@login_required
def admin_helper_action(request: HttpRequest) -> HttpResponse:
    """Handle helper management actions."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username, _groups, _ = get_authentik_data(user)

    if not _check_admin(user):
        return JsonResponse({"error": "Access denied"}, status=403)

    action = request.POST.get("action")

    if action == "add":
        discord_id = request.POST.get("discord_id", "").strip()
        role_name = request.POST.get("role_name", "").strip()

        if not discord_id or not role_name:
            return JsonResponse({"error": "Discord ID and role name required"}, status=400)

        # Find DiscordLink by discord_id
        try:
            discord_link = DiscordLink.objects.select_related("user__usergroups").get(
                discord_id=int(discord_id), is_active=True
            )
        except (DiscordLink.DoesNotExist, ValueError):
            return JsonResponse({"error": "DiscordLink not found. User must link their account first."}, status=404)

        if discord_link.is_student_helper:
            return JsonResponse(
                {"error": f"User is already a helper with role: {discord_link.helper_role_name}"}, status=400
            )

        from core.auth_utils import check_groups_for_permission

        try:
            groups = discord_link.user.usergroups.groups
        except Exception:
            groups = []

        if not check_groups_for_permission(groups, "helper_eligible"):
            return JsonResponse(
                {"error": "User must have WCComps_Ticketing_Support or WCComps_Quotient_Injects group"}, status=400
            )

        # Role ID will be set later by Discord bot when it assigns the role
        discord_link.set_helper(role_name)

        AuditLog.objects.create(
            action="helper_added",
            admin_user=authentik_username,
            target_entity="discordlink",
            target_id=discord_link.id,
            details={
                "discord_id": discord_link.discord_id,
                "discord_username": discord_link.discord_username,
                "role_name": role_name,
            },
        )

        return JsonResponse({"success": True, "message": f"Added {discord_link.discord_username} as helper"})

    elif action == "remove":
        discord_link_id = request.POST.get("discord_link_id")
        reason = request.POST.get("reason", "Removed via web interface")

        if not discord_link_id:
            return JsonResponse({"error": "DiscordLink ID required"}, status=400)

        try:
            discord_link = DiscordLink.objects.get(pk=int(discord_link_id))
        except (DiscordLink.DoesNotExist, ValueError):
            return JsonResponse({"error": "DiscordLink not found"}, status=404)

        if not discord_link.is_student_helper:
            return JsonResponse({"error": "User is not currently a helper"}, status=400)

        role_name = discord_link.helper_role_name
        discord_link.remove_helper(reason)

        AuditLog.objects.create(
            action="helper_removed",
            admin_user=authentik_username,
            target_entity="discordlink",
            target_id=discord_link.id,
            details={
                "discord_id": discord_link.discord_id,
                "discord_username": discord_link.discord_username,
                "role_name": role_name,
                "reason": reason,
            },
        )

        return JsonResponse({"success": True, "message": f"Removed {discord_link.discord_username} as helper"})

    return JsonResponse({"error": "Unknown action"}, status=400)


@login_required
def admin_broadcast(request: HttpRequest) -> HttpResponse:
    """Broadcast message page."""
    user = cast(User, request.user)

    if not _check_admin(user):
        return render(
            request,
            "tickets_error.html",
            {"error": "Access denied", "message": "You do not have permission to broadcast messages."},
        )

    teams = Team.objects.filter(is_active=True).order_by("team_number")

    context = {
        "teams": teams,
        "show_ops_nav": True,
        "nav_active": "ops_admin",
    }

    return render(request, "admin/broadcast.html", context)


@login_required
def admin_broadcast_action(request: HttpRequest) -> HttpResponse:
    """Handle broadcast action."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username, _groups, _ = get_authentik_data(user)

    if not _check_admin(user):
        return JsonResponse({"error": "Access denied"}, status=403)

    target = request.POST.get("target", "").strip()
    message = request.POST.get("message", "").strip()

    if not target or not message:
        return JsonResponse({"error": "Target and message required"}, status=400)

    # Create Discord task for bot to handle broadcast
    DiscordTask.objects.create(
        task_type="broadcast_message",
        payload={
            "target": target,
            "message": message,
            "sender": authentik_username,
        },
        status="pending",
    )

    AuditLog.objects.create(
        action="broadcast_message",
        admin_user=authentik_username,
        target_entity="broadcast",
        target_id=0,
        details={
            "target": target,
            "message_preview": message[:200],
        },
    )

    return JsonResponse({"success": True, "message": "Broadcast task queued for Discord bot"})


@login_required
def admin_sync_roles(request: HttpRequest) -> HttpResponse:
    """Sync roles page."""
    user = cast(User, request.user)

    if not _check_admin(user):
        return render(
            request,
            "tickets_error.html",
            {"error": "Access denied", "message": "You do not have permission to sync roles."},
        )

    context = {
        "show_ops_nav": True,
        "nav_active": "ops_admin",
    }

    return render(request, "admin/sync_roles.html", context)


@login_required
def admin_sync_roles_action(request: HttpRequest) -> HttpResponse:
    """Handle role sync action."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username, _groups, _ = get_authentik_data(user)

    if not _check_admin(user):
        return JsonResponse({"error": "Access denied"}, status=403)

    # Create a task for the bot to perform the sync
    task = DiscordTask.objects.create(
        task_type="sync_roles",
        payload={"requested_by": authentik_username},
        status="pending",
    )

    AuditLog.objects.create(
        action="role_sync_started",
        admin_user=authentik_username,
        target_entity="guilds",
        target_id=0,
        details={"source": "web", "task_id": task.id},
    )

    return JsonResponse(
        {
            "success": True,
            "message": "Role sync started. Results will be posted to the ops channel when complete.",
        }
    )
