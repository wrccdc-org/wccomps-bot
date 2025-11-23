"""
Tests for web views - these views had 0% coverage.

CRITICAL: These views handle:
- Authentication and authorization
- Ticket creation and management
- File uploads and downloads
- Cross-team data access

A bug could:
- Allow unauthorized access to other teams' tickets
- Expose sensitive files to wrong team
- Bypass authentication
- SQL injection via ticket filters
"""


import pytest
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from team.models import DiscordLink, Team
from ticketing.models import Ticket, TicketAttachment


@pytest.mark.django_db
class TestAuthenticationViews:
    """Test authentication and home view routing."""

    @pytest.fixture
    def client(self) -> Client:
        return Client()

    @pytest.fixture
    async def team_user(self) -> User:
        """Create a team user with proper Authentik setup."""
        user = await User.objects.acreate(
            username="teamuser",
            email="team@test.com",
        )

        team = await Team.objects.acreate(
            team_number=1,
            team_name="Test Team",
            authentik_group="WCComps_BlueTeam01",
            max_members=5,
        )

        await SocialAccount.objects.acreate(
            user=user,
            provider="authentik",
            uid="test-uid-team",
            extra_data={
                "id_token": {
                    "groups": ["WCComps_BlueTeam01"],
                    "preferred_username": "teamuser",
                }
            },
        )

        await DiscordLink.objects.acreate(
            discord_id=123456789,
            authentik_username="teamuser",
            is_active=True,
            team=team,
        )

        return user

    @pytest.fixture
    async def ops_user(self) -> User:
        """Create an ops user with gold team permissions."""
        user = await User.objects.acreate(
            username="opsuser",
            email="ops@test.com",
        )

        await SocialAccount.objects.acreate(
            user=user,
            provider="authentik",
            uid="test-uid-ops",
            extra_data={
                "id_token": {
                    "groups": ["WCComps_GoldTeam"],
                    "preferred_username": "opsuser",
                }
            },
        )

        return user

    def test_home_requires_login(self, client: Client) -> None:
        """Test that home view requires authentication."""
        response = client.get(reverse("home"))

        # Should redirect to login
        assert response.status_code == 302
        assert "/accounts/login" in response.url

    @pytest.mark.asyncio
    async def test_home_redirects_team_to_tickets(self, client: Client, team_user: User) -> None:
        """Test that team members are redirected to tickets page."""
        import os

        os.environ["TICKETING_ENABLED"] = "true"

        client.force_login(team_user)
        response = client.get(reverse("home"))

        assert response.status_code == 302
        assert response.url == reverse("team_tickets")

    @pytest.mark.asyncio
    async def test_home_redirects_ops_to_ops_tickets(self, client: Client, ops_user: User) -> None:
        """Test that ops users are redirected to ops ticket list."""
        import os

        os.environ["TICKETING_ENABLED"] = "true"

        client.force_login(ops_user)
        response = client.get(reverse("home"))

        assert response.status_code == 302
        assert response.url == reverse("ops_ticket_list")


