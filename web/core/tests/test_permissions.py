"""Permission integration tests for core views (ops and ticketing)."""

import os

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db


class TestOpsSchoolInfoPermissions:
    """Test permissions for School Info view (/ops/school-info/)."""

    def test_unauthenticated_redirects_to_login(self, unauthenticated_client):
        """Unauthenticated users should be redirected to login."""
        response = unauthenticated_client.get(reverse("ops_school_info"))
        assert response.status_code == 302
        assert "/accounts/" in response.url or "login" in response.url

    def test_blue_team_denied(self, blue_team_user):
        """Blue Team should not access school info."""
        client = Client()
        client.force_login(blue_team_user)
        response = client.get(reverse("ops_school_info"))
        # View renders error template instead of 403
        assert response.status_code == 200
        assert b"Access denied" in response.content or b"permission" in response.content

    def test_red_team_denied(self, red_team_user):
        """Red Team should not access school info."""
        client = Client()
        client.force_login(red_team_user)
        response = client.get(reverse("ops_school_info"))
        assert response.status_code == 200
        assert b"Access denied" in response.content or b"permission" in response.content

    def test_gold_team_allowed(self, gold_team_user):
        """Gold Team should access school info."""
        client = Client()
        client.force_login(gold_team_user)
        response = client.get(reverse("ops_school_info"))
        assert response.status_code == 200
        # Should NOT contain access denied message
        assert b"Access denied" not in response.content

    def test_white_team_denied(self, white_team_user):
        """White Team should not access school info."""
        client = Client()
        client.force_login(white_team_user)
        response = client.get(reverse("ops_school_info"))
        assert response.status_code == 200
        assert b"Access denied" in response.content or b"permission" in response.content

    def test_orange_team_denied(self, orange_team_user):
        """Orange Team should not access school info."""
        client = Client()
        client.force_login(orange_team_user)
        response = client.get(reverse("ops_school_info"))
        assert response.status_code == 200
        assert b"Access denied" in response.content or b"permission" in response.content

    def test_ticketing_support_denied(self, ticketing_support_user):
        """Ticketing Support should not access school info."""
        client = Client()
        client.force_login(ticketing_support_user)
        response = client.get(reverse("ops_school_info"))
        assert response.status_code == 200
        assert b"Access denied" in response.content or b"permission" in response.content

    def test_ticketing_admin_denied(self, ticketing_admin_user):
        """Ticketing Admin should not access school info."""
        client = Client()
        client.force_login(ticketing_admin_user)
        response = client.get(reverse("ops_school_info"))
        assert response.status_code == 200
        assert b"Access denied" in response.content or b"permission" in response.content

    def test_admin_allowed(self, admin_user):
        """Admin (is_staff) should access school info."""
        client = Client()
        client.force_login(admin_user)
        response = client.get(reverse("ops_school_info"))
        assert response.status_code == 200


class TestGroupRoleMappingsPermissions:
    """Test permissions for Group Role Mappings view (/ops/group-role-mappings/)."""

    def test_unauthenticated_redirects_to_login(self, unauthenticated_client):
        """Unauthenticated users should be redirected to login."""
        response = unauthenticated_client.get(reverse("ops_group_role_mappings"))
        assert response.status_code == 302
        assert "/accounts/" in response.url or "login" in response.url

    def test_blue_team_denied(self, blue_team_user):
        """Blue Team should not access group role mappings."""
        client = Client()
        client.force_login(blue_team_user)
        response = client.get(reverse("ops_group_role_mappings"))
        assert response.status_code == 200
        assert b"Access denied" in response.content or b"permission" in response.content

    def test_red_team_denied(self, red_team_user):
        """Red Team should not access group role mappings."""
        client = Client()
        client.force_login(red_team_user)
        response = client.get(reverse("ops_group_role_mappings"))
        assert response.status_code == 200
        assert b"Access denied" in response.content or b"permission" in response.content

    def test_gold_team_allowed(self, gold_team_user):
        """Gold Team should access group role mappings."""
        client = Client()
        client.force_login(gold_team_user)
        response = client.get(reverse("ops_group_role_mappings"))
        assert response.status_code == 200
        # Should NOT contain access denied message
        assert b"Access denied" not in response.content

    def test_white_team_denied(self, white_team_user):
        """White Team should not access group role mappings."""
        client = Client()
        client.force_login(white_team_user)
        response = client.get(reverse("ops_group_role_mappings"))
        assert response.status_code == 200
        assert b"Access denied" in response.content or b"permission" in response.content

    def test_orange_team_denied(self, orange_team_user):
        """Orange Team should not access group role mappings."""
        client = Client()
        client.force_login(orange_team_user)
        response = client.get(reverse("ops_group_role_mappings"))
        assert response.status_code == 200
        assert b"Access denied" in response.content or b"permission" in response.content

    def test_admin_allowed(self, admin_user):
        """Admin (is_staff) should access group role mappings."""
        client = Client()
        client.force_login(admin_user)
        response = client.get(reverse("ops_group_role_mappings"))
        assert response.status_code == 200


