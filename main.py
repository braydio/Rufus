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


@bot.event
async def on_ready():  # <-- async added here
    logger.info(f"Logged in as {bot.user} watching channel {TARGET_CHANNEL_ID}")

    # Delay a second to allow full Discord cache
    import asyncio

    await asyncio.sleep(1)

    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel:
        try:
            await channel.send(
                "🤖 Rufus is online and ready to go! Type `..ai` to ask me anything."
            )
            logger.info(f"📣 Sent ready message to #{channel.name} (ID: {channel.id})")
        except Exception as e:
            logger.error(f"❌ Failed to send ready message: {e}")
    else:
        logger.warning(
            f"⚠️ Channel ID {TARGET_CHANNEL_ID} not found or bot doesn't have access."
        )

    # List all servers + channels to debug
    for guild in bot.guilds:
        logger.info(f"🛡️ In guild: {guild.name} ({guild.id})")
        for ch in guild.text_channels:
            logger.info(f"  🧾 Channel: {ch.name} (ID: {ch.id})")


MAX_ASSISTANT_REPLY_LENGTH = 1000  # Characters (or adjust to taste)


def convert_messages_to_chat_format(messages, bot_user):
    formatted = []

    for msg in messages:
        if "<!--thinking-->" in msg.content:
            continue

        if "Rufus is online and ready to go!" in msg.content:
            continue

        if msg.author == bot_user:
            content = f"Rufus: {msg.content}"
            # Truncate long bot replies
            if len(content) > MAX_ASSISTANT_REPLY_LENGTH:
                content = content[:MAX_ASSISTANT_REPLY_LENGTH] + "..."
            formatted.append({"role": "assistant", "content": content})

        else:
            if msg.content.startswith("..ai"):
                username = (
                    msg.author.display_name
                    if hasattr(msg.author, "display_name")
                    else msg.author.name
                )
                cleaned = msg.content[len("..ai") :].strip()
                formatted.append({"role": "user", "content": f"{username}: {cleaned}"})

    return formatted


async def summarize_text(original_text):
    payload = {
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful assistant that summarizes long texts into short, clear summaries.",
            },
            {
                "role": "user",
                "content": f"Summarize the following in 2 sentences:\n\n{original_text}",
            },
        ],
        "temperature": 0.5,
        "max_tokens": 150,
        "stream": False,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(AI_API_URL, json=payload, timeout=60) as resp:
                if resp.status != 200:
                    logger.error(f"❌ Summarizer API returned status {resp.status}")
                    return original_text  # fallback to original if failed

                result = await resp.json()
                summary = result["choices"][0]["message"]["content"].strip()
                logger.info(f"📝 Summarized AI response: {summary}")
                return summary

    except Exception as e:
        logger.error(f"❌ Error during AI request: {e}")
        return "Sorry, something went wrong talking to the AI."


async def reformat_query(user_input):
    payload = {
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful assistant that reformats and clarify requests into professional prompts for an AI to answer.",
            },
            {
                "role": "user",
                "content": f"Rephrase this query that it can be sent to ChatGPT and will return a high quality response:\n\n{user_input}",
            },
        ],
        "temperature": 0.3,
        "max_tokens": 150,
        "stream": False,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(AI_API_URL, json=payload, timeout=60) as resp:
                if resp.status != 200:
                    logger.error(
                        f"❌ Query reformatter API returned status {resp.status}"
                    )
                    return user_input  # fallback to original if failed

                result = await resp.json()
                reformatted = result["choices"][0]["message"]["content"].strip()
                logger.info(f"🔧 Reformatted user query: {reformatted}")
                return reformatted

    except Exception as e:
        logger.error(f"❌ Error during reformatting request: {e}")
        return user_input


async def query_chat_completion(chat_history):
    payload = {
        "messages": chat_history,
        "temperature": 0.7,
        "max_tokens": 500,
        "stream": False,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(AI_API_URL, json=payload, timeout=60) as resp:
                if resp.status != 200:
                    logger.error(f"❌ Chat API returned status {resp.status}")
                    return "Sorry, something went wrong talking to the AI."

                result = await resp.json()
                ai_reply = result["choices"][0]["message"]["content"].strip()
                logger.info(
                    f"🧠 AI reply: {ai_reply[:100]}{'...' if len(ai_reply) > 100 else ''}"
                )
                return ai_reply

    except Exception as e:
        logger.error(f"❌ Error during AI request: {e}")
        return "Sorry, something went wrong talking to the AI."


# Memory buffer across messages
memory_buffer = []


@bot.event
async def on_message(message):
    global memory_buffer

    if message.author == bot.user or message.channel.id != TARGET_CHANNEL_ID:
        return

    if not message.content.startswith("..ai"):
        return

    logger.info(f"🟡 Received query from {message.author}")

    raw_query = message.content[len("..ai"):].strip()

    try:
        # 1. Reformat query
        reformatted_query = await reformat_query(raw_query)

        # 2. Prepare system + message
        chat_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{message.author.display_name}: {reformatted_query}"}
        ]

        # 3. Get AI's main response
        ai_response = await query_chat_completion(chat_messages)

        # 4. Summarize response
        summary = await summarize_text(ai_response)

        # 5. Log the whole interaction to file
        log_review_flow(message.author.display_name, raw_query, reformatted_query, ai_response, summary)

        # 6. Update memory buffer
        memory_buffer.append({"role": "user", "content": f"{message.author.display_name}: {raw_query}"})
        memory_buffer.append({"role": "assistant", "content": f"Rufus: {summary}"})
        if len(memory_buffer) > MAX_MEMORY_LENGTH:
            memory_buffer = memory_buffer[-MAX_MEMORY_LENGTH:]

        # 7. Respond in Discord with full response only
        if len(ai_response) > MAX_DISCORD_LENGTH:
            chunks = [ai_response[i:i+MAX_DISCORD_LENGTH] for i in range(0, len(ai_response), MAX_DISCORD_LENGTH)]
            for chunk in chunks:
                await message.channel.send(chunk)
        else:
            await message.channel.send(ai_response)

    except Exception as e:
        logger.error(f"Error processing message: {e}")
        await message.channel.send("Something went wrong while processing your request.")
bot.run(TOKEN)

