"""Competition app models - Manage competition lifecycle and configuration."""

from datetime import timedelta

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class Competition(models.Model):
    """
    Represents a CCDC-style competition event.

    Manages timing, status, and configuration for a single competition.
    """

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("upcoming", "Upcoming"),
        ("active", "Active"),
        ("paused", "Paused"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    # Identity
    name = models.CharField(
        max_length=200,
        help_text="Competition name (e.g., 'SWCCDC 2025')",
    )
    description = models.TextField(
        blank=True,
        help_text="Competition overview and rules",
    )

    # Status
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="draft",
        db_index=True,
        help_text="Current competition state",
    )

    # Timing
    scheduled_start_time = models.DateTimeField(
        help_text="Planned competition start time",
    )
    scheduled_end_time = models.DateTimeField(
        help_text="Planned competition end time",
    )
    actual_start_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When competition actually started",
    )
    actual_end_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When competition actually ended",
    )

    # Pause tracking
    paused_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When competition was paused (if currently paused)",
    )
    total_paused_duration = models.DurationField(
        default=timedelta,
        help_text="Total accumulated pause time",
    )

    # Configuration
    team_count = models.IntegerField(
        default=50,
        help_text="Number of competing teams (1-50)",
    )
    ticketing_enabled = models.BooleanField(
        default=True,
        help_text="Allow teams to submit tickets",
    )
    scoring_enabled = models.BooleanField(
        default=True,
        help_text="Enable Quotient scoring integration",
    )

    # Integration
    quotient_competition_id = models.CharField(
        max_length=50,
        blank=True,
        help_text="Quotient competition UUID for scoring",
    )
    discord_announcement_channel_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Discord channel for competition announcements",
    )

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="competitions_created",
        help_text="User who created this competition",
    )

    class Meta:
        db_table = "competition_competition"
        verbose_name = "Competition"
        verbose_name_plural = "Competitions"
        ordering = ["-scheduled_start_time"]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_status_display()})"

    def is_active(self) -> bool:
        """Check if competition is currently active."""
        return self.status == "active"

    def is_paused(self) -> bool:
        """Check if competition is currently paused."""
        return self.status == "paused"

    def is_completed(self) -> bool:
        """Check if competition has ended."""
        return self.status == "completed"

    def get_elapsed_time(self) -> timedelta | None:
        """
        Calculate elapsed competition time, excluding pauses.

        Returns:
            timedelta: Time elapsed since start, minus pauses
            None: If competition hasn't started
        """
        if not self.actual_start_time:
            return None

        # Determine end point
        if self.actual_end_time:
            end_point = self.actual_end_time
        elif self.paused_at:
            end_point = self.paused_at
        else:
            end_point = timezone.now()

        # Calculate elapsed time minus pauses
        return end_point - self.actual_start_time - self.total_paused_duration

    def get_remaining_time(self) -> timedelta | None:
        """
        Calculate remaining competition time.

        Returns:
            timedelta: Time until scheduled end
            None: If competition hasn't started or is completed
        """
        if not self.actual_start_time or self.is_completed():
            return None

        elapsed = self.get_elapsed_time()
        if not elapsed:
            return None

        scheduled_duration = self.scheduled_end_time - self.scheduled_start_time
        remaining = scheduled_duration - elapsed

        return remaining if remaining > timedelta(0) else timedelta(0)

    def start_competition(self) -> None:
        """Start the competition (transition to active)."""
        if self.status == "upcoming":
            self.status = "active"
            self.actual_start_time = timezone.now()
            self.save()

    def pause_competition(self) -> None:
        """Pause the competition."""
        if self.status == "active":
            self.status = "paused"
            self.paused_at = timezone.now()
            self.save()

    def resume_competition(self) -> None:
        """Resume the competition from pause."""
        if self.status == "paused" and self.paused_at:
            # Add pause duration to total
            pause_duration = timezone.now() - self.paused_at
            self.total_paused_duration += pause_duration

            self.status = "active"
            self.paused_at = None
            self.save()

    def end_competition(self) -> None:
        """End the competition (transition to completed)."""
        if self.status in ["active", "paused"]:
            # If paused, add final pause duration
            if self.paused_at:
                pause_duration = timezone.now() - self.paused_at
                self.total_paused_duration += pause_duration
                self.paused_at = None

            self.status = "completed"
            self.actual_end_time = timezone.now()
            self.save()


