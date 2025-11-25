"""Scoring system models for CCDC competitions."""

from decimal import Decimal
from typing import Any

from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


def validate_file_size(file: Any) -> Any:
    """Validate that uploaded file is not larger than 50MB."""
    max_size_mb = 50
    if file.size > max_size_mb * 1024 * 1024:
        from django.core.exceptions import ValidationError

        raise ValidationError(f"File size cannot exceed {max_size_mb}MB")
    return file


class ScoringTemplate(models.Model):
    """Scoring configuration for a competition."""

    # Score multipliers
    service_multiplier = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Multiplier applied to service scores (e.g., 1.0 = 100%)",
    )
    inject_multiplier = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.4"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Multiplier applied to inject scores (e.g., 1.4 = 140%)",
    )
    orange_multiplier = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("5.5"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Multiplier applied to orange team scores (e.g., 5.5 = 550%)",
    )
    red_multiplier = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Multiplier applied to red team deductions (e.g., 1.0 = 100%)",
    )
    sla_multiplier = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Multiplier applied to SLA penalties (e.g., 1.0 = 100%)",
    )
    recovery_multiplier = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("1.0"),
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Multiplier applied to incident recovery points (e.g., 1.0 = 100%)",
    )

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scoring_template_updates",
    )

    class Meta:
        db_table = "scoring_template"
        verbose_name = "Scoring Template"
        verbose_name_plural = "Scoring Templates"

    def __str__(self) -> str:
        return "Scoring Template"


class QuotientMetadataCache(models.Model):
    """Cached metadata from Quotient for populating dropdowns."""

    # JSON fields for infrastructure data
    boxes = models.JSONField(
        default=list,
        help_text="List of boxes from Quotient metadata",
    )
    services = models.JSONField(
        default=list,
        help_text="List of services from Quotient metadata",
    )
    event_name = models.CharField(max_length=200, blank=True)
    team_count = models.IntegerField(default=0)

    # Sync tracking
    last_synced = models.DateTimeField(auto_now=True)
    synced_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "quotient_metadata_cache"
        verbose_name = "Quotient Metadata Cache"
        verbose_name_plural = "Quotient Metadata Caches"

    def __str__(self) -> str:
        return "Quotient Metadata Cache"


class RedTeamFinding(models.Model):
    """Red team vulnerability finding affecting one or more teams."""

    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="red_findings_submitted",
    )

    # Attack details
    attack_vector = models.TextField(help_text="Description of the attack/exploit")
    source_ip = models.GenericIPAddressField(help_text="Red team source IP")
    destination_ip_template = models.CharField(
        max_length=50,
        blank=True,
        help_text="IP template (e.g., 10.100.1X.22 where X is team number)",
    )

    # Affected infrastructure (from Quotient metadata)
    affected_box = models.CharField(max_length=100, blank=True)
    affected_service = models.CharField(max_length=100, blank=True)

    # Flags
    universally_attempted = models.BooleanField(
        default=False,
        help_text="Attack was attempted against all teams",
    )
    persistence_established = models.BooleanField(
        default=False,
        help_text="Persistence was established on target",
    )

    # Affected teams and scoring
    affected_teams = models.ManyToManyField(
        "team.Team",
        related_name="red_team_findings",
        help_text="Teams affected by this finding",
    )
    points_per_team = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Points deducted per affected team (assigned by Gold Team)",
    )

    # Evidence
    notes = models.TextField(blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "red_team_finding"
        verbose_name = "Red Team Finding"
        verbose_name_plural = "Red Team Findings"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"RF-{self.pk}: {self.attack_vector[:50]}"


class RedTeamScreenshot(models.Model):
    """Screenshots for red team findings."""

    finding = models.ForeignKey(
        RedTeamFinding,
        on_delete=models.CASCADE,
        related_name="screenshots",
    )
    image = models.ImageField(
        upload_to="scoring/red_team/%Y/%m/%d/",
        validators=[validate_file_size],
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "red_team_screenshot"
        ordering = ["uploaded_at"]

    def __str__(self) -> str:
        return f"Screenshot for {self.finding}"


class IncidentReport(models.Model):
    """Blue team incident report submission."""

    team = models.ForeignKey(
        "team.Team",
        on_delete=models.CASCADE,
        related_name="incident_reports",
        help_text="Team submitting the incident report",
    )
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="incidents_submitted",
    )

    # Attack details
    attack_description = models.TextField(help_text="Description of detected attack")
    source_ip = models.GenericIPAddressField(help_text="Attacker source IP")
    destination_ip = models.GenericIPAddressField(help_text="Victim IP (team's system)")

    # Affected infrastructure
    affected_box = models.CharField(max_length=100, blank=True)
    affected_service = models.CharField(max_length=100, blank=True)

    # Timeline
    attack_detected_at = models.DateTimeField(help_text="When the attack was detected")
    attack_mitigated = models.BooleanField(
        default=False,
        help_text="Attack was successfully mitigated",
    )

    # Evidence
    evidence_notes = models.TextField(blank=True)

    # Gold team review
    gold_team_reviewed = models.BooleanField(default=False)
    matched_to_red_finding = models.ForeignKey(
        RedTeamFinding,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matched_incident_reports",
        help_text="Red team finding this incident matched to",
    )
    points_returned = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Points awarded for detecting/reporting this incident",
    )
    reviewer_notes = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidents_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "incident_report"
        verbose_name = "Incident Report"
        verbose_name_plural = "Incident Reports"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["team"]),
            models.Index(fields=["gold_team_reviewed"]),
        ]

    def __str__(self) -> str:
        return f"IR-{self.pk}: {self.team.team_name} - {self.attack_description[:50]}"


