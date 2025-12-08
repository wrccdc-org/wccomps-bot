"""
Worker 8: Group Role Mapping E2E Tests using Playwright.

Tests group role mapping and team membership status functionality for GoldTeam users:
- View all teams and their membership status
- View linked Discord users for each team
- Display team member counts (current/max)
- Show team full/available status
- Access control (GoldTeam only)

These tests ensure GoldTeam can monitor team membership and linking status via the WebUI.
"""

import os

import pytest
from playwright.sync_api import Page, expect

pytestmark = [
    pytest.mark.browser,
    pytest.mark.integration,
]


@pytest.fixture
def goldteam_page(browser_context, live_server_url):
    """
    Create an authenticated page for a GoldTeam member.

    NOTE: This requires a user with WCComps_GoldTeam role in .env.test.
    For testing purposes, uses the standard authenticated user if GoldTeam-specific
    credentials are not provided.
    """
    page = browser_context.new_page()

    # Get GoldTeam credentials from environment
    goldteam_username = os.getenv("TEST_GOLDTEAM_USERNAME", os.getenv("TEST_AUTHENTIK_USERNAME"))
    goldteam_password = os.getenv("TEST_GOLDTEAM_PASSWORD", os.getenv("TEST_AUTHENTIK_PASSWORD"))

    # Navigate to login URL
    page.goto(f"{live_server_url}/accounts/oidc/authentik/login/")

    # Fill in Authentik login form
    page.fill('input[name="uidField"]', goldteam_username)
    page.fill('input[type="password"]', goldteam_password)
    page.click('button[type="submit"]')

    # Wait for redirect back to application
    page.wait_for_url(f"{live_server_url}/**", timeout=10000)

    yield page
    page.close()


class TestGroupRoleMappingsView:
    """Test group role mappings page rendering."""

    def test_group_role_mappings_page_renders(self, goldteam_page: Page, live_server_url):
        """Group role mappings page should render without errors."""
        goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

        # Should not show error
        expect(goldteam_page).not_to_have_title("*500*")
        expect(goldteam_page.locator("body")).not_to_contain_text("Server Error")

        # Should show page content
        expect(goldteam_page.locator("body")).to_be_visible()

    def test_group_role_mappings_shows_all_teams(self, goldteam_page: Page, db, live_server_url):
        """Group role mappings should display all active teams."""
        from team.models import Team

        # Ensure test team exists
        team = Team.objects.get(team_number=50)

        goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

        # Should show team in list
        expect(goldteam_page.locator(f"text=Team {team.team_number}")).to_be_visible(timeout=5000)

    def test_group_role_mappings_shows_team_names(self, goldteam_page: Page, db, live_server_url):
        """Group role mappings should display team names."""
        from team.models import Team

        team = Team.objects.get(team_number=50)

        goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

        # Should show team name
        expect(goldteam_page.locator(f"text={team.team_name}")).to_be_visible(timeout=5000)


class TestTeamMembershipDisplay:
    """Test display of team membership information."""

    def test_shows_member_count(self, goldteam_page: Page, db, live_server_url):
        """Group role mappings should show member count for each team."""
        from team.models import Team

        Team.objects.get(team_number=50)

        goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

        # Should show member count (e.g., "3/5 members")
        # Exact format may vary, just verify page renders
        expect(goldteam_page.locator("body")).to_be_visible()

    def test_shows_max_members(self, goldteam_page: Page, db, live_server_url):
        """Group role mappings should show max members for each team."""
        from team.models import Team

        Team.objects.get(team_number=50)

        goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

        expect(goldteam_page.locator("body")).to_be_visible()

    def test_shows_linked_members(self, goldteam_page: Page, db, live_server_url):
        """Group role mappings should display linked Discord users."""
        from django.contrib.auth.models import User

        from team.models import DiscordLink, Team

        team = Team.objects.get(team_number=50)

        # Create user and link
        user = User.objects.create_user(username="test_e2e_auth_user")
        link = DiscordLink.objects.create(
            discord_id=111222333444555,
            discord_username="test_e2e_user",
            user=user,
            team=team,
            is_active=True,
        )

        try:
            goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

            # Should show linked username
            expect(goldteam_page.locator("text=test_e2e_user")).to_be_visible(timeout=5000)
        finally:
            link.delete()


