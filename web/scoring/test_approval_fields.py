"""
Tests for RedTeamFinding approval fields (MODEL-1).

This test file follows TDD methodology - tests are written first to define
the expected behavior of the approval tracking fields.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import TestCase

from team.models import Team

from .models import RedTeamFinding


class RedTeamFindingApprovalFieldsTests(TestCase):
    """Test RedTeamFinding approval tracking fields."""

    def setUp(self) -> None:
        """Set up test data."""
        self.red_user = User.objects.create_user(username="redteam", password="test123")
        self.gold_user = User.objects.create_user(username="goldteam", password="test123")
        self.team1 = Team.objects.create(team_number=1, team_name="Team 1")

    def test_new_finding_defaults_to_not_approved(self) -> None:
        """New findings should have is_approved=False by default."""
        finding = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("0"),
            submitted_by=self.red_user,
        )

        self.assertFalse(finding.is_approved)

    def test_approved_at_defaults_to_none(self) -> None:
        """New findings should have approved_at=None by default."""
        finding = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("0"),
            submitted_by=self.red_user,
        )

        self.assertIsNone(finding.approved_at)

    def test_approved_by_defaults_to_none(self) -> None:
        """New findings should have approved_by=None by default."""
        finding = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("0"),
            submitted_by=self.red_user,
        )

        self.assertIsNone(finding.approved_by)

    def test_can_set_is_approved_to_true(self) -> None:
        """Should be able to set is_approved to True."""
        finding = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("30.00"),
            submitted_by=self.red_user,
        )

        finding.is_approved = True
        finding.save()
        finding.refresh_from_db()

        self.assertTrue(finding.is_approved)

    def test_can_set_approved_at_datetime(self) -> None:
        """Should be able to set approved_at to a datetime."""
        finding = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("30.00"),
            submitted_by=self.red_user,
        )

        approval_time = datetime(2025, 11, 27, 12, 0, 0, tzinfo=UTC)
        finding.approved_at = approval_time
        finding.save()
        finding.refresh_from_db()

        self.assertEqual(finding.approved_at, approval_time)

    def test_can_set_approved_by_user(self) -> None:
        """Should be able to set approved_by to a User."""
        finding = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("30.00"),
            submitted_by=self.red_user,
        )

        finding.approved_by = self.gold_user
        finding.save()
        finding.refresh_from_db()

        self.assertEqual(finding.approved_by, self.gold_user)

    def test_full_approval_workflow(self) -> None:
        """Test complete approval workflow."""
        # Create unapproved finding
        finding = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("0"),
            submitted_by=self.red_user,
        )
        finding.affected_teams.add(self.team1)

        # Verify initial state
        self.assertFalse(finding.is_approved)
        self.assertIsNone(finding.approved_at)
        self.assertIsNone(finding.approved_by)

        # Approve finding
        approval_time = datetime.now(UTC)
        finding.is_approved = True
        finding.approved_at = approval_time
        finding.approved_by = self.gold_user
        finding.points_per_team = Decimal("30.00")
        finding.save()
        finding.refresh_from_db()

        # Verify approved state
        self.assertTrue(finding.is_approved)
        self.assertEqual(finding.approved_at, approval_time)
        self.assertEqual(finding.approved_by, self.gold_user)
        self.assertEqual(finding.points_per_team, Decimal("30.00"))

    def test_can_query_unapproved_findings(self) -> None:
        """Should be able to query for unapproved findings."""
        # Create approved finding
        approved = RedTeamFinding.objects.create(
            attack_vector="Approved attack",
            source_ip="10.0.0.5",
            points_per_team=Decimal("30.00"),
            submitted_by=self.red_user,
            is_approved=True,
            approved_by=self.gold_user,
            approved_at=datetime.now(UTC),
        )

        # Create unapproved finding
        unapproved = RedTeamFinding.objects.create(
            attack_vector="Unapproved attack",
            source_ip="10.0.0.6",
            points_per_team=Decimal("0"),
            submitted_by=self.red_user,
        )

        # Query for unapproved findings
        unapproved_findings = RedTeamFinding.objects.filter(is_approved=False)

        self.assertEqual(unapproved_findings.count(), 1)
        self.assertIn(unapproved, unapproved_findings)
        self.assertNotIn(approved, unapproved_findings)

    def test_can_query_approved_findings(self) -> None:
        """Should be able to query for approved findings."""
        # Create approved finding
        approved = RedTeamFinding.objects.create(
            attack_vector="Approved attack",
            source_ip="10.0.0.5",
            points_per_team=Decimal("30.00"),
            submitted_by=self.red_user,
            is_approved=True,
            approved_by=self.gold_user,
            approved_at=datetime.now(UTC),
        )

        # Create unapproved finding
        unapproved = RedTeamFinding.objects.create(
            attack_vector="Unapproved attack",
            source_ip="10.0.0.6",
            points_per_team=Decimal("0"),
            submitted_by=self.red_user,
        )

        # Query for approved findings
        approved_findings = RedTeamFinding.objects.filter(is_approved=True)

        self.assertEqual(approved_findings.count(), 1)
        self.assertIn(approved, approved_findings)
        self.assertNotIn(unapproved, approved_findings)

    def test_approved_by_can_be_null(self) -> None:
        """approved_by field should allow null values."""
        finding = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("0"),
            submitted_by=self.red_user,
            approved_by=None,
        )

        self.assertIsNone(finding.approved_by)

    def test_approved_at_can_be_null(self) -> None:
        """approved_at field should allow null values."""
        finding = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("0"),
            submitted_by=self.red_user,
            approved_at=None,
        )

        self.assertIsNone(finding.approved_at)

    def test_approved_by_survives_user_deletion(self) -> None:
        """approved_by should be set to NULL when user is deleted (SET_NULL)."""
        approver = User.objects.create_user(username="approver", password="test123")

        finding = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("30.00"),
            submitted_by=self.red_user,
            is_approved=True,
            approved_by=approver,
            approved_at=datetime.now(UTC),
        )

        # Verify approver is set
        self.assertEqual(finding.approved_by, approver)

        # Delete the approver
        approver.delete()

        # Refresh finding and verify approved_by is now NULL
        finding.refresh_from_db()
        self.assertIsNone(finding.approved_by)

        # Verify finding still exists
        self.assertTrue(RedTeamFinding.objects.filter(pk=finding.pk).exists())


@pytest.mark.django_db
class TestApprovalFieldsIntegration:
    """Integration tests for approval fields."""

    def test_can_filter_by_approval_status(self) -> None:
        """Should be able to efficiently filter by approval status."""
        user = User.objects.create_user(username="testuser", password="test123")
        gold_user = User.objects.create_user(username="golduser", password="test123")

        # Create 5 approved findings
        for i in range(5):
            RedTeamFinding.objects.create(
                attack_vector=f"Approved attack {i}",
                source_ip="10.0.0.5",
                points_per_team=Decimal("30.00"),
                submitted_by=user,
                is_approved=True,
                approved_by=gold_user,
                approved_at=datetime.now(UTC),
            )

        # Create 3 unapproved findings
        for i in range(3):
            RedTeamFinding.objects.create(
                attack_vector=f"Unapproved attack {i}",
                source_ip="10.0.0.6",
                points_per_team=Decimal("0"),
                submitted_by=user,
            )

        approved_count = RedTeamFinding.objects.filter(is_approved=True).count()
        unapproved_count = RedTeamFinding.objects.filter(is_approved=False).count()

        assert approved_count == 5
        assert unapproved_count == 3

    def test_approval_fields_work_with_existing_fields(self) -> None:
        """Approval fields should work alongside existing model fields."""
        user = User.objects.create_user(username="testuser", password="test123")
        gold_user = User.objects.create_user(username="golduser", password="test123")
        team = Team.objects.create(team_number=1, team_name="Team 1")

        finding = RedTeamFinding.objects.create(
            attack_vector="Complex attack vector",
            source_ip="10.0.0.5",
            destination_ip_template="10.100.1X.22",
            affected_box="web-server",
            affected_service="HTTP",
            universally_attempted=True,
            persistence_established=True,
            points_per_team=Decimal("50.00"),
            notes="Test notes",
            submitted_by=user,
            is_approved=True,
            approved_by=gold_user,
            approved_at=datetime.now(UTC),
        )
        finding.affected_teams.add(team)

        # Verify all fields are set correctly
        assert finding.attack_vector == "Complex attack vector"
        assert finding.is_approved is True
        assert finding.approved_by == gold_user
        assert finding.approved_at is not None
        assert finding.points_per_team == Decimal("50.00")
        assert finding.affected_teams.count() == 1
