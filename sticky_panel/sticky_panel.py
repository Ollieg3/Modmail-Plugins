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
    "categories": [],   # Empty by default
    "buttons": []       # Empty by default (Close button always renders last)
}

STYLE_MAP = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
    "blurple": discord.ButtonStyle.primary,
    "grey": discord.ButtonStyle.secondary,
    "gray": discord.ButtonStyle.secondary,
    "green": discord.ButtonStyle.success,
    "red": discord.ButtonStyle.danger,
}

# --- SAFE JSON HANDLING ---
def load_config():
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("buttons", [])
            data.setdefault("categories", [])
            data.setdefault("enabled", False)
            data.setdefault("delay", 1.5)
            data.setdefault("title", "⚡ Ticket Control Panel")
            return data
    except Exception as e:
        print(f"[StickyPanel] Config load failed ({e}). Reverting to default in-memory config.")
        return DEFAULT_CONFIG

def save_config(config):
    # Atomic write to prevent file corruption if interrupted
    tmp_path = f"{CONFIG_PATH}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        os.replace(tmp_path, CONFIG_PATH)
    except Exception as e:
        print(f"[StickyPanel] Error saving config: {e}")


# --- DYNAMIC BUTTON ---
class DynamicButton(discord.ui.Button):
    def __init__(self, label: str, alias: str, style: str, emoji: str = None, row: int = 1):
        btn_style = STYLE_MAP.get(style.lower(), discord.ButtonStyle.primary)
        super().__init__(
            label=label,
            style=btn_style,
            emoji=emoji if emoji else None,
            row=row
        )
        self.alias = alias

    async def callback(self, interaction: discord.Interaction):
        try:
            thread = await self.view.bot.threads.find(channel=interaction.channel)
            if not thread:
                return await interaction.response.send_message("This is not an active Modmail thread.", ephemeral=True)

            await interaction.response.send_message(f"⌛ Executing `-{self.alias}`...", ephemeral=True)

            message = interaction.message
            message.content = f"-{self.alias}"
            message.author = interaction.user

            ctx = await self.view.bot.get_context(message)

            if ctx.command:
                await self.view.bot.invoke(ctx)
                return

            snippets_cog = self.view.bot.get_cog("Snippets")
            if snippets_cog:
                snippet = await snippets_cog.get_snippet(self.alias)
                if snippet:
                    await snippets_cog.send_snippet(ctx, snippet)
                    return

            await self.view.bot.process_commands(message)
        except Exception as e:
            print(f"[StickyPanel] Error executing button action '{self.alias}': {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Failed to execute command `-{self.alias}`.", ephemeral=True)


# --- CATEGORY DROPDOWN ---
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
        try:
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
        except Exception as e:
            print(f"[StickyPanel] Category move error: {e}")


# --- CLOSE CONFIRMATION VIEW ---
class ConfirmCloseView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=60)
        self.bot = bot

    @discord.ui.button(label="Yes, Close Thread", style=discord.ButtonStyle.danger, custom_id="confirm_close_yes")
    async def confirm_yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer()
            message = interaction.message
            message.content = "-close"
            message.author = interaction.user
            
            ctx = await self.bot.get_context(message)
            if ctx.command:
                await self.bot.invoke(ctx)
            else:
                await interaction.followup.send("Failed to execute close command.", ephemeral=True)
        except Exception as e:
            print(f"[StickyPanel] Close execution error: {e}")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="confirm_close_no")
    async def confirm_no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Thread closure cancelled.", ephemeral=True)


# --- MAIN PANEL VIEW ---
class StickyPanelView(discord.ui.View):
    def __init__(self, bot, config):
        super().__init__(timeout=None)
        self.bot = bot

        # 1. Add Category Dropdown (Row 0)
        if config.get("categories"):
            try:
                self.add_item(CategorySelect(self.bot, config["categories"]))
            except Exception as e:
                print(f"[StickyPanel] Skipped invalid categories: {e}")

        # 2. Add Dynamic Action Buttons
        configured_buttons = config.get("buttons", [])
        max_row_used = 1

        for btn in configured_buttons:
            try:
                btn_row = min(max(btn.get("row", 1), 1), 4) # Bound row between 1 and 4
                if btn_row > max_row_used:
                    max_row_used = btn_row
                    
                self.add_item(DynamicButton(
                    label=btn["label"],
                    alias=btn["alias"],
                    style=btn.get("style", "primary"),
                    emoji=btn.get("emoji"),
                    row=btn_row
                ))
            except Exception as e:
                print(f"[StickyPanel] Skipped invalid button '{btn.get('label')}': {e}")

        # 3. Permanent Close Thread Button (Always rendered last)
        close_row = max_row_used if len([b for b in configured_buttons if b.get("row", 1) == max_row_used]) < 5 else min(max_row_used + 1, 4)
        
        close_btn = discord.ui.Button(
            label="Close Thread", 
            style=discord.ButtonStyle.danger, 
            emoji="❌", 
            row=close_row
        )
        close_btn.callback = self.close_callback
        self.add_item(close_btn)

    async def close_callback(self, interaction: discord.Interaction):
        try:
            thread = await self.bot.threads.find(channel=interaction.channel)
            if not thread:
                return await interaction.response.send_message("This is not an active Modmail thread.", ephemeral=True)

            view = ConfirmCloseView(self.bot)
            await interaction.response.send_message(
                "⚠️ **Are you sure you want to close this ticket thread?**", 
                view=view, 
                ephemeral=True
            )
        except Exception as e:
            print(f"[StickyPanel] Error initiating thread closure: {e}")


