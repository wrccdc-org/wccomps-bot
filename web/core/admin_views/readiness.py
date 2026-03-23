"""Pre-competition readiness check functions.

Provides streaming checks and fix handlers used by the competition page
to verify system state before starting a competition.
"""

import csv
import io
import json
import logging
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import cast

from django.http import HttpRequest, JsonResponse, StreamingHttpResponse
from django.urls import reverse
from django.utils import timezone

from core.authentik_manager import AuthentikManager
from core.authentik_utils import generate_blueteam_password
from core.forms import ReadinessFixForm
from core.models import CompetitionConfig
from team.models import Team

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Progress helper
# ---------------------------------------------------------------------------


def _progress(
    step: str,
    current: int,
    total: int,
    severity: str = "pass",
    detail: str = "",
    action: dict[str, str] | None = None,
) -> str:
    """Emit a readiness check progress line as NDJSON."""
    return (
        json.dumps(
            {
                "step": step,
                "current": current,
                "total": total,
                "ok": severity != "fail",
                "severity": severity,
                "detail": detail,
                "action": action,
            }
        )
        + "\n"
    )


# ---------------------------------------------------------------------------
# Check result type: (severity, detail, action_or_none)
# ---------------------------------------------------------------------------

type CheckResult = tuple[str, str, dict[str, str] | None]


# ---------------------------------------------------------------------------
# Phase 1 — Authentik checks
# ---------------------------------------------------------------------------


def _check_team_accounts_exist() -> CheckResult:
    """Verify all active team accounts exist in Authentik."""
    active_teams = Team.objects.filter(is_active=True)
    if not active_teams.exists():
        return ("warn", "No active teams", None)

    mgr = AuthentikManager()
    missing: list[str] = []
    for team in active_teams:
        username = f"team{team.team_number:02d}"
        user = mgr.get_user_with_groups(username)
        if not user:
            missing.append(username)

    if missing:
        names = ", ".join(missing[:5])
        suffix = f"... (+{len(missing) - 5})" if len(missing) > 5 else ""
        return (
            "fail",
            f"{len(missing)} missing: {names}{suffix}",
            {"type": "fix", "key": "fix_missing_accounts", "label": "Create Missing Accounts"},
        )
    return ("pass", f"All {active_teams.count()} team accounts exist", None)


def _check_team_group_membership() -> CheckResult:
    """Verify each teamNN is in the WCComps_BlueTeamNN group."""
    active_teams = Team.objects.filter(is_active=True)
    if not active_teams.exists():
        return ("warn", "No active teams", None)

    mgr = AuthentikManager()
    misconfigured: list[str] = []
    for team in active_teams:
        username = f"team{team.team_number:02d}"
        expected_group = team.authentik_group  # e.g. WCComps_BlueTeam01
        user = mgr.get_user_with_groups(username)
        if not user:
            continue  # handled by account existence check

        groups_obj = user.get("groups_obj", [])
        group_names = [g.get("name", "") for g in groups_obj] if isinstance(groups_obj, list) else []
        if expected_group not in group_names:
            misconfigured.append(username)

    if misconfigured:
        names = ", ".join(misconfigured[:5])
        suffix = f"... (+{len(misconfigured) - 5})" if len(misconfigured) > 5 else ""
        return (
            "fail",
            f"{len(misconfigured)} in wrong group: {names}{suffix}",
            {"type": "fix", "key": "fix_group_membership", "label": "Fix Group Membership"},
        )
    return ("pass", "All accounts in correct groups", None)


def _check_blueteam_bindings() -> CheckResult:
    """Verify BlueTeam group bindings exist on all controlled apps."""
    config = CompetitionConfig.get_config()
    apps = config.controlled_applications
    if not apps:
        return ("warn", "No controlled apps configured", {"type": "link", "url": "#setup", "label": "Configure Apps"})

    mgr = AuthentikManager()
    missing: list[str] = []
    for slug in apps:
        app = mgr.get_application_by_slug(slug)
        if not app:
            missing.append(f"{slug} (not found)")
            continue
        binding, _ = mgr.get_blueteam_binding(app["pk"])
        if not binding:
            missing.append(slug)

    if missing:
        return (
            "fail",
            f"Missing bindings: {', '.join(missing)}",
            {"type": "link", "url": "#setup", "label": "Configure Apps"},
        )
    return ("pass", f"Bindings exist for all {len(apps)} apps", None)


# ---------------------------------------------------------------------------
# Phase 2 — Operational readiness checks
# ---------------------------------------------------------------------------


def _check_no_tickets() -> CheckResult:
    """Check that no tickets exist yet (clean slate for competition)."""
    from ticketing.models import Ticket

    count = Ticket.objects.count()
    if count > 0:
        return (
            "warn",
            f"{count} ticket{'s' if count != 1 else ''} already exist",
            {"type": "link", "url": reverse("ticket_list"), "label": "View Tickets"},
        )
    return ("pass", "No existing tickets", None)


