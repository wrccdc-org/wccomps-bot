"""Tests for scorecard functionality."""

from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from scoring.models import FinalScore, ScoringTemplate, ServiceDetail
from team.models import Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def teams():
    """Create test teams."""
    return [
        Team.objects.create(team_number=1, team_name="Team A", is_active=True),
        Team.objects.create(team_number=2, team_name="Team B", is_active=True),
        Team.objects.create(team_number=3, team_name="Team C", is_active=True),
    ]


@pytest.fixture
def scores(teams):
    """Create FinalScore records for all teams."""
    return [
        FinalScore.objects.create(
            team=teams[0],
            service_points=Decimal("8000"),
            inject_points=Decimal("5000"),
            orange_points=Decimal("3000"),
            red_deductions=Decimal("-500"),
            sla_penalties=Decimal("-200"),
            total_score=Decimal("15300"),
            rank=2,
        ),
        FinalScore.objects.create(
            team=teams[1],
            service_points=Decimal("10000"),
            inject_points=Decimal("6000"),
            orange_points=Decimal("4000"),
            red_deductions=Decimal("-100"),
            sla_penalties=Decimal("-100"),
            total_score=Decimal("19800"),
            rank=1,
        ),
        FinalScore.objects.create(
            team=teams[2],
            service_points=Decimal("6000"),
            inject_points=Decimal("3000"),
            orange_points=Decimal("2000"),
            red_deductions=Decimal("-800"),
            sla_penalties=Decimal("-500"),
            total_score=Decimal("9700"),
            rank=3,
        ),
    ]


class TestComputeScorecardStats:
    """Tests for _compute_scorecard_stats function."""

    def test_compute_category_ranks(self, teams, scores):
        from scoring.views import _compute_scorecard_stats

        stats = _compute_scorecard_stats(teams[0], scores[0])

        assert stats["team_count"] == 3
        assert stats["category_ranks"]["services"]["rank"] == 2
        assert stats["category_ranks"]["services"]["avg"] == Decimal("8000")
        assert stats["category_ranks"]["injects"]["rank"] == 2
        assert stats["category_ranks"]["orange"]["rank"] == 2

    def test_compute_service_stats(self, teams, scores):
        from scoring.views import _compute_scorecard_stats

        # Create service details for all teams
        for t, pts in [(teams[0], 500), (teams[1], 700), (teams[2], 300)]:
            ServiceDetail.objects.create(team=t, service_name="dns", points=Decimal(str(pts)))
        for t, pts in [(teams[0], 400), (teams[1], 200), (teams[2], 600)]:
            ServiceDetail.objects.create(team=t, service_name="ssh", points=Decimal(str(pts)))

        stats = _compute_scorecard_stats(teams[0], scores[0])

        assert len(stats["service_stats"]) == 2
        dns_stat = next(s for s in stats["service_stats"] if s["name"] == "dns")
        assert dns_stat["points"] == Decimal("500")
        assert dns_stat["rank"] == 2
        assert dns_stat["avg"] == Decimal("500")

    def test_compute_insights(self, teams, scores):
        from scoring.views import _compute_scorecard_stats

        stats = _compute_scorecard_stats(teams[0], scores[0])

        assert len(stats["insights"]) >= 2
        assert all(isinstance(i, str) for i in stats["insights"])

    def test_excluded_team_not_in_stats(self, teams, scores):
        from scoring.views import _compute_scorecard_stats

        # Exclude team3 (rank 3)
        FinalScore.objects.filter(team=teams[2]).update(is_excluded=True)

        stats = _compute_scorecard_stats(teams[0], scores[0])

        assert stats["team_count"] == 2
        assert stats["category_ranks"]["services"]["rank"] == 2
        assert stats["category_ranks"]["services"]["avg"] == Decimal("9000")


class TestScorecardView:
    """Tests for scorecard view."""

    def test_requires_authentication(self, client, teams, scores):
        url = reverse("scoring:scorecard", args=[1])
        response = client.get(url)
        assert response.status_code == 302
        assert "login" in response.url

    def test_gold_team_can_access(self, gold_team_user, teams, scores):
        client = Client()
        client.force_login(gold_team_user)
        url = reverse("scoring:scorecard", args=[1])
        response = client.get(url)
        assert response.status_code == 200

    def test_returns_404_for_missing_team(self, gold_team_user, teams, scores):
        client = Client()
        client.force_login(gold_team_user)
        url = reverse("scoring:scorecard", args=[99])
        response = client.get(url)
        assert response.status_code == 404
