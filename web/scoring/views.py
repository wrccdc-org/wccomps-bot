"""Views for scoring system."""

from collections.abc import Callable
from decimal import Decimal
from functools import wraps
from typing import Any, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from team.models import Team

from .calculator import (
    calculate_suggested_recovery_points,
    calculate_team_score,
    get_leaderboard,
    recalculate_all_scores,
    suggest_red_finding_matches,
)
from .forms import (
    IncidentMatchForm,
    IncidentReportForm,
    OrangeTeamBonusForm,
    RedTeamFindingForm,
    ScoringTemplateForm,
)
from .models import (
    IncidentReport,
    IncidentScreenshot,
    InjectGrade,
    OrangeTeamBonus,
    QuotientMetadataCache,
    RedTeamFinding,
    RedTeamScreenshot,
    ScoringTemplate,
)
from .quotient_sync import sync_quotient_metadata, sync_service_scores


def require_team_role(
    role_check: Callable[[Any], bool], error_message: str = "You do not have permission to access this page"
) -> Callable[[Callable[..., HttpResponse]], Callable[..., HttpResponse]]:
    """Decorator to require specific team role (red, gold, orange, etc.)."""

    def decorator(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @wraps(view_func)
        def wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
            user = cast(User, request.user)
            # Staff always has access
            if user.is_staff:
                return view_func(request, *args, **kwargs)

            # Check if user has person object with required role
            if not hasattr(user, "person"):
                messages.error(request, error_message)
                return redirect("scoring:leaderboard")

            if not role_check(user.person):
                messages.error(request, error_message)
                return redirect("scoring:leaderboard")

            return view_func(request, *args, **kwargs)

        return wrapped_view

    return decorator


def leaderboard(request: HttpRequest) -> HttpResponse:
    """Public leaderboard view."""
    scores = get_leaderboard()

    context = {
        "scores": scores,
    }
    return render(request, "scoring/leaderboard.html", context)


@login_required
@require_team_role(
    lambda p: p.is_red_team() or p.is_gold_team(),
    "Only Red Team or Gold Team members can access this page",
)
def red_team_portal(request: HttpRequest) -> HttpResponse:
    """Red team portal - list and review findings."""
    base_query = RedTeamFinding.objects.prefetch_related("affected_teams", "screenshots")

    pending_findings = base_query.filter(points_per_team=0).order_by("-created_at")
    reviewed_findings = base_query.exclude(points_per_team=0).order_by("-created_at")

    total_findings = RedTeamFinding.objects.count()
    pending_count = pending_findings.count()
    reviewed_count = total_findings - pending_count

    context = {
        "pending_findings": pending_findings,
        "reviewed_findings": reviewed_findings,
        "total_findings": total_findings,
        "pending_count": pending_count,
        "reviewed_count": reviewed_count,
    }
    return render(request, "scoring/red_team_portal.html", context)


@login_required
@require_team_role(lambda p: p.is_red_team(), "Only Red Team members can submit findings")
@transaction.atomic
def submit_red_finding(request: HttpRequest) -> HttpResponse:
    """Submit red team finding."""

    if request.method == "POST":
        form = RedTeamFindingForm(request.POST, request.FILES)

        if form.is_valid():
            finding = form.save(commit=False)
            finding.submitted_by = cast(User, request.user)
            finding.points_per_team = 0  # Gold team will assign points during review
            finding.save()

            # Save M2M relationship for affected_teams
            form.save_m2m()

            # Handle screenshot uploads with validation
            screenshots = request.FILES.getlist("screenshots")
            max_screenshots = 20

            if len(screenshots) > max_screenshots:
                messages.error(request, f"Maximum {max_screenshots} screenshots allowed per submission")
                finding.delete()
                return redirect("scoring:submit_red_finding")

            try:
                for screenshot in screenshots:
                    RedTeamScreenshot.objects.create(
                        finding=finding,
                        image=screenshot,
                    )
            except Exception as e:
                messages.error(request, f"File upload failed: {str(e)}")
                finding.delete()
                return redirect("scoring:submit_red_finding")

            messages.success(request, f"Red team finding #{finding.id} submitted successfully")
            return redirect("scoring:red_team_portal")
    else:
        form = RedTeamFindingForm()

    # Get box metadata for auto-populating IP and services
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
        "box_metadata": box_metadata,
    }
    return render(request, "scoring/submit_red_finding.html", context)


