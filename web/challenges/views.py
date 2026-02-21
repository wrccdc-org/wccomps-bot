from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from challenges.models import (
    OrangeAssignment,
    OrangeCheck,
    OrangeCheckCriterion,
    OrangeCheckIn,
    OrangeFollowUp,
)
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
    followups = OrangeFollowUp.objects.filter(user=user, dismissed=False).select_related(
        "assignment__orange_check", "assignment__team"
    )

    return render(
        request,
        "challenges/dashboard.html",
        {
            "active_checkin": active_checkin,
            "assignments": my_assignments,
            "followups": followups,
            "is_lead": has_permission(user, "gold_team"),
        },
    )


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


@require_permission("gold_team", error_message="Only leads can manage checks")
def check_list(request: HttpRequest) -> HttpResponse:
    """List all orange checks for management."""
    checks = (
        OrangeCheck.objects.annotate(
            criteria_count=Count("criteria"),
            assignment_count=Count("assignments"),
        )
        .select_related("created_by")
        .order_by("-created_at")
    )
    return render(request, "challenges/check_list.html", {"checks": checks})


@require_permission("gold_team", error_message="Only leads can manage checks")
def check_create(request: HttpRequest) -> HttpResponse:
    """Create a new orange check with criteria."""
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        scheduled_at = request.POST.get("scheduled_at", "").strip() or None

        # Collect criteria from numbered form fields
        criteria: list[dict[str, str | int]] = []
        i = 0
        while f"criterion_label_{i}" in request.POST:
            label = request.POST.get(f"criterion_label_{i}", "").strip()
            points_str = request.POST.get(f"criterion_points_{i}", "").strip()
            if label and points_str:
                try:
                    points = int(points_str)
                    criteria.append({"label": label, "points": points, "sort_order": i})
                except ValueError:
                    pass
            i += 1

        # Validate
        if not title:
            messages.error(request, "Title is required.")
            return render(request, "challenges/check_form.html", {"mode": "create"})
        if not criteria:
            messages.error(request, "At least one criterion is required.")
            return render(request, "challenges/check_form.html", {"mode": "create"})

        user = cast(User, request.user)
        with transaction.atomic():
            orange_check = OrangeCheck.objects.create(
                title=title,
                description=description,
                scheduled_at=scheduled_at,
                created_by=user,
            )
            for c in criteria:
                OrangeCheckCriterion.objects.create(
                    orange_check=orange_check,
                    label=c["label"],
                    points=c["points"],
                    sort_order=c["sort_order"],
                )

        messages.success(request, f"Check '{title}' created with {len(criteria)} criteria.")
        return redirect("challenges:check_list")

    return render(request, "challenges/check_form.html", {"mode": "create"})