@pytest.mark.django_db
class TestTicketViewAuthorization:
    """
    Test authorization for ticket views.

    CRITICAL: Teams should ONLY see their own tickets.
    BUG IF: Team A can view Team B's tickets (IDOR vulnerability).
    """

    @pytest.fixture
    def client(self) -> Client:
        return Client()

    @pytest.fixture
    async def team1_user(self) -> tuple[User, Team]:
        """Create Team 1 user."""
        user = await User.objects.acreate(
            username="team1user",
            email="team1@test.com",
        )

        team = await Team.objects.acreate(
            team_number=1,
            team_name="Team 1",
            authentik_group="WCComps_BlueTeam01",
            max_members=5,
        )

        await SocialAccount.objects.acreate(
            user=user,
            provider="authentik",
            uid="team1-uid",
            extra_data={
                "id_token": {
                    "groups": ["WCComps_BlueTeam01"],
                    "preferred_username": "team1user",
                }
            },
        )

        await DiscordLink.objects.acreate(
            discord_id=111111111,
            authentik_username="team1user",
            is_active=True,
            team=team,
        )

        return user, team

    @pytest.fixture
    async def team2_user(self) -> tuple[User, Team]:
        """Create Team 2 user."""
        user = await User.objects.acreate(
            username="team2user",
            email="team2@test.com",
        )

        team = await Team.objects.acreate(
            team_number=2,
            team_name="Team 2",
            authentik_group="WCComps_BlueTeam02",
            max_members=5,
        )

        await SocialAccount.objects.acreate(
            user=user,
            provider="authentik",
            uid="team2-uid",
            extra_data={
                "id_token": {
                    "groups": ["WCComps_BlueTeam02"],
                    "preferred_username": "team2user",
                }
            },
        )

        await DiscordLink.objects.acreate(
            discord_id=222222222,
            authentik_username="team2user",
            is_active=True,
            team=team,
        )

        return user, team

    @pytest.mark.asyncio
    async def test_cannot_view_other_team_ticket_detail(
        self, client: Client, team1_user: tuple[User, Team], team2_user: tuple[User, Team]
    ) -> None:
        """
        CRITICAL: Team 1 should NOT be able to view Team 2's ticket details.

        This is an IDOR (Insecure Direct Object Reference) vulnerability if it fails.
        """
        user1, team1 = team1_user
        user2, team2 = team2_user

        # Team 2 creates a ticket
        team2_ticket = await Ticket.objects.acreate(
            team=team2,
            title="Team 2 Secret Ticket",
            description="Confidential information for Team 2 only",
            category="other",
            created_by=user2,
        )

        # Team 1 tries to access Team 2's ticket
        client.force_login(user1)
        response = client.get(reverse("ticket_detail", args=[team2_ticket.id]))

        # Should be forbidden or not found (NOT 200 OK)
        assert response.status_code in [403, 404], (
            f"IDOR BUG: Team 1 accessed Team 2's ticket! Status: {response.status_code}"
        )

    @pytest.mark.asyncio
    async def test_cannot_comment_on_other_team_ticket(
        self, client: Client, team1_user: tuple[User, Team], team2_user: tuple[User, Team]
    ) -> None:
        """CRITICAL: Team 1 should NOT be able to comment on Team 2's tickets."""
        user1, team1 = team1_user
        user2, team2 = team2_user

        # Team 2 creates a ticket
        team2_ticket = await Ticket.objects.acreate(
            team=team2,
            title="Team 2 Ticket",
            description="Team 2 issue",
            category="other",
            created_by=user2,
        )

        # Team 1 tries to comment on Team 2's ticket
        client.force_login(user1)
        response = client.post(
            reverse("ticket_comment", args=[team2_ticket.id]),
            {"comment_text": "Malicious comment from Team 1"},
        )

        # Should be forbidden or not found
        assert response.status_code in [403, 404], (
            f"IDOR BUG: Team 1 commented on Team 2's ticket! Status: {response.status_code}"
        )

    @pytest.mark.asyncio
    async def test_cannot_cancel_other_team_ticket(
        self, client: Client, team1_user: tuple[User, Team], team2_user: tuple[User, Team]
    ) -> None:
        """CRITICAL: Team 1 should NOT be able to cancel Team 2's tickets."""
        user1, team1 = team1_user
        user2, team2 = team2_user

        # Team 2 creates a ticket
        team2_ticket = await Ticket.objects.acreate(
            team=team2,
            title="Team 2 Important Ticket",
            description="Critical issue",
            category="other",
            created_by=user2,
            status="open",
        )

        # Team 1 tries to cancel Team 2's ticket
        client.force_login(user1)
        response = client.post(reverse("ticket_cancel", args=[team2_ticket.id]))

        # Should be forbidden or not found
        assert response.status_code in [403, 404], (
            f"IDOR BUG: Team 1 cancelled Team 2's ticket! Status: {response.status_code}"
        )

        # Verify ticket is still open
        await team2_ticket.arefresh_from_db()
        assert team2_ticket.status == "open", "Ticket was cancelled when it shouldn't have been"


