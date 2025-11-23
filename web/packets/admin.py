"""Admin interface for packet distribution system."""

from django.contrib import admin
from django.db.models import Count, Q
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import PacketDistribution, TeamPacket


class PacketDistributionInline(admin.TabularInline):
    """Inline display of packet distributions."""

    model = PacketDistribution
    extra = 0
    fields = [
        "team",
        "email_status",
        "email_sent_to",
        "email_sent_at",
        "download_count",
        "downloaded_at",
    ]
    readonly_fields = [
        "email_sent_at",
        "downloaded_at",
        "download_count",
    ]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(TeamPacket)
class TeamPacketAdmin(admin.ModelAdmin):
    """Admin interface for team packets."""

    list_display = [
        "title",
        "status",
        "scheduled_distribution_time",
        "distribution_stats_display",
        "file_info",
        "created_at",
        "uploaded_by",
    ]
    list_filter = ["status", "send_via_email", "web_access_enabled", "created_at"]
    search_fields = ["title", "filename", "uploaded_by", "notes"]
    readonly_fields = [
        "actual_distribution_time",
        "created_at",
        "updated_at",
        "file_size",
        "mime_type",
        "distribution_stats_display",
    ]
    fieldsets = [
        (
            "Packet Information",
            {
                "fields": [
                    "title",
                    "status",
                    "file_data",
                    "filename",
                    "mime_type",
                    "file_size",
                    "notes",
                    "uploaded_by",
                ]
            },
        ),
        (
            "Distribution Settings",
            {
                "fields": [
                    "send_via_email",
                    "web_access_enabled",
                    "scheduled_distribution_time",
                    "actual_distribution_time",
                ]
            },
        ),
        (
            "Statistics",
            {
                "fields": ["distribution_stats_display"],
            },
        ),
        (
            "Timestamps",
            {
                "fields": ["created_at", "updated_at"],
                "classes": ["collapse"],
            },
        ),
    ]
    inlines = [PacketDistributionInline]
    actions = ["distribute_now", "mark_as_completed", "export_distribution_report"]

    def get_queryset(self, request):
        """Optimize queryset with distribution counts."""
        qs = super().get_queryset(request)
        qs = qs.annotate(
            total_distributions=Count("distributions"),
            sent_count=Count(
                "distributions", filter=Q(distributions__email_status="sent")
            ),
            failed_count=Count(
                "distributions", filter=Q(distributions__email_status="failed")
            ),
            downloaded_count=Count(
                "distributions",
                filter=Q(distributions__downloaded_at__isnull=False),
            ),
        )
        return qs

    def file_info(self, obj):
        """Display file information."""
        size_kb = obj.file_size / 1024
        if size_kb < 1024:
            size_str = f"{size_kb:.1f} KB"
        else:
            size_str = f"{size_kb/1024:.1f} MB"
        return format_html(
            "{}<br><small>{} ({})</small>",
            obj.filename,
            obj.mime_type,
            size_str,
        )

    file_info.short_description = "File"

    def distribution_stats_display(self, obj):
        """Display distribution statistics."""
        if hasattr(obj, "total_distributions"):
            # From annotated queryset
            stats = {
                "total": obj.total_distributions,
                "sent": obj.sent_count,
                "failed": obj.failed_count,
                "downloaded": obj.downloaded_count,
            }
        else:
            # Fallback to method call
            stats = obj.get_distribution_stats()

        html = f"""
        <table style="width: 100%;">
            <tr>
                <td><strong>Total:</strong> {stats['total']}</td>
                <td><strong>Sent:</strong> {stats.get('sent', 0)}</td>
            </tr>
            <tr>
                <td><strong>Failed:</strong> {stats.get('failed', 0)}</td>
                <td><strong>Downloaded:</strong> {stats.get('downloaded', 0)}</td>
            </tr>
        </table>
        """
        return mark_safe(html)

    distribution_stats_display.short_description = "Distribution Stats"

    @admin.action(description="Distribute selected packets now")
    def distribute_now(self, request, queryset):
        """Trigger immediate distribution of selected packets."""
        from .services import PacketDistributionService

        count = 0
        for packet in queryset:
            if packet.status in ["draft", "scheduled"]:
                service = PacketDistributionService()
                service.distribute_packet(packet)
                count += 1

        self.message_user(
            request,
            f"Started distribution for {count} packet(s).",
        )

    @admin.action(description="Mark selected packets as completed")
    def mark_as_completed(self, request, queryset):
        """Mark selected packets as completed."""
        count = queryset.update(status="completed")
        self.message_user(request, f"Marked {count} packet(s) as completed.")

    @admin.action(description="Export distribution report to CSV")
    def export_distribution_report(self, request, queryset):
        """Export distribution report as CSV."""
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="packet_distribution_report.csv"'

        writer = csv.writer(response)
        writer.writerow([
            "Packet Title",
            "Team Number",
            "Team Name",
            "Email Status",
            "Email Sent To",
            "Email Sent At",
            "Downloaded",
            "Download Count",
            "Last Downloaded",
        ])

        for packet in queryset:
            for dist in packet.distributions.select_related("team").order_by(
                "team__team_number"
            ):
                writer.writerow([
                    packet.title,
                    dist.team.team_number,
                    dist.team.team_name,
                    dist.email_status,
                    dist.email_sent_to,
                    dist.email_sent_at.isoformat() if dist.email_sent_at else "",
                    "Yes" if dist.downloaded_at else "No",
                    dist.download_count,
                    dist.last_downloaded_at.isoformat()
                    if dist.last_downloaded_at
                    else "",
                ])

        return response


