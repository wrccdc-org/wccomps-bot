from typing import cast

from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from challenges.models import OrangeAssignment, OrangeCheckIn, OrangeFollowUp
from core.auth_utils import has_permission, require_permission


@require_permission("orange_team", "gold_team", error_message="Only Orange Team members can access this page")
def dashboard(request: HttpRequest) -> HttpResponse:
    """Orange team dashboard showing check-in status and assignments."""
    user = cast(User, request.user)

    # Check-in status
    active_checkin = OrangeCheckIn.objects.filter(user=user, is_active=True).first()

    # My assignments (pending and in-progress, with criteria pre-loaded)
    my_assignments = (
        OrangeAssignment.objects.filter(user=user)
        .exclude(status__in=["approved", "rejected"])
        .select_related("orange_check", "team")
        .prefetch_related("results__criterion")
        .order_by("orange_check__title", "team__team_number")
    )

    # Active follow-up reminders
    followups = OrangeFollowUp.objects.filter(
        user=user, dismissed=False
    ).select_related("assignment__orange_check", "assignment__team")

    return render(request, "challenges/dashboard.html", {
        "active_checkin": active_checkin,
        "assignments": my_assignments,
        "followups": followups,
        "is_lead": has_permission(user, "gold_team"),
    })


@require_permission("orange_team", "gold_team", error_message="Only Orange Team members can access this page")
def toggle_checkin(request: HttpRequest) -> HttpResponse:
    """Toggle check-in/out for the current user."""
    if request.method != "POST":
        return redirect("challenges:dashboard")
    user = cast(User, request.user)
    active = OrangeCheckIn.objects.filter(user=user, is_active=True).first()
    if active:
        active.is_active = False
        active.checked_out_at = timezone.now()
        active.save()
    else:
        OrangeCheckIn.objects.create(user=user)
    return redirect("challenges:dashboard")


@require_permission("gold_team", error_message="Only leads can manage check-ins")
def admin_toggle_checkin(request: HttpRequest, user_id: int) -> HttpResponse:
    """Toggle check-in/out for another user (lead only)."""
    if request.method != "POST":
        return redirect("challenges:dashboard")
    target_user = User.objects.get(pk=user_id)
    active = OrangeCheckIn.objects.filter(user=target_user, is_active=True).first()
    if active:
        active.is_active = False
        active.checked_out_at = timezone.now()
        active.save()
    else:
        OrangeCheckIn.objects.create(user=target_user)
    return redirect("challenges:dashboard")
