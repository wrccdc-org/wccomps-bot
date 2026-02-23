"""Incident reports, screenshots, and gold team review views."""

from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.auth_utils import has_permission, require_permission
from team.models import Team

from ..calculator import calculate_suggested_recovery_points, suggest_red_score_matches
from ..forms import IncidentMatchForm, IncidentReportForm
from ..models import IncidentReport, IncidentScreenshot
from ._helpers import _get_user_team


@transaction.atomic
def submit_incident_report(request: HttpRequest) -> HttpResponse:
    """Submit incident report (blue team or admin)."""

    user = cast(User, request.user)
    is_admin = has_permission(user, "gold_team")
    team: Team | None = None

    if not is_admin:
        team = _get_user_team(user)
        if not team:
            messages.error(request, "You must be assigned to a team to submit incident reports")
            return redirect("scoring:leaderboard")

    if request.method == "POST":
        form = IncidentReportForm(team, is_admin, request.POST, request.FILES)

        if form.is_valid():
            incident = form.save(commit=False)

            # For admin, get team from form; for regular users, use their team
            if is_admin:
                incident.team = form.cleaned_data["team"]
            elif team is not None:
                incident.team = team
            else:
                # This should never happen due to earlier validation
                messages.error(request, "Team assignment error")
                return redirect("scoring:leaderboard")

            incident.submitted_by = user
            incident.save()

            # Handle screenshot uploads with validation
            screenshots = request.FILES.getlist("screenshots")
            max_screenshots = 20

            if len(screenshots) > max_screenshots:
                messages.error(request, f"Maximum {max_screenshots} screenshots allowed per submission")
                incident.delete()
                return redirect("scoring:submit_incident_report")

            try:
                for screenshot in screenshots:
                    file_data = screenshot.read()
                    IncidentScreenshot.objects.create(
                        incident=incident,
                        file_data=file_data,
                        filename=screenshot.name or "screenshot.png",
                        mime_type=screenshot.content_type or "image/png",
                    )
            except Exception as e:
                messages.error(request, f"File upload failed: {str(e)}")
                incident.delete()
                return redirect("scoring:submit_incident_report")

            messages.success(request, f"Incident report #{incident.id} submitted successfully")
            return redirect("scoring:view_incident_report", incident_id=incident.id)
    else:
        form = IncidentReportForm(team, is_admin)

    # Get box metadata for JavaScript (IP auto-population and service filtering)
    from quotient.client import QuotientClient

    box_metadata = {}
    client = QuotientClient()
    infra = client.get_infrastructure()
    if infra:
        for box in infra.boxes:
            box_metadata[box.name] = {
                "ip": box.ip,
                "services": [svc.name for svc in box.services],
            }

    context = {
        "form": form,
        "team": team,
        "is_admin": is_admin,
        "box_metadata": box_metadata,
    }
    return render(request, "scoring/submit_incident.html", context)


def incident_list(request: HttpRequest) -> HttpResponse:
    """List all incidents for the user's team (blue team view)."""
    user = cast(User, request.user)

    if has_permission(user, "gold_team"):
        incidents = IncidentReport.objects.all().select_related("team", "submitted_by").order_by("-created_at")
    else:
        user_team = _get_user_team(user)
        if not user_team:
            return HttpResponseForbidden("You do not have permission to access this page")

        incidents = (
            IncidentReport.objects.filter(team=user_team).select_related("team", "submitted_by").order_by("-created_at")
        )

    context = {
        "incidents": incidents,
        "current_user": user,
    }
    return render(request, "scoring/incident_list.html", context)


def view_incident_report(request: HttpRequest, incident_id: int) -> HttpResponse:
    """View incident report details."""
    incident = get_object_or_404(IncidentReport, id=incident_id)

    user = cast(User, request.user)
    if not has_permission(user, "gold_team"):
        user_team = _get_user_team(user)
        if not user_team or incident.team != user_team:
            messages.error(request, "You do not have permission to view this incident report")
            return redirect("scoring:leaderboard")

    # Check if user can delete this incident
    can_delete = incident.submitted_by == user and not incident.gold_team_reviewed

    context = {
        "incident": incident,
        "can_delete": can_delete,
    }
    return render(request, "scoring/view_incident.html", context)


@transaction.atomic
@require_http_methods(["POST"])
def delete_incident_report(request: HttpRequest, incident_id: int) -> HttpResponse:
    """Delete an incident report (owner only, before review)."""
    incident = get_object_or_404(IncidentReport, id=incident_id)
    user = cast(User, request.user)

    # Only the submitter can delete their own report
    if incident.submitted_by != user:
        messages.error(request, "You can only delete your own incident reports")
        return redirect("scoring:view_incident_report", incident_id=incident_id)

    # Cannot delete if already reviewed
    if incident.gold_team_reviewed:
        messages.error(request, "Cannot delete an incident report that has already been reviewed")
        return redirect("scoring:view_incident_report", incident_id=incident_id)

    incident_num = incident.id
    incident.delete()
    messages.success(request, f"Incident report #{incident_num} deleted")
    return redirect("scoring:incident_list")