@pytest.mark.skipif(
    os.environ.get("TICKETING_ENABLED", "false").lower() != "true",
    reason="Ticketing not enabled",
)
class TestTicketViewsPermissions:
    """Test permissions for ticketing views (requires TICKETING_ENABLED=true)."""

    def test_team_tickets_unauthenticated_redirects(self, unauthenticated_client):
        """Unauthenticated users should be redirected to login."""
        response = unauthenticated_client.get(reverse("team_tickets"))
        assert response.status_code == 302
        assert "/accounts/" in response.url or "login" in response.url

    def test_ops_tickets_unauthenticated_redirects(self, unauthenticated_client):
        """Unauthenticated users should be redirected to login."""
        response = unauthenticated_client.get(reverse("ops_ticket_list"))
        assert response.status_code == 302
        assert "/accounts/" in response.url or "login" in response.url

    def test_ops_tickets_blue_team_denied(self, blue_team_user):
        """Blue Team should not access ops tickets."""
        client = Client()
        client.force_login(blue_team_user)
        response = client.get(reverse("ops_ticket_list"))
        assert response.status_code == 403

    def test_ops_tickets_red_team_denied(self, red_team_user):
        """Red Team should not access ops tickets."""
        client = Client()
        client.force_login(red_team_user)
        response = client.get(reverse("ops_ticket_list"))
        assert response.status_code == 403

    def test_ops_tickets_gold_team_denied(self, gold_team_user):
        """Gold Team should not access ops tickets (ticketing specific roles)."""
        client = Client()
        client.force_login(gold_team_user)
        response = client.get(reverse("ops_ticket_list"))
        assert response.status_code == 403

    def test_ops_tickets_white_team_denied(self, white_team_user):
        """White Team should not access ops tickets."""
        client = Client()
        client.force_login(white_team_user)
        response = client.get(reverse("ops_ticket_list"))
        assert response.status_code == 403

    def test_ops_tickets_orange_team_denied(self, orange_team_user):
        """Orange Team should not access ops tickets."""
        client = Client()
        client.force_login(orange_team_user)
        response = client.get(reverse("ops_ticket_list"))
        assert response.status_code == 403

    def test_ops_tickets_ticketing_support_allowed(self, ticketing_support_user):
        """Ticketing Support should access ops tickets."""
        client = Client()
        client.force_login(ticketing_support_user)
        response = client.get(reverse("ops_ticket_list"))
        assert response.status_code == 200

    def test_ops_tickets_ticketing_admin_allowed(self, ticketing_admin_user):
        """Ticketing Admin should access ops tickets."""
        client = Client()
        client.force_login(ticketing_admin_user)
        response = client.get(reverse("ops_ticket_list"))
        assert response.status_code == 200

    def test_ops_tickets_admin_allowed(self, admin_user):
        """Admin (is_staff) should access ops tickets."""
        client = Client()
        client.force_login(admin_user)
        response = client.get(reverse("ops_ticket_list"))
        assert response.status_code == 200


