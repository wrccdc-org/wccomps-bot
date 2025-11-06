"""Competition app models - Manage competition lifecycle and configuration."""

from django.db import models
from django.utils import timezone
from typing import Optional


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
    slug = models.SlugField(
        max_length=200,
        unique=True,
        help_text="URL-safe identifier",
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
        default=timezone.timedelta,
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

    def get_elapsed_time(self) -> Optional[timezone.timedelta]:
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
        elapsed = end_point - self.actual_start_time - self.total_paused_duration
        return elapsed

    def get_remaining_time(self) -> Optional[timezone.timedelta]:
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

        return remaining if remaining > timezone.timedelta(0) else timezone.timedelta(0)

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


class CompetitionPhase(models.Model):
    """
    Represents a phase or round within a competition.

    Useful for multi-day competitions or competitions with distinct phases.
    """

    PHASE_TYPE_CHOICES = [
        ("qualification", "Qualification"),
        ("regional", "Regional"),
        ("semifinals", "Semifinals"),
        ("finals", "Finals"),
        ("practice", "Practice"),
        ("custom", "Custom"),
    ]

    competition = models.ForeignKey(
        Competition,
        on_delete=models.CASCADE,
        related_name="phases",
        help_text="Parent competition",
    )

    name = models.CharField(
        max_length=100,
        help_text="Phase name (e.g., 'Day 1', 'Finals')",
    )
    phase_type = models.CharField(
        max_length=20,
        choices=PHASE_TYPE_CHOICES,
        default="custom",
    )
    phase_number = models.IntegerField(
        default=1,
        help_text="Phase sequence number",
    )

    # Timing
    start_time = models.DateTimeField(help_text="Phase start time")
    end_time = models.DateTimeField(help_text="Phase end time")

    # Configuration
    description = models.TextField(blank=True)
    is_scored = models.BooleanField(
        default=True,
        help_text="Include this phase in scoring",
    )

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "competition_phase"
        verbose_name = "Competition Phase"
        verbose_name_plural = "Competition Phases"
        ordering = ["competition", "phase_number"]
        unique_together = [["competition", "phase_number"]]

    def __str__(self) -> str:
        return f"{self.competition.name} - {self.name}"

    def is_active(self) -> bool:
        """Check if this phase is currently active."""
        now = timezone.now()
        return self.start_time <= now <= self.end_time
