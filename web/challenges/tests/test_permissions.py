"""Permission tests for challenges views."""

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


class TestDashboardPermissions:
    """Dashboard requires orange_team or gold_team."""

    def test_unauthenticated_redirects(self, unauthenticated_client):
        response = unauthenticated_client.get(reverse("challenges:dashboard"))
        assert response.status_code == 302

    @pytest.mark.parametrize(
        "user_fixture",
        ["blue_team_user", "red_team_user", "white_team_user", "ticketing_support_user"],
    )
    def test_unauthorized_roles_denied(self, user_fixture, request):
        user = request.getfixturevalue(user_fixture)
        client = Client()
        client.force_login(user)
        response = client.get(reverse("challenges:dashboard"))
        assert response.status_code == 302, f"{user_fixture} should be denied"

    @pytest.mark.parametrize("user_fixture", ["orange_team_user", "gold_team_user", "admin_user"])
    def test_authorized_roles_allowed(self, user_fixture, request):
        user = request.getfixturevalue(user_fixture)
        client = Client()
        client.force_login(user)
        response = client.get(reverse("challenges:dashboard"))
        assert response.status_code == 200, f"{user_fixture} should have access"


class TestCheckManagementPermissions:
    """Check management requires gold_team only."""

    def test_unauthenticated_redirects(self, unauthenticated_client):
        response = unauthenticated_client.get(reverse("challenges:check_list"))
        assert response.status_code == 302

    @pytest.mark.parametrize(
        "user_fixture",
        ["blue_team_user", "red_team_user", "white_team_user", "orange_team_user", "ticketing_support_user"],
    )
    def test_unauthorized_roles_denied(self, user_fixture, request):
        user = request.getfixturevalue(user_fixture)
        client = Client()
        client.force_login(user)
        response = client.get(reverse("challenges:check_list"))
        assert response.status_code == 302, f"{user_fixture} should be denied"

    @pytest.mark.parametrize("user_fixture", ["gold_team_user", "admin_user"])
    def test_authorized_roles_allowed(self, user_fixture, request):
        user = request.getfixturevalue(user_fixture)
        client = Client()
        client.force_login(user)
        response = client.get(reverse("challenges:check_list"))
        assert response.status_code == 200, f"{user_fixture} should have access"
