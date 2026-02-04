"""Score calculation logic for competitions."""

from decimal import Decimal

from django.db import transaction
from django.db.models import Q, QuerySet, Sum
from registration.models import Event, EventTeamAssignment

from team.models import Team

from .models import (
    BlackTeamAdjustment,
    EventScore,
    FinalScore,
    IncidentReport,
    InjectGrade,
    OrangeTeamBonus,
    RedTeamFinding,
    ScoringTemplate,
    ServiceScore,
)

# =============================================================================
# Score Component Queries (DRY - used by both global and event-scoped calcs)
# =============================================================================


def get_approved_inject_total(team: Team, event: Event | None = None) -> Decimal:
    """Get total approved inject points for a team, optionally scoped to event."""
    filters = {"team": team, "is_approved": True}
    if event:
        filters["event"] = event
    return InjectGrade.objects.filter(**filters).aggregate(total=Sum("points_awarded"))["total"] or Decimal("0")


def get_approved_orange_total(team: Team, event: Event | None = None) -> Decimal:
    """Get total approved orange team bonuses for a team, optionally scoped to event."""
    filters = {"team": team, "is_approved": True}
    if event:
        filters["event"] = event
    return OrangeTeamBonus.objects.filter(**filters).aggregate(total=Sum("points_awarded"))["total"] or Decimal("0")


def get_approved_red_deductions(team: Team, event: Event | None = None) -> Decimal:
    """Get total approved red team deductions for a team, optionally scoped to event."""
    filters = {"affected_teams": team, "is_approved": True}
    if event:
        filters["event"] = event
    red_findings = RedTeamFinding.objects.filter(**filters)
    total = sum(finding.points_per_team for finding in red_findings)
    return Decimal(str(total)) * Decimal("-1")  # Return as negative


def calculate_team_score(team: Team) -> dict[str, Decimal]:
    """
    Calculate final score for a single team based on 4 weighted categories.

    Categories:
    - Service: (service_points + sla_penalties) / service_max × service_weight
    - Inject: inject_total / inject_max × inject_weight
    - Orange: orange_total / orange_max × orange_weight
    - Red: net_red_impact / red_max × red_weight (deductions offset by recovery)

    Args:
        team: Team instance

    Returns:
        Dictionary with score breakdown (raw SLA/recovery preserved for display)
    """
    template = ScoringTemplate.objects.first() or ScoringTemplate()

    # 1. Service Points + SLA (from Quotient)
    service_score = ServiceScore.objects.filter(team=team).first()
    if service_score:
        service_raw = service_score.service_points
        sla_raw = service_score.sla_violations  # Already stored as negative
    else:
        service_raw = Decimal("0")
        sla_raw = Decimal("0")

    # 2. Inject Points (only approved grades count)
    inject_total = get_approved_inject_total(team)

    # 3. Orange Team Bonuses (only approved bonuses count)
    orange_total = get_approved_orange_total(team)

    # 4. Red Team Deductions (only approved findings count) - returned as negative
    red_raw = get_approved_red_deductions(team)

    # 5. Incident Recovery Points (points returned from matched incident reports)
    recovery_raw = IncidentReport.objects.filter(
        team=team,
        gold_team_reviewed=True,
    ).aggregate(total=Sum("points_returned"))["total"] or Decimal("0")

    # 6. Black Team Adjustments (added directly, not weighted)
    black_adjustments = BlackTeamAdjustment.objects.filter(team=team).aggregate(total=Sum("point_adjustment"))[
        "total"
    ] or Decimal("0")

    # SERVICE: Combine service + SLA (SLA is negative, reduces net service)
    net_service = service_raw + sla_raw
    service_norm = max(min(net_service / template.service_max, Decimal("1")), Decimal("0"))

    # Inject normalization
    inject_norm = min(inject_total / template.inject_max, Decimal("1")) if template.inject_max else Decimal("0")

    # Orange normalization
    orange_norm = min(orange_total / template.orange_max, Decimal("1")) if template.orange_max else Decimal("0")

    # Red: combine deductions + recovery, normalize (negative = deduction, capped at -100%)
    net_red = red_raw + recovery_raw
    red_norm = max(net_red / template.red_max, Decimal("-1")) if net_red < Decimal("0") else Decimal("0")

    # Apply weights (result is on 0-100 scale)
    weighted_service = service_norm * template.service_weight
    weighted_inject = inject_norm * template.inject_weight
    weighted_orange = orange_norm * template.orange_weight
    weighted_red = red_norm * template.red_weight  # Already negative

    # Calculate total (0-100 scale)
    total_score = weighted_service + weighted_inject + weighted_orange + weighted_red

    return {
        # Weighted category contributions (used in total)
        "service_points": weighted_service,
        "inject_points": weighted_inject,
        "orange_points": weighted_orange,
        "red_deductions": weighted_red,
        # Raw values for display (not separately weighted)
        "sla_penalties": sla_raw,
        "incident_recovery_points": recovery_raw,
        # Adjustments and total
        "black_adjustments": black_adjustments,
        "total_score": total_score,
    }


