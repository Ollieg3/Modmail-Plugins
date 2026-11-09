import asyncio
import discord
from discord.ext import commands

class HideTicketCreator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled = True
        # Track active tickets and their creators to re-enforce if synced/moved
        self.hidden_tickets = {} # {channel_id: user_id}

    @commands.group(name="hidecreator", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def hidecreator_cmd(self, ctx):
        """Check the status of the ticket creator hider."""
        status = "🟢 Enabled" if self.enabled else "🔴 Disabled"
        embed = discord.Embed(
            title="🔒 Ticket Creator Hider Settings",
            description=f"**Status:** {status}\n\nWhen enabled, any newly created ticket will automatically deny read/view/send permissions to the ticket author and persist through category moves.",
            color=discord.Color.blurple()
        )
        await ctx.send(embed=embed)

    @hidecreator_cmd.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def enable_hider(self, ctx):
        """Enable automatic ticket creator hiding."""
        self.enabled = True
        await ctx.send("✅ **Ticket Creator Hider has been enabled.**")

    @hidecreator_cmd.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def disable_hider(self, ctx):
        """Disable automatic ticket creator hiding."""
        self.enabled = False
        await ctx.send("🛑 **Ticket Creator Hider has been disabled.**")

    async def apply_hide(self, channel, user_id):
        """Helper to safely enforce the hide overwrite."""
        try:
            member = channel.guild.get_member(user_id)
            if not member:
                member = await channel.guild.fetch_member(user_id)

            if member and not member.guild_permissions.administrator:
                overwrite = discord.PermissionOverwrite(
                    view_channel=False,
                    read_messages=False,
                    send_messages=False,
                    read_message_history=False
                )
                await channel.set_permissions(
                    member,
                    overwrite=overwrite,
                    reason="Support server policy: Persistent ticket concealment from creator."
                )
        except Exception as e:
            print(f"[HideCreator] Error applying persistent hide: {e}")

    @commands.Cog.listener()
    async def on_thread_ready(self, thread, account, issue, logs):
        """Triggered when a ticket/modmail thread is initialized."""
        if not self.enabled:
            return

        try:
            channel = getattr(thread, "channel", None)
            if not channel or not isinstance(channel, discord.TextChannel):
                return

            await asyncio.sleep(1.0)

            if account and isinstance(account, (discord.User, discord.Member)):
                self.hidden_tickets[channel.id] = account.id
                await self.apply_hide(channel, account.id)
                print(f"[HideCreator] Successfully locked ticket creator {account} from #{channel.name}")
        except Exception as e:
            print(f"[HideCreator] on_thread_ready error: {e}")

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        """Fires whenever a channel is updated (such as syncing permissions or changing categories)."""
        if not self.enabled:
            return
            
        if not isinstance(after, discord.TextChannel):
            return

        # Check if this channel is one of our tracked hidden tickets
        if after.id in self.hidden_tickets:
            user_id = self.hidden_tickets[after.id]
            
            # Check if the user overwrite was wiped or changed (e.g. via sync)
            overwrite = after.overwrites_for(after.guild.get_member(user_id) or discord.Object(id=user_id))
            
            # If view_channel is not explicitly False, sync likely wiped it. Re-apply immediately.
            if overwrite.view_channel is not False:
                await asyncio.sleep(0.5) # Brief pause to let sync finish completing
                await self.apply_hide(after, user_id)
                print(f"[HideCreator] Re-enforced permission block on #{after.name} after category sync/move.")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        """Clean up memory when a ticket channel is closed/deleted."""
        if channel.id in self.hidden_tickets:
            del self.hidden_tickets[channel.id]


async def setup(bot):
    await bot.add_cog(HideTicketCreator(bot))
