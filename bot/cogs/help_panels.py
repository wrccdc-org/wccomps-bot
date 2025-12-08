"""Help panels cog - persistent button panels for blue teams."""

import logging
from collections.abc import Awaitable, Callable
from typing import cast

import discord
from discord.ext import commands
from django.conf import settings

from core.tickets_config import TICKET_CATEGORIES
from team.models import DiscordLink

logger = logging.getLogger(__name__)


class ServiceScoringModal(discord.ui.Modal, title="Service Scoring Validation"):
    """Modal for service scoring validation tickets."""

    service_name: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Service Name",
        placeholder="e.g., HTTP, DNS, SSH",
        required=True,
        max_length=100,
    )

    description: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Description (optional)",
        placeholder="Additional details about the issue",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
        self.category_id = "service-scoring-validation"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle ticket creation from modal."""
        await self._create_ticket(
            interaction,
            service_name=self.service_name.value,
            description=self.description.value,
        )

    async def _create_ticket(
        self,
        interaction: discord.Interaction,
        service_name: str = "",
        description: str = "",
        hostname: str = "",
        ip_address: str = "",
    ) -> None:
        """Common ticket creation logic."""
        await interaction.response.defer(ephemeral=True)

        # Check if user is linked to a team
        link = await (
            DiscordLink.objects.filter(discord_id=interaction.user.id, is_active=True).select_related("team").afirst()
        )

        if not link or not link.team:
            await interaction.followup.send(
                "You must be linked to a competition team to create tickets.\n"
                "Click the **🔗 Link Account** button first.",
                ephemeral=True,
            )
            return

        try:
            cat_info = TICKET_CATEGORIES[self.category_id]

            # Create ticket using shared atomic function
            from ticketing.utils import acreate_ticket_atomic

            ticket = await acreate_ticket_atomic(
                team=link.team,
                category=self.category_id,
                title=cat_info["display_name"],
                description=description,
                hostname=hostname,
                ip_address=ip_address,
                service_name=service_name,
                actor_username=f"discord:{interaction.user.name}",
            )

            # Queue Discord thread creation
            from core.models import DiscordTask

            await DiscordTask.objects.acreate(
                task_type="ticket_created_web",
                payload={"ticket_id": ticket.id},
            )

            await interaction.followup.send(
                f"✅ Ticket **{ticket.ticket_number}** created!\n"
                f"Category: **{cat_info['display_name']}**\n"
                f"Points: **{cat_info.get('points', 0)}**\n\n"
                f"A volunteer will respond shortly.",
                ephemeral=True,
            )

        except Exception as e:
            logger.error(f"Failed to create ticket: {e}", exc_info=True)
            await interaction.followup.send(f"Failed to create ticket: {e!s}", ephemeral=True)


class BoxResetModal(discord.ui.Modal, title="Box Reset / Scrub"):
    """Modal for box reset tickets."""

    hostname: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Hostname",
        placeholder="e.g., web01, dc01",
        required=True,
        max_length=255,
    )

    ip_address: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="IP Address",
        placeholder="e.g., 10.0.1.50",
        required=True,
        max_length=50,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
        self.category_id = "box-reset"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle ticket creation from modal."""
        modal = ServiceScoringModal(self.bot)
        modal.category_id = self.category_id
        await modal._create_ticket(
            interaction,
            hostname=self.hostname.value,
            ip_address=self.ip_address.value,
        )


class ScoringServiceCheckModal(discord.ui.Modal, title="Scoring Service Check"):
    """Modal for scoring service check tickets."""

    service_name: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Service Name",
        placeholder="e.g., HTTP, DNS, SSH",
        required=True,
        max_length=100,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
        self.category_id = "scoring-service-check"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle ticket creation from modal."""
        modal = ServiceScoringModal(self.bot)
        modal.category_id = self.category_id
        await modal._create_ticket(
            interaction,
            service_name=self.service_name.value,
        )


class ConsultationModal(discord.ui.Modal, title="Consultation Request"):
    """Modal for consultation tickets."""

    description: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Description",
        placeholder="Describe what you need help with",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000,
    )

    hostname: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Hostname (hands-on only)",
        placeholder="Leave blank for phone consultation",
        required=False,
        max_length=255,
    )

    def __init__(self, bot: commands.Bot, category_id: str):
        super().__init__()
        self.bot = bot
        self.category_id = category_id
        if category_id == "blackteam-phone-consultation":
            self.title = "Black Team Phone Consultation"
            self.remove_item(self.hostname)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle ticket creation from modal."""
        modal = ServiceScoringModal(self.bot)
        modal.category_id = self.category_id
        await modal._create_ticket(
            interaction,
            description=self.description.value,
            hostname=self.hostname.value if self.category_id == "blackteam-handson-consultation" else "",
        )