# --- COG & LISTENERS ---
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
            # Wait configured delay to reduce API noise
            await asyncio.sleep(self.config.get("delay", 1.5))

            # Delete old sticky message
            old_msg_id = self.sticky_messages.get(channel.id)
            if old_msg_id:
                try:
                    old_msg = await channel.fetch_message(old_msg_id)
                    await old_msg.delete()
                except (discord.NotFound, discord.HTTPException, discord.Forbidden):
                    pass

            # Send new sticky message safely
            try:
                view = StickyPanelView(self.bot, self.config)
                new_msg = await channel.send(embed=self.build_panel_embed(), view=view)
                self.sticky_messages[channel.id] = new_msg.id
            except discord.HTTPException as e:
                print(f"[StickyPanel] Failed to send panel in {channel.id}: {e}")
                self.sticky_messages.pop(channel.id, None)

    # --- COMMANDS ---
    @commands.group(name="stickypanel", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def stickypanel_cmd(self, ctx):
        """Displays sticky panel settings."""
        embed = discord.Embed(title="⚙️ Sticky Panel Settings", color=discord.Color.blue())
        embed.add_field(name="Status", value="🟢 Enabled" if self.config.get("enabled") else "🔴 Disabled", inline=True)
        embed.add_field(name="Delay", value=f"`{self.config.get('delay')}s`", inline=True)
        embed.add_field(name="Title", value=self.config.get("title"), inline=False)
        
        cats = self.config.get("categories", [])
        cats_text = "\n".join([f"• {c['label']} -> `{c['value']}`" for c in cats]) if cats else "*None configured*"
        embed.add_field(name="Categories", value=cats_text, inline=False)
        
        btns = self.config.get("buttons", [])
        btns_text = "\n".join([f"• **{b['label']}** (`-{b['alias']}`)" for b in btns]) if btns else "*None configured (Close Thread button only)*"
        embed.add_field(name="Buttons", value=btns_text, inline=False)

        embed.set_footer(text="Use -stickypanel enable | addcategory | addbutton")
        await ctx.send(embed=embed)

    @stickypanel_cmd.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def enable_panel(self, ctx):
        self.config["enabled"] = True
        save_config(self.config)
        await ctx.send("✅ **Sticky Panel enabled!**")

    @stickypanel_cmd.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def disable_panel(self, ctx):
        self.config["enabled"] = False
        save_config(self.config)
        await ctx.send("🛑 **Sticky Panel disabled.**")

    @stickypanel_cmd.command(name="addbutton")
    @commands.has_permissions(administrator=True)
    async def add_button(self, ctx, label: str, alias: str, style: str = "primary", emoji: str = None, row: int = 1):
        if style.lower() not in STYLE_MAP:
            return await ctx.send("❌ Valid styles: `primary`, `secondary`, `success`, `danger`.")

        existing = next((b for b in self.config["buttons"] if b["label"].lower() == label.lower()), None)
        if existing:
            existing.update({"alias": alias, "style": style.lower(), "emoji": emoji, "row": row})
            await ctx.send(f"✅ Updated button **{label}** -> `-{alias}`.")
        else:
            self.config["buttons"].append({"label": label, "alias": alias, "style": style.lower(), "emoji": emoji, "row": row})
            await ctx.send(f"✅ Added button **{label}** -> `-{alias}`.")

        save_config(self.config)

    @stickypanel_cmd.command(name="removebutton")
    @commands.has_permissions(administrator=True)
    async def remove_button(self, ctx, label: str):
        initial = len(self.config["buttons"])
        self.config["buttons"] = [b for b in self.config["buttons"] if b["label"].lower() != label.lower()]
        
        if len(self.config["buttons"]) < initial:
            save_config(self.config)
            await ctx.send(f"✅ Removed button **{label}**.")
        else:
            await ctx.send(f"❌ Button **{label}** not found.")

    @stickypanel_cmd.command(name="addcategory")
    @commands.has_permissions(administrator=True)
    async def add_category(self, ctx, label: str, value: str, emoji: str = None):
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
        initial = len(self.config["categories"])
        self.config["categories"] = [c for c in self.config["categories"] if c["label"].lower() != label.lower()]
        
        if len(self.config["categories"]) < initial:
            save_config(self.config)
            await ctx.send(f"✅ Removed category **{label}**.")
        else:
            await ctx.send(f"❌ Category **{label}** not found.")

    @stickypanel_cmd.command(name="clearcategories")
    @commands.has_permissions(administrator=True)
    async def clear_categories(self, ctx):
        self.config["categories"] = []
        save_config(self.config)
        await ctx.send("✅ Cleared all categories.")

    # --- LISTENERS ---
    @commands.Cog.listener()
    async def on_thread_ready(self, thread, account, issue, logs):
        try:
            if hasattr(thread, "channel") and thread.channel:
                await self.resend_sticky(thread.channel)
        except Exception as e:
            print(f"[StickyPanel] on_thread_ready error: {e}")

    @commands.Cog.listener()
    async def on_message(self, message):
        try:
            # 1. Must be sent by the bot inside an active thread
            if message.author != self.bot.user:
                return

            # 2. Do not loop back on its own embed message
            if message.embeds and message.embeds[0].title == self.config.get("title"):
                return

            # 3. Re-trigger sticky loop in Modmail threads
            if message.guild:
                thread = await self.bot.threads.find(channel=message.channel)
                if thread:
                    await self.resend_sticky(message.channel)
        except Exception as e:
            print(f"[StickyPanel] on_message listener error: {e}")


async def setup(bot):
    await bot.add_cog(StickyPanel(bot))
