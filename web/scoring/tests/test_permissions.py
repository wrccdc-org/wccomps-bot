"""Permission integration tests for scoring views."""

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


class TestLeaderboardPermissions:
    """Test permissions for leaderboard view (/scoring/)."""

    def test_unauthenticated_redirects_to_login(self, unauthenticated_client):
        """Unauthenticated users should be redirected to login."""
        response = unauthenticated_client.get(reverse("scoring:leaderboard"))
        assert response.status_code == 302
        assert "/accounts/" in response.url or "login" in response.url

    def test_blue_team_denied(self, blue_team_user):
        """Blue Team should not access leaderboard."""
        client = Client()
        client.force_login(blue_team_user)
        response = client.get(reverse("scoring:leaderboard"))
        assert response.status_code == 403

    def test_red_team_denied(self, red_team_user):
        """Red Team should not access leaderboard."""
        client = Client()
        client.force_login(red_team_user)
        response = client.get(reverse("scoring:leaderboard"))
        assert response.status_code == 403

    def test_gold_team_allowed(self, gold_team_user):
        """Gold Team should access leaderboard."""
        client = Client()
        client.force_login(gold_team_user)
        response = client.get(reverse("scoring:leaderboard"))
        assert response.status_code == 200

    def test_white_team_allowed(self, white_team_user):
        """White Team should access leaderboard."""
        client = Client()
        client.force_login(white_team_user)
        response = client.get(reverse("scoring:leaderboard"))
        assert response.status_code == 200

    def test_orange_team_denied(self, orange_team_user):
        """Orange Team should not access leaderboard."""
        client = Client()
        client.force_login(orange_team_user)
        response = client.get(reverse("scoring:leaderboard"))
        assert response.status_code == 403

    def test_ticketing_support_denied(self, ticketing_support_user):
        """Ticketing Support should not access leaderboard."""
        client = Client()
        client.force_login(ticketing_support_user)
        response = client.get(reverse("scoring:leaderboard"))
        assert response.status_code == 403

    def test_ticketing_admin_allowed(self, ticketing_admin_user):
        """Ticketing Admin should access leaderboard."""
        client = Client()
        client.force_login(ticketing_admin_user)
        response = client.get(reverse("scoring:leaderboard"))
        assert response.status_code == 200

    def test_admin_allowed(self, admin_user):
        """Admin (is_staff) should access leaderboard."""
        client = Client()
        client.force_login(admin_user)
        response = client.get(reverse("scoring:leaderboard"))
        assert response.status_code == 200


class TestRedTeamPortalPermissions:
    """Test permissions for Red Team Portal (/scoring/red-team/)."""

    def test_unauthenticated_redirects_to_login(self, unauthenticated_client):
        """Unauthenticated users should be redirected to login."""
        response = unauthenticated_client.get(reverse("scoring:red_team_portal"))
        assert response.status_code == 302
        assert "/accounts/" in response.url or "login" in response.url

    def test_blue_team_denied(self, blue_team_user):
        """Blue Team should not access Red Team Portal."""
        client = Client()
        client.force_login(blue_team_user)
        response = client.get(reverse("scoring:red_team_portal"))
        assert response.status_code == 302
        assert "/scoring/" in response.url

    def test_red_team_denied(self, red_team_user):
        """Red Team should not access Gold Team review portal."""
        client = Client()
        client.force_login(red_team_user)
        response = client.get(reverse("scoring:red_team_portal"))
        assert response.status_code == 302

    def test_red_team_uses_findings_view(self, red_team_user):
        """Red Team should access their own findings view."""
        client = Client()
        client.force_login(red_team_user)
        response = client.get(reverse("scoring:red_team_findings"))
        assert response.status_code == 200

    def test_gold_team_allowed(self, gold_team_user):
        """Gold Team should access Red Team Portal."""
        client = Client()
        client.force_login(gold_team_user)
        response = client.get(reverse("scoring:red_team_portal"))
        assert response.status_code == 200

    def test_white_team_denied(self, white_team_user):
        """White Team should not access Red Team Portal."""
        client = Client()
        client.force_login(white_team_user)
        response = client.get(reverse("scoring:red_team_portal"))
        assert response.status_code == 302

    def test_orange_team_denied(self, orange_team_user):
        """Orange Team should not access Red Team Portal."""
        client = Client()
        client.force_login(orange_team_user)
        response = client.get(reverse("scoring:red_team_portal"))
        assert response.status_code == 302

    def test_ticketing_support_denied(self, ticketing_support_user):
        """Ticketing Support should not access Red Team Portal."""
        client = Client()
        client.force_login(ticketing_support_user)
        response = client.get(reverse("scoring:red_team_portal"))
        assert response.status_code == 302

    def test_ticketing_admin_denied(self, ticketing_admin_user):
        """Ticketing Admin should not access Red Team Portal."""
        client = Client()
        client.force_login(ticketing_admin_user)
        response = client.get(reverse("scoring:red_team_portal"))
        assert response.status_code == 302

    def test_admin_allowed(self, admin_user):
        """Admin (is_staff) should access Red Team Portal."""
        client = Client()
        client.force_login(admin_user)
        response = client.get(reverse("scoring:red_team_portal"))
        assert response.status_code == 200


