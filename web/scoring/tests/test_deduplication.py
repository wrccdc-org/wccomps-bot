"""Tests for red team finding deduplication logic."""

from decimal import Decimal

import pytest
from django.contrib.auth.models import User

from scoring.deduplication import (
    OutcomeData,
    process_red_team_submission,
)
from scoring.models import AttackType, RedTeamFinding
from team.models import Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def teams():
    """Create test teams."""
    return [Team.objects.create(team_name=f"Team {i}", team_number=i, max_members=10) for i in range(1, 5)]


@pytest.fixture
def users():
    """Create test users."""
    return {
        "red1": User.objects.create_user("red1", "red1@test.com", "password"),
        "red2": User.objects.create_user("red2", "red2@test.com", "password"),
    }


@pytest.fixture
def attack_type():
    """Get or create a test attack type."""
    attack, _ = AttackType.objects.get_or_create(
        name="SQL Injection",
        defaults={"description": "Test attack type", "is_active": True},
    )
    return attack


class TestProcessRedTeamSubmission:
    """Tests for the main submission processing function."""

    def test_creates_new_finding(self, teams, users, attack_type):
        """Creates new finding when no duplicate exists."""
        result = process_red_team_submission(
            attack_type=attack_type,
            boxes=["Web Server"],
            teams=teams[:2],
            source_ip="10.0.0.1",
            source_ip_pool=None,
            submitter=users["red1"],
            notes="Test finding",
        )

        assert result.status == "created"
        assert result.finding.attack_type == attack_type
        assert result.finding.submitted_by == users["red1"]
        assert users["red1"] in result.finding.contributors.all()

    def test_duplicate_submission_creates_new_finding(self, teams, users, attack_type):
        """Duplicate submissions create separate findings (deduplication disabled)."""
        # First submission
        result1 = process_red_team_submission(
            attack_type=attack_type,
            boxes=["Web Server"],
            teams=[teams[0]],
            source_ip="10.0.0.1",
            source_ip_pool=None,
            submitter=users["red1"],
        )
        assert result1.status == "created"

        # Second submission with same criteria creates new finding
        result2 = process_red_team_submission(
            attack_type=attack_type,
            boxes=["Web Server"],
            teams=[teams[0]],
            source_ip="10.0.0.2",
            source_ip_pool=None,
            submitter=users["red2"],
        )
        assert result2.status == "created"
        assert result2.finding != result1.finding  # Different findings

    def test_overlapping_teams_creates_new_finding(self, teams, users, attack_type):
        """Overlapping team submissions create separate findings (deduplication disabled)."""
        # First submission for team 1
        result1 = process_red_team_submission(
            attack_type=attack_type,
            boxes=["Web Server"],
            teams=[teams[0]],
            source_ip="10.0.0.1",
            source_ip_pool=None,
            submitter=users["red1"],
        )

        # Second submission for teams 1 and 2 creates new finding
        result2 = process_red_team_submission(
            attack_type=attack_type,
            boxes=["Web Server"],
            teams=[teams[0], teams[1]],
            source_ip="10.0.0.2",
            source_ip_pool=None,
            submitter=users["red2"],
        )
        assert result2.status == "created"
        assert result2.finding != result1.finding
        assert result2.finding.affected_teams.count() == 2

    def test_creates_finding_with_outcomes(self, teams, users, attack_type):
        """Creates finding with outcome checkboxes and auto-calculated points."""
        outcomes = OutcomeData(
            root_access=True,
            credentials_recovered=True,
        )
        result = process_red_team_submission(
            attack_type=attack_type,
            boxes=["Web Server"],
            teams=teams[:2],
            source_ip="10.0.0.1",
            source_ip_pool=None,
            submitter=users["red1"],
            outcomes=outcomes,
        )

        assert result.status == "created"
        assert result.finding.root_access is True
        assert result.finding.credentials_recovered is True
        assert result.finding.user_access is False
        # Root (100) + Credentials (50) = 150
        assert result.finding.points_per_team == Decimal("150")


