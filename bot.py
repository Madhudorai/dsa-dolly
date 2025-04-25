
import discord
from discord.ext import commands
import json
import os
import datetime
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
from keep_alive import keep_alive
from leetcode import get_questions

# Load token
load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')

# Setup bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

SCORES_FILE = "scores.json"
DAILY_FILE = "daily_log.json"
USER_ACTIVITY_FILE = "user_activity.json"

def load_json(path): return json.load(open(path)) if os.path.exists(path) else {}
def save_json(path, data): json.dump(data, open(path, "w"), indent=4)

def save_scores(scores): save_json(SCORES_FILE, scores)
def load_scores(): return load_json(SCORES_FILE)

# === Question Scheduling ===
def generate_daily_questions():
    today = datetime.date.today().isoformat()
    daily = load_json(DAILY_FILE)

    if today not in daily:
        qset = get_questions()
        daily[today] = {str(i+1): q for i, q in enumerate(qset)}
        save_json(DAILY_FILE, daily)
        print(f"Generated daily questions for {today}")

# Run once at start in case bot started after 12 AM
generate_daily_questions()

# Schedule to run at 12 AM every day

# === Idle Penalty System ===
def apply_idle_penalties():
    today = datetime.date.today().isoformat()
    activity = load_json(USER_ACTIVITY_FILE)
    scores = load_json(SCORES_FILE)

    for user, data in activity.items():
        if data.get("last_done") != today:
            scores[user] = max(0, scores.get(user, 0) - 2)

    save_json(SCORES_FILE, scores)
    print("Idle penalties applied.")

scheduler = BackgroundScheduler(timezone=pytz.timezone('Asia/Kolkata'))
scheduler.add_job(generate_daily_questions, 'cron', hour=0, minute=0)
scheduler.add_job(apply_idle_penalties, 'cron', hour=23, minute=59)
scheduler.start()

scores = load_scores()

@bot.event
async def on_ready():
    print(f"Bot is ready! Logged in as {bot.user}")

@bot.command()
async def daily(ctx):
    today = datetime.date.today().isoformat()
    daily = load_json(DAILY_FILE)

    if today not in daily:
        await ctx.send("Questions not generated yet for today.")
        return

    qset = daily[today]
    await ctx.send(f"Today's DSA Challenge:\n1. <{qset['1']}>\n2. <{qset['2']}>\n3. <{qset['3']}>")

@bot.command()
async def done(ctx, qnum: str):
    user = str(ctx.author)
    today = datetime.date.today().isoformat()
    daily = load_json(DAILY_FILE)
    activity = load_json(USER_ACTIVITY_FILE)

    if today not in daily or qnum not in daily[today]:
        await ctx.send("Invalid question number or daily not yet posted.")
        return

    if user not in activity:
        activity[user] = {"last_done": today, "done_today": []}

    if activity[user]["last_done"] != today:
        activity[user]["last_done"] = today
        activity[user]["done_today"] = []

    if qnum in activity[user]["done_today"]:
        await ctx.send(f"You already completed Q{qnum} today!")
        return

    point_map = {"1": 10, "2": 10, "3": 10}
    points = point_map.get(qnum, 0)

    scores[user] = scores.get(user, 0) + points
    activity[user]["done_today"].append(qnum)
    save_scores(scores)
    save_json(USER_ACTIVITY_FILE, activity)

    await ctx.send(f"{ctx.author.mention} completed Q{qnum} (+{points} pts) — Total: {scores[user]}")

@bot.command()
async def leaderboard(ctx):
    if not scores:
        await ctx.send("No scores yet!")
        return

    sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
    board = "\n".join(f"{u}: {s} pts" for u, s in sorted_scores)
    await ctx.send(f"Leaderboard:\n{board}")


@bot.command(name="info", help="Show bot command guide and scoring rules")
async def info(ctx):
    message = (
        "** DSAdolly – daily DSA practice overseeing queen**\n\n"
        "**🗓️ !daily** – Get today's 3 randomly chosen LeetCode questions\n\n"
        "**✅ !done 1 / !done 2 / !done 3 – Mark question 1/2/3 as completed (each = +10 pts)\n\n🏆 **!leaderboard** – View everyone's score\n\n"
        "_⏱️ -2 pts if you skip a day without solving_\n"
        "_Questions reset at 12:00 AM IST every day_"
    )
    await ctx.send(message)

keep_alive()
bot.run(TOKEN)
