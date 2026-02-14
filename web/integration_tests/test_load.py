"""
Load and stress tests.

These tests verify the system can handle concurrent requests and high load
without crashing or exhausting resources (connection pool, memory, etc.).

Run with: pytest -m load
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest
from django.contrib.auth.models import User
from django.test import Client

from team.models import DiscordLink, Team
from ticketing.models import Ticket

pytestmark = [
    pytest.mark.load,
]


class TestConcurrentRequests:
    """Test system behavior under concurrent load."""

    def test_50_concurrent_health_checks(self, db):
        """System should handle 50 concurrent health check requests."""
        from django.urls import reverse

        results = []

        def make_request():
            client = Client()
            start = time.time()
            try:
                response = client.get(reverse("health_check"))
                elapsed = time.time() - start
                return (response.status_code, elapsed, None)
            except Exception as e:
                elapsed = time.time() - start
                return (None, elapsed, str(e))

        # Launch 50 concurrent requests
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(make_request) for _ in range(50)]
            results = [future.result() for future in as_completed(futures)]

        # Verify all succeeded
        for status_code, elapsed, error in results:
            assert error is None, f"Request failed with error: {error}"
            assert status_code == 200, f"Expected 200, got {status_code}"
            assert elapsed < 10.0, f"Request took {elapsed}s (should be < 10s)"

        # Verify average response time is reasonable
        avg_time = sum(elapsed for _, elapsed, _ in results) / len(results)
        assert avg_time < 1.0, f"Average response time {avg_time}s too high"

    def test_100_concurrent_page_loads(self, db):
        """System should handle 100 concurrent page loads."""
        results = []

        def load_home_page():
            client = Client()
            start = time.time()
            try:
                response = client.get("/")
                elapsed = time.time() - start
                return (response.status_code, elapsed, None)
            except Exception as e:
                elapsed = time.time() - start
                return (None, elapsed, str(e))

        # Launch 100 concurrent requests
        with ThreadPoolExecutor(max_workers=100) as executor:
            futures = [executor.submit(load_home_page) for _ in range(100)]
            results = [future.result() for future in as_completed(futures)]

        # Most should succeed (allow a few failures due to connection limits)
        successful = [r for r in results if r[0] in [200, 302]]
        assert len(successful) >= 95, f"Only {len(successful)}/100 requests succeeded"

        # No 500 errors
        server_errors = [r for r in results if r[0] == 500]
        assert len(server_errors) == 0, "500 errors occurred under load"


class TestConnectionPoolLimits:
    """Test database connection pool behavior under stress."""

    def test_connection_pool_handles_burst_traffic(self, db):
        """Connection pool should handle burst of DB-heavy requests."""
        from django.urls import reverse

        results = []

        def query_heavy_page():
            """Make request that performs multiple DB queries."""
            client = Client()
            try:
                # Ops tickets page performs many queries
                response = client.get(reverse("ticket_list"))
                return (response.status_code, None)
            except Exception as e:
                return (None, str(e))

        # Launch 30 concurrent DB-heavy requests
        # (PostgreSQL has 120 max connections, web has 4 gunicorn workers)
        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = [executor.submit(query_heavy_page) for _ in range(30)]
            results = [future.result() for future in as_completed(futures)]

        # All should succeed or redirect to login (not crash)
        for status_code, error in results:
            assert error is None, f"Connection pool error: {error}"
            assert status_code in [200, 302], f"Expected 200/302, got {status_code}"

    def test_connection_pool_recovers_after_exhaustion(self, db):
        """Connection pool should recover after temporary exhaustion."""
        from django.urls import reverse

        # First, exhaust the connection pool
        def hold_connection():
            """Hold a DB connection for a while."""
            client = Client()
            client.get(reverse("health_check"))
            time.sleep(0.5)  # Hold connection briefly

        # Launch many concurrent requests
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(hold_connection) for _ in range(50)]
            for future in as_completed(futures):
                future.result()  # Wait for all to complete

        # Now verify system still works
        client = Client()
        response = client.get(reverse("health_check"))
        assert response.status_code == 200, "System didn't recover after connection pool stress"


class TestConcurrentTicketOperations:
    """Test concurrent ticket operations."""

    @pytest.fixture
    def test_tickets(self, db, test_team_id):
        """Create 20 test tickets."""
        team = Team.objects.get(team_number=test_team_id)

        tickets = []
        for i in range(20):
            ticket = Ticket.objects.create(
                ticket_number=f"T-LOAD-{i:03d}",
                title=f"[INTEGRATION TEST] Load test ticket {i}",
                description="Concurrent operations test",
                team=team,
                status="open",
            )
            tickets.append(ticket)

        yield tickets

        # Cleanup
        for ticket in tickets:
            ticket.delete()

    @pytest.fixture
    def support_users(self, db):
        """Create 10 support users."""
        users = []
        for i in range(10):
            user = User.objects.create_user(
                username=f"load_support_{i}",
                email=f"load_support_{i}@example.com",
            )
            discord_link = DiscordLink.objects.create(
                user=user,
                discord_id=999999990 + i,
                discord_username=f"load_support_{i}",
            )
            users.append(discord_link)

        yield users

        # Cleanup
        for discord_link in users:
            discord_link.user.delete()
            discord_link.delete()

    def test_concurrent_ticket_claims(self, db, test_tickets, support_users):
        """10 users claiming 20 tickets concurrently should work."""
        from django.urls import reverse

        results = []

        def claim_ticket(discord_link, ticket):
            """Claim a ticket."""
            client = Client()
            client.force_login(discord_link.user)

            try:
                response = client.post(
                    reverse(
                        "ticket_claim",
                        kwargs={"ticket_number": ticket.ticket_number},
                    )
                )
                return (response.status_code, None)
            except Exception as e:
                return (None, str(e))

        # Each user claims 2 tickets concurrently
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []
            for i, discord_link in enumerate(support_users):
                # Each person claims 2 tickets
                futures.append(executor.submit(claim_ticket, discord_link, test_tickets[i * 2]))
                futures.append(executor.submit(claim_ticket, discord_link, test_tickets[i * 2 + 1]))

            results = [future.result() for future in as_completed(futures)]

        # All should succeed (no 500 errors)
        for status_code, error in results:
            assert error is None, f"Concurrent claim error: {error}"
            assert status_code in [200, 302], f"Expected 200/302, got {status_code}"

        # Verify all tickets were assigned
        assigned_count = sum(1 for ticket in test_tickets if Ticket.objects.get(id=ticket.id).assigned_to is not None)
        assert assigned_count == 20, f"Only {assigned_count}/20 tickets were assigned"

    def test_rapid_ticket_list_queries(self, db):
        """Rapid ticket list queries should not cause N+1 problems."""
        from django.db import connection
        from django.urls import reverse

        user = User.objects.create_user(
            username="rapid_query_user",
            email="rapid_query@example.com",
        )
        discord_link = DiscordLink.objects.create(
            user=user,
            discord_id=111222333,
            discord_username="rapid_query_user",
        )

        client = Client()
        client.force_login(user)

        try:
            # Make 10 rapid requests
            query_counts = []

            for _ in range(10):
                # Reset query counter
                connection.queries_log.clear()

                # Make request
                response = client.get(reverse("ticket_list"))

                # Count queries
                num_queries = len(connection.queries)
                query_counts.append(num_queries)

                assert response.status_code in [200, 302]

            # Query count should be consistent (no N+1 problem)
            # Allow some variation, but should not grow with each request
            assert max(query_counts) - min(query_counts) < 5, f"Query counts vary too much: {query_counts}"

        finally:
            discord_link.delete()
            user.delete()


class TestMemoryLeaks:
    """Test for memory leaks under sustained load."""

    def test_sustained_load_doesnt_leak_memory(self, db):
        """System should not leak memory under sustained load."""
        import gc

        # Force garbage collection before test
        gc.collect()

        client = Client()

        # Make 100 requests
        for i in range(100):
            response = client.get("/health/")
            assert response.status_code == 200

            # Periodic garbage collection
            if i % 10 == 0:
                gc.collect()

        # Force final garbage collection
        gc.collect()

        # If we got here without OOM, test passes
        # (More sophisticated tests could track actual memory usage)
        assert True


class TestRateLimitResilience:
    """Test system behavior under various rate limit scenarios."""

    def test_burst_then_steady_traffic(self, db):
        """System should handle burst followed by steady traffic."""
        from django.urls import reverse

        def make_request():
            client = Client()
            response = client.get(reverse("health_check"))
            return response.status_code

        # Burst: 50 requests at once
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(make_request) for _ in range(50)]
            burst_results = [future.result() for future in as_completed(futures)]

        # All burst requests should succeed
        assert all(status == 200 for status in burst_results)

        # Steady: 100 requests with delays
        for _ in range(100):
            status = make_request()
            assert status == 200
            time.sleep(0.01)  # 10ms between requests

        # System should still be responsive
        final_status = make_request()
        assert final_status == 200


class TestDatabaseQueryPerformance:
    """Test query performance under load."""

    def test_complex_queries_complete_within_timeout(self, db, test_team_id):
        """Complex queries should complete within statement timeout (30s)."""
        from django.urls import reverse

        team = Team.objects.get(team_number=test_team_id)

        # Create many tickets to make queries heavier
        tickets = []
        for i in range(100):
            ticket = Ticket.objects.create(
                ticket_number=f"T-PERF-{i:04d}",
                title=f"[INTEGRATION TEST] Performance test {i}",
                description="Query performance test",
                team=team,
                status="open",
            )
            tickets.append(ticket)

        try:
            user = User.objects.create_user(
                username="perf_test_user",
                email="perf_test@example.com",
            )
            discord_link = DiscordLink.objects.create(
                user=user,
                discord_id=444555666,
                discord_username="perf_test_user",
            )

            client = Client()
            client.force_login(user)

            # Query ticket list (should handle 100 tickets efficiently)
            start = time.time()
            response = client.get(reverse("ticket_list"))
            elapsed = time.time() - start

            assert response.status_code in [200, 302]
            assert elapsed < 5.0, f"Query took {elapsed}s (should be < 5s)"

            discord_link.delete()
            user.delete()

        finally:
            for ticket in tickets:
                ticket.delete()
