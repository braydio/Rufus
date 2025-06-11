# websearch_adapter.py
import aiohttp
import logging
import os

logger = logging.getLogger(__name__)

AI_API_URL = os.getenv("API_URL", "http://localhost:5051/v1/chat/completions")


async def query_with_websearch(user_input: str) -> str:
    """
    Sends a web search-enabled prompt to the LLM backend that has LLM_WebSearch.
    """
    payload = {
        "model": "gpt-4",  # Adjust if necessary
        "messages": [
            {"role": "system", "content": "Use !web to search the web when relevant."},
            {"role": "user", "content": f"!web {user_input}"},
        ],
        "temperature": 0.7,
        "max_tokens": 600,
        "stream": False,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(AI_API_URL, json=payload, timeout=160) as resp:
                if resp.status != 200:
                    logger.error(f"Web search API error: {resp.status}")
                    return f"Web search failed: {resp.status}"
                result = await resp.json()
                return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Web search query failed: {e}")
        return "An error occurred while performing web search."
