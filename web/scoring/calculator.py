"""Score calculation logic for competitions."""

from decimal import Decimal

from django.db import transaction
from django.db.models import Q, QuerySet, Sum
from registration.models import Event

from team.models import Team

from .models import (
    FinalScore,
    IncidentReport,
    InjectScore,
    OrangeTeamScore,
    RedTeamScore,
    ScoringTemplate,
    ServiceScore,
)

# Type alias for score breakdown dictionaries
ScoreBreakdown = dict[str, Decimal]
DetailedScoreBreakdown = dict[str, Decimal]


def _get_modifiers(template: ScoringTemplate) -> tuple[Decimal, Decimal, Decimal]:
    """Derive scaling modifiers from category weights and raw maximums.

    Computes total_pool = max(raw_max / (weight/100)) so the largest category
    keeps its raw scale, then modifier = (weight/100) × total_pool / raw_max.
    """
    hundred = Decimal("100")
    pairs = [
        (template.service_weight, template.service_max),
        (template.inject_weight, template.inject_max),
        (template.orange_weight, template.orange_max),
    ]
    # Largest raw_max / fractional_weight sets the common scale
    total_pool = max(raw_max / (weight / hundred) for weight, raw_max in pairs if weight > 0 and raw_max > 0)
    modifiers: list[Decimal] = []
    for weight, raw_max in pairs:
        if weight > 0 and raw_max > 0:
            modifiers.append(weight / hundred * total_pool / raw_max)
        else:
            modifiers.append(Decimal("0"))
    return modifiers[0], modifiers[1], modifiers[2]


# =============================================================================
# Score Component Queries (DRY - used by both global and event-scoped calcs)
# =============================================================================


def get_approved_inject_total(team: Team, event: Event | None = None) -> Decimal:
    """Get total approved inject points for a team, optionally scoped to event."""
    filters = {"team": team, "is_approved": True}
    if event:
        filters["event"] = event
    return InjectScore.objects.filter(**filters).aggregate(total=Sum("points_awarded"))["total"] or Decimal("0")


def get_approved_orange_total(team: Team, event: Event | None = None) -> Decimal:
    """Get total approved orange team scores for a team, optionally scoped to event."""
    filters = {"team": team, "is_approved": True}
    if event:
        filters["event"] = event
    return OrangeTeamScore.objects.filter(**filters).aggregate(total=Sum("points_awarded"))["total"] or Decimal("0")


def get_approved_red_deductions(team: Team, event: Event | None = None) -> Decimal:
    """Get total approved red team deductions for a team, optionally scoped to event."""
    filters = {"affected_teams": team, "is_approved": True}
    if event:
        filters["event"] = event
    red_scores = RedTeamScore.objects.filter(**filters)
    total = sum(red_score.points_per_team for red_score in red_scores)
    return Decimal(str(total)) * Decimal("-1")  # Return as negative


def calculate_team_score(team: Team) -> ScoreBreakdown:
    """Calculate final score for a team using scaling-factor formula.

    Formula:
        total = (service × service_modifier)
              + (inject × inject_modifier)
              + (orange × orange_modifier)
              + sla_violations + point_adjustments
              + red_deductions + incident_recovery
    """
    template = ScoringTemplate.objects.first() or ScoringTemplate()
    svc_mod, inj_mod, ora_mod = _get_modifiers(template)

    # 1. Service Points + SLA + Point Adjustments
    service_score = ServiceScore.objects.filter(team=team).first()
    if service_score:
        service_raw = service_score.service_points
        sla_raw = service_score.sla_violations
        point_adj = service_score.point_adjustments
    else:
        service_raw = Decimal("0")
        sla_raw = Decimal("0")
        point_adj = Decimal("0")

    # 2. Inject Points (only approved)
    inject_total = get_approved_inject_total(team)

    # 3. Orange Team Bonuses (only approved)
    orange_total = get_approved_orange_total(team)

    # 4. Red Team Deductions (only approved) - returned as negative
    red_raw = get_approved_red_deductions(team)

    # 5. Incident Recovery Points
    recovery_raw = IncidentReport.objects.filter(
        team=team,
        gold_team_reviewed=True,
    ).aggregate(total=Sum("points_returned"))["total"] or Decimal("0")

    # Apply scaling modifiers (derived from weights + raw maxes), round to whole points
    scaled_service = (service_raw * svc_mod).quantize(Decimal("1"))
    scaled_inject = (inject_total * inj_mod).quantize(Decimal("1"))
    scaled_orange = (orange_total * ora_mod).quantize(Decimal("1"))

    # Total: scaled positives + raw negatives
    total_score = scaled_service + scaled_inject + scaled_orange + sla_raw + point_adj + red_raw + recovery_raw

    return {
        "service_points": scaled_service,
        "inject_points": scaled_inject,
        "orange_points": scaled_orange,
        "red_deductions": red_raw,
        "sla_penalties": sla_raw,
        "point_adjustments": point_adj,
        "incident_recovery_points": recovery_raw,
        "total_score": total_score,
    }


