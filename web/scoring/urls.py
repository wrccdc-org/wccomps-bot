"""URL configuration for scoring app."""

from django.urls import path

from . import views

app_name = "scoring"

urlpatterns = [
    # Leaderboard
    path("", views.leaderboard, name="leaderboard"),
    path("event/<int:event_id>/", views.event_leaderboard, name="event_leaderboard"),
    path("event/<int:event_id>/recalculate/", views.recalculate_event_scores_view, name="recalculate_event_scores"),
    path("event/<int:event_id>/send-scorecards/", views.send_scorecards_batch_view, name="send_scorecards_batch"),
    path("scorecard/<int:event_score_id>/send/", views.send_scorecard_single_view, name="send_scorecard_single"),
    # Red Team
    path("red-team/", views.red_team_portal, name="red_team_portal"),
    path("red-team/submit/", views.submit_red_finding, name="submit_red_finding"),
    path("red-team/<int:finding_id>/delete/", views.delete_red_finding, name="delete_red_finding"),
    path("red-team/<int:finding_id>/leave/", views.leave_red_finding, name="leave_red_finding"),
    path("red-team/bulk-approve/", views.bulk_approve_red_findings, name="bulk_approve_red_findings"),
    path("red-team/screenshot/<int:screenshot_id>/", views.red_screenshot_download, name="red_screenshot"),
    # IP Pools (Red Team)
    path("red-team/ip-pools/", views.ip_pool_list, name="ip_pool_list"),
    path("red-team/ip-pools/create/", views.ip_pool_create, name="ip_pool_create"),
    path("red-team/ip-pools/<int:pool_id>/edit/", views.ip_pool_edit, name="ip_pool_edit"),
    path("red-team/ip-pools/<int:pool_id>/delete/", views.ip_pool_delete, name="ip_pool_delete"),
    path("api/ip-pools/", views.api_user_ip_pools, name="api_user_ip_pools"),
    # Incident Reports (Blue Team)
    path("incident/list/", views.incident_list, name="incident_list"),
    path("incident/submit/", views.submit_incident_report, name="submit_incident_report"),
    path("incident/<int:incident_id>/", views.view_incident_report, name="view_incident_report"),
    path("incident/<int:incident_id>/delete/", views.delete_incident_report, name="delete_incident_report"),
    path("incident/screenshot/<int:screenshot_id>/", views.incident_screenshot_download, name="incident_screenshot"),
    # Orange Team
    path("orange-team/", views.orange_team_portal, name="orange_team_portal"),
    path("orange-team/submit/", views.submit_orange_bonus, name="submit_orange_bonus"),
    path("orange-team/check-types/", views.manage_check_types, name="manage_check_types"),
    path("orange-team/check-types/<int:check_type_id>/edit/", views.edit_check_type, name="edit_check_type"),
    path("orange-team/check-types/<int:check_type_id>/delete/", views.delete_check_type, name="delete_check_type"),
    path("orange-team/<int:adjustment_id>/approve/", views.approve_orange_adjustment, name="approve_orange_adjustment"),
    path("orange-team/<int:adjustment_id>/reject/", views.reject_orange_adjustment, name="reject_orange_adjustment"),
    path("orange-team/bulk-approve/", views.bulk_approve_orange_adjustments, name="bulk_approve_orange_adjustments"),
    path("orange-team/bulk-reject/", views.bulk_reject_orange_adjustments, name="bulk_reject_orange_adjustments"),
    # Inject Grading (White/Gold Team)
    path("injects/", views.inject_grading, name="inject_grading"),
    path("injects/review/", views.inject_grades_review, name="inject_grades_review"),
    path("injects/bulk-approve/", views.inject_grades_bulk_approve, name="inject_grades_bulk_approve"),
    # Gold Team - Incident Review
    path("gold-team/incidents/", views.review_incidents, name="review_incidents"),
    path("gold-team/incidents/<int:incident_id>/match/", views.match_incident, name="match_incident"),
    # Admin/Configuration
    path("admin/config/", views.scoring_config, name="scoring_config"),
    path("admin/sync-metadata/", views.sync_metadata, name="sync_metadata"),
    path("admin/sync-scores/", views.sync_scores, name="sync_scores"),
    path("admin/recalculate/", views.recalculate_scores, name="recalculate_scores"),
    # API endpoints
    path("api/scores/", views.api_scores, name="api_scores"),
    path("api/team/<int:team_number>/", views.api_team_detail, name="api_team_detail"),
    path("api/attack-types/", views.api_attack_types, name="api_attack_types"),
    path("api/orange-check-types/", views.api_orange_check_types, name="api_orange_check_types"),
    # Export endpoints
    path("export/", views.export_index, name="export_index"),
    path("export/red-findings/", views.export_red_findings, name="export_red_findings"),
    path("export/incidents/", views.export_incidents, name="export_incidents"),
    path("export/orange-adjustments/", views.export_orange_adjustments, name="export_orange_adjustments"),
    path("export/inject-grades/", views.export_inject_grades, name="export_inject_grades"),
    path("export/final-scores/", views.export_final_scores, name="export_final_scores"),
]
