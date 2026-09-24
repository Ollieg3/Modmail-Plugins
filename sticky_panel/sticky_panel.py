import discord
from discord.ext import commands

class StickyPanelView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Claim Thread", style=discord.ButtonStyle.success, custom_id="sticky_claim", emoji="🔒")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        thread = self.bot.threads.find(channel_id=interaction.channel_id)
        if not thread:
            return await interaction.response.send_message("This is not an active Modmail thread.", ephemeral=True)
        
        await interaction.response.send_message(f"🔒 **Thread claimed by {interaction.user.mention}.**")

    @discord.ui.button(label="Close Thread", style=discord.ButtonStyle.danger, custom_id="sticky_close", emoji="❌")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        thread = self.bot.threads.find(channel_id=interaction.channel_id)
        if not thread:
            return await interaction.response.send_message("This is not an active Modmail thread.", ephemeral=True)

        await interaction.response.send_message("Closing thread...", ephemeral=True)
        cmd = self.bot.get_command("close")
        ctx = await self.bot.get_context(interaction.message)
        ctx.author = interaction.user
        await ctx.invoke(cmd)

    @discord.ui.button(label="User Info", style=discord.ButtonStyle.secondary, custom_id="sticky_info", emoji="👤")
    async def info_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        thread = self.bot.threads.find(channel_id=interaction.channel_id)
        if thread and getattr(thread, "recipient", None):
            user = thread.recipient
            embed = discord.Embed(
                title=f"User Info: {user.name}", 
                color=discord.Color.blue()
            )
            embed.add_field(name="Account ID", value=f"`{user.id}`", inline=True)
            embed.add_field(name="Account Created", value=f"<t:{int(user.created_at.timestamp())}:R>", inline=True)
            embed.set_thumbnail(url=user.display_avatar.url)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        
        await interaction.response.send_message("Could not fetch user details.", ephemeral=True)


class StickyPanel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sticky_messages = {}

    def build_panel_embed(self):
        embed = discord.Embed(
            title="⚡ Ticket Staff Control Panel",
            description="Quick actions for managing this ticket. This panel sticks to the bottom of the channel.",
            color=discord.Color.blurple()
        )
        return embed

    async def resend_sticky(self, channel):
        old_msg_id = self.sticky_messages.get(channel.id)
        if old_msg_id:
            try:
                old_msg = await channel.fetch_message(old_msg_id)
                await old_msg.delete()
            except Exception:
                pass

        view = StickyPanelView(self.bot)
        new_msg = await channel.send(embed=self.build_panel_embed(), view=view)
        self.sticky_messages[channel.id] = new_msg.id

    @commands.Cog.listener()
    async def on_thread_ready(self, thread, account, issue, logs):
        """Sends the panel when a thread is first opened."""
        await self.resend_sticky(thread.channel)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Re-sends the panel whenever a new message arrives in the thread."""
        if message.author.bot:
            return

        # Fixed: using self.bot.threads.find(channel_id=...) instead of .get()
        thread = self.bot.threads.find(channel_id=message.channel.id)
        if thread:
            await self.resend_sticky(message.channel)


async def setup(bot):
    await bot.add_cog(StickyPanel(bot))