def calculate_team_score_detailed(team: Team) -> DetailedScoreBreakdown:
    """Like calculate_team_score but also returns raw scores, modifiers, and weights."""
    template = ScoringTemplate.objects.first() or ScoringTemplate()
    svc_mod, inj_mod, ora_mod = _get_modifiers(template)

    service_score = ServiceScore.objects.filter(team=team).first()
    if service_score:
        service_raw = service_score.service_points
        sla_raw = service_score.sla_violations
        point_adj = service_score.point_adjustments
    else:
        service_raw = Decimal("0")
        sla_raw = Decimal("0")
        point_adj = Decimal("0")

    inject_raw = get_approved_inject_total(team)
    orange_raw = get_approved_orange_total(team)
    red_raw = get_approved_red_deductions(team)
    recovery_raw = IncidentReport.objects.filter(
        team=team,
        gold_team_reviewed=True,
    ).aggregate(total=Sum("points_returned"))["total"] or Decimal("0")

    scaled_service = (service_raw * svc_mod).quantize(Decimal("1"))
    scaled_inject = (inject_raw * inj_mod).quantize(Decimal("1"))
    scaled_orange = (orange_raw * ora_mod).quantize(Decimal("1"))

    total_score = scaled_service + scaled_inject + scaled_orange + sla_raw + point_adj + red_raw + recovery_raw

    return {
        # Standard fields (same as calculate_team_score)
        "service_points": scaled_service,
        "inject_points": scaled_inject,
        "orange_points": scaled_orange,
        "red_deductions": red_raw,
        "sla_penalties": sla_raw,
        "point_adjustments": point_adj,
        "incident_recovery_points": recovery_raw,
        "total_score": total_score,
        # Raw scores (before scaling)
        "service_raw": service_raw,
        "inject_raw": inject_raw,
        "orange_raw": orange_raw,
        # Modifiers
        "svc_modifier": svc_mod,
        "inj_modifier": inj_mod,
        "ora_modifier": ora_mod,
        # Weights
        "service_weight": template.service_weight,
        "inject_weight": template.inject_weight,
        "orange_weight": template.orange_weight,
    }


def _has_scoring_activity(scores: ScoreBreakdown) -> bool:
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
            "point_adjustments",
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

    # Look up which teams are excluded so we can skip them during ranking
    excluded_team_ids = set(
        FinalScore.objects.filter(is_excluded=True).values_list("team_id", flat=True)
    )

    # Update or create FinalScore records; only non-excluded teams get a rank
    rank = 0
    for team, scores in active_teams:
        is_excluded = team.pk in excluded_team_ids
        if not is_excluded:
            rank += 1
        FinalScore.objects.update_or_create(
            team=team,
            defaults={
                "service_points": scores["service_points"],
                "inject_points": scores["inject_points"],
                "orange_points": scores["orange_points"],
                "red_deductions": scores["red_deductions"],
                "incident_recovery_points": scores["incident_recovery_points"],
                "sla_penalties": scores["sla_penalties"],
                "point_adjustments": scores["point_adjustments"],
                "total_score": scores["total_score"],
                "rank": rank if not is_excluded else None,
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
                "point_adjustments": scores["point_adjustments"],
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
        FinalScore.objects.filter(is_excluded=False)
        .exclude(
            service_points=0,
            inject_points=0,
            orange_points=0,
            red_deductions=0,
            incident_recovery_points=0,
            sla_penalties=0,
            point_adjustments=0,
        )
        .select_related("team")
        .order_by("rank")
    )


def suggest_red_score_matches(incident: IncidentReport) -> QuerySet[RedTeamScore]:
    """
    Suggest potential red team scores that match an incident report.

    Matching criteria (prioritized):
    1. Source IP match (most reliable - same attacker IP, including IP pools)
    2. Team is in affected_teams
    3. Same box and/or service

    Args:
        incident: IncidentReport instance

    Returns:
        QuerySet of potential RedTeamScore matches ordered by relevance
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
        # Match if any of the incident's boxes is in the score's list of affected boxes
        for box in incident.affected_boxes:
            filters |= Q(affected_boxes__contains=[box])
    if incident.affected_service:
        filters |= Q(affected_service=incident.affected_service)

    if filters:
        query &= filters

    scores = RedTeamScore.objects.filter(query).distinct().order_by("-created_at")

    return scores[:10]  # Return top 10 matches


def calculate_suggested_recovery_points(incident: IncidentReport, red_score: RedTeamScore) -> Decimal:
    """
    Calculate suggested points to return based on red team deduction.

    Default: 80% of the red team deduction (converted to positive).

    Args:
        incident: IncidentReport instance
        red_score: RedTeamScore instance

    Returns:
        Suggested points to award (positive value)
    """
    deduction_amount = abs(red_score.points_per_team)
    suggested_return = deduction_amount * Decimal("0.80")
    return suggested_return