class TestCompetitionAdminPermissions:
    """Test permissions for competition admin views (/competition/admin/)."""

    def test_unauthenticated_redirects_to_login(self, unauthenticated_client):
        """Unauthenticated users should be redirected to login."""
        response = unauthenticated_client.get(reverse("competition:dashboard"))
        assert response.status_code == 302
        assert "/accounts/" in response.url or "login" in response.url

    def test_blue_team_denied(self, blue_team_user):
        """Blue Team should not access competition admin."""
        client = Client()
        client.force_login(blue_team_user)
        response = client.get(reverse("competition:dashboard"))
        assert response.status_code == 302
        # Should redirect to home due to user_passes_test failure

    def test_red_team_denied(self, red_team_user):
        """Red Team should not access competition admin."""
        client = Client()
        client.force_login(red_team_user)
        response = client.get(reverse("competition:dashboard"))
        assert response.status_code == 302

    def test_gold_team_denied(self, gold_team_user):
        """Gold Team should not access competition admin (admin only)."""
        client = Client()
        client.force_login(gold_team_user)
        response = client.get(reverse("competition:dashboard"))
        assert response.status_code == 302

    def test_white_team_denied(self, white_team_user):
        """White Team should not access competition admin (admin only)."""
        client = Client()
        client.force_login(white_team_user)
        response = client.get(reverse("competition:dashboard"))
        assert response.status_code == 302

    def test_orange_team_denied(self, orange_team_user):
        """Orange Team should not access competition admin."""
        client = Client()
        client.force_login(orange_team_user)
        response = client.get(reverse("competition:dashboard"))
        assert response.status_code == 302

    def test_ticketing_support_denied(self, ticketing_support_user):
        """Ticketing Support should not access competition admin."""
        client = Client()
        client.force_login(ticketing_support_user)
        response = client.get(reverse("competition:dashboard"))
        assert response.status_code == 302

    def test_ticketing_admin_denied(self, ticketing_admin_user):
        """Ticketing Admin should not access competition admin."""
        client = Client()
        client.force_login(ticketing_admin_user)
        response = client.get(reverse("competition:dashboard"))
        assert response.status_code == 302

    def test_admin_allowed(self, admin_user):
        """Admin (is_staff) should access competition admin."""
        client = Client()
        client.force_login(admin_user)
        response = client.get(reverse("competition:dashboard"))
        assert response.status_code == 200


class TestPermissionMatrixSummary:
    """
    Summary test demonstrating the complete permission matrix.

    This test serves as documentation of the access control model.
    """

    def test_permission_matrix_documentation(
        self,
        blue_team_user,
        red_team_user,
        gold_team_user,
        white_team_user,
        orange_team_user,
        ticketing_support_user,
        ticketing_admin_user,
        admin_user,
    ):
        """
        Permission Matrix:

        View                        | Blue | Red | Gold | White | Orange | Ticket_Sup | Ticket_Adm | Admin
        ----------------------------|------|-----|------|-------|--------|------------|------------|------
        Leaderboard                 | NO   | NO  | YES  | YES   | NO     | NO         | YES        | YES
        Red Team Portal             | NO   | YES | YES  | NO    | NO     | NO         | NO         | YES
        Incident Submission         | *    | NO  | NO   | NO    | NO     | NO         | NO         | YES
        Orange Team Portal          | NO   | NO  | YES  | NO    | YES    | NO         | NO         | YES
        Inject Grading              | NO   | NO  | YES  | YES   | NO     | NO         | NO         | YES
        Ops Tickets                 | NO   | NO  | NO   | NO    | NO     | YES        | YES        | YES
        Ops School Info             | NO   | NO  | YES  | NO    | NO     | NO         | NO         | YES
        Ops Group Role Mappings     | NO   | NO  | YES  | NO    | NO     | NO         | NO         | YES
        Competition Admin           | NO   | NO  | NO   | NO    | NO     | NO         | NO         | YES
        Export Views                | NO   | NO  | NO   | NO    | NO     | NO         | NO         | YES

        * Blue Team can submit incidents only if they have a team assigned
        """
        # This test exists purely for documentation purposes
        assert True
