"""Property-based tests using Hypothesis for Django models and business logic."""

import pytest
import uuid
from datetime import datetime, timedelta
from hypothesis import given, strategies as st, assume, settings
from hypothesis.extra.django import from_model, TestCase
from django.utils import timezone
from django.db import IntegrityError, transaction

from core.models import (
    Team,
    DiscordLink,
    LinkToken,
    LinkRateLimit,
    CommentRateLimit,
    CompetitionConfig,
    Ticket,
)


@pytest.mark.django_db(transaction=True)
class TestTeamProperties:
    """Property-based tests for Team model."""

    @given(
        max_members=st.integers(min_value=1, max_value=20),
        member_count=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=50)
    def test_team_is_full_property(
        self, max_members: int, member_count: int
    ):
        """Property: team.is_full() iff get_member_count() >= max_members."""
        # Use unique team_number for each test run
        team_number = hash(str(uuid.uuid4())) % 10000

        team = Team.objects.create(
            team_number=team_number,
            team_name=f"Team {team_number}",
            authentik_group=f"WCComps_BlueTeam{team_number}",
            max_members=max_members,
        )

        # Create the specified number of active members
        for i in range(member_count):
            DiscordLink.objects.create(
                discord_id=1000000000000000000 + team_number * 100 + i,
                discord_username=f"user{i}_{uuid.uuid4()}",
                authentik_username=f"user{i}_{uuid.uuid4()}",
                authentik_user_id=f"uid-{i}-{uuid.uuid4()}",
                team=team,
                is_active=True,
            )

        # Property: is_full() should be True iff member_count >= max_members
        assert team.is_full() == (member_count >= max_members)
        assert team.get_member_count() == member_count

    @given(
        max_members=st.integers(min_value=1, max_value=20),
    )
    @settings(max_examples=50)
    def test_member_count_never_negative(
        self, max_members: int
    ):
        """Property: get_member_count() is always >= 0."""
        # Use unique team_number for each test run
        team_number = hash(str(uuid.uuid4())) % 10000

        team = Team.objects.create(
            team_number=team_number,
            team_name=f"Team {team_number}",
            authentik_group=f"WCComps_BlueTeam{team_number}",
            max_members=max_members,
        )

        assert team.get_member_count() >= 0


@pytest.mark.django_db(transaction=True)
class TestDiscordLinkProperties:
    """Property-based tests for DiscordLink model."""

    @given(
        link_count=st.integers(min_value=2, max_value=5),
    )
    @settings(max_examples=30)
    def test_only_one_active_link_per_discord_id(
        self, link_count: int
    ):
        """Property: only one active DiscordLink per discord_id at any time."""
        # Use unique discord_id for each test run
        discord_id = hash(str(uuid.uuid4())) % 1000000000000000000 + 100000000000000000

        # Create multiple links for the same discord_id
        for i in range(link_count):
            DiscordLink.objects.create(
                discord_id=discord_id,
                discord_username=f"user_{i}_{uuid.uuid4()}",
                authentik_username=f"auth_user_{i}_{uuid.uuid4()}",
                authentik_user_id=f"uid-{i}-{uuid.uuid4()}",
                is_active=True,
            )

        # Property: should only have 1 active link
        active_links = DiscordLink.objects.filter(
            discord_id=discord_id, is_active=True
        ).count()
        assert active_links == 1

        # Property: total links created equals link_count
        total_links = DiscordLink.objects.filter(discord_id=discord_id).count()
        assert total_links == link_count