class TestIncidentSubmissionPermissions:
    """Test permissions for Incident Submission (/scoring/incident/submit/)."""

    def test_unauthenticated_redirects_to_login(self, unauthenticated_client):
        """Unauthenticated users should be redirected to login."""
        response = unauthenticated_client.get(reverse("scoring:submit_incident_report"))
        assert response.status_code == 302
        assert "/accounts/" in response.url or "login" in response.url

    def test_blue_team_denied_without_team(self, blue_team_user):
        """Blue Team user without a team should be denied."""
        client = Client()
        client.force_login(blue_team_user)
        response = client.get(reverse("scoring:submit_incident_report"))
        # Should redirect to leaderboard with error message
        assert response.status_code == 302

    def test_red_team_denied_without_team(self, red_team_user):
        """Red Team should not submit incidents (not a blue team)."""
        client = Client()
        client.force_login(red_team_user)
        response = client.get(reverse("scoring:submit_incident_report"))
        assert response.status_code == 302

    def test_gold_team_denied_without_team(self, gold_team_user):
        """Gold Team should not submit incidents (not a blue team)."""
        client = Client()
        client.force_login(gold_team_user)
        response = client.get(reverse("scoring:submit_incident_report"))
        assert response.status_code == 302

    def test_white_team_denied_without_team(self, white_team_user):
        """White Team should not submit incidents (not a blue team)."""
        client = Client()
        client.force_login(white_team_user)
        response = client.get(reverse("scoring:submit_incident_report"))
        assert response.status_code == 302

    def test_orange_team_denied_without_team(self, orange_team_user):
        """Orange Team should not submit incidents (not a blue team)."""
        client = Client()
        client.force_login(orange_team_user)
        response = client.get(reverse("scoring:submit_incident_report"))
        assert response.status_code == 302

    def test_admin_allowed(self, admin_user, mock_quotient_client):
        """Admin (is_staff) should submit incidents."""
        client = Client()
        client.force_login(admin_user)
        response = client.get(reverse("scoring:submit_incident_report"))
        assert response.status_code == 200


class TestOrangeTeamPortalPermissions:
    """Test permissions for Orange Team Portal (/scoring/orange-team/)."""

    def test_unauthenticated_redirects_to_login(self, unauthenticated_client):
        """Unauthenticated users should be redirected to login."""
        response = unauthenticated_client.get(reverse("scoring:orange_team_portal"))
        assert response.status_code == 302
        assert "/accounts/" in response.url or "login" in response.url

    def test_blue_team_denied(self, blue_team_user):
        """Blue Team should not access Orange Team Portal."""
        client = Client()
        client.force_login(blue_team_user)
        response = client.get(reverse("scoring:orange_team_portal"))
        assert response.status_code == 302

    def test_red_team_denied(self, red_team_user):
        """Red Team should not access Orange Team Portal."""
        client = Client()
        client.force_login(red_team_user)
        response = client.get(reverse("scoring:orange_team_portal"))
        assert response.status_code == 302

    def test_gold_team_allowed(self, gold_team_user):
        """Gold Team should access Orange Team Portal."""
        client = Client()
        client.force_login(gold_team_user)
        response = client.get(reverse("scoring:orange_team_portal"))
        assert response.status_code == 200

    def test_white_team_denied(self, white_team_user):
        """White Team should not access Orange Team Portal."""
        client = Client()
        client.force_login(white_team_user)
        response = client.get(reverse("scoring:orange_team_portal"))
        assert response.status_code == 302

    def test_orange_team_allowed(self, orange_team_user):
        """Orange Team should access Orange Team Portal."""
        client = Client()
        client.force_login(orange_team_user)
        response = client.get(reverse("scoring:orange_team_portal"))
        assert response.status_code == 200

    def test_ticketing_support_denied(self, ticketing_support_user):
        """Ticketing Support should not access Orange Team Portal."""
        client = Client()
        client.force_login(ticketing_support_user)
        response = client.get(reverse("scoring:orange_team_portal"))
        assert response.status_code == 302

    def test_ticketing_admin_denied(self, ticketing_admin_user):
        """Ticketing Admin should not access Orange Team Portal."""
        client = Client()
        client.force_login(ticketing_admin_user)
        response = client.get(reverse("scoring:orange_team_portal"))
        assert response.status_code == 302

    def test_admin_allowed(self, admin_user):
        """Admin (is_staff) should access Orange Team Portal."""
        client = Client()
        client.force_login(admin_user)
        response = client.get(reverse("scoring:orange_team_portal"))
        assert response.status_code == 200


