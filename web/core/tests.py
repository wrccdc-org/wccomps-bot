"""Tests for WCComps core functionality."""

from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from allauth.socialaccount.models import SocialAccount, SocialApp
from django.contrib.sites.models import Site
from .models import (
    Team,
    DiscordLink,
    LinkToken,
    Ticket,
    DiscordTask,
    CompetitionConfig,
)
import secrets


class TeamModelTests(TestCase):
    """Test Team model functionality."""

    def setUp(self) -> None:
        self.team = Team.objects.create(
            team_number=1,
            team_name="BlueTeam01",
            authentik_group="WCComps_BlueTeam01",
            max_members=10,
        )

    def test_team_creation(self) -> None:
        """Test team is created with correct attributes."""
        self.assertEqual(self.team.team_number, 1)
        self.assertEqual(self.team.team_name, "BlueTeam01")
        self.assertTrue(self.team.is_active)

    def test_team_string_representation(self) -> None:
        """Test team __str__ method."""
        self.assertEqual(str(self.team), "BlueTeam01")

    def test_get_member_count(self) -> None:
        """Test member count calculation."""
        self.assertEqual(self.team.get_member_count(), 0)

        DiscordLink.objects.create(
            discord_id=123456,
            discord_username="user1",
            authentik_username="team1user1",
            authentik_user_id="auth123",
            team=self.team,
            is_active=True,
        )
        self.assertEqual(self.team.get_member_count(), 1)

    def test_is_full(self) -> None:
        """Test team capacity checking."""
        self.assertFalse(self.team.is_full())

        for i in range(10):
            DiscordLink.objects.create(
                discord_id=100000 + i,
                discord_username=f"user{i}",
                authentik_username=f"team1user{i}",
                authentik_user_id=f"auth{i}",
                team=self.team,
                is_active=True,
            )

        self.assertTrue(self.team.is_full())

    def test_inactive_members_not_counted(self) -> None:
        """Test that inactive members don't count toward capacity."""
        DiscordLink.objects.create(
            discord_id=123456,
            discord_username="user1",
            authentik_username="team1user1",
            authentik_user_id="auth123",
            team=self.team,
            is_active=False,
        )
        self.assertEqual(self.team.get_member_count(), 0)


class DiscordLinkModelTests(TestCase):
    """Test DiscordLink model functionality."""

    def setUp(self) -> None:
        self.team = Team.objects.create(
            team_number=1, team_name="BlueTeam01", authentik_group="WCComps_BlueTeam01"
        )

    def test_link_creation_with_team(self) -> None:
        """Test creating a link with team."""
        link = DiscordLink.objects.create(
            discord_id=123456789,
            discord_username="testuser",
            authentik_username="team1user",
            authentik_user_id="auth123",
            team=self.team,
        )
        self.assertEqual(link.discord_id, 123456789)
        self.assertEqual(link.team, self.team)
        self.assertTrue(link.is_active)

    def test_link_creation_without_team(self) -> None:
        """Test creating a link without team (admin/support)."""
        link = DiscordLink.objects.create(
            discord_id=987654321,
            discord_username="adminuser",
            authentik_username="admin",
            authentik_user_id="auth999",
            team=None,
        )
        self.assertIsNone(link.team)
        self.assertTrue(link.is_active)

    def test_link_string_representation(self) -> None:
        """Test __str__ method."""
        link = DiscordLink.objects.create(
            discord_id=123456789,
            discord_username="testuser",
            authentik_username="team1user",
            authentik_user_id="auth123",
            team=self.team,
        )
        self.assertIn("testuser", str(link))
        self.assertIn("BlueTeam01", str(link))


class LinkTokenModelTests(TestCase):
    """Test LinkToken model functionality."""

    def test_token_creation(self) -> None:
        """Test creating a link token."""
        expires = timezone.now() + timedelta(minutes=15)
        token = LinkToken.objects.create(
            token=secrets.token_urlsafe(32),
            discord_id=123456789,
            discord_username="testuser",
            expires_at=expires,
        )
        self.assertFalse(token.used)
        self.assertFalse(token.is_expired())

    def test_token_expiration(self) -> None:
        """Test token expiration checking."""
        expires = timezone.now() - timedelta(minutes=1)
        token = LinkToken.objects.create(
            token=secrets.token_urlsafe(32),
            discord_id=123456789,
            discord_username="testuser",
            expires_at=expires,
        )
        self.assertTrue(token.is_expired())


