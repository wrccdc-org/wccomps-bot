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
    OrangeCheckTypeForm,
    OrangeTeamBonusForm,
    RedTeamFindingForm,
    ScoringTemplateForm,
)
from .models import (
    IncidentReport,
    IncidentScreenshot,
    InjectGrade,
    OrangeCheckType,
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


def _get_user_team(user: User) -> Team | None:
    """Get team for a user based on their Person object."""
    if not hasattr(user, "person"):
        return None

    team_number = user.person.get_team_number()
    if not team_number:
        return None

    return Team.objects.filter(team_number=team_number).first()


def require_leaderboard_access(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Decorator to restrict leaderboard access to Gold/White Team, Ticketing Admin, and System Admin."""

    @wraps(view_func)
    def wrapped_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        from django.http import HttpResponseForbidden

        user = cast(User, request.user)

        # Staff always has access
        if user.is_staff:
            return view_func(request, *args, **kwargs)

        # Check if user has person object with required role
        if not hasattr(user, "person"):
            return HttpResponseForbidden("You do not have permission to access this page")

        person = user.person
        if person.is_gold_team() or person.is_white_team() or person.has_group("WCComps_Ticketing_Admin"):
            return view_func(request, *args, **kwargs)

        return HttpResponseForbidden("You do not have permission to access this page")

    return wrapped_view


@login_required
@require_leaderboard_access
def leaderboard(request: HttpRequest) -> HttpResponse:
    """Restricted leaderboard view - accessible only by Gold/White Team, Ticketing Admin, and System Admin."""
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

    # Apply filters from query parameters
    team_filter = request.GET.get("team")
    attack_type_filter = request.GET.get("attack_type")
    submitter_filter = request.GET.get("submitter")

    if team_filter:
        base_query = base_query.filter(affected_teams__id=team_filter)

    if attack_type_filter:
        base_query = base_query.filter(attack_vector__icontains=attack_type_filter)

    if submitter_filter:
        base_query = base_query.filter(submitted_by__id=submitter_filter)

    # Apply distinct to avoid duplicates from M2M joins
    base_query = base_query.distinct()

    pending_findings = base_query.filter(is_approved=False).order_by("-created_at")
    reviewed_findings = base_query.filter(is_approved=True).order_by("-created_at")

    total_findings = RedTeamFinding.objects.count()
    pending_count = pending_findings.count()
    reviewed_count = total_findings - pending_count

    # Get available teams and submitters for filter dropdowns
    available_teams = Team.objects.filter(red_team_findings__isnull=False).distinct().order_by("team_number")
    available_submitters = User.objects.filter(red_findings_submitted__isnull=False).distinct().order_by("username")

    # Check if user is Gold Team
    user = cast(User, request.user)
    is_gold_team = user.is_staff or (hasattr(user, "person") and user.person.is_gold_team())

    context = {
        "pending_findings": pending_findings,
        "reviewed_findings": reviewed_findings,
        "total_findings": total_findings,
        "pending_count": pending_count,
        "reviewed_count": reviewed_count,
        "available_teams": available_teams,
        "available_submitters": available_submitters,
        "selected_team": team_filter,
        "selected_attack_type": attack_type_filter,
        "selected_submitter": submitter_filter,
        "is_gold_team": is_gold_team,
    }
    return render(request, "scoring/red_team_portal.html", context)


@login_required
@require_team_role(
    lambda p: p.is_gold_team(),
    "Only Gold Team members can bulk approve findings",
)
@transaction.atomic
@require_http_methods(["POST"])
def bulk_approve_red_findings(request: HttpRequest) -> HttpResponse:
    """Bulk approve red team findings (Gold Team only)."""
    user = cast(User, request.user)

    # Get finding IDs from POST data
    finding_ids = request.POST.getlist("finding_ids")

    if not finding_ids:
        messages.info(request, "No findings selected for approval")
        return redirect("scoring:red_team_portal")

    # Convert to integers and filter out invalid values
    valid_ids = []
    for fid in finding_ids:
        try:
            valid_ids.append(int(fid))
        except (ValueError, TypeError):
            continue

    if not valid_ids:
        messages.warning(request, "No valid finding IDs provided")
        return redirect("scoring:red_team_portal")

    # Approve findings that are not already approved
    findings_to_approve = RedTeamFinding.objects.filter(id__in=valid_ids, is_approved=False)

    approved_count = 0
    now = timezone.now()

    for finding in findings_to_approve:
        finding.is_approved = True
        finding.approved_at = now
        finding.approved_by = user
        finding.save()
        approved_count += 1

    if approved_count > 0:
        messages.success(request, f"Successfully approved {approved_count} finding(s)")
    else:
        messages.info(request, "No unapproved findings found to approve")

    return redirect("scoring:red_team_portal")


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
def incident_list(request: HttpRequest) -> HttpResponse:
    """List all incidents for the user's team (blue team view)."""
    from django.http import HttpResponseForbidden

    user = cast(User, request.user)

    if user.is_staff:
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
    }
    return render(request, "scoring/incident_list.html", context)


@login_required
def view_incident_report(request: HttpRequest, incident_id: int) -> HttpResponse:
    """View incident report details."""
    incident = get_object_or_404(IncidentReport, id=incident_id)

    user = cast(User, request.user)
    if not user.is_staff:
        user_team = _get_user_team(user)
        if not user_team or incident.team != user_team:
            messages.error(request, "You do not have permission to view this incident report")
            return redirect("scoring:leaderboard")

    context = {
        "incident": incident,
    }
    return render(request, "scoring/view_incident.html", context)


@login_required
@require_team_role(
    lambda p: p.is_orange_team() or p.is_gold_team(),
    "Only Orange Team or Gold Team members can access this page",
)
def orange_team_portal(request: HttpRequest) -> HttpResponse:
    """Orange team portal - list existing bonuses."""
    user = cast(User, request.user)

    # Gold Team and Admin see all bonuses; Orange Team sees only their own
    base_query = OrangeTeamBonus.objects.all()
    can_see_all = user.is_staff or (hasattr(user, "person") and user.person.is_gold_team())

    if can_see_all:
        bonuses = base_query.select_related("team")
    else:
        bonuses = base_query.filter(submitted_by=user).select_related("team")

    context = {
        "bonuses": bonuses,
        "can_approve": can_see_all,
    }
    return render(request, "scoring/orange_team_portal.html", context)


@login_required
@require_team_role(lambda p: p.is_orange_team(), "Only Orange Team members can submit bonuses")
@transaction.atomic
def submit_orange_bonus(request: HttpRequest) -> HttpResponse:
    """Submit orange team bonus."""
    if not OrangeCheckType.objects.exists():
        messages.warning(request, "No check types defined. Set up check types first.")
        return redirect("scoring:manage_check_types")

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
@require_team_role(lambda p: p.is_orange_team(), "Only Orange Team can manage check types")
def manage_check_types(request: HttpRequest) -> HttpResponse:
    """Manage orange check types."""
    check_types = OrangeCheckType.objects.all().order_by("name")
    form = OrangeCheckTypeForm()

    if request.method == "POST":
        form = OrangeCheckTypeForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, f"Check type '{form.cleaned_data['name']}' created")
            return redirect("scoring:manage_check_types")

    context = {
        "check_types": check_types,
        "form": form,
    }
    return render(request, "scoring/manage_check_types.html", context)


