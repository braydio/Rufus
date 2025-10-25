#!/usr/bin/env python3
import os
import json
import random
import asyncio
import logging

import discord
import aiohttp
from dotenv import load_dotenv

# ─── Config & Logging ─────────────────────────────────────────────────────────
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
AI_API_URL = os.getenv("API_URL", "http://localhost:5051/v1/chat/completions")
TARGET_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "5.0"))  # seconds between AI calls
MAX_DISCORD_LENGTH = 2000

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RufusBot")

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

# ─── Load Prompts & Wildcards ─────────────────────────────────────────────────
with open("wild_card.txt", "r") as f:
    WILDCARDS = [line.strip() for line in f if line.strip()]

with open("prompt_system.txt", "r") as f:
    SYSTEM_PROMPT = f.read().strip()

with open("prompt_analysis.txt", "r") as f:
    ANALYSIS_TEMPLATE = f.read().strip()

# ─── Request Queue ─────────────────────────────────────────────────────────────
request_queue: asyncio.Queue[tuple[discord.Message, str]] = asyncio.Queue()


# ─── AI Query ─────────────────────────────────────────────────────────────────
async def query_chat_completion(chat_history):
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": chat_history,
        "temperature": 0.4,
        "max_tokens": 500,
        "stream": False,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(AI_API_URL, json=payload, timeout=360) as resp:
                text = await resp.text()
                if resp.status != 200:
                    logger.error(f"API {resp.status}: {text}")
                    return f"Error: API {resp.status}"
                return json.loads(text)["choices"][0]["message"]["content"].strip()
    except Exception:
        logger.exception("AI request failed")
        return "Error: Exception during request."


# ─── Helper to chunk long messages ─────────────────────────────────────────────
async def send_long_message(channel, content):
    for i in range(0, len(content), MAX_DISCORD_LENGTH):
        await channel.send(content[i : i + MAX_DISCORD_LENGTH])


# ─── Background Worker ────────────────────────────────────────────────────────
CRAZED_PERSONA = (
    "You are completely unhinged, addicted to crack, and babble "
    "nonstop about conspiracies—gibber, yammer, and rant like a madman."
)


async def process_queue():
    await bot.wait_until_ready()
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    while True:
        message, raw_query = await request_queue.get()
        prompt = raw_query
        responses = []

        for i in range(3):
            iteration = i + 1
            # 1) build the system messages
            msgs = [{"role": CRAZED_PERSONA, "content": SYSTEM_PROMPT}]

            # inject crazed persona on even iterations
            if iteration % 2 == 0:
                msgs.append({"role": CRAZED_PERSONA, "content": ANALYSIS_TEMPLATE})

            # still include a wildcard if you like
            if WILDCARDS:
                wc = random.choice(WILDCARDS)
                msgs.append({"role": "system", "content": f"Wildcard directive: {wc}"})

            # user question (or analysis prompt)
            msgs.append({"role": "user", "content": prompt})

            # 2) query the AI
            ai_resp = await query_chat_completion(msgs)
            responses.append(ai_resp)

            # 3) send the reply
            persona_tag = "(CRAZED)" if iteration % 2 == 0 else "(normal)"
            await send_long_message(message.channel, f"**Hey! Fuck you!**\n{ai_resp}")

            # 4) build next prompt via analysis template
            prompt = ANALYSIS_TEMPLATE.replace("{{RESPONSE}}", ai_resp)

            # 5) rate‑limit
            await asyncio.sleep(REQUEST_DELAY)

        # final result
        final = responses[-1]
        await send_long_message(message.channel, f"**Final Response:**\n{final}")
        request_queue.task_done()


# ─── Bot Events ───────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} on channel {TARGET_CHANNEL_ID}")
    # Send ready message
    ch = bot.get_channel(TARGET_CHANNEL_ID)
    if ch:
        await ch.send("**Hey! Fuck you!**")
    else:
        logger.warning("Target channel not found.")
    # Start the queue processor
    bot.loop.create_task(process_queue())


@bot.event
async def on_message(message):
    # Ignore bot itself and other channels
    if message.author == bot.user or message.channel.id != TARGET_CHANNEL_ID:
        return

    if not message.content.startswith("..ai"):
        return

    raw = message.content[len("..ai") :].strip()
    # Enqueue the request
    await request_queue.put((message, raw))
    pos = request_queue.qsize()
    await message.channel.send(f"🔄 Your request has been queued at position {pos}.")
    logger.info(
        f"Enqueued {message.author}. Thank you number {pos} your concerns are valid."
    )


bot.run(TOKEN)
