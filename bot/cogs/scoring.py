"""Scoring commands for CCDC competitions."""

import logging

import discord
from discord import app_commands
from discord.ext import commands
from django.utils import timezone

from team.models import DiscordLink

logger = logging.getLogger(__name__)


class ScoringCog(commands.Cog):
    """Commands for scoring and incident reports."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="incident-report", description="[BLUE TEAM] Submit an incident report for detected red team activity"
    )
    @app_commands.describe(
        affected_box="Which box was affected (e.g., web-server, mail-server)",
        affected_service="Which service was attacked (e.g., HTTP, SSH, SMTP)",
        source_ip="Source IP address of the attack",
        attack_vector="Type of attack (e.g., SQL Injection, Brute Force)",
        description="Detailed description of what you detected and how you mitigated it",
    )
    async def incident_report(
        self,
        interaction: discord.Interaction,
        affected_box: str,
        affected_service: str,
        source_ip: str,
        attack_vector: str,
        description: str,
    ) -> None:
        """Submit an incident report for red team activity."""
        # Check if user is linked to a team
        link = await (
            DiscordLink.objects.filter(discord_id=interaction.user.id, is_active=True).select_related("team").afirst()
        )

        if not link or not link.team:
            await interaction.response.send_message(
                "**This command is for Blue Team competitors only.**\n\n"
                "You must be linked to a competition team to submit incident reports.\n"
                "Use `/link` to connect your Discord account to your team.",
                ephemeral=True,
            )
            return

        team = link.team

        # Import models here to avoid circular imports
        from scoring.models import IncidentReport

        # Validate inputs
        if not source_ip.strip():
            await interaction.response.send_message(
                "Source IP address is required. Please include the IP address from your evidence.",
                ephemeral=True,
            )
            return

        if len(description) < 50:
            await interaction.response.send_message(
                "Description too short. Please provide a detailed explanation (at least 50 characters) including:\n"
                "• How you detected the attack\n"
                "• Evidence you collected (timestamp, IP, logs)\n"
                "• Mitigation steps you took",
                ephemeral=True,
            )
            return

        # Create incident report
        try:
            incident = await IncidentReport.objects.acreate(
                team=team,
                affected_box=affected_box,
                affected_service=affected_service,
                source_ip=source_ip,
                destination_ip="",  # Will be filled in from web interface
                attack_description=f"{attack_vector}\n\n{description}",
                attack_detected_at=timezone.now(),  # Default to now
                submitted_by=None,  # Discord submissions don't have User objects
            )

            # Create success embed
            embed = discord.Embed(
                title="Incident Report Submitted",
                description="Your incident report has been submitted for gold team review.",
                color=discord.Color.blue(),
            )
            embed.add_field(name="Report ID", value=f"#{incident.id}", inline=True)
            embed.add_field(name="Team", value=team.team_name, inline=True)
            embed.add_field(name="Status", value="Pending Review", inline=True)
            embed.add_field(name="Affected Box", value=affected_box, inline=True)
            embed.add_field(name="Affected Service", value=affected_service, inline=True)
            embed.add_field(name="Source IP", value=f"`{source_ip}`", inline=True)
            embed.add_field(name="Attack Vector", value=attack_vector, inline=False)
            embed.add_field(name="Description", value=description[:1024], inline=False)

            # Add next steps
            embed.add_field(
                name="Upload Evidence",
                value=f"Visit the web interface to upload screenshots showing IP addresses and timestamps:\n"
                f"`/scoring/incident/{incident.id}/`",
                inline=False,
            )

            embed.set_footer(
                text="Gold team will review and match this to red team findings. Points may be returned if validated."
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(f"Incident report #{incident.id} created by {interaction.user} for team {team.team_name}")

        except Exception as e:
            logger.exception(f"Failed to create incident report: {e}")
            await interaction.response.send_message(
                "Failed to submit incident report. Please try again or contact staff if the problem persists.",
                ephemeral=True,
            )

    @app_commands.command(name="leaderboard", description="View the current leaderboard")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        """Display the current leaderboard."""
        # Import scoring calculator
        from asgiref.sync import sync_to_async
        from scoring.calculator import get_leaderboard

        # Get leaderboard (sync function, need to wrap)
        scores = await sync_to_async(get_leaderboard)()

        if not scores:
            await interaction.response.send_message(
                "No scores calculated yet. Scores will appear once scoring begins.",
                ephemeral=True,
            )
            return

        # Format leaderboard embed
        embed = discord.Embed(
            title="Leaderboard",
            description=f"Top {min(10, len(scores))} teams",
            color=discord.Color.gold(),
        )

        # Add top 10 teams
        for score in scores[:10]:
            team_info = (
                f"**Services:** {score.service_points:.2f} | "
                f"**Injects:** {score.inject_points:.2f}\n"
                f"**Orange:** +{score.orange_points:.2f} | "
                f"**Red:** {score.red_deductions:.2f} | "
                f"**Incidents:** +{score.incident_recovery_points:.2f}"
            )

            rank = score.rank or 0
            rank_display = f"#{rank}"

            embed.add_field(
                name=f"{rank_display} {score.team.team_name} - {score.total_score:.2f} pts",
                value=team_info,
                inline=False,
            )

        embed.set_footer(text=f"Last updated: {scores[0].calculated_at.strftime('%Y-%m-%d %H:%M:%S')}")

        await interaction.response.send_message(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
    """Setup function to add cog to bot."""
    await bot.add_cog(ScoringCog(bot))
