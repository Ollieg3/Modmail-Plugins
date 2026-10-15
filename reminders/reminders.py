import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
import discord
from discord.ext import commands, tasks

REMINDERS_PATH = "reminders.json"

# --- TIME PARSING HELPER ---
TIME_REGEX = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", re.IGNORECASE)

def parse_time_to_seconds(time_str: str) -> int:
    match = TIME_REGEX.match(time_str.strip())
    if not match or not any(match.groups()):
        return 0
    days, hours, minutes, seconds = (int(x) if x else 0 for x in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds

# --- SAFE JSON HANDLING ---
def load_reminders():
    if not os.path.exists(REMINDERS_PATH):
        save_reminders([])
        return []
    try:
        with open(REMINDERS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Reminders] Failed to load reminders: {e}")
        return []

def save_reminders(reminders):
    tmp_path = f"{REMINDERS_PATH}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(reminders, f, indent=4)
        os.replace(tmp_path, REMINDERS_PATH)
    except Exception as e:
        print(f"[Reminders] Error saving reminders: {e}")


class Reminders(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reminders = load_reminders()
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    # --- BACKGROUND WORKER LOOP ---
    @tasks.loop(seconds=30)
    async def check_reminders(self):
        now = datetime.now(timezone.utc).timestamp()
        due_reminders = []
        remaining_reminders = []

        for rem in self.reminders:
            if rem["timestamp"] <= now:
                due_reminders.append(rem)
            else:
                remaining_reminders.append(rem)

        if due_reminders:
            self.reminders = remaining_reminders
            save_reminders(self.reminders)

            for rem in due_reminders:
                try:
                    channel = self.bot.get_channel(rem["channel_id"])
                    if not channel:
                        try:
                            channel = await self.bot.fetch_channel(rem["channel_id"])
                        except Exception:
                            channel = None
                    
                    target_user_id = rem.get("target_user_id", rem["user_id"])
                    user = self.bot.get_user(target_user_id)
                    if not user:
                        try:
                            user = await self.bot.fetch_user(target_user_id)
                        except Exception:
                            user = None

                    mention = user.mention if user else f"<@ID:{target_user_id}>"

                    embed = discord.Embed(
                        title="⏰ Reminder Triggered",
                        description=f"{rem['message']}",
                        color=discord.Color.gold(),
                        timestamp=datetime.fromtimestamp(rem["timestamp"], tz=timezone.utc)
                    )
                    embed.set_footer(text=f"Requested by {rem['user_name']}")

                    if channel:
                        await channel.send(content=f"🔔 {mention}, here is a reminder for this ticket:", embed=embed)

                    if user:
                        try:
                            dm_embed = discord.Embed(
                                title="⏰ Reminder Alert (Ticket)",
                                description=f"You have a reminder from **{rem['user_name']}**:\n\n> {rem['message']}",
                                color=discord.Color.gold(),
                                timestamp=datetime.fromtimestamp(rem["timestamp"], tz=timezone.utc)
                            )
                            if channel:
                                dm_embed.add_field(name="Ticket Channel", value=channel.mention, inline=False)
                            dm_embed.set_footer(text="Support Centre Reminders")
                            
                            await user.send(embed=dm_embed)
                        except discord.Forbidden:
                            print(f"[Reminders] Could not DM user {target_user_id} (DMs closed).")

                except Exception as e:
                    print(f"[Reminders] Failed to deliver reminder {rem.get('id')}: {e}")

    @check_reminders.before_loop
    async def before_check_reminders(self):
        await self.bot.wait_until_ready()

    # --- COMMANDS ---
    @commands.command(name="remind", aliases=["reminder"])
    async def remind_cmd(self, ctx):
        """
        Sets a reminder for yourself or another user.
        Usage: -remind 30m Check back on logs
        Usage: -remind @User 1h Take over this ticket
        """
        args = ctx.message.content.split()[1:]

        if not args:
            return await ctx.send(
                "❌ **Usage:**\n"
                "• Remind yourself: `-remind <time> <message>` (e.g. `-remind 30m Check logs`)\n"
                "• Remind someone else: `-remind @user <time> <message>` (e.g. `-remind @Alex 1h Follow up`)"
            )

        target_user = ctx.author
        time_str = None
        message = None

        # Check if first argument is a user mention (<@123456789> or <@!123456789>)
        user_match = re.match(r"<@!?(\d+)>", args[0])

        if user_match:
            # Format: -remind @user <time> <message>
            if len(args) < 3:
                return await ctx.send("❌ **Usage:** `-remind @user <time> <message>`\n*Example:* `-remind @Alex 45m Check customer status`")
            
            target_user_id = int(user_match.group(1))
            target_user = ctx.guild.get_member(target_user_id) or await self.bot.fetch_user(target_user_id)
            time_str = args[1]
            message = " ".join(args[2:])
        else:
            # Format: -remind <time> <message>
            if len(args) < 2:
                return await ctx.send("❌ **Usage:** `-remind <time> <message>`\n*Example:* `-remind 45m Check customer status`")
            
            time_str = args[0]
            message = " ".join(args[1:])

        seconds = parse_time_to_seconds(time_str)
        if seconds <= 0:
            return await ctx.send("❌ Invalid time format! Use combinations of days/hours/minutes/seconds. *Examples:* `1h30m`, `45m`, `10s`.")

        if seconds > 30 * 86400:
            return await ctx.send("❌ Maximum reminder duration is 30 days.")

        target_timestamp = datetime.now(timezone.utc).timestamp() + seconds
        reminder_id = str(int(datetime.now(timezone.utc).timestamp() * 1000))[-6:]

        new_reminder = {
            "id": reminder_id,
            "user_id": ctx.author.id,
            "user_name": str(ctx.author),
            "target_user_id": target_user.id,
            "channel_id": ctx.channel.id,
            "message": message,
            "timestamp": target_timestamp
        }

        self.reminders.append(new_reminder)
        save_reminders(self.reminders)

        if target_user.id == ctx.author.id:
            await ctx.send(f"✅ Reminder set! I'll remind you in **{time_str}** for: *{message}* (ID: `{reminder_id}`)")
        else:
            await ctx.send(f"✅ Reminder set! I'll remind **{target_user.mention}** in **{time_str}** for: *{message}* (ID: `{reminder_id}`)")

    @commands.command(name="reminders", aliases=["listreminders"])
    async def list_reminders(self, ctx):
        """Lists active reminders set in this channel."""
        channel_reminders = [r for r in self.reminders if r["channel_id"] == ctx.channel.id]
        
        if not channel_reminders:
            return await ctx.send("📭 There are no active reminders set for this channel.")

        embed = discord.Embed(title="⏰ Active Reminders in this Channel", color=discord.Color.blue())
        for rem in channel_reminders:
            time_left = int(rem["timestamp"] - datetime.now(timezone.utc).timestamp())
            if time_left < 0:
                time_left = 0
            
            td = timedelta(seconds=time_left)
            target_name = "Self"
            if rem.get("target_user_id") and rem["target_user_id"] != rem["user_id"]:
                t_user = self.bot.get_user(rem["target_user_id"])
                target_name = str(t_user) if t_user else f"ID: {rem['target_user_id']}"

            embed.add_field(
                name=f"ID: `{rem['id']}` (Set by {rem['user_name']})",
                value=f"• **For:** {target_name}\n• **Message:** {rem['message']}\n• **Due in:** ~{td}",
                inline=False
            )

        await ctx.send(embed=embed)

    @commands.command(name="delremind", aliases=["cancelremind", "rmremind"])
    async def delete_reminder(self, ctx, reminder_id: str):
        """Cancels an active reminder using its ID."""
        rem = next((r for r in self.reminders if r["id"] == reminder_id), None)
        if not rem:
            return await ctx.send(f"❌ Could not find an active reminder with ID `{reminder_id}`.")

        self.reminders = [r for r in self.reminders if r["id"] != reminder_id]
        save_reminders(self.reminders)

        await ctx.send(f"🗑️ Successfully cancelled reminder ID `{reminder_id}`.")


async def setup(bot):
    await bot.add_cog(Reminders(bot))
