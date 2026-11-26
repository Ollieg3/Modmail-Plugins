import asyncio
from contextlib import asynccontextmanager
import json
import os
import re
import shlex
from typing import List, Optional

import discord
from discord.ext import commands
from discord.ext.commands.view import StringView

try:
    from core import checks
    from core.models import PermissionLevel
except ImportError:
    checks = None
    PermissionLevel = None


def owner_only():
    """Uses Modmail's native PermissionLevel.OWNER check."""
    if checks is not None and PermissionLevel is not None:
        return checks.has_permissions(PermissionLevel.OWNER)
    return commands.is_owner()


CONFIG_PATH = "support_panel_config.json"
DEFAULT_COLOR = 0x5865F2


def parse_color(val) -> int:
    if isinstance(val, int):
        return val
    if isinstance(val, str):
        cleaned = val.strip().lstrip("#")
        if re.fullmatch(r"[0-9a-fA-F]{6}", cleaned):
            return int(cleaned, 16)
    return DEFAULT_COLOR


def load_config() -> dict:
    default_cfg = {
        "title": "🎫 Support",
        "description": (
            "Need help? Open a private support ticket below.\n\n"
            "Choose the option that best matches what you need help with.\n\n"
            "**📋 Before opening a ticket**\n"
            "• Explain your issue clearly.\n"
            "• Do not open duplicate tickets.\n"
            "• Keep your DMs open so we can message you.\n"
            "• Misuse of the support system may result in moderation action."
        ),
        "color": DEFAULT_COLOR,
        "categories": [],
    }
    if not os.path.exists(CONFIG_PATH):
        save_config(default_cfg)
        return default_cfg

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in default_cfg.items():
            data.setdefault(k, v)
        return data
    except Exception as e:
        print(f"[SupportPanel] Failed to load config: {e}")
        return default_cfg


def save_config(config: dict):
    tmp = f"{CONFIG_PATH}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        os.replace(tmp, CONFIG_PATH)
    except Exception as e:
        print(f"[SupportPanel] Failed to save config: {e}")


