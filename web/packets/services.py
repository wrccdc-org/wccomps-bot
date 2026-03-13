"""Services for team packet distribution."""

import json
import logging
from collections.abc import Iterator

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from registration.models import Event, EventTeamAssignment, TeamRegistration

from core.authentik_manager import AuthentikManager
from core.authentik_utils import generate_blueteam_password
from team.models import SchoolInfo, Team

from .models import Packet, PacketDistribution

logger = logging.getLogger(__name__)


from core.utils import ndjson_progress as _progress


class PacketDistributionService:
    """Service for distributing team packets."""

    def distribute_packet(self, packet: Packet) -> dict[str, int]:
        """
        Distribute a packet to all teams.

        Returns:
            Dictionary with counts: {
                'total': total teams,
                'email_sent': emails sent,
                'email_failed': emails failed,
                'created': new distributions created
            }
        """
        if not packet.is_ready_for_distribution():
            raise ValueError(f"Packet {packet.id} is not ready for distribution")

        if not packet.event:
            raise ValueError("Packet must be linked to an event for distribution")

        # Mark packet as distributing
        packet.mark_as_distributing()

        # Create distribution records for all active teams
        distributions_created = self._create_distributions_for_teams(packet)

        # Send emails if enabled
        email_stats = {"sent": 0, "failed": 0}
        if packet.send_via_email:
            email_stats = self._send_emails_for_packet(packet)

        # Mark packet as completed if all emails sent
        if email_stats["failed"] == 0:
            packet.mark_as_completed()

        return {
            "total": Team.objects.filter(is_active=True).count(),
            "email_sent": email_stats["sent"],
            "email_failed": email_stats["failed"],
            "created": distributions_created,
        }

    def _create_distributions_for_teams(self, packet: Packet) -> int:
        """Create PacketDistribution records for active teams with contact emails."""
        teams = Team.objects.filter(is_active=True).exclude(school_info=None)

        # Get teams that don't already have distributions
        existing_teams = PacketDistribution.objects.filter(packet=packet).values_list("team_id", flat=True)
        teams_to_create = teams.exclude(id__in=existing_teams)

        # Create distributions for teams that don't have them
        distributions = [
            PacketDistribution(
                packet=packet,
                team=team,
                web_access_enabled=packet.web_access_enabled,
            )
            for team in teams_to_create
        ]

        if distributions:
            PacketDistribution.objects.bulk_create(distributions)
            logger.info(f"Created {len(distributions)} distributions for packet {packet.id}")

        return len(distributions)

    def _send_emails_for_packet(self, packet: Packet) -> dict[str, int]:
        """Send emails for all pending distributions of a packet."""
        distributions = PacketDistribution.objects.filter(packet=packet, email_status="pending").select_related("team")

        sent_count = 0
        failed_count = 0

        for dist in distributions:
            try:
                self.send_packet_email(dist)
                sent_count += 1
            except Exception as e:
                logger.error(f"Failed to send packet email to team {dist.team.team_number}: {e}")
                dist.mark_as_failed(str(e))
                failed_count += 1

        return {"sent": sent_count, "failed": failed_count}

    def _ensure_team_credentials(self, event: Event, team: Team) -> EventTeamAssignment:
        """Ensure an EventTeamAssignment with credentials exists for this team+event.

        Side effects (on first call per team+event):
            - Creates TeamRegistration from SchoolInfo
            - Creates EventTeamAssignment
            - Generates password and sets it in Authentik via API
        """
        assignment = EventTeamAssignment.objects.filter(event=event, team=team).first()

        if not assignment:
            # Create a TeamRegistration from SchoolInfo if needed
            school_info = SchoolInfo.objects.filter(team=team).first()
            school_name = school_info.school_name if school_info else f"Team {team.team_number}"

            registration, _ = TeamRegistration.objects.get_or_create(
                school_name=school_name,
                defaults={"status": "approved"},
            )
            assignment = EventTeamAssignment.objects.create(event=event, registration=registration, team=team)
            logger.info(f"Created EventTeamAssignment for team {team.team_number} in {event.name}")

        if not assignment.password_generated:
            password = generate_blueteam_password()
            auth_manager = AuthentikManager()
            success, error = auth_manager.reset_blueteam_password(team.team_number, password)
            if not success:
                raise ValueError(f"Failed to set Authentik password for team {team.team_number}: {error}")
            assignment.password_generated = password
            assignment.save(update_fields=["password_generated"])
            logger.info(f"Generated credentials for team {team.team_number}")

        return assignment

    def send_packet_email(self, distribution: PacketDistribution, override_emails: list[str] | None = None) -> None:
        """
        Send packet email to a team.

        Args:
            distribution: The distribution record to send for.
            override_emails: If provided, send to these addresses instead of SchoolInfo lookup.

        Raises:
            Exception: If email sending fails
        """
        packet = distribution.packet
        team = distribution.team

        if not packet.event:
            raise ValueError("Packet must be linked to an event for distribution")

        # Determine recipients
        if override_emails:
            recipients = override_emails
        else:
            email_address = self._get_team_email(team)
            if not email_address:
                raise ValueError(f"No email address for team {team.team_number}")
            recipients = [email_address]

        # Ensure credentials exist (creates assignment + password if needed)
        assignment = self._ensure_team_credentials(packet.event, team)

        # Prepare email context
        username = f"team{team.team_number:02d}"
        raw_extras = packet.team_extras.get(str(team.team_number), {}) if packet.team_extras else {}
        # Format keys for display: "api_key" -> "API Key", "max_spend_usd" -> "Max Spend USD"
        team_extras = {k.replace("_", " ").title(): v for k, v in raw_extras.items()}
        context = {
            "packet": packet,
            "team": team,
            "distribution": distribution,
            "username": username,
            "password": assignment.password_generated,
            "team_extras": team_extras,
        }

        # Render email templates
        subject = f"WCComps: {packet.title}"
        text_content = render_to_string("packets/emails/packet_notification.txt", context)
        html_content = render_to_string("packets/emails/packet_notification.html", context)

        # Create email with packet attached
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
            reply_to=[settings.DEFAULT_REPLY_TO_EMAIL],
        )
        email.attach_alternative(html_content, "text/html")
        email.attach(packet.filename, bytes(packet.file_data), packet.mime_type)

        # Send email
        email.send(fail_silently=False)

        # Mark as sent
        sent_to = ", ".join(recipients)
        distribution.mark_as_sent(sent_to)
        logger.info(f"Sent packet {packet.id} to team {team.team_number} at {sent_to}")

    def send_test_packet_email(self, packet: Packet, team: Team, email: str) -> None:
        """Send a test packet email to a specific address without creating distribution records."""
        if not packet.event:
            raise ValueError("Packet must be linked to an event")

        # Ensure credentials exist (creates assignment + password if needed)
        assignment = self._ensure_team_credentials(packet.event, team)

        username = f"team{team.team_number:02d}"
        raw_extras = packet.team_extras.get(str(team.team_number), {}) if packet.team_extras else {}
        team_extras = {k.replace("_", " ").title(): v for k, v in raw_extras.items()}
        context = {
            "packet": packet,
            "team": team,
            "username": username,
            "password": assignment.password_generated,
            "team_extras": team_extras,
        }

        subject = f"[TEST] WCComps: {packet.title}"
        text_content = render_to_string("packets/emails/packet_notification.txt", context)
        html_content = render_to_string("packets/emails/packet_notification.html", context)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
            reply_to=[settings.DEFAULT_REPLY_TO_EMAIL],
        )
        msg.attach_alternative(html_content, "text/html")
        msg.attach(packet.filename, bytes(packet.file_data), packet.mime_type)
        msg.send(fail_silently=False)

        logger.info(f"Sent test email for packet {packet.id} (team {team.team_number}) to {email}")

    def _get_team_email(self, team: Team) -> str | None:
        """Get email address for a team from SchoolInfo."""
        try:
            school_info = SchoolInfo.objects.get(team=team)
            return school_info.contact_email
        except SchoolInfo.DoesNotExist:
            logger.warning(f"No SchoolInfo found for team {team.team_number}")
            return None

    def record_packet_download(self, packet: Packet, team: Team, username: str) -> None:
        """Record that a team downloaded a packet."""
        with transaction.atomic():
            distribution, created = PacketDistribution.objects.get_or_create(
                packet=packet,
                team=team,
                defaults={"web_access_enabled": packet.web_access_enabled},
            )
            distribution.record_download(username)
            logger.info(
                f"Team {team.team_number} downloaded packet {packet.id} (download #{distribution.download_count})"
            )

    def stream_distribute_packet(self, packet: Packet) -> Iterator[str]:
        """Distribute a packet with streaming progress."""
        if not packet.event:
            yield json.dumps({"done": True, "success": False, "message": "Packet must be linked to an event"}) + "\n"
            return

        packet.mark_as_distributing()
        self._create_distributions_for_teams(packet)

        distributions = list(
            PacketDistribution.objects.filter(packet=packet, email_status="pending").select_related("team")
        )
        total = len(distributions)

        if total == 0:
            packet.mark_as_completed()
            yield json.dumps({"done": True, "success": True, "message": "No teams to distribute to"}) + "\n"
            return

        sent = 0
        failed = 0
        for i, dist in enumerate(distributions, 1):
            try:
                self.send_packet_email(dist)
                sent += 1
                yield _progress(f"Sent to Team {dist.team.team_number}", i, total)
            except Exception as e:
                logger.error(f"Failed to send packet email to team {dist.team.team_number}: {e}")
                dist.mark_as_failed(str(e))
                failed += 1
                yield _progress(f"Failed Team {dist.team.team_number}: {e}", i, total, ok=False)

        if failed == 0:
            packet.mark_as_completed()

        yield (
            json.dumps(
                {
                    "done": True,
                    "success": failed == 0,
                    "message": f"Sent {sent}, failed {failed}" if failed else f"Distributed to {sent} teams",
                }
            )
            + "\n"
        )

    def stream_resend_failed(self, packet: Packet) -> Iterator[str]:
        """Resend failed distributions with streaming progress."""
        failed_dists = list(
            PacketDistribution.objects.filter(packet=packet, email_status="failed").select_related("team")
        )
        total = len(failed_dists)

        if total == 0:
            yield json.dumps({"done": True, "success": True, "message": "No failed distributions to resend"}) + "\n"
            return

        # Reset to pending
        PacketDistribution.objects.filter(packet=packet, email_status="failed").update(
            email_status="pending", email_error_message=""
        )

        # Re-fetch after update
        for dist in failed_dists:
            dist.refresh_from_db()

        sent = 0
        still_failed = 0
        for i, dist in enumerate(failed_dists, 1):
            try:
                self.send_packet_email(dist)
                sent += 1
                yield _progress(f"Resent to Team {dist.team.team_number}", i, total)
            except Exception as e:
                logger.error(f"Failed to resend to team {dist.team.team_number}: {e}")
                dist.mark_as_failed(str(e))
                still_failed += 1
                yield _progress(f"Failed Team {dist.team.team_number}: {e}", i, total, ok=False)

        if still_failed == 0:
            packet.mark_as_completed()

        yield (
            json.dumps(
                {
                    "done": True,
                    "success": still_failed == 0,
                    "message": f"Resent {sent}, failed {still_failed}" if still_failed else f"Resent to {sent} teams",
                }
            )
            + "\n"
        )
