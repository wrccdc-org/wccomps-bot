"""Django admin configuration for WCComps."""

from __future__ import annotations
from typing import TYPE_CHECKING, Any
from django.contrib import admin
from django.contrib.auth.models import Group
from django.http import HttpRequest
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialToken, SocialApp

# Team, DiscordLink, LinkToken, LinkAttempt moved to team.admin
# Ticket, TicketAttachment, TicketComment, TicketHistory moved to ticketing.admin
from .models import (
    AuditLog,
    DiscordTask,
    BotState,
    DashboardUpdate,
    CompetitionConfig,
)

if TYPE_CHECKING:
    from django.contrib.admin import ModelAdmin, TabularInline

    BaseModelAdmin = ModelAdmin[Any]
    BaseTabularInline = TabularInline[Any, Any]
else:
    BaseModelAdmin = admin.ModelAdmin
    BaseTabularInline = admin.TabularInline

# Customize admin site
admin.site.site_header = "WCComps Administration"
admin.site.site_title = "WCComps Admin"
admin.site.index_title = "Competition Management"

# Unregister unnecessary admin models
admin.site.unregister(Group)  # Managed via Authentik
admin.site.unregister(EmailAddress)  # Not using email auth
admin.site.unregister(SocialAccount)  # Internal OAuth data
admin.site.unregister(SocialToken)  # Internal OAuth tokens
admin.site.unregister(SocialApp)  # Configured via settings


# ============================================================================
# TEAM MANAGEMENT MOVED TO team.admin
# Team, DiscordLink, LinkToken, LinkAttempt, SchoolInfo now managed in team app
# ============================================================================


# ============================================================================
# AUDIT & DEBUGGING (Read-only)
# These models provide audit trails and debugging info
# ============================================================================


@admin.register(AuditLog)
class AuditLogAdmin(BaseModelAdmin):
    list_display = ["action", "admin_user", "target_entity", "target_id", "created_at"]
    list_filter = ["action", "target_entity"]
    search_fields = ["admin_user", "action"]
    ordering = ["-created_at"]
    readonly_fields = ["created_at"]


# ============================================================================
# TICKETING SYSTEM MOVED TO ticketing.admin
# Ticket, TicketAttachment, TicketComment, TicketHistory now managed in ticketing app
# ============================================================================


# ============================================================================
# SYSTEM INTERNALS (Limited access)
# Background tasks and bot state - mostly read-only
# ============================================================================


@admin.register(DiscordTask)
class DiscordTaskAdmin(BaseModelAdmin):
    list_display = ["task_type", "status", "retry_count", "created_at", "completed_at"]
    list_filter = ["status", "task_type"]
    search_fields = ["task_type", "error_message"]
    ordering = ["-created_at"]
    readonly_fields = ["created_at", "completed_at"]

    actions = ["retry_failed_tasks"]

    @admin.action(description="Retry failed tasks")
    def retry_failed_tasks(self, request: HttpRequest, queryset: Any) -> None:
        from django.utils import timezone

        updated = queryset.filter(status="failed").update(
            status="pending",
            retry_count=0,
            next_retry_at=timezone.now(),
            error_message="",
        )
        self.message_user(request, f"{updated} tasks reset for retry")


@admin.register(BotState)
class BotStateAdmin(BaseModelAdmin):
    list_display = ["key", "value", "updated_at"]
    search_fields = ["key", "value"]
    ordering = ["key"]
    readonly_fields = ["key", "value", "updated_at"]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False  # Managed by Discord bot

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False  # Internal bot state


@admin.register(DashboardUpdate)
class DashboardUpdateAdmin(BaseModelAdmin):
    list_display = ["needs_update", "last_updated", "update_scheduled_at"]
    readonly_fields = ["needs_update", "last_updated", "update_scheduled_at"]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False  # Singleton managed by system

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False  # System singleton


@admin.register(CompetitionConfig)
class CompetitionConfigAdmin(BaseModelAdmin):
    list_display = [
        "competition_status",
        "competition_start_time",
        "competition_end_time",
        "applications_enabled",
        "max_team_members",
    ]
    readonly_fields = ["created_at", "updated_at", "last_check", "applications_enabled"]

    fieldsets = (
        (
            "Competition Timing",
            {
                "fields": (
                    "competition_start_time",
                    "competition_end_time",
                    "applications_enabled",
                ),
                "description": "Set start/end times for automatic application enable/disable. "
                "Applications will be automatically enabled at start time and disabled at end time.",
            },
        ),
        (
            "Application Control",
            {
                "fields": ("controlled_applications",),
                "description": "List of Authentik application slugs to control (e.g., ['netbird', 'scoring']). "
                "These applications will be enabled/disabled based on competition timing.",
            },
        ),
        (
            "Team Settings",
            {
                "fields": ("max_team_members",),
                "description": "Maximum number of members allowed per team.",
            },
        ),
        (
            "System Info",
            {
                "fields": ("created_at", "updated_at", "last_check"),
                "description": "Audit and system information.",
            },
        ),
    )

    @admin.display(description="Status")
    def competition_status(self, obj: CompetitionConfig) -> str:
        """Display current competition status."""
        from django.utils import timezone

        if obj.applications_enabled:
            return "Active"
        elif obj.competition_start_time and timezone.now() < obj.competition_start_time:
            return "Scheduled"
        elif obj.competition_end_time and timezone.now() > obj.competition_end_time:
            return "Ended"
        else:
            return "Not Scheduled"

    def has_add_permission(self, request: HttpRequest) -> bool:
        # Only allow creation if no config exists
        return not CompetitionConfig.objects.exists()

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False  # Singleton - never delete
