"""Views for team packet distribution system."""

import csv
import io
import mimetypes
import re
from typing import TypedDict, cast

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.files.uploadedfile import UploadedFile
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from registration.models import Event

from core.auth_utils import get_user_team_number, require_permission
from team.models import Team

from .models import PacketDistribution, TeamPacket
from .services import PacketDistributionService


class PacketWithStats(TypedDict):
    """Packet paired with its distribution stats."""

    packet: TeamPacket
    stats: dict[str, int]


@require_GET
@require_permission("blue_team")
def team_packets_list(request: HttpRequest) -> HttpResponse:
    """List all available packets for the current team (or all packets for gold_team)."""
    from core.auth_utils import has_permission

    user = cast(User, request.user)
    is_gold = has_permission(user, "gold_team")

    if is_gold:
        # Gold team sees all distributed packets
        packets = TeamPacket.objects.filter(status__in=["distributing", "completed"], web_access_enabled=True).order_by(
            "-created_at"
        )
        context: dict[str, object] = {"packets": packets, "is_gold_view": True}
        return render(request, "packets/team_packets_list.html", context)

    team_number = get_user_team_number(user)
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
        if dist.packet.status in ["distributing", "completed"] and dist.packet.web_access_enabled
    ]

    context = {
        "distributions": available_distributions,
        "team": team,
    }

    return render(request, "packets/team_packets_list.html", context)


@login_required
@require_GET
def download_packet(request: HttpRequest, packet_id: int) -> HttpResponse:
    """Download a packet file."""
    packet = get_object_or_404(TeamPacket, id=packet_id)

    # Check if packet is available for download
    if packet.status not in ["distributing", "completed"]:
        raise Http404("Packet not available")

    if not packet.web_access_enabled:
        raise Http404("Packet not available for web access")

    # Get user's team (skip download tracking for staff)
    from core.auth_utils import has_permission

    user = cast(User, request.user)
    team_number = get_user_team_number(user)
    if team_number:
        team = get_object_or_404(Team, team_number=team_number)
        service = PacketDistributionService()
        service.record_packet_download(packet, team, request.user.username)
    elif not has_permission(user, "gold_team"):
        messages.error(request, "You are not assigned to a team.")
        return redirect("/")

    # Serve the file
    response = HttpResponse(bytes(packet.file_data), content_type=packet.mime_type)
    response["Content-Disposition"] = f'attachment; filename="{packet.filename}"'
    response["Content-Length"] = packet.file_size

    return response


@require_GET
@require_permission("gold_team")
def ops_packets_list(request: HttpRequest) -> HttpResponse:
    """List all packets for GoldTeam administrators."""
    packets = list(TeamPacket.objects.all().order_by("-created_at"))

    # Build packets with stats for template
    packets_with_stats: list[PacketWithStats] = [
        {"packet": packet, "stats": packet.get_distribution_stats()} for packet in packets
    ]

    context = {
        "packets_with_stats": packets_with_stats,
        "nav_active": "ops_admin",
    }

    return render(request, "packets/ops_packets_list.html", context)


def _parse_team_extras_csv(csv_text: str) -> dict[str, dict[str, str]]:
    """Parse per-team CSV data into a dict keyed by team number.

    Expects a CSV with a 'team' column (e.g. 'Team01', 'Team 3', '5').
    Returns dict like {"1": {"api_key": "sk-...", ...}, "2": {...}}.
    """
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    if not reader.fieldnames:
        return {}

    # Find the team column
    team_col = None
    for col in reader.fieldnames:
        if "team" in col.lower():
            team_col = col
            break

    if not team_col:
        return {}

    result: dict[str, dict[str, str]] = {}
    other_cols = [c for c in reader.fieldnames if c != team_col]

    for row in reader:
        raw_team = row.get(team_col, "").strip()
        # Extract team number: "Team01" -> 1, "Team 3" -> 3, "5" -> 5
        digits = re.sub(r"[^\d]", "", raw_team)
        if not digits:
            continue
        team_num = str(int(digits))
        result[team_num] = {col: row.get(col, "").strip() for col in other_cols}

    return result


