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
    "blue": discord.ButtonStyle.primary,
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
            data.setdefault("description", "Select an action below to manage this ticket.")
            data.setdefault("color", 0x5865F2)
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
        label="Color Style (blue, grey, green, red)",
        placeholder="blue",
        default="blue",
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

    def __init__(self, cog, ctx):
        super().__init__()
        self.cog = cog
        self.ctx = ctx

    async def on_submit(self, interaction: discord.Interaction):
        style_val = self.style_input.value.strip().lower() or "blue"
        if style_val not in STYLE_MAP:
            return await interaction.response.send_message("❌ Invalid color style! Use: `blue`, `grey`, `green`, or `red`.", ephemeral=True)

        try:
            row_val = int(self.row_input.value.strip() or 1)
            row_val = min(max(row_val, 1), 4)
        except ValueError:
            return await interaction.response.send_message("❌ Row number must be a digit between 1 and 4.", ephemeral=True)

        current_row_count = sum(1 for b in self.cog.config["buttons"] if b.get("row", 1) == row_val)
        label_val = self.label_input.value.strip()
        
        existing = next((b for b in self.cog.config["buttons"] if b["label"].lower() == label_val.lower()), None)
        if not existing and current_row_count >= 5:
            return await interaction.response.send_message(f"❌ Row `{row_val}` already has the maximum limit of 5 buttons! Choose a different row.", ephemeral=True)

        alias_val = self.alias_input.value.strip().lstrip("-")
        emoji_val = self.emoji_input.value.strip() or None

        if existing:
            existing.update({"alias": alias_val, "style": style_val, "emoji": emoji_val, "row": row_val})
            action_type = "Updated"
        else:
            self.cog.config["buttons"].append({
                "label": label_val,
                "alias": alias_val,
                "style": style_val,
                "emoji": emoji_val,
                "row": row_val
            })
            action_type = "Added"

        save_config(self.cog.config)
        await interaction.response.defer()
        
        await self.ctx.send(
            f"✅ Successfully **{action_type}** button!\n"
            f"• **Label:** {emoji_val or ''} {label_val}\n"
            f"• **Runs Command:** `-{alias_val}`\n"
            f"• **Color Style:** `{style_val}`\n"
            f"• **Row Placement:** `{row_val}`"
        )