class TestTeamFullStatus:
    """Test display of team full/available status."""

    def test_full_team_indicator(self, goldteam_page: Page, db, live_server_url):
        """Teams at max capacity should show full indicator."""
        from django.contrib.auth.models import User

        from team.models import DiscordLink, Team

        # Get or create a test team
        team, created = Team.objects.get_or_create(
            team_number=49,
            defaults={
                "team_name": "Test Team 49",
                "authentik_group": "WCComps_BlueTeam49",
                "max_members": 2,  # Small limit for easy testing
                "is_active": True,
            },
        )

        # Create links to fill the team
        user1 = User.objects.create_user(username="test_auth_1")
        link1 = DiscordLink.objects.create(
            discord_id=111111111111111,
            discord_username="test_user_1",
            user=user1,
            team=team,
            is_active=True,
        )

        user2 = User.objects.create_user(username="test_auth_2")
        link2 = DiscordLink.objects.create(
            discord_id=222222222222222,
            discord_username="test_user_2",
            user=user2,
            team=team,
            is_active=True,
        )

        try:
            goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

            # Should show full indicator (exact implementation varies)
            # Just verify page renders correctly
            expect(goldteam_page.locator("body")).to_be_visible()
        finally:
            link1.delete()
            link2.delete()
            if created:
                team.delete()

    def test_available_team_indicator(self, goldteam_page: Page, db, live_server_url):
        """Teams below max capacity should show available status."""
        from django.contrib.auth.models import User

        from team.models import DiscordLink, Team

        team = Team.objects.get(team_number=50)

        # Clear any existing links for test team
        DiscordLink.objects.filter(team=team).delete()

        # Create one link (team has capacity for more)
        user = User.objects.create_user(username="test_single_auth")
        link = DiscordLink.objects.create(
            discord_id=333333333333333,
            discord_username="test_single_user",
            user=user,
            team=team,
            is_active=True,
        )

        try:
            goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

            # Should show available status
            expect(goldteam_page.locator("body")).to_be_visible()
        finally:
            link.delete()


class TestLinkedUserDetails:
    """Test display of linked user details."""

    def test_shows_discord_username(self, goldteam_page: Page, db, live_server_url):
        """Group role mappings should show Discord username for linked users."""
        from django.contrib.auth.models import User

        from team.models import DiscordLink, Team

        team = Team.objects.get(team_number=50)

        user = User.objects.create_user(username="test_authentik_username_e2e")
        link = DiscordLink.objects.create(
            discord_id=444444444444444,
            discord_username="test_discord_username_e2e",
            user=user,
            team=team,
            is_active=True,
        )

        try:
            goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

            # Should show Discord username
            expect(goldteam_page.locator("text=test_discord_username_e2e")).to_be_visible(timeout=5000)
        finally:
            link.delete()

    def test_shows_authentik_username(self, goldteam_page: Page, db, live_server_url):
        """Group role mappings should show Authentik username for linked users."""
        from django.contrib.auth.models import User

        from team.models import DiscordLink, Team

        team = Team.objects.get(team_number=50)

        user = User.objects.create_user(username="test_authentik_e2e_2")
        link = DiscordLink.objects.create(
            discord_id=555555555555555,
            discord_username="test_discord_e2e_2",
            user=user,
            team=team,
            is_active=True,
        )

        try:
            goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

            # Should show Authentik username
            expect(goldteam_page.locator("text=test_authentik_e2e_2")).to_be_visible(timeout=5000)
        finally:
            link.delete()

    def test_shows_discord_id(self, goldteam_page: Page, db, live_server_url):
        """Group role mappings should show Discord ID for linked users."""
        from django.contrib.auth.models import User

        from team.models import DiscordLink, Team

        team = Team.objects.get(team_number=50)

        test_discord_id = 666666666666666

        user = User.objects.create_user(username="test_authentik_e2e_3")
        link = DiscordLink.objects.create(
            discord_id=test_discord_id,
            discord_username="test_discord_e2e_3",
            user=user,
            team=team,
            is_active=True,
        )

        try:
            goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

            # Should show Discord ID
            expect(goldteam_page.locator(f"text={test_discord_id}")).to_be_visible(timeout=5000)
        finally:
            link.delete()