def _check_packets_distributed() -> CheckResult:
    """Check that all completed packets were distributed to all active teams."""
    from packets.models import Packet, PacketDistribution

    active_teams = Team.objects.filter(is_active=True)
    if not active_teams.exists():
        return ("warn", "No active teams", None)

    completed_packets = Packet.objects.filter(status="completed")
    if not completed_packets.exists():
        return ("pass", "No completed packets to check", None)

    issues: list[str] = []
    for packet in completed_packets:
        distributed_team_ids = set(
            PacketDistribution.objects.filter(
                packet=packet,
                email_status__in=["sent", "delivered"],
            ).values_list("team_id", flat=True)
        )
        missing = active_teams.exclude(id__in=distributed_team_ids).count()
        if missing > 0:
            issues.append(f"{packet.title}: {missing} teams missing")

    if issues:
        return (
            "warn",
            "; ".join(issues),
            {"type": "link", "url": reverse("packets_list"), "label": "View Packets"},
        )
    return ("pass", "All packets distributed to all teams", None)


def _check_quotient_synced() -> CheckResult:
    """Check that Quotient metadata was synced recently."""
    from scoring.models import QuotientMetadataCache

    cache = QuotientMetadataCache.objects.first()
    if not cache:
        return (
            "warn",
            "Quotient metadata not synced yet",
            {"type": "fix", "key": "fix_sync_quotient", "label": "Sync Now"},
        )

    age = timezone.now() - cache.last_synced
    if age > timedelta(days=7):
        days = age.days
        return (
            "warn",
            f"Last synced {days} days ago",
            {"type": "fix", "key": "fix_sync_quotient", "label": "Sync Now"},
        )
    return ("pass", f"Synced {cache.last_synced.strftime('%b %d %H:%M')}", None)


def _check_unapproved_red_scores() -> CheckResult:
    """Check for unapproved red team findings."""
    from scoring.models import RedTeamScore

    count = RedTeamScore.objects.filter(is_approved=False).count()
    if count > 0:
        return (
            "warn",
            f"{count} unapproved finding{'s' if count != 1 else ''}",
            {"type": "link", "url": reverse("red_team_portal"), "label": "Review"},
        )
    return ("pass", "All findings approved", None)


def _check_unreviewed_incidents() -> CheckResult:
    """Check for unreviewed incident reports."""
    from scoring.models import IncidentReport

    count = IncidentReport.objects.filter(is_approved=False).count()
    if count > 0:
        return (
            "warn",
            f"{count} unreviewed report{'s' if count != 1 else ''}",
            {"type": "link", "url": reverse("review_incidents"), "label": "Review"},
        )
    return ("pass", "All incidents reviewed", None)


def _check_unapproved_inject_grades() -> CheckResult:
    """Check for unapproved inject grades."""
    from scoring.models import InjectScore

    count = InjectScore.objects.filter(is_approved=False).count()
    if count > 0:
        return (
            "warn",
            f"{count} unapproved grade{'s' if count != 1 else ''}",
            {"type": "link", "url": reverse("inject_grades_review"), "label": "Review"},
        )
    return ("pass", "All inject grades approved", None)


def _check_outstanding_orange() -> CheckResult:
    """Check for outstanding orange team assignments."""
    from orange_team.models import OrangeAssignment

    count = OrangeAssignment.objects.filter(
        status__in=["pending", "in_progress", "submitted"],
    ).count()
    if count > 0:
        return (
            "warn",
            f"{count} outstanding assignment{'s' if count != 1 else ''}",
            {"type": "link", "url": reverse("review_queue"), "label": "Review"},
        )
    return ("pass", "All assignments resolved", None)


# ---------------------------------------------------------------------------
# Check registry
# ---------------------------------------------------------------------------

ALL_CHECKS: list[tuple[str, Callable[[], CheckResult]]] = [
    # Phase 1: Authentik
    ("Team accounts exist", _check_team_accounts_exist),
    ("Group membership correct", _check_team_group_membership),
    ("App bindings configured", _check_blueteam_bindings),
    # Phase 2: Operational
    ("No existing tickets", _check_no_tickets),
    ("Packets distributed", _check_packets_distributed),
    ("Quotient metadata synced", _check_quotient_synced),
    ("Red team findings approved", _check_unapproved_red_scores),
    ("Incident reports reviewed", _check_unreviewed_incidents),
    ("Inject grades approved", _check_unapproved_inject_grades),
    ("Orange assignments resolved", _check_outstanding_orange),
]


# ---------------------------------------------------------------------------
# Streaming generator
# ---------------------------------------------------------------------------


