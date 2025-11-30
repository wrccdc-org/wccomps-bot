"""Tests for core utils and models."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from core.models import AuditLog, CompetitionConfig, DiscordTask
from core.utils import (
    get_authentik_data,
    get_team_from_groups,
)
from team.models import Team

pytestmark = pytest.mark.django_db


class TestGetAuthentikData:
    """Tests for get_authentik_data function."""

    def test_returns_username_from_userinfo(self, blue_team_user):
        """Should extract username from userinfo.preferred_username."""
        username, groups, user_id = get_authentik_data(blue_team_user)
        assert username == "blueteam01"
        assert user_id is not None

    def test_returns_groups_from_userinfo(self, blue_team_user):
        """Should extract groups from userinfo.groups."""
        username, groups, user_id = get_authentik_data(blue_team_user)
        assert "WCComps_BlueTeam01" in groups

    def test_returns_django_username_as_fallback(self):
        """Should return Django username when no social account exists."""
        user = User.objects.create_user(username="regular_user", password="test")
        username, groups, user_id = get_authentik_data(user)
        assert username == "regular_user"
        assert groups == []
        assert user_id is None


class TestGetTeamFromGroups:
    """Tests for get_team_from_groups function."""

    @pytest.fixture
    def test_teams(self):
        """Create test teams."""
        teams = []
        for i in [1, 10, 50]:
            team = Team.objects.create(team_number=i, team_name=f"Team {i}", max_members=10)
            teams.append(team)
        return teams

    def test_extracts_team_from_valid_group(self, test_teams):
        """Should extract team from valid BlueTeam group."""
        team, team_number, is_team = get_team_from_groups(["WCComps_BlueTeam01"])
        assert team is not None
        assert team.team_number == 1
        assert team_number == 1
        assert is_team is True

    def test_handles_double_digit_team(self, test_teams):
        """Should handle double-digit team numbers."""
        team, team_number, is_team = get_team_from_groups(["WCComps_BlueTeam10"])
        assert team is not None
        assert team.team_number == 10
        assert team_number == 10

    def test_handles_team_50(self, test_teams):
        """Should handle team 50."""
        team, team_number, is_team = get_team_from_groups(["WCComps_BlueTeam50"])
        assert team is not None
        assert team.team_number == 50

    def test_returns_none_for_non_team_groups(self, test_teams):
        """Should return None for non-team groups."""
        team, team_number, is_team = get_team_from_groups(["WCComps_GoldTeam", "WCComps_RedTeam"])
        assert team is None
        assert team_number is None
        assert is_team is False

    def test_returns_none_for_empty_groups(self, test_teams):
        """Should return None for empty groups list."""
        team, team_number, is_team = get_team_from_groups([])
        assert team is None
        assert team_number is None
        assert is_team is False

    def test_returns_none_for_nonexistent_team(self):
        """Should return None if team doesn't exist in database."""
        # No teams created
        team, team_number, is_team = get_team_from_groups(["WCComps_BlueTeam01"])
        assert team is None
        assert team_number is None
        assert is_team is False

    def test_ignores_invalid_team_numbers(self, test_teams):
        """Should ignore team numbers outside 1-50 range."""
        team, team_number, is_team = get_team_from_groups(["WCComps_BlueTeam99"])
        assert team is None


class TestAuditLogModel:
    """Tests for AuditLog model."""

    def test_str_representation(self):
        """__str__ should return action and admin_user."""
        log = AuditLog.objects.create(
            action="clear_tickets",
            admin_user="admin_user",
            target_entity="Ticket",
            target_id=0,
            details={"count": 5},
        )
        assert str(log) == "clear_tickets by admin_user"

    def test_ordering(self):
        """Should be ordered by created_at descending."""
        log1 = AuditLog.objects.create(action="first", admin_user="user", target_entity="X", target_id=1)
        log2 = AuditLog.objects.create(action="second", admin_user="user", target_entity="X", target_id=2)

        logs = list(AuditLog.objects.all())
        assert logs[0] == log2  # Newer first
        assert logs[1] == log1


class TestDiscordTaskModel:
    """Tests for DiscordTask model."""

    def test_str_representation(self):
        """__str__ should return task_type and status."""
        task = DiscordTask.objects.create(task_type="create_thread", payload={}, status="pending")
        assert str(task) == "create_thread (pending)"

    def test_default_values(self):
        """Should have correct default values."""
        task = DiscordTask.objects.create(task_type="send_message", payload={})
        assert task.status == "pending"
        assert task.retry_count == 0
        assert task.max_retries == 5


class TestCompetitionConfigModel:
    """Tests for CompetitionConfig model."""

    def test_get_config_creates_singleton(self):
        """get_config should create singleton if not exists."""
        assert CompetitionConfig.objects.count() == 0

        config = CompetitionConfig.get_config()

        assert CompetitionConfig.objects.count() == 1
        assert config.pk == 1

    def test_get_config_returns_existing(self):
        """get_config should return existing config."""
        CompetitionConfig.objects.create(pk=1, max_team_members=15)

        config = CompetitionConfig.get_config()

        assert config.max_team_members == 15
        assert CompetitionConfig.objects.count() == 1

    def test_should_enable_applications(self):
        """should_enable_applications should check start time."""
        config = CompetitionConfig.get_config()

        # No start time set
        assert not config.should_enable_applications()

        # Start time in past, not yet enabled
        config.competition_start_time = timezone.now() - timedelta(hours=1)
        config.applications_enabled = False
        config.save()
        assert config.should_enable_applications()

        # Start time in past, already enabled
        config.applications_enabled = True
        config.save()
        assert not config.should_enable_applications()

        # Start time in future
        config.competition_start_time = timezone.now() + timedelta(hours=1)
        config.applications_enabled = False
        config.save()
        assert not config.should_enable_applications()

    def test_should_disable_applications(self):
        """should_disable_applications should check end time."""
        config = CompetitionConfig.get_config()

        # No end time set
        assert not config.should_disable_applications()

        # End time in past, still enabled
        config.competition_end_time = timezone.now() - timedelta(hours=1)
        config.applications_enabled = True
        config.save()
        assert config.should_disable_applications()

        # End time in past, already disabled
        config.applications_enabled = False
        config.save()
        assert not config.should_disable_applications()

        # End time in future
        config.competition_end_time = timezone.now() + timedelta(hours=1)
        config.applications_enabled = True
        config.save()
        assert not config.should_disable_applications()

    def test_str_with_start_time(self):
        """__str__ should include start time when set."""
        config = CompetitionConfig.get_config()
        config.competition_start_time = timezone.now()
        config.save()

        assert "Competition starts at" in str(config)

    def test_str_without_start_time(self):
        """__str__ should indicate not scheduled when no start time."""
        config = CompetitionConfig.get_config()
        assert str(config) == "Competition not scheduled"