@pytest.mark.django_db(transaction=True)
class TestLinkTokenProperties:
    """Property-based tests for LinkToken model."""

    @given(
        hours_from_now=st.floats(min_value=-24, max_value=24, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_token_expiration_property(
        self, hours_from_now: float
    ):
        """Property: token.is_expired() iff current_time > expires_at."""
        discord_id = hash(str(uuid.uuid4())) % 1000000000000000000 + 100000000000000000
        expires_at = timezone.now() + timedelta(hours=hours_from_now)

        token = LinkToken.objects.create(
            token=str(uuid.uuid4()),
            discord_id=discord_id,
            discord_username=f"user_{uuid.uuid4()}",
            expires_at=expires_at,
        )

        # Property: is_expired() should match whether current time > expires_at
        expected_expired = timezone.now() > expires_at
        assert token.is_expired() == expected_expired


@pytest.mark.django_db(transaction=True)
class TestLinkRateLimitProperties:
    """Property-based tests for LinkRateLimit model."""

    @given(
        attempts=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=50)
    def test_rate_limit_property(self, attempts: int):
        """Property: rate limit allows iff attempts < 5 in last hour."""
        discord_id = hash(str(uuid.uuid4())) % 1000000000000000000 + 100000000000000000

        # Create attempts in the last hour
        for i in range(attempts):
            LinkRateLimit.objects.create(discord_id=discord_id)

        is_allowed, attempt_count = LinkRateLimit.check_rate_limit(discord_id)

        # Property: should be allowed iff attempts < 5
        assert is_allowed == (attempts < 5)
        assert attempt_count == attempts

    @given(
        recent_attempts=st.integers(min_value=0, max_value=10),
        old_attempts=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=50)
    def test_rate_limit_only_counts_recent_attempts(
        self, recent_attempts: int, old_attempts: int
    ):
        """Property: only attempts in last hour count toward rate limit."""
        discord_id = hash(str(uuid.uuid4())) % 1000000000000000000 + 100000000000000000
        now = timezone.now()
        two_hours_ago = now - timedelta(hours=2)

        # Create old attempts (should not count)
        for i in range(old_attempts):
            old_attempt = LinkRateLimit.objects.create(discord_id=discord_id)
            # Manually set the timestamp to 2 hours ago
            old_attempt.attempted_at = two_hours_ago
            old_attempt.save()

        # Create recent attempts (should count)
        for i in range(recent_attempts):
            LinkRateLimit.objects.create(discord_id=discord_id)

        is_allowed, attempt_count = LinkRateLimit.check_rate_limit(discord_id)

        # Property: only recent attempts count
        assert attempt_count == recent_attempts
        assert is_allowed == (recent_attempts < 5)


@pytest.mark.django_db(transaction=True)
class TestCommentRateLimitProperties:
    """Property-based tests for CommentRateLimit model."""

    @given(
        ticket_comments=st.integers(min_value=0, max_value=10),
        user_comments=st.integers(min_value=0, max_value=15),
    )
    @settings(max_examples=50)
    def test_comment_rate_limit_properties(
        self,
        ticket_comments: int,
        user_comments: int,
    ):
        """Property: rate limit enforces both per-ticket and per-user limits."""
        assume(ticket_comments <= user_comments)

        team_number = hash(str(uuid.uuid4())) % 10000
        discord_id = hash(str(uuid.uuid4())) % 1000000000000000000 + 100000000000000000

        # Create team and ticket
        team = Team.objects.create(
            team_number=team_number,
            team_name=f"Team {team_number}",
            authentik_group=f"WCComps_BlueTeam{team_number}",
        )

        ticket = Ticket.objects.create(
            ticket_number=f"T{team_number}-001-{uuid.uuid4()}",
            team=team,
            category="technical",
            title="Test ticket",
        )

        # Create comments for this ticket
        for i in range(ticket_comments):
            CommentRateLimit.objects.create(
                ticket=ticket, discord_id=discord_id
            )

        # Create comments for other tickets (to test user-level limit)
        for i in range(user_comments - ticket_comments):
            other_ticket = Ticket.objects.create(
                ticket_number=f"T{team_number}-{i+2:03d}-{uuid.uuid4()}",
                team=team,
                category="technical",
                title=f"Other ticket {i}",
            )
            CommentRateLimit.objects.create(
                ticket=other_ticket, discord_id=discord_id
            )

        is_allowed, reason = CommentRateLimit.check_rate_limit(ticket.id, discord_id)

        # Property: blocked if ticket_comments >= 5 OR user_comments >= 10
        if ticket_comments >= 5:
            assert not is_allowed
            assert "Ticket rate limit" in reason
        elif user_comments >= 10:
            assert not is_allowed
            assert "User rate limit" in reason
        else:
            assert is_allowed
            assert reason == ""


@pytest.mark.django_db(transaction=True)
class TestCompetitionConfigProperties:
    """Property-based tests for CompetitionConfig model."""

    @given(
        hours_from_now=st.floats(min_value=-24, max_value=24, allow_nan=False),
        currently_enabled=st.booleans(),
    )
    @settings(max_examples=50)
    def test_should_enable_applications_property(
        self, hours_from_now: float, currently_enabled: bool
    ):
        """Property: should_enable iff (now >= start_time AND not enabled)."""
        start_time = timezone.now() + timedelta(hours=hours_from_now)

        config = CompetitionConfig.objects.create(
            competition_start_time=start_time, applications_enabled=currently_enabled
        )

        should_enable = config.should_enable_applications()

        # Property: should enable iff time has passed AND not already enabled
        expected = (timezone.now() >= start_time) and not currently_enabled
        assert should_enable == expected

        config.delete()

    @given(currently_enabled=st.booleans())
    @settings(max_examples=20)
    def test_should_not_enable_without_start_time(
        self, currently_enabled: bool
    ):
        """Property: should never enable if no start_time is set."""
        config = CompetitionConfig.objects.create(
            competition_start_time=None, applications_enabled=currently_enabled
        )

        # Property: should never enable without a start time
        assert config.should_enable_applications() is False

        config.delete()


@pytest.mark.django_db(transaction=True)
class TestTeamTicketCounterProperties:
    """Property-based tests for Team ticket counter."""

    @given(
        initial_counter=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=30)
    def test_ticket_counter_never_negative(
        self, initial_counter: int
    ):
        """Property: ticket_counter is always >= 0."""
        team_number = hash(str(uuid.uuid4())) % 10000

        team = Team.objects.create(
            team_number=team_number,
            team_name=f"Team {team_number}",
            authentik_group=f"WCComps_BlueTeam{team_number}",
            ticket_counter=initial_counter,
        )

        assert team.ticket_counter >= 0
        assert team.ticket_counter == initial_counter
