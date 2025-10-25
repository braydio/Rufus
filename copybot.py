import discord
from discord.ext import commands
import os
import logging
import asyncio
import aiohttp
import re
import sys
import time
import traceback
import schedule
import threading
from dotenv import load_dotenv
from collections import defaultdict

from rsa.session_tracker import RSASessionManager
from rsa.watchlist_manager import RufusWatchlistManager
from prompt_setup import SYSTEM_PROMPT, REFORMAT_PROMPT, SUMMARY_PROMPT

# Load environment variables
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
AI_API_URL = os.getenv("API_URL", "http://localhost:5051/v1/chat/completions")
TARGET_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID"))
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "false").lower() == "true"
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "chat_logs.txt")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("RufusBot")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="..", intents=intents)

rsa_tracker = RSASessionManager()
rwatch = RufusWatchlistManager()

memory_buffer = defaultdict(list)
active_trades = {}
MAX_MEMORY_LENGTH = 40
MAX_DISCORD_LENGTH = 2000


async def post_daily_summary():
    summaries = rwatch.log_and_get_summary()
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel:
        for msg in summaries:
            await channel.send(f"📊 {msg}")


def schedule_loop(loop):
    schedule.every().day.at("08:45").do(
        lambda: asyncio.run_coroutine_threadsafe(post_daily_summary(), loop)
    )
    schedule.every().day.at("16:30").do(
        lambda: asyncio.run_coroutine_threadsafe(post_daily_summary(), loop)
    )
    while True:
        schedule.run_pending()
        time.sleep(60)


def log_to_file(user, prompt, response, note=None):
    if LOG_TO_FILE:
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n---\nUser: {user}\n")
            if note:
                f.write(f"Note: {note}\n")
            f.write(f"Prompt: {prompt}\nResponse: {response}\n")


async def query_chat_completion(messages):
    payload = {
        "model": "gpt-4",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 600,
        "stream": False,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(AI_API_URL, json=payload, timeout=160) as resp:
                if resp.status != 200:
                    logger.error(f"❌ Chat API error: {resp.status}")
                    return "Sorry, something went wrong talking to the AI."
                result = await resp.json()
                return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"❌ API call failed: {e}")
        return "Sorry, something went wrong talking to the AI."


