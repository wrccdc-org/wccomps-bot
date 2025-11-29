"""Django admin for registration models."""

from django.contrib import admin

from .models import TeamRegistration


@admin.register(TeamRegistration)
class TeamRegistrationAdmin(admin.ModelAdmin[TeamRegistration]):
    """Admin for TeamRegistration model."""

    list_display = [
        "school_name",
        "contact_email",
        "phone",
        "status",
        "submitted_at",
        "approved_at",
        "approved_by",
    ]
    list_filter = ["status", "submitted_at", "approved_at"]
    search_fields = ["school_name", "contact_email"]
    readonly_fields = ["submitted_at", "approved_at", "paid_at", "credentials_sent_at"]
    ordering = ["-submitted_at"]