class TestInjectGradingPermissions:
    """Test permissions for Inject Grading (/scoring/injects/)."""

    def test_unauthenticated_redirects_to_login(self, unauthenticated_client):
        """Unauthenticated users should be redirected to login."""
        response = unauthenticated_client.get(reverse("scoring:inject_grading"))
        assert response.status_code == 302
        assert "/accounts/" in response.url or "login" in response.url

    def test_blue_team_denied(self, blue_team_user):
        """Blue Team should not access Inject Grading."""
        client = Client()
        client.force_login(blue_team_user)
        response = client.get(reverse("scoring:inject_grading"))
        assert response.status_code == 302

    def test_red_team_denied(self, red_team_user):
        """Red Team should not access Inject Grading."""
        client = Client()
        client.force_login(red_team_user)
        response = client.get(reverse("scoring:inject_grading"))
        assert response.status_code == 302

    def test_gold_team_allowed(self, gold_team_user, mock_quotient_client):
        """Gold Team should access Inject Grading."""
        client = Client()
        client.force_login(gold_team_user)
        response = client.get(reverse("scoring:inject_grading"))
        assert response.status_code == 200

    def test_white_team_allowed(self, white_team_user, mock_quotient_client):
        """White Team should access Inject Grading."""
        client = Client()
        client.force_login(white_team_user)
        response = client.get(reverse("scoring:inject_grading"))
        assert response.status_code == 200

    def test_orange_team_denied(self, orange_team_user):
        """Orange Team should not access Inject Grading."""
        client = Client()
        client.force_login(orange_team_user)
        response = client.get(reverse("scoring:inject_grading"))
        assert response.status_code == 302

    def test_ticketing_support_denied(self, ticketing_support_user):
        """Ticketing Support should not access Inject Grading."""
        client = Client()
        client.force_login(ticketing_support_user)
        response = client.get(reverse("scoring:inject_grading"))
        assert response.status_code == 302

    def test_ticketing_admin_denied(self, ticketing_admin_user):
        """Ticketing Admin should not access Inject Grading."""
        client = Client()
        client.force_login(ticketing_admin_user)
        response = client.get(reverse("scoring:inject_grading"))
        assert response.status_code == 302

    def test_admin_allowed(self, admin_user, mock_quotient_client):
        """Admin (is_staff) should access Inject Grading."""
        client = Client()
        client.force_login(admin_user)
        response = client.get(reverse("scoring:inject_grading"))
        assert response.status_code == 200


class TestExportViewsPermissions:
    """Test permissions for Export views (/scoring/export/)."""

    def test_export_index_unauthenticated_redirects(self, unauthenticated_client):
        """Unauthenticated users should be redirected to login."""
        response = unauthenticated_client.get(reverse("scoring:export_index"))
        assert response.status_code == 302
        assert "/accounts/" in response.url or "login" in response.url

    def test_export_index_blue_team_denied(self, blue_team_user):
        """Blue Team should not access export index."""
        client = Client()
        client.force_login(blue_team_user)
        response = client.get(reverse("scoring:export_index"))
        assert response.status_code == 302

    def test_export_index_red_team_denied(self, red_team_user):
        """Red Team should not access export index."""
        client = Client()
        client.force_login(red_team_user)
        response = client.get(reverse("scoring:export_index"))
        assert response.status_code == 302

    def test_export_index_gold_team_denied(self, gold_team_user):
        """Gold Team should not access export index (admin only)."""
        client = Client()
        client.force_login(gold_team_user)
        response = client.get(reverse("scoring:export_index"))
        assert response.status_code == 302

    def test_export_index_white_team_denied(self, white_team_user):
        """White Team should not access export index (admin only)."""
        client = Client()
        client.force_login(white_team_user)
        response = client.get(reverse("scoring:export_index"))
        assert response.status_code == 302

    def test_export_index_orange_team_denied(self, orange_team_user):
        """Orange Team should not access export index."""
        client = Client()
        client.force_login(orange_team_user)
        response = client.get(reverse("scoring:export_index"))
        assert response.status_code == 302

    def test_export_index_admin_allowed(self, admin_user):
        """Admin (is_staff) should access export index."""
        client = Client()
        client.force_login(admin_user)
        response = client.get(reverse("scoring:export_index"))
        assert response.status_code == 200
