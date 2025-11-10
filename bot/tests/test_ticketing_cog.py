"""Tests for ticketing cog commands and listeners."""

from unittest.mock import AsyncMock, Mock
import discord
import pytest
from datetime import timedelta
from django.utils import timezone

from team.models import Team, DiscordLink
from ticketing.models import Ticket, TicketHistory, TicketComment
from bot.cogs.ticketing import TicketingCog


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestTicketingCog:
    """Test TicketingCog class."""

    @pytest.fixture
    async def bot(self) -> AsyncMock:
        """Create mock bot instance."""
        bot = AsyncMock(spec=discord.Client)
        bot.wait_until_ready = AsyncMock()
        bot.get_channel = Mock(return_value=None)
        return bot

    @pytest.fixture
    async def cog(self, bot: AsyncMock) -> TicketingCog:
        """Create TicketingCog instance."""
        cog = TicketingCog(bot)
        # Stop the background task to avoid test interference
        cog.archive_threads_task.cancel()
        return cog

    @pytest.fixture
    async def team(self) -> Team:
        """Create test team."""
        return await Team.objects.acreate(
            team_number=42,
            team_name="Test Team",
            authentik_group="WCComps_BlueTeam42",
            discord_category_id=1234567890,
            max_members=5,
        )

    @pytest.fixture
    async def discord_link(self, team: Team) -> DiscordLink:
        """Create test Discord link."""
        return await DiscordLink.objects.acreate(
            team=team,
            discord_id=999888777,
            discord_username="testuser#1234",
            authentik_username="testuser",
            is_active=True,
        )

    async def test_cog_initialization(self, bot: AsyncMock) -> None:
        """Test cog initializes and starts background task."""
        cog = TicketingCog(bot)
        assert cog.bot == bot
        # Task should be created
        assert hasattr(cog, "archive_threads_task")
        # Clean up
        cog.archive_threads_task.cancel()

    async def test_archive_threads_task_archives_expired_tickets(
        self, cog: TicketingCog, team: Team
    ) -> None:
        """Test background task archives tickets after grace period."""
        # Create ticket with thread scheduled for archiving in the past
        ticket = await Ticket.objects.acreate(
            ticket_number="T042-001",
            team=team,
            category="box-reset",
            title="Test Ticket",
            description="Test",
            status="resolved",
            discord_thread_id=1111222333,
            thread_archive_scheduled_at=timezone.now() - timedelta(seconds=120),
        )

        # Mock thread
        mock_thread = AsyncMock(spec=discord.Thread)
        mock_thread.edit = AsyncMock()
        cog.bot.get_channel = Mock(return_value=mock_thread)

        # Run the task once
        await cog.archive_threads_task()

        # Verify thread was archived
        mock_thread.edit.assert_called_once()
        call_kwargs = mock_thread.edit.call_args[1]
        assert call_kwargs["archived"] is True
        assert call_kwargs["locked"] is True

        # Verify database updated
        await ticket.arefresh_from_db()
        assert ticket.thread_archive_scheduled_at is None

        # Verify history entry created
        history_exists = await TicketHistory.objects.filter(
            ticket=ticket, action="thread_archived"
        ).aexists()
        assert history_exists

    async def test_archive_threads_task_skips_future_scheduled(
        self, cog: TicketingCog, team: Team
    ) -> None:
        """Test background task skips tickets scheduled for future."""
        ticket = await Ticket.objects.acreate(
            ticket_number="T042-002",
            team=team,
            category="service-check",
            title="Future Archive",
            description="Test",
            status="resolved",
            discord_thread_id=2222333444,
            thread_archive_scheduled_at=timezone.now() + timedelta(minutes=5),
        )

        mock_thread = AsyncMock(spec=discord.Thread)
        cog.bot.get_channel = Mock(return_value=mock_thread)

        await cog.archive_threads_task()

        # Thread should not be archived
        mock_thread.edit.assert_not_called()

        # Database should be unchanged
        await ticket.arefresh_from_db()
        assert ticket.thread_archive_scheduled_at is not None

    async def test_archive_threads_task_handles_missing_thread(
        self, cog: TicketingCog, team: Team
    ) -> None:
        """Test background task handles thread not found."""
        ticket = await Ticket.objects.acreate(
            ticket_number="T042-003",
            team=team,
            category="service-check",
            title="Missing Thread",
            description="Test",
            status="resolved",
            discord_thread_id=3333444555,
            thread_archive_scheduled_at=timezone.now() - timedelta(seconds=120),
        )

        # Thread not found
        cog.bot.get_channel = Mock(return_value=None)

        await cog.archive_threads_task()

        # Scheduled time should be cleared
        await ticket.arefresh_from_db()
        assert ticket.thread_archive_scheduled_at is None

    async def test_on_message_ignores_bot_messages(self, cog: TicketingCog) -> None:
        """Test on_message ignores messages from bots."""
        message = AsyncMock(spec=discord.Message)
        message.author = Mock()
        message.author.bot = True
        message.channel = Mock(spec=discord.Thread)

        initial_count = await TicketComment.objects.acount()
        await cog.on_message(message)

        # No comment should be created
        assert await TicketComment.objects.acount() == initial_count

    async def test_on_message_ignores_non_thread(self, cog: TicketingCog) -> None:
        """Test on_message ignores messages not in threads."""
        message = AsyncMock(spec=discord.Message)
        message.author = Mock()
        message.author.bot = False
        message.channel = Mock(spec=discord.TextChannel)  # Not a thread

        initial_count = await TicketComment.objects.acount()
        await cog.on_message(message)

        # No comment should be created
        assert await TicketComment.objects.acount() == initial_count

    async def test_on_message_edit_ignores_bot_messages(
        self, cog: TicketingCog
    ) -> None:
        """Test on_message_edit ignores bot message edits."""
        before = Mock()
        after = AsyncMock(spec=discord.Message)
        after.author = Mock()
        after.author.bot = True

        await cog.on_message_edit(before, after)
        # Should complete without error

    async def test_on_message_edit_updates_comment(
        self, cog: TicketingCog, team: Team
    ) -> None:
        """Test on_message_edit updates existing TicketComment."""
        ticket = await Ticket.objects.acreate(
            ticket_number="T042-007",
            team=team,
            category="service-check",
            title="Test Edit",
            description="Test",
            status="claimed",
            discord_thread_id=5555666777,
        )

        # Create existing comment
        comment = await TicketComment.objects.acreate(
            ticket=ticket,
            author_name="testuser",
            comment_text="Original text",
            discord_message_id=8888999000,
        )

        # Mock edited message
        before = Mock()
        after = AsyncMock(spec=discord.Message)
        after.author = Mock()
        after.author.bot = False
        after.content = "Edited text"
        after.id = comment.discord_message_id
        after.channel = Mock(spec=discord.Thread)
        after.channel.id = ticket.discord_thread_id

        await cog.on_message_edit(before, after)

        # Verify comment updated
        await comment.arefresh_from_db()
        assert comment.comment_text == "Edited text"

    async def test_on_message_delete_ignores_bot_messages(
        self, cog: TicketingCog
    ) -> None:
        """Test on_message_delete ignores bot message deletes."""
        message = AsyncMock(spec=discord.Message)
        message.author = Mock()
        message.author.bot = True

        await cog.on_message_delete(message)
        # Should complete without error

    async def test_on_message_delete_marks_comment_deleted(
        self, cog: TicketingCog, team: Team
    ) -> None:
        """Test on_message_delete soft-deletes TicketComment."""
        ticket = await Ticket.objects.acreate(
            ticket_number="T042-008",
            team=team,
            category="service-check",
            title="Test Delete",
            description="Test",
            status="claimed",
            discord_thread_id=6666777888,
        )

        # Create comment
        comment = await TicketComment.objects.acreate(
            ticket=ticket,
            author_name="testuser",
            comment_text="Will be deleted",
            discord_message_id=9999000111,
        )

        # Mock deleted message
        message = AsyncMock(spec=discord.Message)
        message.author = Mock()
        message.author.bot = False
        message.id = comment.discord_message_id
        message.channel = Mock(spec=discord.Thread)
        message.channel.id = ticket.discord_thread_id

        await cog.on_message_delete(message)

        # Verify comment marked as deleted
        await comment.arefresh_from_db()
        assert comment.comment_text == "[Message deleted]"

    async def test_archive_threads_task_multiple_tickets(
        self, cog: TicketingCog, team: Team
    ) -> None:
        """Test archiving multiple tickets with mixed expiration times."""
        # Create 5 tickets - 3 expired, 2 not expired
        tickets = []
        for i in range(5):
            if i < 3:
                scheduled_at = timezone.now() - timedelta(seconds=120)
            else:
                scheduled_at = timezone.now() + timedelta(minutes=5)

            ticket = await Ticket.objects.acreate(
                ticket_number=f"T042-{200 + i}",
                team=team,
                category="service-check",
                title=f"Test {i}",
                description="Test",
                status="resolved",
                discord_thread_id=2000000 + i,
                thread_archive_scheduled_at=scheduled_at,
            )
            tickets.append(ticket)

        # Mock threads
        mock_threads = {}
        for ticket in tickets:
            mock_thread = AsyncMock(spec=discord.Thread)
            mock_thread.edit = AsyncMock()
            mock_threads[ticket.discord_thread_id] = mock_thread

        cog.bot.get_channel = lambda tid: mock_threads.get(tid)

        await cog.archive_threads_task()

        # Verify only expired tickets were archived (first 3)
        for i in range(3):
            mock_threads[tickets[i].discord_thread_id].edit.assert_called_once()

        # Verify unexpired tickets were not archived (last 2)
        for i in range(3, 5):
            mock_threads[tickets[i].discord_thread_id].edit.assert_not_called()

    async def test_on_message_creates_comment(
        self, cog: TicketingCog, team: Team
    ) -> None:
        """Test on_message creates TicketComment for Discord messages."""
        ticket = await Ticket.objects.acreate(
            ticket_number="T042-100",
            team=team,
            category="service-check",
            title="Test Comment Sync",
            description="Test",
            status="open",
            discord_thread_id=7777888999,
        )

        # Mock Discord message
        message = AsyncMock(spec=discord.Message)
        message.author = Mock()
        message.author.bot = False
        message.author.id = 123456789
        message.author.__str__ = Mock(return_value="testuser#1234")
        message.id = 999888777666
        message.content = "This is a test message"
        message.channel = Mock(spec=discord.Thread)
        message.channel.id = ticket.discord_thread_id
        message.attachments = []

        initial_count = await TicketComment.objects.acount()
        await cog.on_message(message)

        # Verify comment created
        assert await TicketComment.objects.acount() == initial_count + 1

        # Verify comment has correct data
        comment = await TicketComment.objects.filter(
            discord_message_id=message.id
        ).afirst()
        assert comment is not None
        assert comment.ticket_id == ticket.id
        assert comment.author_name == "testuser#1234"
        assert comment.author_discord_id == 123456789
        assert comment.comment_text == "This is a test message"
        assert comment.discord_message_id == 999888777666

    async def test_on_message_prevents_duplicate_comments(
        self, cog: TicketingCog, team: Team
    ) -> None:
        """Test on_message doesn't create duplicate comments."""
        ticket = await Ticket.objects.acreate(
            ticket_number="T042-101",
            team=team,
            category="service-check",
            title="Test Duplicate",
            description="Test",
            status="open",
            discord_thread_id=8888999111,
        )

        # Create existing comment
        await TicketComment.objects.acreate(
            ticket=ticket,
            author_name="testuser",
            author_discord_id=123456789,
            comment_text="Original",
            discord_message_id=111222333444,
        )

        # Mock Discord message with same ID
        message = AsyncMock(spec=discord.Message)
        message.author = Mock()
        message.author.bot = False
        message.author.id = 123456789
        message.author.__str__ = Mock(return_value="testuser#1234")
        message.id = 111222333444  # Same as existing
        message.content = "Duplicate attempt"
        message.channel = Mock(spec=discord.Thread)
        message.channel.id = ticket.discord_thread_id
        message.attachments = []

        initial_count = await TicketComment.objects.acount()
        await cog.on_message(message)

        # Should not create duplicate
        assert await TicketComment.objects.acount() == initial_count

    async def test_on_message_ignores_empty_content(
        self, cog: TicketingCog, team: Team
    ) -> None:
        """Test on_message ignores messages with no text content."""
        ticket = await Ticket.objects.acreate(
            ticket_number="T042-102",
            team=team,
            category="service-check",
            title="Test Empty",
            description="Test",
            status="open",
            discord_thread_id=9999000222,
        )

        # Mock Discord message with empty content
        message = AsyncMock(spec=discord.Message)
        message.author = Mock()
        message.author.bot = False
        message.author.id = 123456789
        message.content = ""  # Empty content
        message.channel = Mock(spec=discord.Thread)
        message.channel.id = ticket.discord_thread_id
        message.attachments = []

        initial_count = await TicketComment.objects.acount()
        await cog.on_message(message)

        # Should not create comment for empty message
        assert await TicketComment.objects.acount() == initial_count

    async def test_on_message_for_nonexistent_ticket(self, cog: TicketingCog) -> None:
        """Test on_message handles messages in threads with no ticket."""
        # Mock Discord message in thread that doesn't have a ticket
        message = AsyncMock(spec=discord.Message)
        message.author = Mock()
        message.author.bot = False
        message.author.id = 123456789
        message.author.__str__ = Mock(return_value="testuser#1234")
        message.id = 555444333222
        message.content = "This thread has no ticket"
        message.channel = Mock(spec=discord.Thread)
        message.channel.id = 111111111111  # Non-existent thread
        message.attachments = []

        initial_count = await TicketComment.objects.acount()
        await cog.on_message(message)

        # Should not create comment for non-ticket thread
        assert await TicketComment.objects.acount() == initial_count
