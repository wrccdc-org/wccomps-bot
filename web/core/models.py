"""Database models for WCComps ticket system."""

from typing import Any

from django.db import models
from django.utils import timezone


class Team(models.Model):
    """Competition team (1-50)."""

    team_number = models.IntegerField(unique=True)
    team_name = models.CharField(max_length=100)
    authentik_group = models.CharField(max_length=255)

    # Discord integration
    discord_role_id = models.BigIntegerField(null=True, blank=True)
    discord_category_id = models.BigIntegerField(null=True, blank=True)

    # Limits
    max_members = models.IntegerField(default=10)

    # Ticket sequence counter
    ticket_counter = models.IntegerField(default=0)

    # Status
    is_active = models.BooleanField(default=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["team_number"]

    def __str__(self) -> str:
        return f"{self.team_name}"

    def get_member_count(self) -> int:
        """Get count of active members."""
        return self.members.filter(is_active=True).count()

    def is_full(self) -> bool:
        """Check if team has reached max members."""
        return self.get_member_count() >= self.max_members


class DiscordLink(models.Model):
    """Link between Discord user and Authentik account (optionally part of a team)."""

    discord_id = models.BigIntegerField()
    discord_username = models.CharField(max_length=255)
    authentik_username = models.CharField(max_length=255)
    authentik_user_id = models.CharField(max_length=255)
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="members", null=True, blank=True
    )
    is_active = models.BooleanField(default=True)
    linked_at = models.DateTimeField(auto_now_add=True)
    unlinked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["discord_id", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["discord_id"],
                condition=models.Q(is_active=True),
                name="unique_active_discord_link",
            ),
        ]

    def __str__(self) -> str:
        if self.team:
            return f"{self.discord_username} → {self.team.team_name}"
        return f"{self.discord_username} → {self.authentik_username}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Override save to deactivate previous active link when creating new one."""
        if self.is_active:
            # Deactivate any existing active link for this discord_id
            DiscordLink.objects.filter(
                discord_id=self.discord_id, is_active=True
            ).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)


class LinkToken(models.Model):
    """Temporary token for linking flow."""

    token = models.CharField(max_length=64, unique=True)
    discord_id = models.BigIntegerField()
    discord_username = models.CharField(max_length=255)
    used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["token", "used", "expires_at"]),
        ]

    def __str__(self) -> str:
        return f"Token for {self.discord_username}"

    def is_expired(self) -> bool:
        """Check if token has expired."""
        return timezone.now() > self.expires_at


class LinkAttempt(models.Model):
    """Audit log for link attempts."""

    discord_id = models.BigIntegerField()
    discord_username = models.CharField(max_length=255)
    authentik_username = models.CharField(max_length=255)
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL)
    success = models.BooleanField()
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self) -> str:
        status = "Success" if self.success else "Failed"
        return f"{self.discord_username} → {self.authentik_username} ({status})"


class LinkRateLimit(models.Model):
    """Rate limiting for link attempts (5 per hour per user)."""

    discord_id = models.BigIntegerField()
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["discord_id", "-attempted_at"]),
        ]

    def __str__(self) -> str:
        return f"Link attempt by {self.discord_id} at {self.attempted_at}"

    @classmethod
    def check_rate_limit(cls, discord_id: int) -> tuple[bool, int]:
        """
        Check if user has exceeded rate limit (5 attempts per hour).

        Returns: (is_allowed, attempts_in_last_hour)
        """
        from django.utils import timezone
        from datetime import timedelta

        one_hour_ago = timezone.now() - timedelta(hours=1)

        # Count attempts in last hour
        recent_attempts = cls.objects.filter(
            discord_id=discord_id, attempted_at__gte=one_hour_ago
        ).count()

        return recent_attempts < 5, recent_attempts


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


class Ticket(models.Model):
    """Support ticket from team."""

    STATUS_CHOICES = [
        ("open", "Open"),
        ("claimed", "Claimed"),
        ("resolved", "Resolved"),
        ("cancelled", "Cancelled"),
    ]

    # Identity
    ticket_number = models.CharField(max_length=20, unique=True)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="tickets")

    # Content
    category = models.CharField(max_length=50)
    title = models.TextField()
    description = models.TextField(blank=True)

    # Category-specific fields
    hostname = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    service_name = models.CharField(max_length=100, blank=True)
    custom_fields = models.JSONField(default=dict, blank=True)

    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    tags = models.JSONField(
        default=list, blank=True
    )  # e.g., ['operations-issue', 'escalated']

    # Assignment
    assigned_to_discord_id = models.BigIntegerField(null=True, blank=True)
    assigned_to_discord_username = models.CharField(max_length=255, blank=True)
    assigned_to_authentik_username = models.CharField(max_length=255, blank=True)
    assigned_to_authentik_user_id = models.CharField(max_length=255, blank=True)
    assigned_at = models.DateTimeField(null=True, blank=True)

    # Resolution
    resolved_by_discord_id = models.BigIntegerField(null=True, blank=True)
    resolved_by_discord_username = models.CharField(max_length=255, blank=True)
    resolved_by_authentik_username = models.CharField(max_length=255, blank=True)
    resolved_by_authentik_user_id = models.CharField(max_length=255, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    duration_notes = models.TextField(blank=True)
    points_charged = models.IntegerField(default=0)

    # Discord integration
    discord_thread_id = models.BigIntegerField(unique=True, null=True, blank=True)
    discord_channel_id = models.BigIntegerField(null=True, blank=True)
    thread_archive_scheduled_at = models.DateTimeField(null=True, blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["team", "status"]),
            models.Index(fields=["category", "status"]),
            models.Index(fields=["assigned_to_discord_id"]),
            models.Index(fields=["discord_thread_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.ticket_number} - {self.team.team_name}"


class TicketAttachment(models.Model):
    """File attachment for ticket."""

    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="attachments"
    )
    file_data = models.BinaryField()
    filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100)
    uploaded_by = models.CharField(max_length=100)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]

    def __str__(self) -> str:
        return f"{self.filename} ({self.ticket.ticket_number})"


