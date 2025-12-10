"""Admin configuration for ticketing app."""

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse

from .models import (
    CommentRateLimit,
    Ticket,
    TicketAttachment,
    TicketComment,
    TicketHistory,
)


class TicketAttachmentInline(admin.TabularInline[TicketAttachment, Ticket]):
    model = TicketAttachment
    extra = 0
    readonly_fields = ["uploaded_at", "uploaded_by", "filename", "mime_type"]
    fields = ["filename", "mime_type", "uploaded_by", "uploaded_at"]


class TicketCommentInline(admin.TabularInline[TicketComment, Ticket]):
    model = TicketComment
    extra = 0
    readonly_fields = ["posted_at", "author"]
    fields = ["author", "comment_text", "posted_at"]


class TicketHistoryInline(admin.TabularInline[TicketHistory, Ticket]):
    model = TicketHistory
    extra = 0
    readonly_fields = ["timestamp", "action", "actor"]
    fields = ["action", "actor", "details", "timestamp"]


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin[Ticket]):
    list_display = [
        "ticket_number",
        "team",
        "category",
        "status",
        "get_assigned_to_display",
        "points_charged",
        "created_at",
    ]
    list_filter = ["status", "category", "team"]
    search_fields = ["ticket_number", "title", "hostname", "service_name"]
    ordering = ["-created_at"]
    readonly_fields = ["ticket_number", "created_at", "updated_at"]
    inlines = [TicketAttachmentInline, TicketCommentInline, TicketHistoryInline]
    actions = ["export_as_csv"]

    fieldsets = (
        ("Identity", {"fields": ("ticket_number", "team", "status")}),
        (
            "Content",
            {
                "fields": (
                    "category",
                    "title",
                    "description",
                    "hostname",
                    "ip_address",
                    "service_name",
                    "custom_fields",
                )
            },
        ),
        (
            "Assignment",
            {
                "fields": (
                    "assigned_to",
                    "assigned_at",
                )
            },
        ),
        (
            "Resolution",
            {
                "fields": (
                    "resolved_by",
                    "resolved_at",
                    "resolution_notes",
                    "duration_notes",
                    "points_charged",
                )
            },
        ),
        (
            "Discord",
            {
                "fields": (
                    "discord_thread_id",
                    "discord_channel_id",
                    "thread_archive_scheduled_at",
                )
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Assigned To")
    def get_assigned_to_display(self, obj: Ticket) -> str:
        """Display assigned person."""
        return str(obj.assigned_to) if obj.assigned_to else ""

    @admin.action(description="Export selected tickets as CSV")
    def export_as_csv(self, request: HttpRequest, queryset: QuerySet[Ticket]) -> HttpResponse:
        """Export selected tickets as CSV."""
        import csv

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="tickets.csv"'

        writer = csv.writer(response)
        writer.writerow(
            [
                "Ticket Number",
                "Team",
                "Team Number",
                "Category",
                "Title",
                "Description",
                "Status",
                "Hostname",
                "IP Address",
                "Service Name",
                "Assigned To",
                "Points Charged",
                "Created At",
                "Resolved At",
                "Resolution Notes",
                "Duration Notes",
            ]
        )

        for ticket in queryset:
            assigned_to_name = str(ticket.assigned_to) if ticket.assigned_to else ""
            writer.writerow(
                [
                    ticket.ticket_number,
                    ticket.team.team_name,
                    ticket.team.team_number,
                    ticket.category,
                    ticket.title,
                    ticket.description,
                    ticket.status,
                    ticket.hostname or "",
                    ticket.ip_address or "",
                    ticket.service_name or "",
                    assigned_to_name,
                    ticket.points_charged,
                    ticket.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    ticket.resolved_at.strftime("%Y-%m-%d %H:%M:%S") if ticket.resolved_at else "",
                    ticket.resolution_notes or "",
                    ticket.duration_notes or "",
                ]
            )

        return response


@admin.register(TicketAttachment)
class TicketAttachmentAdmin(admin.ModelAdmin[TicketAttachment]):
    list_display = ["filename", "ticket", "uploaded_by", "uploaded_at"]
    list_filter = ["uploaded_at"]
    search_fields = ["filename", "ticket__ticket_number"]
    ordering = ["-uploaded_at"]
    readonly_fields = ["uploaded_at"]


@admin.register(TicketComment)
class TicketCommentAdmin(admin.ModelAdmin[TicketComment]):
    list_display = ["ticket", "author", "posted_at"]
    list_filter = ["posted_at"]
    search_fields = ["ticket__ticket_number", "comment_text"]
    ordering = ["-posted_at"]
    readonly_fields = ["posted_at"]


@admin.register(TicketHistory)
class TicketHistoryAdmin(admin.ModelAdmin[TicketHistory]):
    list_display = ["ticket", "action", "actor", "timestamp"]
    list_filter = ["action", "timestamp"]
    search_fields = ["ticket__ticket_number"]
    ordering = ["-timestamp"]
    readonly_fields = ["timestamp"]


@admin.register(CommentRateLimit)
class CommentRateLimitAdmin(admin.ModelAdmin[CommentRateLimit]):
    list_display = ["ticket", "discord_id", "posted_at"]
    list_filter = ["posted_at"]
    search_fields = ["ticket__ticket_number", "discord_id"]
    ordering = ["-posted_at"]
    readonly_fields = ["posted_at"]

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Disable adding rate limits manually."""
        return False
