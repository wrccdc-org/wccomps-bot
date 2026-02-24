"""Inject grading, review, and feedback views."""

from decimal import Decimal
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.auth_utils import require_permission
from team.models import Team

from ..models import InjectScore


@require_permission("white_team", "gold_team", error_message="Only White/Gold Team members can access inject grading")
@transaction.atomic
def inject_grading(request: HttpRequest) -> HttpResponse:
    """Inject grading interface - select inject, grade all teams."""
    from quotient.client import QuotientClient

    client = QuotientClient()
    injects = client.get_injects()

    if injects is None:
        return render(request, "scoring/inject_grading.html", {"quotient_available": False, "no_injects": False})

    if len(injects) == 0:
        return render(request, "scoring/inject_grading.html", {"quotient_available": True, "no_injects": True})

    inject_choices = [(str(i.inject_id), i.title) for i in injects]
    inject_lookup = {str(i.inject_id): i for i in injects}

    # Get selected inject from query param or POST
    selected_inject_id = request.GET.get("inject") or request.POST.get("inject_id")
    selected_inject = inject_lookup.get(selected_inject_id) if selected_inject_id else None

    teams = Team.objects.filter(is_active=True).order_by("team_number")

    if request.method == "POST" and selected_inject:
        # Process grade submissions for all teams
        grades_saved = 0
        user = cast(User, request.user)

        for team in teams:
            field_name = f"points_team_{team.team_number}"
            points_value = request.POST.get(field_name, "").strip()

            if points_value:
                try:
                    points = Decimal(points_value)
                    InjectScore.objects.update_or_create(
                        team=team,
                        inject_id=selected_inject_id,
                        defaults={
                            "inject_name": selected_inject.title,
                            "points_awarded": points,
                            "graded_by": user,
                            "graded_at": timezone.now(),
                        },
                    )
                    grades_saved += 1
                except (ValueError, TypeError):
                    pass

        if grades_saved:
            messages.success(request, f"Saved {grades_saved} grades for {selected_inject.title}")
        return redirect(f"{reverse('scoring:inject_grading')}?inject={selected_inject_id}")

    # Get existing grades for selected inject and merge with teams
    team_data = []
    if selected_inject:
        existing = InjectScore.objects.filter(inject_id=selected_inject_id).select_related("team", "graded_by")
        grade_by_team = {g.team_id: g for g in existing}

        for team in teams:
            grade = grade_by_team.get(team.id)
            team_data.append(
                {
                    "team": team,
                    "grade": grade,
                    "points": grade.points_awarded if grade else None,
                }
            )

    context = {
        "quotient_available": True,
        "inject_choices": inject_choices,
        "selected_inject": selected_inject,
        "selected_inject_id": selected_inject_id,
        "team_data": team_data,
    }

    # Return partial for htmx requests
    if request.headers.get("HX-Request"):
        return render(request, "cotton/inject_grading_content.html", context)

    return render(request, "scoring/inject_grading.html", context)


