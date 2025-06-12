import discord
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
import json
from dotenv import load_dotenv
from collections import defaultdict

from rsa.session_tracker import RSASessionManager
from rsa.watchlist_manager import RufusWatchlistManager
from prompt_setup import SYSTEM_PROMPT, REFORMAT_PROMPT, SUMMARY_PROMPT
from websearch_adapter import query_with_websearch

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
bot = discord.Client(intents=intents)

rsa_tracker = RSASessionManager()
rwatch = RufusWatchlistManager()

memory_buffer = defaultdict(list)  # per-user buffer
active_trades = {}
MAX_MEMORY_LENGTH = 40
MAX_DISCORD_LENGTH = 2000


async def update_lifecycle_from_ai(
    user_id, rsa_tracker, rwatch, ai_client, discord_channel, chunk_size=10
):
    chunks = rsa_tracker.get_message_chunks(user_id, chunk_size=chunk_size)
    watchlist_summary = rwatch.get_all_statuses()
    ticker_list = list(rwatch.watchlist.keys())

    for idx, chunk in enumerate(chunks):
        raw_messages = "\n".join([msg["content"] for msg in chunk])
        prompt = [
            {
                "role": "system",
                "content": (
                    "You are an assistant helping manage broker positions "
                    "on a stock watchlist. A stock goes through lifecycle stages: "
                    "`planned`, `holding`, `awaiting_sell`, `closed`."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Watchlist:\n{', '.join(ticker_list)}\n\n"
                    f"Split dates and broker status:\n"
                    + "\n".join(watchlist_summary)
                    + f"\n\nHere are recent broker activity logs:\n{raw_messages}\n\n"
                    "Based on these messages, tell me for each stock which brokers "
                    "have entered a new lifecycle stage (like just purchased, or just sold). "
                    "Return JSON like:\n"
                    "{ 'FRGT': { 'BBAE': { '1': { 'status': 'holding', 'account': '4365' } } } }"
                ),
            },
        ]

        try:
            await discord_channel.send(
                "📤 Sending the following messages to AI:\n" + raw_messages[:1800]
            )
            response = await ai_client(prompt)
            lifecycle_updates = json.loads(response)

            for ticker, broker_data in lifecycle_updates.items():
                for broker, accounts in broker_data.items():
                    for broker_number, info in accounts.items():
                        new_status = info.get("status")
                        account = info.get("account")
                        prev = rwatch.get_broker_state(ticker, broker, broker_number)
                        prev_status = prev.get("status")

                        rwatch.update_lifecycle(
                            ticker=ticker,
                            broker=broker,
                            broker_number=broker_number,
                            status=new_status,
                            account=account,
                        )

                        # Notify only on status transition
                        if (
                            new_status == "awaiting_sell"
                            and prev_status != "awaiting_sell"
                        ):
                            await discord_channel.send(
                                f"🔔 `{broker} {broker_number}` is now `awaiting_sell` for `{ticker}`.\n"
                                f"Please check account `{account}` for return of stock after split."
                            )
                        elif new_status == "closed" and prev_status != "closed":
                            await discord_channel.send(
                                f"✅ `{broker} {broker_number}` has closed out `{ticker}`."
                            )

        except Exception as e:
            await discord_channel.send(f"❌ Failed to process lifecycle update: {e}")


async def post_daily_summary():
    summaries = rwatch.log_and_get_summary()
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel:
        for msg in summaries:
            await channel.send(f"📊 {msg}")


def sync_purchases_from_lifecycle(self):
    """Ensure that accounts marked as 'holding' are also registered in 'purchases' list (legacy support)."""
    for ticker, ticker_data in self.watchlist.items():
        brokers = ticker_data.get("brokers", {})
        purchases = set(ticker_data.get("purchases", []))  # legacy style
        updated = False

        for broker, broker_accounts in brokers.items():
            for number, info in broker_accounts.items():
                if info.get("status") == "holding":
                    acct_str = f"{broker}:{number}"
                    if acct_str not in purchases:
                        self.watchlist[ticker].setdefault("purchases", []).append(
                            acct_str
                        )
                        updated = True
                        logger.info(
                            f"🔄 Synced purchase from lifecycle → {acct_str} for {ticker}"
                        )

        if updated:
            self.save()


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


