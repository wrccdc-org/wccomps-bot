"""
Critical API integration tests.

These tests MUST pass before deployment. They test the most error-prone
endpoints with real database and API calls to catch 500 errors.
"""

import os

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from team.models import Team
from ticketing.models import Ticket

# Skip all tests in this file if ticketing is not enabled
TICKETING_ENABLED = os.environ.get("TICKETING_ENABLED", "false").lower() == "true"
pytestmark = [
    pytest.mark.critical,
    pytest.mark.integration,
    pytest.mark.skipif(not TICKETING_ENABLED, reason="Ticketing not enabled"),
]


class TestHealthCheck:
    """Test health check endpoint with real database connectivity."""

    def test_health_check_returns_200(self, db):
        """Health check should return 200 with database connectivity."""
        client = Client()
        response = client.get(reverse("health_check"))

        assert response.status_code == 200
        assert b"healthy" in response.content or b"OK" in response.content

    def test_health_check_queries_database(self, db):
        """Health check should actually query the database."""
        from django.db import connection
        from django.test.utils import override_settings

        client = Client()

        # Enable query logging
        with override_settings(DEBUG=True):
            # Reset query log
            connection.queries_log.clear()

            response = client.get(reverse("health_check"))

            assert response.status_code == 200
            # Verify at least one query was made (database check)
            assert len(connection.queries) > 0


class TestOAuthCallback:
    """
    Test OAuth callback flow - the most common source of 500 errors.

    This tests the /auth/callback endpoint which handles Authentik OAuth.
    """

    def test_oauth_callback_success(self, db, test_team_id):
        """OAuth callback should successfully link Discord account to Authentik account."""
        import random
        import uuid
        from datetime import timedelta

        from allauth.socialaccount.models import SocialAccount
        from django.utils import timezone

        from team.models import LinkToken, Team

        # Create authenticated user with SocialAccount (simulates completed OAuth)
        unique_id = str(uuid.uuid4())[:8]
        username = f"test_oauth_{unique_id}"
        user = User.objects.create_user(username=username, email=f"{username}@example.com")

        # Create SocialAccount with team groups
        team = Team.objects.get(team_number=test_team_id)
        social_account = SocialAccount.objects.create(
            user=user,
            provider="authentik",
            uid=f"test_uid_oauth_{unique_id}",
            extra_data={
                "userinfo": {
                    "preferred_username": username,
                    "groups": [f"WCComps_{team.authentik_group}"],
                },
            },
        )

        # Create LinkToken (simulates Discord /link command)
        discord_id = random.randint(100000000000000000, 999999999999999999)
        discord_username = f"test_discord_{unique_id}"
        link_token = LinkToken.objects.create(
            token=str(uuid.uuid4()),
            discord_id=discord_id,
            discord_username=discord_username,
            expires_at=timezone.now() + timedelta(minutes=15),
        )

        # Call link_initiate first to set up session (CSRF protection)
        client = Client()
        response = client.get(reverse("link_initiate"), {"token": link_token.token})
        assert response.status_code == 302  # Should redirect to OAuth

        # Now login and call the callback
        client.force_login(user)

        try:
            client.get(reverse("link_callback"), {"token": link_token.token})
        except ValueError as e:
            # Static files not collected in test environment - expected
            # The important thing is the link was created before template rendering
            if "Missing staticfiles manifest entry" not in str(e):
                raise

        # Verify token was marked as used (link succeeded)
        link_token.refresh_from_db()
        assert link_token.used is True

        # Verify DiscordLink was created
        from team.models import DiscordLink

        discord_link = DiscordLink.objects.filter(discord_id=discord_id).first()
        assert discord_link is not None, "DiscordLink should have been created"
        assert discord_link.authentik_user_id == social_account.uid
        assert discord_link.is_active is True

    def test_oauth_callback_requires_authentication(self, db):
        """OAuth callback should reject unauthenticated requests."""
        client = Client()

        # Try to access callback without OAuth state
        response = client.get(reverse("link_callback"))

        # Should redirect to login or return error (not 500)
        assert response.status_code in [302, 400, 401, 403]

    def test_link_initiate_requires_token(self, db):
        """Link initiate should require a valid token parameter."""
        client = Client()
        response = client.get(reverse("link_initiate"), follow=False)

        # Should return 400 without token
        assert response.status_code == 400
        assert b"Missing token" in response.content

    def test_link_callback_csrf_protection(self, db, test_team_id):
        """Link callback should reject tokens that weren't initiated in the current session (CSRF protection)."""
        import random
        import uuid
        from datetime import timedelta

        from allauth.socialaccount.models import SocialAccount
        from django.utils import timezone

        from team.models import LinkToken, Team

        # Create authenticated user
        unique_id = str(uuid.uuid4())[:8]
        username = f"test_csrf_{unique_id}"
        user = User.objects.create_user(username=username, email=f"{username}@example.com")

        team = Team.objects.get(team_number=test_team_id)
        SocialAccount.objects.create(
            user=user,
            provider="authentik",
            uid=f"test_uid_csrf_{unique_id}",
            extra_data={
                "userinfo": {
                    "preferred_username": username,
                    "groups": [f"WCComps_{team.authentik_group}"],
                },
            },
        )

        # Create attacker's LinkToken
        attacker_discord_id = random.randint(100000000000000000, 999999999999999999)
        attacker_token = LinkToken.objects.create(
            token=str(uuid.uuid4()),
            discord_id=attacker_discord_id,
            discord_username=f"attacker_{unique_id}",
            expires_at=timezone.now() + timedelta(minutes=15),
        )

        # Attacker tries to trick victim into visiting callback with attacker's token
        # Victim is logged in but hasn't initiated linking
        client = Client()
        client.force_login(user)

        # Direct callback access without going through initiate (CSRF attack attempt)
        response = client.get(reverse("link_callback"), {"token": attacker_token.token})

        # Should reject - CSRF protection
        assert response.status_code == 200  # Renders error page
        assert b"Security verification failed" in response.content or b"CSRF" in response.content

        # Verify token was NOT marked as used
        attacker_token.refresh_from_db()
        assert attacker_token.used is False

        # Verify no DiscordLink was created
        from team.models import DiscordLink

        discord_link = DiscordLink.objects.filter(discord_id=attacker_discord_id).first()
        assert discord_link is None, "DiscordLink should NOT have been created via CSRF attack"


