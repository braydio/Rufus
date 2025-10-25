import discord
import os
import logging
import asyncio
import aiohttp
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
AI_API_URL = os.getenv("API_URL", "http://localhost:5051/v1/chat/completions")
TARGET_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID"))
SYSTEM_PROMPT_FILE = os.getenv("SYSTEM_PROMPT_FILE", "system_prompt.txt")
REFORMAT_PROMPT_FILE = os.getenv("REFORMAT_PROMPT_FILE", "reformat_prompt.txt")
SUMMARY_PROMPT_FILE = os.getenv("SUMMARY_PROMPT_FILE", "summary_prompt.txt")

# Load system prompts from files
with open(SYSTEM_PROMPT_FILE, "r") as f:
    SYSTEM_PROMPT = f.read().strip()
with open(REFORMAT_PROMPT_FILE, "r") as f:
    REFORMAT_PROMPT = f.read().strip()
with open(SUMMARY_PROMPT_FILE, "r") as f:
    SUMMARY_PROMPT = f.read().strip()

LOG_TO_FILE = os.getenv("LOG_TO_FILE", "false").lower() == "true"
LOG_FILE_PATH = os.getenv("LOG_FILE_PATH", "chat_logs.txt")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RufusBot")

# Discord setup
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

# Memory buffer (for conversation history)
memory_buffer = []
MAX_MEMORY_LENGTH = 40
MAX_DISCORD_LENGTH = 2000
MAX_ASSISTANT_REPLY_LENGTH = 500


# Utility functions
def log_to_file(user, prompt, response, note=None):
    if LOG_TO_FILE:
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(f"\n---\nUser: {user}\n")
            if note:
                f.write(f"Note: {note}\n")
            f.write(f"Prompt: {prompt}\nResponse: {response}\n")


async def query_chat_completion(messages):
    payload = {
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


# Discord events
@bot.event
async def on_ready():
    logger.info(f"✅ Logged in as {bot.user}")
    await asyncio.sleep(1)
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel:
        await channel.send(
            "🤖 Rufus is online and ready to go! Type `..ai` to ask me anything."
        )
        logger.info(f"📣 Announced ready in #{channel.name}")


@bot.event
async def on_message(message):
    global memory_buffer

    if message.author == bot.user or message.channel.id != TARGET_CHANNEL_ID:
        return

    if not message.content.startswith("..ai"):
        return

    logger.info(f"🟡 Received query from {message.author.display_name}")

    thinking_task = None

    async def thinking_loop(channel):
        idx = 0
        thinking_messages = [
            "Heh...",
            "Well erm...",
            "Okay so...",
            "Hold on...",
            "Uhh...",
            "Thinking...",
        ]
        msg = await channel.send(thinking_messages[0])
        try:
            while True:
                await asyncio.sleep(5)
                idx += 1
                await msg.edit(content=thinking_messages[idx % len(thinking_messages)])
        except asyncio.CancelledError:
            try:
                await msg.delete()
            except:
                pass

    try:
        thinking_task = asyncio.create_task(thinking_loop(message.channel))

        raw_query = message.content[len("..ai") :].strip()
        reformatted_query = await reformat_query(raw_query)

        chat_messages = (
            [{"role": "system", "content": SYSTEM_PROMPT}]
            + memory_buffer
            + [
                {
                    "role": "user",
                    "content": f"{message.author.display_name}: {reformatted_query}",
                }
            ]
        )

        response = await query_chat_completion(chat_messages)

        if thinking_task:
            thinking_task.cancel()
            try:
                await thinking_task
            except:
                pass

        if len(response) > MAX_DISCORD_LENGTH:
            chunks = [
                response[i : i + MAX_DISCORD_LENGTH]
                for i in range(0, len(response), MAX_DISCORD_LENGTH)
            ]
            for chunk in chunks:
                await message.channel.send(chunk)
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

            memory_buffer.append(
                {
                    "role": "user",
                    "content": f"{message.author.display_name}: {raw_query}",
                }
            )
            memory_buffer.append(
                {"role": "assistant", "content": f"Rufus: {summarized_response}"}
            )

            if len(memory_buffer) > MAX_MEMORY_LENGTH:
                memory_buffer = memory_buffer[-MAX_MEMORY_LENGTH:]

            logger.info("🧹 Updated memory buffer.")
            logger.info("🧠 Memory buffer content:")
            for m in memory_buffer:
                logger.info(
                    f"  - {m['role']}: {m['content'][:80]}{'...' if len(m['content']) > 80 else ''}"
                )

            log_to_file(
                "SYSTEM", "Summary Prompt", summarized_response, note="Memory Summary"
            )

    except Exception as e:
        logger.error(f"❌ Error in on_message: {e}")


bot.run(TOKEN)
