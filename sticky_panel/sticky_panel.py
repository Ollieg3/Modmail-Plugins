import asyncio
import json
import os
import discord
from discord.ext import commands

CONFIG_PATH = "sticky_panel_config.json"

DEFAULT_CONFIG = {
    "enabled": False,
    "delay": 1.5,
    "title": "⚡ Ticket Control Panel",
    "description": "Select an action below to manage this ticket.",
    "color": 0x5865F2,
    "categories": [],
    "buttons": []
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
        print(f"[StickyPanel] Config load failed ({e}). Reverting to default.")
        return DEFAULT_CONFIG

def save_config(config):
    tmp_path = f"{CONFIG_PATH}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        os.replace(tmp_path, CONFIG_PATH)
    except Exception as e:
        print(f"[StickyPanel] Error saving config: {e}")


# --- MODALS FOR CONFIGURATION ---
class AddButtonModal(discord.ui.Modal, title="➕ Add / Edit Action Button"):
    label_input = discord.ui.TextInput(
        label="Button Text Label",
        placeholder="e.g. Greeting",
        max_length=80,
        required=True
    )
    alias_input = discord.ui.TextInput(
        label="Command / Snippet Alias (without prefix)",
        placeholder="e.g. greeting",
        max_length=50,
        required=True
    )
    style_input = discord.ui.TextInput(
        label="Style (primary, secondary, success, danger)",
        placeholder="primary",
        default="primary",
        max_length=20,
        required=False
    )
    emoji_input = discord.ui.TextInput(
        label="Emoji (Optional Unicode Emoji)",
        placeholder="e.g. 👋",
        max_length=10,
        required=False
    )
    row_input = discord.ui.TextInput(
        label="Row (1-4): Line placement (Max 5 buttons/row)",
        placeholder="1",
        default="1",
        max_length=1,
        required=False
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        style_val = self.style_input.value.strip().lower() or "primary"
        if style_val not in STYLE_MAP:
            return await interaction.response.send_message("❌ Invalid style! Use: `primary`, `secondary`, `success`, or `danger`.", ephemeral=True)

        try:
            row_val = int(self.row_input.value.strip() or 1)
            row_val = min(max(row_val, 1), 4)
        except ValueError:
            return await interaction.response.send_message("❌ Row number must be a digit between 1 and 4.", ephemeral=True)

        label_val = self.label_input.value.strip()
        alias_val = self.alias_input.value.strip().lstrip("-")
        emoji_val = self.emoji_input.value.strip() or None

        existing = next((b for b in self.cog.config["buttons"] if b["label"].lower() == label_val.lower()), None)
        if existing:
            existing.update({"alias": alias_val, "style": style_val, "emoji": emoji_val, "row": row_val})
            msg = f"✅ Updated existing button **{label_val}** to run `-{alias_val}`."
        else:
            self.cog.config["buttons"].append({
                "label": label_val,
                "alias": alias_val,
                "style": style_val,
                "emoji": emoji_val,
                "row": row_val
            })
            msg = f"✅ Added button **{label_val}** -> runs `-{alias_val}`."

        save_config(self.cog.config)
        await interaction.response.send_message(msg, ephemeral=True)


class AddCategoryModal(discord.ui.Modal, title="📁 Add / Edit Category Option"):
    label_input = discord.ui.TextInput(
        label="Dropdown Label (What staff see)",
        placeholder="e.g. Executive Team",
        max_length=100,
        required=True
    )
    value_input = discord.ui.TextInput(
        label="Target Category Name (used for -move)",
        placeholder="e.g. Executive Team",
        max_length=100,
        required=True
    )
    emoji_input = discord.ui.TextInput(
        label="Emoji (Optional Unicode Emoji)",
        placeholder="e.g. 👔",
        max_length=10,
        required=False
    )
    alias_input = discord.ui.TextInput(
        label="Auto-run Alias/Snippet upon selection",
        placeholder="e.g. exec_transfer_snippet",
        max_length=50,
        required=False
    )

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        label_val = self.label_input.value.strip()
        value_val = self.value_input.value.strip()
        emoji_val = self.emoji_input.value.strip() or None
        alias_val = self.alias_input.value.strip().lstrip("-") or None

        existing = next((c for c in self.cog.config["categories"] if c["label"].lower() == label_val.lower()), None)
        if existing:
            existing.update({
                "value": value_val,
                "description": f"Move to {label_val}",
                "emoji": emoji_val,
                "alias": alias_val
            })
            msg = f"✅ Updated category **{label_val}**."
        else:
            self.cog.config["categories"].append({
                "label": label_val,
                "value": value_val,
                "description": f"Move to {label_val}",
                "emoji": emoji_val,
                "alias": alias_val
            })
            msg = f"✅ Added category **{label_val}** (`{value_val}`) to dropdown menu."

        save_config(self.cog.config)
        await interaction.response.send_message(msg, ephemeral=True)


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


# --- CATEGORY DROPDOWN ---
class CategorySelect(discord.ui.Select):
    def __init__(self, bot, categories):
        self.bot = bot
        self.categories = categories
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

            selected_value = self.values[0]
            cat_data = next((c for c in self.categories if c.get("value") == selected_value or c.get("label") == selected_value), None)
            alias_to_run = cat_data.get("alias") if cat_data else None

            status_msg = f"⌛ Moving thread to `{selected_value}`..."
            if alias_to_run:
                status_msg += f" and running `-{alias_to_run}`..."
            await interaction.response.send_message(status_msg, ephemeral=True)

            # Move command
            move_msg = interaction.message
            move_msg.content = f"-move {selected_value}"
            move_msg.author = interaction.user

            ctx_move = await self.bot.get_context(move_msg)
            if ctx_move.command:
                await self.bot.invoke(ctx_move)
            else:
                await self.bot.process_commands(move_msg)

            # Alias execution
            if alias_to_run:
                await asyncio.sleep(0.5)
                alias_msg = interaction.message
                alias_msg.content = f"-{alias_to_run}"
                alias_msg.author = interaction.user

                ctx_alias = await self.bot.get_context(alias_msg)
                if ctx_alias.command:
                    await self.bot.invoke(ctx_alias)
                else:
                    snippets_cog = self.bot.get_cog("Snippets")
                    if snippets_cog:
                        snippet = await snippets_cog.get_snippet(alias_to_run)
                        if snippet:
                            await snippets_cog.send_snippet(ctx_alias, snippet)
                            return
                    await self.bot.process_commands(alias_msg)

        except Exception as e:
            print(f"[StickyPanel] Category select error: {e}")


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

        if config.get("categories"):
            try:
                self.add_item(CategorySelect(self.bot, config["categories"]))
            except Exception as e:
                print(f"[StickyPanel] Skipped invalid categories: {e}")

        configured_buttons = config.get("buttons", [])
        max_row_used = 1

        for btn in configured_buttons:
            try:
                btn_row = min(max(btn.get("row", 1), 1), 4)
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
            await asyncio.sleep(self.config.get("delay", 1.5))

            old_msg_id = self.sticky_messages.get(channel.id)
            if old_msg_id:
                try:
                    old_msg = await channel.fetch_message(old_msg_id)
                    await old_msg.delete()
                except (discord.NotFound, discord.HTTPException, discord.Forbidden):
                    pass

            try:
                view = StickyPanelView(self.bot, self.config)
                new_msg = await channel.send(embed=self.build_panel_embed(), view=view)
                self.sticky_messages[channel.id] = new_msg.id
            except discord.HTTPException as e:
                print(f"[StickyPanel] Failed to send panel in {channel.id}: {e}")
                self.sticky_messages.pop(channel.id, None)

    # --- COMMANDS WITH MODALS ---
    @commands.group(name="stickypanel", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def stickypanel_cmd(self, ctx):
        embed = discord.Embed(title="⚙️ Sticky Panel Settings", color=discord.Color.blue())
        embed.add_field(name="Status", value="🟢 Enabled" if self.config.get("enabled") else "🔴 Disabled", inline=True)
        embed.add_field(name="Delay", value=f"`{self.config.get('delay')}s`", inline=True)
        embed.add_field(name="Title", value=self.config.get("title"), inline=False)
        
        cats = self.config.get("categories", [])
        cats_text = "\n".join([f"• {c['label']} -> `{c['value']}`" + (f" (Runs `-{c['alias']}`)" if c.get('alias') else "") for c in cats]) if cats else "*None configured*"
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
    async def add_button(self, ctx):
        """Opens a modal form to add or edit a panel button."""
        if ctx.interaction:
            await ctx.interaction.response.send_modal(AddButtonModal(self))
        else:
            button = discord.ui.Button(label="Open Button Form 📝", style=discord.ButtonStyle.primary)
            async def btn_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(AddButtonModal(self))
            button.callback = btn_callback
            view = discord.ui.View()
            view.add_item(button)
            await ctx.send("Click below to configure the action button:", view=view)

    @stickypanel_cmd.command(name="removebutton")
    @commands.has_permissions(administrator=True)
    async def remove_button(self, ctx, *, label: str):
        initial = len(self.config["buttons"])
        self.config["buttons"] = [b for b in self.config["buttons"] if b["label"].lower() != label.lower()]
        
        if len(self.config["buttons"]) < initial:
            save_config(self.config)
            await ctx.send(f"✅ Removed button **{label}**.")
        else:
            await ctx.send(f"❌ Button **{label}** not found.")

    @stickypanel_cmd.command(name="addcategory")
    @commands.has_permissions(administrator=True)
    async def add_category(self, ctx):
        """Opens a modal form to add or edit a category option."""
        if ctx.interaction:
            await ctx.interaction.response.send_modal(AddCategoryModal(self))
        else:
            button = discord.ui.Button(label="Open Category Form 📁", style=discord.ButtonStyle.primary)
            async def btn_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(AddCategoryModal(self))
            button.callback = btn_callback
            view = discord.ui.View()
            view.add_item(button)
            await ctx.send("Click below to configure the category option:", view=view)

    @stickypanel_cmd.command(name="removecategory")
    @commands.has_permissions(administrator=True)
    async def remove_category(self, ctx, *, label: str):
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
            if message.author != self.bot.user:
                return

            if message.embeds and message.embeds[0].title == self.config.get("title"):
                return

            if message.guild:
                thread = await self.bot.threads.find(channel=message.channel)
                if thread:
                    await self.resend_sticky(message.channel)
        except Exception as e:
            print(f"[StickyPanel] on_message error: {e}")


async def setup(bot):
    await bot.add_cog(StickyPanel(bot))