@pytest.mark.django_db
class TestTicketCreation:
    """Test ticket creation functionality."""

    @pytest.fixture
    def client(self) -> Client:
        return Client()

    @pytest.fixture
    async def team_user(self) -> tuple[User, Team]:
        """Create a team user."""
        user = await User.objects.acreate(
            username="teamuser",
            email="team@test.com",
        )

        team = await Team.objects.acreate(
            team_number=1,
            team_name="Test Team",
            authentik_group="WCComps_BlueTeam01",
            max_members=5,
        )

        await SocialAccount.objects.acreate(
            user=user,
            provider="authentik",
            uid="test-uid",
            extra_data={
                "id_token": {
                    "groups": ["WCComps_BlueTeam01"],
                    "preferred_username": "teamuser",
                }
            },
        )

        await DiscordLink.objects.acreate(
            discord_id=123456789,
            authentik_username="teamuser",
            is_active=True,
            team=team,
        )

        return user, team

    @pytest.mark.asyncio
    async def test_create_ticket_requires_login(self, client: Client) -> None:
        """Test that creating a ticket requires authentication."""
        response = client.get(reverse("create_ticket"))

        # Should redirect to login
        assert response.status_code == 302
        assert "/accounts/login" in response.url

    @pytest.mark.asyncio
    async def test_create_ticket_success(self, client: Client, team_user: tuple[User, Team]) -> None:
        """Test successful ticket creation."""
        user, team = team_user

        client.force_login(user)
        response = client.post(
            reverse("create_ticket"),
            {
                "title": "Test Ticket",
                "description": "This is a test ticket",
                "category": "technical",
            },
        )

        # Should redirect (success)
        assert response.status_code == 302

        # Verify ticket was created
        ticket = await Ticket.objects.aget(title="Test Ticket")
        assert ticket.team == team
        assert ticket.description == "This is a test ticket"
        assert ticket.category == "technical"
        assert ticket.created_by == user


@pytest.mark.django_db
class TestFileUploadDownloadViews:
    """
    Test file upload and download views.

    These views were tested for security in test_file_upload_security.py,
    but this tests that they actually WORK.
    """

    @pytest.fixture
    def client(self) -> Client:
        return Client()

    @pytest.fixture
    async def team_user_with_ticket(self) -> tuple[User, Team, Ticket]:
        """Create a team user with a ticket."""
        user = await User.objects.acreate(
            username="teamuser",
            email="team@test.com",
        )

        team = await Team.objects.acreate(
            team_number=1,
            team_name="Test Team",
            authentik_group="WCComps_BlueTeam01",
            max_members=5,
        )

        await SocialAccount.objects.acreate(
            user=user,
            provider="authentik",
            uid="test-uid",
            extra_data={
                "id_token": {
                    "groups": ["WCComps_BlueTeam01"],
                    "preferred_username": "teamuser",
                }
            },
        )

        await DiscordLink.objects.acreate(
            discord_id=123456789,
            authentik_username="teamuser",
            is_active=True,
            team=team,
        )

        ticket = await Ticket.objects.acreate(
            team=team,
            title="Test Ticket",
            description="Test",
            category="other",
            created_by=user,
        )

        return user, team, ticket

    @pytest.mark.asyncio
    async def test_upload_file_to_ticket(
        self, client: Client, team_user_with_ticket: tuple[User, Team, Ticket]
    ) -> None:
        """Test uploading a file to a ticket."""
        user, team, ticket = team_user_with_ticket

        # Create a test file
        test_file = SimpleUploadedFile(
            "test.txt",
            b"Test file content",
            content_type="text/plain",
        )

        client.force_login(user)
        response = client.post(
            reverse("ticket_attachment_upload", args=[ticket.id]),
            {"file": test_file},
        )

        # Should succeed (redirect or JSON success)
        assert response.status_code in [200, 302]

        # Verify attachment was created
        attachment = await TicketAttachment.objects.aget(ticket=ticket)
        assert attachment.filename == "test.txt"
        assert attachment.uploaded_by == user

    @pytest.mark.asyncio
    async def test_download_file_from_ticket(
        self, client: Client, team_user_with_ticket: tuple[User, Team, Ticket]
    ) -> None:
        """Test downloading a file from a ticket."""
        user, team, ticket = team_user_with_ticket

        # Create an attachment
        attachment = await TicketAttachment.objects.acreate(
            ticket=ticket,
            filename="test.txt",
            content_type="text/plain",
            file_data=b"Test file content",
            file_size=len(b"Test file content"),
            uploaded_by=user,
        )

        client.force_login(user)
        response = client.get(reverse("ticket_attachment_download", args=[ticket.id, attachment.id]))

        # Should succeed
        assert response.status_code == 200
        assert response["Content-Type"] == "text/plain"
        assert b"Test file content" in response.content

        # CRITICAL: Should have Content-Disposition: attachment
        assert "attachment" in response["Content-Disposition"].lower()


