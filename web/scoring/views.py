"""Views for scoring system."""

from collections.abc import Callable
from decimal import Decimal
from functools import wraps
from typing import Concatenate, ParamSpec, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from registration.models import Event

from core.auth_utils import has_permission
from team.models import Team

from .calculator import (
    calculate_suggested_recovery_points,
    calculate_team_score,
    get_event_leaderboard,
    get_leaderboard,
    recalculate_all_scores,
    recalculate_event_scores,
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
    AttackType,
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
from .quotient_sync import get_cached_team_count, sync_quotient_metadata, sync_service_scores

P = ParamSpec("P")
type ViewFunc[**P] = Callable[Concatenate[HttpRequest, P], HttpResponse]


def _normalize_red_finding_post(post_data: QueryDict) -> QueryDict:
    """Normalize legacy field names in red team finding POST data.

    Supports backwards compatibility for scripted submissions using old field names:
    - attack_vector → attack_type
    - affected_box → affected_boxes
    - target_teams → affected_teams
    """
    field_mappings = {
        "attack_vector": "attack_type",
        "affected_box": "affected_boxes",
        "target_teams": "affected_teams",
    }

    needs_normalization = any(old in post_data for old in field_mappings)
    if not needs_normalization:
        return post_data

    normalized = QueryDict(mutable=True)
    for key in post_data:
        new_key = field_mappings.get(key, key)
        for value in post_data.getlist(key):
            normalized.appendlist(new_key, value)
    return normalized


def require_role(
    *permission_names: str, error_message: str = "You do not have permission to access this page"
) -> Callable[[ViewFunc[P]], ViewFunc[P]]:
    """Decorator to require specific permissions based on Authentik groups."""

    def decorator(view_func: ViewFunc[P]) -> ViewFunc[P]:
        @wraps(view_func)
        def wrapped_view(request: HttpRequest, *args: P.args, **kwargs: P.kwargs) -> HttpResponse:
            user = cast(User, request.user)
            if user.is_staff:
                return view_func(request, *args, **kwargs)

            if any(has_permission(user, perm) for perm in permission_names):
                return view_func(request, *args, **kwargs)

            messages.error(request, error_message)
            return redirect("scoring:leaderboard")

        return wrapped_view  # type: ignore[return-value]

    return decorator


def _get_user_team(user: User) -> Team | None:
    """Get team for a user based on their Authentik groups."""
    from core.auth_utils import get_user_team_number

    team_number = get_user_team_number(user)
    if not team_number:
        return None
    return Team.objects.filter(team_number=team_number).first()


def require_leaderboard_access[**P](
    view_func: Callable[Concatenate[HttpRequest, P], HttpResponse],
) -> Callable[Concatenate[HttpRequest, P], HttpResponse]:
    """Decorator to restrict leaderboard access to Gold/White Team, Ticketing Admin, and System Admin."""
    from django.http import HttpResponseForbidden

    @wraps(view_func)
    def wrapped_view(request: HttpRequest, *args: P.args, **kwargs: P.kwargs) -> HttpResponse:
        user = cast(User, request.user)

        if user.is_staff:
            return view_func(request, *args, **kwargs)

        if (
            has_permission(user, "gold_team")
            or has_permission(user, "white_team")
            or has_permission(user, "ticketing_admin")
        ):
            return view_func(request, *args, **kwargs)

        return HttpResponseForbidden("You do not have permission to access this page")

    return wrapped_view  # type: ignore[return-value]


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
@require_leaderboard_access
def event_leaderboard(request: HttpRequest, event_id: int) -> HttpResponse:
    """Event-scoped leaderboard view - shows scores for a specific event.

    Scores are only visible after the event is finalized.
    """
    event = get_object_or_404(Event, id=event_id)

    user = cast(User, request.user)
    is_gold_team = user.is_staff or has_permission(user, "gold_team")

    # Only show scores after event is finalized (or to Gold Team)
    if not event.is_finalized and not is_gold_team:
        messages.error(request, "Scores are not yet available for this event.")
        return redirect("scoring:leaderboard")

    scores = get_event_leaderboard(event)

    context = {
        "event": event,
        "scores": scores,
        "is_finalized": event.is_finalized,
    }
    return render(request, "scoring/event_leaderboard.html", context)


@login_required
@require_role("gold_team", error_message="Only Gold Team members can recalculate event scores")
@require_http_methods(["POST"])
def recalculate_event_scores_view(request: HttpRequest, event_id: int) -> HttpResponse:
    """Recalculate all scores for a specific event."""
    event = get_object_or_404(Event, id=event_id)
    recalculate_event_scores(event)
    messages.success(request, f"Scores recalculated for {event.name}")
    return redirect("scoring:event_leaderboard", event_id=event_id)


@login_required
@require_role(
    "gold_team",
    "Only Gold Team members can review findings",
)
def red_team_portal(request: HttpRequest) -> HttpResponse:
    """Gold team review page for red team findings."""
    from django.core.paginator import Paginator

    # Get filter parameters
    status_filter = request.GET.get("status", "pending") or "pending"
    team_filter = request.GET.get("team", "")
    attack_type_filter = request.GET.get("attack_type", "")
    submitter_filter = request.GET.get("submitter", "")
    sort_by = request.GET.get("sort", "-created_at")
    page = request.GET.get("page", "1")

    base_query = RedTeamFinding.objects.prefetch_related("affected_teams", "screenshots").select_related("submitted_by")

    # Apply status filter
    if status_filter == "pending":
        base_query = base_query.filter(is_approved=False)
    elif status_filter == "reviewed":
        base_query = base_query.filter(is_approved=True)

    # Apply other filters
    if team_filter:
        base_query = base_query.filter(affected_teams__id=team_filter)

    if attack_type_filter:
        base_query = base_query.filter(attack_type_id=int(attack_type_filter))

    if submitter_filter:
        base_query = base_query.filter(submitted_by__id=submitter_filter)

    # Apply distinct to avoid duplicates from M2M joins
    base_query = base_query.distinct()

    # Validate and apply sort
    valid_sort_fields = ["created_at", "-created_at", "attack_type__name", "-attack_type__name"]
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
    total_findings = RedTeamFinding.objects.count()
    pending_count = RedTeamFinding.objects.filter(is_approved=False).count()
    reviewed_count = total_findings - pending_count

    # Get available teams, attack types, and submitters for filter dropdowns
    available_teams = Team.objects.filter(red_team_findings__isnull=False).distinct().order_by("team_number")
    available_attack_types = AttackType.objects.filter(findings__isnull=False).distinct().order_by("name")
    available_submitters = User.objects.filter(red_findings_submitted__isnull=False).distinct().order_by("username")

    user = cast(User, request.user)
    is_gold_team = user.is_staff or has_permission(user, "gold_team")

    # For bulk approve button visibility
    pending_findings = pending_count > 0

    context = {
        "findings": page_obj,
        "page_obj": page_obj,
        "pending_findings": pending_findings,
        "total_findings": total_findings,
        "pending_count": pending_count,
        "reviewed_count": reviewed_count,
        "available_teams": available_teams,
        "available_attack_types": available_attack_types,
        "available_submitters": available_submitters,
        "selected_team": team_filter,
        "selected_attack_type": attack_type_filter,
        "selected_submitter": submitter_filter,
        "status_filter": status_filter,
        "sort_by": sort_by,
        "is_gold_team": is_gold_team,
        "current_user": user,
    }

    # Return partial for htmx requests
    if request.headers.get("HX-Request"):
        return render(request, "cotton/red_findings_table.html", context)

    return render(request, "scoring/review_red_findings.html", context)


@login_required
@require_role(
    "red_team",
    error_message="Only Red Team members can view findings",
)
def red_team_findings(request: HttpRequest) -> HttpResponse:
    """Red team view of all findings (read-only, can delete/leave own)."""
    from django.core.paginator import Paginator

    # Get filter parameters
    status_filter = request.GET.get("status", "all") or "all"
    team_filter = request.GET.get("team", "")
    attack_type_filter = request.GET.get("attack_type", "")
    submitter_filter = request.GET.get("submitter", "")
    sort_by = request.GET.get("sort", "-created_at")
    page = request.GET.get("page", "1")

    base_query = RedTeamFinding.objects.prefetch_related("affected_teams", "screenshots").select_related("submitted_by")

    # Apply status filter
    if status_filter == "pending":
        base_query = base_query.filter(is_approved=False)
    elif status_filter == "reviewed":
        base_query = base_query.filter(is_approved=True)
    # "all" shows everything

    # Apply team filter
    if team_filter:
        base_query = base_query.filter(affected_teams__id=team_filter)

    # Apply attack type filter
    if attack_type_filter:
        base_query = base_query.filter(attack_type_id=int(attack_type_filter))

    # Apply submitter filter
    if submitter_filter:
        base_query = base_query.filter(submitted_by_id=int(submitter_filter))

    # Apply sorting
    if sort_by.lstrip("-") in ["created_at", "points_per_team"]:
        base_query = base_query.order_by(sort_by)
    else:
        base_query = base_query.order_by("-created_at")

    # Paginate
    paginator = Paginator(base_query.distinct(), 25)
    try:
        page_num = int(page)
    except ValueError:
        page_num = 1
    page_obj = paginator.get_page(page_num)

    # Get available teams, attack types, and submitters for filter dropdowns
    available_teams = Team.objects.filter(red_team_findings__isnull=False).distinct().order_by("team_number")
    available_attack_types = AttackType.objects.filter(findings__isnull=False).distinct().order_by("name")
    available_submitters = User.objects.filter(red_findings_submitted__isnull=False).distinct().order_by("username")

    context = {
        "findings": page_obj,
        "page_obj": page_obj,
        "status_filter": status_filter,
        "selected_team": team_filter,
        "selected_attack_type": attack_type_filter,
        "selected_submitter": submitter_filter,
        "sort_by": sort_by,
        "available_teams": available_teams,
        "available_attack_types": available_attack_types,
        "available_submitters": available_submitters,
        "is_gold_team": False,  # Red team view - no approval actions
    }

    # Return partial for htmx requests
    if request.headers.get("HX-Request"):
        return render(request, "cotton/red_findings_table.html", context)

    return render(request, "scoring/red_team_portal.html", context)


@login_required
@require_role(
    "gold_team",
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
@require_role("red_team", error_message="Only Red Team members can submit findings")
@transaction.atomic
def submit_red_finding(request: HttpRequest) -> HttpResponse:
    """Submit red team finding with deduplication."""
    from .deduplication import OutcomeData, process_red_team_submission
    from .models import RedTeamIPPool

    user = cast(User, request.user)
    team_count = get_cached_team_count()

    # Get user's IP pools for the form
    user_pools = RedTeamIPPool.objects.filter(created_by=user)

    if request.method == "POST":
        post_data = _normalize_red_finding_post(request.POST)
        form = RedTeamFindingForm(post_data, request.FILES, team_count=team_count, user=user)

        if form.is_valid():
            # Extract form data for deduplication
            attack_type = form.cleaned_data["attack_type"]
            affected_boxes = form.cleaned_data.get("affected_boxes", [])
            affected_teams = form.cleaned_data["affected_teams"]
            source_ip = form.cleaned_data.get("source_ip")
            source_ip_pool = form.cleaned_data.get("source_ip_pool")
            notes = form.cleaned_data.get("notes", "")
            affected_service = form.cleaned_data.get("affected_service", "")
            destination_ip_template = form.cleaned_data.get("destination_ip_template", "")
            universally_attempted = form.cleaned_data.get("universally_attempted", False)
            persistence_established = form.cleaned_data.get("persistence_established", False)

            # Extract outcome checkboxes
            outcomes = OutcomeData(
                root_access=form.cleaned_data.get("root_access", False),
                user_access=form.cleaned_data.get("user_access", False),
                privilege_escalation=form.cleaned_data.get("privilege_escalation", False),
                credentials_recovered=form.cleaned_data.get("credentials_recovered", False),
                sensitive_files_recovered=form.cleaned_data.get("sensitive_files_recovered", False),
                credit_cards_recovered=form.cleaned_data.get("credit_cards_recovered", False),
                pii_recovered=form.cleaned_data.get("pii_recovered", False),
                encrypted_db_recovered=form.cleaned_data.get("encrypted_db_recovered", False),
                db_decrypted=form.cleaned_data.get("db_decrypted", False),
            )

            # Process with deduplication
            result = process_red_team_submission(
                attack_type=attack_type,
                boxes=affected_boxes,
                teams=affected_teams,
                source_ip=source_ip,
                source_ip_pool=source_ip_pool,
                submitter=user,
                notes=notes,
                affected_service=affected_service,
                destination_ip_template=destination_ip_template,
                universally_attempted=universally_attempted,
                persistence_established=persistence_established,
                outcomes=outcomes,
            )

            finding = result.finding

            # Handle screenshot uploads for new findings only
            if result.status == "created":
                screenshots = request.FILES.getlist("screenshots")
                max_screenshots = 20

                if len(screenshots) > max_screenshots:
                    messages.error(request, f"Maximum {max_screenshots} screenshots allowed per submission")
                    finding.delete()
                    return redirect("scoring:submit_red_finding")

                try:
                    for screenshot in screenshots:
                        file_data = screenshot.read()
                        RedTeamScreenshot.objects.create(
                            finding=finding,
                            file_data=file_data,
                            filename=screenshot.name or "screenshot.png",
                            mime_type=screenshot.content_type or "image/png",
                        )
                except Exception as e:
                    messages.error(request, f"File upload failed: {str(e)}")
                    finding.delete()
                    return redirect("scoring:submit_red_finding")

            # Show appropriate message based on result
            if result.status == "created":
                messages.success(request, f"Finding #{finding.id} created successfully.")
            elif result.status in ("merged", "partial_merge"):
                messages.info(request, result.message)

            return redirect("scoring:red_team_findings")
    else:
        form = RedTeamFindingForm(team_count=team_count, user=user)

    # Get box metadata from cache for auto-populating IP and services
    box_metadata = {}
    metadata = QuotientMetadataCache.objects.first()
    if metadata:
        for box in metadata.boxes:
            box_metadata[box["name"]] = {
                "ip": box["ip"],
                "services": [svc["name"] for svc in box.get("services", [])],
            }

    context = {
        "form": form,
        "box_metadata": box_metadata,
        "user_pools": user_pools,
    }
    return render(request, "scoring/submit_red_finding.html", context)


@login_required
@require_role("red_team", "gold_team", error_message="Only Red Team or Gold Team can view findings")
def view_red_finding(request: HttpRequest, finding_id: int) -> HttpResponse:
    """View red team finding details with screenshot previews."""
    finding = get_object_or_404(
        RedTeamFinding.objects.select_related(
            "attack_type", "submitted_by", "approved_by", "source_ip_pool"
        ).prefetch_related("affected_teams", "contributors", "screenshots"),
        id=finding_id,
    )
    user = cast(User, request.user)
    is_gold_team = has_permission(user, "gold_team")
    can_delete = finding.submitted_by == user and not finding.is_approved

    context = {
        "finding": finding,
        "is_gold_team": is_gold_team,
        "can_delete": can_delete,
    }
    return render(request, "scoring/view_red_finding.html", context)


@login_required
@require_role("red_team", error_message="Only Red Team members can delete findings")
@transaction.atomic
@require_http_methods(["POST"])
def delete_red_finding(request: HttpRequest, finding_id: int) -> HttpResponse:
    """Delete a red team finding (owner only, before approval)."""
    finding = get_object_or_404(RedTeamFinding, id=finding_id)
    user = cast(User, request.user)

    # Only the submitter can delete their own finding
    if finding.submitted_by != user:
        messages.error(request, "You can only delete your own findings")
        return redirect("scoring:red_team_findings")

    # Cannot delete if already approved
    if finding.is_approved:
        messages.error(request, "Cannot delete a finding that has already been approved")
        return redirect("scoring:red_team_findings")

    finding_num = finding.id
    finding.delete()
    messages.success(request, f"Red team finding #{finding_num} deleted")
    return redirect("scoring:red_team_findings")


@login_required
@require_role("red_team", error_message="Only Red Team members can leave findings")
@transaction.atomic
@require_http_methods(["POST"])
def leave_red_finding(request: HttpRequest, finding_id: int) -> HttpResponse:
    """Remove yourself as a contributor from a merged finding."""
    finding = get_object_or_404(RedTeamFinding, id=finding_id)
    user = cast(User, request.user)

    # Cannot leave if already approved
    if finding.is_approved:
        messages.error(request, "Cannot leave a finding that has already been approved")
        return redirect("scoring:red_team_findings")

    # Check if user is a contributor (but not the original submitter)
    if finding.submitted_by == user:
        messages.error(request, "You are the original submitter. Use delete instead.")
        return redirect("scoring:red_team_findings")

    if user not in finding.contributors.all():
        messages.error(request, "You are not a contributor to this finding")
        return redirect("scoring:red_team_findings")

    # Remove user from contributors
    finding.contributors.remove(user)

    # Append note about removal
    if finding.notes:
        finding.notes += f"\n\n[System]: {user.username} removed themselves from this finding."
    else:
        finding.notes = f"[System]: {user.username} removed themselves from this finding."
    finding.save()

    messages.success(request, f"You have been removed from finding #{finding.id}")
    return redirect("scoring:red_team_findings")


# IP Pool Management Views
@login_required
@require_role("red_team", error_message="Only Red Team members can manage IP pools")
def ip_pool_list(request: HttpRequest) -> HttpResponse:
    """List user's IP pools."""
    from .models import RedTeamIPPool

    user = cast(User, request.user)
    pools = RedTeamIPPool.objects.filter(created_by=user)

    context = {
        "pools": pools,
    }
    return render(request, "scoring/ip_pool_list.html", context)


@login_required
@require_role("red_team", error_message="Only Red Team members can manage IP pools")
@transaction.atomic
def ip_pool_create(request: HttpRequest) -> HttpResponse:
    """Create a new IP pool."""
    from .forms import RedTeamIPPoolForm

    user = cast(User, request.user)

    if request.method == "POST":
        form = RedTeamIPPoolForm(request.POST, user=user)
        if form.is_valid():
            pool = form.save(commit=False)
            pool.created_by = user
            pool.save()
            messages.success(request, f"IP pool '{pool.name}' created with {pool.ip_count} IPs")
            # If this was an AJAX request (from modal), return JSON
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse(
                    {
                        "success": True,
                        "pool": {
                            "id": pool.id,
                            "name": pool.name,
                            "ip_count": pool.ip_count,
                        },
                    }
                )
            return redirect("scoring:ip_pool_list")
        else:
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return JsonResponse({"success": False, "errors": form.errors}, status=400)
    else:
        form = RedTeamIPPoolForm(user=user)

    context = {
        "form": form,
        "action": "Create",
    }
    return render(request, "scoring/ip_pool_form.html", context)


@login_required
@require_role("red_team", error_message="Only Red Team members can manage IP pools")
@transaction.atomic
def ip_pool_edit(request: HttpRequest, pool_id: int) -> HttpResponse:
    """Edit an IP pool."""
    from .forms import RedTeamIPPoolForm
    from .models import RedTeamIPPool

    user = cast(User, request.user)
    pool = get_object_or_404(RedTeamIPPool, id=pool_id, created_by=user)

    if request.method == "POST":
        form = RedTeamIPPoolForm(request.POST, instance=pool, user=user)
        if form.is_valid():
            pool = form.save()
            messages.success(request, f"IP pool '{pool.name}' updated")
            return redirect("scoring:ip_pool_list")
    else:
        form = RedTeamIPPoolForm(instance=pool, user=user)

    context = {
        "form": form,
        "pool": pool,
        "action": "Edit",
    }
    return render(request, "scoring/ip_pool_form.html", context)


@login_required
@require_role("red_team", error_message="Only Red Team members can manage IP pools")
@transaction.atomic
@require_http_methods(["POST"])
def ip_pool_delete(request: HttpRequest, pool_id: int) -> HttpResponse:
    """Delete an IP pool."""
    from .models import RedTeamIPPool

    user = cast(User, request.user)
    pool = get_object_or_404(RedTeamIPPool, id=pool_id, created_by=user)

    # Check if pool is in use by any findings
    if pool.findings.exists():
        messages.error(request, f"Cannot delete pool '{pool.name}' - it is used by {pool.findings.count()} finding(s)")
        return redirect("scoring:ip_pool_list")

    pool_name = pool.name
    pool.delete()
    messages.success(request, f"IP pool '{pool_name}' deleted")
    return redirect("scoring:ip_pool_list")


@login_required
@require_role("red_team", error_message="Only Red Team members can view IP pools")
def api_user_ip_pools(request: HttpRequest) -> JsonResponse:
    """API endpoint to get user's IP pools for dropdown."""
    from .models import RedTeamIPPool

    user = cast(User, request.user)
    pools = RedTeamIPPool.objects.filter(created_by=user)

    return JsonResponse(
        {
            "pools": [
                {
                    "id": pool.id,
                    "name": pool.name,
                    "ip_count": pool.ip_count,
                }
                for pool in pools
            ]
        }
    )


@login_required
@transaction.atomic
def submit_incident_report(request: HttpRequest) -> HttpResponse:
    """Submit incident report (blue team or admin)."""

    user = cast(User, request.user)
    is_admin = user.is_staff
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
        "current_user": user,
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

    # Check if user can delete this incident
    can_delete = incident.submitted_by == user and not incident.gold_team_reviewed

    context = {
        "incident": incident,
        "can_delete": can_delete,
    }
    return render(request, "scoring/view_incident.html", context)


@login_required
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


@login_required
@require_role("orange_team", "gold_team", error_message="Only Orange Team or Gold Team members can access this page")
def orange_team_portal(request: HttpRequest) -> HttpResponse:
    """Orange team portal - list user's own submitted bonuses."""
    user = cast(User, request.user)
    bonuses = OrangeTeamBonus.objects.filter(submitted_by=user).select_related("team")
    return render(request, "scoring/orange_team_portal.html", {"bonuses": bonuses})


@login_required
@require_role("gold_team", error_message="Only Gold Team members can review orange team")
def review_orange(request: HttpRequest) -> HttpResponse:
    """Gold team review page for orange team."""
    bonuses = OrangeTeamBonus.objects.select_related("team", "submitted_by", "approved_by")
    return render(request, "scoring/review_orange.html", {"bonuses": bonuses})


@login_required
@require_role("orange_team", error_message="Only Orange Team members can submit bonuses")
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
@require_role("orange_team", error_message="Only Orange Team can manage check types")
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
@require_role("orange_team", error_message="Only Orange Team can manage check types")
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
@require_role("orange_team", error_message="Only Orange Team can manage check types")
@require_http_methods(["POST"])
def delete_check_type(request: HttpRequest, check_type_id: int) -> HttpResponse:
    """Delete an orange check type."""
    check_type = get_object_or_404(OrangeCheckType, pk=check_type_id)
    name = check_type.name
    check_type.delete()
    messages.success(request, f"Check type '{name}' deleted")
    return redirect("scoring:manage_check_types")


@login_required
@require_role("white_team", "gold_team", error_message="Only White/Gold Team members can access inject grading")
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
        return redirect(f"{reverse('scoring:inject_grading')}?inject={selected_inject_id}")

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

    # Return partial for htmx requests
    if request.headers.get("HX-Request"):
        return render(request, "cotton/inject_grading_content.html", context)

    return render(request, "scoring/inject_grading.html", context)


@login_required
@require_role(
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


@login_required
@require_role(
    "gold_team", "white_team", error_message="Only Gold Team or White Team members can match incident reports"
)
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


@login_required
@require_leaderboard_access
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


@login_required
@require_leaderboard_access
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
@require_role("red_team", "gold_team", error_message="Only Red Team or Gold Team can access attack suggestions")
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


@login_required
def api_orange_check_types(request: HttpRequest) -> JsonResponse:
    """API endpoint for orange check types with default points."""
    check_types = OrangeCheckType.objects.all().order_by("name")
    data = [{"id": ct.id, "name": ct.name, "default_points": float(ct.default_points)} for ct in check_types]
    return JsonResponse({"check_types": data})


@login_required
@require_role("gold_team", error_message="Only Gold Team members can review inject grades")
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
    page = request.GET.get("page", "1")

    base_query = InjectGrade.objects.select_related("team", "graded_by")

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
    inject_grades_map: dict[str, list[InjectGrade]] = defaultdict(list)
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
    if sort_by not in valid_sort_fields:
        sort_by = "inject_name"

    # Sort in Python since we already have the list
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
    total_grades = InjectGrade.objects.count()
    approved_count = InjectGrade.objects.filter(is_approved=True).count()
    unapproved_count = total_grades - approved_count

    # Get available injects and teams for filter dropdowns
    available_injects = InjectGrade.objects.values("inject_id", "inject_name").distinct().order_by("inject_name")
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


@login_required
@require_role("gold_team", error_message="Only Gold Team members can approve inject grades")
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
@user_passes_test(lambda u: u.is_staff)
def export_all(request: HttpRequest) -> HttpResponse:
    """Export all scoring data as a zip file (admin only)."""
    from .export import export_all_zip

    return export_all_zip()


@login_required
@require_role("gold_team", error_message="Only Gold Team members can approve adjustments")
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
@require_role("gold_team", error_message="Only Gold Team members can reject adjustments")
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
@require_role("gold_team", error_message="Only Gold Team members can bulk approve adjustments")
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
@require_role("gold_team", error_message="Only Gold Team members can bulk reject adjustments")
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


@login_required
@require_role("gold_team", error_message="Only Gold Team members can send scorecards")
@require_http_methods(["POST"])
def send_scorecards_batch_view(request: HttpRequest, event_id: int) -> HttpResponse:
    """Send scorecards to all teams for an event."""
    from .services import send_scorecards_batch

    event = get_object_or_404(Event, id=event_id)

    if not event.is_finalized:
        messages.warning(request, "Event must be finalized before sending scorecards.")
        return redirect("scoring:event_leaderboard", event_id=event_id)

    results = send_scorecards_batch(event)

    success_count = sum(1 for r in results if r.success)
    fail_count = sum(1 for r in results if not r.success)

    if success_count > 0:
        messages.success(request, f"Sent {success_count} scorecards successfully.")
    if fail_count > 0:
        messages.warning(request, f"Failed to send {fail_count} scorecards.")

    return redirect("scoring:event_leaderboard", event_id=event_id)


@login_required
@require_role("gold_team", error_message="Only Gold Team members can send scorecards")
@require_http_methods(["POST"])
def send_scorecard_single_view(request: HttpRequest, event_score_id: int) -> HttpResponse:
    """Send scorecard to a single team."""
    from .models import EventScore
    from .services import send_scorecard_single

    event_score = get_object_or_404(EventScore, id=event_score_id)

    if not event_score.event.is_finalized:
        messages.warning(request, "Event must be finalized before sending scorecards.")
        return redirect("scoring:event_leaderboard", event_id=event_score.event_id)

    result = send_scorecard_single(event_score)

    if result.success:
        messages.success(request, f"Scorecard sent to {result.school_name} (Team {result.team_number}).")
    else:
        messages.error(request, f"Failed to send scorecard: {result.error}")

    return redirect("scoring:event_leaderboard", event_id=event_score.event_id)


@login_required
def incident_screenshot_download(request: HttpRequest, screenshot_id: int) -> HttpResponse:
    """Serve incident screenshot from database."""
    from django.http import Http404

    screenshot = get_object_or_404(IncidentScreenshot, id=screenshot_id)

    # Check permission: must be staff or team member
    user = cast(User, request.user)
    if not user.is_staff:
        user_team = _get_user_team(user)
        if not user_team or screenshot.incident.team != user_team:
            return HttpResponseForbidden("You do not have permission to view this file")

    if not screenshot.file_data:
        raise Http404("File data not available (file was lost)")

    response = HttpResponse(screenshot.file_data, content_type=screenshot.mime_type)
    response["Content-Disposition"] = f'inline; filename="{screenshot.filename}"'
    return response


@login_required
@require_role("red_team", "gold_team", error_message="Only Red Team or Gold Team can view this")
def red_screenshot_download(request: HttpRequest, screenshot_id: int) -> HttpResponse:
    """Serve red team screenshot from database."""
    from django.http import Http404

    screenshot = get_object_or_404(RedTeamScreenshot, id=screenshot_id)

    if not screenshot.file_data:
        raise Http404("File data not available (file was lost)")

    response = HttpResponse(screenshot.file_data, content_type=screenshot.mime_type)
    response["Content-Disposition"] = f'inline; filename="{screenshot.filename}"'
    return response