@login_required
@transaction.atomic
def submit_incident_report(request: HttpRequest) -> HttpResponse:
    """Submit incident report (blue team or admin)."""

    user = cast(User, request.user)
    is_admin = user.is_staff
    team: Team | None = None

    # Get user's team if not admin
    if not is_admin:
        if hasattr(user, "person"):
            team_number = user.person.get_team_number()
            if team_number:
                team = Team.objects.filter(team_number=team_number).first()

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
                    IncidentScreenshot.objects.create(
                        incident=incident,
                        image=screenshot,
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


@login_required
def view_incident_report(request: HttpRequest, incident_id: int) -> HttpResponse:
    """View incident report details."""
    incident = get_object_or_404(IncidentReport, id=incident_id)

    # Check authorization: must be the owning team or staff
    user = cast(User, request.user)
    if not user.is_staff:
        # Check if user's team owns this incident
        user_team: Team | None = None
        if hasattr(user, "person"):
            team_number = user.person.get_team_number()
            if team_number:
                user_team = Team.objects.filter(team_number=team_number).first()

        if not user_team or incident.team != user_team:
            messages.error(request, "You do not have permission to view this incident report")
            return redirect("scoring:leaderboard")

    context = {
        "incident": incident,
    }
    return render(request, "scoring/view_incident.html", context)


@login_required
@require_team_role(lambda p: p.is_orange_team(), "Only Orange Team members can access this page")
def orange_team_portal(request: HttpRequest) -> HttpResponse:
    """Orange team portal - list existing bonuses."""
    bonuses = OrangeTeamBonus.objects.all().select_related("team")

    context = {
        "bonuses": bonuses,
    }
    return render(request, "scoring/orange_team_portal.html", context)


@login_required
@require_team_role(lambda p: p.is_orange_team(), "Only Orange Team members can submit bonuses")
@transaction.atomic
def submit_orange_bonus(request: HttpRequest) -> HttpResponse:
    """Submit orange team bonus."""

    if request.method == "POST":
        form = OrangeTeamBonusForm(request.POST)

        if form.is_valid():
            bonus = form.save(commit=False)
            bonus.submitted_by = cast(User, request.user)
            bonus.save()

            messages.success(request, f"Orange team bonus awarded to {bonus.team.team_name}")
            return redirect("scoring:orange_team_portal")
    else:
        form = OrangeTeamBonusForm()

    context = {
        "form": form,
    }
    return render(request, "scoring/submit_orange_bonus.html", context)


@login_required
@require_team_role(
    lambda p: p.is_white_team() or p.is_gold_team(), "Only White/Gold Team members can access inject grading"
)
def inject_grading(request: HttpRequest) -> HttpResponse:
    """Inject grading interface (white/gold team)."""
    from quotient.client import QuotientClient

    teams = Team.objects.filter(is_active=True).order_by("team_number")

    # Fetch injects from Quotient
    client = QuotientClient()
    injects = client.get_injects()

    if not injects:
        # Fallback to showing existing grades only
        grades = InjectGrade.objects.all().select_related("team").order_by("inject_name", "team__team_number")
        context = {
            "teams": teams,
            "grades": grades,
            "injects": [],
            "quotient_available": False,
        }
        return render(request, "scoring/inject_grading.html", context)

    # Get existing grades for these injects
    inject_ids = [i.inject_id for i in injects]
    existing_grades = InjectGrade.objects.filter(inject_id__in=inject_ids).select_related("team")

    # Build grade lookup: {inject_id: {team_number: grade}}
    grade_lookup: dict[str, dict[int, InjectGrade]] = {}
    for grade in existing_grades:
        if grade.inject_id not in grade_lookup:
            grade_lookup[grade.inject_id] = {}
        grade_lookup[grade.inject_id][grade.team.team_number] = grade

    # Build data structure for template
    inject_data = []
    for inject in injects:
        # All injects from API are available for grading
        team_grades = []
        for team in teams:
            team_grade: InjectGrade | None = grade_lookup.get(str(inject.inject_id), {}).get(team.team_number)
            team_grades.append(
                {
                    "team": team,
                    "grade": team_grade,
                    "points_awarded": team_grade.points_awarded if team_grade else None,
                }
            )

        inject_data.append(
            {
                "inject_id": inject.inject_id,
                "title": inject.title,
                "description": inject.description,
                "max_points": 100,  # Default max points, can be configured per inject
                "due_date": inject.due_time,
                "team_grades": team_grades,
            }
        )

    context = {
        "teams": teams,
        "inject_data": inject_data,
        "quotient_available": True,
    }
    return render(request, "scoring/inject_grading.html", context)


@login_required
@require_team_role(
    lambda p: p.is_white_team() or p.is_gold_team(), "Only White/Gold Team members can submit inject grades"
)
@transaction.atomic
@require_http_methods(["POST"])
def submit_inject_grades(request: HttpRequest) -> HttpResponse:
    """Submit inject grades (white/gold team)."""
    user = cast(User, request.user)

    # Parse form data: inject_{inject_id}_team_{team_number} = points_awarded
    grades_saved = 0
    errors = []

    for key, value in request.POST.items():
        if not key.startswith("inject_"):
            continue

        try:
            # Parse: inject_{inject_id}_team_{team_number}
            parts = key.split("_team_")
            if len(parts) != 2:
                continue

            inject_id = parts[0].replace("inject_", "")
            team_number = int(parts[1])

            # Skip empty values - request.POST values can be str or list
            value_str: str = (str(value[0]) if value else "") if isinstance(value, list) else value
            if not value_str or not value_str.strip():
                continue

            points_awarded = Decimal(value_str)

            # Get team
            team = Team.objects.get(team_number=team_number)

            # Get or create grade
            grade, created = InjectGrade.objects.get_or_create(
                team=team,
                inject_id=inject_id,
                defaults={
                    "inject_name": request.POST.get(f"inject_name_{inject_id}", ""),
                    "max_points": Decimal(request.POST.get(f"max_points_{inject_id}", "0")),
                    "points_awarded": points_awarded,
                    "graded_by": user,
                },
            )

            if not created:
                # Update existing grade
                grade.points_awarded = points_awarded
                grade.graded_by = user
                grade.save()

            grades_saved += 1

        except (ValueError, Team.DoesNotExist, KeyError) as e:
            errors.append(f"Error processing {key}: {e}")
            continue

    if errors:
        for error in errors:
            messages.warning(request, error)

    if grades_saved > 0:
        messages.success(request, f"Saved {grades_saved} inject grades")
    else:
        messages.info(request, "No grades to save")

    return redirect("scoring:inject_grading")


@login_required
@require_team_role(lambda p: p.is_gold_team(), "Only Gold Team members can review incident reports")
def review_incidents(request: HttpRequest) -> HttpResponse:
    """Review and match incident reports (gold team)."""

    # Get unreviewed incidents
    incidents = (
        IncidentReport.objects.filter(gold_team_reviewed=False)
        .select_related("team")
        .prefetch_related("screenshots")
        .order_by("-created_at")
    )

    # Get stats
    total_incidents = IncidentReport.objects.all().count()
    reviewed_count = IncidentReport.objects.filter(gold_team_reviewed=True).count()
    pending_count = total_incidents - reviewed_count

    context = {
        "incidents": incidents,
        "total_incidents": total_incidents,
        "reviewed_count": reviewed_count,
        "pending_count": pending_count,
    }
    return render(request, "scoring/review_incidents.html", context)


@login_required
@require_team_role(lambda p: p.is_gold_team(), "Only Gold Team members can match incident reports")
@transaction.atomic
def match_incident(request: HttpRequest, incident_id: int) -> HttpResponse:
    """Match incident to red team finding (gold team)."""
    incident = get_object_or_404(IncidentReport, id=incident_id)

    # Get suggested matches
    suggested_findings = suggest_red_finding_matches(incident)

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


@login_required
@user_passes_test(lambda u: u.is_staff)
def scoring_config(request: HttpRequest) -> HttpResponse:
    """Scoring configuration (admin)."""

    # Get or create scoring template (singleton)
    template = ScoringTemplate.objects.first()
    if not template:
        template = ScoringTemplate.objects.create()

    # Get metadata sync status
    try:
        metadata = QuotientMetadataCache.objects.first()
    except QuotientMetadataCache.DoesNotExist:
        metadata = None

    if request.method == "POST":
        form = ScoringTemplateForm(request.POST, instance=template)
        if form.is_valid():
            template = form.save(commit=False)
            template.updated_by = cast(User, request.user)
            template.save()
            messages.success(request, "Scoring configuration updated")
            return redirect("scoring:scoring_config")
    else:
        form = ScoringTemplateForm(instance=template)

    context = {
        "form": form,
        "template": template,
        "metadata": metadata,
    }
    return render(request, "scoring/scoring_config.html", context)


@login_required
@user_passes_test(lambda u: u.is_staff)
@require_http_methods(["POST"])
def sync_metadata(request: HttpRequest) -> HttpResponse:
    """Sync metadata from Quotient."""
    try:
        sync_quotient_metadata(cast(User, request.user))
        messages.success(request, "Metadata synced successfully")
    except ValueError as e:
        messages.error(request, f"Failed to sync metadata: {e}")
    except Exception as e:
        messages.error(request, f"Unexpected error syncing metadata: {e}")
    return redirect("scoring:scoring_config")


@login_required
@user_passes_test(lambda u: u.is_staff)
@require_http_methods(["POST"])
def sync_scores(request: HttpRequest) -> HttpResponse:
    """Sync service scores from Quotient."""
    try:
        result = sync_service_scores(cast(User, request.user))
        messages.success(request, f"Synced {result['total']} teams")
    except Exception as e:
        messages.error(request, f"Failed to sync scores: {e}")
    return redirect("scoring:scoring_config")


@login_required
@user_passes_test(lambda u: u.is_staff)
@require_http_methods(["POST"])
def recalculate_scores(request: HttpRequest) -> HttpResponse:
    """Recalculate all scores."""
    recalculate_all_scores()
    messages.success(request, "Scores recalculated successfully")
    return redirect("scoring:leaderboard")


def api_scores(request: HttpRequest) -> JsonResponse:
    """API endpoint for scores."""
    scores = get_leaderboard()
    data = [
        {
            "rank": score.rank,
            "team": score.team.team_name,
            "team_number": score.team.team_number,
            "total": float(score.total_score),
            "services": float(score.service_points),
            "injects": float(score.inject_points),
            "orange": float(score.orange_points),
            "red": float(score.red_deductions),
            "incidents": float(score.incident_recovery_points),
            "sla": float(score.sla_penalties),
        }
        for score in scores
    ]
    return JsonResponse({"scores": data})


def api_team_detail(request: HttpRequest, team_number: int) -> JsonResponse:
    """API endpoint for team detail."""
    team = get_object_or_404(Team, team_number=team_number)
    scores = calculate_team_score(team)
    return JsonResponse(
        {
            "team": team.team_name,
            "team_number": team.team_number,
            "scores": {k: float(v) for k, v in scores.items()},
        }
    )


@login_required
def api_attack_types(request: HttpRequest) -> JsonResponse:
    """API endpoint for attack type suggestions."""
    # Get distinct attack vectors from previous findings
    attack_vectors = (
        RedTeamFinding.objects.values_list("attack_vector", flat=True).distinct().order_by("attack_vector")[:50]
    )

    # Extract unique attack types, truncated to 50 chars
    suggestions = []
    seen: set[str] = set()
    for vector in attack_vectors:
        if vector:
            # Truncate to 50 chars max for short attack type names
            attack_type = vector.strip()[:50]
            if attack_type and attack_type.lower() not in seen:
                suggestions.append(attack_type)
                seen.add(attack_type.lower())

    return JsonResponse({"suggestions": sorted(suggestions)})
