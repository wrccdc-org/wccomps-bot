"""Team linking commands (/link, /team-info)."""

import discord
from discord import app_commands
from discord.ext import commands
import secrets
import logging
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from core.models import DiscordLink, LinkToken, LinkRateLimit

logger = logging.getLogger(__name__)


class LinkingCog(commands.Cog):
    """Commands for linking Discord accounts to teams."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="link", description="Link your Discord account to your WCComps team"
    )
    async def link_command(self, interaction: discord.Interaction) -> None:
        """Generate a link token for user authentication."""

        # Check rate limit (5 attempts per hour)
        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent_attempts = await LinkRateLimit.objects.filter(
            discord_id=interaction.user.id, attempted_at__gte=one_hour_ago
        ).acount()

        if recent_attempts >= 5:
            await interaction.response.send_message(
                f"Rate limit exceeded. You have made {recent_attempts} link attempts in the last hour. "
                f"Please wait before trying again (limit: 5 per hour).",
                ephemeral=True,
            )
            return

        # Record this attempt for rate limiting
        await LinkRateLimit.objects.acreate(discord_id=interaction.user.id)

        # Check if already linked
        existing_link = await (
            DiscordLink.objects.filter(discord_id=interaction.user.id, is_active=True)
            .select_related("team")
            .afirst()
        )

        if existing_link:
            # If linked but no team (orphaned link), deactivate it and proceed
            if not existing_link.team:
                logger.warning(
                    f"Found orphaned link for {interaction.user.id}, deactivating and allowing re-link"
                )
                existing_link.is_active = False
                existing_link.unlinked_at = timezone.now()
                await existing_link.asave()
                # Continue with normal link flow below
            else:
                # Normal case: linked to a team
                await interaction.response.send_message(
                    f"You are already linked to **{existing_link.team.team_name}**. "
                    f"If you need to change teams, please contact an administrator.",
                    ephemeral=True,
                )
                return

        # Generate unique token
        token = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timedelta(minutes=15)

        # Store token
        await LinkToken.objects.acreate(
            token=token,
            discord_id=interaction.user.id,
            discord_username=str(interaction.user),
            expires_at=expires_at,
        )

        # Generate auth URL
        base_url = settings.BASE_URL
        auth_url = f"{base_url}/auth/link?token={token}"

        embed = discord.Embed(
            title="🔗 Link Your Discord Account to Team",
            description=f"Click the link below to authenticate with your team credentials (team01-team50):\n\n"
            f"[Click here to link your account]({auth_url})\n\n"
            f"⏰ This link expires in 15 minutes\n"
            f"🔒 You'll be redirected to Authentik to log in\n"
            f"✅ After successful login, you'll automatically receive your team role\n\n"
            f"Need help? Contact a volunteer.",
            color=discord.Color.blue(),
        )
        embed.set_footer(text="Link expires in 15 minutes")

        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(
            f"Generated link token for {interaction.user} ({interaction.user.id})"
        )

    @app_commands.command(name="team-info", description="View your team information")
    async def team_info_command(self, interaction: discord.Interaction) -> None:
        """Display user's team information."""

        link = await (
            DiscordLink.objects.filter(discord_id=interaction.user.id, is_active=True)
            .select_related("team")
            .afirst()
        )

        if not link or not link.team:
            await interaction.response.send_message(
                "You are not currently linked to a team. Use `/link` to get started!",
                ephemeral=True,
            )
            return

        team = link.team

        # Get member count and list
        member_count = await team.members.filter(is_active=True).acount()

        # Fetch all members
        members = [
            m async for m in team.members.filter(is_active=True).order_by("linked_at")
        ]

        embed = discord.Embed(
            title=f"Team: {team.team_name}", color=discord.Color.green()
        )
        embed.add_field(name="Team Number", value=f"#{team.team_number}", inline=True)
        embed.add_field(
            name="Members", value=f"{member_count}/{team.max_members}", inline=True
        )
        embed.add_field(
            name="Authentik Account", value=link.authentik_username, inline=False
        )

        if members:
            # Build member list, respecting Discord's 1024 char field limit
            member_lines = [f"• {m.discord_username}" for m in members]

            member_list = ""
            shown_count = 0
            for line in member_lines:
                test_list = member_list + line + "\n"
                # Leave room for "... and N more" message
                if len(test_list) > 950:
                    break
                member_list = test_list
                shown_count += 1

            # Add overflow message if needed
            if shown_count < len(members):
                remaining = len(members) - shown_count
                member_list += f"... and {remaining} more"

            embed.add_field(
                name="Team Members", value=member_list.strip(), inline=False
            )

        embed.set_footer(
            text=f"Linked {discord.utils.format_dt(link.linked_at, style='R')}"
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    """Setup function to add cog to bot."""
    await bot.add_cog(LinkingCog(bot))
