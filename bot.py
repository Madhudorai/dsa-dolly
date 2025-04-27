import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import pandas as pd
import random
import schedule
import time
import asyncio
from collections import defaultdict
import json

load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
KAGGLE_DATASET_PATH = 'leetcode_problems.csv'
LEADERBOARD_FILE = 'leaderboard.json'
SUBMISSIONS_FILE = 'submissions.json'
DAILY_PROBLEMS_FILE = 'daily_problems.json'
DAILY_CONFIGS_FILE = 'daily_configs.json'
HISTORICAL_PROBLEMS_FILE = 'historical_problems.json'

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

problems_df = None
daily_configs = {}
leaderboard = defaultdict(int)
submissions = defaultdict(lambda: defaultdict(bool))
daily_problems = defaultdict(list)
historical_problems = set()

async def load_data():
    global leaderboard, submissions, daily_problems, daily_configs, historical_problems
    try:
        with open(LEADERBOARD_FILE, 'r') as f:
            leaderboard = defaultdict(int, json.load(f))
        print("Leaderboard data loaded.")
    except FileNotFoundError:
        print("Leaderboard file not found, starting with empty leaderboard.")
    except json.JSONDecodeError:
        print("Error decoding leaderboard JSON, starting with empty leaderboard.")

    try:
        with open(SUBMISSIONS_FILE, 'r') as f:
            submissions = defaultdict(lambda: defaultdict(bool), json.load(f))
        print("Submissions data loaded.")
    except FileNotFoundError:
        print("Submissions file not found, starting with empty submissions.")
    except json.JSONDecodeError:
        print("Error decoding submissions JSON, starting with empty submissions.")

    try:
        with open(DAILY_PROBLEMS_FILE, 'r') as f:
            loaded_daily_problems = json.load(f)
            daily_problems = defaultdict(list, {int(k): v for k, v in loaded_daily_problems.items()})
        print("Daily problems data loaded.")
    except FileNotFoundError:
        print("Daily problems file not found, starting with empty daily problems.")
    except json.JSONDecodeError:
        print("Error decoding daily problems JSON, starting with empty daily problems.")

    try:
        with open(DAILY_CONFIGS_FILE, 'r') as f:
            daily_configs = {int(k): v for k, v in json.load(f).items()}
        print("Daily configurations loaded.")
    except FileNotFoundError:
        print("Daily configurations file not found, starting with empty configurations.")
    except json.JSONDecodeError:
        print("Error decoding daily configurations JSON, starting with empty configurations.")

    try:
        with open(HISTORICAL_PROBLEMS_FILE, 'r') as f:
            historical_problems = set(json.load(f))
        print("Historical problems data loaded.")
    except FileNotFoundError:
        print("Historical problems file not found, starting with empty historical problems.")
    except json.JSONDecodeError:
        print("Error decoding historical problems JSON, starting with empty historical problems.")

    print(f"Loaded - Leaderboard: {leaderboard}, Submissions: {submissions}, Daily Problems: {daily_problems}, Daily Configs: {daily_configs}, Historical Problems: {historical_problems}")

async def save_leaderboard():
    with open(LEADERBOARD_FILE, 'w') as f:
        json.dump(dict(leaderboard), f)

async def save_submissions():
    with open(SUBMISSIONS_FILE, 'w') as f:
        json.dump({user_id: dict(subs) for user_id, subs in submissions.items()}, f)

async def save_daily_problems():
    with open(DAILY_PROBLEMS_FILE, 'w') as f:
        json.dump(dict(daily_problems), f)

async def save_daily_configs():
    with open(DAILY_CONFIGS_FILE, 'w') as f:
        json.dump(daily_configs, f)

async def save_historical_problems():
    with open(HISTORICAL_PROBLEMS_FILE, 'w') as f:
        json.dump(list(historical_problems), f)

@bot.event
async def on_ready():
    global problems_df
    await load_data()
    try:
        problems_df = pd.read_csv(KAGGLE_DATASET_PATH)
        print(f'Loaded {len(problems_df)} problems from the dataset.')
        print("Column Names:", problems_df.columns.tolist())
    except FileNotFoundError:
        print(f"Error: Dataset file not found at {KAGGLE_DATASET_PATH}")
    except Exception as e:
        print(f"Error loading dataset: {e}")

    schedule.every().day.at("10:00").do(lambda: asyncio.run(send_daily_problems()))

    async def scheduler_loop():
        while True:
            schedule.run_pending()
            await asyncio.sleep(1)

    bot.loop.create_task(scheduler_loop())

