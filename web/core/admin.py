"""Django admin configuration for WCComps."""

from __future__ import annotations
from typing import TYPE_CHECKING, Any
from django.contrib import admin
from django.contrib.auth.models import Group
from django.http import HttpRequest, HttpResponse
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialToken, SocialApp
from .models import (
    Team,
    DiscordLink,
    LinkToken,
    LinkAttempt,
    AuditLog,
    Ticket,
    TicketAttachment,
    TicketComment,
    TicketHistory,
    DiscordTask,
    BotState,
    DashboardUpdate,
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
# CORE COMPETITION MANAGEMENT
# These models are the primary interface for managing teams and competitions
# ============================================================================


@admin.register(Team)
class TeamAdmin(BaseModelAdmin):
    list_display = [
        "team_number",
        "team_name",
        "get_member_count",
        "max_members",
        "is_active",
    ]
    list_filter = ["is_active"]
    search_fields = ["team_number", "team_name", "authentik_group"]
    ordering = ["team_number"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Members")
    def get_member_count(self, obj: Team) -> int:
        return obj.get_member_count()


# ============================================================================
# TEAM MEMBER LINKING
# Manage Discord account linkages to Authentik/teams
# ============================================================================


@admin.register(DiscordLink)
class DiscordLinkAdmin(BaseModelAdmin):
    list_display = [
        "discord_username",
        "team",
        "authentik_username",
        "is_active",
        "linked_at",
    ]
    list_filter = ["is_active", "team"]
    search_fields = ["discord_username", "authentik_username", "discord_id"]
    ordering = ["-linked_at"]
    readonly_fields = ["linked_at", "unlinked_at"]


@admin.register(LinkToken)
class LinkTokenAdmin(BaseModelAdmin):
    list_display = ["discord_username", "token", "used", "expires_at", "created_at"]
    list_filter = ["used"]
    search_fields = ["discord_username", "token"]
    ordering = ["-created_at"]
    readonly_fields = [
        "token",
        "discord_id",
        "discord_username",
        "used",
        "expires_at",
        "created_at",
    ]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False  # Created automatically by Discord bot

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False  # Read-only


@admin.register(LinkAttempt)
class LinkAttemptAdmin(BaseModelAdmin):
    list_display = [
        "discord_username",
        "authentik_username",
        "team",
        "success",
        "created_at",
    ]
    list_filter = ["success", "team"]
    search_fields = ["discord_username", "authentik_username"]
    ordering = ["-created_at"]
    readonly_fields = [
        "discord_id",
        "discord_username",
        "authentik_username",
        "team",
        "success",
        "failure_reason",
        "created_at",
    ]

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False  # Created automatically during linking

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False  # Read-only audit log


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
# TICKETING SYSTEM
# Manage support tickets, comments, and attachments
# ============================================================================


class TicketAttachmentInline(BaseTabularInline):
    model = TicketAttachment
    extra = 0
    readonly_fields = ["uploaded_at", "uploaded_by", "filename", "mime_type"]
    fields = ["filename", "mime_type", "uploaded_by", "uploaded_at"]


class TicketCommentInline(BaseTabularInline):
    model = TicketComment
    extra = 0
    readonly_fields = ["posted_at", "author_name"]
    fields = ["author_name", "comment_text", "posted_at"]


class TicketHistoryInline(BaseTabularInline):
    model = TicketHistory
    extra = 0
    readonly_fields = ["timestamp", "action", "actor_username"]
    fields = ["action", "actor_username", "details", "timestamp"]


@admin.register(Ticket)
class TicketAdmin(BaseModelAdmin):
    list_display = [
        "ticket_number",
        "team",
        "category",
        "status",
        "assigned_to_discord_username",
        "points_charged",
        "created_at",
    ]
    list_filter = ["status", "category", "team"]
    search_fields = ["ticket_number", "title", "hostname", "service_name"]
    ordering = ["-created_at"]
    readonly_fields = ["ticket_number", "created_at", "updated_at"]
    inlines = [TicketAttachmentInline, TicketCommentInline, TicketHistoryInline]
    actions = ["export_as_csv"]

    fieldsets = (
        ("Identity", {"fields": ("ticket_number", "team", "status")}),
        (
            "Content",
            {
                "fields": (
                    "category",
                    "title",
                    "description",
                    "hostname",
                    "ip_address",
                    "service_name",
                    "custom_fields",
                )
            },
        ),
        (
            "Assignment",
            {
                "fields": (
                    "assigned_to_discord_id",
                    "assigned_to_discord_username",
                    "assigned_to_authentik_username",
                    "assigned_to_authentik_user_id",
                    "assigned_at",
                )
            },
        ),
        (
            "Resolution",
            {
                "fields": (
                    "resolved_by_discord_id",
                    "resolved_by_discord_username",
                    "resolved_by_authentik_username",
                    "resolved_by_authentik_user_id",
                    "resolved_at",
                    "resolution_notes",
                    "duration_notes",
                    "points_charged",
                )
            },
        ),
        (
            "Discord",
            {
                "fields": (
                    "discord_thread_id",
                    "discord_channel_id",
                    "thread_archive_scheduled_at",
                )
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    @admin.action(description="Export selected tickets as CSV")
    def export_as_csv(self, request: HttpRequest, queryset: Any) -> HttpResponse:
        """Export selected tickets as CSV."""
        import csv

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="tickets.csv"'

        writer = csv.writer(response)
        writer.writerow(
            [
                "Ticket Number",
                "Team",
                "Team Number",
                "Category",
                "Title",
                "Description",
                "Status",
                "Hostname",
                "IP Address",
                "Service Name",
                "Assigned To",
                "Points Charged",
                "Created At",
                "Resolved At",
                "Resolution Notes",
                "Duration Notes",
            ]
        )

        for ticket in queryset:
            writer.writerow(
                [
                    ticket.ticket_number,
                    ticket.team.team_name,
                    ticket.team.team_number,
                    ticket.category,
                    ticket.title,
                    ticket.description,
                    ticket.status,
                    ticket.hostname or "",
                    ticket.ip_address or "",
                    ticket.service_name or "",
                    ticket.assigned_to_discord_username or "",
                    ticket.points_charged,
                    ticket.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    ticket.resolved_at.strftime("%Y-%m-%d %H:%M:%S")
                    if ticket.resolved_at
                    else "",
                    ticket.resolution_notes or "",
                    ticket.duration_notes or "",
                ]
            )

        return response


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(BaseModelAdmin):
    list_display = ["filename", "ticket", "uploaded_by", "uploaded_at"]
    list_filter = ["uploaded_at"]
    search_fields = ["filename", "ticket__ticket_number"]
    ordering = ["-uploaded_at"]
    readonly_fields = ["uploaded_at"]


@admin.register(TicketComment)
class TicketCommentAdmin(BaseModelAdmin):
    list_display = ["ticket", "author_name", "posted_at"]
    list_filter = ["posted_at"]
    search_fields = ["ticket__ticket_number", "author_name", "comment_text"]
    ordering = ["-posted_at"]
    readonly_fields = ["posted_at"]


@admin.register(TicketHistory)
class TicketHistoryAdmin(BaseModelAdmin):
    list_display = ["ticket", "action", "actor_username", "timestamp"]
    list_filter = ["action", "timestamp"]
    search_fields = ["ticket__ticket_number", "actor_username"]
    ordering = ["-timestamp"]
    readonly_fields = ["timestamp"]


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
