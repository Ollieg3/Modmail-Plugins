import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import discord
from discord.ext import commands, tasks

REMINDERS_PATH = "reminders.json"
UK_TZ = ZoneInfo("Europe/London")

WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6
}

TIME_REGEX = re.compile(r"^(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$", re.IGNORECASE)

def parse_relative_time(time_str: str) -> int:
    match = TIME_REGEX.match(time_str.strip())
    if not match or not any(match.groups()):
        return 0
    days, hours, minutes, seconds = (int(x) if x else 0 for x in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds

def parse_time_of_day(time_token: str):
    """
    Parses various time formats:
    - 12-hour: 11am, 3pm, 11:30am, 3:15pm
    - 24-hour: 11:00, 15:00, 23:30
    - Standalone numbers: 11, 3, 15
    """
    token = time_token.lower().strip()
    
    # 1. Match 12-hour format with AM/PM (11am, 3pm, 11:30am, 3:15pm)
    match_12 = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", token)
    if match_12:
        hour = int(match_12.group(1))
        minute = int(match_12.group(2)) if match_12.group(2) else 0
        meridiem = match_12.group(3)

        if hour < 1 or hour > 12:
            return None

        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0

        if 0 <= minute <= 59:
            return hour, minute

    # 2. Match 24-hour format with colon (11:00, 15:00, 23:30, 09:15)
    match_24 = re.match(r"^(\d{1,2}):(\d{2})$", token)
    if match_24:
        hour = int(match_24.group(1))
        minute = int(match_24.group(2))
        
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute

    # 3. Match standalone number for hour (e.g. 11, 3, 15)
    match_num = re.match(r"^(\d{1,2})$", token)
    if match_num:
        hour = int(match_num.group(1))
        # If hour is between 1 and 7, assume PM (e.g. "tomorrow 3" -> 3 PM)
        if 1 <= hour <= 7:
            hour += 12
        if 0 <= hour <= 23:
            return hour, 0

    return None

def parse_datetime_query(args):
    """
    Parses arguments into (target_datetime_utc, consumed_token_count).
    Supports: today, tomorrow, tmr, tmw, Tuesday, next Tuesday, etc.
    """
    if not args:
        return None, 0

    now_uk = datetime.now(UK_TZ)

    # 1. Standard relative durations (30m, 1h, 1d)
    rel_seconds = parse_relative_time(args[0])
    if rel_seconds > 0:
        return datetime.now(timezone.utc) + timedelta(seconds=rel_seconds), 1

    day_token = args[0].lower()

    # Handle "next <weekday>"
    if day_token == "next" and len(args) > 1 and args[1].lower() in WEEKDAYS:
        target_weekday = WEEKDAYS[args[1].lower()]
        days_ahead = (target_weekday - now_uk.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        
        target_date = now_uk.date() + timedelta(days=days_ahead)
        
        if len(args) > 2:
            parsed_time = parse_time_of_day(args[2])
            if parsed_time:
                target_dt_naive = datetime.combine(target_date, datetime.min.time()).replace(hour=parsed_time[0], minute=parsed_time[1])
                return target_dt_naive.replace(tzinfo=UK_TZ).astimezone(timezone.utc), 3
        
        target_dt_naive = datetime.combine(target_date, datetime.min.time()).replace(hour=9, minute=0)
        return target_dt_naive.replace(tzinfo=UK_TZ).astimezone(timezone.utc), 2

    # Handle "today", "tomorrow", or single "<weekday>"
    target_date = None

    if day_token == "today":
        target_date = now_uk.date()
    elif day_token in ("tomorrow", "tmr", "tmw"):
        target_date = now_uk.date() + timedelta(days=1)
    elif day_token in WEEKDAYS:
        target_weekday = WEEKDAYS[day_token]
        days_ahead = (target_weekday - now_uk.weekday()) % 7
        if days_ahead <= 0:
            days_ahead += 7
        target_date = now_uk.date() + timedelta(days=days_ahead)

    if target_date:
        if len(args) > 1:
            parsed_time = parse_time_of_day(args[1])
            if parsed_time:
                target_dt_naive = datetime.combine(target_date, datetime.min.time()).replace(hour=parsed_time[0], minute=parsed_time[1])
                return target_dt_naive.replace(tzinfo=UK_TZ).astimezone(timezone.utc), 2
        
        # Default to 9:00 AM if no time component was provided
        target_dt_naive = datetime.combine(target_date, datetime.min.time()).replace(hour=9, minute=0)
        return target_dt_naive.replace(tzinfo=UK_TZ).astimezone(timezone.utc), 1

    return None, 0


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
        Sets a reminder for yourself or another staff member using UK time.
        """
        args = ctx.message.content.split()[1:]

        if not args:
            return await ctx.send(
                "❌ **Usage:**\n"
                "• `-remind <time> <message>`\n"
                "• `-remind @user <time> <message>`\n"
                "*Examples:* `30m`, `today 11am`, `today 15:00`, `tomorrow 11am`, `Tuesday 16:30`"
            )

        target_user = ctx.author

        user_match = re.match(r"<@!?(\d+)>", args[0])
        if user_match:
            target_user_id = int(user_match.group(1))
            target_user = ctx.guild.get_member(target_user_id) or await self.bot.fetch_user(target_user_id)
            args = args[1:]

        if not args:
            return await ctx.send("❌ Please specify a time and message.")

        target_utc_dt, consumed_tokens = parse_datetime_query(args)

        if not target_utc_dt or consumed_tokens == 0:
            return await ctx.send("❌ Could not understand that time format. Try formats like `30m`, `today 11am`, `today 15:00`, `tomorrow 3pm`, or `Tuesday 16:00`.")

        message = " ".join(args[consumed_tokens:])
        if not message:
            return await ctx.send("❌ Please include a reminder message.")

        now_utc = datetime.now(timezone.utc)
        if target_utc_dt <= now_utc:
            return await ctx.send("❌ That time is in the past! Please specify a future time.")

        if (target_utc_dt - now_utc).total_seconds() > (30 * 86400):
            return await ctx.send("❌ Maximum reminder duration is 30 days.")

        reminder_id = str(int(now_utc.timestamp() * 1000))[-6:]

        new_reminder = {
            "id": reminder_id,
            "user_id": ctx.author.id,
            "user_name": str(ctx.author),
            "target_user_id": target_user.id,
            "channel_id": ctx.channel.id,
            "message": message,
            "timestamp": target_utc_dt.timestamp()
        }

        self.reminders.append(new_reminder)
        save_reminders(self.reminders)

        uk_display_dt = target_utc_dt.astimezone(UK_TZ)
        formatted_time = uk_display_dt.strftime("%b %d at %H:%M %Z")

        if target_user.id == ctx.author.id:
            await ctx.send(f"✅ Reminder set for **{formatted_time}**! (*{message}*) (ID: `{reminder_id}`)")
        else:
            await ctx.send(f"✅ Reminder set for **{target_user.mention}** on **{formatted_time}**! (*{message}*) (ID: `{reminder_id}`)")

    @commands.command(name="reminders", aliases=["listreminders"])
    async def list_reminders(self, ctx):
        """Lists active reminders set in this channel."""
        channel_reminders = [r for r in self.reminders if r["channel_id"] == ctx.channel.id]
        
        if not channel_reminders:
            return await ctx.send("📭 There are no active reminders set for this channel.")

        embed = discord.Embed(title="⏰ Active Reminders in this Channel", color=discord.Color.blue())
        for rem in channel_reminders:
            due_dt_utc = datetime.fromtimestamp(rem["timestamp"], tz=timezone.utc)
            due_dt_uk = due_dt_utc.astimezone(UK_TZ)
            time_str = due_dt_uk.strftime("%b %d, %H:%M %Z")
            
            target_name = "Self"
            if rem.get("target_user_id") and rem["target_user_id"] != rem["user_id"]:
                t_user = self.bot.get_user(rem["target_user_id"])
                target_name = str(t_user) if t_user else f"ID: {rem['target_user_id']}"

            embed.add_field(
                name=f"ID: `{rem['id']}` (Set by {rem['user_name']})",
                value=f"• **For:** {target_name}\n• **Message:** {rem['message']}\n• **Due:** {time_str}",
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
