from typing import Any
import pytest
from bot.discord_manager import DiscordManager
from core.models import Team


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestEndCompetition:
    async def test_end_competition_workflow_removes_team_roles(
        self, mock_discord_guild: Any, db: Any
    ) -> None:
        await Team.objects.acreate(
            team_number=1,
            team_name="BlueTeam01",
            max_members=5,
            discord_role_id=5001,
            discord_category_id=6001,
        )
        await Team.objects.acreate(
            team_number=2,
            team_name="BlueTeam02",
            max_members=5,
            discord_role_id=5002,
            discord_category_id=6002,
        )

        manager = DiscordManager(mock_discord_guild)
        removed_count = await manager.remove_all_team_roles()
        await Team.objects.all().aupdate(discord_category_id=None, discord_role_id=None)

        assert removed_count == 2

        member1 = mock_discord_guild.get_role(5001).members[0]
        member2 = mock_discord_guild.get_role(5002).members[0]

        assert member1.remove_roles.called
        assert member2.remove_roles.called

        first_call_args = member1.remove_roles.call_args_list[0][0]
        role_names = [role.name for role in first_call_args]
        assert "Team 01" in role_names
        assert "Blueteam" in role_names
