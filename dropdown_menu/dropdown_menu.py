import asyncio
import json
import os
import shlex
from typing import Dict, Optional

import discord
from discord.ext import commands


DEFAULT_CONFIG_PATH = "data/support_dropdown_config.json"

DEFAULT_CATEGORIES: Dict[str, dict] = {
    "general": {
        "label": "General",
        "description": "General help and questions.",
        "emoji": "💬",
        "alias": "",
    },
    "staffing": {
        "label": "Staffing",
        "description": "Help relating to staff or internal matters.",
        "emoji": "🛡️",
        "alias": "",
    },
    "development": {
        "label": "Development",
        "description": "Bot, web, or technical development support.",
        "emoji": "🛠️",
        "alias": "",
    },
    "partnerships": {
        "label": "Partnerships",
        "description": "Questions or inquiries about partnerships.",
        "emoji": "🤝",
        "alias": "",
    },
}


class SupportCategorySelect(discord.ui.Select):
    def __init__(self, cog: "SupportDropdownCog"):
        self.cog = cog
        options = []
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

        super().__init__(
            custom_id="support_dropdown:category_select",
            placeholder="Choose a support category...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "This menu can only be used inside a server.",
                ephemeral=True,
            )
            return

        selected_key = self.values[0]
        cat_cfg = self.cog.categories.get(selected_key)
        if not cat_cfg:
            await interaction.response.send_message(
                "⚠️ That support category is no longer configured.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # 1. Verify the user's DMs are open before creating a ticket
        try:
            dm_channel = await interaction.user.create_dm()
            await dm_channel.send(
                embed=discord.Embed(
                    title=f"📩 {cat_cfg['label']} Ticket Opened",
                    description=(
                        f"Your **{cat_cfg['label']}** ticket has been opened in **{interaction.guild.name}**.\n"
                        "A staff member or automated system will follow up with you here."
                    ),
                    color=discord.Color.blurple(),
                )
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I couldn't send you a DM. Please **open your DMs** (check your server/privacy settings) and **try again**.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            await interaction.followup.send(
                "⚠️ There was an issue checking your DMs. Please make sure your DMs are open and try again.",
                ephemeral=True,
            )
            return

        # 2. Create the ticket channel
        guild = interaction.guild
        category = guild.get_channel(self.cog.ticket_category_id) if self.cog.ticket_category_id else None
        if not isinstance(category, discord.CategoryChannel):
            category = None

        safe_username = "".join(c for c in interaction.user.name.lower() if c.isalnum() or c in ("-", "_")).strip("-_") or "user"
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

        topic_text = f"Ticket opened by {interaction.user} (ID: {interaction.user.id}) | Category: {cat_cfg['label']}"

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
                "❌ I don't have permission to create ticket channels here. Please contact an administrator.",
                ephemeral=True,
            )
            return

        # Brief pause so channel creation/hider listeners settle before alias runs
        await asyncio.sleep(0.4)

        # 3. Auto-run configured alias/command for this category if set
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
            f"✅ Your **{cat_cfg['label']}** ticket ({ticket_channel.mention}) is ready! **Please check your DMs.**",
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
        self.categories: Dict[str, dict] = {k: dict(v) for k, v in DEFAULT_CATEGORIES.items()}
        self._load_config()
        self.view = SupportDropdownView(self)
        self.bot.add_view(self.view)

    def _load_config(self):
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.ticket_category_id = data.get("ticket_category_id")
            self.support_role_id = data.get("support_role_id")
            loaded_cats = data.get("categories")
            if isinstance(loaded_cats, dict) and loaded_cats:
                merged = {k: dict(v) for k, v in DEFAULT_CATEGORIES.items()}
                for k, v in loaded_cats.items():
                    key = k.lower().strip()
                    if key in merged:
                        merged[key].update(v)
                    else:
                        merged[key] = {
                            "label": v.get("label", key.title()),
                            "description": v.get("description", "Open a support ticket."),
                            "emoji": v.get("emoji"),
                            "alias": v.get("alias", ""),
                        }
                self.categories = merged
        except Exception as e:
            print(f"[SupportDropdown] Failed to load config: {e}")

    def _save_config(self):
        os.makedirs(os.path.dirname(self.config_path) or ".", exist_ok=True)
        payload = {
            "ticket_category_id": self.ticket_category_id,
            "support_role_id": self.support_role_id,
            "categories": self.categories,
        }
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _rebuild_view(self):
        self.view.stop()
        self.view = SupportDropdownView(self)
        self.bot.add_view(self.view)

    def _build_panel_embed(self, guild: Optional[discord.Guild]) -> discord.Embed:
        title_prefix = f"{guild.name} | " if guild else ""
        embed = discord.Embed(
            title=f"🎫 {title_prefix}Support",
            description=(
                "Need help? Open a private support ticket below.\n\n"
                "Choose the option that best matches what you need help with.\n\n"
                "**📋 Before opening a ticket**\n"
                "• Explain your issue clearly.\n"
                "• Do not open duplicate tickets.\n"
                "• Keep your DMs open so we can message you.\n"
                "• Misuse of the support system may result in moderation action."
            ),
            color=discord.Color.blurple(),
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
        """
        Executes a bot prefix command/alias in the newly created ticket channel.
        Supports placeholders: {user}, {user_id}, {user_name}, {channel}, {channel_id}, {category}, {category_key}
        Leading prefixes like '!' or '/' are stripped automatically for commands.get_command().
        """
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

        # Build a synthetic message context inside the ticket channel
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
                "content": f"!{raw}",
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
            # Parse arguments using the command's converter logic via a clean invoke string
            # If the command takes a single greedy/str arg or typed args, invoke through a helper
            arg_string = raw[len(tokens[0]):].strip()
            if not arg_string:
                await command.callback(ctx) if not command.cog else await command.callback(command.cog, ctx)
            else:
                # Re-parse with discord.py's view so converters (Member, TextChannel, int, etc.) work
                from discord.ext.commands.view import StringView

                ctx.view = StringView(arg_string)
                await command.prepare(ctx)
                await command.invoke(ctx)
        except Exception as e:
            print(f"[SupportDropdown] Error running alias '{raw}' in #{channel.name}: {e}")

    @commands.group(name="supportpanel", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def supportpanel_cmd(self, ctx: commands.Context):
        cat_name = "Not set"
        if self.ticket_category_id:
            ch = ctx.guild.get_channel(self.ticket_category_id)
            cat_name = f"{ch.name} (`{self.ticket_category_id}`)" if ch else f"`{self.ticket_category_id}`"

        role_name = "Not set"
        if self.support_role_id:
            r = ctx.guild.get_role(self.support_role_id)
            role_name = f"{r.mention} (`{self.support_role_id}`)" if r else f"`{self.support_role_id}`"

        lines = []
        for key, item in self.categories.items():
            alias_display = f"`{item['alias']}`" if item.get("alias") else "*None*"
            emoji_display = f"{item['emoji']} " if item.get("emoji") else ""
            lines.append(f"• {emoji_display}**{item['label']}** (`{key}`) → Alias: {alias_display}")

        embed = discord.Embed(
            title="🎛️ Support Dropdown Setup",
            color=discord.Color.blurple(),
            description=(
                f"**Ticket Category:** {cat_name}\n"
                f"**Support Role:** {role_name}\n\n"
                "**Categories & Auto-Aliases:**\n" + "\n".join(lines)
            ),
        )
        embed.add_field(
            name="Setup Commands",
            value=(
                "`!supportpanel send [#channel]` — Post the dropdown menu\n"
                "`!supportpanel category <category_id>` — Set ticket category\n"
                "`!supportpanel role <@role|role_id>` — Set support role\n"
                "`!supportpanel alias <general|staffing|development|partnerships> <command...>` — Set alias\n"
                "`!supportpanel clearalias <option>` — Remove alias"
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @supportpanel_cmd.command(name="send")
    @commands.has_permissions(administrator=True)
    async def send_panel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        target = channel or ctx.channel
        embed = self._build_panel_embed(ctx.guild)
        await target.send(embed=embed, view=self.view)
        if target != ctx.channel:
            await ctx.send(f"✅ Support dropdown panel sent to {target.mention}.")

    @supportpanel_cmd.command(name="category")
    @commands.has_permissions(administrator=True)
    async def set_ticket_category(self, ctx: commands.Context, category: discord.CategoryChannel):
        self.ticket_category_id = category.id
        self._save_config()
        await ctx.send(f"✅ Ticket category set to **{category.name}** (`{category.id}`).")

    @supportpanel_cmd.command(name="role")
    @commands.has_permissions(administrator=True)
    async def set_support_role(self, ctx: commands.Context, role: discord.Role):
        self.support_role_id = role.id
        self._save_config()
        await ctx.send(f"✅ Support role set to {role.mention} (`{role.id}`).")

    @supportpanel_cmd.command(name="alias")
    @commands.has_permissions(administrator=True)
    async def set_alias(self, ctx: commands.Context, option: str, *, alias_command: str):
        key = option.lower().strip()
        if key not in self.categories:
            valid = ", ".join(f"`{k}`" for k in self.categories)
            await ctx.send(f"❌ Unknown option `{option}`. Valid options: {valid}")
            return

        self.categories[key]["alias"] = alias_command.strip()
        self._save_config()
        await ctx.send(
            f"✅ Alias for **{self.categories[key]['label']}** set to:\n`{alias_command.strip()}`"
        )

    @supportpanel_cmd.command(name="clearalias")
    @commands.has_permissions(administrator=True)
    async def clear_alias(self, ctx: commands.Context, option: str):
        key = option.lower().strip()
        if key not in self.categories:
            valid = ", ".join(f"`{k}`" for k in self.categories)
            await ctx.send(f"❌ Unknown option `{option}`. Valid options: {valid}")
            return

        self.categories[key]["alias"] = ""
        self._save_config()
        await ctx.send(f"🗑️ Cleared alias for **{self.categories[key]['label']}**.")


async def setup(bot: commands.Bot):
    await bot.add_cog(SupportDropdownCog(bot))
