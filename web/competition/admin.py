"""Admin configuration for competition app."""

from django.contrib import admin
from django.utils.html import format_html

from competition.models import Competition, StudentHelper


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Admin interface for Competition model."""

    list_display = [
        "name",
        "slug",
        "status",
        "scheduled_start_time",
        "scheduled_end_time",
        "team_count",
        "ticketing_enabled",
        "scoring_enabled",
    ]
    list_filter = ["status", "ticketing_enabled", "scoring_enabled"]
    search_fields = ["name", "slug", "description"]
    readonly_fields = ["created_at", "updated_at", "actual_start_time", "actual_end_time", "paused_at"]
    fieldsets = [
        (
            "Basic Information",
            {
                "fields": ["name", "slug", "description", "status"],
            },
        ),
        (
            "Timing",
            {
                "fields": [
                    "scheduled_start_time",
                    "scheduled_end_time",
                    "actual_start_time",
                    "actual_end_time",
                    "paused_at",
                    "total_paused_duration",
                ],
            },
        ),
        (
            "Configuration",
            {
                "fields": ["team_count", "ticketing_enabled", "scoring_enabled"],
            },
        ),
        (
            "Integration",
            {
                "fields": ["quotient_competition_id", "discord_announcement_channel_id"],
            },
        ),
        (
            "Audit",
            {
                "fields": ["created_at", "updated_at", "created_by"],
            },
        ),
    ]


@admin.register(StudentHelper)
class StudentHelperAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Admin interface for StudentHelper model."""

    list_display = [
        "authentik_username",
        "discord_username",
        "competition",
        "discord_role_name",
        "status_badge",
        "get_start_time",
        "get_end_time",
        "created_at",
    ]
    list_filter = ["status", "competition", "created_at"]
    search_fields = ["authentik_username", "discord_username", "discord_role_name", "competition__name"]
    readonly_fields = [
        "discord_id",
        "discord_username",
        "authentik_username",
        "activated_at",
        "deactivated_at",
        "created_at",
        "updated_at",
    ]
    autocomplete_fields = ["person", "competition"]
    fieldsets = [
        (
            "Helper Identity",
            {
                "fields": ["person", "discord_id", "discord_username", "authentik_username"],
            },
        ),
        (
            "Assignment",
            {
                "fields": ["competition", "discord_role_name", "discord_role_id", "status"],
            },
        ),
        (
            "Time Configuration",
            {
                "fields": ["custom_start_time", "custom_end_time"],
                "description": "Leave blank to use competition start/end times",
            },
        ),
        (
            "Lifecycle",
            {
                "fields": ["activated_at", "deactivated_at"],
            },
        ),
        (
            "Revocation",
            {
                "fields": ["revoked_by", "revoke_reason"],
            },
        ),
        (
            "Audit",
            {
                "fields": ["created_at", "updated_at", "created_by"],
            },
        ),
    ]

    def status_badge(self, obj):  # type: ignore[no-untyped-def]
        """Display status with color badge."""
        colors = {
            "pending": "#FFA500",  # Orange
            "active": "#28A745",  # Green
            "expired": "#6C757D",  # Gray
            "revoked": "#DC3545",  # Red
        }
        color = colors.get(obj.status, "#6C757D")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_badge.short_description = "Status"  # type: ignore[attr-defined]

    def save_model(self, request, obj, form, change):  # type: ignore[no-untyped-def]
        """Auto-populate cached fields from Person on save."""
        if not change or not obj.discord_id:  # New object or missing cached fields
            obj.discord_id = obj.person.discord_id
            obj.discord_username = obj.person.discord_username
            obj.authentik_username = obj.person.authentik_username

        if not change:  # New object
            obj.created_by = request.user

        super().save_model(request, obj, form, change)