class TicketModelTests(TestCase):
    """Test Ticket model functionality."""

    def setUp(self) -> None:
        self.team = Team.objects.create(
            team_number=1, team_name="BlueTeam01", authentik_group="WCComps_BlueTeam01"
        )

    def test_ticket_creation(self) -> None:
        """Test creating a ticket."""
        ticket = Ticket.objects.create(
            ticket_number="T001-001",
            team=self.team,
            category="network",
            title="Cannot connect to server",
            description="Getting timeout errors",
            hostname="web01",
            status="open",
        )
        self.assertEqual(ticket.status, "open")
        self.assertEqual(ticket.team, self.team)
        self.assertEqual(ticket.points_charged, 0)

    def test_ticket_string_representation(self) -> None:
        """Test ticket __str__ method."""
        ticket = Ticket.objects.create(
            ticket_number="T001-002",
            team=self.team,
            category="network",
            title="Issue",
            status="open",
        )
        self.assertIn("T001-002", str(ticket))
        self.assertIn("BlueTeam01", str(ticket))


# PointAdjustment model was removed - tests commented out


class CompetitionConfigModelTests(TestCase):
    """Test CompetitionConfig model functionality."""

    def test_get_config_singleton(self) -> None:
        """Test get_config creates singleton."""
        config1 = CompetitionConfig.get_config()
        config2 = CompetitionConfig.get_config()
        self.assertEqual(config1.pk, config2.pk)
        self.assertEqual(config1.pk, 1)

    def test_should_enable_applications_not_set(self) -> None:
        """Test should_enable when start time not set."""
        config = CompetitionConfig.get_config()
        config.competition_start_time = None
        config.applications_enabled = False
        config.save()

        self.assertFalse(config.should_enable_applications())

    def test_should_enable_applications_future(self) -> None:
        """Test should_enable when start time in future."""
        config = CompetitionConfig.get_config()
        config.competition_start_time = timezone.now() + timedelta(hours=1)
        config.applications_enabled = False
        config.save()

        self.assertFalse(config.should_enable_applications())

    def test_should_enable_applications_past(self) -> None:
        """Test should_enable when start time has passed."""
        config = CompetitionConfig.get_config()
        config.competition_start_time = timezone.now() - timedelta(hours=1)
        config.applications_enabled = False
        config.save()

        self.assertTrue(config.should_enable_applications())

    def test_should_enable_applications_already_enabled(self) -> None:
        """Test should_enable when already enabled."""
        config = CompetitionConfig.get_config()
        config.competition_start_time = timezone.now() - timedelta(hours=1)
        config.applications_enabled = True
        config.save()

        self.assertFalse(config.should_enable_applications())


class DiscordTaskModelTests(TestCase):
    """Test DiscordTask model functionality."""

    def test_task_creation(self) -> None:
        """Test creating a Discord task."""
        task = DiscordTask.objects.create(
            task_type="create_thread", payload={"ticket_id": 123}, status="pending"
        )
        self.assertEqual(task.status, "pending")
        self.assertEqual(task.retry_count, 0)

    def test_task_string_representation(self) -> None:
        """Test task __str__ method."""
        task = DiscordTask.objects.create(task_type="send_message", status="completed")
        self.assertIn("send_message", str(task))
        self.assertIn("completed", str(task))