@admin.register(PacketDistribution)
class PacketDistributionAdmin(admin.ModelAdmin):
    """Admin interface for packet distributions."""

    list_display = [
        "packet",
        "team",
        "email_status",
        "email_sent_to",
        "email_sent_at",
        "download_info",
    ]
    list_filter = [
        "email_status",
        "web_access_enabled",
        "packet__status",
        "email_sent_at",
        "downloaded_at",
    ]
    search_fields = [
        "packet__title",
        "team__team_name",
        "team__team_number",
        "email_sent_to",
        "downloaded_by",
    ]
    readonly_fields = [
        "email_sent_at",
        "downloaded_at",
        "last_downloaded_at",
        "download_count",
        "created_at",
        "updated_at",
    ]
    fieldsets = [
        (
            "Basic Information",
            {
                "fields": ["packet", "team"],
            },
        ),
        (
            "Email Delivery",
            {
                "fields": [
                    "email_status",
                    "email_sent_to",
                    "email_sent_at",
                    "email_error_message",
                ]
            },
        ),
        (
            "Web Access",
            {
                "fields": [
                    "web_access_enabled",
                    "downloaded_at",
                    "download_count",
                    "last_downloaded_at",
                    "downloaded_by",
                ]
            },
        ),
        (
            "Timestamps",
            {
                "fields": ["created_at", "updated_at"],
                "classes": ["collapse"],
            },
        ),
    ]
    actions = ["retry_failed_emails"]

    def download_info(self, obj):
        """Display download information."""
        if obj.download_count > 0:
            return format_html(
                "{} download(s)<br><small>Last: {}</small>",
                obj.download_count,
                obj.last_downloaded_at.strftime("%Y-%m-%d %H:%M")
                if obj.last_downloaded_at
                else "Never",
            )
        return "Not downloaded"

    download_info.short_description = "Downloads"

    @admin.action(description="Retry sending failed emails")
    def retry_failed_emails(self, request, queryset):
        """Retry sending emails for failed distributions."""
        from .services import PacketDistributionService

        service = PacketDistributionService()
        failed_dists = queryset.filter(email_status="failed")
        count = 0

        for dist in failed_dists:
            try:
                service.send_packet_email(dist)
                count += 1
            except Exception:
                pass

        self.message_user(
            request,
            f"Retried {count} failed email(s).",
        )
