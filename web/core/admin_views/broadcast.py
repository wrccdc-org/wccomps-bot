"""Admin views for broadcasting and role sync."""

from typing import cast

from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from core.models import AuditLog, DiscordTask
from team.models import Team

from .competition import _has_admin_or_gold_access


def admin_broadcast(request: HttpRequest) -> HttpResponse:
    """Broadcast message page."""
    user = cast(User, request.user)

    if not _has_admin_or_gold_access(user):
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


def admin_broadcast_action(request: HttpRequest) -> HttpResponse:
    """Handle broadcast action."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username = user.username

    if not _has_admin_or_gold_access(user):
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


def admin_sync_roles(request: HttpRequest) -> HttpResponse:
    """Sync roles page."""
    user = cast(User, request.user)

    if not _has_admin_or_gold_access(user):
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


def admin_sync_roles_action(request: HttpRequest) -> HttpResponse:
    """Handle role sync action."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    user = cast(User, request.user)
    authentik_username = user.username

    if not _has_admin_or_gold_access(user):
        return JsonResponse({"error": "Access denied"}, status=403)

    # For now, force dry_run=True until we're confident the sync is working correctly
    dry_run = True  # request.POST.get("dry_run", "true") == "true"

    # Create a task for the bot to perform the sync
    task = DiscordTask.objects.create(
        task_type="sync_roles",
        payload={"requested_by": authentik_username, "dry_run": dry_run},
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
            "task_id": task.id,
            "message": "Role sync started...",
        }
    )


def admin_task_status(request: HttpRequest, task_id: int) -> HttpResponse:
    """Check status of an async task."""
    user = cast(User, request.user)

    if not _has_admin_or_gold_access(user):
        return JsonResponse({"error": "Access denied"}, status=403)

    try:
        task = DiscordTask.objects.get(id=task_id)
    except DiscordTask.DoesNotExist:
        return JsonResponse({"error": "Task not found"}, status=404)

    response: dict[str, object] = {
        "status": task.status,
        "task_type": task.task_type,
    }

    if task.status == "completed":
        result = task.payload.get("result", {})
        if task.task_type == "sync_roles":
            response["message"] = (
                f"Sync complete: {result.get('roles_added', 0)} added, "
                f"{result.get('roles_removed', 0)} removed, "
                f"{result.get('errors', 0)} errors"
            )
        else:
            response["message"] = "Task completed"
    elif task.status == "failed":
        response["message"] = task.error_message or "Task failed"
    else:
        response["message"] = "Processing..."

    return JsonResponse(response)
