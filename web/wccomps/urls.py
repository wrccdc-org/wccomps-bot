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

import os

from django.contrib import admin
from django.urls import include, path

from core import views

# Check if ticketing is enabled (default: False, using external system)
TICKETING_ENABLED = os.environ.get("TICKETING_ENABLED", "false").lower() == "true"

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health_check, name="health_check"),
    path("admin/", admin.site.urls),
    path("accounts/logout/", views.custom_logout, name="account_logout"),
    path("accounts/", include("allauth.urls")),
    path("auth/link", views.link_initiate, name="link_initiate"),
    path("auth/callback", views.link_callback, name="link_callback"),
    path("ops/school-info/", views.ops_school_info, name="ops_school_info"),
    path(
        "ops/school-info/<int:team_number>/",
        views.ops_school_info_edit,
        name="ops_school_info_edit",
    ),
    path(
        "ops/group-role-mappings/",
        views.ops_group_role_mappings,
        name="ops_group_role_mappings",
    ),
]

# Add ticket routes only if enabled
if TICKETING_ENABLED:
    urlpatterns += [
        path("tickets/", views.team_tickets, name="team_tickets"),
        path("tickets/create/", views.create_ticket, name="create_ticket"),
        path("tickets/<int:ticket_id>/", views.ticket_detail, name="ticket_detail"),
        path(
            "tickets/<int:ticket_id>/comment/",
            views.ticket_comment,
            name="ticket_comment",
        ),
        path("tickets/<int:ticket_id>/cancel/", views.ticket_cancel, name="ticket_cancel"),
        path(
            "tickets/<int:ticket_id>/attachment/upload/",
            views.ticket_attachment_upload,
            name="ticket_attachment_upload",
        ),
        path(
            "tickets/<int:ticket_id>/attachment/<int:attachment_id>/",
            views.ticket_attachment_download,
            name="ticket_attachment_download",
        ),
        path("ops/tickets/", views.ops_ticket_list, name="ops_ticket_list"),
        path(
            "ops/tickets/bulk-claim/",
            views.ops_tickets_bulk_claim,
            name="ops_tickets_bulk_claim",
        ),
        path(
            "ops/tickets/bulk-resolve/",
            views.ops_tickets_bulk_resolve,
            name="ops_tickets_bulk_resolve",
        ),
        path(
            "ops/ticket/<str:ticket_number>/",
            views.ops_ticket_detail,
            name="ops_ticket_detail",
        ),
        path(
            "ops/ticket/<str:ticket_number>/comment/",
            views.ops_ticket_comment,
            name="ops_ticket_comment",
        ),
        path(
            "ops/ticket/<str:ticket_number>/claim/",
            views.ops_ticket_claim,
            name="ops_ticket_claim",
        ),
        path(
            "ops/ticket/<str:ticket_number>/unclaim/",
            views.ops_ticket_unclaim,
            name="ops_ticket_unclaim",
        ),
        path(
            "ops/ticket/<str:ticket_number>/resolve/",
            views.ops_ticket_resolve,
            name="ops_ticket_resolve",
        ),
        path(
            "ops/ticket/<str:ticket_number>/reopen/",
            views.ops_ticket_reopen,
            name="ops_ticket_reopen",
        ),
        path(
            "ops/ticket/<str:ticket_number>/change-category/",
            views.ops_ticket_change_category,
            name="ops_ticket_change_category",
        ),
        path(
            "ops/ticket/<str:ticket_number>/attachment/upload/",
            views.ops_ticket_attachment_upload,
            name="ops_ticket_attachment_upload",
        ),
        path(
            "ops/ticket/<str:ticket_number>/attachment/<int:attachment_id>/",
            views.ops_ticket_attachment_download,
            name="ops_ticket_attachment_download",
        ),
    ]