def _has_scoring_activity(scores: dict[str, Decimal]) -> bool:
    """Check if a team has any scoring activity (any non-zero component)."""
    return any(
        scores[key] != 0
        for key in [
            "service_points",
            "inject_points",
            "orange_points",
            "red_deductions",
            "incident_recovery_points",
            "sla_penalties",
            "black_adjustments",
        ]
    )


@transaction.atomic
def recalculate_all_scores() -> None:
    """
    Recalculate scores for all teams and update rankings.
    Only teams with scoring activity are ranked.
    """
    # Get all active teams
    teams = Team.objects.filter(is_active=True)

    # Calculate scores for all teams
    score_data = []
    for team in teams:
        scores = calculate_team_score(team)
        score_data.append((team, scores))

    # Separate teams with activity from those without
    active_teams = [(t, s) for t, s in score_data if _has_scoring_activity(s)]
    inactive_teams = [(t, s) for t, s in score_data if not _has_scoring_activity(s)]

    # Sort active teams by total_score descending to assign ranks
    active_teams.sort(key=lambda x: x[1]["total_score"], reverse=True)

    # Update or create FinalScore records with ranks for active teams
    for rank, (team, scores) in enumerate(active_teams, start=1):
        FinalScore.objects.update_or_create(
            team=team,
            defaults={
                "service_points": scores["service_points"],
                "inject_points": scores["inject_points"],
                "orange_points": scores["orange_points"],
                "red_deductions": scores["red_deductions"],
                "incident_recovery_points": scores["incident_recovery_points"],
                "sla_penalties": scores["sla_penalties"],
                "black_adjustments": scores["black_adjustments"],
                "total_score": scores["total_score"],
                "rank": rank,
            },
        )

    # Update inactive teams with rank=None
    for team, scores in inactive_teams:
        FinalScore.objects.update_or_create(
            team=team,
            defaults={
                "service_points": scores["service_points"],
                "inject_points": scores["inject_points"],
                "orange_points": scores["orange_points"],
                "red_deductions": scores["red_deductions"],
                "incident_recovery_points": scores["incident_recovery_points"],
                "sla_penalties": scores["sla_penalties"],
                "black_adjustments": scores["black_adjustments"],
                "total_score": scores["total_score"],
                "rank": None,
            },
        )


def get_leaderboard() -> list[FinalScore]:
    """
    Get the current leaderboard.

    Returns:
        List of FinalScore objects ordered by rank, excluding teams with no scoring activity
    """
    return list(
        FinalScore.objects.exclude(
            service_points=0,
            inject_points=0,
            orange_points=0,
            red_deductions=0,
            incident_recovery_points=0,
            sla_penalties=0,
            black_adjustments=0,
        )
        .select_related("team")
        .order_by("rank")
    )


