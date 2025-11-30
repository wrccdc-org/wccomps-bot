"""Permission integration tests for core views (ops and ticketing)."""

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
