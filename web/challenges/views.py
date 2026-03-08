import csv
import json
from datetime import timedelta
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count
from django.http import HttpRequest, HttpResponse, JsonResponse
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
from challenges.services import assign_teams_round_robin, create_orange_score_from_assignment
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

    is_lead = has_permission(user, "gold_team")
    context: dict[str, object] = {
        "active_checkin": active_checkin,
        "assignments": my_assignments,
        "followups": followups,
        "is_lead": is_lead,
    }

    if is_lead:
        # Checked-in members
        checked_in_members = OrangeCheckIn.objects.filter(is_active=True).select_related("user")
        # All submitted/in-progress assignments for review
        review_assignments = (
            OrangeAssignment.objects.filter(status__in=["submitted", "in_progress"])
            .select_related("orange_check", "team", "user")
            .order_by("-submitted_at")
        )
        context["checked_in_members"] = checked_in_members
        context["review_assignments"] = review_assignments

    return render(request, "challenges/dashboard.html", context)


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

    assign_teams_round_robin(orange_check, users, active_teams)

    messages.success(request, f"Assigned {len(active_teams)} teams across {len(users)} users.")
    return redirect("challenges:check_detail", check_id=check_id)


@require_permission("orange_team", "gold_team", error_message="Only Orange Team members can access this page")
def assignment_save(request: HttpRequest, assignment_id: int) -> HttpResponse:
    """Autosave a criterion result for an assignment."""
    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    user = cast(User, request.user)
    assignment = get_object_or_404(OrangeAssignment, pk=assignment_id, user=user)

    if assignment.status in ("submitted", "approved"):
        return JsonResponse({"error": "Assignment already submitted"}, status=400)

    try:
        data = json.loads(request.body)
        criterion_id = data["criterion_id"]
        met = data["met"]
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({"error": "Invalid data"}, status=400)

    result = get_object_or_404(OrangeAssignmentResult, assignment=assignment, criterion_id=criterion_id)
    result.met = met
    result.save()

    # Update assignment status to in_progress if still pending
    if assignment.status == "pending":
        assignment.status = "in_progress"
        assignment.save()

    score = assignment.calculate_score()
    max_score = assignment.orange_check.max_score
    return JsonResponse({"score": score, "max_score": max_score})


@require_permission("orange_team", "gold_team", error_message="Only Orange Team members can access this page")
def assignment_submit(request: HttpRequest, assignment_id: int) -> HttpResponse:
    """Submit a completed assignment for review."""
    if request.method != "POST":
        return redirect("challenges:dashboard")

    user = cast(User, request.user)
    assignment = get_object_or_404(OrangeAssignment, pk=assignment_id, user=user)

    if assignment.status in ("submitted", "approved"):
        messages.error(request, "Assignment already submitted.")
        return redirect("challenges:dashboard")

    assignment.score = assignment.calculate_score()
    assignment.status = "submitted"
    assignment.submitted_at = timezone.now()
    assignment.save()

    messages.success(
        request,
        f"Assignment submitted: {assignment.orange_check.title}"
        f" - Team {assignment.team.team_number}"
        f" ({assignment.score}/{assignment.orange_check.max_score})",
    )
    return redirect("challenges:dashboard")


@require_permission("orange_team", "gold_team", error_message="Only Orange Team members can access this page")
def followup_create(request: HttpRequest) -> HttpResponse:
    """Create a follow-up reminder for an assignment."""
    if request.method != "POST":
        return redirect("challenges:dashboard")

    user = cast(User, request.user)
    assignment_id = request.POST.get("assignment_id")
    minutes_str = request.POST.get("minutes", "15")
    note = request.POST.get("note", "").strip()

    try:
        minutes = int(minutes_str)
    except (ValueError, TypeError):
        messages.error(request, "Invalid minutes value.")
        return redirect("challenges:dashboard")

    assignment = get_object_or_404(OrangeAssignment, pk=assignment_id, user=user)
    OrangeFollowUp.objects.create(
        user=user,
        assignment=assignment,
        remind_at=timezone.now() + timedelta(minutes=minutes),
        note=note,
    )
    messages.success(request, f"Reminder set for {minutes} minutes.")
    return redirect("challenges:dashboard")


