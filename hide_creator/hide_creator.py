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
        """Check the status of the ticket creator hider."""
        status = "🟢 Enabled" if self.enabled else "🔴 Disabled"
        embed = discord.Embed(
            title="🔒 Ticket Creator Hider Settings",
            description=f"**Status:** {status}\n\nWhen enabled, any newly created ticket will automatically deny read/view/send permissions to the ticket author.",
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

    @commands.Cog.listener()
    async def on_thread_ready(self, thread, account, issue, logs):
        """
        Triggered when a Modmail/ticket thread is fully initialized.
        Automatically applies a strict channel overwrite to hide the ticket author.
        """
        if not self.enabled:
            return

        try:
            channel = getattr(thread, "channel", None)
            if not channel or not isinstance(channel, discord.TextChannel):
                return

            # Short delay to allow Modmail thread creation to finalize
            await asyncio.sleep(1.0)

            if account and isinstance(account, (discord.User, discord.Member)):
                # Fetch member instance from the guild
                member = channel.guild.get_member(account.id) or account

                # Skip if the ticket author is a Server Administrator
                # (Discord permanently lets Admins see all channels regardless of overwrites)
                if isinstance(member, discord.Member) and member.guild_permissions.administrator:
                    print(f"[HideCreator] Skipped hiding {member} because they have Administrator permissions.")
                    return

                # Strict permission overwrite blocking all access to the channel
                overwrite = discord.PermissionOverwrite(
                    view_channel=False,
                    read_messages=False,
                    send_messages=False,
                    read_message_history=False
                )

                await channel.set_permissions(
                    member,
                    overwrite=overwrite,
                    reason="Support server policy: Automatic ticket concealment from creator."
                )
                print(f"[HideCreator] Successfully hid ticket author {member} from #{channel.name}")
        except Exception as e:
            print(f"[HideCreator] Error hiding ticket creator: {e}")


async def setup(bot):
    await bot.add_cog(HideTicketCreator(bot))
