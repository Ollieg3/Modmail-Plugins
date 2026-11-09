import asyncio
import discord
from discord.ext import commands

class HideTicketCreator(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.enabled = True

    @commands.Cog.listener()
    async def on_thread_ready(self, thread, account, issue, logs):
        if not self.enabled:
            return

        try:
            channel = getattr(thread, "channel", None)
            if not channel or not isinstance(channel, discord.TextChannel):
                return

            await asyncio.sleep(1.0)

            if account and isinstance(account, (discord.User, discord.Member)):
                # If they are a member in the guild, pull their Member object
                member = channel.guild.get_member(account.id) or account

                # Skip hiding if they are a server Administrator (Discord won't hide anyway)
                if isinstance(member, discord.Member) and member.guild_permissions.administrator:
                    print(f"[HideCreator] Skipped {member} - User has Administrator permissions.")
                    return

                # Strict overwrite stripping view, history, and message rights
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
                print(f"[HideCreator] Hard-blocked user {member} from #{channel.name}")
        except Exception as e:
            print(f"[HideCreator] Error hiding ticket creator: {e}")

async def setup(bot):
    await bot.add_cog(HideTicketCreator(bot))