class OtherModal(discord.ui.Modal, title="Other / General Issue"):
    """Modal for other/general tickets."""

    description: discord.ui.TextInput[discord.ui.Modal] = discord.ui.TextInput(
        label="Description",
        placeholder="Describe your issue or request",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot
        self.category_id = "other"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle ticket creation from modal."""
        modal = ServiceScoringModal(self.bot)
        modal.category_id = self.category_id
        await modal._create_ticket(
            interaction,
            description=self.description.value,
        )


class CategorySelect(discord.ui.Select["TicketCategoryView"]):
    """Select menu for choosing ticket category."""

    def __init__(self) -> None:
        options = []
        for cat_id, cat_info in TICKET_CATEGORIES.items():
            if cat_info.get("user_creatable", True):
                points = cat_info.get("points", 0)
                options.append(
                    discord.SelectOption(
                        label=cat_info["display_name"],
                        value=cat_id,
                        description=f"{points} points",
                    )
                )

        super().__init__(
            placeholder="Select a ticket category...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle category selection."""
        category_id = self.values[0]
        bot = cast(TicketCategoryView, self.view).bot

        # Show appropriate modal based on category
        modal: ServiceScoringModal | BoxResetModal | ScoringServiceCheckModal | ConsultationModal | OtherModal
        if category_id == "service-scoring-validation":
            modal = ServiceScoringModal(bot)
        elif category_id == "box-reset":
            modal = BoxResetModal(bot)
        elif category_id == "scoring-service-check":
            modal = ScoringServiceCheckModal(bot)
        elif category_id in [
            "blackteam-phone-consultation",
            "blackteam-handson-consultation",
        ]:
            modal = ConsultationModal(bot, category_id)
        else:  # other
            modal = OtherModal(bot)

        await interaction.response.send_modal(modal)


class TicketCategoryView(discord.ui.View):
    """View for selecting ticket category."""

    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=300)  # 5 minute timeout
        self.bot = bot
        self.add_item(CategorySelect())