@require_permission("orange_team", "gold_team", error_message="Only Orange Team members can access this page")
def followup_dismiss(request: HttpRequest, followup_id: int) -> HttpResponse:
    """Dismiss a follow-up reminder."""
    if request.method != "POST":
        return redirect("challenges:dashboard")

    user = cast(User, request.user)
    followup = get_object_or_404(OrangeFollowUp, pk=followup_id, user=user)
    followup.dismissed = True
    followup.save()
    return redirect("challenges:dashboard")


@require_permission("gold_team", error_message="Only leads can approve assignments")
def assignment_approve(request: HttpRequest, assignment_id: int) -> HttpResponse:
    """Approve a submitted assignment, creating an OrangeTeamScore record."""
    if request.method != "POST":
        return redirect("challenges:dashboard")

    user = cast(User, request.user)
    assignment = get_object_or_404(
        OrangeAssignment.objects.select_related("orange_check", "team", "user"),
        pk=assignment_id,
    )

    if assignment.status != "submitted":
        messages.error(request, "Only submitted assignments can be approved.")
        return redirect("challenges:dashboard")

    assignment.status = "approved"
    assignment.reviewed_by = user
    assignment.reviewed_at = timezone.now()
    assignment.save()

    create_orange_score_from_assignment(assignment, user)

    messages.success(
        request,
        f"Approved: {assignment.orange_check.title} - Team {assignment.team.team_number} ({assignment.score} pts)",
    )
    return redirect("challenges:dashboard")


@require_permission("gold_team", error_message="Only leads can reject assignments")
def assignment_reject(request: HttpRequest, assignment_id: int) -> HttpResponse:
    """Reject a submitted assignment, sending it back to the teamer."""
    if request.method != "POST":
        return redirect("challenges:dashboard")

    user = cast(User, request.user)
    assignment = get_object_or_404(OrangeAssignment, pk=assignment_id)

    if assignment.status != "submitted":
        messages.error(request, "Only submitted assignments can be rejected.")
        return redirect("challenges:dashboard")

    notes = request.POST.get("notes", "").strip()
    assignment.status = "rejected"
    assignment.reviewed_by = user
    assignment.reviewed_at = timezone.now()
    assignment.notes = notes
    assignment.save()

    messages.success(
        request,
        f"Rejected: {assignment.orange_check.title} - Team {assignment.team.team_number}",
    )
    return redirect("challenges:dashboard")


@require_permission("gold_team", error_message="Only leads can export scores")
def export_scores(request: HttpRequest) -> HttpResponse:
    """Export all assignments as CSV."""
    assignments = (
        OrangeAssignment.objects.filter(status__in=["submitted", "approved"])
        .select_related("orange_check", "team", "user", "reviewed_by")
        .order_by("orange_check__title", "team__team_number")
    )

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="orange_scores.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "Check",
            "Team Number",
            "Team Name",
            "Assignee",
            "Score",
            "Max Score",
            "Status",
            "Submitted At",
            "Reviewed By",
            "Reviewed At",
        ]
    )
    for a in assignments:
        writer.writerow(
            [
                a.orange_check.title,
                a.team.team_number,
                a.team.team_name,
                a.user.username,
                a.score or 0,
                a.orange_check.max_score,
                a.status,
                a.submitted_at.strftime("%Y-%m-%d %H:%M") if a.submitted_at else "",
                a.reviewed_by.username if a.reviewed_by else "",
                a.reviewed_at.strftime("%Y-%m-%d %H:%M") if a.reviewed_at else "",
            ]
        )
    return response
