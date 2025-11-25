"""Tests for packet services."""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from team.models import SchoolInfo, Team

from ..models import PacketDistribution, TeamPacket
from ..services import PacketDistributionService


class PacketDistributionServiceTestCase(TestCase):
    """Test PacketDistributionService."""

    def setUp(self):
        """Create test data."""
        self.service = PacketDistributionService()

        # Create teams with school info
        for i in range(1, 4):
            team = Team.objects.create(
                team_number=i,
                team_name=f"Team {i}",
                authentik_group=f"WCComps_BlueTeam{i:02d}",
                is_active=True,
            )
            SchoolInfo.objects.create(
                team=team,
                school_name=f"School {i}",
                contact_email=f"team{i}@example.com",
            )

        self.packet = TeamPacket.objects.create(
            title="Test Packet",
            file_data=b"test file content",
            filename="test.pdf",
            mime_type="application/pdf",
            file_size=100,
            uploaded_by="testuser",
            status="draft",
            send_via_email=True,
            web_access_enabled=True,
        )

    def test_create_distributions_for_teams(self):
        """Test creating distributions for all teams."""
        created = self.service._create_distributions_for_teams(self.packet)

        self.assertEqual(created, 3)
        self.assertEqual(PacketDistribution.objects.count(), 3)

        # Verify distributions created for all teams
        for i in range(1, 4):
            team = Team.objects.get(team_number=i)
            dist = PacketDistribution.objects.get(packet=self.packet, team=team)
            self.assertEqual(dist.email_status, "pending")

    @patch("packets.services.EmailMultiAlternatives")
    def test_send_packet_email(self, mock_email_class):
        """Test sending packet email."""
        team = Team.objects.get(team_number=1)
        distribution = PacketDistribution.objects.create(packet=self.packet, team=team)

        # Mock email sending
        mock_email = MagicMock()
        mock_email_class.return_value = mock_email

        self.service.send_packet_email(distribution)

        # Verify email was sent
        mock_email.send.assert_called_once_with(fail_silently=False)

        # Verify distribution was marked as sent
        distribution.refresh_from_db()
        self.assertEqual(distribution.email_status, "sent")
        self.assertEqual(distribution.email_sent_to, "team1@example.com")

    @patch("packets.services.PacketDistributionService.send_packet_email")
    def test_distribute_packet(self, mock_send_email):
        """Test distributing packet."""
        result = self.service.distribute_packet(self.packet)

        # Verify distributions created
        self.assertEqual(result["created"], 3)
        self.assertEqual(PacketDistribution.objects.count(), 3)

        # Verify packet marked as distributing then completed
        self.packet.refresh_from_db()
        self.assertEqual(self.packet.status, "completed")
        self.assertIsNotNone(self.packet.actual_distribution_time)

    def test_record_packet_download(self):
        """Test recording packet download."""
        team = Team.objects.get(team_number=1)

        # First download creates distribution
        self.service.record_packet_download(self.packet, team, "testuser")

        distribution = PacketDistribution.objects.get(packet=self.packet, team=team)
        self.assertEqual(distribution.download_count, 1)
        self.assertEqual(distribution.downloaded_by, "testuser")

        # Second download increments count
        self.service.record_packet_download(self.packet, team, "testuser2")

        distribution.refresh_from_db()
        self.assertEqual(distribution.download_count, 2)
        self.assertEqual(distribution.downloaded_by, "testuser2")
