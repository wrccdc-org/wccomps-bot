import random
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from challenges.models import (
    OrangeAssignment,
    OrangeAssignmentResult,
    OrangeCheck,
    OrangeCheckCriterion,
    OrangeCheckIn,
    OrangeFollowUp,
)
from core.auth_utils import has_permission, require_permission
from team.models import Team


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


@require_permission("gold_team", error_message="Only leads can manage checks")
def check_detail(request: HttpRequest, check_id: int) -> HttpResponse:
    """Show check details with criteria and assignments."""
    orange_check = get_object_or_404(
        OrangeCheck.objects.prefetch_related("criteria", "assignments__user", "assignments__team"),
        pk=check_id,
    )
    checked_in_users = User.objects.filter(orange_checkins__is_active=True).distinct()
    return render(
        request,
        "challenges/check_detail.html",
        {
            "orange_check": orange_check,
            "checked_in_users": checked_in_users,
        },
    )


@require_permission("gold_team", error_message="Only leads can manage checks")
def check_edit(request: HttpRequest, check_id: int) -> HttpResponse:
    """Edit an existing orange check and its criteria."""
    orange_check = get_object_or_404(OrangeCheck, pk=check_id)

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        scheduled_at = request.POST.get("scheduled_at", "").strip() or None

        criteria_data: list[dict[str, str | int]] = []
        i = 0
        while f"criterion_label_{i}" in request.POST:
            label = request.POST.get(f"criterion_label_{i}", "").strip()
            points_str = request.POST.get(f"criterion_points_{i}", "").strip()
            if label and points_str:
                try:
                    points = int(points_str)
                    criteria_data.append({"label": label, "points": points, "sort_order": i})
                except ValueError:
                    pass
            i += 1

        if not title:
            messages.error(request, "Title is required.")
            return render(
                request,
                "challenges/check_form.html",
                {"mode": "edit", "orange_check": orange_check},
            )
        if not criteria_data:
            messages.error(request, "At least one criterion is required.")
            return render(
                request,
                "challenges/check_form.html",
                {"mode": "edit", "orange_check": orange_check},
            )

        with transaction.atomic():
            orange_check.title = title
            orange_check.description = description
            orange_check.scheduled_at = scheduled_at
            orange_check.save()
            # Replace criteria
            orange_check.criteria.all().delete()
            for c in criteria_data:
                OrangeCheckCriterion.objects.create(
                    orange_check=orange_check,
                    label=c["label"],
                    points=c["points"],
                    sort_order=c["sort_order"],
                )

        messages.success(request, f"Check '{title}' updated.")
        return redirect("challenges:check_detail", check_id=orange_check.pk)

    existing_criteria = list(orange_check.criteria.values("label", "points"))
    return render(
        request,
        "challenges/check_form.html",
        {
            "mode": "edit",
            "orange_check": orange_check,
            "existing_criteria": existing_criteria,
        },
    )


@require_permission("gold_team", error_message="Only leads can manage checks")
def check_duplicate(request: HttpRequest, check_id: int) -> HttpResponse:
    """Duplicate a check and its criteria into a new draft."""
    if request.method != "POST":
        return redirect("challenges:check_detail", check_id=check_id)
    original = get_object_or_404(OrangeCheck.objects.prefetch_related("criteria"), pk=check_id)
    user = cast(User, request.user)
    with transaction.atomic():
        new_check = OrangeCheck.objects.create(
            title=f"{original.title} (copy)",
            description=original.description,
            created_by=user,
            status="draft",
        )
        for criterion in original.criteria.all():
            OrangeCheckCriterion.objects.create(
                orange_check=new_check,
                label=criterion.label,
                points=criterion.points,
                sort_order=criterion.sort_order,
            )
    messages.success(request, f"Duplicated '{original.title}' as new draft.")
    return redirect("challenges:check_detail", check_id=new_check.pk)


@require_permission("gold_team", error_message="Only leads can manage checks")
def check_assign(request: HttpRequest, check_id: int) -> HttpResponse:
    """Assign checked-in users to score teams for a check."""
    if request.method != "POST":
        return redirect("challenges:check_detail", check_id=check_id)

    orange_check = get_object_or_404(OrangeCheck.objects.prefetch_related("criteria"), pk=check_id)
    user_ids = request.POST.getlist("user_ids")
    if not user_ids:
        messages.error(request, "Select at least one user to assign.")
        return redirect("challenges:check_detail", check_id=check_id)

    users = list(User.objects.filter(pk__in=user_ids))
    active_teams = list(Team.objects.filter(is_active=True).order_by("team_number"))

    if not active_teams:
        messages.error(request, "No active teams found.")
        return redirect("challenges:check_detail", check_id=check_id)

    # Shuffle teams and round-robin assign to users
    random.shuffle(active_teams)
    criteria = list(orange_check.criteria.all())

    with transaction.atomic():
        for i, team in enumerate(active_teams):
            assigned_user = users[i % len(users)]
            # Skip if assignment already exists for this check+team
            if OrangeAssignment.objects.filter(orange_check=orange_check, team=team).exists():
                continue
            assignment = OrangeAssignment.objects.create(
                orange_check=orange_check,
                user=assigned_user,
                team=team,
            )
            # Create result rows for each criterion
            for criterion in criteria:
                OrangeAssignmentResult.objects.create(
                    assignment=assignment,
                    criterion=criterion,
                    met=False,
                )

        orange_check.status = "active"
        orange_check.save()

    messages.success(request, f"Assigned {len(active_teams)} teams across {len(users)} users.")
    return redirect("challenges:check_detail", check_id=check_id)