@require_permission("gold_team", error_message="Only Gold Team members can review inject grades")
def inject_grades_review(request: HttpRequest) -> HttpResponse:
    """Review and approve inject grades (Gold Team)."""
    import statistics
    from collections import defaultdict

    from django.core.paginator import Paginator

    # Get filter parameters
    status_filter = request.GET.get("status", "pending") or "pending"
    inject_filter = request.GET.get("inject", "")
    team_filter = request.GET.get("team", "")
    show_outliers_only = request.GET.get("outliers") == "1"
    sort_by = request.GET.get("sort", "inject_name")
    if sort_by == "default":
        sort_by = ""
    page = request.GET.get("page", "1")

    base_query = InjectScore.objects.select_related("team", "graded_by")

    # Apply status filter
    if status_filter == "pending":
        base_query = base_query.filter(is_approved=False)
    elif status_filter == "approved":
        base_query = base_query.filter(is_approved=True)

    # Apply other filters
    if inject_filter:
        base_query = base_query.filter(inject_id=inject_filter)

    if team_filter:
        base_query = base_query.filter(team__id=team_filter)

    # Calculate outliers for each inject before filtering
    # Dynamically add is_outlier and std_devs_from_mean attrs to grade objects
    all_grades_for_outlier_calc = list(base_query)
    inject_grades_map: dict[str, list[InjectScore]] = defaultdict(list)
    for grade in all_grades_for_outlier_calc:
        inject_grades_map[grade.inject_id].append(grade)

    for grades in inject_grades_map.values():
        if len(grades) >= 3:
            points_list = [float(g.points_awarded) for g in grades]
            mean = statistics.mean(points_list)
            try:
                std_dev = statistics.stdev(points_list)
                for grade in grades:
                    points = float(grade.points_awarded)
                    z_score = abs(points - mean) / std_dev if std_dev > 0 else 0
                    grade.is_outlier = z_score > 1.5  # type: ignore[attr-defined]
                    grade.std_devs_from_mean = z_score  # type: ignore[attr-defined]
            except statistics.StatisticsError:
                for grade in grades:
                    grade.is_outlier = False  # type: ignore[attr-defined]
                    grade.std_devs_from_mean = 0  # type: ignore[attr-defined]
        else:
            for grade in grades:
                grade.is_outlier = False  # type: ignore[attr-defined]
                grade.std_devs_from_mean = 0  # type: ignore[attr-defined]

    # Filter outliers if requested
    if show_outliers_only:
        all_grades_for_outlier_calc = [g for g in all_grades_for_outlier_calc if g.is_outlier]  # type: ignore[attr-defined]

    # Validate and apply sort
    valid_sort_fields = [
        "inject_name",
        "-inject_name",
        "team__team_number",
        "-team__team_number",
        "points_awarded",
        "-points_awarded",
        "graded_at",
        "-graded_at",
    ]
    if sort_by and sort_by not in valid_sort_fields:
        sort_by = "inject_name"

    # Sort in Python since we already have the list
    if sort_by:
        reverse = sort_by.startswith("-")
        sort_key = sort_by.lstrip("-")
        if sort_key == "team__team_number":
            all_grades_for_outlier_calc.sort(key=lambda g: g.team.team_number, reverse=reverse)
        elif sort_key == "inject_name":
            all_grades_for_outlier_calc.sort(key=lambda g: g.inject_name, reverse=reverse)
        elif sort_key == "points_awarded":
            all_grades_for_outlier_calc.sort(key=lambda g: float(g.points_awarded), reverse=reverse)
        elif sort_key == "graded_at":
            all_grades_for_outlier_calc.sort(key=lambda g: g.graded_at, reverse=reverse)

    # Pagination
    paginator = Paginator(all_grades_for_outlier_calc, 50)
    try:
        page_num = int(page)
    except ValueError:
        page_num = 1
    page_obj = paginator.get_page(page_num)

    # Stats (unfiltered counts)
    total_grades = InjectScore.objects.count()
    approved_count = InjectScore.objects.filter(is_approved=True).count()
    unapproved_count = total_grades - approved_count

    # Get available injects and teams for filter dropdowns
    available_injects = InjectScore.objects.values("inject_id", "inject_name").distinct().order_by("inject_name")
    available_teams = Team.objects.filter(inject_grades__isnull=False).distinct().order_by("team_number")

    context = {
        "page_obj": page_obj,
        "unapproved_count": unapproved_count,
        "approved_count": approved_count,
        "total_grades": total_grades,
        "has_unapproved": unapproved_count > 0,
        "available_injects": available_injects,
        "available_teams": available_teams,
        "selected_inject": inject_filter,
        "selected_team": team_filter,
        "show_outliers_only": show_outliers_only,
        "status_filter": status_filter,
        "sort_by": sort_by,
    }

    # Return partial for htmx requests
    if request.headers.get("HX-Request"):
        return render(request, "cotton/inject_grades_table.html", context)

    return render(request, "scoring/review_inject_grades.html", context)


@require_permission("gold_team", error_message="Only Gold Team members can approve inject grades")
@transaction.atomic
@require_http_methods(["POST"])
def inject_grades_bulk_approve(request: HttpRequest) -> HttpResponse:
    """Bulk approve inject grades (Gold Team)."""
    user = cast(User, request.user)

    # Get grade IDs from POST data
    grade_ids_raw = request.POST.getlist("grade_ids")

    if not grade_ids_raw:
        messages.info(request, "No grades selected for approval")
        return redirect("scoring:inject_grades_review")

    # Convert to integers and filter invalid IDs
    grade_ids = []
    for grade_id in grade_ids_raw:
        try:
            grade_ids.append(int(grade_id))
        except (ValueError, TypeError):
            continue

    if not grade_ids:
        messages.warning(request, "Invalid grade IDs provided")
        return redirect("scoring:inject_grades_review")

    # Get grades to approve (only unapproved ones)
    grades_to_approve = InjectScore.objects.filter(id__in=grade_ids, is_approved=False)

    if not grades_to_approve.exists():
        messages.warning(request, "No unapproved grades found with provided IDs")
        return redirect("scoring:inject_grades_review")

    # Approve grades
    approval_time = timezone.now()
    approved_count = 0

    for grade in grades_to_approve:
        grade.is_approved = True
        grade.approved_at = approval_time
        grade.approved_by = user
        grade.save()
        approved_count += 1

    messages.success(request, f"Successfully approved {approved_count} inject grades")
    return redirect("scoring:inject_grades_review")