class TestCalculatePoints:
    """Tests for RedTeamFinding.calculate_points method."""

    def test_root_access_only(self, users, attack_type):
        """Root access gives 100 points."""
        finding = RedTeamFinding.objects.create(
            attack_type=attack_type,
            affected_boxes=["Web Server"],
            source_ip="10.0.0.1",
            submitted_by=users["red1"],
            root_access=True,
            points_per_team=0,
        )
        assert finding.calculate_points() == Decimal("100")

    def test_user_access_only(self, users, attack_type):
        """User access gives 25 points."""
        finding = RedTeamFinding.objects.create(
            attack_type=attack_type,
            affected_boxes=["Web Server"],
            source_ip="10.0.0.1",
            submitted_by=users["red1"],
            user_access=True,
            points_per_team=0,
        )
        assert finding.calculate_points() == Decimal("25")

    def test_root_overrides_user_access(self, users, attack_type):
        """If both root and user access, only root is scored."""
        finding = RedTeamFinding.objects.create(
            attack_type=attack_type,
            affected_boxes=["Web Server"],
            source_ip="10.0.0.1",
            submitted_by=users["red1"],
            root_access=True,
            user_access=True,
            points_per_team=0,
        )
        # Only root access scored, not user access
        assert finding.calculate_points() == Decimal("100")

    def test_privilege_escalation_additional(self, users, attack_type):
        """Privilege escalation adds 100 on top of user access."""
        finding = RedTeamFinding.objects.create(
            attack_type=attack_type,
            affected_boxes=["Web Server"],
            source_ip="10.0.0.1",
            submitted_by=users["red1"],
            user_access=True,
            privilege_escalation=True,
            points_per_team=0,
        )
        # User (25) + Priv Esc (100) = 125
        assert finding.calculate_points() == Decimal("125")

    def test_all_data_recovery_outcomes(self, users, attack_type):
        """All data recovery outcomes are cumulative."""
        finding = RedTeamFinding.objects.create(
            attack_type=attack_type,
            affected_boxes=["Web Server"],
            source_ip="10.0.0.1",
            submitted_by=users["red1"],
            credentials_recovered=True,  # 50
            sensitive_files_recovered=True,  # 25
            credit_cards_recovered=True,  # 50
            pii_recovered=True,  # 200
            encrypted_db_recovered=True,  # 25
            db_decrypted=True,  # 25
            points_per_team=0,
        )
        # 50 + 25 + 50 + 200 + 25 + 25 = 375
        assert finding.calculate_points() == Decimal("375")

    def test_max_possible_points(self, users, attack_type):
        """Maximum possible points with all outcomes checked."""
        finding = RedTeamFinding.objects.create(
            attack_type=attack_type,
            affected_boxes=["Web Server"],
            source_ip="10.0.0.1",
            submitted_by=users["red1"],
            root_access=True,  # 100
            privilege_escalation=True,  # 100
            credentials_recovered=True,  # 50
            sensitive_files_recovered=True,  # 25
            credit_cards_recovered=True,  # 50
            pii_recovered=True,  # 200
            encrypted_db_recovered=True,  # 25
            db_decrypted=True,  # 25
            points_per_team=0,
        )
        # 100 + 100 + 50 + 25 + 50 + 200 + 25 + 25 = 575
        assert finding.calculate_points() == Decimal("575")

    def test_no_outcomes_zero_points(self, users, attack_type):
        """No outcomes checked gives 0 points."""
        finding = RedTeamFinding.objects.create(
            attack_type=attack_type,
            affected_boxes=["Web Server"],
            source_ip="10.0.0.1",
            submitted_by=users["red1"],
            points_per_team=0,
        )
        assert finding.calculate_points() == Decimal("0")


class TestOutcomesDisplay:
    """Tests for RedTeamFinding.outcomes_display property."""

    def test_outcomes_display_empty(self, users, attack_type):
        """No outcomes returns empty list."""
        finding = RedTeamFinding.objects.create(
            attack_type=attack_type,
            affected_boxes=["Web Server"],
            source_ip="10.0.0.1",
            submitted_by=users["red1"],
            points_per_team=0,
        )
        assert finding.outcomes_display == []

    def test_outcomes_display_root_access(self, users, attack_type):
        """Root access is shown in display."""
        finding = RedTeamFinding.objects.create(
            attack_type=attack_type,
            affected_boxes=["Web Server"],
            source_ip="10.0.0.1",
            submitted_by=users["red1"],
            root_access=True,
            points_per_team=0,
        )
        assert "Root Access (-100)" in finding.outcomes_display

    def test_outcomes_display_user_access_not_shown_with_root(self, users, attack_type):
        """User access not shown when root access present (matching calculate logic)."""
        finding = RedTeamFinding.objects.create(
            attack_type=attack_type,
            affected_boxes=["Web Server"],
            source_ip="10.0.0.1",
            submitted_by=users["red1"],
            root_access=True,
            user_access=True,
            points_per_team=0,
        )
        outcomes = finding.outcomes_display
        assert "Root Access (-100)" in outcomes
        assert "User Access (-25)" not in outcomes
