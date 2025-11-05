"""Tests for user-facing slash commands."""

from typing import Any
import pytest
from unittest.mock import patch
from bot.cogs.linking import LinkingCog
from core.models import LinkToken


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestUserCommands:
    """Test user-facing commands."""

    async def test_link_command_generates_token(
        self, mock_interaction: Any, mock_bot: Any, db: Any
    ) -> None:
        cog = LinkingCog(mock_bot)

        with patch("bot.cogs.linking.settings") as mock_settings:
            mock_settings.BASE_URL = "http://test.com"
            await cog.link_command.callback(cog, mock_interaction)

        # Verify response was sent
        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert call_args.kwargs.get("ephemeral") is True

        # Verify token was created
        token = await LinkToken.objects.filter(
            discord_id=mock_interaction.user.id
        ).afirst()
        assert token is not None

    async def test_team_info_without_link(
        self, mock_interaction: Any, mock_bot: Any, db: Any
    ) -> None:
        cog = LinkingCog(mock_bot)
        await cog.team_info_command.callback(cog, mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert (
            "not linked" in call_args.args[0].lower()
            or "link" in call_args.args[0].lower()
        )

    async def test_team_info_with_link(
        self, mock_interaction: Any, mock_team_user: Any, mock_bot: Any
    ) -> None:
        mock_interaction.user.id = mock_team_user._discord_id

        cog = LinkingCog(mock_bot)
        await cog.team_info_command.callback(cog, mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "embed" in call_args.kwargs
        embed = call_args.kwargs["embed"]
        assert "Test Team" in embed.title or "Test Team" in str(embed.description)