class TicketComment(models.Model):
    """Comment on ticket (bidirectional with Discord)."""

    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="comments"
    )
    author_name = models.CharField(max_length=255)
    author_discord_id = models.BigIntegerField(null=True, blank=True)
    comment_text = models.TextField()
    posted_at = models.DateTimeField(auto_now_add=True)
    discord_message_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["posted_at"]

    def __str__(self) -> str:
        return f"Comment by {self.author_name} on {self.ticket.ticket_number}"


class TicketHistory(models.Model):
    """History of ticket state changes."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="history")
    action = models.CharField(max_length=50)
    actor_discord_id = models.BigIntegerField(null=True)
    actor_username = models.CharField(max_length=255, blank=True)
    details = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self) -> str:
        return f"{self.action} on {self.ticket.ticket_number}"


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
    ticket = models.ForeignKey(Ticket, null=True, blank=True, on_delete=models.CASCADE)
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


class CommentRateLimit(models.Model):
    """Rate limiting for ticket comments (5/min per ticket, 10/min per user)."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, null=True, blank=True)
    discord_id = models.BigIntegerField()
    posted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["ticket", "-posted_at"]),
            models.Index(fields=["discord_id", "-posted_at"]),
        ]

    def __str__(self) -> str:
        return f"Comment by {self.discord_id} at {self.posted_at}"

    @classmethod
    def check_rate_limit(cls, ticket_id: int, discord_id: int) -> tuple[bool, str]:
        """
        Check if user has exceeded rate limit.

        Returns: (is_allowed, reason_if_blocked)
        """
        from django.utils import timezone
        from datetime import timedelta

        one_minute_ago = timezone.now() - timedelta(minutes=1)

        # Check ticket-level rate limit (5 comments per minute)
        ticket_comments = cls.objects.filter(
            ticket_id=ticket_id, posted_at__gte=one_minute_ago
        ).count()

        if ticket_comments >= 5:
            return (
                False,
                f"Ticket rate limit exceeded ({ticket_comments}/5 comments in last minute)",
            )

        # Check user-level rate limit (10 comments per minute across all tickets)
        user_comments = cls.objects.filter(
            discord_id=discord_id, posted_at__gte=one_minute_ago
        ).count()

        if user_comments >= 10:
            return (
                False,
                f"User rate limit exceeded ({user_comments}/10 comments in last minute)",
            )

        return True, ""


class CompetitionConfig(models.Model):
    """Competition configuration and timing."""

    # Team settings
    max_team_members = models.IntegerField(
        default=10, help_text="Maximum members per team"
    )

    # Competition timing
    competition_start_time = models.DateTimeField(
        null=True, blank=True, help_text="When applications should be enabled"
    )
    applications_enabled = models.BooleanField(
        default=False, help_text="Whether applications are currently enabled"
    )

    # Application slugs to control
    controlled_applications = models.JSONField(
        default=list,
        help_text="List of Authentik application slugs to enable/disable (e.g., ['netbird', 'scoring'])",
    )

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_check = models.DateTimeField(
        null=True, blank=True, help_text="Last time background task checked"
    )

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
        return (
            timezone.now() >= self.competition_start_time
            and not self.applications_enabled
        )

    @classmethod
    def get_config(cls) -> "CompetitionConfig":
        """Get or create singleton config instance."""
        config, _ = cls.objects.get_or_create(pk=1)
        return config


class SchoolInfo(models.Model):
    """School information for teams (GoldTeam only)."""

    team = models.OneToOneField(
        Team, on_delete=models.CASCADE, related_name="school_info"
    )
    school_name = models.CharField(max_length=255)
    contact_email = models.EmailField()
    secondary_email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "School Information"
        verbose_name_plural = "School Information"
        ordering = ["team__team_number"]

    def __str__(self) -> str:
        return f"{self.school_name} (Team {self.team.team_number})"
