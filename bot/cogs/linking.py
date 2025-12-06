"""Team linking commands (/link)."""

import logging
import secrets
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands
from django.conf import settings
from django.utils import timezone

from team.models import DiscordLink, LinkRateLimit, LinkToken

logger = logging.getLogger(__name__)


class LinkingCog(commands.Cog):
    """Commands for linking Discord accounts to teams."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="link", description="Link your Discord account to your WCComps team")
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
            DiscordLink.objects.filter(discord_id=interaction.user.id, is_active=True).select_related("team").afirst()
        )

        if existing_link:
            # If linked but no team (orphaned link), deactivate it and proceed
            if not existing_link.team:
                logger.warning(f"Found orphaned link for {interaction.user.id}, deactivating and allowing re-link")
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
            title="Link Your Discord Account",
            description=(
                f"Click the link below to authenticate with your team credentials (team01-team50):\n\n"
                f"[Click here to link your account]({auth_url})\n\n"
                f"This link expires in 15 minutes.\n"
                f"You will be redirected to Authentik to log in.\n"
                f"After successful login, you will receive your team role."
            ),
            color=discord.Color.blue(),
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"Generated link token for {interaction.user} ({interaction.user.id})")

    async def send_link_dm(self, user: discord.User | discord.Member) -> bool:
        """Send link instructions via DM. Returns True if sent successfully."""
        # Check rate limit
        one_hour_ago = timezone.now() - timedelta(hours=1)
        recent_attempts = await LinkRateLimit.objects.filter(
            discord_id=user.id, attempted_at__gte=one_hour_ago
        ).acount()

        if recent_attempts >= 5:
            logger.info(f"Rate limit exceeded for {user.id}, skipping DM")
            return False

        await LinkRateLimit.objects.acreate(discord_id=user.id)

        # Check if already linked
        existing_link = await (
            DiscordLink.objects.filter(discord_id=user.id, is_active=True).select_related("team").afirst()
        )

        if existing_link and existing_link.team:
            try:
                await user.send(
                    f"You are already linked to **{existing_link.team.team_name}**. "
                    f"If you need to change teams, please contact an administrator."
                )
            except discord.Forbidden:
                logger.warning(f"Cannot DM {user.id} - DMs disabled")
            return False

        # Deactivate orphaned link if exists
        if existing_link and not existing_link.team:
            existing_link.is_active = False
            existing_link.unlinked_at = timezone.now()
            await existing_link.asave()

        # Generate token
        token = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timedelta(minutes=15)

        await LinkToken.objects.acreate(
            token=token,
            discord_id=user.id,
            discord_username=str(user),
            expires_at=expires_at,
        )

        base_url = settings.BASE_URL
        auth_url = f"{base_url}/auth/link?token={token}"

        embed = discord.Embed(
            title="Link Your Discord Account",
            description=(
                f"Click the link below to authenticate with your team credentials (team01-team50):\n\n"
                f"[Click here to link your account]({auth_url})\n\n"
                f"This link expires in 15 minutes.\n"
                f"You will be redirected to Authentik to log in.\n"
                f"After successful login, you will receive your team role."
            ),
            color=discord.Color.blue(),
        )

        try:
            await user.send(embed=embed)
            logger.info(f"Sent link DM to {user} ({user.id})")
            return True
        except discord.Forbidden:
            logger.warning(f"Cannot DM {user.id} - DMs disabled")
            return False


async def setup(bot: commands.Bot) -> None:
    """Setup function to add cog to bot."""
    await bot.add_cog(LinkingCog(bot))