def incident_screenshot_download(request: HttpRequest, screenshot_id: int) -> HttpResponse:
    """Serve incident screenshot from database."""
    from django.http import Http404

    screenshot = get_object_or_404(IncidentScreenshot, id=screenshot_id)

    # Check permission: must be gold_team/staff or the team that submitted it
    user = cast(User, request.user)
    if not has_permission(user, "gold_team"):
        user_team = _get_user_team(user)
        if not user_team or screenshot.incident.team != user_team:
            return HttpResponseForbidden("You do not have permission to view this file")

    if not screenshot.file_data:
        raise Http404("File data not available (file was lost)")

    response = HttpResponse(screenshot.file_data, content_type=screenshot.mime_type)
    response["Content-Disposition"] = f'inline; filename="{screenshot.filename}"'
    return response


@require_permission(
    "gold_team", "white_team", error_message="Only Gold Team or White Team members can review incident reports"
)
def review_incidents(request: HttpRequest) -> HttpResponse:
    """Review and match incident reports (gold team)."""
    from django.core.paginator import Paginator

    # Get filter parameters
    status_filter = request.GET.get("status", "pending") or "pending"
    team_filter = request.GET.get("team", "")
    box_filter = request.GET.get("box", "")
    sort_by = request.GET.get("sort", "-created_at")
    page = request.GET.get("page", "1")

    base_query = IncidentReport.objects.select_related("team").prefetch_related("screenshots")

    # Apply status filter
    if status_filter == "pending":
        base_query = base_query.filter(gold_team_reviewed=False)
    elif status_filter == "reviewed":
        base_query = base_query.filter(gold_team_reviewed=True)

    # Apply other filters
    if team_filter:
        base_query = base_query.filter(team__id=team_filter)

    if box_filter:
        base_query = base_query.filter(affected_boxes__contains=[box_filter])

    # Validate and apply sort
    valid_sort_fields = [
        "created_at",
        "-created_at",
        "team__team_number",
        "-team__team_number",
        "attack_detected_at",
        "-attack_detected_at",
    ]
    if sort_by not in valid_sort_fields:
        sort_by = "-created_at"
    base_query = base_query.order_by(sort_by)

    # Pagination
    paginator = Paginator(base_query, 50)
    try:
        page_num = int(page)
    except ValueError:
        page_num = 1
    page_obj = paginator.get_page(page_num)

    # Stats (unfiltered counts)
    total_incidents = IncidentReport.objects.count()
    reviewed_count = IncidentReport.objects.filter(gold_team_reviewed=True).count()
    pending_count = total_incidents - reviewed_count

    # Get available teams for filter dropdown
    available_teams = Team.objects.filter(incident_reports__isnull=False).distinct().order_by("team_number")

    context = {
        "page_obj": page_obj,
        "total_incidents": total_incidents,
        "reviewed_count": reviewed_count,
        "pending_count": pending_count,
        "available_teams": available_teams,
        "selected_team": team_filter,
        "selected_box": box_filter,
        "status_filter": status_filter,
        "sort_by": sort_by,
    }

    # Return partial for htmx requests
    if request.headers.get("HX-Request"):
        return render(request, "cotton/review_incidents_table.html", context)

    return render(request, "scoring/review_incidents.html", context)


@require_permission(
    "gold_team", "white_team", error_message="Only Gold Team or White Team members can match incident reports"
)
@transaction.atomic
def match_incident(request: HttpRequest, incident_id: int) -> HttpResponse:
    """Match incident to red team finding (gold team)."""
    incident = get_object_or_404(IncidentReport, id=incident_id)

    # Get suggested matches
    suggested_findings = suggest_red_score_matches(incident)

    if request.method == "POST":
        form = IncidentMatchForm(suggested_findings, request.POST, instance=incident)

        if form.is_valid():
            incident = form.save(commit=False)
            incident.gold_team_reviewed = True
            incident.reviewed_by = cast(User, request.user)
            incident.reviewed_at = timezone.now()
            incident.save()

            messages.success(request, f"Incident #{incident.id} reviewed and {incident.points_returned} points awarded")
            return redirect("scoring:review_incidents")
    else:
        # Auto-suggest points if matching to a red finding
        if suggested_findings:
            suggested_points = calculate_suggested_recovery_points(incident, suggested_findings[0])
            form = IncidentMatchForm(
                suggested_findings, instance=incident, initial={"points_returned": suggested_points}
            )
        else:
            form = IncidentMatchForm(suggested_findings, instance=incident)

    context = {
        "incident": incident,
        "form": form,
        "suggested_findings": suggested_findings,
    }
    return render(request, "scoring/match_incident.html", context)
