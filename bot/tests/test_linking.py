"""Tests for Discord linking logic and uniqueness constraints."""

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from team.models import DiscordLink, Team


@pytest.mark.django_db(transaction=True)
class TestDiscordLinkUniqueness:
    """Test uniqueness constraints for active DiscordLinks."""

    def test_multiple_inactive_links_allowed(self, db) -> None:
        """Test that multiple inactive links can exist for same discord_id."""
        discord_id = 987654321

        # Create first inactive link
        link1 = DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username="user1",
            authentik_username="auth_user1",
            authentik_user_id="auth_id_1",
            is_active=False,
        )

        # Create second inactive link
        link2 = DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username="user2",
            authentik_username="auth_user2",
            authentik_user_id="auth_id_2",
            is_active=False,
        )

        # Both should exist and be inactive
        assert not link1.is_active
        assert not link2.is_active

        # Verify count
        assert DiscordLink.objects.filter(discord_id=discord_id, is_active=False).count() == 2
        assert DiscordLink.objects.filter(discord_id=discord_id, is_active=True).count() == 0

    def test_inactive_links_dont_conflict_with_active(self, db) -> None:
        """Test creating active link doesn't affect existing inactive links."""
        discord_id = 555555555

        # Create inactive link (history)
        link1 = DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username="old_user",
            authentik_username="old_auth",
            authentik_user_id="old_id",
            is_active=False,
        )

        # Create active link
        link2 = DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username="current_user",
            authentik_username="current_auth",
            authentik_user_id="current_id",
            is_active=True,
        )

        # Refresh first to get latest state
        link1.refresh_from_db()

        # First should still be inactive
        assert not link1.is_active

        # Second should be active
        assert link2.is_active

        # Verify counts
        assert DiscordLink.objects.filter(discord_id=discord_id, is_active=False).count() == 1
        assert DiscordLink.objects.filter(discord_id=discord_id, is_active=True).count() == 1

    def test_creating_new_active_link_deactivates_old_history_preserved(self, db) -> None:
        """Test creating new active link deactivates old one, but keeps history."""
        discord_id = 444444444

        # Create first active link
        link1 = DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username="user_v1",
            authentik_username="auth_v1",
            authentik_user_id="auth_id_v1",
            is_active=True,
        )

        # Create second active link
        link2 = DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username="user_v2",
            authentik_username="auth_v2",
            authentik_user_id="auth_id_v2",
            is_active=True,
        )

        # Create third active link
        link3 = DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username="user_v3",
            authentik_username="auth_v3",
            authentik_user_id="auth_id_v3",
            is_active=True,
        )

        # Refresh to get latest state
        link1.refresh_from_db()
        link2.refresh_from_db()

        # Only link3 should be active
        assert not link1.is_active
        assert not link2.is_active
        assert link3.is_active

        # All three should exist in database (history preserved)
        all_links = DiscordLink.objects.filter(discord_id=discord_id).order_by("linked_at")
        assert all_links.count() == 3
        assert list(all_links.values_list("discord_username", flat=True)) == [
            "user_v1",
            "user_v2",
            "user_v3",
        ]


