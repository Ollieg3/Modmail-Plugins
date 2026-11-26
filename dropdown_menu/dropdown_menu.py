import asyncio
import json
import os
import re
import shlex
from typing import Dict, List, Optional

import discord
from discord.ext import commands
from discord.ext.commands.view import StringView


DEFAULT_CONFIG_PATH = "data/support_dropdown_config.json"
DEFAULT_EMBED_COLOR = discord.Color.blurple()


def parse_hex_color(value: str) -> Optional[discord.Color]:
    """Parses a hex color string like '#5865F2' or '5865F2' into a discord.Color."""
    cleaned = value.strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", cleaned):
        return discord.Color(int(cleaned, 16))
    return None


class SupportCategorySelect(discord.ui.Select):
    def __init__(self, cog: "SupportDropdownCog"):
        self.cog = cog
        options: List[discord.SelectOption] = []

        for key, data in cog.categories.items():
            emoji_val = data.get("emoji") or None
            options.append(
                discord.SelectOption(
                    label=data["label"][:100],
                    value=key[:100],
                    description=(data.get("description") or "Open a support ticket.")[:100],
                    emoji=emoji_val,
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="No categories configured",
                    value="__none__",
                    description="An admin needs to run the setup command first.",
                )
            )

        super().__init__(
            custom_id="support_dropdown:category_select",
            placeholder="Choose a support category...",
            min_values=1,
            max_values=1,
            options=options,
            disabled=(len(cog.categories) == 0),
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This menu can only be used inside a server.",
                ephemeral=True,
            )
            return

        selected_key = self.values[0]
        if selected_key == "__none__" or selected_key not in self.cog.categories:
            await interaction.response.send_message(
                "⚠️ That support category is no longer configured.",
                ephemeral=True,
            )
            return

        cat_cfg = self.cog.categories[selected_key]
        await interaction.response.defer(ephemeral=True)

        # 1. Check if the user's DMs are open BEFORE creating a ticket
        try:
            dm_channel = await interaction.user.create_dm()
            await dm_channel.send(
                embed=discord.Embed(
                    title=f"📩 {cat_cfg['label']} Ticket Opened",
                    description=(
                        f"Your **{cat_cfg['label']}** ticket has been opened in **{interaction.guild.name}**.\n"
                        "Please reply here or wait for a staff member to follow up."
                    ),
                    color=self.cog.get_embed_color(),
                )
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I couldn't send you a DM. Please **open your DMs** (check your server privacy settings) and **try again**.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            await interaction.followup.send(
                "⚠️ There was an issue reaching your DMs. Please make sure your DMs are open and try again.",
                ephemeral=True,
            )
            return

        # 2. Create the ticket channel
        guild = interaction.guild
        category = (
            guild.get_channel(self.cog.ticket_category_id)
            if self.cog.ticket_category_id
            else None
        )
        if not isinstance(category, discord.CategoryChannel):
            category = None

        safe_username = (
            "".join(
                c for c in interaction.user.name.lower() if c.isalnum() or c in ("-", "_")
            ).strip("-_")
            or "user"
        )
        channel_name = f"{selected_key}-{safe_username}"[:100]

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
            guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_permissions=True,
            ),
        }

        if self.cog.support_role_id:
            support_role = guild.get_role(self.cog.support_role_id)
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )

        topic_text = (
            f"Ticket opened by {interaction.user} (ID: {interaction.user.id}) "
            f"| Category: {cat_cfg['label']}"
        )

        try:
            ticket_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=topic_text[:1024],
                reason=f"Support ticket ({cat_cfg['label']}) opened by {interaction.user} ({interaction.user.id})",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to create ticket channels. Please contact an administrator.",
                ephemeral=True,
            )
            return

        # Brief delay so channel-create / HideTicketCreator listeners settle first
        await asyncio.sleep(0.4)

        # 3. Auto-run the configured alias/command for this option
        alias_template = (cat_cfg.get("alias") or "").strip()
        if alias_template:
            await self.cog.run_alias(
                template=alias_template,
                guild=guild,
                channel=ticket_channel,
                member=interaction.user,
                category_key=selected_key,
                category_label=cat_cfg["label"],
            )

        # 4. Tell the user to check their DMs
        await interaction.followup.send(
            f"✅ Your **{cat_cfg['label']}** ticket ({ticket_channel.mention}) has been created! **Please check your DMs.**",
            ephemeral=True,
        )