@bot.event
async def on_message(message):
    # These are commented out because they filtered out the messages
    # That I was trying to record, sent from other bots in other channel.
    #
    # if message.author.bot or message.channel.id != TARGET_CHANNEL_ID:
    #     return

    content = message.content.lower()
    user_id = message.author.id
    logger.info(f"📩 New message received: {message.content[:80]}")

    full_text = message.content
    for embed in message.embeds:
        if embed.description:
            full_text += "\n" + embed.description
        for field in embed.fields:
            full_text += f"\n{field.name}: {field.value}"

    if message.embeds:
        logger.info(f"📎 Found {len(message.embeds)} embeds in message.")
        for i, embed in enumerate(message.embeds):
            logger.info(f"Embed {i}: title={embed.title}, description={embed.fields}")
    # Watchlist dump and sync
    if (
        content.startswith("..watchlist")
        or content.startswith("..summary")
        or content.startswith("..all")
    ):
        rwatch.sync_purchases_from_lifecycle()
        summaries = rwatch.log_and_get_summary()
        for msg in summaries:
            await message.channel.send(f"📊 {msg}")
        return
    if content.startswith("!web "):
        user_query = message.content[5:].strip()
        response = await query_with_websearch(user_query)
        await message.channel.send(response)
        return
    # Regex-based split date watchlist add
    if "split date" in content and "watchlist" in content:
        match = re.search(
            r"\*\*\|\s*([A-Z]+)\*\*.*?(\d{4}-\d{2}-\d{2})", message.content
        )
        if match:
            ticker, split_date = match.group(1), match.group(2)
            if rwatch.add(ticker, split_date):
                await message.channel.send(
                    f"👀 Tracking `{ticker}` for {split_date} split."
                )
        return

    # RSA session start
    if content.startswith("!rsa"):
        rsa_tracker.start_session(
            user_id,
            expected_brokers=[
                "bbae",
                "dspac",
                "fennel",
                "public",
                "schwab",
                "sofi",
                "vanguard",
                "webull",
            ],
        )
        await message.channel.send("📍 Tracking this RSA session.")
        return

    # Broker buy activity → update lifecycle to 'holding'
    if match := re.search(r"(\w+)\s+(\d): buying .* of ([A-Z]+)", content):
        broker, acct, ticker = match.groups()
        ticker = ticker.upper()
        if ticker in active_trades:
            rwatch.update_lifecycle(
                ticker=ticker,
                broker=broker,
                broker_number=acct,
                status="holding",
                account=f"{broker}:{acct}",
            )
        return

    # Track "!rsa buy 1 XYZ" to trigger trade tracking
    if match := re.match(r"!rsa (buy|sell) (\d+)? ?([A-Z]+)", content):
        action, qty, ticker = match.groups()
        ticker = ticker.upper()
        active_trades[ticker] = True
        await message.channel.send(f"🟢 Monitoring broker fills for `{ticker}`.")
        return

    # Handle broker closeout (by broker group)
    if match := re.match(r"all (\w+) transactions complete", content):
        broker = match.group(1)
        rsa_tracker.mark_broker_complete(user_id, broker)
        for ticker in list(active_trades):
            rwatch.update_lifecycle(
                ticker=ticker, broker=broker, broker_number="?", status="closed"
            )
            del active_trades[ticker]
        await message.channel.send(f"✅ Closeout activity logged for `{ticker}`.")
        return

    # Handle final completion + AI lifecycle update
    if "all commands complete in all brokers" in content:
        rsa_tracker.mark_all_done(user_id)
        summary = rsa_tracker.get_status(user_id)
        await message.channel.send(f"📊 RSA session summary:\n```\n{summary}\n```")
        await update_lifecycle_from_ai(
            user_id=user_id,
            rsa_tracker=rsa_tracker,
            rwatch=rwatch,
            ai_client=query_chat_completion,
            discord_channel=message.channel,
        )
        return

    # Broker error parsing
    if err_match := re.search(r"(?:error.*order.*(?:for|on)) (\w+)", content):
        rsa_tracker.mark_error(user_id, err_match.group(1), message.content)
        return

    if content.startswith("..lifecycle"):
        parts = content.split()
        if len(parts) < 2:
            await message.channel.send("Usage: `..lifecycle TICKER`")
            return

        ticker = parts[1].upper()
        data = rwatch.watchlist.get(ticker)
        if not data:
            await message.channel.send(f"⚠️ `{ticker}` is not on the watchlist.")
            return

        split_date = data.get("split_date", "???")
        brokers = data.get("brokers", {})
        today = datetime.today().date()
        passed = (
            "✅ passed"
            if today >= datetime.strptime(split_date, "%Y-%m-%d").date()
            else "⏳ upcoming"
        )

        msg = f"📋 Lifecycle state for **{ticker}** (split {split_date}, {passed}):\n"

        for broker, accounts in brokers.items():
            for num, info in accounts.items():
                state = info.get("status", "unknown")
                acct = info.get("account", "???")
                last = info.get("last_seen", "unknown")
                msg += f"  • {broker} {num} [{acct}] → `{state}` (last seen {last})\n"

        await message.channel.send(msg)
        return

    # Dump session log (debug)
    if content.startswith("..sessiondump"):
        session = rsa_tracker.get_session_dump(user_id)
        if not session:
            await message.channel.send("⚠️ No session found for your user.")
            return
        logs = session.get("messages", [])
        output = "\n".join(f"- {msg['content']}" for msg in logs[-10:]) or "(empty)"
        await message.channel.send(
            f"🧾 Last 10 messages in session:\n```\n{output}\n```"
        )
        return

    # Skip if not an AI query
    if not message.content.startswith("..ai"):
        return

    # 🧠 AI handling with memory and summarization
    async def thinking_loop(channel):
        idx = 0
        thoughts = [
            "Heh...",
            "Well erm...",
            "Okay so...",
            "Hold on...",
            "Uhh...",
            "Thinking...",
        ]
        msg = await channel.send(thoughts[0])
        try:
            while True:
                await asyncio.sleep(5)
                idx += 1
                await msg.edit(content=thoughts[idx % len(thoughts)])
        except asyncio.CancelledError:
            try:
                await msg.delete()
            except:
                pass

    thinking_task = asyncio.create_task(thinking_loop(message.channel))
    try:
        raw_query = message.content[len("..ai") :].strip()
        reformatted_query = await reformat_query(raw_query)

        chat_messages = (
            [{"role": "system", "content": SYSTEM_PROMPT}]
            + memory_buffer[user_id]
            + [
                {"role": "user", "content": raw_query}
            ]  # CHANGE raw_query tp reformatted_query for intermediate self-prompt
        )
        response = await query_chat_completion(chat_messages)

        thinking_task.cancel()
        try:
            await thinking_task
        except:
            pass

        if len(response) > MAX_DISCORD_LENGTH:
            for i in range(0, len(response), MAX_DISCORD_LENGTH):
                await message.channel.send(response[i : i + MAX_DISCORD_LENGTH])
        else:
            await message.channel.send(response)

        if response != "Sorry, something went wrong talking to the AI.":
            log_to_file(
                message.author.display_name,
                reformatted_query,
                response,
                note="Final Response",
            )

            summary_prompt = [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": response},
            ]
            summarized_response = await query_chat_completion(summary_prompt)

            memory_buffer[user_id].append({"role": "user", "content": raw_query})
            memory_buffer[user_id].append(
                {"role": "assistant", "content": summarized_response}
            )

            if len(memory_buffer[user_id]) > MAX_MEMORY_LENGTH:
                memory_buffer[user_id] = memory_buffer[user_id][-MAX_MEMORY_LENGTH:]

            log_to_file(
                "SYSTEM", "Summary Prompt", summarized_response, note="Memory Summary"
            )
    except Exception as e:
        logger.error(f"❌ Error in on_message: {e}")


if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        threading.Thread(target=schedule_loop, args=(loop,), daemon=True).start()
        bot.run(TOKEN)
    except Exception:
        print("❌ Bot startup error:")
        print(traceback.format_exc())