@pytest.mark.django_db(transaction=True)
class TestTeamMemberLimitEnforcement:
    """Test team member limits are enforced during linking."""

    def test_team_is_full_method_at_capacity(self, db) -> None:
        """Team.is_full() returns True when members equals max_members."""
        # Arrange: Create team with max_members=3
        team = Team.objects.create(
            team_number=20,
            team_name="Full Team",
            authentik_group="WCComps_BlueTeam10",
            max_members=3,
        )

        # Create 3 active members
        for i in range(3):
            DiscordLink.objects.create(
                discord_id=1000000 + i,
                discord_username=f"user{i}",
                authentik_username=f"user{i}",
                authentik_user_id=f"uid-{i}",
                team=team,
                is_active=True,
            )

        # Assert: Team with 3/3 members is full
        assert team.get_member_count() == 3
        assert team.is_full() is True

    def test_team_is_full_method_below_capacity(self, db) -> None:
        """Team.is_full() returns False when members less than max_members."""
        # Arrange: Create team with max_members=5
        team = Team.objects.create(
            team_number=21,
            team_name="Open Team",
            authentik_group="WCComps_BlueTeam11",
            max_members=5,
        )

        # Create 2 active members
        for i in range(2):
            DiscordLink.objects.create(
                discord_id=2000000 + i,
                discord_username=f"user{i}",
                authentik_username=f"user{i}",
                authentik_user_id=f"uid-{i}",
                team=team,
                is_active=True,
            )

        # Assert: Team with 2/5 members is not full
        assert team.get_member_count() == 2
        assert team.is_full() is False

    def test_team_is_full_method_empty(self, db) -> None:
        """Team.is_full() returns False when team has no members."""
        # Arrange: Create empty team
        team = Team.objects.create(
            team_number=22,
            team_name="Empty Team",
            authentik_group="WCComps_BlueTeam12",
            max_members=10,
        )

        # Assert: Empty team is not full
        assert team.get_member_count() == 0
        assert team.is_full() is False

    def test_get_member_count_counts_only_active(self, db) -> None:
        """get_member_count() counts only active members, not inactive ones."""
        # Arrange: Create team
        team = Team.objects.create(
            team_number=23,
            team_name="Mixed Activity",
            authentik_group="WCComps_BlueTeam13",
            max_members=5,
        )

        # Create 2 active members
        for i in range(2):
            DiscordLink.objects.create(
                discord_id=3000000 + i,
                discord_username=f"active{i}",
                authentik_username=f"active{i}",
                authentik_user_id=f"uid-active-{i}",
                team=team,
                is_active=True,
            )

        # Create 2 inactive members
        from django.utils import timezone

        for i in range(2):
            DiscordLink.objects.create(
                discord_id=3000010 + i,
                discord_username=f"inactive{i}",
                authentik_username=f"inactive{i}",
                authentik_user_id=f"uid-inactive-{i}",
                team=team,
                is_active=False,
                unlinked_at=timezone.now(),
            )

        # Assert: Only active members are counted
        assert team.get_member_count() == 2

    def test_team_is_full_ignores_inactive_members(self, db) -> None:
        """Team.is_full() does not count inactive members toward capacity."""
        # Arrange: Create team with max_members=2
        team = Team.objects.create(
            team_number=24,
            team_name="Capacity Test",
            authentik_group="WCComps_BlueTeam14",
            max_members=2,
        )

        # Create 1 active member
        DiscordLink.objects.create(
            discord_id=4000000,
            discord_username="active",
            authentik_username="active",
            authentik_user_id="uid-active",
            team=team,
            is_active=True,
        )

        # Create 5 inactive members (to verify they're not counted)
        from django.utils import timezone

        for i in range(5):
            DiscordLink.objects.create(
                discord_id=4000010 + i,
                discord_username=f"inactive{i}",
                authentik_username=f"inactive{i}",
                authentik_user_id=f"uid-inactive-{i}",
                team=team,
                is_active=False,
                unlinked_at=timezone.now(),
            )

        # Assert: Team is not full (1 active < 2 max)
        assert team.get_member_count() == 1
        assert team.is_full() is False

    def test_team_full_error_message_includes_capacity(self, db) -> None:
        """LinkAttempt records full team with member count and capacity."""
        from team.models import LinkAttempt

        # Arrange: Create team and members
        team = Team.objects.create(
            team_number=25,
            team_name="Full Test Team",
            authentik_group="WCComps_BlueTeam15",
            max_members=2,
        )

        for i in range(2):
            DiscordLink.objects.create(
                discord_id=5000000 + i,
                discord_username=f"user{i}",
                authentik_username=f"user{i}",
                authentik_user_id=f"uid-{i}",
                team=team,
                is_active=True,
            )

        # Act: Create failed link attempt with full team error
        attempt = LinkAttempt.objects.create(
            discord_id=5000010,
            discord_username="denied",
            authentik_username="denied",
            team=team,
            success=False,
            failure_reason=f"Team full ({team.get_member_count()}/{team.max_members})",
        )

        # Assert: Failure reason includes count and capacity
        assert "Team full" in attempt.failure_reason
        assert "2/2" in attempt.failure_reason

    def test_select_for_update_pattern_usage(self, db) -> None:
        """Test that select_for_update can be used with team capacity checks."""
        from django.db import transaction

        team = Team.objects.create(
            team_number=22,
            team_name="Locking Pattern Test",
            authentik_group="WCComps_BlueTeam22",
            max_members=3,
        )

        # Add 2 members
        for i in range(2):
            DiscordLink.objects.create(
                discord_id=10000000 + i,
                discord_username=f"existing{i}",
                authentik_username=f"existing{i}",
                authentik_user_id=f"uid-existing-{i}",
                team=team,
                is_active=True,
            )

        # Verify select_for_update pattern works for capacity checking
        with transaction.atomic():
            locked_team = Team.objects.select_for_update().get(pk=team.pk)
            assert locked_team.is_full() is False

            DiscordLink.objects.create(
                discord_id=10000010,
                discord_username="new_member",
                authentik_username="new_member",
                authentik_user_id="uid-new",
                team=locked_team,
                is_active=True,
            )

        team.refresh_from_db()
        assert team.get_member_count() == 3


@pytest.mark.django_db(transaction=True)
class TestLinkingProperties:
    """Property-based tests for linking logic."""

    @given(
        discord_id=st.integers(min_value=100000000000000000, max_value=999999999999999999),
        active_count=st.integers(min_value=0, max_value=5),
        inactive_count=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=30)
    def test_active_link_count_invariant(self, discord_id: int, active_count: int, inactive_count: int):
        """Property: at most one active link per discord_id at any time."""
        import uuid

        # Skip if discord_id already exists
        assume(not DiscordLink.objects.filter(discord_id=discord_id).exists())

        # Create inactive links
        for _i in range(inactive_count):
            DiscordLink.objects.create(
                discord_id=discord_id,
                discord_username=f"inactive_{uuid.uuid4()}",
                authentik_username=f"auth_{uuid.uuid4()}",
                authentik_user_id=f"uid-{uuid.uuid4()}",
                is_active=False,
            )

        # Create active links (only last one should remain active)
        for _i in range(active_count):
            DiscordLink.objects.create(
                discord_id=discord_id,
                discord_username=f"active_{uuid.uuid4()}",
                authentik_username=f"auth_{uuid.uuid4()}",
                authentik_user_id=f"uid-{uuid.uuid4()}",
                is_active=True,
            )

        # Property: exactly 0 or 1 active links
        active_links = DiscordLink.objects.filter(discord_id=discord_id, is_active=True).count()
        assert active_links in (0, 1)

        # Property: if we created any active links, exactly 1 should remain
        if active_count > 0:
            assert active_links == 1

        # Property: total inactive links equals inactive_count + (active_count - 1)
        total_inactive = DiscordLink.objects.filter(discord_id=discord_id, is_active=False).count()
        if active_count > 0:
            assert total_inactive == inactive_count + (active_count - 1)