async def _send_problems(channel, num_questions, difficulty, topics):
    global problems_df, daily_problems, historical_problems

    if problems_df is None:
        await channel.send("Problem dataset not loaded yet.")
        return

    filtered_problems = problems_df[problems_df['difficulty'].isin(difficulty)]

    if topics:
        filtered_problems = filtered_problems[
            filtered_problems['related_topics'].apply(
                lambda x: any(topic.lower() in x.lower().split(',') for topic in topics) if pd.notna(x) else False
            )
        ]

    # Filter out historical problems
    available_problems = filtered_problems[~filtered_problems['title'].isin(historical_problems)]

    if available_problems.empty:
        await channel.send("No new problems found matching the current configuration.")
        return

    if len(available_problems) < num_questions:
        selected_problems = available_problems.sample(len(available_problems))
    else:
        selected_problems = available_problems.sample(num_questions)

    new_problems = [row['title'] for _, row in selected_problems.iterrows()]
    daily_problems[channel.guild.id] = new_problems  # Replace existing problems
    historical_problems.update(new_problems)

    await save_daily_problems()
    await save_historical_problems()

    embed = discord.Embed(title="Today's LeetCode Challenge Set!", color=discord.Color.blue())
    for title in daily_problems[channel.guild.id]:
        url_row = problems_df[problems_df['title'] == title]
        if not url_row.empty:
            problem_url = url_row.iloc[0]['url']
            embed.add_field(name=title, value=f"[Solve it here]({problem_url})", inline=False)

    await channel.send(embed=embed)

async def show_today_problems(channel):
    global problems_df, daily_problems

    print(f"Guild ID in show_today_problems: {channel.guild.id}")
    print(f"Current daily_problems: {daily_problems}")

    today_sent_problems = daily_problems.get(channel.guild.id, [])

    print(f"Today's sent problems for guild {channel.guild.id}: {today_sent_problems}")

    if not today_sent_problems:
        await channel.send("No problems have been sent yet for today.")
        return

    embed = discord.Embed(title="Today's LeetCode Challenge Set!", color=discord.Color.blue())
    for title in today_sent_problems:
        url_row = problems_df[problems_df['title'] == title]
        if not url_row.empty:
            problem_url = url_row.iloc[0]['url']
            embed.add_field(name=title, value=f"[Solve it here]({problem_url})", inline=False)
    await channel.send(embed=embed)

async def send_daily_problems():
    for guild_id, config in daily_configs.items():
        num_questions = config.get('num_questions', 1)
        difficulty = config.get('difficulty', ['Easy'])
        topics = config.get('topics', [])
        channel_id = config.get('channel_id')
        if not channel_id:
            continue
        channel = bot.get_channel(channel_id)
        await _send_problems(channel, num_questions, difficulty, topics)

@bot.command(name='submit', help='Submit your solution for a given problem: !submit <problem_title>')
async def submit(ctx, *, problem_title: str):
    global leaderboard, submissions, daily_problems
    user_id = ctx.author.id
    problem_lower = problem_title.lower()

    today_sent_problems = daily_problems.get(ctx.guild.id, [])
    if not any(problem_lower == p.lower() for p in today_sent_problems):
        await ctx.send(f"'{problem_title}' was not part of today's challenge. Only today's problems are allowed!")
        return

    found = False
    for index, row in problems_df.iterrows():
        if row['title'].lower() == problem_lower:
            found = True
            difficulty = row['difficulty'] if 'difficulty' in row else 'Easy'

            point_map = {
                "Easy": 10,
                "Medium": 20,
                "Hard": 30
            }
            points = point_map.get(difficulty, 10)

            if not submissions[user_id][row['title']]:
                submissions[user_id][row['title']] = True
                leaderboard[user_id] += points
                await save_leaderboard()
                await save_submissions()
                await ctx.send(f"{ctx.author.mention} submitted '{row['title']}' ({difficulty}) — +{points} points! Total: {leaderboard[user_id]}.")
            else:
                await ctx.send(f"{ctx.author.mention}, you already submitted '{row['title']}' today.")
            break

    if not found:
        await ctx.send(f"Problem with title '{problem_title}' not found in dataset.")

@bot.command(name='delete_today', help='Delete today\'s sent problems and reset submissions.')
async def delete_today(ctx):
    global daily_problems

    if ctx.guild.id in daily_problems:
        del daily_problems[ctx.guild.id]
        await save_daily_problems()
        for user_subs in submissions.values():
            for problem in list(user_subs.keys()):
                if problem in daily_problems.get(ctx.guild.id, []):
                    del user_subs[problem]
        await save_submissions()
        await ctx.send("Today's problems have been deleted! Submissions for today's problems are also reset.")
    else:
        await ctx.send("No problems were set for today yet.")

