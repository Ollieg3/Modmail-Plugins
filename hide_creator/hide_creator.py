import asyncio
import discord
from discord.ext import commands

class HideTicketCreator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled = True

    @commands.Cog.listener()
    async def on_thread_ready(self, thread, account, issue, logs):
        """
        Triggered when a Modmail/ticket thread is fully initialized.
        Automatically applies a channel overwrite to hide the ticket author.
        """
        if not self.enabled:
            return

        try:
            channel = getattr(thread, "channel", None)
            if not channel or not isinstance(channel, discord.TextChannel):
                return

            # Give Discord a split second to finish channel setup/syncing
            await asyncio.sleep(0.5)

            # Ensure we have the user object for the ticket creator
            if account and isinstance(account, (discord.User, discord.Member)):
                # Explicit channel override denies viewing/reading, overriding role/category perms
                await channel.set_permissions(
                    account,
                    read_messages=False,
                    view_channel=False,
                    reason="Support server policy: Automatic ticket concealment from creator."
                )
                print(f"[HideCreator] Successfully hid user {account} ({account.id}) from ticket channel #{channel.name}")
        except Exception as e:
            print(f"[HideCreator] Error hiding ticket creator: {e}")

    @commands.group(name="hidecreator", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def hidecreator_cmd(self, ctx):
        """Check the status of the ticket creator hider."""
        status = "🟢 Enabled" if self.enabled else "🔴 Disabled"
        embed = discord.Embed(
            title="🔒 Ticket Creator Hider Settings",
            description=f"**Status:** {status}\n\nWhen enabled, any newly created ticket will automatically deny read/view permissions to the ticket author.",
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


async def setup(bot):
    await bot.add_cog(HideTicketCreator(bot))
