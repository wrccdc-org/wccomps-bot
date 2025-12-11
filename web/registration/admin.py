"""Django admin for registration models."""

from django.contrib import admin

from .models import (
    Event,
    EventTeamAssignment,
    RegistrationContact,
    RegistrationEventEnrollment,
    Season,
    TeamRegistration,
)


class RegistrationContactInline(admin.TabularInline[RegistrationContact, TeamRegistration]):
    """Inline admin for contacts."""

    model = RegistrationContact
    extra = 0


class RegistrationEventEnrollmentInline(admin.TabularInline[RegistrationEventEnrollment, TeamRegistration]):
    """Inline admin for event enrollments."""

    model = RegistrationEventEnrollment
    extra = 0


@admin.register(TeamRegistration)
class TeamRegistrationAdmin(admin.ModelAdmin[TeamRegistration]):
    """Admin for TeamRegistration model."""

    list_display = [
        "school_name",
        "status",
        "submitted_at",
        "approved_at",
        "approved_by",
    ]
    list_filter = ["status", "submitted_at", "approved_at"]
    search_fields = ["school_name", "contacts__email", "contacts__name"]
    readonly_fields = ["submitted_at", "approved_at", "paid_at", "credentials_sent_at", "edit_token"]
    ordering = ["-submitted_at"]
    inlines = [RegistrationContactInline, RegistrationEventEnrollmentInline]


@admin.register(Season)
class SeasonAdmin(admin.ModelAdmin[Season]):
    """Admin for Season model."""

    list_display = ["name", "year", "is_active", "created_at"]
    list_filter = ["is_active"]
    ordering = ["-year"]


class EventTeamAssignmentInline(admin.TabularInline[EventTeamAssignment, Event]):
    """Inline admin for team assignments."""

    model = EventTeamAssignment
    extra = 0
    readonly_fields = ["assigned_at", "credentials_sent_at"]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin[Event]):
    """Admin for Event model."""

    list_display = [
        "name",
        "season",
        "event_type",
        "date",
        "registration_open",
        "is_active",
        "is_finalized",
    ]
    list_filter = ["season", "event_type", "registration_open", "is_active", "is_finalized"]
    ordering = ["season", "date"]
    inlines = [EventTeamAssignmentInline]


@admin.register(RegistrationContact)
class RegistrationContactAdmin(admin.ModelAdmin[RegistrationContact]):
    """Admin for RegistrationContact model."""

    list_display = ["name", "email", "role", "registration"]
    list_filter = ["role"]
    search_fields = ["name", "email", "registration__school_name"]
