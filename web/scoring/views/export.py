"""Export endpoint views."""

from django.http import HttpRequest, HttpResponse

from core.auth_utils import require_permission


@require_permission("gold_team", error_message="Only Gold Team members can access this")
def export_index(request: HttpRequest) -> HttpResponse:
    """Export data index page (admin only)."""
    from django.shortcuts import render

    return render(request, "scoring/export_index.html")


@require_permission("gold_team", error_message="Only Gold Team members can access this")
def export_red_scores(request: HttpRequest) -> HttpResponse:
    """Export red team findings (admin only)."""
    from ..export import export_red_scores_csv, export_red_scores_json

    export_format = request.GET.get("format", "csv").lower()
    if export_format == "json":
        return export_red_scores_json()
    return export_red_scores_csv()


@require_permission("gold_team", error_message="Only Gold Team members can access this")
def export_incidents(request: HttpRequest) -> HttpResponse:
    """Export incident reports (admin only)."""
    from ..export import export_incidents_csv, export_incidents_json

    export_format = request.GET.get("format", "csv").lower()
    if export_format == "json":
        return export_incidents_json()
    return export_incidents_csv()


@require_permission("gold_team", error_message="Only Gold Team members can access this")
def export_orange_adjustments(request: HttpRequest) -> HttpResponse:
    """Export orange team adjustments (admin only)."""
    from ..export import export_orange_adjustments_csv, export_orange_adjustments_json

    export_format = request.GET.get("format", "csv").lower()
    if export_format == "json":
        return export_orange_adjustments_json()
    return export_orange_adjustments_csv()


@require_permission("gold_team", error_message="Only Gold Team members can access this")
def export_inject_grades(request: HttpRequest) -> HttpResponse:
    """Export inject grades (admin only)."""
    from ..export import export_inject_grades_csv, export_inject_grades_json

    export_format = request.GET.get("format", "csv").lower()
    if export_format == "json":
        return export_inject_grades_json()
    return export_inject_grades_csv()


@require_permission("gold_team", error_message="Only Gold Team members can access this")
def export_final_scores(request: HttpRequest) -> HttpResponse:
    """Export final scores (admin only)."""
    from ..export import export_final_scores_csv, export_final_scores_json

    export_format = request.GET.get("format", "csv").lower()
    if export_format == "json":
        return export_final_scores_json()
    return export_final_scores_csv()


@require_permission("gold_team", error_message="Only Gold Team members can access this")
def export_all(request: HttpRequest) -> HttpResponse:
    """Export all scoring data as a zip file (admin only)."""
    from ..export import export_all_zip

    return export_all_zip()


@require_permission("gold_team", error_message="Only Gold Team members can access this")
def export_scorecards(request: HttpRequest) -> HttpResponse:
    """Export all team scorecards as a zip of PDFs."""
    import io
    import zipfile

    import weasyprint
    from django.template.loader import render_to_string
    from django.utils import timezone

    from ..calculator import calculate_team_score_detailed
    from ..models import FinalScore, RedTeamScore
    from .leaderboard import _compute_scorecard_stats

    scores = FinalScore.objects.filter(is_excluded=False, rank__isnull=False).select_related("team").order_by("rank")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for final_score in scores:
            team = final_score.team
            red_scores = (
                RedTeamScore.objects.filter(affected_teams=team, is_approved=True)
                .select_related("attack_type")
                .order_by("attack_type__name", "pk")
            )

            stats = _compute_scorecard_stats(team, final_score)
            detailed = calculate_team_score_detailed(team)

            context = {
                "team": team,
                "score": final_score,
                "red_scores": red_scores,
                "stats": stats,
                "red_total": sum(r.points_per_team for r in red_scores),
                "inject_total": sum(i["points"] for i in stats["inject_stats"]),
                "service_total": sum(s["points"] for s in stats["service_stats"]),
                "scaling": {
                    "service_raw": detailed["service_raw"],
                    "inject_raw": detailed["inject_raw"],
                    "orange_raw": detailed["orange_raw"],
                    "svc_modifier": detailed["svc_modifier"],
                    "inj_modifier": detailed["inj_modifier"],
                    "ora_modifier": detailed["ora_modifier"],
                    "service_weight": detailed["service_weight"],
                    "inject_weight": detailed["inject_weight"],
                    "orange_weight": detailed["orange_weight"],
                },
            }

            html_string = render_to_string("scoring/scorecard_print.html", context, request=request)
            pdf_bytes = weasyprint.HTML(string=html_string).write_pdf()
            zf.writestr(f"team-{team.team_number:02d}-scorecard.pdf", pdf_bytes)

    timestamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    response = HttpResponse(buf.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="scorecards-{timestamp}.zip"'
    return response