def suggest_red_finding_matches(incident: IncidentReport) -> QuerySet[RedTeamFinding]:
    """
    Suggest potential red team findings that match an incident report.

    Matching criteria (prioritized):
    1. Source IP match (most reliable - same attacker IP, including IP pools)
    2. Team is in affected_teams
    3. Same box and/or service

    Args:
        incident: IncidentReport instance

    Returns:
        QuerySet of potential RedTeamFinding matches, ordered by relevance
    """
    from .models import RedTeamIPPool

    # Primary match: source_ip (most reliable indicator)
    # Secondary match: team + box/service
    query = Q(affected_teams=incident.team)

    # Build optional filters
    filters = Q()
    if incident.source_ip:
        # Match exact source_ip
        filters |= Q(source_ip=incident.source_ip)
        # Also match any IP pools that contain this IP
        pool_ids = [pool.id for pool in RedTeamIPPool.objects.all() if pool.contains_ip(str(incident.source_ip))]
        if pool_ids:
            filters |= Q(source_ip_pool_id__in=pool_ids)
    if incident.affected_boxes:
        # Match if any of the incident's boxes is in the finding's list of affected boxes
        for box in incident.affected_boxes:
            filters |= Q(affected_boxes__contains=[box])
    if incident.affected_service:
        filters |= Q(affected_service=incident.affected_service)

    if filters:
        query &= filters

    findings = RedTeamFinding.objects.filter(query).distinct().order_by("-created_at")

    return findings[:10]  # Return top 10 matches


def calculate_suggested_recovery_points(incident: IncidentReport, red_finding: RedTeamFinding) -> Decimal:
    """
    Calculate suggested points to return based on red team deduction.

    Default: 80% of the red team deduction (converted to positive).

    Args:
        incident: IncidentReport instance
        red_finding: RedTeamFinding instance

    Returns:
        Suggested points to award (positive value)
    """
    deduction_amount = abs(red_finding.points_per_team)
    suggested_return = deduction_amount * Decimal("0.80")
    return suggested_return


def calculate_team_event_score(team: Team, event: Event) -> dict[str, Decimal]:
    """
    Calculate score for a single team for a specific event using 4 weighted categories.

    Categories:
    - Service: (service_points + sla_penalties) / service_max × service_weight
    - Inject: inject_total / inject_max × inject_weight
    - Orange: orange_total / orange_max × orange_weight
    - Red: net_red_impact / red_max × red_weight (deductions offset by recovery)

    Args:
        team: Team instance
        event: Event instance

    Returns:
        Dictionary with score breakdown (raw SLA/recovery preserved for display)
    """
    template = ScoringTemplate.objects.first() or ScoringTemplate()

    # 1. Service Points + SLA (from Quotient, scoped to event)
    service_score = ServiceScore.objects.filter(team=team, event=event).first()
    if service_score:
        service_raw = service_score.service_points
        sla_raw = service_score.sla_violations
    else:
        service_raw = Decimal("0")
        sla_raw = Decimal("0")

    # 2. Inject Points (scoped to event, only approved grades count)
    inject_total = get_approved_inject_total(team, event)

    # 3. Orange Team Bonuses (scoped to event, only approved bonuses count)
    orange_total = get_approved_orange_total(team, event)

    # 4. Red Team Deductions (scoped to event, only approved findings count) - returned as negative
    red_raw = get_approved_red_deductions(team, event)

    # 5. Incident Recovery Points (scoped to event)
    recovery_raw = IncidentReport.objects.filter(
        team=team,
        event=event,
        gold_team_reviewed=True,
    ).aggregate(total=Sum("points_returned"))["total"] or Decimal("0")

    # 6. Black Team Adjustments (scoped to event, added directly, not weighted)
    black_adjustments = BlackTeamAdjustment.objects.filter(team=team, event=event).aggregate(
        total=Sum("point_adjustment")
    )["total"] or Decimal("0")

    # SERVICE: Combine service + SLA (SLA is negative, reduces net service)
    net_service = service_raw + sla_raw
    service_norm = max(min(net_service / template.service_max, Decimal("1")), Decimal("0"))

    # Inject normalization
    inject_norm = min(inject_total / template.inject_max, Decimal("1")) if template.inject_max else Decimal("0")

    # Orange normalization
    orange_norm = min(orange_total / template.orange_max, Decimal("1")) if template.orange_max else Decimal("0")

    # Red: combine deductions + recovery, normalize (negative = deduction, capped at -100%)
    net_red = red_raw + recovery_raw
    red_norm = max(net_red / template.red_max, Decimal("-1")) if net_red < Decimal("0") else Decimal("0")

    # Apply weights (result is on 0-100 scale)
    weighted_service = service_norm * template.service_weight
    weighted_inject = inject_norm * template.inject_weight
    weighted_orange = orange_norm * template.orange_weight
    weighted_red = red_norm * template.red_weight  # Already negative

    # Calculate total (0-100 scale)
    total_score = weighted_service + weighted_inject + weighted_orange + weighted_red

    return {
        # Weighted category contributions (used in total)
        "service_points": weighted_service,
        "inject_points": weighted_inject,
        "orange_points": weighted_orange,
        "red_deductions": weighted_red,
        # Raw values for display (not separately weighted)
        "sla_penalties": sla_raw,
        "incident_recovery_points": recovery_raw,
        # Adjustments and total
        "black_adjustments": black_adjustments,
        "total_score": total_score,
    }


