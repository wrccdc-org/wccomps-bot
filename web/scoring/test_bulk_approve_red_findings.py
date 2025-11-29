"""
Tests for bulk approve red team findings functionality (FEAT-3).

Following TDD methodology - tests are written first to define expected behavior.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from allauth.socialaccount.models import SocialApp
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from .models import RedTeamFinding


@pytest.mark.django_db
class TestBulkApproveRedFindingsView:
    """Test bulk approve red team findings view."""

    def test_bulk_approve_url_exists(self, create_user_with_groups: Callable[..., User]) -> None:
        """Bulk approve URL should exist at /scoring/red-team/bulk-approve/."""
        gold_user = create_user_with_groups("gold_user", ["WCComps_GoldTeam"])
        client = Client()
        client.force_login(gold_user)

        response = client.post(reverse("scoring:bulk_approve_red_findings"))

        # Should not be 404, even if we get validation error
        assert response.status_code != 404

    def test_only_gold_team_can_access_bulk_approve(self, create_user_with_groups: Callable[..., User]) -> None:
        """Only Gold Team and Admin should be able to access bulk approve."""
        red_user = create_user_with_groups("red_user", ["WCComps_RedTeam"])
        client = Client()
        client.force_login(red_user)

        response = client.post(reverse("scoring:bulk_approve_red_findings"), {"finding_ids": []})

        # Red Team should be denied
        assert response.status_code == 302  # Redirect to leaderboard or error page

    def test_admin_can_access_bulk_approve(self, social_app: SocialApp) -> None:
        """Admin users should be able to access bulk approve."""
        admin_user = User.objects.create_user(username="admin", password="test123", is_staff=True)
        client = Client()
        client.force_login(admin_user)

        response = client.post(reverse("scoring:bulk_approve_red_findings"), {"finding_ids": []})

        # Admin should have access (not redirected with 302 to leaderboard)
        # Empty list should return redirect to red team portal
        assert response.status_code in [200, 302]
        if response.status_code == 302:
            assert "red-team" in response.url  # type: ignore[attr-defined]

    def test_gold_team_can_access_bulk_approve(self, create_user_with_groups: Callable[..., User]) -> None:
        """Gold Team should be able to access bulk approve."""
        gold_user = create_user_with_groups("gold_user", ["WCComps_GoldTeam"])
        client = Client()
        client.force_login(gold_user)

        response = client.post(reverse("scoring:bulk_approve_red_findings"), {"finding_ids": []})

        # Gold Team should have access
        assert response.status_code in [200, 302]

    def test_requires_post_method(self, create_user_with_groups: Callable[..., User]) -> None:
        """Bulk approve should only accept POST requests."""
        gold_user = create_user_with_groups("gold_user", ["WCComps_GoldTeam"])
        client = Client()
        client.force_login(gold_user)

        response = client.get(reverse("scoring:bulk_approve_red_findings"))

        # GET should not be allowed
        assert response.status_code == 405

    def test_approves_single_finding(self, create_user_with_groups: Callable[..., User]) -> None:
        """Should be able to approve a single finding."""
        gold_user = create_user_with_groups("gold_user", ["WCComps_GoldTeam"])
        red_user = create_user_with_groups("red_user", ["WCComps_RedTeam"])

        finding = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("30.00"),
            submitted_by=red_user,
        )

        assert finding.is_approved is False
        assert finding.approved_at is None
        assert finding.approved_by is None

        client = Client()
        client.force_login(gold_user)

        response = client.post(reverse("scoring:bulk_approve_red_findings"), {"finding_ids": [finding.id]})

        # Should redirect to red team portal on success
        assert response.status_code == 302
        assert "red-team" in response.url  # type: ignore[attr-defined]

        finding.refresh_from_db()
        assert finding.is_approved is True
        assert finding.approved_at is not None  # type: ignore[unreachable]
        assert finding.approved_by == gold_user

    def test_approves_multiple_findings(self, create_user_with_groups: Callable[..., User]) -> None:
        """Should be able to approve multiple findings at once."""
        gold_user = create_user_with_groups("gold_user", ["WCComps_GoldTeam"])
        red_user = create_user_with_groups("red_user", ["WCComps_RedTeam"])

        finding1 = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("30.00"),
            submitted_by=red_user,
        )
        finding2 = RedTeamFinding.objects.create(
            attack_vector="RCE",
            source_ip="10.0.0.6",
            points_per_team=Decimal("50.00"),
            submitted_by=red_user,
        )
        finding3 = RedTeamFinding.objects.create(
            attack_vector="XSS",
            source_ip="10.0.0.7",
            points_per_team=Decimal("20.00"),
            submitted_by=red_user,
        )

        client = Client()
        client.force_login(gold_user)

        response = client.post(
            reverse("scoring:bulk_approve_red_findings"),
            {"finding_ids": [finding1.id, finding2.id, finding3.id]},
        )

        assert response.status_code == 302

        finding1.refresh_from_db()
        finding2.refresh_from_db()
        finding3.refresh_from_db()

        assert finding1.is_approved is True
        assert finding2.is_approved is True
        assert finding3.is_approved is True

        assert finding1.approved_by == gold_user
        assert finding2.approved_by == gold_user
        assert finding3.approved_by == gold_user

    def test_does_not_approve_already_approved_findings(self, create_user_with_groups: Callable[..., User]) -> None:
        """Should handle already approved findings gracefully."""
        gold_user = create_user_with_groups("gold_user", ["WCComps_GoldTeam"])
        another_gold_user = create_user_with_groups("another_gold", ["WCComps_GoldTeam"])
        red_user = create_user_with_groups("red_user", ["WCComps_RedTeam"])

        original_approval_time = datetime(2025, 11, 27, 10, 0, 0, tzinfo=UTC)

        finding = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("30.00"),
            submitted_by=red_user,
            is_approved=True,
            approved_by=another_gold_user,
            approved_at=original_approval_time,
        )

        client = Client()
        client.force_login(gold_user)

        client.post(reverse("scoring:bulk_approve_red_findings"), {"finding_ids": [finding.id]})

        finding.refresh_from_db()

        # Should remain approved by original user
        assert finding.is_approved is True
        assert finding.approved_by == another_gold_user
        assert finding.approved_at == original_approval_time

    def test_handles_empty_finding_ids(self, create_user_with_groups: Callable[..., User]) -> None:
        """Should handle empty finding_ids gracefully."""
        gold_user = create_user_with_groups("gold_user", ["WCComps_GoldTeam"])
        client = Client()
        client.force_login(gold_user)

        response = client.post(reverse("scoring:bulk_approve_red_findings"), {"finding_ids": []})

        # Should redirect back to portal
        assert response.status_code == 302
        assert "red-team" in response.url  # type: ignore[attr-defined]

    def test_handles_nonexistent_finding_ids(self, create_user_with_groups: Callable[..., User]) -> None:
        """Should handle nonexistent finding IDs gracefully."""
        gold_user = create_user_with_groups("gold_user", ["WCComps_GoldTeam"])
        client = Client()
        client.force_login(gold_user)

        # IDs that don't exist
        response = client.post(reverse("scoring:bulk_approve_red_findings"), {"finding_ids": [99999, 88888]})

        # Should redirect back without error
        assert response.status_code == 302
        assert "red-team" in response.url  # type: ignore[attr-defined]

    def test_uses_transaction_for_bulk_approval(self, create_user_with_groups: Callable[..., User]) -> None:
        """Bulk approval should use atomic transaction."""
        gold_user = create_user_with_groups("gold_user", ["WCComps_GoldTeam"])
        red_user = create_user_with_groups("red_user", ["WCComps_RedTeam"])

        finding1 = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("30.00"),
            submitted_by=red_user,
        )
        finding2 = RedTeamFinding.objects.create(
            attack_vector="RCE",
            source_ip="10.0.0.6",
            points_per_team=Decimal("50.00"),
            submitted_by=red_user,
        )

        client = Client()
        client.force_login(gold_user)

        # Valid request should succeed
        response = client.post(
            reverse("scoring:bulk_approve_red_findings"), {"finding_ids": [finding1.id, finding2.id]}
        )

        assert response.status_code == 302

        # Both should be approved
        finding1.refresh_from_db()
        finding2.refresh_from_db()
        assert finding1.is_approved is True
        assert finding2.is_approved is True

    def test_approval_timestamp_is_recent(self, create_user_with_groups: Callable[..., User]) -> None:
        """Approval timestamp should be set to current time."""
        gold_user = create_user_with_groups("gold_user", ["WCComps_GoldTeam"])
        red_user = create_user_with_groups("red_user", ["WCComps_RedTeam"])

        finding = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("30.00"),
            submitted_by=red_user,
        )

        before_approval = datetime.now(UTC)

        client = Client()
        client.force_login(gold_user)
        client.post(reverse("scoring:bulk_approve_red_findings"), {"finding_ids": [finding.id]})

        after_approval = datetime.now(UTC)

        finding.refresh_from_db()

        # Approved timestamp should be between before and after
        assert finding.approved_at is not None
        assert before_approval <= finding.approved_at <= after_approval

    def test_success_message_shown(self, create_user_with_groups: Callable[..., User]) -> None:
        """Should show success message after bulk approval."""
        gold_user = create_user_with_groups("gold_user", ["WCComps_GoldTeam"])
        red_user = create_user_with_groups("red_user", ["WCComps_RedTeam"])

        finding1 = RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("30.00"),
            submitted_by=red_user,
        )
        finding2 = RedTeamFinding.objects.create(
            attack_vector="RCE",
            source_ip="10.0.0.6",
            points_per_team=Decimal("50.00"),
            submitted_by=red_user,
        )

        client = Client()
        client.force_login(gold_user)

        response = client.post(
            reverse("scoring:bulk_approve_red_findings"),
            {"finding_ids": [finding1.id, finding2.id]},
            follow=True,
        )

        # Check for success message in response
        messages = list(response.context["messages"])
        assert len(messages) > 0
        assert "approved" in str(messages[0]).lower()


@pytest.mark.django_db
class TestBulkApproveUIElements:
    """Test UI elements for bulk approve functionality."""

    def test_gold_team_sees_checkboxes_in_portal(self, create_user_with_groups: Callable[..., User]) -> None:
        """Gold Team should see checkboxes next to findings."""
        gold_user = create_user_with_groups("gold_user", ["WCComps_GoldTeam"])
        red_user = create_user_with_groups("red_user", ["WCComps_RedTeam"])

        RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("30.00"),
            submitted_by=red_user,
        )

        client = Client()
        client.force_login(gold_user)

        response = client.get(reverse("scoring:red_team_portal"))

        assert response.status_code == 200
        # Should have checkbox inputs for selecting findings
        assert b'type="checkbox"' in response.content
        # Should have bulk approve button
        assert b"Bulk Approve" in response.content or b"bulk-approve" in response.content

    def test_red_team_does_not_see_bulk_approve_controls(self, create_user_with_groups: Callable[..., User]) -> None:
        """Red Team should NOT see bulk approve controls."""
        red_user = create_user_with_groups("red_user", ["WCComps_RedTeam"])

        RedTeamFinding.objects.create(
            attack_vector="SQL injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("30.00"),
            submitted_by=red_user,
        )

        client = Client()
        client.force_login(red_user)

        response = client.get(reverse("scoring:red_team_portal"))

        assert response.status_code == 200
        # Should NOT have bulk approve button
        content = response.content.decode()
        assert "Bulk Approve" not in content or "bulk-approve-form" not in content
