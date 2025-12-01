"""Inject grading commands for White/Gold Team."""

import logging
from decimal import Decimal, InvalidOperation

import discord
from asgiref.sync import sync_to_async
from discord import app_commands
from discord.ext import commands
from django.utils import timezone

from person.models import Person

logger = logging.getLogger(__name__)


class InjectGradingCog(commands.Cog):
    """Commands for grading inject submissions."""

    inject_group = app_commands.Group(
        name="inject",
        description="Inject grading commands",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _can_grade(self, person: Person) -> bool:
        """Check if person can grade injects (White or Gold Team)."""
        return person.is_white_team() or person.is_gold_team()

    @inject_group.command(
        name="list",
        description="[WHITE/GOLD TEAM] List available injects from Quotient",
    )
    async def inject_list(self, interaction: discord.Interaction) -> None:
        """List available injects."""
        from quotient.client import QuotientClient

        # Check permission
        person = await Person.objects.filter(discord_id=interaction.user.id).afirst()
        if not person or not self._can_grade(person):
            await interaction.response.send_message(
                "This command is for White/Gold Team members only.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        client = QuotientClient()
        injects = await sync_to_async(client.get_injects)()

        if not injects:
            await interaction.followup.send(
                "No injects available from Quotient, or Quotient is unavailable.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Available Injects",
            color=discord.Color.purple(),
        )

        for inject in injects[:15]:
            embed.add_field(
                name=f"#{inject.inject_id}: {inject.title}",
                value=f"Use `/inject grade {inject.inject_id} <team> <points>`",
                inline=False,
            )

        if len(injects) > 15:
            embed.set_footer(text=f"Showing 15 of {len(injects)} injects")

        await interaction.followup.send(embed=embed, ephemeral=True)

    @inject_group.command(
        name="grade",
        description="[WHITE/GOLD TEAM] Grade an inject for a team",
    )
    @app_commands.describe(
        inject_id="Inject ID from Quotient",
        team_number="Team number (1-50)",
        points="Points to award",
        notes="Optional grading notes",
    )
    async def inject_grade(
        self,
        interaction: discord.Interaction,
        inject_id: str,
        team_number: int,
        points: str,
        notes: str = "",
    ) -> None:
        """Grade an inject for a team."""
        from quotient.client import QuotientClient
        from scoring.models import InjectGrade

        from team.models import Team

        # Check permission
        person = await Person.objects.filter(discord_id=interaction.user.id).afirst()
        if not person or not self._can_grade(person):
            await interaction.response.send_message(
                "This command is for White/Gold Team members only.",
                ephemeral=True,
            )
            return

        # Validate team
        if team_number < 1 or team_number > 50:
            await interaction.response.send_message(
                "Team number must be between 1 and 50.",
                ephemeral=True,
            )
            return

        # Validate points
        try:
            points_decimal = Decimal(points)
            if points_decimal < 0:
                await interaction.response.send_message(
                    "Points cannot be negative.",
                    ephemeral=True,
                )
                return
        except InvalidOperation:
            await interaction.response.send_message(
                "Invalid points value. Enter a number like 100, 75.5, etc.",
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

        await interaction.response.defer(ephemeral=True)

        # Get inject name from Quotient
        client = QuotientClient()
        injects = await sync_to_async(client.get_injects)()
        inject_obj = next((i for i in (injects or []) if str(i.inject_id) == inject_id), None)
        inject_name = inject_obj.title if inject_obj else f"Inject {inject_id}"

        # Create or update grade
        grade, created = await InjectGrade.objects.aupdate_or_create(
            team=team,
            inject_id=inject_id,
            defaults={
                "inject_name": inject_name,
                "points_awarded": points_decimal,
                "notes": notes,
                "graded_at": timezone.now(),
                "is_approved": False,
            },
        )

        action = "Created" if created else "Updated"
        embed = discord.Embed(
            title=f"Inject Grade {action}",
            color=discord.Color.green() if created else discord.Color.blue(),
        )
        embed.add_field(name="Inject", value=inject_name, inline=True)
        embed.add_field(name="Team", value=f"Team {team_number} - {team.team_name}", inline=True)
        embed.add_field(name="Points", value=str(points_decimal), inline=True)
        embed.add_field(name="Status", value="Pending Approval", inline=True)
        if notes:
            embed.add_field(name="Notes", value=notes[:1024], inline=False)

        embed.set_footer(text="Gold Team must approve before grade is finalized.")

        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(f"Inject grade for {inject_name} team {team_number} set by {interaction.user}")

    @inject_group.command(
        name="list-grades",
        description="[WHITE/GOLD TEAM] List grades for an inject",
    )
    @app_commands.describe(
        inject_id="Inject ID to view grades for (leave empty for all pending)",
        status="Filter by approval status",
    )
    @app_commands.choices(
        status=[
            app_commands.Choice(name="Pending", value="pending"),
            app_commands.Choice(name="Approved", value="approved"),
            app_commands.Choice(name="All", value="all"),
        ]
    )
    async def inject_list_grades(
        self,
        interaction: discord.Interaction,
        inject_id: str | None = None,
        status: str = "pending",
    ) -> None:
        """List inject grades."""
        from scoring.models import InjectGrade

        # Check permission
        person = await Person.objects.filter(discord_id=interaction.user.id).afirst()
        if not person or not self._can_grade(person):
            await interaction.response.send_message(
                "This command is for White/Gold Team members only.",
                ephemeral=True,
            )
            return

        # Build query
        queryset = InjectGrade.objects.select_related("team").order_by("inject_name", "team__team_number")

        if inject_id:
            queryset = queryset.filter(inject_id=inject_id)

        if status == "pending":
            queryset = queryset.filter(is_approved=False)
        elif status == "approved":
            queryset = queryset.filter(is_approved=True)

        grades: list[InjectGrade] = await sync_to_async(lambda: list(queryset[:50]))()

        if not grades:
            await interaction.response.send_message(
                f"No {status} grades found" + (f" for inject {inject_id}" if inject_id else "") + ".",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="Inject Grades" + (f" - {grades[0].inject_name}" if inject_id and grades else ""),
            color=discord.Color.purple(),
        )

        # Group by inject
        current_inject = None
        field_value = ""

        for grade in grades[:25]:
            if current_inject != grade.inject_name:
                if current_inject and field_value:
                    embed.add_field(name=current_inject, value=field_value[:1024], inline=False)
                current_inject = grade.inject_name
                field_value = ""

            status_emoji = "\u2705" if grade.is_approved else "\u23f3"
            field_value += f"{status_emoji} Team {grade.team.team_number}: **{grade.points_awarded}** pts\n"

        if current_inject and field_value:
            embed.add_field(name=current_inject, value=field_value[:1024], inline=False)

        if len(grades) > 25:
            embed.set_footer(text=f"Showing 25 of {len(grades)} grades")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Setup function to add cog to bot."""
    await bot.add_cog(InjectGradingCog(bot))