@pytest.mark.django_db
class TestOpsViews:
    """Test ops team views."""

    @pytest.fixture
    def client(self) -> Client:
        return Client()

    @pytest.fixture
    async def ops_user(self) -> User:
        """Create an ops user."""
        user = await User.objects.acreate(
            username="opsuser",
            email="ops@test.com",
        )

        await SocialAccount.objects.acreate(
            user=user,
            provider="authentik",
            uid="ops-uid",
            extra_data={
                "id_token": {
                    "groups": ["WCComps_GoldTeam"],
                    "preferred_username": "opsuser",
                }
            },
        )

        return user

    @pytest.fixture
    async def team_with_ticket(self) -> tuple[Team, Ticket]:
        """Create a team with a ticket."""
        team = await Team.objects.acreate(
            team_number=1,
            team_name="Test Team",
            authentik_group="WCComps_BlueTeam01",
            max_members=5,
        )

        user = await User.objects.acreate(
            username="teamuser",
            email="team@test.com",
        )

        ticket = await Ticket.objects.acreate(
            team=team,
            title="Test Ticket",
            description="Test",
            category="other",
            created_by=user,
            ticket_number="BT01-00001",
        )

        return team, ticket

    @pytest.mark.asyncio
    async def test_ops_can_view_ticket_list(self, client: Client, ops_user: User) -> None:
        """Test that ops users can view the ticket list."""
        client.force_login(ops_user)
        response = client.get(reverse("ops_ticket_list"))

        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_ops_can_claim_ticket(
        self, client: Client, ops_user: User, team_with_ticket: tuple[Team, Ticket]
    ) -> None:
        """Test that ops users can claim tickets."""
        team, ticket = team_with_ticket

        client.force_login(ops_user)
        response = client.post(reverse("ops_ticket_claim", args=[ticket.ticket_number]))

        # Should succeed (redirect or JSON success)
        assert response.status_code in [200, 302]

        # Verify ticket was claimed
        await ticket.arefresh_from_db()
        assert ticket.claimed_by == ops_user

    @pytest.mark.asyncio
    async def test_ops_can_resolve_ticket(
        self, client: Client, ops_user: User, team_with_ticket: tuple[Team, Ticket]
    ) -> None:
        """Test that ops users can resolve tickets."""
        team, ticket = team_with_ticket

        # First claim the ticket
        ticket.claimed_by = ops_user
        await ticket.asave()

        client.force_login(ops_user)
        response = client.post(
            reverse("ops_ticket_resolve", args=[ticket.ticket_number]),
            {"resolution_notes": "Fixed the issue"},
        )

        # Should succeed
        assert response.status_code in [200, 302]

        # Verify ticket was resolved
        await ticket.arefresh_from_db()
        assert ticket.status == "resolved"


@pytest.mark.django_db
class TestHealthCheck:
    """Test health check endpoint."""

    @pytest.fixture
    def client(self) -> Client:
        return Client()

    def test_health_check_returns_200(self, client: Client) -> None:
        """Test that health check endpoint returns 200 OK."""
        response = client.get(reverse("health_check"))

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