class AddCategoryModal(discord.ui.Modal, title="📁 Add / Edit Category Option"):
    label_input = discord.ui.TextInput(
        label="Dropdown Label (What staff see)",
        placeholder="e.g. Executive Team",
        max_length=100,
        required=True
    )
    value_input = discord.ui.TextInput(
        label="Target Category ID (used for -move ID)",
        placeholder="e.g. 123456789012345678",
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

    def __init__(self, cog, ctx):
        super().__init__()
        self.cog = cog
        self.ctx = ctx

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
            action_type = "Updated"
        else:
            self.cog.config["categories"].append({
                "label": label_val,
                "value": value_val,
                "description": f"Move to {label_val}",
                "emoji": emoji_val,
                "alias": alias_val
            })
            action_type = "Added"

        save_config(self.cog.config)
        await interaction.response.defer()

        await self.ctx.send(
            f"✅ Successfully **{action_type}** category option!\n"
            f"• **Dropdown Label:** {emoji_val or ''} {label_val}\n"
            f"• **Target Category ID:** `{value_val}`\n"
            f"• **Auto-run Snippet/Command:** `-{alias_val}`" if alias_val else f"• **Auto-run Snippet/Command:** *None*"
        )


# --- INTERACTIVE REMOVAL DROPDOWNS ---
class RemoveButtonSelect(discord.ui.Select):
    def __init__(self, cog, ctx):
        self.cog = cog
        self.ctx = ctx
        options = []
        for btn in cog.config["buttons"]:
            options.append(discord.SelectOption(
                label=btn["label"],
                description=f"Runs -{btn['alias']}",
                emoji=btn.get("emoji")
            ))
        super().__init__(placeholder="Select a button to remove...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_label = self.values[0]
        removed_btn = next((b for b in self.cog.config["buttons"] if b["label"] == selected_label), None)
        self.cog.config["buttons"] = [b for b in self.cog.config["buttons"] if b["label"] != selected_label]
        save_config(self.cog.config)
        
        await interaction.message.delete()
        await self.ctx.send(
            f"🗑️ Successfully removed panel button:\n"
            f"• **Label:** {selected_label}\n"
            f"• **Was running:** `-{removed_btn['alias'] if removed_btn else 'unknown'}`"
        )


class RemoveButtonView(discord.ui.View):
    def __init__(self, cog, ctx):
        super().__init__(timeout=60)
        self.add_item(RemoveButtonSelect(cog, ctx))


class RemoveCategorySelect(discord.ui.Select):
    def __init__(self, cog, ctx):
        self.cog = cog
        self.ctx = ctx
        options = []
        for cat in cog.config["categories"]:
            options.append(discord.SelectOption(
                label=cat["label"],
                description=f"ID: {cat['value']}",
                emoji=cat.get("emoji")
            ))
        super().__init__(placeholder="Select a category to remove...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_label = self.values[0]
        removed_cat = next((c for c in self.cog.config["categories"] if c["label"] == selected_label), None)
        self.cog.config["categories"] = [c for c in self.cog.config["categories"] if c["label"] != selected_label]
        save_config(self.cog.config)
        
        await interaction.message.delete()
        await self.ctx.send(
            f"🗑️ Successfully removed panel dropdown category:\n"
            f"• **Label:** {selected_label}\n"
            f"• **Target ID:** `{removed_cat['value'] if removed_cat else 'unknown'}`"
        )


class RemoveCategoryView(discord.ui.View):
    def __init__(self, cog, ctx):
        super().__init__(timeout=60)
        self.add_item(RemoveCategorySelect(cog, ctx))


# --- DYNAMIC BUTTON (WITH USER TRACKING FIX) ---
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
            message.author = interaction.user  # Actual staff member

            ctx = await self.view.bot.get_context(message)
            ctx.author = interaction.user  # Ensures logging/permissions attribute correctly

            if ctx.command:
                await ctx.command.invoke(ctx)
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

            status_msg = f"⌛ Moving thread..."
            if alias_to_run:
                status_msg += f" and running `-{alias_to_run}`..."
            await interaction.response.send_message(status_msg, ephemeral=True)

            move_msg = interaction.message
            move_msg.content = f"-move {selected_value}"
            move_msg.author = interaction.user

            ctx_move = await self.bot.get_context(move_msg)
            ctx_move.author = interaction.user
            if ctx_move.command:
                await ctx_move.command.invoke(ctx_move)
            else:
                await self.bot.process_commands(move_msg)

            if alias_to_run:
                await asyncio.sleep(0.5)
                alias_msg = interaction.message
                alias_msg.content = f"-{alias_to_run}"
                alias_msg.author = interaction.user

                ctx_alias = await self.bot.get_context(alias_msg)
                ctx_alias.author = interaction.user
                if ctx_alias.command:
                    await ctx_alias.command.invoke(ctx_alias)
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


# --- CLOSE CONFIRMATION VIEW (WITH USER TRACKING FIX) ---
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
            message.author = interaction.user  # Actual staff member
            
            ctx = await self.bot.get_context(message)
            ctx.author = interaction.user  # Ensures transcript logs the correct closer
            
            if ctx.command:
                await ctx.command.invoke(ctx)
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
                    style=btn.get("style", "blue"),
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
        color_val = self.config.get("color", 0x5865F2)
        if isinstance(color_val, str):
            try:
                color_val = int(color_val.lstrip("#"), 16)
            except ValueError:
                color_val = 0x5865F2

        embed = discord.Embed(
            title=self.config.get("title", "⚡ Ticket Control Panel"),
            description=self.config.get("description", "Select an action below to manage this ticket."),
            color=color_val
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

    # --- COMMANDS ---
    @commands.group(name="stickypanel", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def stickypanel_cmd(self, ctx):
        embed = discord.Embed(title="⚙️ Sticky Panel Settings", color=discord.Color.blue())
        embed.add_field(name="Status", value="🟢 Enabled" if self.config.get("enabled") else "🔴 Disabled", inline=True)
        embed.add_field(name="Delay", value=f"`{self.config.get('delay')}s`", inline=True)
        embed.add_field(name="Title", value=self.config.get("title"), inline=False)
        
        cats = self.config.get("categories", [])
        cats_text = "\n".join([f"• {c['label']} -> ID: `{c['value']}`" + (f" (Runs `-{c['alias']}`)" if c.get('alias') else "") for c in cats]) if cats else "*None configured*"
        embed.add_field(name="Categories", value=cats_text, inline=False)
        
        btns = self.config.get("buttons", [])
        btns_text = "\n".join([f"• **{b['label']}** (`-{b['alias']}`)" for b in btns]) if btns else "*None configured (Close Thread button only)*"
        embed.add_field(name="Buttons", value=btns_text, inline=False)

        embed.set_footer(text="Use -stickypanel help for a full list of commands.")
        await ctx.send(embed=embed)

    @stickypanel_cmd.command(name="help")
    @commands.has_permissions(administrator=True)
    async def panel_help(self, ctx):
        embed = discord.Embed(
            title="📖 Sticky Panel Help & Commands",
            description="Manage your automated ticket control panels easily using the commands below:",
            color=discord.Color.blue()
        )
        embed.add_field(
            name="⚙️ General Control & Customization",
            value=(
                "• `-stickypanel` - View current configuration status.\n"
                "• `-stickypanel enable` / `disable` - Toggle automatic sticky panel.\n"
                "• `-stickypanel preview` - Send a live test preview of the panel here.\n"
                "• `-stickypanel settitle <text>` - Set embed header title.\n"
                "• `-stickypanel setdescription <text>` - Set embed description.\n"
                "• `-stickypanel setcolor <hex>` - Set embed border color (e.g. `#5865F2`).\n"
                "• `-stickypanel delay <seconds>` - Set resend debounce rate limit delay.\n"
                "• `-stickypanel help` - Show this help menu."
            ),
            inline=False
        )
        embed.add_field(
            name="➕ Additions (Interactive Forms)",
            value=(
                "• `-stickypanel addbutton` - Add/edit custom action button.\n"
                "• `-stickypanel addcategory` - Add/edit dropdown category transfer option."
            ),
            inline=False
        )
        embed.add_field(
            name="🗑️ Removals & Clearances",
            value=(
                "• `-stickypanel removebutton` - Pick a button to delete.\n"
                "• `-stickypanel clearbuttons` - Wipe all custom action buttons.\n"
                "• `-stickypanel removecategory` - Pick a category to delete.\n"
                "• `-stickypanel clearcategories` - Wipe all dropdown categories."
            ),
            inline=False
        )
        embed.set_footer(text="Sticky Panel System • Requires Administrator Permissions")
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

    @stickypanel_cmd.command(name="preview")
    @commands.has_permissions(administrator=True)
    async def panel_preview(self, ctx):
        view = StickyPanelView(self.bot, self.config)
        await ctx.send("🔍 **Panel Preview:** (This is how it looks in threads)", embed=self.build_panel_embed(), view=view)

    @stickypanel_cmd.command(name="settitle")
    @commands.has_permissions(administrator=True)
    async def set_title(self, ctx, *, title: str):
        self.config["title"] = title
        save_config(self.config)
        await ctx.send(f"✅ Successfully updated panel title to:\n> {title}")

    @stickypanel_cmd.command(name="setdescription")
    @commands.has_permissions(administrator=True)
    async def set_description(self, ctx, *, description: str):
        self.config["description"] = description
        save_config(self.config)
        await ctx.send(f"✅ Successfully updated panel description to:\n> {description}")

    @stickypanel_cmd.command(name="setcolor")
    @commands.has_permissions(administrator=True)
    async def set_color(self, ctx, color_code: str):
        try:
            clean_hex = color_code.lstrip("#")
            color_int = int(clean_hex, 16)
            self.config["color"] = color_int
            save_config(self.config)
            await ctx.send(f"✅ Successfully updated panel embed color to `#{clean_hex.upper()}`!")
        except ValueError:
            await ctx.send("❌ Invalid color format! Please provide a valid Hex code (e.g., `-stickypanel setcolor #5865F2`).")

    @stickypanel_cmd.command(name="delay")
    @commands.has_permissions(administrator=True)
    async def set_delay(self, ctx, seconds: float):
        if seconds < 0.5 or seconds > 10.0:
            return await ctx.send("❌ Delay must be between `0.5` and `10.0` seconds.")
        self.config["delay"] = seconds
        save_config(self.config)
        await ctx.send(f"✅ Successfully updated sticky resend delay to `{seconds}s`.")

    @stickypanel_cmd.command(name="addbutton")
    @commands.has_permissions(administrator=True)
    async def add_button(self, ctx):
        if ctx.interaction:
            await ctx.interaction.response.send_modal(AddButtonModal(self, ctx))
        else:
            button = discord.ui.Button(label="Open Button Form 📝", style=discord.ButtonStyle.primary)
            async def btn_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(AddButtonModal(self, ctx))
            button.callback = btn_callback
            view = discord.ui.View()
            view.add_item(button)
            await ctx.send("Click below to configure the action button:", view=view)

    @stickypanel_cmd.command(name="removebutton")
    @commands.has_permissions(administrator=True)
    async def remove_button(self, ctx):
        if not self.config["buttons"]:
            return await ctx.send("❌ There are no custom buttons configured to remove.")
        view = RemoveButtonView(self, ctx)
        await ctx.send("Select the button you want to remove from the dropdown below:", view=view, ephemeral=True)

    @stickypanel_cmd.command(name="clearbuttons")
    @commands.has_permissions(administrator=True)
    async def clear_buttons(self, ctx):
        self.config["buttons"] = []
        save_config(self.config)
        await ctx.send("✅ Cleared all custom panel action buttons.")

    @stickypanel_cmd.command(name="addcategory")
    @commands.has_permissions(administrator=True)
    async def add_category(self, ctx):
        if ctx.interaction:
            await ctx.interaction.response.send_modal(AddCategoryModal(self, ctx))
        else:
            button = discord.ui.Button(label="Open Category Form 📁", style=discord.ButtonStyle.primary)
            async def btn_callback(interaction: discord.Interaction):
                await interaction.response.send_modal(AddCategoryModal(self, ctx))
            button.callback = btn_callback
            view = discord.ui.View()
            view.add_item(button)
            await ctx.send("Click below to configure the category option:", view=view)

    @stickypanel_cmd.command(name="removecategory")
    @commands.has_permissions(administrator=True)
    async def remove_category(self, ctx):
        if not self.config["categories"]:
            return await ctx.send("❌ There are no categories configured to remove.")
        view = RemoveCategoryView(self, ctx)
        await ctx.send("Select the category you want to remove from the dropdown below:", view=view, ephemeral=True)

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
