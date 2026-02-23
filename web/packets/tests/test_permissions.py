"""Permission tests for packets views."""

import pytest
from django.test import Client
from django.urls import reverse

from team.models import Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def team_1(db):
    """Create test team 1 for blue_team_user."""
    return Team.objects.create(team_number=1, team_name="Test Team 1", authentik_group="WCComps_BlueTeam01")


class TestTeamPacketPermissions:
    """Team packet view requires blue_team (which includes gold_team via hierarchy)."""

    def test_unauthenticated_redirects(self, unauthenticated_client):
        response = unauthenticated_client.get(reverse("team_packet"))
        assert response.status_code == 302

    @pytest.mark.parametrize(
        "user_fixture",
        ["red_team_user", "white_team_user", "orange_team_user", "ticketing_support_user"],
    )
    def test_unauthorized_roles_denied(self, user_fixture, request):
        user = request.getfixturevalue(user_fixture)
        client = Client()
        client.force_login(user)
        response = client.get(reverse("team_packet"))
        assert response.status_code == 302, f"{user_fixture} should be denied"

    @pytest.mark.parametrize("user_fixture", ["blue_team_user", "gold_team_user", "admin_user"])
    def test_authorized_roles_allowed(self, user_fixture, request, team_1):
        user = request.getfixturevalue(user_fixture)
        client = Client()
        client.force_login(user)
        response = client.get(reverse("team_packet"))
        assert response.status_code == 200, f"{user_fixture} should have access"


class TestPacketsManagementPermissions:
    """Packets management requires gold_team."""

    def test_unauthenticated_redirects(self, unauthenticated_client):
        response = unauthenticated_client.get(reverse("packets_list"))
        assert response.status_code == 302

    @pytest.mark.parametrize(
        "user_fixture",
        ["blue_team_user", "red_team_user", "white_team_user", "orange_team_user", "ticketing_support_user"],
    )
    def test_unauthorized_roles_denied(self, user_fixture, request):
        user = request.getfixturevalue(user_fixture)
        client = Client()
        client.force_login(user)
        response = client.get(reverse("packets_list"))
        assert response.status_code == 302, f"{user_fixture} should be denied"

    @pytest.mark.parametrize("user_fixture", ["gold_team_user", "admin_user"])
    def test_authorized_roles_allowed(self, user_fixture, request):
        user = request.getfixturevalue(user_fixture)
        client = Client()
        client.force_login(user)
        response = client.get(reverse("packets_list"))
        assert response.status_code == 200, f"{user_fixture} should have access"