class LinkButton(discord.ui.Button["TeamHelpView"]):
    """Button for linking account."""

    def __init__(self) -> None:
        super().__init__(
            style=discord.ButtonStyle.primary,
            label="🔗 Link Account",
            custom_id="help_panel:link",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle link account button click."""
        if not self.view:
            raise RuntimeError("Button callback invoked without view")
        await self.view.link_account(interaction)


class TicketButton(discord.ui.Button["TeamHelpView"]):
    """Button for creating ticket."""

    def __init__(self) -> None:
        super().__init__(
            style=discord.ButtonStyle.success,
            label="🎫 Create Ticket",
            custom_id="help_panel:ticket",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Handle create ticket button click."""
        if not self.view:
            raise RuntimeError("Button callback invoked without view")
        await self.view.create_ticket(interaction)


class TeamHelpView(discord.ui.View):
    """Persistent view with help buttons for blue teams."""

    def __init__(self, bot: commands.Bot, show_link: bool = True, show_ticket: bool = True):
        super().__init__(timeout=None)
        self.bot = bot

        # Add link button if requested
        if show_link:
            self.add_item(LinkButton())

        # Add ticket button if requested
        if show_ticket:
            self.add_item(TicketButton())

    async def link_account(self, interaction: discord.Interaction) -> None:
        """Handle link account button click."""
        # Import here to avoid circular dependency
        from bot.cogs.linking import LinkingCog

        cog = self.bot.get_cog("LinkingCog")
        if not isinstance(cog, LinkingCog):
            await interaction.response.send_message("Linking system is not available.", ephemeral=True)
            return

        # Call the link command logic
        callback = cast(
            Callable[[LinkingCog, discord.Interaction], Awaitable[None]],
            cog.link_command.callback,
        )
        await callback(cog, interaction)

    async def create_ticket(self, interaction: discord.Interaction) -> None:
        """Handle create ticket button click - show category selection."""
        view = TicketCategoryView(self.bot)
        await interaction.response.send_message(
            "Select a ticket category:",
            view=view,
            ephemeral=True,
        )


class HelpPanelsCog(commands.Cog):
    """Manages persistent help panels for blue teams."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        """Called when cog is loaded - set up persistent views."""
        # Register persistent views
        self.bot.add_view(TeamHelpView(self.bot, show_link=True, show_ticket=False))
        self.bot.add_view(TeamHelpView(self.bot, show_link=False, show_ticket=True))
        self.bot.add_view(TeamHelpView(self.bot, show_link=True, show_ticket=True))

        logger.info("Help panel views registered")

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Post help panels to configured channels on bot startup."""
        try:
            # Post link panel to link channel (hidden after linking)
            link_channel_id = getattr(settings, "DISCORD_LINK_CHANNEL_ID", None)
            if link_channel_id:
                await self._post_link_panel(link_channel_id)

            # Post ticket panel to welcome-rules (always visible)
            welcome_channel_id = getattr(settings, "DISCORD_WELCOME_CHANNEL_ID", None)
            if welcome_channel_id:
                await self._post_ticket_panel(welcome_channel_id)

        except Exception as e:
            logger.error(f"Failed to post help panels: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Delete messages posted to #link channel and trigger link flow."""
        # Ignore bot's own messages
        if message.author.bot:
            return

        # Check if message is in link channel
        link_channel_id = getattr(settings, "DISCORD_LINK_CHANNEL_ID", None)
        if link_channel_id and message.channel.id == link_channel_id:
            try:
                await message.delete()
                logger.info(f"Deleted message from {message.author} in #link channel")
            except discord.HTTPException as e:
                logger.exception(f"Failed to delete message in #link: {e}")
                return

            # Trigger link flow via DM
            from bot.cogs.linking import LinkingCog

            cog = self.bot.get_cog("LinkingCog")
            if isinstance(cog, LinkingCog):
                await cog.send_link_dm(message.author)

    async def _post_link_panel(self, channel_id: int) -> None:
        """Post the link account panel to a channel."""
        channel = self.bot.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            logger.warning(f"Link channel {channel_id} not found or not a text channel")
            return

        embed = discord.Embed(
            title="🔗 Link Your Discord Account",
            description=(
                "**Welcome to WRCCDC Competition!**\n\n"
                "Before you can participate, you need to link your Discord account to your Authentik account.\n\n"
                "**Click the button below to get started:**"
            ),
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="What happens when I link?",
            value=(
                "• You'll be redirected to Authentik to authenticate\n"
                "• Your Discord account will be linked to your team\n"
                "• You'll automatically get your team role\n"
                "• You'll gain access to your team channels"
            ),
            inline=False,
        )

        view = TeamHelpView(self.bot, show_link=True, show_ticket=False)

        # Check if we already posted a panel (look for bot's recent messages)
        async for message in channel.history(limit=10):
            if message.author == self.bot.user and message.embeds and message.embeds[0].title == embed.title:
                # Update existing message
                await message.edit(embed=embed, view=view)
                logger.info(f"Updated link panel in channel {channel_id}")
                return

        # Post new message
        await channel.send(embed=embed, view=view)
        logger.info(f"Posted link panel to channel {channel_id}")

    async def _post_ticket_panel(self, channel_id: int) -> None:
        """Post the ticket creation panel to a channel."""
        channel = self.bot.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            logger.warning(f"Ticket channel {channel_id} not found or not a text channel")
            return

        # Build category list
        categories_text = []
        for cat_info in TICKET_CATEGORIES.values():
            if cat_info.get("user_creatable", True):
                points = cat_info.get("points", 0)
                categories_text.append(f"• **{cat_info['display_name']}** - {points}pt")

        embed = discord.Embed(
            title="🎫 Need Help?",
            description=(
                "**Create a support ticket and our volunteers will assist you!**\n\n"
                "Click the button below to create a ticket. A volunteer will respond shortly.\n\n"
                "**Available Categories:**\n" + "\n".join(categories_text)
            ),
            color=discord.Color.green(),
        )

        view = TeamHelpView(self.bot, show_link=False, show_ticket=True)

        # Check if we already posted a panel
        async for message in channel.history(limit=10):
            if message.author == self.bot.user and message.embeds and message.embeds[0].title == embed.title:
                # Update existing message
                await message.edit(embed=embed, view=view)
                logger.info(f"Updated ticket panel in channel {channel_id}")
                return

        # Post new message
        await channel.send(embed=embed, view=view)
        logger.info(f"Posted ticket panel to channel {channel_id}")

    async def post_team_ticket_panel(self, team_channel_id: int) -> None:
        """Post ticket panel to a team's channel (called when team is created)."""
        await self._post_ticket_panel(team_channel_id)


async def setup(bot: commands.Bot) -> None:
    """Setup function to add cog to bot."""
    await bot.add_cog(HelpPanelsCog(bot))