@login_required
@require_team_role(lambda p: p.is_orange_team(), "Only Orange Team can manage check types")
def edit_check_type(request: HttpRequest, check_type_id: int) -> HttpResponse:
    """Edit an orange check type."""
    check_type = get_object_or_404(OrangeCheckType, pk=check_type_id)

    if request.method == "POST":
        form = OrangeCheckTypeForm(request.POST, instance=check_type)
        if form.is_valid():
            form.save()
            messages.success(request, f"Check type '{check_type.name}' updated")
            return redirect("scoring:manage_check_types")
    else:
        form = OrangeCheckTypeForm(instance=check_type)

    context = {
        "form": form,
        "check_type": check_type,
    }
    return render(request, "scoring/edit_check_type.html", context)


@login_required
@require_team_role(lambda p: p.is_orange_team(), "Only Orange Team can manage check types")
@require_http_methods(["POST"])
def delete_check_type(request: HttpRequest, check_type_id: int) -> HttpResponse:
    """Delete an orange check type."""
    check_type = get_object_or_404(OrangeCheckType, pk=check_type_id)
    name = check_type.name
    check_type.delete()
    messages.success(request, f"Check type '{name}' deleted")
    return redirect("scoring:manage_check_types")


@login_required
@require_team_role(
    lambda p: p.is_white_team() or p.is_gold_team(), "Only White/Gold Team members can access inject grading"
)
@transaction.atomic
def inject_grading(request: HttpRequest) -> HttpResponse:
    """Inject grading interface - select inject, grade all teams."""
    from quotient.client import QuotientClient

    client = QuotientClient()
    injects = client.get_injects()

    if not injects:
        context: dict[str, Any] = {"quotient_available": False}
        return render(request, "scoring/inject_grading.html", context)

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
                    InjectGrade.objects.update_or_create(
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
        return redirect(f"{request.path}?inject={selected_inject_id}")

    # Get existing grades for selected inject and merge with teams
    team_data = []
    if selected_inject:
        existing = InjectGrade.objects.filter(inject_id=selected_inject_id).select_related("team", "graded_by")
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
    return render(request, "scoring/inject_grading.html", context)


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


def api_orange_check_types(request: HttpRequest) -> JsonResponse:
    """API endpoint for orange check types with default points."""
    check_types = OrangeCheckType.objects.all().order_by("name")
    data = [{"id": ct.id, "name": ct.name, "default_points": float(ct.default_points)} for ct in check_types]
    return JsonResponse({"check_types": data})


@login_required
@require_team_role(lambda p: p.is_gold_team(), "Only Gold Team members can review inject grades")
def inject_grades_review(request: HttpRequest) -> HttpResponse:
    """Review and approve inject grades (Gold Team)."""
    import statistics
    from collections import defaultdict

    # Get all unapproved grades
    unapproved_grades = (
        InjectGrade.objects.filter(is_approved=False)
        .select_related("team", "graded_by")
        .order_by("inject_id", "team__team_number")
    )

    # Get stats
    total_grades = InjectGrade.objects.count()
    approved_count = InjectGrade.objects.filter(is_approved=True).count()
    unapproved_count = total_grades - approved_count

    # Group grades by inject_id
    inject_groups_dict: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"inject_id": "", "inject_name": "", "max_points": Decimal("0"), "grades": []}
    )

    for grade in unapproved_grades:
        if grade.inject_id not in inject_groups_dict:
            inject_groups_dict[grade.inject_id] = {
                "inject_id": grade.inject_id,
                "inject_name": grade.inject_name,
                "max_points": grade.max_points,
                "grades": [],
            }
        inject_groups_dict[grade.inject_id]["grades"].append(grade)

    # Calculate outliers for each inject group
    for group in inject_groups_dict.values():
        grades = group["grades"]

        # Need at least 3 grades for meaningful std dev
        if len(grades) >= 3:
            points_list = [float(g.points_awarded) for g in grades]
            mean = statistics.mean(points_list)
            try:
                std_dev = statistics.stdev(points_list)

                # Flag outliers (> 1.5 std dev from mean)
                for grade in grades:
                    points = float(grade.points_awarded)
                    z_score = abs(points - mean) / std_dev if std_dev > 0 else 0
                    grade.is_outlier = z_score > 1.5
                    grade.std_devs_from_mean = z_score
            except statistics.StatisticsError:
                # Handle case with zero variance
                for grade in grades:
                    grade.is_outlier = False
                    grade.std_devs_from_mean = 0
        else:
            # Not enough data for outlier detection
            for grade in grades:
                grade.is_outlier = False
                grade.std_devs_from_mean = 0

    # Convert to list for template
    inject_groups = list(inject_groups_dict.values())

    context = {
        "inject_groups": inject_groups,
        "unapproved_count": unapproved_count,
        "approved_count": approved_count,
        "total_grades": total_grades,
    }
    return render(request, "scoring/review_inject_grades.html", context)