@transaction.atomic
def recalculate_event_scores(event: Event) -> None:
    """
    Recalculate scores for all teams participating in an event.

    Only teams with an EventTeamAssignment for this event are included.
    """
    assignments = EventTeamAssignment.objects.filter(event=event).select_related("team", "registration")

    score_data = []
    for assignment in assignments:
        team = assignment.team
        scores = calculate_team_event_score(team, event)
        score_data.append((assignment, team, scores))

    # Separate teams with activity from those without
    active_teams = [(a, t, s) for a, t, s in score_data if _has_scoring_activity(s)]
    inactive_teams = [(a, t, s) for a, t, s in score_data if not _has_scoring_activity(s)]

    # Sort by total_score descending
    active_teams.sort(key=lambda x: x[2]["total_score"], reverse=True)

    # Update or create EventScore records with ranks
    for rank, (assignment, team, scores) in enumerate(active_teams, start=1):
        EventScore.objects.update_or_create(
            team=team,
            event=event,
            defaults={
                "team_assignment": assignment,
                "service_points": scores["service_points"],
                "inject_points": scores["inject_points"],
                "orange_points": scores["orange_points"],
                "red_deductions": scores["red_deductions"],
                "incident_recovery_points": scores["incident_recovery_points"],
                "sla_penalties": scores["sla_penalties"],
                "black_adjustments": scores["black_adjustments"],
                "total_score": scores["total_score"],
                "rank": rank,
            },
        )

    # Update inactive teams with rank=None
    for assignment, team, scores in inactive_teams:
        EventScore.objects.update_or_create(
            team=team,
            event=event,
            defaults={
                "team_assignment": assignment,
                "service_points": scores["service_points"],
                "inject_points": scores["inject_points"],
                "orange_points": scores["orange_points"],
                "red_deductions": scores["red_deductions"],
                "incident_recovery_points": scores["incident_recovery_points"],
                "sla_penalties": scores["sla_penalties"],
                "black_adjustments": scores["black_adjustments"],
                "total_score": scores["total_score"],
                "rank": None,
            },
        )


def get_event_leaderboard(event: Event) -> list[EventScore]:
    """
    Get the leaderboard for a specific event.

    Returns:
        List of EventScore objects ordered by rank, excluding teams with no scoring activity
    """
    return list(
        EventScore.objects.filter(event=event)
        .exclude(
            service_points=0,
            inject_points=0,
            orange_points=0,
            red_deductions=0,
            incident_recovery_points=0,
            sla_penalties=0,
            black_adjustments=0,
        )
        .select_related("team", "team_assignment", "team_assignment__registration")
        .order_by("rank")
    )
