"""Scoring system models for CCDC competitions."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import UploadedFile
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


def validate_file_size(file: UploadedFile) -> UploadedFile:
    """Validate that uploaded file is not larger than 50MB."""
    max_size_mb = 50
    if file.size and file.size > max_size_mb * 1024 * 1024:
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

    event = models.ForeignKey(
        "registration.Event",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="red_team_findings",
    )
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

    # Approval tracking
    is_approved = models.BooleanField(
        default=False,
        help_text="Whether this finding has been approved by Gold Team",
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this finding was approved",
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="red_findings_approved",
        help_text="Gold Team member who approved this finding",
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
    """Screenshots for red team findings (stored in database)."""

    finding = models.ForeignKey(
        RedTeamFinding,
        on_delete=models.CASCADE,
        related_name="screenshots",
    )
    file_data = models.BinaryField(null=True, blank=True)
    filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100, default="image/png")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "red_team_screenshot"
        ordering = ["uploaded_at"]

    @property
    def has_data(self) -> bool:
        """Check if file data exists (for legacy records without data)."""
        return bool(self.file_data)

    def __str__(self) -> str:
        return f"{self.filename} ({self.finding})"


class IncidentReport(models.Model):
    """Blue team incident report submission."""

    event = models.ForeignKey(
        "registration.Event",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="incident_reports",
    )
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
    attack_description = models.TextField()
    source_ip = models.GenericIPAddressField()
    destination_ip = models.GenericIPAddressField(null=True, blank=True)

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
    """Screenshots for incident reports (stored in database)."""

    incident = models.ForeignKey(
        IncidentReport,
        on_delete=models.CASCADE,
        related_name="screenshots",
    )
    file_data = models.BinaryField(null=True, blank=True)
    filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100, default="image/png")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "incident_screenshot"
        ordering = ["uploaded_at"]

    @property
    def has_data(self) -> bool:
        """Check if file data exists (for legacy records without data)."""
        return bool(self.file_data)

    def __str__(self) -> str:
        return f"{self.filename} ({self.incident})"


class InjectGrade(models.Model):
    """White/Gold team grading of inject submissions."""

    event = models.ForeignKey(
        "registration.Event",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="inject_grades",
    )
    team = models.ForeignKey(
        "team.Team",
        on_delete=models.CASCADE,
        related_name="inject_grades",
    )

    # Inject info (inject definitions come from Quotient)
    inject_id = models.CharField(max_length=100, help_text="Quotient inject ID")
    inject_name = models.CharField(max_length=200)
    max_points = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Grading
    points_awarded = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    notes = models.TextField(blank=True, help_text="Grader notes")

    # Approval tracking
    is_approved = models.BooleanField(
        default=False,
        help_text="Grade has been approved by supervisor",
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the grade was approved",
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="injects_approved",
        help_text="User who approved this grade",
    )

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
        if self.max_points:
            return f"{self.team.team_name} - {self.inject_name}: {self.points_awarded}/{self.max_points}"
        return f"{self.team.team_name} - {self.inject_name}: {self.points_awarded}"


class OrangeCheckType(models.Model):
    """Categories for orange team bonus/penalty checks."""

    name = models.CharField(max_length=100, unique=True)
    default_points = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Default point value when this check type is selected",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "orange_check_type"
        verbose_name = "Orange Check Type"
        verbose_name_plural = "Orange Check Types"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class OrangeTeamBonus(models.Model):
    """Orange team point adjustments for customer service evaluation (positive or negative)."""

    event = models.ForeignKey(
        "registration.Event",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="orange_team_bonuses",
    )
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
    check_type = models.ForeignKey(
        OrangeCheckType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bonuses",
        help_text="Category of this check (optional for backwards compatibility)",
    )
    description = models.TextField(help_text="Description of why points are adjusted (positive or negative)")
    points_awarded = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Points to add (positive) or deduct (negative)",
    )

    # Approval tracking
    is_approved = models.BooleanField(
        default=False,
        help_text="Whether this bonus has been approved",
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this bonus was approved",
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orange_bonuses_approved",
        help_text="User who approved this bonus",
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

    event = models.ForeignKey(
        "registration.Event",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="service_scores",
    )
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

    event = models.ForeignKey(
        "registration.Event",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="black_team_adjustments",
    )
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


class EventScore(models.Model):
    """Per-event calculated totals for leaderboard."""

    team = models.ForeignKey(
        "team.Team",
        on_delete=models.CASCADE,
        related_name="event_scores",
    )
    event = models.ForeignKey(
        "registration.Event",
        on_delete=models.CASCADE,
        related_name="scores",
    )
    team_assignment = models.ForeignKey(
        "registration.EventTeamAssignment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="event_scores",
        help_text="Link to registration for traceability",
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

    # Tracking
    calculated_at = models.DateTimeField(auto_now=True)
    scorecard_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When PDF score card was emailed",
    )

    class Meta:
        db_table = "event_score"
        verbose_name = "Event Score"
        verbose_name_plural = "Event Scores"
        unique_together = [["team", "event"]]
        ordering = ["-total_score", "team__team_number"]

    def __str__(self) -> str:
        rank_str = f"#{self.rank}" if self.rank else "Unranked"
        return f"{rank_str} - {self.team.team_name} @ {self.event.name}: {self.total_score}"