# --- Inject Feedback Review (Gold Team) ---


@require_permission("gold_team", "white_team", error_message="Only Gold/White Team members can review inject feedback")
def review_inject_feedback(request: HttpRequest) -> HttpResponse:
    """Gold/White team review of inject feedback before showing to teams."""
    inject_filter = request.GET.get("inject", "")
    status_filter = request.GET.get("status", "pending")

    scores = (
        InjectScore.objects.filter(is_approved=True)
        .exclude(inject_id="qualifier-total")
        .exclude(notes="")
        .select_related("team", "feedback_approved_by")
        .order_by("inject_name", "team__team_number")
    )

    if inject_filter:
        scores = scores.filter(inject_id=inject_filter)
    if status_filter == "pending":
        scores = scores.filter(feedback_approved=False)
    elif status_filter == "approved":
        scores = scores.filter(feedback_approved=True)

    # Get distinct inject IDs for filter dropdown
    inject_choices = (
        InjectScore.objects.filter(is_approved=True)
        .exclude(inject_id="qualifier-total")
        .exclude(notes="")
        .values_list("inject_id", "inject_name")
        .distinct()
        .order_by("inject_id")
    )

    has_unapproved = scores.filter(feedback_approved=False).exists()

    context = {
        "scores": scores,
        "inject_choices": inject_choices,
        "inject_filter": inject_filter,
        "status_filter": status_filter,
        "has_unapproved": has_unapproved,
    }
    return render(request, "scoring/review_inject_feedback.html", context)


@require_permission("gold_team", "white_team", error_message="Only Gold/White Team members can edit inject feedback")
@transaction.atomic
@require_http_methods(["POST"])
def save_inject_feedback(request: HttpRequest) -> HttpResponse:
    """Save edited feedback text for a single InjectScore."""
    score_id = request.POST.get("score_id")
    feedback_text = request.POST.get("feedback", "").strip()

    if not score_id:
        messages.warning(request, "No score specified")
        return redirect("scoring:review_inject_feedback")

    score = get_object_or_404(InjectScore, pk=score_id)
    score.feedback = feedback_text
    score.save(update_fields=["feedback"])

    messages.success(request, f"Saved feedback for {score.inject_name} - Team {score.team.team_number}")
    return redirect("scoring:review_inject_feedback")


@require_permission("gold_team", "white_team", error_message="Only Gold/White Team members can approve inject feedback")
@transaction.atomic
@require_http_methods(["POST"])
def approve_inject_feedback(request: HttpRequest) -> HttpResponse:
    """Approve feedback for a single InjectScore."""
    user = cast(User, request.user)
    score_id = request.POST.get("score_id")

    if not score_id:
        messages.warning(request, "No score specified")
        return redirect("scoring:review_inject_feedback")

    score = get_object_or_404(InjectScore, pk=score_id)
    score.feedback_approved = True
    score.feedback_approved_by = user
    score.save(update_fields=["feedback_approved", "feedback_approved_by"])

    messages.success(request, f"Approved feedback for {score.inject_name} - Team {score.team.team_number}")
    return redirect("scoring:review_inject_feedback")


@require_permission("gold_team", "white_team", error_message="Only Gold/White Team members can approve inject feedback")
@transaction.atomic
@require_http_methods(["POST"])
def bulk_approve_inject_feedback(request: HttpRequest) -> HttpResponse:
    """Bulk approve feedback for multiple InjectScore records."""
    user = cast(User, request.user)
    score_ids_raw = request.POST.getlist("score_ids")

    if not score_ids_raw:
        messages.info(request, "No feedback selected for approval")
        return redirect("scoring:review_inject_feedback")

    score_ids = []
    for sid in score_ids_raw:
        try:
            score_ids.append(int(sid))
        except (ValueError, TypeError):
            continue

    if not score_ids:
        messages.warning(request, "Invalid score IDs provided")
        return redirect("scoring:review_inject_feedback")

    scores_to_approve = InjectScore.objects.filter(
        id__in=score_ids,
        feedback_approved=False,
    )

    approved_count = 0
    for score in scores_to_approve:
        score.feedback_approved = True
        score.feedback_approved_by = user
        score.save(update_fields=["feedback_approved", "feedback_approved_by"])
        approved_count += 1

    messages.success(request, f"Approved feedback for {approved_count} inject scores")
    return redirect("scoring:review_inject_feedback")
