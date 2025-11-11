"""Discord bot entry point for the Rufus project.

This module hosts a minimal Discord client that forwards prompts to an AI
completion endpoint while speaking with an upbeat personality.  The focus is on
maintainability and clarity rather than feature bloat.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import socket
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Mapping, Optional, Sequence

import aiohttp
import discord
from discord import Message, TextChannel
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = os.getenv("API_URL", "http://localhost:5051/v1/chat/completions")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "..ai")
MINECRAFT_COMMAND = os.getenv("MINECRAFT_COMMAND", "..startmc")
MINECRAFT_SCRIPT = os.path.expanduser(
    os.getenv(
        "MINECRAFT_SCRIPT",
        "/home/braydenchaffee/Media/Minecraft/MinecraftReloaded/run.sh",
    )
)
MINECRAFT_ALT_SCRIPT = os.path.expanduser(
    os.getenv(
        "MINECRAFT_ALT_SCRIPT",
        "/home/braydenchaffee/Media/Minecraft/Opticraft_VR/run.sh",
    )
)
SERVER_STATUS_COMMAND = os.getenv("SERVER_STATUS_COMMAND", "..serverstatus")
STOP_SERVER_COMMAND = os.getenv("STOP_SERVER_COMMAND", "..stopserver")
HELP_COMMAND = os.getenv("HELP_COMMAND", "..mchelp")
MINECRAFT_PORT = os.getenv("MINECRAFT_PORT", "25565")
MAX_DISCORD_MESSAGE = 1900
MAX_HISTORY = 6

MINECRAFT_LOG_CHANNEL_ID = os.getenv("MINECRAFT_LOG_CHANNEL_ID")

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
        self._log_channel_id: Optional[int] = _parse_int(MINECRAFT_LOG_CHANNEL_ID)
        self._log_channel: Optional[TextChannel] = None
        self._command_descriptions: Dict[str, str] = _build_command_descriptions()
        self._help_message: str = _format_help_message(self._command_descriptions)

    async def setup_hook(self) -> None:
        """Configure logging once the client loop is ready."""

        logging.basicConfig(level=logging.INFO)
        _logger.info("Rufus bot starting up")
        _logger.info(
            "Command overview: %s",
            _summarize_commands_for_log(self._command_descriptions),
        )

    async def on_ready(self) -> None:  # pragma: no cover - Discord callback
        _logger.info("Logged in as %s", self.user)

        if self._log_channel_id is not None:
            channel = self.get_channel(self._log_channel_id)
            if isinstance(channel, TextChannel):
                self._log_channel = channel
                _logger.info(
                    "Minecraft log channel configured: #%s (%s)",
                    channel.name,
                    channel.id,
                )
            else:
                _logger.warning(
                    "Minecraft log channel %s not found or not a text channel.",
                    self._log_channel_id,
                )

        _logger.info("Rufus is ready to ride! Use %s for AI chat or %s for help.", COMMAND_PREFIX, HELP_COMMAND)

    async def on_message(self, message: Message) -> None:  # pragma: no cover - Discord callback
        if message.author == self.user:
            return

        if message.content.startswith(MINECRAFT_COMMAND):
            await self._handle_minecraft_launch(message)
            return

        if message.content.startswith(SERVER_STATUS_COMMAND):
            await self._handle_server_status(message)
            return

        if message.content.startswith(STOP_SERVER_COMMAND):
            await self._handle_stop_server(message)
            return

        if message.content.startswith(HELP_COMMAND):
            await message.channel.send(self._help_message)
            return

        if not message.content.startswith(COMMAND_PREFIX):
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


    async def _handle_minecraft_launch(self, message: Message) -> None:
        """Launch the main Minecraft server, shutting down the alt server if needed."""

        await message.channel.send(
            "Waxing the board and starting the Minecraft server... hang tight! 🏄"
        )

        try:
            alt_running = await _is_server_running(MINECRAFT_ALT_SCRIPT)
        except Exception as exc:  # pragma: no cover - system-level failure path
            _logger.exception("Failed to determine alt server status")
            await message.channel.send(
                f"Couldn't check the alt server status: `{exc}`."
            )
            return

        if alt_running:
            await message.channel.send(
                "Alt server is up — letting the crew know and shutting it down before launching the main server."
            )
            try:
                alt_stopped = await _stop_server(MINECRAFT_ALT_SCRIPT)
            except Exception as exc:  # pragma: no cover - system-level failure path
                _logger.exception("Failed to stop alt server")
                await message.channel.send(
                    f"Tried to stop the alt server but wiped out with: `{exc}`."
                )
                return

            if not alt_stopped:
                await message.channel.send(
                    "Couldn't find a running alt server after all, so moving ahead with the main launch."
                )

        try:
            await _launch_minecraft_server(MINECRAFT_SCRIPT)
        except Exception as exc:  # pragma: no cover - system-level failure path
            _logger.exception("Minecraft server launch failed")
            await message.channel.send(
                f"The server launch bailed with an error: `{exc}`."
            )
            return

        await message.channel.send(
            "Main Minecraft server launch command sent! Grab your gear and hop in. 🎮"
        )

    async def _handle_server_status(self, message: Message) -> None:
        """Report which Minecraft servers are active along with tunnel info."""

        async with message.channel.typing():
            status = await _collect_server_status()

        await message.channel.send(_format_server_status(status))

    async def _handle_stop_server(self, message: Message) -> None:
        """Stop the requested Minecraft server."""

        target = _parse_stopserver_target(message.content, STOP_SERVER_COMMAND)

        async with message.channel.typing():
            status = await _collect_server_status()

            if target == "auto":
                if status.alt_running:
                    target = "alt"
                elif status.main_running:
                    target = "main"
                else:
                    await message.channel.send(
                        "No Minecraft servers are running right now — nothing to stop."
                    )
                    return

            script = MINECRAFT_SCRIPT if target == "main" else MINECRAFT_ALT_SCRIPT

            try:
                stopped = await _stop_server(script)
            except Exception as exc:  # pragma: no cover - system-level failure path
                _logger.exception("Failed to stop requested server")
                await message.channel.send(
                    f"Tried to stop the {target} server but ran into trouble: `{exc}`."
                )
                return

        if stopped:
            await message.channel.send(
                f"The {target} server received the stop command. Give it a moment to wind down."
            )
        else:
            await message.channel.send(
                f"Didn't spot an active process for the {target} server. It may already be offline."
            )


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


@dataclass(frozen=True)
class ServerStatus:
    """Container describing the current Minecraft server environment."""

    main_running: bool
    alt_running: bool
    ngrok_urls: Sequence[str]
    lan_ip: Optional[str]


async def _launch_minecraft_server(script_path: str) -> None:
    """Spawn the provided Minecraft server script in the background."""

    if not os.path.exists(script_path):
        raise RuntimeError(
            f"Launch script not found at {script_path}."
        )

    command = f"nohup {shlex.quote(script_path)} >/dev/null 2>&1 &"

    process = await asyncio.create_subprocess_exec(
        "/bin/bash",
        "-c",
        command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )

    stderr_data = await process.stderr.read()
    return_code = await process.wait()

    if return_code != 0:
        stderr_text = stderr_data.decode().strip() or "Unknown error launching server"
        raise RuntimeError(stderr_text)


async def _is_server_running(script_path: str) -> bool:
    """Determine whether a process matching the script path is running."""

    if not script_path:
        return False

    process = await asyncio.create_subprocess_exec(
        "pgrep",
        "-f",
        script_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    return await process.wait() == 0


async def _stop_server(script_path: str) -> bool:
    """Attempt to stop the server whose processes reference the script path."""

    if not os.path.exists(script_path):
        raise RuntimeError(f"Launch script not found at {script_path}.")

    process = await asyncio.create_subprocess_exec(
        "pkill",
        "-f",
        script_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )

    stderr_data = await process.stderr.read()
    return_code = await process.wait()

    if return_code == 0:
        return True

    if return_code == 1:
        return False

    stderr_text = stderr_data.decode().strip() or "Unknown error stopping server"
    raise RuntimeError(stderr_text)


async def _collect_server_status() -> ServerStatus:
    """Gather information about running servers, tunnels, and LAN IP."""

    main_running, alt_running = await asyncio.gather(
        _is_server_running(MINECRAFT_SCRIPT),
        _is_server_running(MINECRAFT_ALT_SCRIPT),
    )

    ngrok_urls = await _get_ngrok_tunnels()
    lan_ip = await _get_lan_ip()

    return ServerStatus(
        main_running=main_running,
        alt_running=alt_running,
        ngrok_urls=ngrok_urls,
        lan_ip=lan_ip,
    )


async def _get_ngrok_tunnels() -> List[str]:
    """Return the active ngrok public URLs if the local API is reachable."""

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "http://127.0.0.1:4040/api/tunnels", timeout=5
            ) as response:
                if response.status != 200:
                    return []

                data = await response.json()
    except aiohttp.ClientError:  # pragma: no cover - network failure path
        return []

    tunnels = data.get("tunnels", [])
    return [tunnel.get("public_url", "") for tunnel in tunnels if tunnel.get("public_url")]


async def _get_lan_ip() -> Optional[str]:
    """Resolve the LAN IP address without blocking the event loop."""

    return await asyncio.to_thread(_determine_lan_ip)


def _determine_lan_ip() -> Optional[str]:
    """Return the LAN IP by opening a dummy socket connection."""

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:  # pragma: no cover - network failure path
        return None


def _format_server_status(status: ServerStatus) -> str:
    """Format a Discord-ready status message for server information."""

    main_line = (
        "✅ Main server is running"
        if status.main_running
        else "⛔ Main server is stopped"
    )
    alt_line = (
        "✅ Alt server is running"
        if status.alt_running
        else "⛔ Alt server is stopped"
    )

    lines = [
        "**Minecraft Server Status**",
        f"{main_line} (`{MINECRAFT_SCRIPT}`)",
        f"{alt_line} (`{MINECRAFT_ALT_SCRIPT}`)",
    ]

    if status.ngrok_urls:
        lines.append("Ngrok tunnels: " + ", ".join(status.ngrok_urls))
    else:
        lines.append("Ngrok tunnels: none detected.")

    if status.lan_ip:
        lines.append(f"LAN address: {status.lan_ip}:{MINECRAFT_PORT}")
    else:
        lines.append("LAN address: unavailable.")

    return "\n".join(lines)


def _build_command_descriptions() -> Dict[str, str]:
    """Return a mapping describing Rufus' public bot commands."""

    return {
        f"{COMMAND_PREFIX} <message>": "Chat with Rufus' AI brain.",
        MINECRAFT_COMMAND: "Start the main Minecraft server (stops the alt server first).",
        f"{STOP_SERVER_COMMAND} [main|alt]": "Stop the requested Minecraft server (auto-detect by default).",
        SERVER_STATUS_COMMAND: "Show which servers are running plus tunnel and LAN info.",
        HELP_COMMAND: "Display this help overview.",
    }


