"""Services for packet distribution."""

import logging
from typing import Optional

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from team.models import SchoolInfo, Team

from .models import PacketDistribution, TeamPacket

logger = logging.getLogger(__name__)


class PacketDistributionService:
    """Service for distributing team packets."""

    def distribute_packet(self, packet: TeamPacket) -> dict[str, int]:
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

    def _create_distributions_for_teams(self, packet: TeamPacket) -> int:
        """Create PacketDistribution records for all active teams."""
        teams = Team.objects.filter(is_active=True)
        distributions = []

        for team in teams:
            # Check if distribution already exists
            if not PacketDistribution.objects.filter(
                packet=packet, team=team
            ).exists():
                distributions.append(
                    PacketDistribution(
                        packet=packet,
                        team=team,
                        web_access_enabled=packet.web_access_enabled,
                    )
                )

        if distributions:
            PacketDistribution.objects.bulk_create(distributions)
            logger.info(
                f"Created {len(distributions)} distributions for packet {packet.id}"
            )

        return len(distributions)

    def _send_emails_for_packet(self, packet: TeamPacket) -> dict[str, int]:
        """Send emails for all pending distributions of a packet."""
        distributions = PacketDistribution.objects.filter(
            packet=packet, email_status="pending"
        ).select_related("team")

        sent_count = 0
        failed_count = 0

        for dist in distributions:
            try:
                self.send_packet_email(dist)
                sent_count += 1
            except Exception as e:
                logger.error(
                    f"Failed to send packet email to team {dist.team.team_number}: {e}"
                )
                dist.mark_as_failed(str(e))
                failed_count += 1

        return {"sent": sent_count, "failed": failed_count}

    def send_packet_email(self, distribution: PacketDistribution) -> None:
        """
        Send packet email to a team.

        Raises:
            Exception: If email sending fails
        """
        packet = distribution.packet
        team = distribution.team

        # Get school email from SchoolInfo
        email_address = self._get_team_email(team)
        if not email_address:
            raise ValueError(f"No email address for team {team.team_number}")

        # Prepare email context
        context = {
            "packet": packet,
            "team": team,
            "distribution": distribution,
            "download_url": f"{settings.BASE_URL}/packets/download/{packet.id}/",
        }

        # Render email templates
        subject = f"WCComps: {packet.title}"
        text_content = render_to_string("packets/emails/packet_notification.txt", context)
        html_content = render_to_string("packets/emails/packet_notification.html", context)

        # Create email
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email_address],
        )
        email.attach_alternative(html_content, "text/html")

        # Send email
        email.send(fail_silently=False)

        # Mark as sent
        distribution.mark_as_sent(email_address)
        logger.info(
            f"Sent packet {packet.id} to team {team.team_number} at {email_address}"
        )

    def _get_team_email(self, team: Team) -> Optional[str]:
        """Get email address for a team from SchoolInfo."""
        try:
            school_info = SchoolInfo.objects.get(team=team)
            return school_info.contact_email
        except SchoolInfo.DoesNotExist:
            logger.warning(f"No SchoolInfo found for team {team.team_number}")
            return None

    def record_packet_download(
        self, packet: TeamPacket, team: Team, username: str
    ) -> None:
        """Record that a team downloaded a packet."""
        with transaction.atomic():
            distribution, created = PacketDistribution.objects.get_or_create(
                packet=packet,
                team=team,
                defaults={"web_access_enabled": packet.web_access_enabled},
            )
            distribution.record_download(username)
            logger.info(
                f"Team {team.team_number} downloaded packet {packet.id} "
                f"(download #{distribution.download_count})"
            )


class ScheduledPacketDistributor:
    """Service for checking and distributing scheduled packets."""

    def process_scheduled_packets(self) -> dict[str, int]:
        """
        Process all packets scheduled for distribution.

        Returns:
            Dictionary with counts of packets processed
        """
        now = timezone.now()

        # Find packets ready for distribution
        packets = TeamPacket.objects.filter(
            status="scheduled",
            scheduled_distribution_time__lte=now,
        )

        service = PacketDistributionService()
        processed = 0
        failed = 0

        for packet in packets:
            try:
                logger.info(f"Processing scheduled packet: {packet.title}")
                service.distribute_packet(packet)
                processed += 1
            except Exception as e:
                logger.error(f"Failed to distribute packet {packet.id}: {e}")
                failed += 1

        if processed > 0:
            logger.info(f"Processed {processed} scheduled packet(s), {failed} failed")

        return {"processed": processed, "failed": failed}
