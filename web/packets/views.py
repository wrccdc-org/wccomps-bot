"""Views for packet distribution system."""

import mimetypes
from datetime import datetime

from django.contrib import messages
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.auth_utils import get_user_team_number, require_permission
from team.models import Team

from .models import PacketDistribution, TeamPacket
from .services import PacketDistributionService


@require_GET
@require_permission("blue_team")
def team_packets_list(request):
    """List all available packets for the current team."""
    team_number = get_user_team_number(request.user)
    if not team_number:
        messages.error(request, "You are not assigned to a team.")
        return redirect("/")

    team = get_object_or_404(Team, team_number=team_number)

    # Get all distributions for this team
    distributions = (
        PacketDistribution.objects.filter(team=team, web_access_enabled=True)
        .select_related("packet")
        .order_by("-packet__created_at")
    )

    # Filter to only show packets that are ready for access
    available_distributions = [
        dist
        for dist in distributions
        if dist.packet.status in ["distributing", "completed"]
        and dist.packet.web_access_enabled
    ]

    context = {
        "distributions": available_distributions,
        "team": team,
    }

    return render(request, "packets/team_packets_list.html", context)


@require_GET
def download_packet(request, packet_id):
    """Download a packet file."""
    packet = get_object_or_404(TeamPacket, id=packet_id)

    # Check if packet is available for download
    if packet.status not in ["distributing", "completed"]:
        raise Http404("Packet not available")

    if not packet.web_access_enabled:
        raise Http404("Packet not available for web access")

    # Get user's team
    team_number = get_user_team_number(request.user)
    if not team_number:
        messages.error(request, "You are not assigned to a team.")
        return redirect("/")

    team = get_object_or_404(Team, team_number=team_number)

    # Record the download
    service = PacketDistributionService()
    service.record_packet_download(packet, team, request.user.username)

    # Serve the file
    response = HttpResponse(bytes(packet.file_data), content_type=packet.mime_type)
    response["Content-Disposition"] = f'attachment; filename="{packet.filename}"'
    response["Content-Length"] = packet.file_size

    return response


@require_GET
@require_permission("gold_team")
def ops_packets_list(request):
    """List all packets for GoldTeam administrators."""
    packets = TeamPacket.objects.all().order_by("-created_at")

    # Add distribution stats to each packet
    for packet in packets:
        packet.stats = packet.get_distribution_stats()

    context = {
        "packets": packets,
    }

    return render(request, "packets/ops_packets_list.html", context)


@require_http_methods(["GET", "POST"])
@require_permission("gold_team")
def ops_upload_packet(request):
    """Upload a new team packet."""
    if request.method == "POST":
        # Get form data
        title = request.POST.get("title", "").strip()
        notes = request.POST.get("notes", "").strip()
        send_via_email = request.POST.get("send_via_email") == "on"
        web_access_enabled = request.POST.get("web_access_enabled") == "on"
        schedule_distribution = request.POST.get("schedule_distribution") == "on"
        scheduled_time_str = request.POST.get("scheduled_time", "").strip()

        # Validate
        if not title:
            messages.error(request, "Title is required.")
            return render(request, "packets/ops_upload_packet.html")

        # Get uploaded file
        if "packet_file" not in request.FILES:
            messages.error(request, "Please select a file to upload.")
            return render(request, "packets/ops_upload_packet.html")

        uploaded_file = request.FILES["packet_file"]

        # Validate file size (max 25 MB)
        max_size = 25 * 1024 * 1024
        if uploaded_file.size > max_size:
            messages.error(request, "File size must not exceed 25 MB.")
            return render(request, "packets/ops_upload_packet.html")

        # Read file data
        file_data = uploaded_file.read()
        filename = uploaded_file.name
        mime_type = uploaded_file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        # Parse scheduled time if provided
        scheduled_time = None
        status = "draft"

        if schedule_distribution and scheduled_time_str:
            try:
                # Parse datetime-local format: YYYY-MM-DDTHH:MM
                scheduled_time = timezone.make_aware(
                    datetime.strptime(scheduled_time_str, "%Y-%m-%dT%H:%M")
                )
                status = "scheduled"
            except ValueError:
                messages.error(request, "Invalid scheduled time format.")
                return render(request, "packets/ops_upload_packet.html")

        # Create packet
        packet = TeamPacket.objects.create(
            title=title,
            file_data=file_data,
            filename=filename,
            mime_type=mime_type,
            file_size=len(file_data),
            status=status,
            send_via_email=send_via_email,
            web_access_enabled=web_access_enabled,
            scheduled_distribution_time=scheduled_time,
            uploaded_by=request.user.username,
            notes=notes,
        )

        messages.success(
            request,
            f"Packet '{title}' uploaded successfully. "
            f"Status: {packet.get_status_display()}",
        )
        return redirect("ops_packets_list")

    return render(request, "packets/ops_upload_packet.html")


@require_GET
@require_permission("gold_team")
def ops_packet_detail(request, packet_id):
    """View packet details and distribution status."""
    packet = get_object_or_404(TeamPacket, id=packet_id)

    distributions = packet.distributions.select_related("team").order_by(
        "team__team_number"
    )

    context = {
        "packet": packet,
        "distributions": distributions,
        "stats": packet.get_distribution_stats(),
    }

    return render(request, "packets/ops_packet_detail.html", context)


@require_POST
@require_permission("gold_team")
def ops_distribute_packet(request, packet_id):
    """Manually trigger distribution of a packet."""
    packet = get_object_or_404(TeamPacket, id=packet_id)

    if packet.status not in ["draft", "scheduled"]:
        messages.error(
            request, f"Cannot distribute packet with status: {packet.get_status_display()}"
        )
        return redirect("ops_packet_detail", packet_id=packet_id)

    try:
        service = PacketDistributionService()
        result = service.distribute_packet(packet)

        messages.success(
            request,
            f"Distribution started. Emails sent: {result['email_sent']}, "
            f"Failed: {result['email_failed']}",
        )
    except Exception as e:
        messages.error(request, f"Distribution failed: {e}")

    return redirect("ops_packet_detail", packet_id=packet_id)


@require_POST
@require_permission("gold_team")
def ops_cancel_packet(request, packet_id):
    """Cancel a packet distribution."""
    packet = get_object_or_404(TeamPacket, id=packet_id)

    packet.status = "cancelled"
    packet.save(update_fields=["status", "updated_at"])

    messages.success(request, f"Packet '{packet.title}' has been cancelled.")
    return redirect("ops_packet_detail", packet_id=packet_id)
