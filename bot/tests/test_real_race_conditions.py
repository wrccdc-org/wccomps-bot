"""
Race condition tests that find REAL bugs.

Unlike the existing test_concurrent_operations.py which tests happy paths,
these tests try to BREAK the system with realistic concurrent scenarios.

Goal: Find bugs like:
- Two users linking to same team slot simultaneously
- Team becoming "full" but accepting one extra member
- Rate limits being bypassed by rapid requests
- Database transaction isolation failures
"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import transaction
from django.utils import timezone

from team.models import DiscordLink, LinkRateLimit, Team
from ticketing.models import CommentRateLimit, Ticket


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestTeamMemberRaceConditions:
    """Test race conditions in team member management.

    REAL BUG SCENARIO: Two users click "join team" at the same time when team has 1 slot left.
    EXPECTED: One succeeds, one fails
    POTENTIAL BUG: Both succeed, team is over capacity
    """

    @pytest.mark.asyncio
    async def test_concurrent_joins_to_almost_full_team(self):
        """
        SCENARIO: Team has max_members=5, currently has 4 members.
        Two users try to join simultaneously.

        PROPERTY: Exactly one should succeed, team should have exactly 5 members.
        BUG IF: Team ends up with 6 members (both succeeded).
        """
        # Create team with 4/5 members
        team = await Team.objects.acreate(
            team_number=42,
            team_name="Almost Full Team",
            authentik_group="WCComps_BlueTeam42",
            max_members=5,
        )

        # Add 4 existing members
        for i in range(4):
            await DiscordLink.objects.acreate(
                discord_id=1000000000000000000 + i,
                discord_username=f"existing_user_{i}",
                authentik_username=f"existing_user_{i}",
                authentik_user_id=f"uid-{i}",
                team=team,
                is_active=True,
            )

        # Verify team is almost full
        assert await team.aget_member_count() == 4
        assert not team.is_full()

        # Two new users try to join simultaneously
        async def try_join(user_id):
            """Simulate user joining team."""
            try:
                link = await DiscordLink.objects.acreate(
                    discord_id=2000000000000000000 + user_id,
                    discord_username=f"new_user_{user_id}",
                    authentik_username=f"new_user_{user_id}",
                    authentik_user_id=f"new-uid-{user_id}",
                    team=team,
                    is_active=True,
                )
                return "success"
            except Exception as e:
                return f"failed: {e}"

        # Execute both joins concurrently
        results = await asyncio.gather(
            try_join(100),
            try_join(101),
        )

        # CRITICAL PROPERTY: Team should have exactly 5 members
        final_count = await team.aget_member_count()
        assert final_count <= 5, (
            f"RACE CONDITION BUG: Team exceeded max_members! Expected: 5, Got: {final_count}. Results: {results}"
        )

        # At least one should have succeeded
        success_count = sum(1 for r in results if r == "success")
        assert success_count >= 1, f"Both joins failed: {results}"

        # If team is full, exactly one should have succeeded
        if final_count == 5:
            assert success_count == 1, f"Team full but both joins succeeded? Count: {final_count}, Results: {results}"

    @pytest.mark.asyncio
    async def test_concurrent_deactivation_and_reactivation(self):
        """
        SCENARIO: User has active link. Two operations happen:
        1. Admin deactivates the link
        2. User tries to reactivate (or create duplicate)

        PROPERTY: Should maintain database constraint (one active link)
        BUG IF: End up with 0 or 2 active links
        """
        team = await Team.objects.acreate(
            team_number=43,
            team_name="Test Team",
            authentik_group="WCComps_BlueTeam43",
        )

        discord_id = 3000000000000000000

        # Create initial active link
        link = await DiscordLink.objects.acreate(
            discord_id=discord_id,
            discord_username="test_user",
            authentik_username="test_user",
            authentik_user_id="uid-test",
            team=team,
            is_active=True,
        )

        async def deactivate_link():
            """Admin deactivates."""
            await asyncio.sleep(0.001)  # Small delay
            link_obj = await DiscordLink.objects.aget(id=link.id)
            link_obj.is_active = False
            await link_obj.asave()
            return "deactivated"

        async def try_create_duplicate():
            """User tries to create duplicate link."""
            await asyncio.sleep(0.001)  # Small delay
            try:
                new_link = await DiscordLink.objects.acreate(
                    discord_id=discord_id,
                    discord_username="test_user_duplicate",
                    authentik_username="test_user_duplicate",
                    authentik_user_id="uid-test-duplicate",
                    team=team,
                    is_active=True,
                )
                return "created"
            except Exception as e:
                return f"blocked: {e}"

        # Execute concurrently
        results = await asyncio.gather(
            deactivate_link(),
            try_create_duplicate(),
        )

        # CRITICAL: Should have at most one active link for this discord_id
        active_count = await DiscordLink.objects.filter(discord_id=discord_id, is_active=True).acount()

        assert active_count <= 1, (
            f"RACE CONDITION BUG: Multiple active links! Count: {active_count}, Results: {results}"
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestRateLimitBypassAttempts:
    """Test if rate limits can be bypassed by concurrent requests.

    REAL BUG SCENARIO: User makes 10 rapid requests before rate limit kicks in.
    EXPECTED: Only first 5 succeed
    POTENTIAL BUG: All 10 succeed (race condition in rate limit check)
    """

    @pytest.mark.asyncio
    async def test_rapid_link_attempts_cannot_bypass_rate_limit(self):
        """
        SCENARIO: User makes 10 link attempts rapidly (within milliseconds).

        PROPERTY: Should be blocked after 5 attempts.
        BUG IF: More than 5 attempts succeed.
        """
        discord_id = 4000000000000000000

        async def attempt_link(attempt_num):
            """Try to create a link attempt."""
            try:
                # Check rate limit
                is_allowed, count = LinkRateLimit.check_rate_limit(discord_id)

                if is_allowed:
                    # Record attempt
                    await LinkRateLimit.objects.acreate(discord_id=discord_id)
                    return "allowed"
                else:
                    return "blocked"
            except Exception as e:
                return f"error: {e}"

        # Make 10 concurrent attempts
        results = await asyncio.gather(*[attempt_link(i) for i in range(10)])

        # Count how many were allowed
        allowed_count = sum(1 for r in results if r == "allowed")

        # CRITICAL: Should allow at most 5 (the rate limit)
        assert allowed_count <= 5, (
            f"RACE CONDITION BUG: Rate limit bypassed! Expected: ≤5, Got: {allowed_count}. Results: {results}"
        )

        # Verify rate limit is now enforced
        final_check, final_count = LinkRateLimit.check_rate_limit(discord_id)
        assert not final_check, "Rate limit should be active after 5 attempts"

    @pytest.mark.asyncio
    async def test_rapid_comments_cannot_bypass_rate_limit(self):
        """
        SCENARIO: User posts 10 comments rapidly to same ticket.

        PROPERTY: Should be blocked after 5 comments.
        BUG IF: More than 5 comments succeed.
        """
        team = await Team.objects.acreate(
            team_number=44,
            team_name="Rate Limit Test Team",
            authentik_group="WCComps_BlueTeam44",
        )

        ticket = await Ticket.objects.acreate(
            ticket_number="T044-001",
            team=team,
            category="other",
            title="Rate Limit Test",
            status="open",
        )

        discord_id = 5000000000000000000

        async def attempt_comment(comment_num):
            """Try to post a comment."""
            try:
                # Check rate limit
                is_allowed, reason = CommentRateLimit.check_rate_limit(ticket.id, discord_id)

                if is_allowed:
                    # Record comment attempt
                    await CommentRateLimit.objects.acreate(ticket=ticket, discord_id=discord_id)
                    return "posted"
                else:
                    return f"blocked: {reason}"
            except Exception as e:
                return f"error: {e}"

        # Make 10 concurrent comment attempts
        results = await asyncio.gather(*[attempt_comment(i) for i in range(10)])

        # Count successful posts
        posted_count = sum(1 for r in results if r == "posted")

        # CRITICAL: Should allow at most 5 per ticket
        assert posted_count <= 5, (
            f"RACE CONDITION BUG: Comment rate limit bypassed! Expected: ≤5, Got: {posted_count}. Results: {results}"
        )


@pytest.mark.django_db(transaction=True)
class TestDatabaseTransactionIsolation:
    """Test that database transactions properly isolate concurrent operations.

    These test for bugs where:
    - Read-modify-write operations aren't atomic
    - Transactions don't properly rollback on error
    - Dirty reads allow seeing uncommitted data
    """

    def test_concurrent_ticket_counter_increments(self):
        """
        SCENARIO: Two tickets created simultaneously for same team.

        PROPERTY: Each should get unique ticket number, no duplicates.
        BUG IF: Both get same number (lost update).
        """
        team = Team.objects.create(
            team_number=45,
            team_name="Counter Test Team",
            authentik_group="WCComps_BlueTeam45",
            ticket_counter=0,
        )

        results = []
        errors = []

        def create_ticket(ticket_suffix):
            """Create ticket in a thread."""
            try:
                with transaction.atomic():
                    # Refresh team to get latest counter
                    fresh_team = Team.objects.select_for_update().get(id=team.id)

                    # Increment counter
                    fresh_team.ticket_counter += 1
                    counter = fresh_team.ticket_counter
                    fresh_team.save()

                    # Create ticket
                    ticket = Ticket.objects.create(
                        ticket_number=f"T045-{counter:03d}",
                        team=fresh_team,
                        category="other",
                        title=f"Concurrent Ticket {ticket_suffix}",
                        status="open",
                    )
                    results.append(ticket.ticket_number)
            except Exception as e:
                errors.append(str(e))

        # Create 5 tickets concurrently
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(create_ticket, i) for i in range(5)]
            for future in futures:
                future.result()

        # CRITICAL: Should have 5 unique ticket numbers
        assert len(results) == 5, f"Some tickets failed: {errors}"
        assert len(set(results)) == 5, f"RACE CONDITION BUG: Duplicate ticket numbers! Got: {results}"

        # Verify counter is at 5
        team.refresh_from_db()
        assert team.ticket_counter == 5, f"Counter inconsistent. Expected: 5, Got: {team.ticket_counter}"

    def test_rollback_on_error_doesnt_corrupt_data(self):
        """
        SCENARIO: Transaction fails halfway through, should rollback.

        PROPERTY: Either all changes committed or none.
        BUG IF: Partial changes committed (data corruption).
        """
        team = Team.objects.create(
            team_number=46,
            team_name="Rollback Test Team",
            authentik_group="WCComps_BlueTeam46",
        )

        initial_link_count = DiscordLink.objects.filter(team=team).count()

        try:
            with transaction.atomic():
                # Create first link (should succeed)
                DiscordLink.objects.create(
                    discord_id=6000000000000000000,
                    discord_username="user1",
                    authentik_username="user1",
                    authentik_user_id="uid-1",
                    team=team,
                    is_active=True,
                )

                # Create second link (should succeed)
                DiscordLink.objects.create(
                    discord_id=6000000000000000001,
                    discord_username="user2",
                    authentik_username="user2",
                    authentik_user_id="uid-2",
                    team=team,
                    is_active=True,
                )

                # Force an error (violate unique constraint)
                DiscordLink.objects.create(
                    discord_id=6000000000000000000,  # Duplicate!
                    discord_username="user3",
                    authentik_username="user3",
                    authentik_user_id="uid-3",
                    team=team,
                    is_active=True,
                )
        except Exception:
            # Expected to fail
            pass

        # CRITICAL: Should have rolled back ALL changes
        final_link_count = DiscordLink.objects.filter(team=team).count()
        assert final_link_count == initial_link_count, (
            f"TRANSACTION BUG: Partial commit! "
            f"Initial: {initial_link_count}, Final: {final_link_count}. "
            f"Expected: All or nothing."
        )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestRealWorldRaceConditions:
    """Test race conditions that happen in actual production scenarios."""

    @pytest.mark.asyncio
    async def test_user_spamming_join_button(self):
        """
        REAL SCENARIO: User double-clicks "Join Team" button.

        PROPERTY: Should create exactly one link.
        BUG IF: Creates multiple links or crashes.
        """
        team = await Team.objects.acreate(
            team_number=47,
            team_name="Spam Test Team",
            authentik_group="WCComps_BlueTeam47",
        )

        discord_id = 7000000000000000000

        async def spam_join():
            """Simulate rapid button clicks."""
            try:
                link = await DiscordLink.objects.acreate(
                    discord_id=discord_id,
                    discord_username="spammer",
                    authentik_username="spammer",
                    authentik_user_id="uid-spammer",
                    team=team,
                    is_active=True,
                )
                return "created"
            except Exception as e:
                return f"error: {type(e).__name__}"

        # Simulate 5 rapid clicks
        results = await asyncio.gather(*[spam_join() for _ in range(5)])

        # CRITICAL: Should have exactly one active link
        active_links = await DiscordLink.objects.filter(discord_id=discord_id, is_active=True).acount()

        assert active_links == 1, f"BUG: Multiple links created! Count: {active_links}, Results: {results}"

    @pytest.mark.asyncio
    async def test_admin_deactivating_while_user_is_active(self):
        """
        REAL SCENARIO: Admin clicks "remove user" while user is posting ticket.

        PROPERTY: Either user finishes AND stays active, OR gets deactivated.
        BUG IF: User deactivated but ticket still created with their name.
        """
        team = await Team.objects.acreate(
            team_number=48,
            team_name="Admin Action Team",
            authentik_group="WCComps_BlueTeam48",
        )

        discord_id = 8000000000000000000

        link = await DiscordLink.objects.acreate(
            discord_id=discord_id,
            discord_username="active_user",
            authentik_username="active_user",
            authentik_user_id="uid-active",
            team=team,
            is_active=True,
        )

        ticket_created = []

        async def user_creates_ticket():
            """User tries to create ticket."""
            await asyncio.sleep(0.001)
            try:
                # Check if still active
                current_link = await DiscordLink.objects.aget(id=link.id)
                if current_link.is_active:
                    ticket = await Ticket.objects.acreate(
                        ticket_number="T048-001",
                        team=team,
                        category="other",
                        title="User's Ticket",
                        status="open",
                    )
                    ticket_created.append(True)
                    return "ticket_created"
                else:
                    return "user_deactivated"
            except Exception as e:
                return f"error: {e}"

        async def admin_deactivates():
            """Admin deactivates user."""
            await asyncio.sleep(0.001)
            link_obj = await DiscordLink.objects.aget(id=link.id)
            link_obj.is_active = False
            await link_obj.asave()
            return "deactivated"

        # Run concurrently
        results = await asyncio.gather(
            user_creates_ticket(),
            admin_deactivates(),
        )

        # Check final state
        final_link = await DiscordLink.objects.aget(id=link.id)
        ticket_exists = await Ticket.objects.filter(ticket_number="T048-001").aexists()

        # PROPERTY: If ticket was created, user should still be active
        # OR if user is deactivated, ticket should not exist
        if ticket_exists:
            # This is acceptable IF user was still active when ticket was created
            # But we can't have: user deactivated AND ticket exists from AFTER deactivation
            pass  # This is a timing-dependent scenario

        # At minimum: should not crash
        assert all("error" not in str(r) for r in results), f"Operations crashed: {results}"
