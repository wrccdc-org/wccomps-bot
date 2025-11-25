"""Django admin configuration for scoring models."""

from django.contrib import admin
from django.utils.html import format_html

from .models import (
    BlackTeamAdjustment,
    FinalScore,
    IncidentReport,
    IncidentScreenshot,
    InjectGrade,
    OrangeTeamBonus,
    QuotientMetadataCache,
    RedTeamFinding,
    RedTeamScreenshot,
    ScoringTemplate,
    ServiceScore,
)


class RedTeamScreenshotInline(admin.TabularInline[RedTeamScreenshot, RedTeamFinding]):
    model = RedTeamScreenshot
    extra = 1
    fields = ["image", "description"]


@admin.register(RedTeamFinding)
class RedTeamFindingAdmin(admin.ModelAdmin[RedTeamFinding]):
    list_display = [
        "id",
        "attack_vector_short",
        "affected_box",
        "affected_service",
        "team_count",
        "points_per_team",
        "submitted_by",
        "created_at",
    ]
    list_filter = ["affected_box", "universally_attempted", "created_at"]
    search_fields = ["attack_vector", "affected_box", "affected_service"]
    filter_horizontal = ["affected_teams"]
    inlines = [RedTeamScreenshotInline]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = [
        ("Submitted By", {"fields": ["submitted_by"]}),
        (
            "Attack Details",
            {
                "fields": [
                    "attack_vector",
                    "source_ip",
                    "destination_ip_template",
                    "affected_box",
                    "affected_service",
                ]
            },
        ),
        (
            "Flags",
            {"fields": ["universally_attempted", "persistence_established"]},
        ),
        (
            "Scoring",
            {"fields": ["affected_teams", "points_per_team"]},
        ),
        ("Evidence", {"fields": ["notes"]}),
        ("Audit", {"fields": ["created_at", "updated_at"]}),
    ]

    @admin.display(description="Attack")
    def attack_vector_short(self, obj: RedTeamFinding) -> str:
        return obj.attack_vector[:50] + "..." if len(obj.attack_vector) > 50 else obj.attack_vector

    @admin.display(description="Teams")
    def team_count(self, obj: RedTeamFinding) -> int:
        return obj.affected_teams.count()


class IncidentScreenshotInline(admin.TabularInline[IncidentScreenshot, IncidentReport]):
    model = IncidentScreenshot
    extra = 1
    fields = ["image", "description"]


