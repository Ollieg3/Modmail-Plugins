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
            description=f"**Status:** {status}\n\nActively monitoring channel creation to lock out ticket authors instantly.",
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

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        """Fires the absolute millisecond any text channel is created in the server."""
        if not self.enabled:
            return

        if not isinstance(channel, discord.TextChannel):
            return

        # Check if this channel looks like a Modmail ticket (e.g. checks topic for a User ID)
        await asyncio.sleep(0.5) # Brief pause for topic/metadata to populate
        try:
            topic = channel.topic or ""
            # Modmail bots typically store the user ID in the channel topic
            if "1265" in topic or channel.name.startswith("ticket-") or len(topic) >= 17:
                # Extract potential user ID from topic if numerical
                potential_id = ''.join(filter(str.isdigit, topic))
                
                user_id = None
                if len(potential_id) >= 17:
                    user_id = int(potential_id)
                else:
                    # Fallback: Check if channel name matches a member name
                    for member in channel.guild.members:
                        if member.name.lower() in channel.name.lower():
                            user_id = member.id
                            break

                if user_id:
                    member = channel.guild.get_member(user_id) or await channel.guild.fetch_member(user_id)
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
                            reason="Instant ticket concealment from creator."
                        )
                        print(f"[HideCreator] Instantly locked out user {member} from newly created channel #{channel.name}")
        except Exception as e:
            print(f"[HideCreator] Error on channel create check: {e}")

async def setup(bot):
    await bot.add_cog(HideTicketCreator(bot))