@require_http_methods(["GET", "POST"])
@require_permission("gold_team")
def ops_upload_packet(request: HttpRequest) -> HttpResponse:
    """Upload a new team packet."""
    events = Event.objects.all()
    form_context = {"events": events, "nav_active": "packets"}

    if request.method == "POST":
        # Get form data
        title = request.POST.get("title", "").strip()
        notes = request.POST.get("notes", "").strip()
        send_via_email = request.POST.get("send_via_email") == "on"
        web_access_enabled = request.POST.get("web_access_enabled") == "on"
        event_id = request.POST.get("event", "").strip()
        team_extras_csv = request.POST.get("team_extras", "").strip()

        # Validate
        if not title:
            messages.error(request, "Title is required.")
            return render(request, "packets/ops_upload_packet.html", form_context)

        # Get uploaded file
        if "packet_file" not in request.FILES:
            messages.error(request, "Please select a file to upload.")
            return render(request, "packets/ops_upload_packet.html", form_context)

        uploaded_file = cast(UploadedFile, request.FILES["packet_file"])

        # Validate file size (max 25 MB)
        max_size = 25 * 1024 * 1024
        file_size = uploaded_file.size or 0
        if file_size > max_size:
            messages.error(request, "File size must not exceed 25 MB.")
            return render(request, "packets/ops_upload_packet.html", form_context)

        # Read file data
        file_data = uploaded_file.read()
        filename = uploaded_file.name or "unnamed"
        mime_type = uploaded_file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        # Parse event
        event = None
        if event_id:
            try:
                event = Event.objects.get(id=event_id)
            except Event.DoesNotExist:
                messages.error(request, "Selected event not found.")
                return render(request, "packets/ops_upload_packet.html", form_context)

        # Parse per-team extras CSV
        team_extras: dict[str, dict[str, str]] = {}
        if team_extras_csv:
            team_extras = _parse_team_extras_csv(team_extras_csv)
            if not team_extras:
                messages.error(request, "Could not parse per-team data. Ensure CSV has a 'team' column.")
                return render(request, "packets/ops_upload_packet.html", form_context)

        # Create packet
        TeamPacket.objects.create(
            title=title,
            file_data=file_data,
            filename=filename,
            mime_type=mime_type,
            file_size=len(file_data),
            status="draft",
            send_via_email=send_via_email,
            web_access_enabled=web_access_enabled,
            uploaded_by=request.user.username,
            notes=notes,
            event=event,
            team_extras=team_extras,
        )

        messages.success(
            request,
            f"Team packet '{title}' uploaded successfully. Use 'Distribute Now' to send to all teams.",
        )
        return redirect("ops_packets_list")

    return render(request, "packets/ops_upload_packet.html", form_context)


@require_GET
@require_permission("gold_team")
def ops_packet_detail(request: HttpRequest, packet_id: int) -> HttpResponse:
    """View packet details and distribution status."""
    packet = get_object_or_404(TeamPacket, id=packet_id)

    distributions = packet.distributions.select_related("team", "team__school_info").order_by("team__team_number")
    teams = Team.objects.filter(is_active=True).order_by("team_number")

    context = {
        "packet": packet,
        "distributions": distributions,
        "stats": packet.get_distribution_stats(),
        "teams": teams,
        "nav_active": "ops_admin",
    }

    return render(request, "packets/ops_packet_detail.html", context)


@require_POST
@require_permission("gold_team")
def ops_distribute_packet(request: HttpRequest, packet_id: int) -> HttpResponse:
    """Manually trigger distribution of a packet."""
    packet = get_object_or_404(TeamPacket, id=packet_id)

    if packet.status != "draft":
        messages.error(request, f"Cannot distribute packet with status: {packet.get_status_display()}")
        return redirect("ops_packet_detail", packet_id=packet_id)

    try:
        service = PacketDistributionService()
        result = service.distribute_packet(packet)

        messages.success(
            request,
            f"Team packet distributed. Emails sent: {result['email_sent']}, Failed: {result['email_failed']}",
        )
    except Exception as e:
        messages.error(request, f"Distribution failed: {e}")

    return redirect("ops_packet_detail", packet_id=packet_id)


