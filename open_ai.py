import aiohttp
import os
import logging
import asyncio
import json
from dotenv import load_dotenv

# Load environment
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-nano")
MAX_TOKENS = 600

# Logging setup
logger = logging.getLogger("RufusRSA")
logging.basicConfig(level=logging.INFO)


async def query_openai_chat(messages):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": MAX_TOKENS,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"OpenAI API error {resp.status}: {text}")
                    return None
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Request failed: {e}")
        return None


# Example usage
async def main():
    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant that summarizes user inputs.",
        },
        {
            "role": "user",
            "content": "Summarize the recent broker trades for AAPL and NVDA.",
        },
    ]
    response = await query_openai_chat(messages)
    if response:
        print("OpenAI Response:\n", response)
    else:
        print("Failed to get response.")


if __name__ == "__main__":
    asyncio.run(main())
