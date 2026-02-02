"""Tests for event-scoped scoring functionality."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from django.test import Client
from django.urls import reverse
from registration.models import (
    Event,
    EventTeamAssignment,
    RegistrationContact,
    Season,
    TeamRegistration,
)

from scoring.calculator import (
    calculate_team_event_score,
    get_event_leaderboard,
    recalculate_event_scores,
)
from scoring.models import EventScore, InjectGrade, OrangeTeamBonus
from team.models import Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def season():
    """Create a test season."""
    return Season.objects.create(name="2025 Season", year=2025, is_active=True)


@pytest.fixture
def event(season):
    """Create a test event."""
    return Event.objects.create(
        season=season,
        name="Test Invitational",
        event_type="invitational",
        date="2025-03-15",
        start_time="09:00",
        end_time="17:00",
    )


@pytest.fixture
def team():
    """Create a test team."""
    return Team.objects.create(
        team_number=1,
        team_name="Team 01",
        is_active=True,
    )


@pytest.fixture
def registration():
    """Create a test registration."""
    return TeamRegistration.objects.create(
        school_name="Test High School",
        status="paid",
    )


@pytest.fixture
def registration_contact(registration):
    """Create a captain contact for registration."""
    return RegistrationContact.objects.create(
        registration=registration,
        role="captain",
        name="John Doe",
        email="captain@test.edu",
    )


@pytest.fixture
def team_assignment(event, team, registration):
    """Create an event team assignment."""
    return EventTeamAssignment.objects.create(
        event=event,
        registration=registration,
        team=team,
        password_generated="test-password-123",
    )


class TestCalculateTeamEventScore:
    """Tests for calculate_team_event_score function."""

    def test_empty_scores(self, team, event):
        """Should return zeros when no scores exist."""
        scores = calculate_team_event_score(team, event)

        assert scores["service_points"] == Decimal("0")
        assert scores["inject_points"] == Decimal("0")
        assert scores["orange_points"] == Decimal("0")
        assert scores["total_score"] == Decimal("0")

    def test_inject_points_scoped_to_event(self, team, event, season):
        """Should only count inject grades for the specific event."""
        # Create another event
        other_event = Event.objects.create(
            season=season,
            name="Other Event",
            event_type="qualifier",
            date="2025-04-15",
        )

        # Create inject grades for both events (must be approved to count)
        InjectGrade.objects.create(
            team=team,
            event=event,
            inject_id="inject1",
            inject_name="Inject 1",
            points_awarded=Decimal("100"),
            is_approved=True,
        )
        InjectGrade.objects.create(
            team=team,
            event=other_event,
            inject_id="inject2",
            inject_name="Inject 2",
            points_awarded=Decimal("200"),
            is_approved=True,
        )

        scores = calculate_team_event_score(team, event)

        # Should only count the inject for 'event', not 'other_event'
        # Default inject multiplier is 1.4
        assert scores["inject_points"] == Decimal("100") * Decimal("1.4")

    def test_orange_points_scoped_to_event(self, team, event, season):
        """Should only count orange bonuses for the specific event."""
        other_event = Event.objects.create(
            season=season,
            name="Other Event",
            event_type="qualifier",
            date="2025-04-15",
        )

        OrangeTeamBonus.objects.create(
            team=team,
            event=event,
            description="Good work",
            points_awarded=Decimal("50"),
            is_approved=True,
        )
        OrangeTeamBonus.objects.create(
            team=team,
            event=other_event,
            description="Other event bonus",
            points_awarded=Decimal("100"),
            is_approved=True,
        )

        scores = calculate_team_event_score(team, event)

        # Default orange multiplier is 5.5
        assert scores["orange_points"] == Decimal("50") * Decimal("5.5")


class TestRecalculateEventScores:
    """Tests for recalculate_event_scores function."""

    def test_creates_event_scores(self, event, team, team_assignment):
        """Should create EventScore records for assigned teams."""
        recalculate_event_scores(event)

        assert EventScore.objects.filter(event=event).count() == 1
        event_score = EventScore.objects.get(event=event, team=team)
        assert event_score.team_assignment == team_assignment

    def test_assigns_ranks(self, event, registration, season):
        """Should assign ranks based on total score."""
        # Create multiple teams and assignments
        team1 = Team.objects.create(team_number=1, team_name="Team 01", is_active=True)
        team2 = Team.objects.create(team_number=2, team_name="Team 02", is_active=True)

        EventTeamAssignment.objects.create(event=event, registration=registration, team=team1)

        reg2 = TeamRegistration.objects.create(school_name="School 2", status="paid")
        EventTeamAssignment.objects.create(event=event, registration=reg2, team=team2)

        # Give team2 more points (must be approved to count)
        InjectGrade.objects.create(
            team=team2,
            event=event,
            inject_id="inject1",
            inject_name="Inject 1",
            points_awarded=Decimal("100"),
            is_approved=True,
        )

        recalculate_event_scores(event)

        score1 = EventScore.objects.get(event=event, team=team1)
        score2 = EventScore.objects.get(event=event, team=team2)

        # Team2 should be ranked higher (rank 1)
        assert score2.rank == 1
        # Team1 has no scoring activity, should have no rank
        assert score1.rank is None


class TestGetEventLeaderboard:
    """Tests for get_event_leaderboard function."""

    def test_returns_ordered_scores(self, event, team, team_assignment):
        """Should return scores ordered by rank."""
        # Create inject grade to have scoring activity (must be approved to count)
        InjectGrade.objects.create(
            team=team,
            event=event,
            inject_id="inject1",
            inject_name="Inject 1",
            points_awarded=Decimal("100"),
            is_approved=True,
        )

        recalculate_event_scores(event)
        leaderboard = get_event_leaderboard(event)

        assert len(leaderboard) == 1
        assert leaderboard[0].team == team

    def test_excludes_inactive_teams(self, event, team, team_assignment):
        """Should exclude teams with no scoring activity."""
        recalculate_event_scores(event)
        leaderboard = get_event_leaderboard(event)

        # Team has no scoring activity, should be excluded
        assert len(leaderboard) == 0


class TestEventLeaderboardView:
    """Tests for event_leaderboard view."""

    def test_requires_authentication(self, client, event):
        """Unauthenticated users should be redirected."""
        url = reverse("scoring:event_leaderboard", args=[event.id])
        response = client.get(url)
        assert response.status_code == 302
        assert "login" in response.url or "accounts" in response.url

    def test_non_finalized_event_restricted(self, gold_team_user, event):
        """Non-finalized events should still be viewable by Gold Team."""
        client = Client()
        client.force_login(gold_team_user)

        url = reverse("scoring:event_leaderboard", args=[event.id])
        response = client.get(url)

        assert response.status_code == 200

    def test_finalized_event_accessible(self, gold_team_user, event):
        """Finalized events should be accessible."""
        event.is_finalized = True
        event.save()

        client = Client()
        client.force_login(gold_team_user)

        url = reverse("scoring:event_leaderboard", args=[event.id])
        response = client.get(url)

        assert response.status_code == 200


# Check if WeasyPrint dependencies are available (pango library)
try:
    from weasyprint import HTML  # noqa: F401

    WEASYPRINT_AVAILABLE = True
except OSError:
    WEASYPRINT_AVAILABLE = False


@pytest.mark.skipif(not WEASYPRINT_AVAILABLE, reason="WeasyPrint system dependencies not available")
class TestScorecardServices:
    """Tests for scorecard distribution services."""

    def test_get_scorecard_recipient_emails(self, event, team, team_assignment, registration_contact):
        """Should return captain and coach emails."""
        from scoring.services import get_scorecard_recipient_emails

        # Create event score
        event_score = EventScore.objects.create(
            team=team,
            event=event,
            team_assignment=team_assignment,
            total_score=Decimal("1000"),
        )

        emails = get_scorecard_recipient_emails(event_score)

        assert "captain@test.edu" in emails

    def test_send_scorecard_single_no_recipients(self, event, team, team_assignment):
        """Should fail gracefully when no recipients."""
        from scoring.services import send_scorecard_single

        event_score = EventScore.objects.create(
            team=team,
            event=event,
            team_assignment=team_assignment,
            total_score=Decimal("1000"),
        )

        result = send_scorecard_single(event_score)

        assert result.success is False
        assert "No email recipients" in result.error

    @patch("scoring.services.get_email_service")
    def test_send_scorecard_single_success(self, mock_get_email, event, team, team_assignment, registration_contact):
        """Should send scorecard email successfully."""
        from scoring.services import send_scorecard_single

        mock_email_service = MagicMock()
        mock_email_service.send_templated.return_value = True
        mock_get_email.return_value = mock_email_service

        event_score = EventScore.objects.create(
            team=team,
            event=event,
            team_assignment=team_assignment,
            total_score=Decimal("1000"),
            rank=1,
        )

        result = send_scorecard_single(event_score)

        assert result.success is True
        assert result.team_number == 1
        mock_email_service.send_templated.assert_called_once()

        # Verify scorecard_sent_at was updated
        event_score.refresh_from_db()
        assert event_score.scorecard_sent_at is not None