async def reformat_query(user_input):
    payload = {
        "model": "gpt-4",
        "messages": [
            {"role": "system", "content": REFORMAT_PROMPT},
            {"role": "user", "content": user_input},
        ],
        "temperature": 0.3,
        "max_tokens": 150,
        "stream": False,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(AI_API_URL, json=payload, timeout=160) as resp:
                if resp.status != 200:
                    return user_input
                result = await resp.json()
                reformatted = result["choices"][0]["message"]["content"].strip()
                logger.info(f"🔧 Reformatted prompt: {reformatted}")
                log_to_file("SYSTEM", user_input, reformatted, note="Reformatted Query")
                return reformatted
    except:
        return user_input


@bot.event
async def on_ready():
    logger.info(f"✅ Logged in as {bot.user}")
    loop = asyncio.get_event_loop()
    threading.Thread(target=schedule_loop, args=(loop,), daemon=True).start()
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel:
        await channel.send(
            "🤖 Rufus is online and ready to go! Type `..ai` to ask me anything."
        )


@bot.command(name="summary")
async def summary(ctx):
    if ctx.channel.id != TARGET_CHANNEL_ID:
        return
    summaries = rwatch.log_and_get_summary()
    for msg in summaries:
        await ctx.send(f"📊 {msg}")


@bot.command(name="status")
async def status(ctx, ticker: str = None):
    if ctx.channel.id != TARGET_CHANNEL_ID:
        return
    if not ticker:
        await ctx.send("Usage: `..status TICKER`")
        return
    summary = rwatch.get_status(ticker)
    await ctx.send(summary)


@bot.command(name="ai")
async def ai(ctx, *, query: str):
    if ctx.channel.id != TARGET_CHANNEL_ID:
        return

    user_id = ctx.author.id
    reformatted_query = await reformat_query(query)

    chat_messages = (
        [{"role": "system", "content": SYSTEM_PROMPT}]
        + memory_buffer[user_id]
        + [{"role": "user", "content": reformatted_query}]
    )

    thinking = await ctx.send("Thinking...")
    response = await query_chat_completion(chat_messages)
    await thinking.delete()

    if len(response) > MAX_DISCORD_LENGTH:
        for i in range(0, len(response), MAX_DISCORD_LENGTH):
            await ctx.send(response[i : i + MAX_DISCORD_LENGTH])
    else:
        await ctx.send(response)

    if response != "Sorry, something went wrong talking to the AI.":
        log_to_file(
            ctx.author.display_name, reformatted_query, response, note="Final Response"
        )
        summary_prompt = [
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": response},
        ]
        summarized_response = await query_chat_completion(summary_prompt)
        memory_buffer[user_id].append({"role": "user", "content": query})
        memory_buffer[user_id].append(
            {"role": "assistant", "content": summarized_response}
        )
        if len(memory_buffer[user_id]) > MAX_MEMORY_LENGTH:
            memory_buffer[user_id] = memory_buffer[user_id][-MAX_MEMORY_LENGTH:]
        log_to_file(
            "SYSTEM", "Summary Prompt", summarized_response, note="Memory Summary"
        )


@bot.event
async def on_message(message):
    await bot.process_commands(message)
    if message.author.bot or message.channel.id != TARGET_CHANNEL_ID:
        return

    content = message.content.lower()
    if "split date" in content and "watchlist" in content:
        match = re.search(
            r"\*\*\|\s*([A-Z]+)\*\*.*?(\d{4}-\d{2}-\d{2})", message.content
        )
        if match:
            ticker, split_date = match.group(1), match.group(2)
            added = rwatch.add(ticker, split_date)
            if added:
                await message.channel.send(
                    f"👀 Tracking `{ticker}` for {split_date} split."
                )
        return

    if match := re.match(r"!rsa (buy|sell) (\d+)? ?([A-Z]+)", content):
        action, qty, ticker = match.groups()
        ticker = ticker.upper()
        active_trades[ticker] = True
        await message.channel.send(f"🟢 Monitoring broker fills for `{ticker}`.")
        return

    if buy_match := re.search(r"(\w+)\s+(\d): buying .* of ([A-Z]+)", content):
        broker, acct, ticker = buy_match.groups()
        ticker = ticker.upper()
        acct_id = f"{broker}:{acct}"
        if ticker in active_trades:
            rwatch.mark_purchase(ticker, acct_id)
        return

    if match := re.match(r"all (\w+) transactions complete", content):
        broker = match.group(1)
        for ticker in list(active_trades):
            for acct in rwatch.watchlist.get(ticker, {}).get("purchases", []):
                if acct.lower().startswith(broker.lower()):
                    rwatch.mark_closeout(ticker, acct)
        rsa_tracker.mark_broker_complete(message.author.id, broker)
        await message.channel.send(f"✅ Closeout activity logged for `{ticker}`.")
        return

    if "all commands complete in all brokers" in content:
        rsa_tracker.mark_all_done(message.author.id)
        summary = rsa_tracker.get_status(message.author.id)
        await message.channel.send(f"📊 RSA session summary:\n```\n{summary}\n```")
        return

    if err_match := re.search(r"(?:error.*order.*(?:for|on)) (\w+)", content):
        rsa_tracker.mark_error(message.author.id, err_match.group(1), message.content)
        return


if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        threading.Thread(target=schedule_loop, args=(loop,), daemon=True).start()
        bot.run(TOKEN)
    except Exception:
        print("❌ Bot startup error:")
        print(traceback.format_exc())
