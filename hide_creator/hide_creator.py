import asyncio
import discord
from discord.ext import commands

class HideTicketCreator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled = True

    @commands.group(name="hidecreator", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def hidecreator_cmd(self, ctx):
        status = "🟢 Enabled" if self.enabled else "🔴 Disabled"
        embed = discord.Embed(
            title="🔒 Ticket Creator Hider Settings",
            description=f"**Status:** {status}\n\nActively locking out ticket authors and re-enforcing blocks automatically on category moves and permission syncs.",
            color=discord.Color.blurple()
        )
        await ctx.send(embed=embed)

    @hidecreator_cmd.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def enable_hider(self, ctx):
        self.enabled = True
        await ctx.send("✅ **Ticket Creator Hider has been enabled.**")

    @hidecreator_cmd.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def disable_hider(self, ctx):
        self.enabled = False
        await ctx.send("🛑 **Ticket Creator Hider has been disabled.**")

    async def enforce_hide(self, channel):
        """Extracts the ticket creator ID from the channel topic and enforces the permission block."""
        try:
            topic = channel.topic or ""
            potential_id = ''.join(filter(str.isdigit, topic))
            
            user_id = None
            if len(potential_id) >= 17:
                user_id = int(potential_id)
            else:
                # Fallback: match channel name against guild members
                for member in channel.guild.members:
                    if member.name.lower() in channel.name.lower():
                        user_id = member.id
                        break

            if user_id:
                member = channel.guild.get_member(user_id) or await channel.guild.fetch_member(user_id)
                if member and not member.guild_permissions.administrator:
                    overwrite = channel.overwrites_for(member)
                    # If the user can view the channel (e.g. wiped by category sync/move), lock it down again
                    if overwrite.view_channel is not False:
                        strict_overwrite = discord.PermissionOverwrite(
                            view_channel=False,
                            read_messages=False,
                            send_messages=False,
                            read_message_history=False
                        )
                        await channel.set_permissions(
                            member,
                            overwrite=strict_overwrite,
                            reason="Persistent enforcement: Re-concealing ticket creator after category move/sync."
                        )
                        print(f"[HideCreator] Re-enforced permission block on #{channel.name} for {member}")
        except Exception as e:
            print(f"[HideCreator] Error enforcing hide: {e}")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        """Applies lock the moment the channel is created."""
        if not self.enabled or not isinstance(channel, discord.TextChannel):
            return
        await asyncio.sleep(0.5)
        await self.enforce_hide(channel)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        """Catches category moves, permission syncs, or any updates and re-applies the block instantly."""
        if not self.enabled or not isinstance(after, discord.TextChannel):
            return
        
        # Triggered if category changes or channel overwrites are modified/synced
        if before.category_id != after.category_id or before.overwrites != after.overwrites:
            await asyncio.sleep(0.3)
            await self.enforce_hide(after)

async def setup(bot):
    await bot.add_cog(HideTicketCreator(bot))
