"""Tests for htmx partial responses in registration views."""

from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from core.models import UserGroups

pytestmark = pytest.mark.django_db


@pytest.fixture
def gold_team_user(db):
    """Create a gold team user."""
    user = User.objects.create_user(username="gold_user", password="test")
    UserGroups.objects.create(user=user, authentik_id="gold-user-uid", groups=["WCComps_GoldTeam"])
    return user


class TestRegistrationReviewListHtmx:
    """Tests for registration_review_list htmx partial responses."""

    @patch("core.auth_utils.has_permission", return_value=True)
    def test_htmx_request_returns_partial(self, mock_perm, gold_team_user):
        """htmx request returns only the registration table partial."""
        client = Client()
        client.force_login(gold_team_user)
        response = client.get(
            reverse("registration_review_list") + "?status=pending",
            HTTP_HX_REQUEST="true",
        )
        assert response.status_code == 200
        content = response.content.decode()
        assert 'id="registration-review-content"' in content
        assert "<title>" not in content

    @patch("core.auth_utils.has_permission", return_value=True)
    def test_regular_request_returns_full_page(self, mock_perm, gold_team_user):
        """Regular request returns full page."""
        client = Client()
        client.force_login(gold_team_user)
        response = client.get(reverse("registration_review_list"))
        assert response.status_code == 200
        content = response.content.decode()
        assert "<title>" in content
        assert "Team Registration Review" in content
