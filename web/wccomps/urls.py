"""
URL configuration for wccomps project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path

from core import admin_views, oauth, views
from ticketing import views as ticketing_views

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health_check, name="health_check"),
    path("admin/", admin.site.urls),
    # OAuth routes (replaces allauth)
    path("auth/login/", oauth.oauth_login, name="oauth_login"),
    path("auth/callback/", oauth.oauth_callback, name="oauth_callback"),
    path("auth/logout/", oauth.oauth_logout, name="oauth_logout"),
    # Discord linking routes
    path("auth/link", views.link_initiate, name="link_initiate"),
    path("auth/link-callback", views.link_callback, name="link_callback"),
    path("packet/", include("packets.urls_team")),
    path("packets/", include("packets.urls_admin")),
    path("ops/school-info/", views.school_info, name="school_info"),
    path(
        "ops/school-info/import/",
        views.school_info_import,
        name="school_info_import",
    ),
    path(
        "ops/school-info/<int:team_number>/",
        views.school_info_edit,
        name="school_info_edit",
    ),
    path(
        "ops/group-role-mappings/",
        views.ops_group_role_mappings,
        name="ops_group_role_mappings",
    ),
    path("scoring/", include("scoring.urls")),
    path("orange-team/", include("challenges.urls")),
    path("register/", include("registration.urls")),
    # Ticketing routes (unified under /tickets/)
    path("tickets/", include("ticketing.urls")),
    # Ops ticket review routes (stay under /ops/)
    path("ops/review-tickets/", ticketing_views.ops_review_tickets, name="ops_review_tickets"),
    path("ops/ticket/<str:ticket_number>/verify/", ticketing_views.ops_verify_ticket, name="ops_verify_ticket"),
    path(
        "ops/tickets/batch-verify-points/",
        ticketing_views.ops_batch_verify_tickets,
        name="ops_batch_verify_tickets",
    ),
    # Backwards-compat redirects for old /ops/tickets/ URLs
    path("ops/tickets/", lambda r: redirect("ticket_list", permanent=True), name="ops_ticket_list_redirect"),
    path(
        "ops/ticket/<str:ticket_number>/",
        lambda r, ticket_number: redirect("ticket_detail", ticket_number=ticket_number, permanent=True),
        name="ops_ticket_detail_redirect",
    ),
    # Admin management routes
    path("ops/admin/competition/", admin_views.admin_competition, name="admin_competition"),
    path("ops/admin/competition/action/", admin_views.admin_competition_action, name="admin_competition_action"),
    path("ops/admin/teams/", admin_views.admin_teams, name="admin_teams"),
    path("ops/admin/teams/bulk/", admin_views.admin_teams_bulk_action, name="admin_teams_bulk_action"),
    path("ops/admin/teams/<int:team_number>/", admin_views.admin_team_detail, name="admin_team_detail"),
    path("ops/admin/teams/<int:team_number>/action/", admin_views.admin_team_action, name="admin_team_action"),
    path("ops/admin/broadcast/", admin_views.admin_broadcast, name="admin_broadcast"),
    path("ops/admin/broadcast/action/", admin_views.admin_broadcast_action, name="admin_broadcast_action"),
    path("ops/admin/sync-roles/", admin_views.admin_sync_roles, name="admin_sync_roles"),
    path("ops/admin/sync-roles/action/", admin_views.admin_sync_roles_action, name="admin_sync_roles_action"),
    path("ops/admin/task/<int:task_id>/status/", admin_views.admin_task_status, name="admin_task_status"),
    path("ops/admin/categories/", admin_views.admin_categories, name="admin_categories"),
    path("ops/admin/categories/create/", admin_views.admin_category_create, name="admin_category_create"),
    path(
        "ops/admin/categories/<int:category_id>/edit/",
        admin_views.admin_category_edit,
        name="admin_category_edit",
    ),
    path(
        "ops/admin/categories/<int:category_id>/delete/",
        admin_views.admin_category_delete,
        name="admin_category_delete",
    ),
]