def stream_readiness_checks() -> Iterator[str]:
    """Run all readiness checks and yield NDJSON progress lines."""
    total = len(ALL_CHECKS)
    fail_count = 0
    warn_count = 0

    for i, (name, check_fn) in enumerate(ALL_CHECKS, 1):
        try:
            severity, detail, action = check_fn()
        except Exception as e:
            severity, detail, action = "fail", f"Check error: {e}", None

        if severity == "fail":
            fail_count += 1
        elif severity == "warn":
            warn_count += 1

        yield _progress(name, i, total, severity, detail, action)

    # Summary
    if fail_count > 0:
        msg = f"{fail_count} failed, {warn_count} warning(s)"
        success = False
    elif warn_count > 0:
        msg = f"All passed with {warn_count} warning(s)"
        success = True
    else:
        msg = "All checks passed"
        success = True

    yield json.dumps({"done": True, "success": success, "message": msg}) + "\n"


# ---------------------------------------------------------------------------
# Fix handlers
# ---------------------------------------------------------------------------


def _fix_missing_accounts(request: HttpRequest) -> JsonResponse:
    """Create missing team accounts by resetting their passwords."""
    active_teams = Team.objects.filter(is_active=True)
    mgr = AuthentikManager()

    missing_teams: list[Team] = []
    for team in active_teams:
        username = f"team{team.team_number:02d}"
        user = mgr.get_user_with_groups(username)
        if not user:
            missing_teams.append(team)

    if not missing_teams:
        return JsonResponse({"success": True, "message": "No missing accounts found"})

    password_list: list[tuple[int, str, str]] = []
    failed: list[str] = []
    for team in missing_teams:
        username = f"team{team.team_number:02d}"
        password = generate_blueteam_password()
        success, error = mgr.reset_blueteam_password(team.team_number, password)
        if success:
            password_list.append((team.team_number, username, password))
        else:
            failed.append(f"{username}: {error}")

    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(["Username", "Password"])
    for _num, username, password in password_list:
        writer.writerow([username, password])

    return JsonResponse(
        {
            "success": True,
            "message": f"Created {len(password_list)}/{len(missing_teams)} accounts",
            "csv": csv_buffer.getvalue(),
            "failed": failed,
        }
    )


def _fix_group_membership(request: HttpRequest) -> JsonResponse:
    """Add team accounts to their correct Authentik groups."""
    active_teams = Team.objects.filter(is_active=True)
    mgr = AuthentikManager()

    fixed = 0
    failed: list[str] = []
    for team in active_teams:
        username = f"team{team.team_number:02d}"
        expected_group = team.authentik_group
        user = mgr.get_user_with_groups(username)
        if not user:
            continue

        groups_obj = user.get("groups_obj", [])
        group_names = [g.get("name", "") for g in groups_obj] if isinstance(groups_obj, list) else []
        if expected_group in group_names:
            continue

        # Find the group and add user
        group = mgr.get_group_by_name(expected_group)
        if not group:
            failed.append(f"{username}: group {expected_group} not found")
            continue

        success, error = mgr.add_user_to_group(cast(int, user["pk"]), cast(str, group["pk"]))
        if success:
            fixed += 1
        else:
            failed.append(f"{username}: {error}")

    msg = f"Fixed {fixed} account(s)"
    if failed:
        msg += f", {len(failed)} failed"
    return JsonResponse({"success": True, "message": msg, "failed": failed})


def _fix_sync_quotient(request: HttpRequest) -> JsonResponse:
    """Sync Quotient metadata."""
    from scoring.quotient_sync import sync_quotient_metadata

    try:
        sync_quotient_metadata()
        return JsonResponse({"success": True, "message": "Quotient metadata synced"})
    except Exception as e:
        logger.exception(f"Failed to sync Quotient metadata: {e}")
        return JsonResponse({"error": f"Sync failed: {e}"}, status=500)


_FIX_HANDLERS: dict[str, Callable[[HttpRequest], JsonResponse]] = {
    "fix_missing_accounts": _fix_missing_accounts,
    "fix_group_membership": _fix_group_membership,
    "fix_sync_quotient": _fix_sync_quotient,
}


# ---------------------------------------------------------------------------
# Action handlers (called from competition.py dispatcher)
# ---------------------------------------------------------------------------


def action_readiness_check(
    request: HttpRequest,
    config: CompetitionConfig,
    authentik_username: str,
) -> StreamingHttpResponse:
    """Handle readiness_check action — streams check results."""
    return StreamingHttpResponse(
        stream_readiness_checks(),
        content_type="application/x-ndjson",
    )


def action_readiness_fix(
    request: HttpRequest,
    config: CompetitionConfig,
    authentik_username: str,
) -> JsonResponse:
    """Handle readiness_fix action — dispatches to fix handlers."""
    form = ReadinessFixForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"error": "Missing fix parameter"}, status=400)
    fix_key = form.cleaned_data["fix"]
    handler = _FIX_HANDLERS.get(fix_key)
    if not handler:
        return JsonResponse({"error": f"Unknown fix: {fix_key}"}, status=400)
    return handler(request)
