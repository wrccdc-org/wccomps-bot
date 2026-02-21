from typing import cast

from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

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
