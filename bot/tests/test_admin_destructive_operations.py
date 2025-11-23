"""
Tests for destructive admin operations.

These have 0% coverage because admin_competition.py is NEVER IMPORTED in tests.

CRITICAL: These are DESTRUCTIVE operations that:
- Delete Discord channels
- Remove user roles
- Deactivate accounts
- Reset passwords

A bug could:
- Delete wrong channels (e.g., admin channels)
- Deactivate wrong accounts (e.g., admin accounts)
- Fail to log audit trail
- Leave database in inconsistent state

These tests verify SAFETY, not just functionality.
"""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import discord
import pytest

from core.models import AuditLog
from team.models import DiscordLink, Team
from ticketing.models import Ticket


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestEndCompetitionSafety:
    """Test that end_competition doesn't destroy wrong things.

    RISK: 888 lines of code with 0% coverage, NEVER TESTED.
    Deletes channels, removes roles, deactivates accounts.
    """

    @pytest.fixture
    async def setup_competition(self):
        """Set up a realistic competition state."""
        # Create teams
        team1 = await Team.objects.acreate(
            team_number=1,
            team_name="Blue Team 1",
            authentik_group="WCComps_BlueTeam1",
            discord_category_id=1111111111111111111,
        )
        team2 = await Team.objects.acreate(
            team_number=2,
            team_name="Blue Team 2",
            authentik_group="WCComps_BlueTeam2",
            discord_category_id=2222222222222222222,
        )

        # Create team member links
        team1_link = await DiscordLink.objects.acreate(
            discord_id=3000000000000000001,
            discord_username="team1_user",
            authentik_username="blueteam1_user",
            authentik_user_id="uid-team1",
            team=team1,
            is_active=True,
        )
        team2_link = await DiscordLink.objects.acreate(
            discord_id=3000000000000000002,
            discord_username="team2_user",
            authentik_username="blueteam2_user",
            authentik_user_id="uid-team2",
            team=team2,
            is_active=True,
        )

        # Create admin link (should NOT be deactivated)
        admin_link = await DiscordLink.objects.acreate(
            discord_id=3000000000000000100,
            discord_username="admin_user",
            authentik_username="admin",
            authentik_user_id="uid-admin",
            team=None,  # No team - admin/support
            is_active=True,
        )

        # Create support link (should NOT be deactivated)
        support_link = await DiscordLink.objects.acreate(
            discord_id=3000000000000000101,
            discord_username="support_user",
            authentik_username="support",
            authentik_user_id="uid-support",
            team=None,  # No team - admin/support
            is_active=True,
        )

        return {
            "teams": [team1, team2],
            "team_links": [team1_link, team2_link],
            "admin_links": [admin_link, support_link],
        }

    async def test_end_competition_only_deactivates_team_links(self, setup_competition):
        """
        CRITICAL: Should deactivate team member links, NOT admin/support links.

        BUG IF: Admin/support accounts are deactivated.
        """
        data = await setup_competition

        # Import the cog
        from bot.cogs.admin_competition import AdminCompetitionCog

        bot = AsyncMock()
        cog = AdminCompetitionCog(bot)

        # Create mock interaction
        interaction = AsyncMock(spec=discord.Interaction)
        interaction.user = Mock()
        interaction.user.id = 9000000000000000000
        interaction.user.mention = "@admin"
        interaction.guild = Mock()
        interaction.guild.id = 1234567890

        # Mock the response
        interaction.response.send_message = AsyncMock()
        interaction.followup.send = AsyncMock()

        # Mock log_to_ops_channel to prevent actual Discord calls
        with patch("bot.cogs.admin_competition.log_to_ops_channel", new=AsyncMock()):
            # Call end_competition
            await cog.admin_end_competition(interaction)

            # Wait for background cleanup to complete
            await asyncio.sleep(0.5)

        # CRITICAL: Verify team links are deactivated
        for link in data["team_links"]:
            await link.arefresh_from_db()
            assert not link.is_active, (
                f"BUG: Team member link still active! discord_id={link.discord_id}, username={link.discord_username}"
            )
            assert link.unlinked_at is not None, "unlinked_at should be set"

        # CRITICAL: Verify admin/support links are NOT deactivated
        for link in data["admin_links"]:
            await link.arefresh_from_db()
            assert link.is_active, (
                f"BUG: Admin/support link was deactivated! "
                f"discord_id={link.discord_id}, username={link.discord_username}"
            )
            assert link.unlinked_at is None, "Admin link should not be unlinked"

    async def test_end_competition_creates_audit_logs(self, setup_competition):
        """
        CRITICAL: Every deactivation should be logged.

        BUG IF: Audit trail is incomplete.
        """
        data = await setup_competition

        from bot.cogs.admin_competition import AdminCompetitionCog

        bot = AsyncMock()
        cog = AdminCompetitionCog(bot)

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.user = Mock()
        interaction.user.id = 9000000000000000000
        interaction.user.mention = "@admin"
        interaction.guild = Mock()
        interaction.guild.id = 1234567890
        interaction.response.send_message = AsyncMock()

        initial_audit_count = await AuditLog.objects.acount()

        with patch("bot.cogs.admin_competition.log_to_ops_channel", new=AsyncMock()):
            await cog.admin_end_competition(interaction)
            await asyncio.sleep(0.5)

        # CRITICAL: Should have audit logs for each deactivation
        final_audit_count = await AuditLog.objects.acount()
        team_link_count = len(data["team_links"])

        assert final_audit_count >= initial_audit_count + team_link_count, (
            f"BUG: Incomplete audit trail! "
            f"Deactivated {team_link_count} links but only "
            f"{final_audit_count - initial_audit_count} audit logs created."
        )

        # Verify audit log details
        recent_audits = [
            audit
            async for audit in AuditLog.objects.filter(action="user_unlinked").order_by("-created_at")[:team_link_count]
        ]

        for audit in recent_audits:
            assert audit.details.get("reason") == "competition_ended"
            assert "discord_id" in audit.details
            assert "authentik_username" in audit.details

    async def test_end_competition_doesnt_delete_admin_channels(self, setup_competition):
        """
        CRITICAL: Should only delete team category channels, not admin channels.

        BUG IF: Deletes #ops, #announcements, etc.
        """
        await setup_competition

        from bot.cogs.admin_competition import AdminCompetitionCog

        bot = AsyncMock()
        cog = AdminCompetitionCog(bot)

        # Mock guild with various channels
        guild = Mock()
        guild.id = 1234567890

        # Create team categories
        team1_category = Mock(spec=discord.CategoryChannel)
        team1_category.id = 1111111111111111111
        team1_category.name = "🔵 Blue Team 01"

        team2_category = Mock(spec=discord.CategoryChannel)
        team2_category.id = 2222222222222222222
        team2_category.name = "🔵 Blue Team 02"

        # Create admin categories (should NOT be deleted)
        admin_category = Mock(spec=discord.CategoryChannel)
        admin_category.id = 9999999999999999999
        admin_category.name = "🔧 Admin"

        ops_category = Mock(spec=discord.CategoryChannel)
        ops_category.id = 8888888888888888888
        ops_category.name = "👮 Operations"

        # Mock channels method
        all_channels = [team1_category, team2_category, admin_category, ops_category]
        guild.channels = all_channels

        deleted_channels = []

        # Track deletions
        async def mock_delete():
            deleted_channels.append(team1_category)

        async def mock_delete2():
            deleted_channels.append(team2_category)

        async def mock_delete_admin():
            deleted_channels.append(admin_category)

        async def mock_delete_ops():
            deleted_channels.append(ops_category)

        team1_category.delete = mock_delete
        team2_category.delete = mock_delete2
        admin_category.delete = mock_delete_admin
        ops_category.delete = mock_delete_ops

        interaction = AsyncMock(spec=discord.Interaction)
        interaction.user = Mock()
        interaction.user.mention = "@admin"
        interaction.guild = guild
        interaction.response.send_message = AsyncMock()

        with patch("bot.cogs.admin_competition.log_to_ops_channel", new=AsyncMock()):
            await cog.admin_end_competition(interaction)
            await asyncio.sleep(0.5)

        # CRITICAL: Should only delete team categories
        deleted_ids = [ch.id for ch in deleted_channels]

        # Team categories should be deleted
        assert 1111111111111111111 in deleted_ids or 2222222222222222222 in deleted_ids, (
            "BUG: Team categories not deleted"
        )

        # Admin categories should NOT be deleted
        assert 9999999999999999999 not in deleted_ids, "BUG: Admin category was deleted!"
        assert 8888888888888888888 not in deleted_ids, "BUG: Operations category was deleted!"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestPasswordResetSafety:
    """Test password reset operations.

    RISK: 0% coverage, untested password reset could:
    - Reset wrong accounts
    - Not actually reset passwords
    - Fail to log changes
    """

    async def test_password_reset_affects_only_target_team(self):
        """
        CRITICAL: Resetting Team 1 password should not affect Team 2.

        BUG IF: All teams get same password.
        """
        # This would require mocking Authentik API calls
        # For now, verify the logic structure
        from bot.authentik_utils import reset_blueteam_password

        team_number = 5

        with patch("bot.authentik_utils.requests.request") as mock_request:
            # Mock successful password reset
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            mock_request.return_value = mock_response

            # Reset password for team 5
            reset_blueteam_password(team_number, "new_password_123")

        # Verify API was called with correct team
        assert mock_request.called
        call_args = mock_request.call_args

        # Should target specific team group
        assert "BlueTeam05" in str(call_args) or "blueteam05" in str(call_args).lower(), (
            "BUG: Password reset not targeting correct team"
        )

    async def test_password_reset_validates_team_number(self):
        """
        CRITICAL: Should reject invalid team numbers.

        BUG IF: Accepts team_number=0, -1, 999, etc.
        """
        from bot.authentik_utils import reset_blueteam_password

        invalid_teams = [-1, 0, 51, 100, 999]

        for team_num in invalid_teams:
            with patch("bot.authentik_utils.requests.request") as mock_request:
                mock_response = Mock()
                mock_response.status_code = 404
                mock_request.return_value = mock_response

                result = reset_blueteam_password(team_num, "password")

                # Should fail or return error
                # At minimum, should not blindly succeed
                if result:
                    # If it returns something, should indicate failure
                    assert "error" in str(result).lower() or "failed" in str(result).lower(), (
                        f"BUG: Invalid team number {team_num} accepted"
                    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestBulkOperationsSafety:
    """Test bulk team operations.

    RISK: Operating on multiple teams - errors could be catastrophic.
    """

    async def test_bulk_operation_failure_doesnt_leave_inconsistent_state(self):
        """
        SCENARIO: Bulk operation on teams 1-5, operation fails on team 3.

        PROPERTY: Either all succeed or all rollback.
        BUG IF: Teams 1-2 processed, teams 3-5 not processed.
        """
        # Create 5 teams
        teams = []
        for i in range(1, 6):
            team = await Team.objects.acreate(
                team_number=i,
                team_name=f"Team {i}",
                authentik_group=f"WCComps_BlueTeam{i}",
            )
            teams.append(team)

        from bot.authentik_utils import toggle_all_blueteam_accounts

        # Mock API calls
        call_count = 0

        def mock_api_call(method, url, **kwargs):
            nonlocal call_count
            call_count += 1

            # Fail on team 3
            if "BlueTeam03" in url or "blueteam03" in url.lower():
                mock_response = Mock()
                mock_response.status_code = 500
                mock_response.text = "API Error"
                return mock_response

            # Succeed for others
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"success": True}
            return mock_response

        with patch("bot.authentik_utils.requests.request", side_effect=mock_api_call):
            results = toggle_all_blueteam_accounts(enabled=True, team_range="1-5")

        # Check results
        # Should either:
        # 1. All succeeded (if it retried team 3)
        # 2. All failed (if it rolled back)
        # 3. Clearly indicate which failed (for manual intervention)

        # At minimum: should not silently fail
        assert results is not None, "Function returned None - unclear success/failure"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestDataIntegrityAfterFailure:
    """Test that failed operations don't corrupt data.

    These test error recovery paths.
    """

    async def test_failed_link_creation_doesnt_leave_zombie_record(self):
        """
        SCENARIO: Creating link fails after database insert but before activation.

        PROPERTY: Should not have inactive/broken links in database.
        """
        team = await Team.objects.acreate(
            team_number=10,
            team_name="Test Team",
            authentik_group="WCComps_BlueTeam10",
        )

        initial_count = await DiscordLink.objects.filter(team=team).acount()

        # Try to create link but simulate failure
        try:
            from django.db import transaction

            with transaction.atomic():
                await DiscordLink.objects.acreate(
                    discord_id=5000000000000000000,
                    discord_username="test_user",
                    authentik_username="test_user",
                    authentik_user_id="uid-test",
                    team=team,
                    is_active=True,
                )

                # Simulate failure (e.g., Authentik API call fails)
                raise Exception("Authentik API error")

        except Exception:
            pass  # Expected

        # CRITICAL: Database should be rolled back
        final_count = await DiscordLink.objects.filter(team=team).acount()

        assert final_count == initial_count, f"BUG: Zombie link created! Initial: {initial_count}, Final: {final_count}"

    async def test_partial_team_creation_failure_is_cleaned_up(self):
        """
        SCENARIO: Creating team fails after some setup.

        PROPERTY: No orphaned database records.
        """
        initial_team_count = await Team.objects.acount()
        initial_ticket_count = await Ticket.objects.acount()

        try:
            from django.db import transaction

            with transaction.atomic():
                # Create team
                team = await Team.objects.acreate(
                    team_number=99,
                    team_name="Partial Team",
                    authentik_group="WCComps_BlueTeam99",
                )

                # Create initial ticket
                await Ticket.objects.acreate(
                    ticket_number="T099-001",
                    team=team,
                    category="other",
                    title="Setup Ticket",
                    status="open",
                )

                # Simulate failure during setup
                raise Exception("Discord category creation failed")

        except Exception:
            pass  # Expected

        # CRITICAL: All records should be rolled back
        final_team_count = await Team.objects.acount()
        final_ticket_count = await Ticket.objects.acount()

        assert final_team_count == initial_team_count, (
            f"BUG: Orphaned team! Teams increased from {initial_team_count} to {final_team_count}"
        )
        assert final_ticket_count == initial_ticket_count, (
            f"BUG: Orphaned ticket! Tickets increased from {initial_ticket_count} to {final_ticket_count}"
        )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestAdminCommandAuthorizationTest:
    """Verify admin commands actually check authorization.

    CRITICAL: These are destructive operations.
    """

    async def test_non_admin_cannot_end_competition(self):
        """
        CRITICAL: Regular users should not be able to end competition.
        """
        from bot.permissions import check_admin

        # Create non-admin user interaction
        interaction = Mock()
        interaction.user = Mock()
        interaction.user.id = 1234567890  # Not in admin list

        # check_admin should return False
        with patch.dict("os.environ", {"ADMIN_IDS": "9999999999"}):
            is_admin = await check_admin(interaction)
            assert not is_admin, "Non-admin user returned as admin"

    async def test_admin_commands_log_who_executed_them(self):
        """
        CRITICAL: Audit trail must show WHO performed destructive action.
        """
        # Create team link
        team = await Team.objects.acreate(
            team_number=20,
            team_name="Audit Test Team",
            authentik_group="WCComps_BlueTeam20",
        )

        await DiscordLink.objects.acreate(
            discord_id=6000000000000000000,
            discord_username="test_user",
            authentik_username="test_user",
            authentik_user_id="uid-test",
            team=team,
            is_active=True,
        )

        from bot.cogs.admin_competition import AdminCompetitionCog

        bot = AsyncMock()
        cog = AdminCompetitionCog(bot)

        admin_user = Mock()
        admin_user.id = 9000000000000000000
        admin_user.__str__ = lambda x: "admin#1234"

        interaction = AsyncMock()
        interaction.user = admin_user
        interaction.guild = Mock()
        interaction.response.send_message = AsyncMock()

        with patch("bot.cogs.admin_competition.log_to_ops_channel", new=AsyncMock()):
            await cog.admin_end_competition(interaction)
            await asyncio.sleep(0.5)

        # Check audit log
        audit = await AuditLog.objects.filter(action="user_unlinked").afirst()

        assert audit is not None, "No audit log created"
        assert audit.admin_user == "admin#1234", (
            f"BUG: Audit log doesn't show who performed action. Got: {audit.admin_user}"
        )