@admin.register(IncidentReport)
class IncidentReportAdmin(admin.ModelAdmin[IncidentReport]):
    list_display = [
        "id",
        "team",
        "attack_description_short",
        "affected_box",
        "affected_service",
        "attack_detected_at",
        "reviewed_status",
        "points_returned",
        "created_at",
    ]
    list_filter = [
        "team",
        "gold_team_reviewed",
        "attack_mitigated",
        "attack_detected_at",
    ]
    search_fields = ["attack_description", "affected_box", "affected_service", "team__team_name"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [IncidentScreenshotInline]

    fieldsets = [
        ("Report Info", {"fields": ["team", "submitted_by"]}),
        (
            "Attack Details",
            {
                "fields": [
                    "attack_description",
                    "source_ip",
                    "destination_ip",
                    "affected_box",
                    "affected_service",
                ]
            },
        ),
        (
            "Timeline",
            {"fields": ["attack_detected_at", "attack_mitigated"]},
        ),
        ("Evidence", {"fields": ["evidence_notes"]}),
        (
            "Gold Team Review",
            {
                "fields": [
                    "gold_team_reviewed",
                    "matched_to_red_finding",
                    "points_returned",
                    "reviewer_notes",
                    "reviewed_by",
                    "reviewed_at",
                ]
            },
        ),
        ("Audit", {"fields": ["created_at", "updated_at"]}),
    ]

    @admin.display(description="Description")
    def attack_description_short(self, obj: IncidentReport) -> str:
        return obj.attack_description[:50] + "..." if len(obj.attack_description) > 50 else obj.attack_description

    @admin.display(description="Status")
    def reviewed_status(self, obj: IncidentReport) -> str:
        if obj.gold_team_reviewed:
            return format_html('<span style="color: green;">✓ Reviewed</span>')
        return format_html('<span style="color: orange;">Pending</span>')


@admin.register(InjectGrade)
class InjectGradeAdmin(admin.ModelAdmin[InjectGrade]):
    list_display = [
        "team",
        "inject_name",
        "points_awarded",
        "max_points",
        "percentage",
        "graded_by",
        "graded_at",
    ]
    list_filter = ["inject_name", "graded_at"]
    search_fields = ["team__team_name", "inject_name", "inject_id"]
    readonly_fields = ["graded_at", "updated_at"]

    fieldsets = [
        ("Team", {"fields": ["team"]}),
        ("Inject", {"fields": ["inject_id", "inject_name", "max_points"]}),
        ("Grading", {"fields": ["points_awarded", "notes"]}),
        ("Audit", {"fields": ["graded_by", "graded_at", "updated_at"]}),
    ]

    @admin.display(description="%")
    def percentage(self, obj: InjectGrade) -> str:
        if obj.max_points > 0:
            pct = (obj.points_awarded / obj.max_points) * 100
            color = "green" if pct >= 80 else "orange" if pct >= 60 else "red"
            return format_html(f'<span style="color: {color};">{pct:.1f}%</span>')
        return "N/A"


@admin.register(OrangeTeamBonus)
class OrangeTeamBonusAdmin(admin.ModelAdmin[OrangeTeamBonus]):
    list_display = [
        "team",
        "description_short",
        "points_awarded",
        "submitted_by",
        "created_at",
    ]
    list_filter = ["created_at"]
    search_fields = ["team__team_name", "description"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Description")
    def description_short(self, obj: OrangeTeamBonus) -> str:
        return obj.description[:50] + "..." if len(obj.description) > 50 else obj.description


@admin.register(ServiceScore)
class ServiceScoreAdmin(admin.ModelAdmin[ServiceScore]):
    list_display = [
        "team",
        "service_points",
        "sla_violations",
        "net_score",
        "synced_at",
        "synced_by",
    ]
    list_filter = ["synced_at"]
    search_fields = ["team__team_name"]
    readonly_fields = ["synced_at"]

    @admin.display(description="Net")
    def net_score(self, obj: ServiceScore) -> str:
        total = obj.service_points + obj.sla_violations
        color = "green" if total > 0 else "red" if total < 0 else "black"
        return format_html(f'<span style="color: {color};">{total:.2f}</span>')


@admin.register(BlackTeamAdjustment)
class BlackTeamAdjustmentAdmin(admin.ModelAdmin[BlackTeamAdjustment]):
    list_display = [
        "team",
        "reason_short",
        "point_adjustment",
        "submitted_by",
        "created_at",
    ]
    list_filter = ["created_at"]
    search_fields = ["team__team_name", "reason"]
    readonly_fields = ["created_at", "updated_at"]

    @admin.display(description="Reason")
    def reason_short(self, obj: BlackTeamAdjustment) -> str:
        return obj.reason[:50] + "..." if len(obj.reason) > 50 else obj.reason


@admin.register(FinalScore)
class FinalScoreAdmin(admin.ModelAdmin[FinalScore]):
    list_display = [
        "rank",
        "team",
        "total_score",
        "service_points",
        "inject_points",
        "orange_points",
        "red_deductions",
        "incident_recovery_points",
        "calculated_at",
    ]
    list_filter = ["calculated_at"]
    search_fields = ["team__team_name"]
    readonly_fields = ["calculated_at"]
    ordering = ["rank"]


@admin.register(ScoringTemplate)
class ScoringTemplateAdmin(admin.ModelAdmin[ScoringTemplate]):
    list_display = [
        "inject_multiplier",
        "orange_multiplier",
        "updated_at",
    ]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = [
        (
            "Multipliers",
            {
                "fields": [
                    "inject_multiplier",
                    "orange_multiplier",
                ]
            },
        ),
        ("Audit", {"fields": ["updated_by", "created_at", "updated_at"]}),
    ]


@admin.register(QuotientMetadataCache)
class QuotientMetadataCacheAdmin(admin.ModelAdmin[QuotientMetadataCache]):
    list_display = ["event_name", "team_count", "last_synced", "synced_by"]
    readonly_fields = ["last_synced"]
    search_fields = ["event_name"]