class LinkFlowViewTests(TestCase):
    """Test the Discord linking flow views."""

    def setUp(self) -> None:
        self.client = Client()
        self.team = Team.objects.create(
            team_number=1,
            team_name="BlueTeam01",
            authentik_group="WCComps_BlueTeam01",
            max_members=10,
        )

        # Create test user
        self.user = User.objects.create_user(username="team01", password="testpass123")

        # Set up Authentik social account
        site = Site.objects.get_current()
        app = SocialApp.objects.create(
            provider="openid_connect",
            name="Authentik",
            client_id="test-client-id",
            secret="test-secret",
        )
        app.sites.add(site)

        self.social_account = SocialAccount.objects.create(
            user=self.user,
            provider="authentik",
            uid="auth123",
            extra_data={
                "preferred_username": "team01",
                "groups": ["WCComps_BlueTeam01"],
            },
        )

    def test_link_initiate_missing_token(self) -> None:
        """Test link initiate without token parameter."""
        response = self.client.get("/auth/link", follow=True)
        self.assertEqual(response.status_code, 400)

    def test_link_initiate_invalid_token(self) -> None:
        """Test link initiate with invalid token."""
        response = self.client.get("/auth/link?token=invalid", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid or expired token")

    def test_link_initiate_expired_token(self) -> None:
        """Test link initiate with expired token."""
        token = LinkToken.objects.create(
            token="expired-token",
            discord_id=123456789,
            discord_username="testuser",
            expires_at=timezone.now() - timedelta(minutes=1),
        )

        response = self.client.get(f"/auth/link?token={token.token}", follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Token expired")

    def test_link_initiate_valid_token(self) -> None:
        """Test link initiate with valid token."""
        token = LinkToken.objects.create(
            token="valid-token",
            discord_id=123456789,
            discord_username="testuser",
            expires_at=timezone.now() + timedelta(minutes=15),
        )

        response = self.client.get(f"/auth/link?token={token.token}")
        self.assertIn(response.status_code, [301, 302])

    def test_link_callback_team_full(self) -> None:
        """Test link callback when team is full."""
        for i in range(10):
            DiscordLink.objects.create(
                discord_id=100000 + i,
                discord_username=f"user{i}",
                authentik_username=f"team01user{i}",
                authentik_user_id=f"auth{i}",
                team=self.team,
                is_active=True,
            )

        token = LinkToken.objects.create(
            token="test-token",
            discord_id=999999,
            discord_username="newuser",
            expires_at=timezone.now() + timedelta(minutes=15),
        )

        session = self.client.session
        session["link_token"] = token.token
        session["discord_id"] = token.discord_id
        session["discord_username"] = token.discord_username
        session.save()

        self.client.force_login(self.user)
        response = self.client.get("/auth/callback", follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Team full")

    def test_successful_link_creates_discord_task(self) -> None:
        """Test successful link creates Discord task for role assignment."""
        token = LinkToken.objects.create(
            token="test-token",
            discord_id=123456789,
            discord_username="testuser",
            expires_at=timezone.now() + timedelta(minutes=15),
        )

        session = self.client.session
        session["link_token"] = token.token
        session["discord_id"] = token.discord_id
        session["discord_username"] = token.discord_username
        session.save()

        self.client.force_login(self.user)
        response = self.client.get("/auth/callback", follow=True)

        self.assertEqual(response.status_code, 200)

        # Check DiscordLink was created
        link = DiscordLink.objects.get(discord_id=123456789)
        self.assertEqual(link.team, self.team)
        self.assertTrue(link.is_active)

        # Check Discord tasks were created
        tasks = DiscordTask.objects.filter(
            task_type__in=["assign_role", "log_to_channel"]
        )
        self.assertGreater(tasks.count(), 0)

        # Check token was marked as used
        token.refresh_from_db()
        self.assertTrue(token.used)


class HomeViewTests(TestCase):
    """Test the home view."""

    def setUp(self) -> None:
        self.client = Client()
        self.user = User.objects.create_user(username="team01", password="testpass123")

        site = Site.objects.get_current()
        app = SocialApp.objects.create(
            provider="openid_connect",
            name="Authentik",
            client_id="test-client-id",
            secret="test-secret",
        )
        app.sites.add(site)

    def test_home_requires_login(self) -> None:
        """Test home page requires authentication."""
        response = self.client.get("/")
        self.assertIn(response.status_code, [301, 302])

    def test_home_with_team_account(self) -> None:
        """Test home page with team account."""
        team = Team.objects.create(
            team_number=1, team_name="BlueTeam01", authentik_group="WCComps_BlueTeam01"
        )

        SocialAccount.objects.create(
            user=self.user,
            provider="authentik",
            uid="auth123",
            extra_data={
                "preferred_username": "team01",
                "groups": ["WCComps_BlueTeam01"],
            },
        )

        self.client.force_login(self.user)
        response = self.client.get("/", follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["is_team"])
        self.assertEqual(response.context["team"], team)