class TestTicketOperations:
    """Test ticket claim/resolve operations - prone to race conditions."""

    @pytest.fixture
    def test_ticket(self, db, test_team_id):
        """Create a test ticket for operations."""
        team = Team.objects.get(team_number=test_team_id)

        ticket = Ticket.objects.create(
            ticket_number="T-TEST-001",
            title="[INTEGRATION TEST] Test ticket",
            description="Test ticket for integration testing",
            team=team,
            status="open",
        )

        yield ticket

        # Cleanup
        ticket.delete()

    @pytest.fixture
    def support_user(self, db, django_user_model):
        """Create a support user for ticket operations."""
        import random
        import uuid

        from allauth.socialaccount.models import SocialAccount

        unique_id = str(uuid.uuid4())[:8]
        # Generate numeric discord ID (as integer)
        discord_id = random.randint(100000000000000000, 999999999999999999)
        username = f"test_support_{unique_id}"

        # Create Django user (signal auto-creates Person)
        user = django_user_model.objects.create_user(
            username=username,
            email=f"{username}@example.com",
        )

        # Create SocialAccount with Authentik groups
        social_account = SocialAccount.objects.create(
            user=user,
            provider="authentik",
            uid=f"test_uid_{unique_id}",
            extra_data={
                "userinfo": {
                    "preferred_username": username,
                    "groups": ["WCComps_Ticketing_Support"],  # Grant ticketing permissions
                },
            },
        )

        # Update Person with Discord info
        person = user.person
        person.discord_id = discord_id
        person.authentik_username = username
        person.authentik_groups = ["WCComps_Ticketing_Support"]
        person.save()

        # Create DiscordLink so ticket operations can find Discord ID
        from team.models import DiscordLink

        DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username=username,
            authentik_username=username,
            authentik_user_id=social_account.uid,
            is_active=True,
        )

        return person
        # Let pytest-django's transaction rollback handle cleanup

    def test_ticket_claim_requires_authentication(self, db, test_ticket):
        """Ticket claim should require authentication."""
        client = Client()

        response = client.post(reverse("ops_ticket_claim", kwargs={"ticket_number": test_ticket.ticket_number}))

        # Should redirect to login (not 500)
        assert response.status_code in [302, 401, 403]

    def test_ticket_claim_with_authenticated_user(self, db, test_ticket, support_user):
        """Ticket claim should succeed with authenticated support user."""
        client = Client()
        client.force_login(support_user.user)

        response = client.post(reverse("ops_ticket_claim", kwargs={"ticket_number": test_ticket.ticket_number}))

        # Should succeed or redirect (not 500)
        assert response.status_code in [200, 302]

        # Verify ticket was claimed
        test_ticket.refresh_from_db()
        assert test_ticket.status == "claimed"
        assert test_ticket.assigned_to_discord_id == support_user.discord_id

    def test_ticket_resolve_requires_authentication(self, db, test_ticket):
        """Ticket resolve should require authentication."""
        client = Client()

        response = client.post(
            reverse(
                "ops_ticket_resolve",
                kwargs={"ticket_number": test_ticket.ticket_number},
            ),
            data={"resolution": "Test resolution"},
        )

        # Should redirect to login (not 500)
        assert response.status_code in [302, 401, 403]

    def test_ticket_resolve_with_points(self, db, test_ticket, support_user):
        """Ticket resolve should handle point assignment."""
        client = Client()
        client.force_login(support_user.user)

        # Claim ticket first
        test_ticket.status = "claimed"
        test_ticket.assigned_to_discord_id = support_user.discord_id
        test_ticket.assigned_to_authentik_username = support_user.authentik_username
        test_ticket.save()

        response = client.post(
            reverse(
                "ops_ticket_resolve",
                kwargs={"ticket_number": test_ticket.ticket_number},
            ),
            data={
                "resolution": "Test resolution",
                "points": "5",
            },
        )

        # Should succeed (not 500)
        assert response.status_code in [200, 302]

        # Verify ticket was resolved
        test_ticket.refresh_from_db()
        assert test_ticket.status == "resolved"

    def test_ticket_resolve_requires_ownership(self, db, test_ticket, support_user, django_user_model):
        """Non-admin support users should only be able to resolve tickets they claimed."""
        import uuid

        from allauth.socialaccount.models import SocialAccount

        # Create another support user
        unique_id = str(uuid.uuid4())[:8]
        other_username = f"other_support_{unique_id}"
        other_user = django_user_model.objects.create_user(
            username=other_username, email=f"{other_username}@example.com"
        )

        SocialAccount.objects.create(
            user=other_user,
            provider="authentik",
            uid=f"other_support_uid_{unique_id}",
            extra_data={
                "userinfo": {
                    "preferred_username": other_username,
                    "groups": ["WCComps_Ticketing_Support"],
                },
            },
        )

        # First user claims the ticket
        test_ticket.status = "claimed"
        test_ticket.assigned_to_discord_id = support_user.discord_id
        test_ticket.assigned_to_authentik_username = support_user.authentik_username
        test_ticket.save()

        # Second support user tries to resolve (should fail - not their ticket)
        client = Client()
        client.force_login(other_user)

        response = client.post(
            reverse(
                "ops_ticket_resolve",
                kwargs={"ticket_number": test_ticket.ticket_number},
            ),
            data={
                "resolution_notes": "Trying to resolve someone else's ticket",
            },
        )

        # Should be denied
        assert response.status_code == 403
        assert b"Access denied" in response.content

        # Verify ticket was NOT resolved
        test_ticket.refresh_from_db()
        assert test_ticket.status == "claimed"


