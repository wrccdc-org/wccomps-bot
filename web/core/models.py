"""Database models for WCComps ticket system."""

from django.db import models


class AuditLog(models.Model):
    """General audit log for admin actions."""

    action = models.CharField(max_length=50)
    admin_user = models.CharField(max_length=255)
    target_entity = models.CharField(max_length=50)
    target_id = models.BigIntegerField()
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action} by {self.admin_user}"


class DiscordTask(models.Model):
    """Task queue for Discord API operations (rate limit resilience)."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    TASK_TYPE_CHOICES = [
        ("create_thread", "Create Thread"),
        ("update_embed", "Update Embed"),
        ("update_dashboard", "Update Dashboard"),
        ("archive_thread", "Archive Thread"),
        ("send_message", "Send Message"),
        ("post_comment", "Post Comment to Thread"),
        ("broadcast_message", "Broadcast Message"),
        ("assign_role", "Assign Team Role"),
        ("remove_role", "Remove Team Role"),
        ("setup_team_infrastructure", "Setup Team Infrastructure"),
        ("log_to_channel", "Log to Ops Channel"),
    ]

    task_type = models.CharField(max_length=50, choices=TASK_TYPE_CHOICES)
    ticket = models.ForeignKey("ticketing.Ticket", null=True, blank=True, on_delete=models.CASCADE)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=5)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "next_retry_at"]),
            models.Index(fields=["task_type", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.task_type} ({self.status})"


class BotState(models.Model):
    """Bot state storage (dashboard message IDs, etc)."""

    key = models.CharField(max_length=100, unique=True)
    value = models.CharField(max_length=255)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.key}: {self.value}"


class DashboardUpdate(models.Model):
    """Dashboard update tracking (for debouncing)."""

    needs_update = models.BooleanField(default=True)
    last_updated = models.DateTimeField(auto_now=True)
    update_scheduled_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Dashboard (needs_update={self.needs_update})"


class CompetitionConfig(models.Model):
    """Competition configuration and timing."""

    # Team settings
    max_team_members = models.IntegerField(default=10, help_text="Maximum members per team")

    # Competition timing
    competition_start_time = models.DateTimeField(
        null=True, blank=True, help_text="When applications should be enabled"
    )
    competition_end_time = models.DateTimeField(null=True, blank=True, help_text="When applications should be disabled")
    applications_enabled = models.BooleanField(default=False, help_text="Whether applications are currently enabled")

    # Application slugs to control
    controlled_applications = models.JSONField(
        default=list,
        help_text="List of Authentik application slugs to enable/disable (e.g., ['netbird', 'scoring'])",
    )

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_check = models.DateTimeField(null=True, blank=True, help_text="Last time background task checked")

    class Meta:
        verbose_name = "Competition Configuration"
        verbose_name_plural = "Competition Configuration"

    def __str__(self) -> str:
        if self.competition_start_time:
            return f"Competition starts at {self.competition_start_time} (enabled={self.applications_enabled})"
        return "Competition not scheduled"

    def should_enable_applications(self) -> bool:
        """Check if applications should be enabled based on current time."""
        if not self.competition_start_time:
            return False
        return timezone.now() >= self.competition_start_time and not self.applications_enabled

    def should_disable_applications(self) -> bool:
        """Check if applications should be disabled based on current time."""
        if not self.competition_end_time:
            return False
        return timezone.now() >= self.competition_end_time and self.applications_enabled

    @classmethod
    def get_config(cls) -> "CompetitionConfig":
        """Get or create singleton config instance."""
        config, _ = cls.objects.get_or_create(pk=1)
        return config