def _format_help_message(command_descriptions: Mapping[str, str]) -> str:
    """Create a Discord-friendly help message for the available commands."""

    lines = [
        "**Rufus Command Guide**",
        "Rufus keeps the vibes high while helping with AI chats and Minecraft servers.",
        "",
    ]

    for command, description in command_descriptions.items():
        lines.append(f"• `{command}` — {description}")

    lines.append("")
    lines.append("Only actual Minecraft server log lines are sent to the dedicated log channel.")
    return "\n".join(lines)


def _summarize_commands_for_log(command_descriptions: Mapping[str, str]) -> str:
    """Return a compact one-line summary of commands for startup logging."""

    parts = [f"{cmd}: {desc}" for cmd, desc in command_descriptions.items()]
    return " | ".join(parts)


def _parse_int(value: Optional[str]) -> Optional[int]:
    """Attempt to parse an integer from a string value."""

    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        _logger.warning("Invalid integer value provided: %s", value)
        return None


def _parse_stopserver_target(message_content: str, command: str) -> str:
    """Determine which server the stop command should target."""

    remainder = message_content[len(command) :].strip()

    if not remainder:
        return "auto"

    lowered = remainder.lower()
    if lowered.startswith("main") or "primary" in lowered:
        return "main"

    if lowered.startswith("alt") or "opticraft" in lowered:
        return "alt"

    return "auto"

if __name__ == "__main__":  # pragma: no cover - CLI entry
    main()