@bot.command(name='leaderboard', help='View the LeetCode leaderboard.')
async def leaderboard_cmd(ctx):
    if not leaderboard:
        await ctx.send("The leaderboard is currently empty.")
        return
    sorted_leaderboard = sorted(leaderboard.items(), key=lambda item: item[1], reverse=True)
    embed = discord.Embed(title="LeetCode Leaderboard", color=discord.Color.gold())
    for rank, (user_id, score) in enumerate(sorted_leaderboard, 1):
        user = await bot.fetch_user(user_id)
        embed.add_field(name=f"#{rank} {user.name}", value=f"Score: {score}", inline=False)
    await ctx.send(embed=embed)

@bot.command(name='commands', help='Shows information about the bot\'s commands.')
async def commands_cmd(ctx):
    embed = discord.Embed(title="LeetCode Bot Commands", description="Here's a list of available commands:", color=discord.Color.green())
    for command in bot.commands:
        embed.add_field(name=f"!{command.name}", value=command.help, inline=False)
    await ctx.send(embed=embed)

@bot.command(name='show_now', help='Resend today\'s already picked LeetCode problems.')
async def show_now(ctx):
    await show_today_problems(ctx.channel)

@bot.command(name='set_daily_config', help='Set the daily problem configuration: !set_daily_config <number> <difficulty> [topics]')
async def set_daily_config(ctx, num_questions: int, difficulty: str, *topics):
    global daily_configs, daily_problems, historical_problems

    difficulty_list = [d.strip().capitalize() for d in difficulty.split(',')]
    valid_difficulties = problems_df['difficulty'].unique() if problems_df is not None else ["Easy", "Medium", "Hard"]

    for diff in difficulty_list:
        if diff not in valid_difficulties:
            await ctx.send(f"Invalid difficulty: '{diff}'. Please choose from {', '.join(valid_difficulties)}.")
            return

    all_topics = set()
    if 'related_topics' in problems_df.columns:
        topics_series = problems_df['related_topics'].dropna()
        for entry in topics_series:
            these_topics = [t.strip().lower() for t in entry.split(',')]
            all_topics.update(these_topics)

    invalid_topics = []
    if topics:
        for topic in topics:
            if topic.lower() not in all_topics and topic.lower() != "all":
                invalid_topics.append(topic)

    if invalid_topics:
        sorted_topics = sorted(all_topics)
        await ctx.send(f"Invalid topics: {', '.join(invalid_topics)}.\nHere are the valid topics:\n" + ", ".join(sorted_topics))
        return

    final_topics = [] if ("all" in [t.lower() for t in topics]) else list(topics)

    guild_id = ctx.guild.id
    # Remove previously selected daily problems from historical problems when config is reset
    if guild_id in daily_problems:
        problems_to_remove = daily_problems[guild_id]
        historical_problems.difference_update(problems_to_remove)
        del daily_problems[guild_id]
        await save_daily_problems()
        await save_historical_problems()

    daily_configs[guild_id] = {
        'num_questions': num_questions,
        'difficulty': difficulty_list,
        'topics': final_topics,
        'channel_id': ctx.channel.id
    }
    await save_daily_configs()

    await ctx.send(f"Daily config set to {num_questions} {', '.join(difficulty_list)} problem(s) with topics: {', '.join(final_topics) if final_topics else 'All'} in this channel.")

    # Automatically send problems right after setting config
    await _send_problems(ctx.channel, num_questions, difficulty_list, final_topics)

@bot.command(name='hello', help='Says hello!')
async def hello(ctx):
    await ctx.send(f'Hello {ctx.author.mention}!')

@bot.command(name='topics', help='Show available topics parsed from the dataset')
async def topics_cmd(ctx):
    global problems_df

    if problems_df is None or 'related_topics' not in problems_df.columns:
        await ctx.send("Problem dataset not loaded yet or doesn't have related topics.")
        return

    all_topics = set()
    topics_series = problems_df['related_topics'].dropna()
    for entry in topics_series:
        topics = [t.strip().lower() for t in entry.split(',')]
        all_topics.update(topics)

    sorted_topics = sorted(all_topics)

    if not sorted_topics:
        await ctx.send("No topics found in the dataset.")
        return

    message = "**Available Topics:**\n" + ", ".join(sorted_topics)

    if len(message) > 1900:
        parts = [", ".join(sorted_topics[i:i+30]) for i in range(0, len(sorted_topics), 30)]
        for part in parts:
            await ctx.send("**Available Topics:**\n" + part)
    else:
        await ctx.send(message)

bot.run(TOKEN)