import asyncio
import json
import os
import discord
from discord.ext import commands

CONFIG_PATH = "sticky_panel_config.json"

DEFAULT_CONFIG = {
    "enabled": False,  # Disabled by default
    "delay": 1.5,
    "title": "⚡ Ticket Control Panel",
    "description": "Select an action below to manage this ticket.",
    "color": 0x5865F2,  # Blurple
    "categories": []    # None by default
}

def load_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_CONFIG

def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)


class CategorySelect(discord.ui.Select):
    def __init__(self, bot, categories):
        self.bot = bot
        options = []
        for cat in categories:
            options.append(discord.SelectOption(
                label=cat.get("label", "Unknown"),
                value=cat.get("value", "General"),
                description=cat.get("description", None),
                emoji=cat.get("emoji", None)
            ))
        
        super().__init__(
            placeholder="📁 Move thread to category...",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        thread = await self.bot.threads.find(channel=interaction.channel)
        if not thread:
            return await interaction.response.send_message("This is not an active Modmail thread.", ephemeral=True)

        selected_category = self.values[0]
        await interaction.response.send_message(f"⌛ Moving thread to `{selected_category}`...", ephemeral=True)

        message = interaction.message
        message.content = f"-move {selected_category}"
        message.author = interaction.user

        ctx = await self.bot.get_context(message)
        if ctx.command:
            await self.bot.invoke(ctx)
        else:
            await self.bot.process_commands(message)


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
    def __init__(self, bot, config):
        super().__init__(timeout=None)
        self.bot = bot

        # Only add dropdown if categories exist
        if config.get("categories"):
            self.add_item(CategorySelect(self.bot, config["categories"]))

    async def _invoke_alias(self, interaction: discord.Interaction, alias_name: str):
        thread = await self.bot.threads.find(channel=interaction.channel)
        if not thread:
            return await interaction.response.send_message("This is not an active Modmail thread.", ephemeral=True)

        await interaction.response.send_message(f"⌛ Executing `-{alias_name}`...", ephemeral=True)

        message = interaction.message
        message.content = f"-{alias_name}"
        message.author = interaction.user

        ctx = await self.bot.get_context(message)

        if ctx.command:
            await self.bot.invoke(ctx)
            return

        snippets_cog = self.bot.get_cog("Snippets")
        if snippets_cog:
            snippet = await snippets_cog.get_snippet(alias_name)
            if snippet:
                await snippets_cog.send_snippet(ctx, snippet)
                return

        await self.bot.process_commands(message)

    # --- BUTTON ROW 1 ---
    @discord.ui.button(label="Greeting", style=discord.ButtonStyle.primary, custom_id="sticky_greeting", emoji="👋", row=1)
    async def greeting_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._invoke_alias(interaction, "greeting")

    @discord.ui.button(label="No Reply", style=discord.ButtonStyle.secondary, custom_id="sticky_noreply", emoji="⏰", row=1)
    async def noreply_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._invoke_alias(interaction, "noreply")

    @discord.ui.button(label="Warn", style=discord.ButtonStyle.danger, custom_id="sticky_warn", emoji="⚠️", row=1)
    async def warn_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._invoke_alias(interaction, "warn")

    # --- BUTTON ROW 2 ---
    @discord.ui.button(label="Delay", style=discord.ButtonStyle.primary, custom_id="sticky_delay", emoji="⏳", row=2)
    async def delay_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._invoke_alias(interaction, "delay")

    @discord.ui.button(label="Close Thread", style=discord.ButtonStyle.danger, custom_id="sticky_close", emoji="❌", row=2)
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
        self.config = load_config()
        self.sticky_messages = {}
        self.locks = {}

    def get_lock(self, channel_id):
        if channel_id not in self.locks:
            self.locks[channel_id] = asyncio.Lock()
        return self.locks[channel_id]

    def build_panel_embed(self):
        embed = discord.Embed(
            title=self.config.get("title", "⚡ Ticket Control Panel"),
            description=self.config.get("description", "Select an action below to manage this ticket."),
            color=self.config.get("color", 0x5865F2)
        )
        embed.set_footer(text="Support Centre Panel")
        return embed

    async def resend_sticky(self, channel):
        if not self.config.get("enabled", False):
            return

        if not isinstance(channel, discord.TextChannel):
            return

        lock = self.get_lock(channel.id)
        
        async with lock:
            await asyncio.sleep(self.config.get("delay", 1.5))

            # Delete old sticky message
            old_msg_id = self.sticky_messages.get(channel.id)
            if old_msg_id:
                try:
                    old_msg = await channel.fetch_message(old_msg_id)
                    await old_msg.delete()
                except Exception:
                    pass

            # Send new sticky message
            try:
                view = StickyPanelView(self.bot, self.config)
                new_msg = await channel.send(embed=self.build_panel_embed(), view=view)
                self.sticky_messages[channel.id] = new_msg.id
            except (discord.NotFound, discord.HTTPException):
                self.sticky_messages.pop(channel.id, None)

    # --- CONFIG COMMAND GROUP ---
    @commands.group(name="stickypanel", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def stickypanel_cmd(self, ctx):
        """Shows sticky panel configuration settings."""
        embed = discord.Embed(title="⚙️ Sticky Panel Settings", color=discord.Color.blue())
        embed.add_field(name="Status", value="🟢 Enabled" if self.config.get("enabled") else "🔴 Disabled", inline=True)
        embed.add_field(name="Delay", value=f"`{self.config.get('delay')}s`", inline=True)
        embed.add_field(name="Title", value=self.config.get("title"), inline=False)
        
        cats = self.config.get("categories", [])
        cats_text = "\n".join([f"• {c['label']} -> `{c['value']}`" for c in cats]) if cats else "*None configured*"
        embed.add_field(name="Categories", value=cats_text, inline=False)
        
        embed.set_footer(text="Use -stickypanel enable | addcategory | removecategory")
        await ctx.send(embed=embed)

    @stickypanel_cmd.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def enable_panel(self, ctx):
        """Enables the sticky panel plugin."""
        self.config["enabled"] = True
        save_config(self.config)
        await ctx.send("✅ **Sticky Panel enabled!** It will now trigger when the bot sends messages in thread channels.")

    @stickypanel_cmd.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def disable_panel(self, ctx):
        """Disables the sticky panel plugin."""
        self.config["enabled"] = False
        save_config(self.config)
        await ctx.send("🛑 **Sticky Panel disabled.**")

    @stickypanel_cmd.command(name="addcategory")
    @commands.has_permissions(administrator=True)
    async def add_category(self, ctx, label: str, value: str, emoji: str = None):
        """Adds a dropdown category: -stickypanel addcategory "Management" "Management" "🛠️" """
        self.config["categories"].append({
            "label": label,
            "value": value,
            "description": f"Move to {label}",
            "emoji": emoji
        })
        save_config(self.config)
        await ctx.send(f"✅ Added category **{label}** (`{value}`) to dropdown.")

    @stickypanel_cmd.command(name="removecategory")
    @commands.has_permissions(administrator=True)
    async def remove_category(self, ctx, label: str):
        """Removes a category by label: -stickypanel removecategory "Management" """
        initial_count = len(self.config["categories"])
        self.config["categories"] = [c for c in self.config["categories"] if c["label"].lower() != label.lower()]
        
        if len(self.config["categories"]) < initial_count:
            save_config(self.config)
            await ctx.send(f"✅ Removed category **{label}** from dropdown.")
        else:
            await ctx.send(f"❌ Category **{label}** was not found.")

    @stickypanel_cmd.command(name="clearcategories")
    @commands.has_permissions(administrator=True)
    async def clear_categories(self, ctx):
        """Clears all movement categories."""
        self.config["categories"] = []
        save_config(self.config)
        await ctx.send("✅ Cleared all categories from sticky panel dropdown.")

    # --- LISTENERS ---
    @commands.Cog.listener()
    async def on_thread_ready(self, thread, account, issue, logs):
        if hasattr(thread, "channel") and thread.channel:
            await self.resend_sticky(thread.channel)

    @commands.Cog.listener()
    async def on_message(self, message):
        # 1. MUST BE SENT BY THE BOT
        if message.author != self.bot.user:
            return

        # 2. DO NOT RE-TRIGGER ON THE PANEL EMBED ITSELF
        if message.embeds and message.embeds[0].title == self.config.get("title"):
            return

        # 3. MUST BE IN A GUILD & INSIDE AN ACTIVE MODMAIL THREAD
        if message.guild:
            thread = await self.bot.threads.find(channel=message.channel)
            if thread:
                await self.resend_sticky(message.channel)


async def setup(bot):
    await bot.add_cog(StickyPanel(bot))
