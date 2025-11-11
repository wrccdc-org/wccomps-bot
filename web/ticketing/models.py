"""Ticketing system models."""

from django.db import models


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
    team = models.ForeignKey(
        "team.Team", on_delete=models.CASCADE, related_name="tickets"
    )

    # Content
    category = models.CharField(max_length=50)
    title = models.TextField()
    description = models.TextField(blank=True)

    # Category-specific fields
    hostname = models.CharField(max_length=255, blank=True)
    ip_address = models.CharField(max_length=45, blank=True, null=True)
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
        from datetime import timedelta
        from django.utils import timezone

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