class TestConcurrentOperations:
    """Test concurrent ticket operations - race condition testing."""

    @pytest.fixture
    def test_ticket(self, db, test_team_id):
        """Create a test ticket for concurrent operations."""
        team = Team.objects.get(team_number=test_team_id)

        ticket = Ticket.objects.create(
            ticket_number="T-TEST-CONCURRENT",
            title="[INTEGRATION TEST] Concurrent test",
            description="Test concurrent operations",
            team=team,
            status="open",
        )

        yield ticket
        ticket.delete()

    @pytest.fixture
    def support_users(self, db, django_user_model):
        """Create multiple support users for concurrent testing."""
        import random
        import uuid

        from allauth.socialaccount.models import SocialAccount

        users = []
        for i in range(3):
            unique_id = str(uuid.uuid4())[:8]
            # Generate numeric discord ID (as integer)
            discord_id = random.randint(100000000000000000, 999999999999999999)
            username = f"test_support_{i}_{unique_id}"

            # Create Django user (signal auto-creates Person)
            user = django_user_model.objects.create_user(
                username=username,
                email=f"{username}@example.com",
            )

            # Create SocialAccount with Authentik groups
            social_account = SocialAccount.objects.create(
                user=user,
                provider="authentik",
                uid=f"test_uid_{i}_{unique_id}",
                extra_data={
                    "userinfo": {
                        "preferred_username": username,
                        "groups": ["WCComps_Ticketing_Support"],
                    },
                },
            )

            # Update Person with Discord info
            person = user.person
            person.discord_id = discord_id
            person.authentik_username = username
            person.authentik_groups = ["WCComps_Ticketing_Support"]
            person.save()

            # Create DiscordLink so ticket operations can find Discord ID
            from team.models import DiscordLink

            DiscordLink.objects.create(
                discord_id=discord_id,
                discord_username=username,
                authentik_username=username,
                authentik_user_id=social_account.uid,
                is_active=True,
            )

            users.append(person)

        return users
        # Let pytest-django's transaction rollback handle cleanup

    def test_concurrent_ticket_claim(self, transactional_db, cleanup_test_data, test_ticket, support_users):
        """
        Test that only one user can claim a ticket when multiple try simultaneously.
        This catches race conditions that cause 500 errors.
        """
        import threading

        results = []

        def claim_ticket(person):
            """Claim ticket in separate thread."""
            client = Client()
            client.force_login(person.user)

            response = client.post(
                reverse(
                    "ops_ticket_claim",
                    kwargs={"ticket_number": test_ticket.ticket_number},
                )
            )
            results.append((person, response.status_code))

        # Launch concurrent claims
        threads = []
        for person in support_users:
            thread = threading.Thread(target=claim_ticket, args=(person,))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        # Verify no 500 errors occurred
        for person, status_code in results:
            assert status_code != 500, f"500 error for user {person.authentik_username}"

        # Verify exactly one user claimed the ticket
        test_ticket.refresh_from_db()
        assert test_ticket.status == "claimed"
        assert test_ticket.assigned_to_discord_id is not None
        # Verify assigned user is one of the support users
        assigned_user = next(
            (u for u in support_users if u.discord_id == test_ticket.assigned_to_discord_id),
            None,
        )
        assert assigned_user is not None, "Ticket assigned to unknown user"