@require_POST
@require_permission("gold_team")
def ops_cancel_packet(request: HttpRequest, packet_id: int) -> HttpResponse:
    """Cancel a packet distribution."""
    packet = get_object_or_404(TeamPacket, id=packet_id)

    packet.status = "cancelled"
    packet.save(update_fields=["status", "updated_at"])

    messages.success(request, f"Packet '{packet.title}' has been cancelled.")
    return redirect("ops_packet_detail", packet_id=packet_id)


@require_POST
@require_permission("gold_team")
def ops_reset_packet(request: HttpRequest, packet_id: int) -> HttpResponse:
    """Reset a packet back to draft status, clearing failed distributions."""
    packet = get_object_or_404(TeamPacket, id=packet_id)

    # Reset failed distributions to pending
    packet.distributions.filter(email_status="failed").update(email_status="pending", email_error_message="")

    packet.status = "draft"
    packet.actual_distribution_time = None
    packet.save(update_fields=["status", "actual_distribution_time", "updated_at"])

    messages.success(request, f"Packet '{packet.title}' reset to draft.")
    return redirect("ops_packet_detail", packet_id=packet_id)


@require_POST
@require_permission("gold_team")
def ops_send_test_email(request: HttpRequest, packet_id: int) -> HttpResponse:
    """Send a test email for a packet to a specific address."""
    packet = get_object_or_404(TeamPacket, id=packet_id)
    email = request.POST.get("email", "").strip()
    team_id = request.POST.get("team_id", "").strip()

    if not email:
        messages.error(request, "Email address is required.")
        return redirect("ops_packet_detail", packet_id=packet_id)

    if not team_id:
        messages.error(request, "Please select a team.")
        return redirect("ops_packet_detail", packet_id=packet_id)

    team = get_object_or_404(Team, id=team_id)

    try:
        service = PacketDistributionService()
        service.send_test_packet_email(packet, team, email)
        messages.success(request, f"Test email sent to {email} as Team {team.team_number}.")
    except Exception as e:
        messages.error(request, f"Failed to send test email: {e}")

    return redirect("ops_packet_detail", packet_id=packet_id)


@require_POST
@require_permission("gold_team")
def ops_resend_team(request: HttpRequest, packet_id: int, team_id: int) -> HttpResponse:
    """Resend a packet email to a specific team, saving any email changes."""
    from team.models import SchoolInfo

    packet = get_object_or_404(TeamPacket, id=packet_id)
    team = get_object_or_404(Team, id=team_id)

    dist = PacketDistribution.objects.filter(packet=packet, team=team).first()
    if not dist:
        messages.error(request, f"No distribution record for Team {team.team_number}.")
        return redirect("ops_packet_detail", packet_id=packet_id)

    primary_email = request.POST.get("primary_email", "").strip()
    secondary_email = request.POST.get("secondary_email", "").strip()

    if not primary_email:
        messages.error(request, f"Primary email is required for Team {team.team_number}.")
        return redirect("ops_packet_detail", packet_id=packet_id)

    # Save email changes back to SchoolInfo
    school_info, _ = SchoolInfo.objects.get_or_create(
        team=team, defaults={"school_name": f"Team {team.team_number}", "contact_email": primary_email}
    )
    school_info.contact_email = primary_email
    school_info.secondary_email = secondary_email
    school_info.save(update_fields=["contact_email", "secondary_email"])

    # Build recipient list
    recipients = [primary_email]
    if secondary_email:
        recipients.append(secondary_email)

    try:
        dist.email_status = "pending"
        dist.email_error_message = ""
        dist.save(update_fields=["email_status", "email_error_message"])

        service = PacketDistributionService()
        service.send_packet_email(dist, override_emails=recipients)
        messages.success(request, f"Email resent to Team {team.team_number} ({', '.join(recipients)}).")
    except Exception as e:
        messages.error(request, f"Failed to resend to Team {team.team_number}: {e}")

    return redirect("ops_packet_detail", packet_id=packet_id)
