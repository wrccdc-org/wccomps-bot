"""Models for team registration."""

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class TeamRegistration(models.Model):
    """Team registration for competition."""

    STATUS_CHOICES = [
        ("pending", "Pending Review"),
        ("approved", "Approved"),
        ("paid", "Paid"),
        ("credentials_sent", "Credentials Sent"),
        ("rejected", "Rejected"),
    ]

    school_name = models.CharField(max_length=255)
    contact_email = models.EmailField()
    phone = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    submitted_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    credentials_sent_at = models.DateTimeField(null=True, blank=True)

    rejection_reason = models.TextField(blank=True)
    approved_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self) -> str:
        return f"{self.school_name} ({self.status})"

    def approve(self, user: User) -> None:
        """Approve the registration."""
        self.status = "approved"
        self.approved_at = timezone.now()
        self.approved_by = user
        self.save()

    def reject(self, reason: str) -> None:
        """Reject the registration."""
        self.status = "rejected"
        self.rejection_reason = reason
        self.save()
