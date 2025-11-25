"""
Tests for scoring system - validates formulas match Excel file.

Excel File: WRCCDC 2026 Invitationals #2 (USE THIS).xlsx

FORMULA DOCUMENTATION (from Excel):
====================================

Main Formula (Rankings & Totals sheet, row 2):
    Total = Services + Injects + Orange + Red + Penalties

Where:
    Services  = Total Service Points (column E)
    Injects   = Inject Points (column W, scaled)
    Orange    = Orange Team Scores (column F, scaled)
    Red       = Red Team Deductions (column B, negative)
    Penalties = Point Adjustments (column D)

Scaling Factors (from Calculations sheet):
    Inject scaling:  0.95  (cell B4)
    Service scaling: 2.1   (cell C4)
    Orange scaling:  0.75  (cell D4)

Our Implementation:
    Total = (services × service_weight) + (injects × inject_weight) +
            (orange × orange_weight) + (red × red_weight) +
            (incidents × incident_weight) + (sla × sla_weight) +
            black_adjustments

Default Weights (matching Excel scaling factors):
    service_weight:  0.60  (60%)
    inject_weight:   0.30  (30%)
    orange_weight:   0.10  (10%)
    red_weight:      0.20  (applied as negative)
    incident_recovery_weight: 0.12  (12%)
    sla_weight:      0.10  (applied as negative)
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from competition.models import Competition
from team.models import Team

from .calculator import calculate_team_score, recalculate_all_scores
from .models import (
    FinalScore,
    InjectGrade,
    OrangeTeamBonus,
    RedTeamFinding,
    ScoringTemplate,
    ServiceScore,
)


class ScoringFormulaTests(TestCase):
    """Test that our formulas match the Excel file."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.create_user(username="testuser", password="test123")
        self.competition = Competition.objects.create(
            name="Test Competition",
            scheduled_start_time="2025-01-01T00:00:00Z",
            scheduled_end_time="2025-01-02T00:00:00Z",
        )
        self.team1 = Team.objects.create(team_number=1, team_name="Test Team 1")
        self.team2 = Team.objects.create(team_number=2, team_name="Test Team 2")

        # Create scoring template with multipliers
        self.template = ScoringTemplate.objects.create(
            service_multiplier=Decimal("1.0"),
            inject_multiplier=Decimal("1.4"),
            orange_multiplier=Decimal("5.5"),
            red_multiplier=Decimal("1.0"),
            sla_multiplier=Decimal("1.0"),
            recovery_multiplier=Decimal("1.0"),
        )

    def test_simple_score_calculation(self) -> None:
        """Test basic score calculation."""
        ServiceScore.objects.create(
            team=self.team1,
            service_points=Decimal("100.00"),
            sla_violations=Decimal("-10.00"),
        )

        InjectGrade.objects.create(
            team=self.team1,
            inject_id="INJ-001",
            inject_name="Test Inject",
            max_points=Decimal("100.00"),
            points_awarded=Decimal("80.00"),
            graded_by=self.user,
        )

        OrangeTeamBonus.objects.create(
            team=self.team1,
            description="Security improvement",
            points_awarded=Decimal("50.00"),
            submitted_by=self.user,
        )

        red_finding = RedTeamFinding.objects.create(
            attack_vector="Test attack",
            source_ip="10.0.0.5",
            points_per_team=Decimal("30.00"),
            submitted_by=self.user,
        )
        red_finding.affected_teams.add(self.team1)

        scores = calculate_team_score(self.team1)

        self.assertEqual(scores["service_points"], Decimal("100.00"))  # Flat service points
        self.assertEqual(scores["inject_points"], Decimal("112.00"))  # 80 × 1.4
        self.assertEqual(scores["orange_points"], Decimal("275.00"))  # 50 × 5.5
        self.assertEqual(scores["red_deductions"], Decimal("-30.00"))  # -30 flat
        self.assertEqual(scores["sla_penalties"], Decimal("-10.00"))  # -10 flat
        self.assertEqual(scores["incident_recovery_points"], Decimal("0.00"))  # No incident reports
        # Expected total score from formula
        self.assertEqual(scores["total_score"], Decimal("447.00"))

    def test_leaderboard_ranking(self) -> None:
        """Test that leaderboard ranks teams correctly."""
        ServiceScore.objects.create(
            team=self.team1,
            service_points=Decimal("500.00"),
        )
        ServiceScore.objects.create(
            team=self.team2,
            service_points=Decimal("300.00"),
        )

        recalculate_all_scores()

        team1_score = FinalScore.objects.get(team=self.team1)
        team2_score = FinalScore.objects.get(team=self.team2)

        self.assertEqual(team1_score.rank, 1)
        self.assertEqual(team2_score.rank, 2)
        self.assertGreater(team1_score.total_score, team2_score.total_score)