class SupportDropdownView(discord.ui.View):
    def __init__(self, cog: "SupportDropdownCog"):
        super().__init__(timeout=None)
        self.add_item(SupportCategorySelect(cog))


class SupportDropdownCog(commands.Cog):
    def __init__(self, bot: commands.Bot, config_path: str = DEFAULT_CONFIG_PATH):
        self.bot = bot
        self.config_path = config_path
        self.ticket_category_id: Optional[int] = None
        self.support_role_id: Optional[int] = None
        self.panel_title: Optional[str] = None
        self.panel_description: Optional[str] = None
        self.embed_color_hex: Optional[str] = None
        self.categories: Dict[str, dict] = {}
        self._load_config()
        self.view = SupportDropdownView(self)
        self.bot.add_view(self.view)

    def get_embed_color(self) -> discord.Color:
        if self.embed_color_hex:
            parsed = parse_hex_color(self.embed_color_hex)
            if parsed is not None:
                return parsed
        return DEFAULT_EMBED_COLOR

    def _load_config(self):
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.ticket_category_id = data.get("ticket_category_id")
            self.support_role_id = data.get("support_role_id")
            self.panel_title = data.get("panel_title")
            self.panel_description = data.get("panel_description")
            self.embed_color_hex = data.get("embed_color_hex")
            loaded_cats = data.get("categories")
            if isinstance(loaded_cats, dict):
                self.categories = loaded_cats
        except Exception as e:
            print(f"[SupportDropdown] Failed to load config: {e}")

    def _save_config(self):
        os.makedirs(os.path.dirname(self.config_path) or ".", exist_ok=True)
        payload = {
            "ticket_category_id": self.ticket_category_id,
            "support_role_id": self.support_role_id,
            "panel_title": self.panel_title,
            "panel_description": self.panel_description,
            "embed_color_hex": self.embed_color_hex,
            "categories": self.categories,
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _rebuild_view(self):
        self.view.stop()
        self.view = SupportDropdownView(self)
        self.bot.add_view(self.view)

    def _resolve_option_key(self, query: str) -> Optional[str]:
        cleaned = query.strip().lower()
        if cleaned in self.categories:
            return cleaned
        for key, data in self.categories.items():
            if data.get("label", "").strip().lower() == cleaned:
                return key
        return None

    async def _get_bot_prefix(self, message_or_channel) -> str:
        prefixes = await self.bot.get_prefix(message_or_channel)
        if isinstance(prefixes, str):
            return prefixes
        if isinstance(prefixes, (list, tuple)) and prefixes:
            for p in prefixes:
                if not p.startswith("<@"):
                    return p
            return prefixes[0]
        return "!"

    def _build_panel_embed(self, guild: Optional[discord.Guild]) -> discord.Embed:
        default_title = f"🎫 {guild.name} | Support" if guild else "🎫 Support"
        default_desc = (
            "Need help? Open a private support ticket below.\n\n"
            "Choose the option that best matches what you need help with.\n\n"
            "**📋 Before opening a ticket**\n"
            "• Explain your issue clearly.\n"
            "• Do not open duplicate tickets.\n"
            "• Keep your DMs open so we can message you.\n"
            "• Misuse of the support system may result in moderation action."
        )
        embed = discord.Embed(
            title=self.panel_title or default_title,
            description=self.panel_description or default_desc,
            color=self.get_embed_color(),
        )
        embed.set_footer(text="Support System • Select a category below")
        return embed

    async def run_alias(
        self,
        template: str,
        guild: discord.Guild,
        channel: discord.TextChannel,
        member: discord.Member,
        category_key: str,
        category_label: str,
    ):
        """Auto-executes a bot command/alias inside the newly created ticket channel."""
        formatted = template.format(
            user=str(member.id),
            user_mention=member.mention,
            user_id=str(member.id),
            user_name=member.name,
            channel=str(channel.id),
            channel_mention=channel.mention,
            channel_id=str(channel.id),
            category=category_label,
            category_key=category_key,
        ).strip()

        if not formatted:
            return

        prefixes = await self.bot.get_prefix(channel)
        if isinstance(prefixes, str):
            prefixes = [prefixes]

        raw = formatted
        for p in sorted(prefixes, key=len, reverse=True):
            if p and raw.startswith(p):
                raw = raw[len(p):].strip()
                break
        if raw.startswith("/"):
            raw = raw[1:].strip()

        try:
            tokens = shlex.split(raw)
        except ValueError:
            tokens = raw.split()

        if not tokens:
            return

        cmd_name = tokens[0].lower()
        command = self.bot.get_command(cmd_name)
        if not command:
            print(f"[SupportDropdown] Alias command '{cmd_name}' not found.")
            return

        active_prefix = await self._get_bot_prefix(channel)
        msg = discord.Message(
            state=self.bot._connection,
            channel=channel,
            data={
                "id": discord.utils.time_snowflake(discord.utils.utcnow()),
                "webhook_id": None,
                "attachments": [],
                "embeds": [],
                "application": None,
                "activity": None,
                "edited_timestamp": None,
                "flags": 0,
                "mention_everyone": False,
                "mentions": [],
                "mention_roles": [],
                "type": discord.MessageType.default.value,
                "pinned": False,
                "tts": False,
                "content": f"{active_prefix}{raw}",
                "author": {
                    "id": str(guild.me.id),
                    "username": guild.me.name,
                    "discriminator": guild.me.discriminator,
                    "avatar": guild.me.avatar.key if guild.me.avatar else None,
                    "bot": True,
                },
                "timestamp": discord.utils.utcnow().isoformat(),
            },
        )
        ctx = await self.bot.get_context(msg)
        ctx.author = guild.me
        ctx.guild = guild
        ctx.channel = channel
        ctx.command = command
        ctx.invoked_with = cmd_name

        try:
            arg_string = raw[len(tokens[0]):].strip()
            if not arg_string:
                if command.cog:
                    await command.callback(command.cog, ctx)
                else:
                    await command.callback(ctx)
            else:
                ctx.view = StringView(arg_string)
                await command.prepare(ctx)
                await command.invoke(ctx)
        except Exception as e:
            print(f"[SupportDropdown] Error running alias '{raw}' in #{channel.name}: {e}")

    @staticmethod
    def _slugify(label: str, existing: Dict[str, dict]) -> str:
        base = re.sub(r"[^a-z0-9_-]+", "-", label.lower()).strip("-_") or "option"
        key = base[:80]
        counter = 2
        while key in existing:
            key = f"{base[:75]}-{counter}"
            counter += 1
        return key

    @commands.command(name="supportsetup")
    @commands.has_permissions(administrator=True)
    async def interactive_setup(self, ctx: commands.Context):
        """Interactive step-by-step wizard to configure and post the support dropdown."""
        prefix = await self._get_bot_prefix(ctx.message)
        wizard_color = self.get_embed_color()

        def check(m: discord.Message) -> bool:
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        async def ask(prompt_embed: discord.Embed, timeout: float = 180.0) -> Optional[str]:
            await ctx.send(embed=prompt_embed)
            try:
                reply = await self.bot.wait_for("message", check=check, timeout=timeout)
            except asyncio.TimeoutError:
                await ctx.send("⏰ Setup timed out. Run the command again whenever you're ready.")
                return None

            content = reply.content.strip()
            if content.lower() in ("cancel", "stop", "exit"):
                await ctx.send("🛑 Setup cancelled. No changes were saved.")
                return None
            return content

        # Step 1: Ticket Category
        step1 = await ask(
            discord.Embed(
                title="🛠️ Support Dropdown Setup — Step 1/6: Ticket Category",
                description=(
                    "Where should new ticket channels be created?\n\n"
                    "Send the **Category ID** or **exact Category Name**, or type `skip` for none.\n"
                    "*(Type `cancel` at any time to abort.)*"
                ),
                color=wizard_color,
            )
        )
        if step1 is None:
            return

        ticket_category_id: Optional[int] = None
        if step1.lower() != "skip":
            cat_obj = None
            if step1.isdigit():
                ch = ctx.guild.get_channel(int(step1))
                if isinstance(ch, discord.CategoryChannel):
                    cat_obj = ch
            if not cat_obj:
                cat_obj = discord.utils.find(
                    lambda c: isinstance(c, discord.CategoryChannel) and c.name.lower() == step1.lower(),
                    ctx.guild.channels,
                )
            if cat_obj:
                ticket_category_id = cat_obj.id
                await ctx.send(f"✅ Ticket category set to **{cat_obj.name}**.")
            else:
                await ctx.send("⚠️ Couldn't find that category—defaulting to uncategorized.")

        # Step 2: Staff / Support Role
        step2 = await ask(
            discord.Embed(
                title="🛠️ Support Dropdown Setup — Step 2/6: Support Role",
                description=(
                    "Which role should be able to view and reply in created tickets?\n\n"
                    "**Mention the role**, send its **Role ID** or **name**, or type `skip`."
                ),
                color=wizard_color,
            )
        )
        if step2 is None:
            return

        support_role_id: Optional[int] = None
        if step2.lower() != "skip":
            role_obj = None
            mention_match = re.match(r"^<@&(\d+)>$", step2)
            if mention_match:
                role_obj = ctx.guild.get_role(int(mention_match.group(1)))
            elif step2.isdigit():
                role_obj = ctx.guild.get_role(int(step2))
            if not role_obj:
                role_obj = discord.utils.find(
                    lambda r: r.name.lower() == step2.lower(), ctx.guild.roles
                )
            if role_obj:
                support_role_id = role_obj.id
                await ctx.send(f"✅ Support role set to {role_obj.mention}.")
            else:
                await ctx.send("⚠️ Couldn't find that role—skipping role permissions.")

        # Step 3: Embed Color (Manual hex or default)
        step3_color = await ask(
            discord.Embed(
                title="🛠️ Support Dropdown Setup — Step 3/6: Embed Color",
                description=(
                    "Send a **6-digit hex color** for the embeds (e.g. `#F1C40F` or `#2B2D31`), "
                    "or type **`default`** to use the default blurple color."
                ),
                color=wizard_color,
            )
        )
        if step3_color is None:
            return

        embed_color_hex: Optional[str] = None
        if step3_color.lower() != "default":
            parsed = parse_hex_color(step3_color)
            if parsed is not None:
                embed_color_hex = f"#{step3_color.strip().lstrip('#').upper()}"
                wizard_color = parsed
                await ctx.send(f"✅ Embed color set to `{embed_color_hex}`.")
            else:
                await ctx.send("⚠️ Invalid hex code—using the `default` color instead.")
        else:
            wizard_color = DEFAULT_EMBED_COLOR
            await ctx.send("✅ Using `default` embed color.")

        # Step 4: Panel Title & Description
        step4 = await ask(
            discord.Embed(
                title="🛠️ Support Dropdown Setup — Step 4/6: Panel Embed",
                description=(
                    "Send the **embed title** for your support panel, or type `default` to use the standard layout."
                ),
                color=wizard_color,
            )
        )
        if step4 is None:
            return

        panel_title: Optional[str] = None
        panel_description: Optional[str] = None
        if step4.lower() != "default":
            panel_title = step4[:256]
            step4_desc = await ask(
                discord.Embed(
                    title="🛠️ Support Dropdown Setup — Step 4b/6: Panel Description",
                    description="Now send the **embed description** (or type `default` for the default text).",
                    color=wizard_color,
                )
            )
            if step4_desc is None:
                return
            if step4_desc.lower() != "default":
                panel_description = step4_desc[:4000]

        # Step 5: Loop to build Dropdown Categories
        new_categories: Dict[str, dict] = {}
        while True:
            count = len(new_categories)
            if count >= 25:
                await ctx.send("⚠️ Reached Discord's maximum of 25 dropdown options.")
                break

            prompt_text = (
                f"Currently added: **{count}** option(s).\n\n"
                "Send the **name/label** for the next dropdown option (e.g. `General Support`, `Staffing Support`, `Development Support`, `Partnership Support`)."
            )
            if count > 0:
                prompt_text += "\nOr type **`done`** when you've finished adding options."

            opt_label = await ask(
                discord.Embed(
                    title=f"🛠️ Support Dropdown Setup — Step 5/6: Dropdown Option #{count + 1}",
                    description=prompt_text,
                    color=wizard_color,
                )
            )
            if opt_label is None:
                return

            if opt_label.lower() == "done":
                if count == 0:
                    await ctx.send("❌ You need to add at least **1** dropdown option before finishing.")
                    continue
                break

            opt_desc = await ask(
                discord.Embed(
                    title=f"Option '{opt_label}' — Description",
                    description="Enter a short description shown under this option in the menu (or `skip`).",
                    color=wizard_color,
                )
            )
            if opt_desc is None:
                return
            description_val = "Open a support ticket." if opt_desc.lower() == "skip" else opt_desc[:100]

            opt_emoji = await ask(
                discord.Embed(
                    title=f"Option '{opt_label}' — Emoji",
                    description="Send an **emoji** for this option (standard or custom server emoji), or type `skip`.",
                    color=wizard_color,
                )
            )
            if opt_emoji is None:
                return
            emoji_val = None if opt_emoji.lower() == "skip" else opt_emoji.strip()

            opt_alias = await ask(
                discord.Embed(
                    title=f"Option '{opt_label}' — Auto-Run Alias",
                    description=(
                        "Enter the command/alias to auto-run when a ticket is opened with this option, or type `skip`.\n\n"
                        f"• Uses your bot's prefix (`{prefix}`) automatically (with or without typing `{prefix}`).\n"
                        "• Available placeholders: `{user}`, `{user_id}`, `{user_name}`, `{channel}`, `{channel_id}`, `{category}`\n"
                        f"• Example: `{prefix}myalias {{user}}`"
                    ),
                    color=wizard_color,
                )
            )
            if opt_alias is None:
                return
            alias_val = "" if opt_alias.lower() == "skip" else opt_alias.strip()

            key = self._slugify(opt_label, new_categories)
            new_categories[key] = {
                "label": opt_label[:100],
                "description": description_val,
                "emoji": emoji_val,
                "alias": alias_val,
            }
            await ctx.send(f"✅ Added option **{opt_label}** (`{key}`).")

        # Step 6: Target Channel to post the dropdown panel
        step6 = await ask(
            discord.Embed(
                title="🛠️ Support Dropdown Setup — Step 6/6: Post Panel",
                description=(
                    "Where should I send the support dropdown panel?\n\n"
                    "**Mention the channel** (e.g. `#support`), send its **Channel ID**, type `here`, or type `skip` to save without posting yet."
                ),
                color=wizard_color,
            )
        )
        if step6 is None:
            return

        # Save everything & rebuild persistent view
        self.ticket_category_id = ticket_category_id
        self.support_role_id = support_role_id
        self.embed_color_hex = embed_color_hex
        self.panel_title = panel_title
        self.panel_description = panel_description
        self.categories = new_categories
        self._save_config()
        self._rebuild_view()

        target_channel: Optional[discord.TextChannel] = None
        if step6.lower() == "here":
            if isinstance(ctx.channel, discord.TextChannel):
                target_channel = ctx.channel
        elif step6.lower() != "skip":
            ch_match = re.match(r"^<#(\d+)>$", step6)
            ch_id = int(ch_match.group(1)) if ch_match else (int(step6) if step6.isdigit() else None)
            if ch_id:
                ch_obj = ctx.guild.get_channel(ch_id)
                if isinstance(ch_obj, discord.TextChannel):
                    target_channel = ch_obj

        if target_channel:
            await target_channel.send(embed=self._build_panel_embed(ctx.guild), view=self.view)
            await ctx.send(f"🎉 Setup complete! Support dropdown panel posted in {target_channel.mention}.")
        else:
            await ctx.send(
                f"🎉 Setup saved! Whenever you're ready to post it, run `{prefix}supportpanel send #channel`."
            )

    @commands.group(name="supportedit", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def supportedit_cmd(self, ctx: commands.Context):
        """Show quick edit commands for the support dropdown configuration."""
        prefix = await self._get_bot_prefix(ctx.message)
        embed = discord.Embed(
            title="✏️ Support Dropdown Edit Commands",
            color=self.get_embed_color(),
            description=(
                f"`{prefix}supportedit color <#hex|default>` — Change embed color\n"
                f"`{prefix}supportedit category <#category|id|none>` — Change ticket category\n"
                f"`{prefix}supportedit role <@role|id|none>` — Change support role\n"
                f"`{prefix}supportedit title <text|default>` — Change panel title\n"
                f"`{prefix}supportedit description <text|default>` — Change panel description\n"
                f"`{prefix}supportedit alias <option> <command|clear>` — Change or clear an option's alias\n"
                f"`{prefix}supportedit option <option> <label|desc|emoji> <value|clear>` — Edit an option\n"
                f"`{prefix}supportedit addoption <label> | <description> | [emoji] | [alias]` — Add a new option\n"
                f"`{prefix}supportedit removeoption <option>` — Remove an option"
            ),
        )
        await ctx.send(embed=embed)

    @supportedit_cmd.command(name="color")
    @commands.has_permissions(administrator=True)
    async def edit_color(self, ctx: commands.Context, color_value: str):
        if color_value.lower() == "default":
            self.embed_color_hex = None
            self._save_config()
            await ctx.send("✅ Embed color reset to `default`.")
            return

        parsed = parse_hex_color(color_value)
        if parsed is None:
            await ctx.send("❌ Invalid hex color. Use a 6-digit hex like `#F1C40F` or type `default`.")
            return

        self.embed_color_hex = f"#{color_value.strip().lstrip('#').upper()}"
        self._save_config()
        await ctx.send(f"✅ Embed color updated to `{self.embed_color_hex}`.")

    @supportedit_cmd.command(name="category")
    @commands.has_permissions(administrator=True)
    async def edit_category(self, ctx: commands.Context, *, target: str):
        if target.strip().lower() in ("none", "clear", "skip"):
            self.ticket_category_id = None
            self._save_config()
            await ctx.send("✅ Ticket category cleared.")
            return

        cat_obj = None
        if target.strip().isdigit():
            ch = ctx.guild.get_channel(int(target.strip()))
            if isinstance(ch, discord.CategoryChannel):
                cat_obj = ch
        if not cat_obj:
            cat_obj = discord.utils.find(
                lambda c: isinstance(c, discord.CategoryChannel) and c.name.lower() == target.strip().lower(),
                ctx.guild.channels,
            )

        if not cat_obj:
            await ctx.send("❌ Category not found. Send a valid Category ID, exact name, or `none`.")
            return

        self.ticket_category_id = cat_obj.id
        self._save_config()
        await ctx.send(f"✅ Ticket category updated to **{cat_obj.name}** (`{cat_obj.id}`).")

    @supportedit_cmd.command(name="role")
    @commands.has_permissions(administrator=True)
    async def edit_role(self, ctx: commands.Context, *, target: str):
        if target.strip().lower() in ("none", "clear", "skip"):
            self.support_role_id = None
            self._save_config()
            await ctx.send("✅ Support role cleared.")
            return

        role_obj = None
        mention_match = re.match(r"^<@&(\d+)>$", target.strip())
        if mention_match:
            role_obj = ctx.guild.get_role(int(mention_match.group(1)))
        elif target.strip().isdigit():
            role_obj = ctx.guild.get_role(int(target.strip()))
        if not role_obj:
            role_obj = discord.utils.find(
                lambda r: r.name.lower() == target.strip().lower(), ctx.guild.roles
            )

        if not role_obj:
            await ctx.send("❌ Role not found. Mention the role, send its ID/name, or type `none`.")
            return

        self.support_role_id = role_obj.id
        self._save_config()
        await ctx.send(f"✅ Support role updated to {role_obj.mention} (`{role_obj.id}`).")

    @supportedit_cmd.command(name="title")
    @commands.has_permissions(administrator=True)
    async def edit_title(self, ctx: commands.Context, *, title: str):
        if title.strip().lower() == "default":
            self.panel_title = None
            self._save_config()
            await ctx.send("✅ Panel title reset to `default`.")
            return

        self.panel_title = title.strip()[:256]
        self._save_config()
        await ctx.send(f"✅ Panel title updated to **{self.panel_title}**.")

    @supportedit_cmd.command(name="description")
    @commands.has_permissions(administrator=True)
    async def edit_description(self, ctx: commands.Context, *, description: str):
        if description.strip().lower() == "default":
            self.panel_description = None
            self._save_config()
            await ctx.send("✅ Panel description reset to `default`.")
            return

        self.panel_description = description.strip()[:4000]
        self._save_config()
        await ctx.send("✅ Panel description updated.")

    @supportedit_cmd.command(name="alias")
    @commands.has_permissions(administrator=True)
    async def edit_alias(self, ctx: commands.Context, option: str, *, alias_command: str):
        key = self._resolve_option_key(option)
        if not key:
            await ctx.send(f"❌ Option `{option}` not found.")
            return

        if alias_command.strip().lower() in ("clear", "none"):
            self.categories[key]["alias"] = ""
            self._save_config()
            await ctx.send(f"🗑️ Cleared alias for **{self.categories[key]['label']}**.")
            return

        self.categories[key]["alias"] = alias_command.strip()
        self._save_config()
        await ctx.send(
            f"✅ Alias for **{self.categories[key]['label']}** (`{key}`) updated to:\n`{alias_command.strip()}`"
        )

    @supportedit_cmd.command(name="option")
    @commands.has_permissions(administrator=True)
    async def edit_option_field(
        self, ctx: commands.Context, option: str, field: str, *, value: str
    ):
        key = self._resolve_option_key(option)
        if not key:
            await ctx.send(f"❌ Option `{option}` not found.")
            return

        field_clean = field.strip().lower()
        val_clean = value.strip()

        if field_clean in ("label", "name"):
            self.categories[key]["label"] = val_clean[:100]
        elif field_clean in ("desc", "description"):
            self.categories[key]["description"] = (
                "Open a support ticket." if val_clean.lower() == "clear" else val_clean[:100]
            )
        elif field_clean == "emoji":
            self.categories[key]["emoji"] = None if val_clean.lower() in ("clear", "none") else val_clean
        else:
            await ctx.send("❌ Field must be `label`, `desc` (or `description`), or `emoji`.")
            return

        self._save_config()
        self._rebuild_view()
        await ctx.send(
            f"✅ Updated `{field_clean}` for **{self.categories[key]['label']}** (`{key}`). Re-send the panel if you want the message updated."
        )

    @supportedit_cmd.command(name="addoption")
    @commands.has_permissions(administrator=True)
    async def add_option(self, ctx: commands.Context, *, spec: str):
        if len(self.categories) >= 25:
            await ctx.send("❌ Maximum of 25 dropdown options reached.")
            return

        parts = [p.strip() for p in spec.split("|")]
        if not parts[0]:
            await ctx.send(
                "❌ Provide at least an option label, e.g.:\n`!supportedit addoption Billing Support | Help with invoices | 💳 | billingalias {user}`"
            )
            return

        label = parts[0][:100]
        description = parts[1][:100] if len(parts) > 1 and parts[1] else "Open a support ticket."
        emoji = parts[2] if len(parts) > 2 and parts[2] and parts[2].lower() != "none" else None
        alias = parts[3] if len(parts) > 3 and parts[3] and parts[3].lower() != "none" else ""

        key = self._slugify(label, self.categories)
        self.categories[key] = {
            "label": label,
            "description": description,
            "emoji": emoji,
            "alias": alias,
        }
        self._save_config()
        self._rebuild_view()
        await ctx.send(f"✅ Added option **{label}** (`{key}`). Re-send the panel to show the updated menu.")

    @supportedit_cmd.command(name="removeoption")
    @commands.has_permissions(administrator=True)
    async def remove_option(self, ctx: commands.Context, *, option: str):
        key = self._resolve_option_key(option)
        if not key:
            await ctx.send(f"❌ Option `{option}` not found.")
            return

        removed = self.categories.pop(key)
        self._save_config()
        self._rebuild_view()
        await ctx.send(f"🗑️ Removed option **{removed['label']}** (`{key}`).")

    @commands.command(name="supportpanel")
    @commands.has_permissions(administrator=True)
    async def post_or_view_panel(
        self, ctx: commands.Context, action: Optional[str] = None, channel: Optional[discord.TextChannel] = None
    ):
        """View current config or post the panel with `<prefix>supportpanel send #channel`."""
        prefix = await self._get_bot_prefix(ctx.message)
        if action and action.lower() == "send":
            if not self.categories:
                await ctx.send(f"⚠️ No categories configured yet. Run `{prefix}supportsetup` first.")
                return
            target = channel or ctx.channel
            await target.send(embed=self._build_panel_embed(ctx.guild), view=self.view)
            if target != ctx.channel:
                await ctx.send(f"✅ Support dropdown panel sent to {target.mention}.")
            return

        color_label = self.embed_color_hex or "default"
        lines = [
            f"• {item['emoji'] + ' ' if item.get('emoji') else ''}**{item['label']}** (`{key}`) → Alias: `{item['alias']}`"
            if item.get("alias")
            else f"• {item['emoji'] + ' ' if item.get('emoji') else ''}**{item['label']}** (`{key}`) → Alias: *None*"
            for key, item in self.categories.items()
        ]
        embed = discord.Embed(
            title="🎛️ Support Dropdown Config",
            description=(
                f"**Embed Color:** `{color_label}`\n\n"
                + ("\n".join(lines) if lines else "*No categories configured yet.*")
                + f"\n\nRun `{prefix}supportsetup` for the wizard, `{prefix}supportedit` to edit, or `{prefix}supportpanel send #channel` to post."
            ),
            color=self.get_embed_color(),
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(SupportDropdownCog(bot))