@login_required
@require_team_role(lambda p: p.is_gold_team(), "Only Gold Team members can approve inject grades")
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
    grades_to_approve = InjectGrade.objects.filter(id__in=grade_ids, is_approved=False)

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


@login_required
@user_passes_test(lambda u: u.is_staff)
def export_index(request: HttpRequest) -> HttpResponse:
    """Export data index page (admin only)."""
    return render(request, "scoring/export_index.html")


@login_required
@user_passes_test(lambda u: u.is_staff)
def export_red_findings(request: HttpRequest) -> HttpResponse:
    """Export red team findings (admin only)."""
    from .export import export_red_findings_csv, export_red_findings_json

    export_format = request.GET.get("format", "csv").lower()
    if export_format == "json":
        return export_red_findings_json()
    return export_red_findings_csv()


@login_required
@user_passes_test(lambda u: u.is_staff)
def export_incidents(request: HttpRequest) -> HttpResponse:
    """Export incident reports (admin only)."""
    from .export import export_incidents_csv, export_incidents_json

    export_format = request.GET.get("format", "csv").lower()
    if export_format == "json":
        return export_incidents_json()
    return export_incidents_csv()


@login_required
@user_passes_test(lambda u: u.is_staff)
def export_orange_adjustments(request: HttpRequest) -> HttpResponse:
    """Export orange team adjustments (admin only)."""
    from .export import export_orange_adjustments_csv, export_orange_adjustments_json

    export_format = request.GET.get("format", "csv").lower()
    if export_format == "json":
        return export_orange_adjustments_json()
    return export_orange_adjustments_csv()


