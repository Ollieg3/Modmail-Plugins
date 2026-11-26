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

        # Discord requires at least 1 option on a Select component if rendered
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
                    color=discord.Color.blurple(),
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
