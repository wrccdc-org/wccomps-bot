"""Orange team check review and bulk approve views."""

import contextlib
from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.auth_utils import require_permission

from ..models import OrangeTeamScore


def orange_team_portal(request: HttpRequest) -> HttpResponse:
    """Redirect to new orange team dashboard."""
    return redirect("challenges:dashboard")


@require_permission("orange_team", error_message="Only Orange Team or Gold Team members can review checks")
def review_orange(request: HttpRequest) -> HttpResponse:
    """Review page for orange team checks."""
    from challenges.models import OrangeCheck
    from django.core.paginator import Paginator
    from django.db.models import Q

    from team.models import Team

    status_filter = request.GET.get("status", "pending") or "pending"
    team_filter = request.GET.get("team", "")
    check_filter = request.GET.get("check", "")
    search_query = request.GET.get("search", "").strip()
    sort_by = request.GET.get("sort", "-created_at")
    if sort_by == "default":
        sort_by = ""
    page = request.GET.get("page", "1")

    base_query = OrangeTeamScore.objects.select_related("team", "submitted_by", "approved_by", "orange_check")

    if status_filter == "pending":
        base_query = base_query.filter(is_approved=False)
    elif status_filter == "approved":
        base_query = base_query.filter(is_approved=True)

    if team_filter:
        base_query = base_query.filter(team__id=team_filter)

    if check_filter:
        if check_filter == "manual":
            base_query = base_query.filter(orange_check__isnull=True)
        else:
            with contextlib.suppress(ValueError, TypeError):
                base_query = base_query.filter(orange_check_id=int(check_filter))

    if search_query:
        base_query = base_query.filter(Q(description__icontains=search_query))

    valid_sort_fields = [
        "created_at",
        "-created_at",
        "team__team_number",
        "-team__team_number",
        "points_awarded",
        "-points_awarded",
    ]
    if sort_by and sort_by not in valid_sort_fields:
        sort_by = "-created_at"
    if sort_by:
        base_query = base_query.order_by(sort_by)

    paginator = Paginator(base_query, 50)
    try:
        page_num = int(page)
    except ValueError:
        page_num = 1
    page_obj = paginator.get_page(page_num)

    total_checks = OrangeTeamScore.objects.count()
    pending_count = OrangeTeamScore.objects.filter(is_approved=False).count()
    approved_count = total_checks - pending_count

    available_teams = Team.objects.filter(orange_team_scores__isnull=False).distinct().order_by("team_number")
    available_checks = OrangeCheck.objects.filter(orange_scores__isnull=False).distinct().order_by("title")

    context = {
        "page_obj": page_obj,
        "total_checks": total_checks,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "has_pending": pending_count > 0,
        "available_teams": available_teams,
        "available_checks": available_checks,
        "selected_team": team_filter,
        "selected_check": check_filter,
        "search_query": search_query,
        "status_filter": status_filter,
        "sort_by": sort_by,
    }

    if request.headers.get("HX-Request"):
        return render(request, "cotton/review_orange_table.html", context)

    return render(request, "scoring/review_orange.html", context)


def submit_orange_check(request: HttpRequest) -> HttpResponse:
    """Redirect to new orange team dashboard."""
    return redirect("challenges:dashboard")


@require_permission("orange_team", error_message="Only Orange Team or Gold Team members can approve checks")
@transaction.atomic
@require_http_methods(["POST"])
def bulk_approve_orange_adjustments(request: HttpRequest) -> HttpResponse:
    """Bulk approve orange team checks."""
    adjustment_ids = request.POST.getlist("adjustment_ids")

    if not adjustment_ids:
        messages.info(request, "No checks selected")
        return redirect("scoring:review_orange")

    # Convert to integers and filter valid IDs
    valid_ids = []
    for adj_id in adjustment_ids:
        try:
            valid_ids.append(int(adj_id))
        except ValueError, TypeError:
            continue

    # Bulk update adjustments
    count = OrangeTeamScore.objects.filter(id__in=valid_ids).update(
        is_approved=True,
        approved_at=timezone.now(),
        approved_by=cast(User, request.user),
    )

    messages.success(request, f"Approved {count} check(s)")
    return redirect("scoring:review_orange")
