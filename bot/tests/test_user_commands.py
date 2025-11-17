"""Tests for user-facing slash commands."""

from typing import Any

import pytest

from bot.cogs.linking import LinkingCog


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestUserCommands:
    """Test user-facing commands."""

    async def test_team_info_without_link(self, mock_interaction: Any, mock_bot: Any, db: Any) -> None:
        cog = LinkingCog(mock_bot)
        await cog.team_info_command.callback(cog, mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "not linked" in call_args.args[0].lower() or "link" in call_args.args[0].lower()

    async def test_team_info_with_link(self, mock_interaction: Any, mock_team_user: Any, mock_bot: Any) -> None:
        mock_interaction.user.id = mock_team_user._discord_id

        cog = LinkingCog(mock_bot)
        await cog.team_info_command.callback(cog, mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "embed" in call_args.kwargs
        embed = call_args.kwargs["embed"]
        assert "Test Team" in embed.title or "Test Team" in str(embed.description)
