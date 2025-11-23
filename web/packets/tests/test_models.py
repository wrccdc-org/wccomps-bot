"""Tests for packet models."""

from django.test import TestCase
from django.utils import timezone

from team.models import Team

from ..models import PacketDistribution, TeamPacket


class TeamPacketTestCase(TestCase):
    """Test TeamPacket model."""

    def setUp(self):
        """Create test data."""
        self.packet = TeamPacket.objects.create(
            title="Test Packet",
            file_data=b"test file content",
            filename="test.pdf",
            mime_type="application/pdf",
            file_size=100,
            uploaded_by="testuser",
        )

    def test_packet_creation(self):
        """Test packet can be created."""
        self.assertEqual(self.packet.title, "Test Packet")
        self.assertEqual(self.packet.status, "draft")
        self.assertTrue(self.packet.send_via_email)
        self.assertTrue(self.packet.web_access_enabled)

    def test_is_ready_for_distribution(self):
        """Test packet readiness check."""
        # Draft packet is ready
        self.assertTrue(self.packet.is_ready_for_distribution())

        # Scheduled packet in future is not ready
        self.packet.status = "scheduled"
        self.packet.scheduled_distribution_time = timezone.now() + timezone.timedelta(
            hours=1
        )
        self.packet.save()
        self.assertFalse(self.packet.is_ready_for_distribution())

        # Scheduled packet in past is ready
        self.packet.scheduled_distribution_time = timezone.now() - timezone.timedelta(
            hours=1
        )
        self.packet.save()
        self.assertTrue(self.packet.is_ready_for_distribution())

        # Distributing packet is not ready
        self.packet.status = "distributing"
        self.packet.save()
        self.assertFalse(self.packet.is_ready_for_distribution())

    def test_mark_as_distributing(self):
        """Test marking packet as distributing."""
        self.packet.mark_as_distributing()
        self.assertEqual(self.packet.status, "distributing")
        self.assertIsNotNone(self.packet.actual_distribution_time)

    def test_mark_as_completed(self):
        """Test marking packet as completed."""
        self.packet.mark_as_completed()
        self.assertEqual(self.packet.status, "completed")


class PacketDistributionTestCase(TestCase):
    """Test PacketDistribution model."""

    def setUp(self):
        """Create test data."""
        self.team = Team.objects.create(
            team_number=1, team_name="Test Team", authentik_group="WCComps_BlueTeam01"
        )
        self.packet = TeamPacket.objects.create(
            title="Test Packet",
            file_data=b"test file content",
            filename="test.pdf",
            mime_type="application/pdf",
            file_size=100,
            uploaded_by="testuser",
        )
        self.distribution = PacketDistribution.objects.create(
            packet=self.packet, team=self.team
        )

    def test_distribution_creation(self):
        """Test distribution can be created."""
        self.assertEqual(self.distribution.email_status, "pending")
        self.assertEqual(self.distribution.download_count, 0)
        self.assertTrue(self.distribution.web_access_enabled)

    def test_mark_as_sent(self):
        """Test marking distribution as sent."""
        email = "test@example.com"
        self.distribution.mark_as_sent(email)
        self.assertEqual(self.distribution.email_status, "sent")
        self.assertEqual(self.distribution.email_sent_to, email)
        self.assertIsNotNone(self.distribution.email_sent_at)

    def test_mark_as_failed(self):
        """Test marking distribution as failed."""
        error = "SMTP connection failed"
        self.distribution.mark_as_failed(error)
        self.assertEqual(self.distribution.email_status, "failed")
        self.assertEqual(self.distribution.email_error_message, error)

    def test_record_download(self):
        """Test recording a download."""
        username = "testuser"
        self.distribution.record_download(username)

        self.assertEqual(self.distribution.download_count, 1)
        self.assertEqual(self.distribution.downloaded_by, username)
        self.assertIsNotNone(self.distribution.downloaded_at)
        self.assertIsNotNone(self.distribution.last_downloaded_at)

        # Record second download
        self.distribution.record_download("testuser2")
        self.assertEqual(self.distribution.download_count, 2)
        self.assertEqual(self.distribution.downloaded_by, "testuser2")
