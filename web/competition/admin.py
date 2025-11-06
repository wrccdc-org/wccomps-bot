"""Admin configuration for competition app."""

from django.contrib import admin
from django.http import HttpRequest
from .models import Competition, CompetitionPhase


class CompetitionPhaseInline(admin.TabularInline):
    """Inline admin for competition phases."""

    model = CompetitionPhase
    extra = 0
    fields = [
        "phase_number",
        "name",
        "phase_type",
        "start_time",
        "end_time",
        "is_scored",
    ]
    ordering = ["phase_number"]


@admin.register(Competition)
class CompetitionAdmin(admin.ModelAdmin):
    """Admin interface for competitions."""

    list_display = [
        "name",
        "status",
        "scheduled_start_time",
        "scheduled_end_time",
        "elapsed_time_display",
        "team_count",
    ]
    list_filter = ["status", "ticketing_enabled", "scoring_enabled"]
    search_fields = ["name", "slug", "description"]
    readonly_fields = [
        "created_at",
        "updated_at",
        "created_by",
        "actual_start_time",
        "actual_end_time",
        "total_paused_duration",
        "elapsed_time_display",
        "remaining_time_display",
    ]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [CompetitionPhaseInline]

    fieldsets = (
        (
            "Identity",
            {
                "fields": (
                    "name",
                    "slug",
                    "description",
                )
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "status",
                    "elapsed_time_display",
                    "remaining_time_display",
                )
            },
        ),
        (
            "Schedule",
            {
                "fields": (
                    "scheduled_start_time",
                    "scheduled_end_time",
                    "actual_start_time",
                    "actual_end_time",
                )
            },
        ),
        (
            "Pause Tracking",
            {
                "fields": (
                    "paused_at",
                    "total_paused_duration",
                )
            },
        ),
        (
            "Configuration",
            {
                "fields": (
                    "team_count",
                    "ticketing_enabled",
                    "scoring_enabled",
                )
            },
        ),
        (
            "Integration",
            {
                "fields": (
                    "quotient_competition_id",
                    "discord_announcement_channel_id",
                )
            },
        ),
        (
            "Audit",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                    "created_by",
                )
            },
        ),
    )

    def elapsed_time_display(self, obj: Competition) -> str:
        """Display elapsed competition time."""
        elapsed = obj.get_elapsed_time()
        if elapsed:
            hours = int(elapsed.total_seconds() // 3600)
            minutes = int((elapsed.total_seconds() % 3600) // 60)
            return f"{hours}h {minutes}m"
        return "-"

    elapsed_time_display.short_description = "Elapsed Time"

    def remaining_time_display(self, obj: Competition) -> str:
        """Display remaining competition time."""
        remaining = obj.get_remaining_time()
        if remaining:
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            return f"{hours}h {minutes}m"
        return "-"

    remaining_time_display.short_description = "Remaining Time"

    def save_model(self, request: HttpRequest, obj: Competition, form, change):
        """Set created_by on first save."""
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    actions = [
        "start_competitions",
        "pause_competitions",
        "resume_competitions",
        "end_competitions",
    ]

    @admin.action(description="Start selected competitions")
    def start_competitions(self, request: HttpRequest, queryset):
        """Start competitions (upcoming -> active)."""
        count = 0
        for competition in queryset.filter(status="upcoming"):
            competition.start_competition()
            count += 1
        self.message_user(request, f"Started {count} competition(s)")

    @admin.action(description="Pause selected competitions")
    def pause_competitions(self, request: HttpRequest, queryset):
        """Pause active competitions."""
        count = 0
        for competition in queryset.filter(status="active"):
            competition.pause_competition()
            count += 1
        self.message_user(request, f"Paused {count} competition(s)")

    @admin.action(description="Resume selected competitions")
    def resume_competitions(self, request: HttpRequest, queryset):
        """Resume paused competitions."""
        count = 0
        for competition in queryset.filter(status="paused"):
            competition.resume_competition()
            count += 1
        self.message_user(request, f"Resumed {count} competition(s)")

    @admin.action(description="End selected competitions")
    def end_competitions(self, request: HttpRequest, queryset):
        """End competitions (active/paused -> completed)."""
        count = 0
        for competition in queryset.filter(status__in=["active", "paused"]):
            competition.end_competition()
            count += 1
        self.message_user(request, f"Ended {count} competition(s)")


@admin.register(CompetitionPhase)
class CompetitionPhaseAdmin(admin.ModelAdmin):
    """Admin interface for competition phases."""

    list_display = [
        "competition",
        "phase_number",
        "name",
        "phase_type",
        "start_time",
        "end_time",
        "is_active_display",
    ]
    list_filter = ["phase_type", "is_scored", "competition"]
    search_fields = ["name", "description", "competition__name"]
    ordering = ["competition", "phase_number"]
    readonly_fields = ["created_at", "is_active_display"]

    fieldsets = (
        (
            "Phase Information",
            {
                "fields": (
                    "competition",
                    "phase_number",
                    "name",
                    "phase_type",
                )
            },
        ),
        (
            "Timing",
            {
                "fields": (
                    "start_time",
                    "end_time",
                    "is_active_display",
                )
            },
        ),
        (
            "Configuration",
            {
                "fields": (
                    "description",
                    "is_scored",
                )
            },
        ),
        (
            "Audit",
            {"fields": ("created_at",)},
        ),
    )

    def is_active_display(self, obj: CompetitionPhase) -> str:
        """Display if phase is currently active."""
        return "Yes" if obj.is_active() else "No"

    is_active_display.short_description = "Currently Active"