class IncidentScreenshot(models.Model):
    """Screenshots for incident reports."""

    incident = models.ForeignKey(
        IncidentReport,
        on_delete=models.CASCADE,
        related_name="screenshots",
    )
    image = models.ImageField(
        upload_to="scoring/incidents/%Y/%m/%d/",
        validators=[validate_file_size],
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "incident_screenshot"
        ordering = ["uploaded_at"]

    def __str__(self) -> str:
        return f"Screenshot for {self.incident}"


class InjectGrade(models.Model):
    """White/Gold team grading of inject submissions."""

    team = models.ForeignKey(
        "team.Team",
        on_delete=models.CASCADE,
        related_name="inject_grades",
    )

    # Inject info (inject definitions come from Quotient)
    inject_id = models.CharField(max_length=100, help_text="Quotient inject ID")
    inject_name = models.CharField(max_length=200)
    max_points = models.DecimalField(max_digits=10, decimal_places=2)

    # Grading
    points_awarded = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    notes = models.TextField(blank=True, help_text="Grader notes")

    # Audit
    graded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="injects_graded",
    )
    graded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "inject_grade"
        verbose_name = "Inject Grade"
        verbose_name_plural = "Inject Grades"
        unique_together = [["team", "inject_id"]]
        ordering = ["inject_name", "team__team_number"]

    def __str__(self) -> str:
        return f"{self.team.team_name} - {self.inject_name}: {self.points_awarded}/{self.max_points}"


class OrangeTeamBonus(models.Model):
    """Orange team point adjustments for customer service evaluation (positive or negative)."""

    team = models.ForeignKey(
        "team.Team",
        on_delete=models.CASCADE,
        related_name="orange_team_bonuses",
    )
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="orange_bonuses_submitted",
    )

    # Point adjustment details
    description = models.TextField(help_text="Description of why points are adjusted (positive or negative)")
    points_awarded = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Points to add (positive) or deduct (negative)",
    )

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "orange_team_bonus"
        verbose_name = "Orange Team Adjustment"
        verbose_name_plural = "Orange Team Adjustments"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        sign = "+" if self.points_awarded >= 0 else ""
        return f"{self.team.team_name} - {self.description[:50]}: {sign}{self.points_awarded}"


class ServiceScore(models.Model):
    """Service uptime scores from Quotient."""

    team = models.ForeignKey(
        "team.Team",
        on_delete=models.CASCADE,
        related_name="service_scores",
    )

    # Scores from Quotient
    service_points = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0"),
    )
    sla_violations = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0"),
        help_text="SLA penalty points (stored as negative)",
    )

    # Sync tracking
    synced_at = models.DateTimeField(auto_now=True)
    synced_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "service_score"
        verbose_name = "Service Score"
        verbose_name_plural = "Service Scores"
        unique_together = [["team"]]
        ordering = ["team__team_number"]

    def __str__(self) -> str:
        return f"{self.team.team_name}: {self.service_points} (SLA: {self.sla_violations})"


class BlackTeamAdjustment(models.Model):
    """Manual point adjustments by admin/black team."""

    team = models.ForeignKey(
        "team.Team",
        on_delete=models.CASCADE,
        related_name="black_team_adjustments",
    )
    submitted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="black_adjustments_submitted",
    )

    # Adjustment details
    reason = models.TextField(help_text="Reason for point adjustment")
    point_adjustment = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Point adjustment (positive or negative)",
    )

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "black_team_adjustment"
        verbose_name = "Black Team Adjustment"
        verbose_name_plural = "Black Team Adjustments"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.team.team_name}: {self.point_adjustment:+.2f} - {self.reason[:50]}"


class FinalScore(models.Model):
    """Calculated final scores for leaderboard."""

    team = models.ForeignKey(
        "team.Team",
        on_delete=models.CASCADE,
        related_name="final_scores",
    )

    # Component scores
    service_points = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    inject_points = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    orange_points = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    red_deductions = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    incident_recovery_points = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    sla_penalties = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    black_adjustments = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))

    # Total and rank
    total_score = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    rank = models.IntegerField(null=True, blank=True)

    # Calculation tracking
    calculated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "final_score"
        verbose_name = "Final Score"
        verbose_name_plural = "Final Scores"
        unique_together = [["team"]]
        ordering = ["-total_score", "team__team_number"]
        indexes = []

    def __str__(self) -> str:
        rank_str = f"#{self.rank}" if self.rank else "Unranked"
        return f"{rank_str} - {self.team.team_name}: {self.total_score}"
