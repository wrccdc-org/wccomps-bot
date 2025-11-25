"""Score calculation logic for competitions."""

from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction
from django.db.models import Q, Sum

if TYPE_CHECKING:
    from django.db.models import QuerySet

from team.models import Team

from .models import (
    BlackTeamAdjustment,
    FinalScore,
    IncidentReport,
    InjectGrade,
    OrangeTeamBonus,
    RedTeamFinding,
    ScoringTemplate,
    ServiceScore,
)


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

    # 2. Inject Points
    inject_total = InjectGrade.objects.filter(team=team).aggregate(total=Sum("points_awarded"))["total"] or Decimal("0")

    # 3. Orange Team Bonuses
    orange_total = OrangeTeamBonus.objects.filter(team=team).aggregate(total=Sum("points_awarded"))["total"] or Decimal(
        "0"
    )

    # 4. Red Team Deductions (sum of all findings affecting this team)
    red_findings = RedTeamFinding.objects.filter(affected_teams=team)
    red_deductions = sum(finding.points_per_team for finding in red_findings)
    red_deductions = Decimal(str(red_deductions)) * Decimal("-1")  # Apply as negative

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


@transaction.atomic
def recalculate_all_scores() -> None:
    """
    Recalculate scores for all teams and update rankings.
    """
    # Get all active teams
    teams = Team.objects.filter(is_active=True)

    # Calculate scores for all teams
    score_data = []
    for team in teams:
        scores = calculate_team_score(team)
        score_data.append((team, scores))

    # Sort by total_score descending to assign ranks
    score_data.sort(key=lambda x: x[1]["total_score"], reverse=True)

    # Update or create FinalScore records with ranks
    for rank, (team, scores) in enumerate(score_data, start=1):
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


def get_leaderboard() -> list[FinalScore]:
    """
    Get the current leaderboard.

    Returns:
        List of FinalScore objects ordered by rank
    """
    return list(FinalScore.objects.all().select_related("team").order_by("rank"))


def suggest_red_finding_matches(incident: IncidentReport) -> "QuerySet[RedTeamFinding]":
    """
    Suggest potential red team findings that match an incident report.

    Matching criteria:
    - Team is in affected_teams
    - Same box and/or service
    - Similar timestamp (±30 minutes)

    Args:
        incident: IncidentReport instance

    Returns:
        QuerySet of potential RedTeamFinding matches, ordered by relevance
    """
    from datetime import timedelta

    time_window_start = incident.attack_detected_at - timedelta(minutes=30)
    time_window_end = incident.attack_detected_at + timedelta(minutes=30)

    # Build query with filters
    query = Q(affected_teams=incident.team)

    # Match on box or service
    if incident.affected_box:
        query &= Q(affected_box=incident.affected_box)
    if incident.affected_service:
        query &= Q(affected_service=incident.affected_service)

    # Time window
    query &= Q(created_at__gte=time_window_start, created_at__lte=time_window_end)

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
