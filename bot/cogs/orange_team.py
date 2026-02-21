"""Orange Team commands for scoring adjustments."""

import logging
from decimal import Decimal, InvalidOperation

import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands

from bot.permissions import check_orange_team
from team.models import DiscordLink

logger = logging.getLogger(__name__)


class OrangeTeamCog(commands.Cog):
    """Commands for Orange Team scoring adjustments."""

    orange_group = app_commands.Group(
        name="orange",
        description="Orange Team scoring adjustment commands",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @orange_group.command(
        name="submit",
        description="[ORANGE TEAM] Submit a scoring adjustment for a team",
    )
    @app_commands.describe(
        team_number="Team number to adjust (1-50)",
        points="Points to award (positive) or deduct (negative)",
        check_type="Type of check performed",
        description="Description of why points are adjusted",
    )
    @app_commands.check(check_orange_team)
    async def orange_submit(
        self,
        interaction: discord.Interaction,
        team_number: int,
        points: str,
        check_type: str,
        description: str,
    ) -> None:
        """Submit an orange team scoring adjustment."""
        from scoring.models import OrangeCheckType, OrangeTeamScore

        from team.models import Team

        # Validate team number
        if team_number < 1 or team_number > 50:
            await interaction.response.send_message(
                "Team number must be between 1 and 50.",
                ephemeral=True,
            )
            return

        # Validate points
        try:
            points_decimal = Decimal(points)
        except InvalidOperation:
            await interaction.response.send_message(
                "Invalid points value. Enter a number like 5, -10, or 2.5",
                ephemeral=True,
            )
            return

        # Find team
        team = await Team.objects.filter(team_number=team_number, is_active=True).afirst()
        if not team:
            await interaction.response.send_message(
                f"Team {team_number} not found or inactive.",
                ephemeral=True,
            )
            return

        # Find or create check type
        check_type_obj = await OrangeCheckType.objects.filter(name__iexact=check_type).afirst()
        if not check_type_obj:
            await interaction.response.send_message(
                f"Check type '{check_type}' not found. Use `/orange add-type` to create it first.",
                ephemeral=True,
            )
            return

        # Resolve Discord user to Django user for attribution
        discord_link = await (
            DiscordLink.objects.filter(discord_id=interaction.user.id, is_active=True).select_related("user").afirst()
        )
        submitted_by_user = discord_link.user if discord_link else None

        # Create adjustment
        bonus = await OrangeTeamScore.objects.acreate(
            team=team,
            submitted_by=submitted_by_user,
            check_type=check_type_obj,
            description=description,
            points_awarded=points_decimal,
            is_approved=False,
        )

        # Build response embed
        sign = "+" if points_decimal >= 0 else ""
        color = discord.Color.green() if points_decimal >= 0 else discord.Color.red()

        embed = discord.Embed(
            title="Orange Team Adjustment Submitted",
            color=color,
        )
        embed.add_field(name="ID", value=f"#{bonus.id}", inline=True)
        embed.add_field(name="Team", value=f"Team {team_number} - {team.team_name}", inline=True)
        embed.add_field(name="Points", value=f"{sign}{points_decimal}", inline=True)
        embed.add_field(name="Check Type", value=check_type, inline=True)
        embed.add_field(name="Status", value="Pending Approval", inline=True)
        embed.add_field(name="Description", value=description[:1024], inline=False)
        embed.set_footer(text="Gold Team must approve before points are applied.")

        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"Orange adjustment #{bonus.id} submitted by {interaction.user}")

    @orange_group.command(
        name="list",
        description="[ORANGE/GOLD TEAM] List pending orange team adjustments",
    )
    @app_commands.describe(
        status="Filter by status",
    )
    @app_commands.choices(
        status=[
            app_commands.Choice(name="Pending", value="pending"),
            app_commands.Choice(name="Approved", value="approved"),
            app_commands.Choice(name="All", value="all"),
        ]
    )
    @app_commands.check(check_orange_team)
    async def orange_list(
        self,
        interaction: discord.Interaction,
        status: str = "pending",
    ) -> None:
        """List orange team adjustments."""
        from scoring.models import OrangeTeamScore

        # Build query
        queryset = OrangeTeamScore.objects.select_related("team", "check_type").order_by("-created_at")
        if status == "pending":
            queryset = queryset.filter(is_approved=False)
        elif status == "approved":
            queryset = queryset.filter(is_approved=True)

        # Fetch adjustments
        adjustments: list[OrangeTeamScore] = await sync_to_async(lambda: list(queryset[:25]))()

        if not adjustments:
            await interaction.response.send_message(
                f"No {status} adjustments found.",
                ephemeral=True,
            )
            return

        # Build embed
        embed = discord.Embed(
            title=f"Orange Team Adjustments ({status.title()})",
            color=discord.Color.orange(),
        )

        for adj in adjustments[:10]:
            sign = "+" if adj.points_awarded >= 0 else ""
            status_emoji = "\u2705" if adj.is_approved else "\u23f3"
            check_name = adj.check_type.name if adj.check_type else "N/A"

            embed.add_field(
                name=f"{status_emoji} #{adj.id} - Team {adj.team.team_number}",
                value=f"**{sign}{adj.points_awarded}** pts | {check_name}\n{adj.description[:100]}",
                inline=False,
            )

        if len(adjustments) > 10:
            embed.set_footer(text=f"Showing 10 of {len(adjustments)} adjustments")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @orange_group.command(
        name="list-types",
        description="[ORANGE TEAM] List available check types",
    )
    @app_commands.check(check_orange_team)
    async def orange_list_types(self, interaction: discord.Interaction) -> None:
        """List available orange check types."""
        from scoring.models import OrangeCheckType

        check_types: list[OrangeCheckType] = await sync_to_async(
            lambda: list(OrangeCheckType.objects.all().order_by("name"))
        )()

        if not check_types:
            await interaction.response.send_message(
                "No check types defined yet. Use `/orange add-type` to create one.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Orange Check Types",
            color=discord.Color.orange(),
        )

        for ct in check_types:
            sign = "+" if ct.default_points >= 0 else ""
            embed.add_field(
                name=ct.name,
                value=f"Default: {sign}{ct.default_points} pts",
                inline=True,
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @orange_group.command(
        name="add-type",
        description="[ORANGE TEAM] Add a new check type",
    )
    @app_commands.describe(
        name="Name for the check type",
        default_points="Default points for this check type",
    )
    @app_commands.check(check_orange_team)
    async def orange_add_type(
        self,
        interaction: discord.Interaction,
        name: str,
        default_points: str,
    ) -> None:
        """Add a new orange check type."""
        from scoring.models import OrangeCheckType

        # Validate points
        try:
            points_decimal = Decimal(default_points)
        except InvalidOperation:
            await interaction.response.send_message(
                "Invalid points value. Enter a number like 5, -10, or 2.5",
                ephemeral=True,
            )
            return

        # Check if already exists
        existing = await OrangeCheckType.objects.filter(name__iexact=name).afirst()
        if existing:
            await interaction.response.send_message(
                f"Check type '{name}' already exists.",
                ephemeral=True,
            )
            return

        # Create
        check_type = await OrangeCheckType.objects.acreate(
            name=name,
            default_points=points_decimal,
        )

        sign = "+" if points_decimal >= 0 else ""
        await interaction.response.send_message(
            f"\u2705 Created check type **{check_type.name}** with default {sign}{points_decimal} pts",
            ephemeral=True,
        )
        logger.info(f"Orange check type '{name}' created by {interaction.user}")

    @orange_group.command(
        name="remove-type",
        description="[ORANGE TEAM] Remove a check type",
    )
    @app_commands.describe(
        name="Name of the check type to remove",
    )
    @app_commands.check(check_orange_team)
    async def orange_remove_type(
        self,
        interaction: discord.Interaction,
        name: str,
    ) -> None:
        """Remove an orange check type."""
        from scoring.models import OrangeCheckType

        # Find check type
        check_type = await OrangeCheckType.objects.filter(name__iexact=name).afirst()
        if not check_type:
            await interaction.response.send_message(
                f"Check type '{name}' not found.",
                ephemeral=True,
            )
            return

        # Delete
        deleted_name = check_type.name
        await check_type.adelete()

        await interaction.response.send_message(
            f"\u274c Removed check type **{deleted_name}**",
            ephemeral=True,
        )
        logger.info(f"Orange check type '{deleted_name}' removed by {interaction.user}")


async def setup(bot: commands.Bot) -> None:
    """Setup function to add cog to bot."""
    await bot.add_cog(OrangeTeamCog(bot))
