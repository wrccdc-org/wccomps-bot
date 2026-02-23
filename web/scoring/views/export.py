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
