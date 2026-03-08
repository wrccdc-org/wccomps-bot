"""Orange team portal, review, approve/reject views."""

from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.auth_utils import require_permission

from ..models import OrangeTeamScore


def orange_team_portal(request: HttpRequest) -> HttpResponse:
    """Redirect to new orange team dashboard."""
    return redirect("challenges:dashboard")


@require_permission("gold_team", error_message="Only Gold Team members can review orange team")
def review_orange(request: HttpRequest) -> HttpResponse:
    """Gold team review page for orange team."""
    bonuses = OrangeTeamScore.objects.select_related("team", "submitted_by", "approved_by")
    return render(request, "scoring/review_orange.html", {"bonuses": bonuses})


def submit_orange_bonus(request: HttpRequest) -> HttpResponse:
    """Redirect to new orange team dashboard."""
    return redirect("challenges:dashboard")


@require_permission("gold_team", error_message="Only Gold Team members can approve adjustments")
@transaction.atomic
@require_http_methods(["POST"])
def approve_orange_adjustment(request: HttpRequest, adjustment_id: int) -> HttpResponse:
    """Approve individual Orange adjustment."""
    adjustment = get_object_or_404(OrangeTeamScore, id=adjustment_id)

    adjustment.is_approved = True
    adjustment.approved_at = timezone.now()
    adjustment.approved_by = cast(User, request.user)
    adjustment.save()

    messages.success(request, f"Adjustment #{adjustment.id} approved")
    return redirect("scoring:orange_team_portal")


@require_permission("gold_team", error_message="Only Gold Team members can reject adjustments")
@transaction.atomic
@require_http_methods(["POST"])
def reject_orange_adjustment(request: HttpRequest, adjustment_id: int) -> HttpResponse:
    """Reject individual Orange adjustment."""
    adjustment = get_object_or_404(OrangeTeamScore, id=adjustment_id)

    adjustment.is_approved = False
    adjustment.approved_at = None
    adjustment.approved_by = None
    adjustment.save()

    messages.success(request, f"Adjustment #{adjustment.id} rejected")
    return redirect("scoring:orange_team_portal")


@require_permission("gold_team", error_message="Only Gold Team members can bulk approve adjustments")
@transaction.atomic
@require_http_methods(["POST"])
def bulk_approve_orange_adjustments(request: HttpRequest) -> HttpResponse:
    """Bulk approve Orange adjustments."""
    adjustment_ids = request.POST.getlist("adjustment_ids")

    if not adjustment_ids:
        messages.info(request, "No adjustments selected")
        return redirect("scoring:orange_team_portal")

    # Convert to integers and filter valid IDs
    valid_ids = []
    for adj_id in adjustment_ids:
        try:
            valid_ids.append(int(adj_id))
        except (ValueError, TypeError):
            continue

    # Bulk update adjustments
    count = OrangeTeamScore.objects.filter(id__in=valid_ids).update(
        is_approved=True,
        approved_at=timezone.now(),
        approved_by=cast(User, request.user),
    )

    messages.success(request, f"Approved {count} adjustment(s)")
    return redirect("scoring:orange_team_portal")


@require_permission("gold_team", error_message="Only Gold Team members can bulk reject adjustments")
@transaction.atomic
@require_http_methods(["POST"])
def bulk_reject_orange_adjustments(request: HttpRequest) -> HttpResponse:
    """Bulk reject Orange adjustments."""
    adjustment_ids = request.POST.getlist("adjustment_ids")

    if not adjustment_ids:
        messages.info(request, "No adjustments selected")
        return redirect("scoring:orange_team_portal")

    # Convert to integers and filter valid IDs
    valid_ids = []
    for adj_id in adjustment_ids:
        try:
            valid_ids.append(int(adj_id))
        except (ValueError, TypeError):
            continue

    # Bulk update adjustments
    count = OrangeTeamScore.objects.filter(id__in=valid_ids).update(
        is_approved=False,
        approved_at=None,
        approved_by=None,
    )

    messages.success(request, f"Rejected {count} adjustment(s)")
    return redirect("scoring:orange_team_portal")
