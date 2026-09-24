import asyncio
import discord
from discord.ext import commands

class ConfirmCloseView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot

    @discord.ui.button(label="Yes, Close Thread", style=discord.ButtonStyle.danger, custom_id="confirm_close_yes")
    async def confirm_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        message = interaction.message
        message.content = "-close"
        message.author = interaction.user
        
        ctx = await self.bot.get_context(message)
        if ctx.command:
            await self.bot.invoke(ctx)
        else:
            await interaction.followup.send("Failed to execute close command.", ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="confirm_close_no")
    async def confirm_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Thread closure cancelled.", ephemeral=True)


class StickyPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    async def _invoke_alias(self, interaction: discord.Interaction, alias_name: str):
        thread = await self.bot.threads.find(channel=interaction.channel)
        if not thread:
            return await interaction.response.send_message("This is not an active Modmail thread.", ephemeral=True)

        await interaction.response.defer()

        # Build a message object formatted as if the staff member typed '-<alias_name>'
        message = interaction.message
        message.content = f"-{alias_name}"
        message.author = interaction.user

        ctx = await self.bot.get_context(message)

        # 1. Check if it's a registered native command or alias
        if ctx.command:
            await self.bot.invoke(ctx)
            return

        # 2. Check MongoDB snippets dynamically if it's not a core command
        snippets_cog = self.bot.get_cog("Snippets")
        if snippets_cog:
            # Look up snippet in MongoDB via Modmail's Snippet Manager
            snippet = await snippets_cog.get_snippet(alias_name)
            if snippet:
                # Execute the snippet in thread context (sends reply to user)
                await snippets_cog.send_snippet(ctx, snippet)
                return

        # 3. Fallback: process raw message command dispatch via bot process
        await self.bot.process_commands(message)

    @discord.ui.button(label="Greeting", style=discord.ButtonStyle.primary, custom_id="sticky_greeting", emoji="👋", row=0)
    async def greeting_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._invoke_alias(interaction, "greeting")

    @discord.ui.button(label="No Reply", style=discord.ButtonStyle.primary, custom_id="sticky_noreply", emoji="⏰", row=0)
    async def noreply_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._invoke_alias(interaction, "noreply")

    @discord.ui.button(label="Warn", style=discord.ButtonStyle.danger, custom_id="sticky_warn", emoji="⚠️", row=0)
    async def warn_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._invoke_alias(interaction, "warn")

    @discord.ui.button(label="Delay", style=discord.ButtonStyle.secondary, custom_id="sticky_delay", emoji="⏳", row=1)
    async def delay_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._invoke_alias(interaction, "delay")

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="sticky_close", emoji="❌", row=1)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        thread = await self.bot.threads.find(channel=interaction.channel)
        if not thread:
            return await interaction.response.send_message("This is not an active Modmail thread.", ephemeral=True)

        view = ConfirmCloseView(self.bot)
        await interaction.response.send_message(
            "⚠️ **Are you sure you want to close this ticket thread?**", 
            view=view, 
            ephemeral=True
        )


class StickyPanel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sticky_messages = {}

    def build_panel_embed(self):
        embed = discord.Embed(
            title="⚡ Ticket Control Panel",
            description="Select an action below to manage this ticket.",
            color=discord.Color.blurple()
        )
        return embed

    async def resend_sticky(self, channel):
        if not isinstance(channel, discord.TextChannel):
            return

        await asyncio.sleep(2)

        old_msg_id = self.sticky_messages.get(channel.id)
        if old_msg_id:
            try:
                old_msg = await channel.fetch_message(old_msg_id)
                await old_msg.delete()
            except Exception:
                pass

        try:
            view = StickyPanelView(self.bot)
            new_msg = await channel.send(embed=self.build_panel_embed(), view=view)
            self.sticky_messages[channel.id] = new_msg.id
        except (discord.NotFound, discord.HTTPException):
            self.sticky_messages.pop(channel.id, None)

    @commands.Cog.listener()
    async def on_thread_ready(self, thread, account, issue, logs):
        if hasattr(thread, "channel") and thread.channel:
            await self.resend_sticky(thread.channel)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if message.guild:
            thread = await self.bot.threads.find(channel=message.channel)
            if thread:
                await self.resend_sticky(message.channel)


async def setup(bot):
    await bot.add_cog(StickyPanel(bot))