@login_required
@user_passes_test(lambda u: u.is_staff)
def export_inject_grades(request: HttpRequest) -> HttpResponse:
    """Export inject grades (admin only)."""
    from .export import export_inject_grades_csv, export_inject_grades_json

    export_format = request.GET.get("format", "csv").lower()
    if export_format == "json":
        return export_inject_grades_json()
    return export_inject_grades_csv()


@login_required
@user_passes_test(lambda u: u.is_staff)
def export_final_scores(request: HttpRequest) -> HttpResponse:
    """Export final scores (admin only)."""
    from .export import export_final_scores_csv, export_final_scores_json

    export_format = request.GET.get("format", "csv").lower()
    if export_format == "json":
        return export_final_scores_json()
    return export_final_scores_csv()


@login_required
@require_team_role(lambda p: p.is_gold_team(), "Only Gold Team members can approve adjustments")
@transaction.atomic
@require_http_methods(["POST"])
def approve_orange_adjustment(request: HttpRequest, adjustment_id: int) -> HttpResponse:
    """Approve individual Orange adjustment."""
    adjustment = get_object_or_404(OrangeTeamBonus, id=adjustment_id)

    adjustment.is_approved = True
    adjustment.approved_at = timezone.now()
    adjustment.approved_by = cast(User, request.user)
    adjustment.save()

    messages.success(request, f"Adjustment #{adjustment.id} approved")
    return redirect("scoring:orange_team_portal")


@login_required
@require_team_role(lambda p: p.is_gold_team(), "Only Gold Team members can reject adjustments")
@transaction.atomic
@require_http_methods(["POST"])
def reject_orange_adjustment(request: HttpRequest, adjustment_id: int) -> HttpResponse:
    """Reject individual Orange adjustment."""
    adjustment = get_object_or_404(OrangeTeamBonus, id=adjustment_id)

    adjustment.is_approved = False
    adjustment.approved_at = None
    adjustment.approved_by = None
    adjustment.save()

    messages.success(request, f"Adjustment #{adjustment.id} rejected")
    return redirect("scoring:orange_team_portal")


@login_required
@require_team_role(lambda p: p.is_gold_team(), "Only Gold Team members can bulk approve adjustments")
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
    count = OrangeTeamBonus.objects.filter(id__in=valid_ids).update(
        is_approved=True,
        approved_at=timezone.now(),
        approved_by=cast(User, request.user),
    )

    messages.success(request, f"Approved {count} adjustment(s)")
    return redirect("scoring:orange_team_portal")


@login_required
@require_team_role(lambda p: p.is_gold_team(), "Only Gold Team members can bulk reject adjustments")
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
    count = OrangeTeamBonus.objects.filter(id__in=valid_ids).update(
        is_approved=False,
        approved_at=None,
        approved_by=None,
    )

    messages.success(request, f"Rejected {count} adjustment(s)")
    return redirect("scoring:orange_team_portal")
