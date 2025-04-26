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

load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
KAGGLE_DATASET_PATH = 'leetcode_problems.csv'

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

problems_df = None
daily_configs = {}
leaderboard = defaultdict(int)  # Store user scores (user_id: score)
submissions = defaultdict(lambda: defaultdict(bool)) # Store submissions (user_id: {problem_title: submitted})
daily_problems = defaultdict(list)  # {guild_id: [problem_title1, problem_title2, ...]}

@bot.event
async def on_ready():
    global problems_df
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
    global problems_df, daily_problems

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

    if filtered_problems.empty:
        await channel.send("No problems found matching the current configuration.")
        return

    if len(filtered_problems) < num_questions:
        selected_problems = filtered_problems.sample(len(filtered_problems))
    else:
        selected_problems = filtered_problems.sample(num_questions)

    # ADD selected problems to today's problems
    daily_problems[channel.guild.id].extend([row['title'] for _, row in selected_problems.iterrows()])

    # NOW instead of showing just selected problems, show all today's problems
    embed = discord.Embed(title="Today's Full LeetCode Challenge Set!", color=discord.Color.blue())
    for title in daily_problems[channel.guild.id]:
        # find URL for each title
        url_row = problems_df[problems_df['title'] == title]
        if not url_row.empty:
            problem_url = url_row.iloc[0]['url']
            embed.add_field(name=title, value=f"[Solve it here]({problem_url})", inline=False)

    await channel.send(embed=embed)
    
async def show_today_problems(channel):
    global problems_df, daily_problems

    today_sent_problems = daily_problems.get(channel.guild.id, [])

    if not today_sent_problems:
        await channel.send("No problems have been sent yet for today.")
        return

    embed = discord.Embed(title="Today's Full LeetCode Challenge Set!", color=discord.Color.blue())
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

    # Validate if problem was sent today
    today_sent_problems = daily_problems.get(ctx.guild.id, [])
    if not any(problem_lower == p.lower() for p in today_sent_problems):
        await ctx.send(f"'{problem_title}' was not part of today's challenge. Only today's problems are allowed!")
        return

    found = False
    for index, row in problems_df.iterrows():
        if row['title'].lower() == problem_lower:
            found = True
            difficulty = row['difficulty'] if 'difficulty' in row else 'Easy'

            # Award points
            point_map = {
                "Easy": 10,
                "Medium": 20,
                "Hard": 30
            }
            points = point_map.get(difficulty, 10)

            if not submissions[user_id][row['title']]:
                submissions[user_id][row['title']] = True
                leaderboard[user_id] += points
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
        await ctx.send("Today's problems have been deleted! No submissions allowed now until new problems are sent.")
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
    global daily_configs

    difficulty_list = [d.strip().capitalize() for d in difficulty.split(',')]
    valid_difficulties = problems_df['difficulty'].unique() if problems_df is not None else ["Easy", "Medium", "Hard"]

    for diff in difficulty_list:
        if diff not in valid_difficulties:
            await ctx.send(f"Invalid difficulty: '{diff}'. Please choose from {', '.join(valid_difficulties)}.")
            return

    # Now validate topics also
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

    # If "all" is given as topic, treat it like empty (no filtering)
    final_topics = [] if ("all" in [t.lower() for t in topics]) else list(topics)

    daily_configs[ctx.guild.id] = {
        'num_questions': num_questions,
        'difficulty': difficulty_list,
        'topics': final_topics,
        'channel_id': ctx.channel.id
    }

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

    # Discord 2000 character limit, split if too long
    message = "**Available Topics:**\n" + ", ".join(sorted_topics)

    if len(message) > 1900:
        parts = [", ".join(sorted_topics[i:i+30]) for i in range(0, len(sorted_topics), 30)]
        for part in parts:
            await ctx.send("**Available Topics:**\n" + part)
    else:
        await ctx.send(message)

bot.run(TOKEN)
