"""Discord bot entry point for the Rufus project.

This module hosts a minimal Discord client that forwards prompts to an AI
completion endpoint while speaking with an upbeat personality.  The focus is on
maintainability and clarity rather than feature bloat.
"""

from __future__ import annotations

import logging
import os
from collections import deque
from typing import Deque, Dict, List

import aiohttp
import discord
from discord import Message
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = os.getenv("API_URL", "http://localhost:5051/v1/chat/completions")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "..ai")
MAX_DISCORD_MESSAGE = 1900
MAX_HISTORY = 6

SYSTEM_PROMPT = (
    "You are Rufus, an upbeat surf coach turned AI companion. You respond with "
    "encouragement, helpful details, and beachy enthusiasm without going overboard."
)

_logger = logging.getLogger("rufus.bot")


async def request_completion(messages: List[Dict[str, str]]) -> str:
    """Call the configured completion API and return the assistant's text.

    Args:
        messages: The chat history formatted according to the OpenAI-compatible
            schema.

    Returns:
        The assistant message content returned by the API.

    Raises:
        RuntimeError: If the API returns a non-success status code or lacks a
            usable response body.
    """

    payload = {
        "model": os.getenv("MODEL", "gpt-4o-mini"),
        "messages": messages,
        "temperature": 0.7,
        "stream": False,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(API_URL, json=payload, timeout=60) as response:
            if response.status != 200:
                text = await response.text()
                raise RuntimeError(f"API error {response.status}: {text}")

            data = await response.json()

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError) as exc:  # pragma: no cover - defensive
        raise RuntimeError("API response missing choices/message content") from exc


class RufusBot(discord.Client):
    """Discord client that handles AI chat requests with lightweight context."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._channel_histories: Dict[int, Deque[Dict[str, str]]] = {}

    async def setup_hook(self) -> None:
        """Configure logging once the client loop is ready."""

        logging.basicConfig(level=logging.INFO)
        _logger.info("Rufus bot starting up")

    async def on_ready(self) -> None:  # pragma: no cover - Discord callback
        _logger.info("Logged in as %s", self.user)

    async def on_message(self, message: Message) -> None:  # pragma: no cover - Discord callback
        if message.author == self.user or not message.content.startswith(COMMAND_PREFIX):
            return

        user_prompt = message.content[len(COMMAND_PREFIX) :].strip()
        if not user_prompt:
            await message.channel.send(
                "Hey there! Toss a question after the command so I can help. 🤙"
            )
            return

        history = self._channel_histories.setdefault(message.channel.id, deque(maxlen=MAX_HISTORY))
        history.append({"role": "user", "content": f"{message.author.display_name}: {user_prompt}"})

        chat_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        chat_messages.extend(history)

        async with message.channel.typing():
            try:
                reply = await request_completion(chat_messages)
            except Exception as exc:  # pragma: no cover - network failure path
                _logger.exception("Failed to fetch completion")
                await message.channel.send(
                    "Gnarly wipeout talking to the AI. Give it another shot in a moment!"
                )
                return

        history.append({"role": "assistant", "content": f"Rufus: {reply}"})
        for chunk in _chunk_message(reply):
            await message.channel.send(chunk)


def _chunk_message(text: str) -> List[str]:
    """Split a long response into Discord-safe chunks."""

    if not text:
        return ["Rufus is momentarily speechless, try again! 🤔"]

    return [
        text[i : i + MAX_DISCORD_MESSAGE]
        for i in range(0, len(text), MAX_DISCORD_MESSAGE)
    ]


def main() -> None:  # pragma: no cover - CLI entry
    """Entrypoint for running the Discord bot from the command line."""

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not configured in the environment")

    client = RufusBot()
    client.run(BOT_TOKEN)

if __name__ == "__main__":  # pragma: no cover - CLI entry
    main()