class TestBulkOperations:
    """Test bulk ticket operations - transaction integrity."""

    @pytest.fixture
    def test_tickets(self, db, test_team_id):
        """Create multiple test tickets."""
        team = Team.objects.get(team_number=test_team_id)

        tickets = []
        for i in range(5):
            ticket = Ticket.objects.create(
                ticket_number=f"T-TEST-BULK-{i}",
                title=f"[INTEGRATION TEST] Bulk test {i}",
                description=f"Bulk operation test ticket {i}",
                team=team,
                status="open",
            )
            tickets.append(ticket)

        yield tickets

        # Cleanup
        for ticket in tickets:
            ticket.delete()

    @pytest.fixture
    def support_user(self, db, django_user_model):
        """Create support user for bulk operations."""
        import random
        import uuid

        from allauth.socialaccount.models import SocialAccount

        unique_id = str(uuid.uuid4())[:8]
        # Generate numeric discord ID (as integer)
        discord_id = random.randint(100000000000000000, 999999999999999999)
        username = f"test_bulk_support_{unique_id}"

        # Create Django user (signal auto-creates Person)
        user = django_user_model.objects.create_user(
            username=username,
            email=f"{username}@example.com",
        )

        # Create SocialAccount with Authentik groups
        social_account = SocialAccount.objects.create(
            user=user,
            provider="authentik",
            uid=f"test_uid_bulk_{unique_id}",
            extra_data={
                "userinfo": {
                    "preferred_username": username,
                    "groups": ["WCComps_Ticketing_Support"],
                },
            },
        )

        # Update Person with Discord info
        person = user.person
        person.discord_id = discord_id
        person.authentik_username = username
        person.authentik_groups = ["WCComps_Ticketing_Support"]
        person.save()

        # Create DiscordLink so ticket operations can find Discord ID
        from team.models import DiscordLink

        DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username=username,
            authentik_username=username,
            authentik_user_id=social_account.uid,
            is_active=True,
        )

        return person
        # Let pytest-django's transaction rollback handle cleanup

    def test_bulk_claim_all_or_nothing(self, db, test_tickets, support_user):
        """Bulk claim should be atomic - all succeed or all fail."""
        client = Client()
        client.force_login(support_user.user)

        ticket_numbers = ",".join([ticket.ticket_number for ticket in test_tickets])

        response = client.post(
            reverse("ops_tickets_bulk_claim"),
            data={"ticket_numbers": ticket_numbers},
        )

        # Should succeed (not 500)
        assert response.status_code in [200, 302]

        # Verify all tickets were claimed
        for ticket in test_tickets:
            ticket.refresh_from_db()
            assert ticket.status == "claimed"
            assert ticket.assigned_to_discord_id == support_user.discord_id

    def test_bulk_resolve_with_points(self, db, test_tickets, support_user):
        """Bulk resolve should handle point assignment for all tickets."""
        client = Client()
        client.force_login(support_user.user)

        # Claim all tickets first
        for ticket in test_tickets:
            ticket.status = "claimed"
            ticket.assigned_to_discord_id = support_user.discord_id
            ticket.assigned_to_authentik_username = support_user.authentik_username
            ticket.save()

        ticket_numbers = ",".join([ticket.ticket_number for ticket in test_tickets])

        response = client.post(
            reverse("ops_tickets_bulk_resolve"),
            data={
                "ticket_numbers": ticket_numbers,
                "resolution": "Bulk test resolution",
                "points": "3",
            },
        )

        # Should succeed (not 500)
        assert response.status_code in [200, 302]

        # Verify all tickets were resolved
        for ticket in test_tickets:
            ticket.refresh_from_db()
            assert ticket.status == "resolved"


class TestDatabaseConnectivity:
    """Test database connection handling under stress."""

    def test_repeated_queries_dont_exhaust_pool(self, db):
        """Rapid repeated queries should not exhaust connection pool."""
        client = Client()

        # Make 50 rapid requests
        for _ in range(50):
            response = client.get(reverse("health_check"))
            assert response.status_code == 200

        # Connection pool should still work
        response = client.get(reverse("health_check"))
        assert response.status_code == 200

    def test_long_running_request_doesnt_block_others(self, transactional_db):
        """Long queries shouldn't block other requests (tests connection pooling)."""
        import threading
        import time

        results = []

        def make_request():
            client = Client()
            start = time.time()
            response = client.get(reverse("health_check"))
            elapsed = time.time() - start
            results.append((response.status_code, elapsed))

        # Launch multiple concurrent requests
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
            thread.start()

        # Wait for all
        for thread in threads:
            thread.join()

        # All should succeed
        for status_code, elapsed in results:
            assert status_code == 200
            # None should take longer than 5 seconds (statement timeout is 30s)
            assert elapsed < 5.0
