"""Django admin configuration for scoring models."""

from django.contrib import admin
from django.utils.html import format_html

from .models import (
    AttackType,
    BlackTeamAdjustment,
    FinalScore,
    IncidentReport,
    IncidentScreenshot,
    InjectGrade,
    OrangeCheckType,
    OrangeTeamBonus,
    QuotientMetadataCache,
    RedTeamFinding,
    RedTeamIPPool,
    RedTeamScreenshot,
    ScoringTemplate,
    ServiceScore,
)


@admin.register(AttackType)
class AttackTypeAdmin(admin.ModelAdmin[AttackType]):
    list_display = ["name", "description_short", "is_active", "findings_count", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "description"]
    readonly_fields = ["created_at"]
    ordering = ["name"]

    @admin.display(description="Description")
    def description_short(self, obj: AttackType) -> str:
        return obj.description[:50] + "..." if len(obj.description) > 50 else obj.description

    @admin.display(description="Findings")
    def findings_count(self, obj: AttackType) -> int:
        return obj.findings.count()


class RedTeamScreenshotInline(admin.TabularInline[RedTeamScreenshot, RedTeamFinding]):
    model = RedTeamScreenshot
    extra = 1
    fields = ["image", "description"]


@admin.register(RedTeamFinding)
class RedTeamFindingAdmin(admin.ModelAdmin[RedTeamFinding]):
    list_display = [
        "id",
        "attack_type",
        "affected_boxes_display",
        "affected_service",
        "team_count",
        "contributors_count",
        "points_per_team",
        "submitted_by",
        "created_at",
    ]
    list_filter = ["attack_type", "universally_attempted", "is_approved", "created_at"]
    search_fields = ["attack_type__name", "affected_service", "notes"]
    autocomplete_fields = ["attack_type"]

    @admin.display(description="Boxes")
    def affected_boxes_display(self, obj: RedTeamFinding) -> str:
        if obj.affected_boxes:
            boxes = obj.affected_boxes[:3]
            suffix = "..." if len(obj.affected_boxes) > 3 else ""
            return ", ".join(boxes) + suffix
        return "—"

    filter_horizontal = ["affected_teams", "contributors"]
    inlines = [RedTeamScreenshotInline]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = [
        ("Submitted By", {"fields": ["submitted_by", "contributors"]}),
        (
            "Attack Details",
            {
                "fields": [
                    "attack_type",
                    "attack_vector",
                    "source_ip",
                    "source_ip_pool",
                    "destination_ip_template",
                    "affected_boxes",
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
            {"fields": ["affected_teams", "points_per_team", "is_approved", "approved_by", "approved_at"]},
        ),
        ("Evidence", {"fields": ["notes"]}),
        ("Audit", {"fields": ["created_at", "updated_at"]}),
    ]

    @admin.display(description="Teams")
    def team_count(self, obj: RedTeamFinding) -> int:
        return obj.affected_teams.count()

    @admin.display(description="Contributors")
    def contributors_count(self, obj: RedTeamFinding) -> int:
        return obj.contributors.count()


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
        "affected_boxes_display",
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
    search_fields = ["attack_description", "affected_service", "team__team_name"]
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
                    "affected_boxes",
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

    @admin.display(description="Affected Boxes")
    def affected_boxes_display(self, obj: IncidentReport) -> str:
        if obj.affected_boxes:
            boxes = obj.affected_boxes[:3]
            suffix = "..." if len(obj.affected_boxes) > 3 else ""
            return ", ".join(boxes) + suffix
        return "—"

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
        if obj.max_points and obj.max_points > 0:
            pct = (obj.points_awarded / obj.max_points) * 100
            color = "green" if pct >= 80 else "orange" if pct >= 60 else "red"
            return format_html(f'<span style="color: {color};">{pct:.1f}%</span>')
        return "N/A"


@admin.register(OrangeCheckType)
class OrangeCheckTypeAdmin(admin.ModelAdmin[OrangeCheckType]):
    list_display = ["name", "default_points", "created_at"]
    search_fields = ["name"]
    readonly_fields = ["created_at"]


@admin.register(OrangeTeamBonus)
class OrangeTeamBonusAdmin(admin.ModelAdmin[OrangeTeamBonus]):
    list_display = [
        "team",
        "check_type",
        "description_short",
        "points_awarded",
        "submitted_by",
        "created_at",
    ]
    list_filter = ["check_type", "created_at"]
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
        "service_weight",
        "inject_weight",
        "orange_weight",
        "red_weight",
        "weights_total",
        "updated_at",
    ]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = [
        (
            "Category Weights (must sum to 100%)",
            {
                "fields": [
                    "service_weight",
                    "inject_weight",
                    "orange_weight",
                    "red_weight",
                ],
                "description": "Service includes SLA penalties. Red includes recovery points.",
            },
        ),
        (
            "Max Points (for normalization)",
            {
                "fields": [
                    "service_max",
                    "inject_max",
                    "orange_max",
                    "red_max",
                ]
            },
        ),
        ("Audit", {"fields": ["updated_by", "created_at", "updated_at"]}),
    ]

    @admin.display(description="Total")
    def weights_total(self, obj: ScoringTemplate) -> str:
        total = obj.service_weight + obj.inject_weight + obj.orange_weight + obj.red_weight
        color = "green" if total == 100 else "red"
        return format_html(f'<span style="color: {color};">{total}%</span>')


@admin.register(QuotientMetadataCache)
class QuotientMetadataCacheAdmin(admin.ModelAdmin[QuotientMetadataCache]):
    list_display = ["event_name", "team_count", "last_synced", "synced_by"]
    readonly_fields = ["last_synced"]
    search_fields = ["event_name"]


@admin.register(RedTeamIPPool)
class RedTeamIPPoolAdmin(admin.ModelAdmin[RedTeamIPPool]):
    list_display = ["name", "ip_count", "findings_count", "created_by", "created_at"]
    search_fields = ["name", "created_by__username"]
    readonly_fields = ["created_at", "updated_at"]
    list_filter = ["created_by", "created_at"]

    @admin.display(description="IPs")
    def ip_count(self, obj: RedTeamIPPool) -> int:
        return obj.ip_count

    @admin.display(description="Findings")
    def findings_count(self, obj: RedTeamIPPool) -> int:
        return obj.findings.count()
