"""Tests for management commands."""

import contextlib
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command

from core.models import AuditLog, CompetitionConfig, DiscordTask
from team.models import DiscordLink, LinkAttempt, LinkToken, Team
from ticketing.models import Ticket, TicketHistory

pytestmark = pytest.mark.django_db


class TestInitTeamsCommand:
    """Tests for init_teams management command."""

    def test_creates_50_teams(self):
        """Command should create 50 teams."""
        assert Team.objects.count() == 0

        out = StringIO()
        call_command("init_teams", stdout=out)

        assert Team.objects.count() == 50
        assert "Initialization complete: 50 created" in out.getvalue()

    def test_uses_competition_config_max_members(self):
        """Teams should use max_members from CompetitionConfig."""
        config = CompetitionConfig.get_config()
        config.max_team_members = 8
        config.save()

        call_command("init_teams", stdout=StringIO())

        team = Team.objects.first()
        assert team is not None
        assert team.max_members == 8

    def test_idempotent_running_twice(self):
        """Running twice should not create duplicates."""
        call_command("init_teams", stdout=StringIO())
        assert Team.objects.count() == 50

        out = StringIO()
        call_command("init_teams", stdout=out)
        assert Team.objects.count() == 50
        assert "50 already existed" in out.getvalue()

    def test_team_number_sequence(self):
        """Teams should be numbered 1-50."""
        call_command("init_teams", stdout=StringIO())

        team_numbers = list(Team.objects.values_list("team_number", flat=True).order_by("team_number"))
        assert team_numbers == list(range(1, 51))

    def test_team_name_format(self):
        """Teams should have correct name format."""
        call_command("init_teams", stdout=StringIO())

        team1 = Team.objects.get(team_number=1)
        team10 = Team.objects.get(team_number=10)

        assert team1.team_name == "BlueTeam01"
        assert team10.team_name == "BlueTeam10"

    def test_authentik_group_format(self):
        """Teams should have correct Authentik group format."""
        call_command("init_teams", stdout=StringIO())

        team1 = Team.objects.get(team_number=1)
        team50 = Team.objects.get(team_number=50)

        assert team1.authentik_group == "WCComps_BlueTeam01"
        assert team50.authentik_group == "WCComps_BlueTeam50"

    def test_teams_are_active(self):
        """Created teams should be active."""
        call_command("init_teams", stdout=StringIO())

        inactive_count = Team.objects.filter(is_active=False).count()
        assert inactive_count == 0


class TestWipeCompetitionCommand:
    """Tests for wipe_competition management command."""

    @pytest.fixture
    def populated_database(self):
        """Create test data in the database."""
        team = Team.objects.create(team_number=1, team_name="Test Team", max_members=10)
        ticket = Ticket.objects.create(
            ticket_number="T001-001",
            team=team,
            category="other",
            title="Test Ticket",
            status="open",
        )
        TicketHistory.objects.create(ticket=ticket, action="created")
        test_user = User.objects.create_user(username="auth_user")
        DiscordLink.objects.create(
            discord_id=123456789,
            discord_username="testuser",
            user=test_user,
            team=team,
            is_active=True,
        )
        LinkAttempt.objects.create(
            discord_id=123456789,
            discord_username="testuser",
            authentik_username="auth_user",
            success=True,
        )
        LinkToken.objects.create(
            token="test_token",
            discord_id=123456789,
            discord_username="testuser",
            expires_at="2099-01-01T00:00:00Z",
        )
        DiscordTask.objects.create(task_type="test", payload={}, status="pending")
        return team

    def test_requires_confirm_flag(self, populated_database):
        """Command should not delete without --confirm flag."""
        out = StringIO()
        call_command("wipe_competition", stdout=out)

        output = out.getvalue()
        assert "DELETE ALL" in output
        assert "--confirm" in output

        # Verify nothing was deleted
        assert Team.objects.count() == 1
        assert Ticket.objects.count() == 1

    def test_deletes_all_data_with_confirm(self, populated_database):
        """Command should delete all data with --confirm."""
        assert Team.objects.count() == 1
        assert Ticket.objects.count() == 1
        assert DiscordLink.objects.count() == 1

        out = StringIO()
        call_command("wipe_competition", "--confirm", stdout=out)

        assert Team.objects.count() == 0
        assert Ticket.objects.count() == 0
        assert TicketHistory.objects.count() == 0
        assert DiscordLink.objects.count() == 0
        assert LinkAttempt.objects.count() == 0
        assert LinkToken.objects.count() == 0
        assert DiscordTask.objects.count() == 0

    def test_handles_empty_database(self):
        """Command should handle empty database gracefully."""
        out = StringIO()
        call_command("wipe_competition", "--confirm", stdout=out)

        output = out.getvalue()
        assert "wiped" in output.lower()


class TestCheckDbHealthCommand:
    """Tests for check_db_health management command."""

    def test_runs_successfully_on_healthy_db(self):
        """Command should pass on healthy database."""
        out = StringIO()
        try:
            call_command("check_db_health", stdout=out)
        except SystemExit as e:
            # Exit code 0 means success
            assert e.code == 0

        output = out.getvalue()
        assert "Database connection OK" in output

    def test_checks_database_connection(self):
        """Command should check database connection."""
        out = StringIO()
        with contextlib.suppress(SystemExit):
            call_command("check_db_health", stdout=out)

        assert "Checking database connection" in out.getvalue()

    def test_checks_migrations(self):
        """Command should check for unapplied migrations."""
        out = StringIO()
        with contextlib.suppress(SystemExit):
            call_command("check_db_health", stdout=out)

        assert "Checking migrations" in out.getvalue()

    def test_checks_model_integrity(self):
        """Command should verify model integrity."""
        out = StringIO()
        with contextlib.suppress(SystemExit):
            call_command("check_db_health", stdout=out)

        assert "Checking model integrity" in out.getvalue()

    def test_checks_critical_queries(self):
        """Command should test critical queries."""
        out = StringIO()
        with contextlib.suppress(SystemExit):
            call_command("check_db_health", stdout=out)

        assert "Testing critical queries" in out.getvalue()

    def test_checks_view_imports(self):
        """Command should test view imports."""
        out = StringIO()
        with contextlib.suppress(SystemExit):
            call_command("check_db_health", stdout=out)

        assert "Testing view imports" in out.getvalue()

    def test_checks_template_syntax(self):
        """Command should test template syntax."""
        out = StringIO()
        with contextlib.suppress(SystemExit):
            call_command("check_db_health", stdout=out)

        assert "Testing template syntax" in out.getvalue()


class TestClearTicketsCommand:
    """Tests for clear_tickets management command (supplement to existing tests)."""

    def test_preserves_team_structure(self):
        """Clearing tickets should preserve teams but reset counters."""
        team = Team.objects.create(team_number=1, team_name="Test Team", max_members=10, ticket_counter=5)
        Ticket.objects.create(
            ticket_number="T001-001",
            team=team,
            category="other",
            title="Test",
            status="open",
        )

        call_command("clear_tickets", "--confirm", stdout=StringIO())

        # Team should exist but counter reset
        team.refresh_from_db()
        assert team.team_number == 1
        assert team.ticket_counter == 0

    def test_creates_audit_log(self):
        """Clearing tickets should create audit log entry."""
        team = Team.objects.create(team_number=1, team_name="Test Team", max_members=10)
        Ticket.objects.create(
            ticket_number="T001-001",
            team=team,
            category="other",
            title="Test",
            status="open",
        )

        call_command("clear_tickets", "--confirm", stdout=StringIO())

        audit = AuditLog.objects.filter(action="clear_tickets").first()
        assert audit is not None
