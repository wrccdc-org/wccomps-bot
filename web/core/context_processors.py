"""Context processors for making data available to all templates."""

from django.contrib.auth.models import User
from django.http import HttpRequest

from .auth_utils import get_permissions_context, has_permission

NAV_MAPPING: dict[str, tuple[str, str]] = {
    # Tickets - ops team ticket management
    "ops_ticket_list": ("tickets", ""),
    "ops_ticket_detail": ("tickets", ""),
    "ops_ticket_claim": ("tickets", ""),
    "ops_ticket_unclaim": ("tickets", ""),
    "ops_ticket_resolve": ("tickets", ""),
    "ops_ticket_reopen": ("tickets", ""),
    "ops_ticket_reassign": ("tickets", ""),
    "ops_ticket_comment": ("tickets", ""),
    "ops_ticket_change_category": ("tickets", ""),
    "ops_ticket_attachment_upload": ("tickets", ""),
    "ops_ticket_attachment_download": ("tickets", ""),
    "ops_tickets_bulk_claim": ("tickets", ""),
    "ops_tickets_bulk_resolve": ("tickets", ""),
    "ops_tickets_clear_all": ("tickets", ""),
    # Incident Report (blue team)
    "submit_incident_report": ("incident", ""),
    "view_incident_report": ("incident", ""),
    "incident_list": ("incident", ""),
    "delete_incident_report": ("incident", ""),
    # Red Team Findings
    "submit_red_finding": ("red_findings", "submit"),
    "red_team_findings": ("red_findings", "findings"),
    "view_red_finding": ("red_findings", "findings"),
    "delete_red_finding": ("red_findings", "findings"),
    "leave_red_finding": ("red_findings", "findings"),
    "ip_pool_list": ("red_findings", "pools"),
    "ip_pool_create": ("red_findings", "pools"),
    "ip_pool_edit": ("red_findings", "pools"),
    "ip_pool_delete": ("red_findings", "pools"),
    # Orange Team
    "orange_team_portal": ("orange", "portal"),
    "submit_orange_bonus": ("orange", "submit"),
    "bulk_approve_orange_adjustments": ("orange", "portal"),
    "approve_orange_adjustment": ("orange", "portal"),
    "reject_orange_adjustment": ("orange", "portal"),
    "manage_check_types": ("orange", "check_types"),
    "edit_check_type": ("orange", "check_types"),
    "delete_check_type": ("orange", "check_types"),
    "api_orange_check_types": ("orange", "check_types"),
    # School Info
    "ops_school_info": ("school", ""),
    "ops_school_info_edit": ("school", ""),
    "ops_school_info_import": ("school", ""),
    # Scoring pages
    "leaderboard": ("scoring", "leaderboard"),
    "event_leaderboard": ("scoring", "leaderboard"),
    "red_team_portal": ("scoring", "red_team"),
    "bulk_approve_red_findings": ("scoring", "red_team"),
    "review_orange": ("scoring", "orange_team"),
    "review_incidents": ("scoring", "review_incidents"),
    "match_incident": ("scoring", "review_incidents"),
    "inject_grading": ("scoring", "inject_grading"),
    "submit_inject_grade": ("scoring", "inject_grading"),
    "inject_grades_review": ("scoring", "inject_grades_review"),
    "inject_grades_bulk_approve": ("scoring", "inject_grades_review"),
    "ops_review_tickets": ("scoring", "review_tickets"),
    "ops_verify_ticket": ("scoring", "review_tickets"),
    "ops_batch_verify_tickets": ("scoring", "review_tickets"),
    "scoring_config": ("scoring", "config"),
    "sync_quotient_injects": ("scoring", "config"),
    "recalculate_scores": ("scoring", "config"),
    "export_index": ("scoring", "export"),
    "export_red_findings": ("scoring", "export"),
    "export_incidents": ("scoring", "export"),
    "export_scores": ("scoring", "export"),
}


def _get_nav_active(request: HttpRequest) -> dict[str, str]:
    """Determine which nav items should be active based on URL."""
    url_name = getattr(request.resolver_match, "url_name", "") or ""
    app_name = getattr(request.resolver_match, "app_name", "") or ""

    # Look up in explicit mapping first
    if url_name in NAV_MAPPING:
        nav, subnav = NAV_MAPPING[url_name]
        return {"nav": nav, "subnav": subnav}

    # Fallback for admin
    if app_name == "admin":
        return {"nav": "admin", "subnav": ""}

    return {"nav": "", "subnav": ""}


def permissions(request: HttpRequest) -> dict[str, bool | str]:
    """Add permission flags to all template contexts."""
    if not request.user.is_authenticated:
        return {
            "is_ticketing_admin": False,
            "is_ticketing_support": False,
            "is_gold_team": False,
            "is_blue_team": False,
            "is_red_team": False,
            "is_white_team": False,
            "is_orange_team": False,
            "is_admin": False,
            "authentik_username": "",
            "nav_active": "",
            "subnav_active": "",
        }

    user: User = request.user
    perms = get_permissions_context(user)

    nav_context = _get_nav_active(request)
    return {
        **perms,
        "is_blue_team": has_permission(user, "blue_team"),
        "is_red_team": has_permission(user, "red_team"),
        "authentik_username": user.username,
        "nav_active": nav_context["nav"],
        "subnav_active": nav_context["subnav"],
    }