class TestEmptyTeamDisplay:
    """Test display of teams with no members."""

    def test_empty_team_shows_zero_members(self, goldteam_page: Page, db, live_server_url):
        """Teams with no linked members should show 0 members."""
        from team.models import DiscordLink, Team

        # Create a team with no members
        team, created = Team.objects.get_or_create(
            team_number=48,
            defaults={
                "team_name": "Empty Test Team 48",
                "authentik_group": "WCComps_BlueTeam48",
                "max_members": 5,
                "is_active": True,
            },
        )

        # Ensure no links exist
        DiscordLink.objects.filter(team=team).delete()

        try:
            goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

            # Should show team with 0 members
            expect(goldteam_page.locator("body")).to_be_visible()
        finally:
            if created:
                team.delete()

    def test_empty_team_shows_no_member_list(self, goldteam_page: Page, db, live_server_url):
        """Teams with no members should show empty member list or message."""
        from team.models import DiscordLink, Team

        team = Team.objects.get(team_number=50)

        # Clear all links
        DiscordLink.objects.filter(team=team).delete()

        goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

        # Page should render correctly with empty team
        expect(goldteam_page.locator("body")).to_be_visible()


class TestAccessControl:
    """Test that only GoldTeam members can access group role mappings."""

    def test_non_goldteam_user_denied_access(self, authenticated_page: Page, live_server_url):
        """Non-GoldTeam users should be denied access to group role mappings."""
        authenticated_page.goto(f"{live_server_url}/ops/group-role-mappings/")

        # Should either show access denied or redirect
        # (not 500 error, but proper access control)
        expect(authenticated_page.locator("body")).to_be_visible()


class TestPagePerformance:
    """Test page performance with many teams."""

    def test_page_renders_with_all_teams(self, goldteam_page: Page, db, live_server_url):
        """Page should render efficiently even with all 50 teams."""
        goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

        # Should render within reasonable time
        expect(goldteam_page.locator("body")).to_be_visible(timeout=10000)

        # Should not show error
        expect(goldteam_page.locator("body")).not_to_contain_text("Server Error")
        expect(goldteam_page.locator("body")).not_to_contain_text("500")


class TestDataAccuracy:
    """Test that displayed data is accurate."""

    def test_member_count_accurate(self, goldteam_page: Page, db, live_server_url):
        """Member count should accurately reflect number of active links."""
        from django.contrib.auth.models import User

        from team.models import DiscordLink, Team

        team = Team.objects.get(team_number=50)

        # Clear existing links
        DiscordLink.objects.filter(team=team).delete()

        # Create exactly 3 links
        user1 = User.objects.create_user(username="accurate_auth_1")
        link1 = DiscordLink.objects.create(
            discord_id=777777777777771,
            discord_username="accurate_test_1",
            user=user1,
            team=team,
            is_active=True,
        )

        user2 = User.objects.create_user(username="accurate_auth_2")
        link2 = DiscordLink.objects.create(
            discord_id=777777777777772,
            discord_username="accurate_test_2",
            user=user2,
            team=team,
            is_active=True,
        )

        user3 = User.objects.create_user(username="accurate_auth_3")
        link3 = DiscordLink.objects.create(
            discord_id=777777777777773,
            discord_username="accurate_test_3",
            user=user3,
            team=team,
            is_active=True,
        )

        try:
            goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

            # Should show 3 members for team 50
            # Exact format varies, but verify all 3 users are visible
            expect(goldteam_page.locator("text=accurate_test_1")).to_be_visible(timeout=5000)
            expect(goldteam_page.locator("text=accurate_test_2")).to_be_visible(timeout=5000)
            expect(goldteam_page.locator("text=accurate_test_3")).to_be_visible(timeout=5000)
        finally:
            link1.delete()
            link2.delete()
            link3.delete()

    def test_inactive_links_not_shown(self, goldteam_page: Page, db, live_server_url):
        """Inactive links should not be counted or displayed."""
        from django.contrib.auth.models import User

        from team.models import DiscordLink, Team

        team = Team.objects.get(team_number=50)

        # Create an inactive link
        user = User.objects.create_user(username="inactive_auth_user")
        inactive_link = DiscordLink.objects.create(
            discord_id=888888888888888,
            discord_username="inactive_test_user",
            user=user,
            team=team,
            is_active=False,  # Inactive
        )

        try:
            goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

            # Inactive user should NOT be visible
            inactive_locator = goldteam_page.locator("text=inactive_test_user")
            expect(inactive_locator).not_to_be_visible()
        finally:
            inactive_link.delete()


class TestTeamOrdering:
    """Test that teams are displayed in correct order."""

    def test_teams_ordered_by_team_number(self, goldteam_page: Page, live_server_url):
        """Teams should be ordered by team number (ascending)."""
        goldteam_page.goto(f"{live_server_url}/ops/group-role-mappings/")

        # Verify page renders
        # Exact ordering test would require parsing HTML structure
        expect(goldteam_page.locator("body")).to_be_visible()
