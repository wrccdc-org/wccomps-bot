"""JSON API endpoint views."""

from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404

from core.auth_utils import require_permission
from team.models import Team

from ..calculator import calculate_team_score, get_leaderboard
from ..models import RedTeamScore


@require_permission("gold_team", "white_team", "ticketing_admin")
def api_scores(request: HttpRequest) -> JsonResponse:
    """API endpoint for scores."""
    scores = get_leaderboard()
    data = [
        {
            "rank": score.rank,
            "team": f"Team {score.team.team_number}",
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


@require_permission("gold_team", "white_team", "ticketing_admin")
def api_team_detail(request: HttpRequest, team_number: int) -> JsonResponse:
    """API endpoint for team detail."""
    team = get_object_or_404(Team, team_number=team_number)
    scores = calculate_team_score(team)
    return JsonResponse(
        {
            "team": f"Team {team.team_number}",
            "team_number": team.team_number,
            "scores": {k: float(v) for k, v in scores.items()},  # type: ignore[arg-type]
        }
    )


@require_permission("red_team", "gold_team", error_message="Only Red Team or Gold Team can access attack suggestions")
def api_attack_types(request: HttpRequest) -> JsonResponse:
    """API endpoint for attack type suggestions."""
    # Get distinct attack vectors from previous findings
    attack_vectors = (
        RedTeamScore.objects.values_list("attack_vector", flat=True).distinct().order_by("attack_vector")[:50]
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