class StudentHelper(models.Model):
    """
    Tracks student helpers with temporary access to team channels.

    Student helpers are assigned to specific competitions/invitationals
    and automatically receive Discord roles for the duration of the event.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),  # Created but not yet active (before start time)
        ("active", "Active"),  # Currently has role assigned
        ("expired", "Expired"),  # Past end time, role removed
        ("revoked", "Revoked"),  # Manually removed before end time
    ]

    # Competition/Invitational
    competition = models.ForeignKey(
        Competition,
        on_delete=models.CASCADE,
        related_name="student_helpers",
        help_text="Competition or invitational this helper is assigned to",
    )

    # Helper identity (link to Person for Authentik integration)
    person = models.ForeignKey(
        "person.Person",
        on_delete=models.CASCADE,
        related_name="helper_assignments",
        help_text="Person assigned as helper",
    )

    # Cached identity fields for quick lookups
    discord_id = models.BigIntegerField(
        db_index=True,
        help_text="Discord user ID (cached from Person)",
    )
    discord_username = models.CharField(
        max_length=100,
        help_text="Discord username (cached from Person)",
    )
    authentik_username = models.CharField(
        max_length=150,
        db_index=True,
        help_text="Authentik username (cached from Person)",
    )

    # Discord role configuration
    discord_role_name = models.CharField(
        max_length=100,
        help_text='Discord role name (e.g., "UCI Invitationals 2026")',
    )
    discord_role_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Discord role ID (snowflake) once assigned",
    )

    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
        db_index=True,
        help_text="Current helper status",
    )

    # Time overrides (optional - defaults to competition times)
    custom_start_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Custom start time (overrides competition start)",
    )
    custom_end_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Custom end time (overrides competition end)",
    )

    # Lifecycle timestamps
    activated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When role was actually assigned",
    )
    deactivated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When role was actually removed",
    )

    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="student_helpers_created",
        help_text="User who created this helper assignment",
    )
    revoked_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_helpers_revoked",
        help_text="User who revoked this helper assignment (if applicable)",
    )
    revoke_reason = models.TextField(
        blank=True,
        help_text="Reason for manual revocation",
    )

    class Meta:
        db_table = "competition_student_helper"
        verbose_name = "Student Helper"
        verbose_name_plural = "Student Helpers"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["competition", "status"]),
            models.Index(fields=["person", "status"]),
            models.Index(fields=["discord_id", "status"]),
        ]
        constraints = [
            # Prevent duplicate active assignments for same person+competition
            models.UniqueConstraint(
                fields=["person", "competition"],
                condition=models.Q(status__in=["pending", "active"]),
                name="competition_unique_active_helper_assignment",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.authentik_username} → {self.competition.name} ({self.get_status_display()})"

    def get_start_time(self):  # type: ignore[no-untyped-def]
        """Get effective start time (custom or competition start)."""
        return self.custom_start_time or self.competition.scheduled_start_time

    def get_end_time(self):  # type: ignore[no-untyped-def]
        """Get effective end time (custom or competition end)."""
        return self.custom_end_time or self.competition.scheduled_end_time

    def should_be_active(self) -> bool:
        """
        Check if helper should currently have active role.

        Returns True if current time is between start and end time.
        """
        if self.status == "revoked":
            return False

        now = timezone.now()
        start_time = self.get_start_time()  # type: ignore[no-untyped-call]
        end_time = self.get_end_time()  # type: ignore[no-untyped-call]

        return start_time <= now <= end_time  # type: ignore[no-any-return]

    def activate(self, role_id: int) -> None:
        """
        Mark helper as active with assigned Discord role.

        Args:
            role_id: Discord role ID (snowflake) that was assigned
        """
        self.status = "active"
        self.discord_role_id = role_id
        self.activated_at = timezone.now()
        self.save()

    def deactivate(self) -> None:
        """Mark helper as expired (role removed)."""
        if self.status == "active":
            self.status = "expired"
            self.deactivated_at = timezone.now()
            self.save()

    def revoke(self, user: User, reason: str = "") -> None:
        """
        Manually revoke helper access before end time.

        Args:
            user: User performing the revocation
            reason: Optional reason for revocation
        """
        if self.status in ["pending", "active"]:
            self.status = "revoked"
            self.revoked_by = user
            self.revoke_reason = reason
            self.deactivated_at = timezone.now()
            self.save()
