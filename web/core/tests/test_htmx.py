"""Tests for htmx partial responses in core views."""

import pytest
from django.test import Client
from django.urls import reverse

from team.models import DiscordLink, Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def team_with_link(blue_team_user):
    """Create a team with DiscordLink for blue_team_user."""
    team = Team.objects.create(team_number=1, team_name="Test Team", is_active=True)
    DiscordLink.objects.create(
        discord_id=123456789,
        discord_username="blueteam01",
        user=blue_team_user,
        team=team,
        is_active=True,
    )
    return blue_team_user


class TestOpsTicketListHtmx:
    """Tests for ops_ticket_list htmx partial responses."""

    def test_htmx_request_returns_partial(self, ticketing_support_user):
        """htmx request returns only the ticket list table partial."""
        client = Client()
        client.force_login(ticketing_support_user)
        response = client.get(
            reverse("ops_ticket_list") + "?status=all",
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert 'id="ops-ticket-list-content"' in content
        assert "<title>" not in content

    def test_regular_request_returns_full_page(self, ticketing_support_user):
        """Regular request returns full page."""
        client = Client()
        client.force_login(ticketing_support_user)
        response = client.get(reverse("ops_ticket_list"))
        assert response.status_code == 200
        content = response.content.decode()
        assert "<title>" in content
        assert "Ticket List" in content


class TestTeamTicketsHtmx:
    """Tests for team_tickets htmx partial responses."""

    def test_htmx_request_returns_partial(self, team_with_link):
        """htmx request returns only the ticket list partial."""
        client = Client()
        client.force_login(team_with_link)
        response = client.get(
            reverse("team_tickets") + "?status=all",
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert 'id="ticket-list-content"' in content
        assert "<title>" not in content

    def test_regular_request_returns_full_page(self, team_with_link):
        """Regular request returns full page."""
        client = Client()
        client.force_login(team_with_link)
        response = client.get(reverse("team_tickets"))
        assert response.status_code == 200
        content = response.content.decode()
        assert "<title>" in content


class TestOpsReviewTicketsHtmx:
    """Tests for ops_review_tickets htmx partial responses."""

    def test_htmx_request_returns_partial(self, ticketing_admin_user):
        """htmx request returns only the review tickets table partial."""
        client = Client()
        client.force_login(ticketing_admin_user)
        response = client.get(
            reverse("ops_review_tickets") + "?verified=unverified",
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert 'id="review-tickets-content"' in content
        assert "<title>" not in content

    def test_regular_request_returns_full_page(self, ticketing_admin_user):
        """Regular request returns full page."""
        client = Client()
        client.force_login(ticketing_admin_user)
        response = client.get(reverse("ops_review_tickets"))
        assert response.status_code == 200
        content = response.content.decode()
        assert "<title>" in content
        assert "Review Tickets" in content