class ModmailCategorySelect(discord.ui.Select):
    def __init__(self, cog: "ModmailSupportPanel"):
        self.cog = cog
        cats = cog.config.get("categories", [])
        options: List[discord.SelectOption] = []

        for idx, cat in enumerate(cats):
            options.append(
                discord.SelectOption(
                    label=cat.get("label", f"Option {idx + 1}")[:100],
                    value=str(idx),
                    description=(cat.get("description") or "Open a support ticket.")[:100],
                    emoji=cat.get("emoji") or None,
                )
            )

        if not options:
            options.append(
                discord.SelectOption(
                    label="No categories configured",
                    value="__none__",
                    description="A bot owner needs to run supportsetup first.",
                )
            )

        super().__init__(
            custom_id="modmail_support_panel:select",
            placeholder="Choose a support category...",
            min_values=1,
            max_values=1,
            options=options,
            disabled=(len(cats) == 0),
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "__none__":
            return await interaction.response.send_message(
                "⚠️ No support categories are configured yet.", ephemeral=True
            )

        try:
            idx = int(self.values[0])
            cat = self.cog.config["categories"][idx]
        except (ValueError, IndexError, KeyError):
            return await interaction.response.send_message(
                "⚠️ That support option is no longer valid.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        user = interaction.user
        label = cat.get("label", "Support")
        alias_cmd = (cat.get("alias") or "").strip()
        target_cat_id = (cat.get("category_id") or "").strip() or None

        # 1. Verify DMs are open before creating a Modmail thread
        try:
            dm = await user.create_dm()
            await dm.send(
                embed=discord.Embed(
                    title=f"📩 {label} Ticket Opened",
                    description=(
                        f"Your **{label}** ticket has been opened.\n"
                        "Please reply here or wait for our team to respond."
                    ),
                    color=self.cog.get_color(),
                )
            )
        except discord.Forbidden:
            return await interaction.followup.send(
                "❌ I couldn't send you a DM. Please **open your DMs** and **try again**.",
                ephemeral=True,
            )
        except discord.HTTPException:
            return await interaction.followup.send(
                "⚠️ Couldn't verify your DMs right now. Please make sure your DMs are open and try again.",
                ephemeral=True,
            )

        # 2. Open a normal user-initiated Modmail thread
        bot = self.cog.bot
        if not hasattr(bot, "threads"):
            return await interaction.followup.send(
                "❌ Modmail threads manager not found on bot.", ephemeral=True
            )

        thread = None
        try:
            existing_thread = await bot.threads.find(recipient=user)
            if existing_thread:
                thread = existing_thread
            else:
                create_kwargs = {}
                if target_cat_id and getattr(bot, "modmail_guild", None):
                    cat_channel = (
                        bot.modmail_guild.get_channel(int(target_cat_id))
                        if target_cat_id.isdigit()
                        else None
                    )
                    if isinstance(cat_channel, discord.CategoryChannel):
                        create_kwargs["category"] = cat_channel

                async with self.cog.bypass_confirm_thread_creation():
                    created = await bot.threads.create(
                        recipient=user,
                        **create_kwargs,
                    )
                    if created and getattr(created, "channel", None):
                        thread = created
        except Exception as e:
            print(f"[SupportPanel] Exception during threads.create for {user}: {e}")

        # Poll briefly while Modmail finishes creating the thread channel
        if not thread or not getattr(thread, "channel", None):
            for _ in range(15):
                await asyncio.sleep(0.4)
                try:
                    found = await bot.threads.find(recipient=user)
                    if found and getattr(found, "channel", None):
                        thread = found
                        break
                except Exception:
                    pass

        if not thread or not getattr(thread, "channel", None):
            return await interaction.followup.send(
                "❌ Failed to open your ticket thread. Please try again or contact staff.",
                ephemeral=True,
            )

        await asyncio.sleep(1.0)

        # 3. Auto-run configured alias / command / snippet in the thread channel
        if alias_cmd:
            await self.cog.run_in_thread(
                channel=thread.channel,
                member=user,
                category_label=label,
                raw_alias=alias_cmd,
            )

        # 4. Tell the user to check their DMs
        await interaction.followup.send(
            f"✅ Your **{label}** ticket is open! **Please check your DMs.**",
            ephemeral=True,
        )


class ModmailSupportView(discord.ui.View):
    def __init__(self, cog: "ModmailSupportPanel"):
        super().__init__(timeout=None)
        self.add_item(ModmailCategorySelect(cog))


class ModmailSupportPanel(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = load_config()
        self.view = ModmailSupportView(self)
        self.bot.add_view(self.view)

    def get_color(self) -> int:
        return parse_color(self.config.get("color", DEFAULT_COLOR))

    def rebuild_view(self):
        self.view.stop()
        self.view = ModmailSupportView(self)
        self.bot.add_view(self.view)

    @asynccontextmanager
    async def bypass_confirm_thread_creation(self):
        """Temporarily disables thread creation confirmation while opening via the dropdown."""
        cfg = getattr(self.bot, "config", None)
        keys = ("confirm_thread_creation", "thread_creation_confirmation", "confirm_new_thread")
        saved = {}

        try:
            if isinstance(cfg, dict):
                for k in keys:
                    if k in cfg:
                        saved[("dict", k)] = cfg[k]
                        cfg[k] = False
            elif cfg is not None:
                for k in keys:
                    if hasattr(cfg, k):
                        saved[("attr", k)] = getattr(cfg, k)
                        setattr(cfg, k, False)

            for k in keys:
                if hasattr(self.bot, k):
                    saved[("bot", k)] = getattr(self.bot, k)
                    setattr(self.bot, k, False)

            yield
        finally:
            for (kind, k), val in saved.items():
                if kind == "dict" and isinstance(cfg, dict):
                    cfg[k] = val
                elif kind == "attr" and cfg is not None:
                    setattr(cfg, k, val)
                elif kind == "bot":
                    setattr(self.bot, k, val)

    def build_panel_embed(self, guild: Optional[discord.Guild] = None) -> discord.Embed:
        title = self.config.get("title") or (f"🎫 {guild.name} | Support" if guild else "🎫 Support")
        desc = self.config.get("description") or "Choose a support category below."
        embed = discord.Embed(title=title, description=desc, color=self.get_color())
        embed.set_footer(text="Support System • Select a category below")
        return embed

    async def _get_prefix(self, channel) -> str:
        try:
            prefixes = await self.bot.get_prefix(channel)
            if isinstance(prefixes, str):
                return prefixes
            if isinstance(prefixes, (list, tuple)) and prefixes:
                for p in prefixes:
                    if not p.startswith("<@"):
                        return p
                return prefixes[0]
        except Exception:
            pass
        return getattr(self.bot, "prefix", "-") or "-"

    def _resolve_modmail_alias(self, cmd_name: str, arg_str: str, prefix: str) -> Optional[str]:
        aliases_map = None
        if isinstance(getattr(self.bot, "aliases", None), dict):
            aliases_map = self.bot.aliases
        elif isinstance(getattr(self.bot, "config", None), dict) and isinstance(
            self.bot.config.get("aliases"), dict
        ):
            aliases_map = self.bot.config["aliases"]
        elif getattr(self.bot, "config", None) is not None and isinstance(
            getattr(self.bot.config, "aliases", None), dict
        ):
            aliases_map = self.bot.config.aliases

        if not aliases_map or cmd_name not in aliases_map:
            return None

        target = str(aliases_map[cmd_name]).strip()
        if not target:
            return None
        if not any(target.startswith(p) for p in [prefix, "!", "?", ".", "-"]):
            target = f"{prefix}{target}"
        return f"{target} {arg_str}".strip() if arg_str else target

    async def _get_bot_owner_member(self, guild: discord.Guild):
        """Resolves a bot owner Member in the Modmail guild so Modmail's PermissionLevel checks pass."""
        owner_ids = list(getattr(self.bot, "owner_ids", None) or [])
        single_owner = getattr(self.bot, "owner_id", None)
        if single_owner and single_owner not in owner_ids:
            owner_ids.append(single_owner)

        for oid in owner_ids:
            m = guild.get_member(oid)
            if m:
                return m
            try:
                return await guild.fetch_member(oid)
            except discord.HTTPException:
                pass

        if guild.owner:
            return guild.owner
        if getattr(guild, "owner_id", None):
            try:
                return await guild.fetch_member(guild.owner_id)
            except discord.HTTPException:
                pass
        return guild.me

    async def run_in_thread(
        self,
        channel: discord.TextChannel,
        member,
        category_label: str,
        raw_alias: str,
    ):
        """Runs a command, Modmail alias, or snippet inside the newly opened thread channel."""
        formatted = raw_alias.format(
            user=str(member.id),
            user_id=str(member.id),
            user_name=member.name,
            user_mention=member.mention,
            channel=str(channel.id),
            channel_id=str(channel.id),
            channel_mention=channel.mention,
            category=category_label,
        ).strip()

        if not formatted:
            return

        prefix = await self._get_prefix(channel)
        content = formatted
        if not any(content.startswith(p) for p in [prefix, "!", "?", ".", "-"]):
            content = f"{prefix}{content}"

        try:
            tokens = shlex.split(content)
        except ValueError:
            tokens = content.split()

        if not tokens:
            return

        cmd_name = tokens[0].lstrip("-!?.").lower()
        arg_str = content[len(tokens[0]):].strip()

        expanded = self._resolve_modmail_alias(cmd_name, arg_str, prefix)
        if expanded:
            content = expanded
            try:
                tokens = shlex.split(content)
            except ValueError:
                tokens = content.split()
            cmd_name = tokens[0].lstrip("-!?.").lower()
            arg_str = content[len(tokens[0]):].strip()

        exec_member = await self._get_bot_owner_member(channel.guild)

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
                "content": content,
                "author": {
                    "id": str(exec_member.id),
                    "username": exec_member.name,
                    "discriminator": exec_member.discriminator,
                    "avatar": exec_member.avatar.key if exec_member.avatar else None,
                    "bot": False,
                },
                "timestamp": discord.utils.utcnow().isoformat(),
            },
        )
        msg.author = exec_member

        try:
            ctx = await self.bot.get_context(msg)
            ctx.author = exec_member

            if ctx.command:
                if arg_str:
                    ctx.view = StringView(arg_str)
                    await ctx.command.prepare(ctx)
                    await ctx.command.invoke(ctx)
                else:
                    if ctx.command.cog:
                        await ctx.command.callback(ctx.command.cog, ctx)
                    else:
                        await ctx.command.callback(ctx)
                return

            snippets_cog = self.bot.get_cog("Snippets")
            if snippets_cog and cmd_name:
                snippet = await snippets_cog.get_snippet(cmd_name)
                if snippet:
                    await snippets_cog.send_snippet(ctx, snippet)
                    return

            await self.bot.process_commands(msg)
            self.bot.dispatch("message", msg)
        except Exception as e:
            print(f"[SupportPanel] Error running alias '{content}' in #{channel.name}: {e}")

    def _find_category_index(self, query: str) -> Optional[int]:
        q = query.strip().lower()
        if q.isdigit():
            idx = int(q)
            if 0 <= idx < len(self.config.get("categories", [])):
                return idx
        for i, cat in enumerate(self.config.get("categories", [])):
            if cat.get("label", "").strip().lower() == q:
                return i
        return None

    # --- STEP-BY-STEP SETUP WIZARD ---
    @commands.command(name="supportsetup")
    @owner_only()
    async def support_setup(self, ctx: commands.Context):
        """Interactive step-by-step setup for the main-server support dropdown."""
        prefix = await self._get_prefix(ctx.channel)

        def check(m: discord.Message) -> bool:
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id

        async def ask(title: str, body: str) -> Optional[str]:
            await ctx.send(embed=discord.Embed(title=title, description=body, color=self.get_color()))
            try:
                msg = await self.bot.wait_for("message", check=check, timeout=180.0)
            except asyncio.TimeoutError:
                await ctx.send("⏰ Setup timed out.")
                return None
            txt = msg.content.strip()
            if txt.lower() in ("cancel", "stop", "exit"):
                await ctx.send("🛑 Setup cancelled.")
                return None
            return txt

        c_ans = await ask(
            "🛠️ Support Setup (1/4) — Embed Color",
            "Send a **6-digit hex color** (e.g. `#5865F2`), or type **`default`**.\n*(Type `cancel` anytime to stop.)*",
        )
        if c_ans is None:
            return
        color_val = DEFAULT_COLOR if c_ans.lower() == "default" else parse_color(c_ans)

        t_ans = await ask(
            "🛠️ Support Setup (2/4) — Panel Title",
            "Send the **panel title**, or type **`default`**.",
        )
        if t_ans is None:
            return
        title_val = f"🎫 {ctx.guild.name} | Support" if t_ans.lower() == "default" else t_ans[:256]

        d_ans = await ask(
            "🛠️ Support Setup (2b/4) — Panel Description",
            "Send the **panel description**, or type **`default`**.",
        )
        if d_ans is None:
            return
        desc_val = self.config["description"] if d_ans.lower() == "default" else d_ans[:4000]

        categories = []
        while True:
            if len(categories) >= 25:
                await ctx.send("⚠️ Reached Discord's limit of 25 options.")
                break

            extra = "\nOr type **`done`** when finished." if categories else ""
            lbl = await ask(
                f"🛠️ Support Setup (3/4) — Option #{len(categories) + 1} Name",
                f"Enter the dropdown option name (e.g. `General Support`, `Staffing Support`, `Development Support`, `Partnership Support`).{extra}",
            )
            if lbl is None:
                return
            if lbl.lower() == "done":
                if not categories:
                    await ctx.send("❌ Add at least **1** option before typing `done`.")
                    continue
                break

            desc = await ask(
                f"Option '{lbl}' — Description",
                "Enter a short description for this option (or `skip`).",
            )
            if desc is None:
                return

            emoji = await ask(
                f"Option '{lbl}' — Emoji",
                "Send an emoji for this option (or `skip`).",
            )
            if emoji is None:
                return

            cat_id = await ask(
                f"Option '{lbl}' — Support Server Category ID (Optional)",
                "Send the Category ID in the **support server** to open into, or `skip`.",
            )
            if cat_id is None:
                return

            alias = await ask(
                f"Option '{lbl}' — Auto-Run Alias / Command",
                (
                    f"Enter the alias/command/snippet to auto-run in the opened thread, or `skip`.\n"
                    f"Placeholders: `{{user}}`, `{{user_id}}`, `{{user_name}}`, `{{channel}}`, `{{channel_id}}`, `{{category}}`\n"
                    f"Example: `{prefix}myalias {{user}}`"
                ),
            )
            if alias is None:
                return

            categories.append({
                "label": lbl[:100],
                "description": "Open a support ticket." if desc.lower() == "skip" else desc[:100],
                "emoji": None if emoji.lower() == "skip" else emoji,
                "category_id": None if cat_id.lower() == "skip" else cat_id,
                "alias": "" if alias.lower() == "skip" else alias,
            })
            await ctx.send(f"✅ Added **{lbl}**.")

        ch_ans = await ask(
            "🛠️ Support Setup (4/4) — Post Panel",
            "Mention the channel in this server to post the panel (e.g. `#support`), type `here`, or type `skip`.",
        )
        if ch_ans is None:
            return

        self.config["color"] = color_val
        self.config["title"] = title_val
        self.config["description"] = desc_val
        self.config["categories"] = categories
        save_config(self.config)
        self.rebuild_view()

        target_ch: Optional[discord.TextChannel] = None
        if ch_ans.lower() == "here" and isinstance(ctx.channel, discord.TextChannel):
            target_ch = ctx.channel
        elif ch_ans.lower() != "skip":
            m = re.match(r"^<#(\d+)>$", ch_ans)
            cid = int(m.group(1)) if m else (int(ch_ans) if ch_ans.isdigit() else None)
            if cid and isinstance(ctx.guild.get_channel(cid), discord.TextChannel):
                target_ch = ctx.guild.get_channel(cid)

        if target_ch:
            await target_ch.send(embed=self.build_panel_embed(ctx.guild), view=self.view)
            await ctx.send(f"🎉 Saved and posted panel in {target_ch.mention}!")
        else:
            await ctx.send(f"🎉 Saved! Post anytime with `{prefix}supportpanel send #channel`.")

    # --- PANEL & EDIT COMMANDS ---
    @commands.command(name="supportpanel")
    @owner_only()
    async def support_panel(
        self, ctx: commands.Context, action: Optional[str] = None, channel: Optional[discord.TextChannel] = None
    ):
        prefix = await self._get_prefix(ctx.channel)
        if action and action.lower() == "send":
            if not self.config.get("categories"):
                return await ctx.send(f"⚠️ No categories configured. Run `{prefix}supportsetup` first.")
            target = channel or ctx.channel
            await target.send(embed=self.build_panel_embed(ctx.guild), view=self.view)
            if target != ctx.channel:
                await ctx.send(f"✅ Panel sent to {target.mention}.")
            return

        cats = self.config.get("categories", [])
        lines = [
            f"`{i}` • {c['emoji'] + ' ' if c.get('emoji') else ''}**{c['label']}** → Alias: `{c['alias'] or 'None'}`"
            for i, c in enumerate(cats)
        ]
        embed = discord.Embed(
            title="🎛️ Support Panel Config",
            description=(
                f"**Title:** {self.config.get('title')}\n"
                f"**Color:** `#{self.get_color():06X}`\n\n"
                + ("\n".join(lines) if lines else "*No options configured yet.*")
                + f"\n\nUse `{prefix}supportsetup`, `{prefix}supportedit`, or `{prefix}supportpanel send #channel`."
            ),
            color=self.get_color(),
        )
        await ctx.send(embed=embed)

    @commands.group(name="supportedit", invoke_without_command=True)
    @owner_only()
    async def support_edit(self, ctx: commands.Context):
        prefix = await self._get_prefix(ctx.channel)
        embed = discord.Embed(
            title="✏️ Support Panel Edit Commands",
            color=self.get_color(),
            description=(
                f"`{prefix}supportedit color <#hex|default>`\n"
                f"`{prefix}supportedit title <text|default>`\n"
                f"`{prefix}supportedit description <text>`\n"
                f"`{prefix}supportedit alias <option> <command|clear>`\n"
                f"`{prefix}supportedit option <option> <label|desc|emoji|category> <value|clear>`\n"
                f"`{prefix}supportedit addoption <label> | <desc> | [emoji] | [category_id] | [alias]`\n"
                f"`{prefix}supportedit removeoption <option>`"
            ),
        )
        await ctx.send(embed=embed)

    @support_edit.command(name="color")
    @owner_only()
    async def edit_color(self, ctx: commands.Context, value: str):
        self.config["color"] = DEFAULT_COLOR if value.lower() == "default" else parse_color(value)
        save_config(self.config)
        await ctx.send(f"✅ Color updated to `#{self.get_color():06X}`.")

    @support_edit.command(name="title")
    @owner_only()
    async def edit_title(self, ctx: commands.Context, *, title: str):
        self.config["title"] = f"🎫 {ctx.guild.name} | Support" if title.lower() == "default" else title[:256]
        save_config(self.config)
        await ctx.send("✅ Title updated.")

    @support_edit.command(name="description")
    @owner_only()
    async def edit_description(self, ctx: commands.Context, *, desc: str):
        self.config["description"] = desc[:4000]
        save_config(self.config)
        await ctx.send("✅ Description updated.")

    @support_edit.command(name="alias")
    @owner_only()
    async def edit_alias(self, ctx: commands.Context, option: str, *, alias_cmd: str):
        idx = self._find_category_index(option)
        if idx is None:
            return await ctx.send("❌ Option not found.")
        self.config["categories"][idx]["alias"] = (
            "" if alias_cmd.strip().lower() in ("clear", "none") else alias_cmd.strip()
        )
        save_config(self.config)
        await ctx.send(f"✅ Updated alias for **{self.config['categories'][idx]['label']}**.")

    @support_edit.command(name="option")
    @owner_only()
    async def edit_option(self, ctx: commands.Context, option: str, field: str, *, value: str):
        idx = self._find_category_index(option)
        if idx is None:
            return await ctx.send("❌ Option not found.")
        f = field.strip().lower()
        v = value.strip()
        cat = self.config["categories"][idx]

        if f in ("label", "name"):
            cat["label"] = v[:100]
        elif f in ("desc", "description"):
            cat["description"] = "Open a support ticket." if v.lower() == "clear" else v[:100]
        elif f == "emoji":
            cat["emoji"] = None if v.lower() in ("clear", "none") else v
        elif f in ("category", "cat", "category_id"):
            cat["category_id"] = None if v.lower() in ("clear", "none") else v
        else:
            return await ctx.send("❌ Field must be `label`, `desc`, `emoji`, or `category`.")

        save_config(self.config)
        self.rebuild_view()
        await ctx.send(f"✅ Updated `{f}` for **{cat['label']}**. Re-send panel to refresh the menu.")

    @support_edit.command(name="addoption")
    @owner_only()
    async def add_option(self, ctx: commands.Context, *, spec: str):
        if len(self.config.get("categories", [])) >= 25:
            return await ctx.send("❌ Max 25 options reached.")
        parts = [p.strip() for p in spec.split("|")]
        if not parts[0]:
            return await ctx.send("❌ Provide at least a label.")
        self.config["categories"].append({
            "label": parts[0][:100],
            "description": parts[1][:100] if len(parts) > 1 and parts[1] else "Open a support ticket.",
            "emoji": parts[2] if len(parts) > 2 and parts[2] and parts[2].lower() != "none" else None,
            "category_id": parts[3] if len(parts) > 3 and parts[3] and parts[3].lower() != "none" else None,
            "alias": parts[4] if len(parts) > 4 and parts[4] and parts[4].lower() != "none" else "",
        })
        save_config(self.config)
        self.rebuild_view()
        await ctx.send(f"✅ Added **{parts[0]}**. Re-send panel to refresh the menu.")

    @support_edit.command(name="removeoption")
    @owner_only()
    async def remove_option(self, ctx: commands.Context, *, option: str):
        idx = self._find_category_index(option)
        if idx is None:
            return await ctx.send("❌ Option not found.")
        removed = self.config["categories"].pop(idx)
        save_config(self.config)
        self.rebuild_view()
        await ctx.send(f"🗑️ Removed **{removed['label']}**.")


async def setup(bot):
    await bot.add_cog(ModmailSupportPanel(bot))
