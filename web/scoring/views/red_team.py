"""Red team submission, management, IP pools, and screenshot views."""

from typing import cast

from django.contrib import messages
from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpRequest, HttpResponse, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.auth_utils import has_permission, require_permission
from team.models import Team

from ..forms import RedTeamScoreForm
from ..models import (
    AttackType,
    QuotientMetadataCache,
    RedTeamScore,
    RedTeamScreenshot,
)
from ..quotient_sync import get_cached_team_count


def _normalize_red_score_post(post_data: QueryDict) -> QueryDict:
    """Normalize legacy field names in red team finding POST data.

    Supports backwards compatibility for scripted submissions using old field names:
    - attack_vector -> attack_type
    - affected_box -> affected_boxes
    - target_teams -> affected_teams
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


@require_permission(
    "gold_team",
    error_message="Only Gold Team members can review findings",
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
    if sort_by == "default":
        sort_by = ""
    page = request.GET.get("page", "1")

    base_query = RedTeamScore.objects.prefetch_related("affected_teams", "screenshots").select_related("submitted_by")

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
    if sort_by and sort_by not in valid_sort_fields:
        sort_by = "-created_at"
    if sort_by:
        base_query = base_query.order_by(sort_by)

    # Pagination
    paginator = Paginator(base_query, 50)
    try:
        page_num = int(page)
    except ValueError:
        page_num = 1
    page_obj = paginator.get_page(page_num)

    # Stats (unfiltered counts)
    total_findings = RedTeamScore.objects.count()
    pending_count = RedTeamScore.objects.filter(is_approved=False).count()
    reviewed_count = total_findings - pending_count

    # Get available teams, attack types, and submitters for filter dropdowns
    available_teams = Team.objects.filter(red_team_scores__isnull=False).distinct().order_by("team_number")
    available_attack_types = AttackType.objects.filter(findings__isnull=False).distinct().order_by("name")
    available_submitters = User.objects.filter(red_scores_submitted__isnull=False).distinct().order_by("username")

    user = cast(User, request.user)
    is_gold_team = has_permission(user, "gold_team")

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


@require_permission(
    "red_team",
    error_message="Only Red Team members can view findings",
)
def red_team_scores(request: HttpRequest) -> HttpResponse:
    """Red team view of all findings (read-only, can delete/leave own)."""
    from django.core.paginator import Paginator

    # Get filter parameters
    status_filter = request.GET.get("status", "all") or "all"
    team_filter = request.GET.get("team", "")
    attack_type_filter = request.GET.get("attack_type", "")
    submitter_filter = request.GET.get("submitter", "")
    sort_by = request.GET.get("sort", "-created_at")
    if sort_by == "default":
        sort_by = ""
    page = request.GET.get("page", "1")

    base_query = RedTeamScore.objects.prefetch_related("affected_teams", "screenshots").select_related("submitted_by")

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
    if sort_by and sort_by.lstrip("-") in ["created_at", "points_per_team"]:
        base_query = base_query.order_by(sort_by)
    elif sort_by:
        base_query = base_query.order_by("-created_at")
        sort_by = "-created_at"

    # Paginate
    paginator = Paginator(base_query.distinct(), 25)
    try:
        page_num = int(page)
    except ValueError:
        page_num = 1
    page_obj = paginator.get_page(page_num)

    # Get available teams, attack types, and submitters for filter dropdowns
    available_teams = Team.objects.filter(red_team_scores__isnull=False).distinct().order_by("team_number")
    available_attack_types = AttackType.objects.filter(findings__isnull=False).distinct().order_by("name")
    available_submitters = User.objects.filter(red_scores_submitted__isnull=False).distinct().order_by("username")

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


@require_permission(
    "gold_team",
    "Only Gold Team members can bulk approve findings",
)
@transaction.atomic
@require_http_methods(["POST"])
def bulk_approve_red_scores(request: HttpRequest) -> HttpResponse:
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
        except ValueError, TypeError:
            continue

    if not valid_ids:
        messages.warning(request, "No valid finding IDs provided")
        return redirect("scoring:red_team_portal")

    # Approve findings that are not already approved
    findings_to_approve = RedTeamScore.objects.filter(id__in=valid_ids, is_approved=False)

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


@require_permission("red_team", error_message="Only Red Team members can submit findings")
@transaction.atomic
def submit_red_score(request: HttpRequest) -> HttpResponse:
    """Submit red team finding with deduplication."""
    from ..deduplication import OutcomeData, process_red_team_submission
    from ..models import RedTeamIPPool

    user = cast(User, request.user)
    team_count = get_cached_team_count()

    # Get user's IP pools for the form
    user_pools = RedTeamIPPool.objects.filter(created_by=user)

    if request.method == "POST":
        post_data = _normalize_red_score_post(request.POST)
        form = RedTeamScoreForm(post_data, request.FILES, team_count=team_count, user=user)

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
                    return redirect("scoring:submit_red_score")

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
                    return redirect("scoring:submit_red_score")

            # Show appropriate message based on result
            if result.status == "created":
                messages.success(request, f"Finding #{finding.id} created successfully.")
            elif result.status in ("merged", "partial_merge"):
                messages.info(request, result.message)

            return redirect("scoring:red_team_scores")
    else:
        form = RedTeamScoreForm(team_count=team_count, user=user)

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


@require_permission("red_team", "gold_team", error_message="Only Red Team or Gold Team can view findings")
def view_red_score(request: HttpRequest, finding_id: int) -> HttpResponse:
    """View red team finding details with screenshot previews."""
    finding = get_object_or_404(
        RedTeamScore.objects.select_related(
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


@require_permission("red_team", error_message="Only Red Team members can delete findings")
@transaction.atomic
@require_http_methods(["POST"])
def delete_red_score(request: HttpRequest, finding_id: int) -> HttpResponse:
    """Delete a red team finding (owner only, before approval)."""
    finding = get_object_or_404(RedTeamScore, id=finding_id)
    user = cast(User, request.user)

    # Only the submitter can delete their own finding
    if finding.submitted_by != user:
        messages.error(request, "You can only delete your own findings")
        return redirect("scoring:red_team_scores")

    # Cannot delete if already approved
    if finding.is_approved:
        messages.error(request, "Cannot delete a finding that has already been approved")
        return redirect("scoring:red_team_scores")

    finding_num = finding.id
    finding.delete()
    messages.success(request, f"Red team finding #{finding_num} deleted")
    return redirect("scoring:red_team_scores")


@require_permission("red_team", error_message="Only Red Team members can leave findings")
@transaction.atomic
@require_http_methods(["POST"])
def leave_red_score(request: HttpRequest, finding_id: int) -> HttpResponse:
    """Remove yourself as a contributor from a merged finding."""
    finding = get_object_or_404(RedTeamScore, id=finding_id)
    user = cast(User, request.user)

    # Cannot leave if already approved
    if finding.is_approved:
        messages.error(request, "Cannot leave a finding that has already been approved")
        return redirect("scoring:red_team_scores")

    # Check if user is a contributor (but not the original submitter)
    if finding.submitted_by == user:
        messages.error(request, "You are the original submitter. Use delete instead.")
        return redirect("scoring:red_team_scores")

    if user not in finding.contributors.all():
        messages.error(request, "You are not a contributor to this finding")
        return redirect("scoring:red_team_scores")

    # Remove user from contributors
    finding.contributors.remove(user)

    # Append note about removal
    if finding.notes:
        finding.notes += f"\n\n[System]: {user.username} removed themselves from this finding."
    else:
        finding.notes = f"[System]: {user.username} removed themselves from this finding."
    finding.save()

    messages.success(request, f"You have been removed from finding #{finding.id}")
    return redirect("scoring:red_team_scores")


@require_permission("red_team", "gold_team", error_message="Only Red Team or Gold Team can view this")
def red_screenshot_download(request: HttpRequest, screenshot_id: int) -> HttpResponse:
    """Serve red team screenshot from database."""
    from django.http import Http404

    screenshot = get_object_or_404(RedTeamScreenshot, id=screenshot_id)

    if not screenshot.file_data:
        raise Http404("File data not available (file was lost)")

    response = HttpResponse(screenshot.file_data, content_type=screenshot.mime_type)
    response["Content-Disposition"] = f'inline; filename="{screenshot.filename}"'
    return response


# IP Pool Management Views
@require_permission("red_team", error_message="Only Red Team members can manage IP pools")
def ip_pool_list(request: HttpRequest) -> HttpResponse:
    """List user's IP pools."""
    from ..models import RedTeamIPPool

    user = cast(User, request.user)
    pools = RedTeamIPPool.objects.filter(created_by=user)

    context = {
        "pools": pools,
    }
    return render(request, "scoring/ip_pool_list.html", context)


@require_permission("red_team", error_message="Only Red Team members can manage IP pools")
@transaction.atomic
def ip_pool_create(request: HttpRequest) -> HttpResponse:
    """Create a new IP pool."""
    from ..forms import RedTeamIPPoolForm

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


@require_permission("red_team", error_message="Only Red Team members can manage IP pools")
@transaction.atomic
def ip_pool_edit(request: HttpRequest, pool_id: int) -> HttpResponse:
    """Edit an IP pool."""
    from ..forms import RedTeamIPPoolForm
    from ..models import RedTeamIPPool

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


@require_permission("red_team", error_message="Only Red Team members can manage IP pools")
@transaction.atomic
@require_http_methods(["POST"])
def ip_pool_delete(request: HttpRequest, pool_id: int) -> HttpResponse:
    """Delete an IP pool."""
    from ..models import RedTeamIPPool

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


@require_permission("red_team", error_message="Only Red Team members can view IP pools")
def api_user_ip_pools(request: HttpRequest) -> JsonResponse:
    """API endpoint to get user's IP pools for dropdown."""
    from ..models import RedTeamIPPool

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
