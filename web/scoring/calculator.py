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
    Calculate final score for a single team based on all scoring components.

    Args:
        team: Team instance

    Returns:
        Dictionary with score breakdown
    """
    # Get scoring template with weights
    template = ScoringTemplate.objects.first()
    if not template:
        # Use default weights if no template exists
        template = ScoringTemplate()

    # 1. Service Points (from Quotient)
    service_score = ServiceScore.objects.filter(team=team).first()
    if service_score:
        service_points = service_score.service_points
        sla_penalties = service_score.sla_violations  # Already stored as negative
    else:
        service_points = Decimal("0")
        sla_penalties = Decimal("0")

    # 2. Inject Points (only approved grades count)
    inject_total = get_approved_inject_total(team)

    # 3. Orange Team Bonuses (only approved bonuses count)
    orange_total = get_approved_orange_total(team)

    # 4. Red Team Deductions (only approved findings count)
    red_deductions = get_approved_red_deductions(team)

    # 5. Incident Recovery Points (points returned from matched incident reports)
    incident_recovery = IncidentReport.objects.filter(
        team=team,
        gold_team_reviewed=True,
    ).aggregate(total=Sum("points_returned"))["total"] or Decimal("0")

    # 6. Black Team Adjustments
    black_adjustments = BlackTeamAdjustment.objects.filter(team=team).aggregate(total=Sum("point_adjustment"))[
        "total"
    ] or Decimal("0")

    # Apply multipliers to all score components
    scaled_service = service_points * template.service_multiplier
    scaled_inject = inject_total * template.inject_multiplier
    scaled_orange = orange_total * template.orange_multiplier
    scaled_red = red_deductions * template.red_multiplier
    scaled_sla = sla_penalties * template.sla_multiplier
    scaled_recovery = incident_recovery * template.recovery_multiplier

    # Calculate total using formula with configurable multipliers
    total_score = scaled_service + scaled_inject + scaled_orange + scaled_red + scaled_sla + scaled_recovery

    return {
        "service_points": scaled_service,
        "inject_points": scaled_inject,
        "orange_points": scaled_orange,
        "red_deductions": scaled_red,
        "incident_recovery_points": scaled_recovery,
        "sla_penalties": scaled_sla,
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
    Calculate score for a single team for a specific event.

    Args:
        team: Team instance
        event: Event instance

    Returns:
        Dictionary with score breakdown
    """
    # Get scoring template with weights
    template = ScoringTemplate.objects.first()
    if not template:
        template = ScoringTemplate()

    # 1. Service Points (from Quotient, scoped to event)
    service_score = ServiceScore.objects.filter(team=team, event=event).first()
    if service_score:
        service_points = service_score.service_points
        sla_penalties = service_score.sla_violations
    else:
        service_points = Decimal("0")
        sla_penalties = Decimal("0")

    # 2. Inject Points (scoped to event, only approved grades count)
    inject_total = get_approved_inject_total(team, event)

    # 3. Orange Team Bonuses (scoped to event, only approved bonuses count)
    orange_total = get_approved_orange_total(team, event)

    # 4. Red Team Deductions (scoped to event, only approved findings count)
    red_deductions = get_approved_red_deductions(team, event)

    # 5. Incident Recovery Points (scoped to event)
    incident_recovery = IncidentReport.objects.filter(
        team=team,
        event=event,
        gold_team_reviewed=True,
    ).aggregate(total=Sum("points_returned"))["total"] or Decimal("0")

    # 6. Black Team Adjustments (scoped to event)
    black_adjustments = BlackTeamAdjustment.objects.filter(team=team, event=event).aggregate(
        total=Sum("point_adjustment")
    )["total"] or Decimal("0")

    # Apply multipliers
    scaled_service = service_points * template.service_multiplier
    scaled_inject = inject_total * template.inject_multiplier
    scaled_orange = orange_total * template.orange_multiplier
    scaled_red = red_deductions * template.red_multiplier
    scaled_sla = sla_penalties * template.sla_multiplier
    scaled_recovery = incident_recovery * template.recovery_multiplier

    total_score = scaled_service + scaled_inject + scaled_orange + scaled_red + scaled_sla + scaled_recovery

    return {
        "service_points": scaled_service,
        "inject_points": scaled_inject,
        "orange_points": scaled_orange,
        "red_deductions": scaled_red,
        "incident_recovery_points": scaled_recovery,
        "sla_penalties": scaled_sla,
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
