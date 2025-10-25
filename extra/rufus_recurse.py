import discord
import requests
import os
import logging
from dotenv import load_dotenv
import asyncio
import aiohttp
import json

# Load .env
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
AI_API_URL = os.getenv("API_URL", "http://localhost:5051/v1/chat/completions")
TARGET_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID"))

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RufusBot")

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

MAX_ASSISTANT_REPLY_LENGTH = 1000
MAX_DISCORD_LENGTH = 2000
MAX_MEMORY_LENGTH = 10

# Load prompts from external files
with open("prompt_system.txt", "r") as f:
    SYSTEM_PROMPT = f.read().strip()

with open("prompt_analysis.txt", "r") as f:
    ANALYSIS_TEMPLATE = f.read().strip()


async def query_chat_completion(chat_history):
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": chat_history,
        "temperature": 0.7,
        "max_tokens": 500,
        "stream": False,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(AI_API_URL, json=payload, timeout=660) as resp:
                response_text = await resp.text()
                if resp.status != 200:
                    logger.error(
                        f"Chat API returned status {resp.status}: {response_text}"
                    )
                    return f"Error: API returned status {resp.status}"
                result = json.loads(response_text)
                return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.exception("Error during AI request")
        return "Error: Exception occurred during request."


async def send_long_message(channel, content):
    for i in range(0, len(content), MAX_DISCORD_LENGTH):
        await channel.send(content[i : i + MAX_DISCORD_LENGTH])


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} watching channel {TARGET_CHANNEL_ID}")
    await asyncio.sleep(1)
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel:
        try:
            await channel.send(
                "Rufus is online and ready to go! Type `..ai` to ask me anything."
            )
            logger.info(f"Sent ready message to #{channel.name} (ID: {channel.id})")
        except Exception as e:
            logger.error(f"Failed to send ready message: {e}")
    else:
        logger.warning(f"Channel ID {TARGET_CHANNEL_ID} not found or inaccessible.")


memory_buffer = []


@bot.event
async def on_message(message):
    if message.author == bot.user or message.channel.id != TARGET_CHANNEL_ID:
        return

    if not message.content.startswith("..ai"):
        return

    raw_query = message.content[len("..ai") :].strip()

    logger.info(f"Received query from {message.author}: {raw_query}")

    input_prompt = raw_query
    responses = []

    for i in range(5):
        logger.info(f"--- Self-query iteration {i + 1} ---")
        chat_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": input_prompt},
        ]
        ai_response = await query_chat_completion(chat_messages)
        responses.append(ai_response)

        await send_long_message(
            message.channel, f"**Iteration {i + 1} Response:**\n{ai_response}"
        )

        analysis_prompt = ANALYSIS_TEMPLATE.replace("{{RESPONSE}}", ai_response)

        logger.info(f"Analysis Prompt:\n{analysis_prompt}")
        input_prompt = analysis_prompt

    final_response = responses[-1]
    await send_long_message(message.channel, f"**Final Response:**\n{final_response}")
    logger.info(f"Final Response:\n{final_response}")


bot.run(TOKEN)
