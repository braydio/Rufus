"""Discord bot entry point for the Rufus project.

This module hosts a minimal Discord client that forwards prompts to an AI
completion endpoint while speaking with an upbeat personality. The focus is on
maintainability and clarity rather than feature bloat.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import socket
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Sequence

import aiohttp

# Optional imports for testability: allow running unit tests without discord/dotenv installed
DISCORD_AVAILABLE = True
try:
    import discord
    from discord import Message
except Exception:  # pragma: no cover - allows tests without discord installed
    DISCORD_AVAILABLE = False

    class _DiscordClientStub:
        def __init__(self, *args, **kwargs):
            pass

    class _DiscordStub:
        Client = _DiscordClientStub

    discord = _DiscordStub()  # type: ignore

    class Message:  # minimal placeholder for type hints
        ...

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - allow running tests without python-dotenv
    def load_dotenv() -> None:  # type: ignore
        return None

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = os.getenv("API_URL", "http://localhost:5051/v1/chat/completions")
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", "..ai")
MINECRAFT_COMMAND = os.getenv("MINECRAFT_COMMAND", "..startmc")
DISCORD_LOG_CHANNEL_ID = os.getenv(
    "DISCORD_LOG_CHANNEL_ID",
)
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
MINECRAFT_PORT = os.getenv("MINECRAFT_PORT", "25565")
MAX_DISCORD_MESSAGE = 1900
MAX_HISTORY = 6

# Process-match pattern for pgrep when checking if Minecraft is running
MINECRAFT_PGREP = os.getenv(
    "MINECRAFT_PGREP",
    os.path.basename(MINECRAFT_SCRIPT) if MINECRAFT_SCRIPT else "java",
)

# ngrok configuration (defaults to TCP tunnel on the Minecraft port)
NGROK_BIN = os.getenv("NGROK_BIN", "ngrok")
NGROK_API_URL = os.getenv("NGROK_API_URL", "http://127.0.0.1:4040/api/tunnels")
NGROK_AUTHTOKEN = os.getenv("NGROK_AUTHTOKEN")
NGROK_REGION = os.getenv("NGROK_REGION")
NGROK_CACHE_PATH = os.path.expanduser(
    os.getenv("NGROK_CACHE_PATH", "~/.cache/rufus/ngrok.json")
)

# Build the ngrok command to expose the Minecraft port via TCP
NGROK_CMD = [NGROK_BIN, "tcp", str(MINECRAFT_PORT)]
if NGROK_AUTHTOKEN:
    NGROK_CMD += ["--authtoken", NGROK_AUTHTOKEN]
if NGROK_REGION:
    NGROK_CMD += ["--region", NGROK_REGION]

MINECRAFT_LOG_CHANNEL_ID = os.getenv("MINECRAFT_LOG_CHANNEL_ID")

SYSTEM_PROMPT = (
    "You are Rufus, an upbeat surf coach turned AI companion. You respond with "
    "encouragement, helpful details, and beachy enthusiasm without going overboard."
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
_logger = logging.getLogger("rufus.bot")


# ---------------------------------------------------------------------------
# OpenAI-compatible completion
# ---------------------------------------------------------------------------


async def request_completion(messages: List[Dict[str, str]]) -> str:
    """Call the configured completion API and return the assistant's text."""
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
    except (KeyError, IndexError, AttributeError) as exc:
        raise RuntimeError("API response missing choices/message content") from exc


# ---------------------------------------------------------------------------
# Discord log piping (optional)
# ---------------------------------------------------------------------------


class DiscordQueueHandler(logging.Handler):
    """Logging handler that pushes formatted records into RufusBot's queue."""

    def __init__(self, bot: "RufusBot", level=logging.INFO) -> None:
        super().__init__(level=level)
        self.bot = bot
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            if getattr(self.bot, "_log_queue", None) is not None:
                self.bot._log_queue.put_nowait(msg)
        except Exception:
            # Never let logging explode
            pass


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------


class RufusBot(discord.Client):
    """Discord client that handles AI chat requests with lightweight context."""

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._channel_histories: Dict[int, Deque[Dict[str, str]]] = {}
        self._log_queue: Optional[asyncio.Queue[str]] = None
        self._log_worker_task: Optional[asyncio.Task] = None

    async def setup_hook(self) -> None:
        """Configure Discord logging bridge and startup note."""
        _logger.info("Rufus bot starting up")
        _logger.info(
            "Command overview: %s",
    (
        "No commands registered."
        if not getattr(self, "_command_descriptions", None)
        else "; ".join(
            f"{name}: {description}"
            for name, description in sorted(
                getattr(self, "_command_descriptions", {}).items(),
                key=lambda pair: str(pair[0]),
            )
        )
    ),
        )

        # Optional Discord logging: attach a queue + handler
        if DISCORD_LOG_CHANNEL_ID is not None:
            self._log_queue = asyncio.Queue()
            handler = DiscordQueueHandler(self)
            logging.getLogger().addHandler(handler)  # root
            logging.getLogger("rufus.bot").addHandler(handler)  # local
            self._log_worker_task = asyncio.create_task(self._discord_log_worker())
            _logger.info("Discord log channel enabled: %s", DISCORD_LOG_CHANNEL_ID)
        else:
            _logger.info("Discord log channel not configured; console-only logs.")

    async def _discord_log_worker(self) -> None:
        """Background task that forwards log lines to the configured Discord channel."""
        if self._log_queue is None:
            return
        # Wait until the bot is fully ready
        await self.wait_until_ready()
        channel = None
        if DISCORD_LOG_CHANNEL_ID is not None:
            channel = self.get_channel(DISCORD_LOG_CHANNEL_ID)
            if channel is None:
                # Try fetching if not cached
                try:
                    channel = await self.fetch_channel(DISCORD_LOG_CHANNEL_ID)
                except Exception as e:
                    _logger.warning("Unable to fetch Discord log channel: %s", e)

        # Drain queue and post; if channel missing, just drop quietly
        while not self.is_closed():
            try:
                msg = await self._log_queue.get()
                if channel:
                    # Chunk long messages
                    for chunk in _chunk_message(msg):
                        try:
                            await channel.send(f"```{chunk}```")
                        except Exception:
                            # Avoid tight failure loops
                            await asyncio.sleep(1.0)
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.5)

    async def on_ready(self) -> None:
        _logger.info("Logged in as %s", self.user)
        # Startup tunnel visibility
        try:
            tunnel = await _get_ngrok_tunnel()
            if tunnel:
                _logger.info("Existing ngrok tunnel detected at startup: %s", tunnel)
            else:
                _logger.info("No ngrok tunnel active at startup.")
        except Exception as e:
            _logger.warning("Could not query ngrok on startup: %s", e)

    async def on_message(self, message: Message) -> None:
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

        if not message.content.startswith(COMMAND_PREFIX):
            return

        user_prompt = message.content[len(COMMAND_PREFIX) :].strip()
        if not user_prompt:
            await message.channel.send(
                "Hey there! Toss a question after the command so I can help. 🤙"
            )
            return

        history = self._channel_histories.setdefault(
            message.channel.id, deque(maxlen=MAX_HISTORY)
        )
        history.append(
            {"role": "user", "content": f"{message.author.display_name}: {user_prompt}"}
        )

        chat_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        chat_messages.extend(history)

        async with message.channel.typing():
            try:
                reply = await request_completion(chat_messages)
            except Exception:
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
            "Waxing the board and firing up the Minecraft server... 🏄"
        )

        # Duplicate-launch guard
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
            await message.channel.send(f"Server launch error: `{exc}`")
            return

        # Ensure ngrok tunnel
        try:
            tunnel_url = await _ensure_ngrok_tunnel()
            await message.channel.send(
                f"🌍 **Minecraft tunnel active!**\n`{_format_tunnel_address(tunnel_url)}`"
            )
        except Exception as exc:
            _logger.exception("ngrok tunnel setup failed")
            await message.channel.send(
                f"Server launched but ngrok failed to initialize: `{exc}`"
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _chunk_message(text: str) -> List[str]:
    """Split a long response into Discord-safe chunks."""
    if not text:
        return ["Rufus is momentarily speechless, try again! 🤔"]
    return [
        text[i : i + MAX_DISCORD_MESSAGE]
        for i in range(0, len(text), MAX_DISCORD_MESSAGE)
    ]


def _format_tunnel_address(url: str) -> str:
    # ngrok returns tcp://host:port – Discord users only need host:port
    return url.replace("tcp://", "").strip()


async def _is_minecraft_running() -> bool:
    """Best-effort process check to prevent duplicate launches."""
    proc = await asyncio.create_subprocess_exec(
        "pgrep",
        "-f",
        MINECRAFT_PGREP,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    running = bool(stdout.strip())
    _logger.info("Minecraft running: %s", running)
    return running


async def _launch_minecraft_server() -> None:
    """Launch the Minecraft server with detailed logging and correct working directory."""
    mc_dir = os.path.dirname(MINECRAFT_SCRIPT)

    if not os.path.exists(MINECRAFT_SCRIPT):
        _logger.error("Launch script missing: %s", MINECRAFT_SCRIPT)
        raise RuntimeError(f"Launch script not found at {MINECRAFT_SCRIPT}")

    _logger.info("Launching Minecraft from directory: %s", mc_dir)

    # Log file for stdout/stderr
    log_path = os.path.join(mc_dir, "rufus_launch.log")
    command = "nohup ./run.sh >> rufus_launch.log 2>&1 &"

    _logger.debug("Full launch command: %s", command)

    process = await asyncio.create_subprocess_exec(
        "/bin/bash",
        "-c",
        command,
        cwd=mc_dir,  # Run in the Minecraft directory (fixes @user_jvm_args.txt resolution)
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    _logger.info("Subprocess started (PID %s)", process.pid)
    stderr_data = await process.stderr.read()
    return_code = await process.wait()

    if return_code != 0:
        stderr_text = stderr_data.decode().strip() or "Unknown error"
        _logger.error("Server launch failed (code %s): %s", return_code, stderr_text)
        raise RuntimeError(stderr_text)

    _logger.info("Server launch successful; output logged to %s", log_path)


# ------------------------ ngrok management ------------------------


async def _get_ngrok_tunnel() -> Optional[str]:
    """Return the public TCP address from an active ngrok tunnel, or None if not found."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(NGROK_API_URL, timeout=5) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        for tunnel in data.get("tunnels", []):
            if tunnel.get("proto") == "tcp":
                return tunnel.get("public_url")
        return None
    except Exception as e:
        _logger.debug("ngrok API check failed: %s", e)
        return None


def _save_tunnel_cache(url: str) -> None:
    try:
        with open(NGROK_CACHE_PATH, "w") as f:
            json.dump({"url": url}, f)
    except Exception as e:
        _logger.debug("Failed to write ngrok cache: %s", e)


def _load_tunnel_cache() -> Optional[str]:
    try:
        if not os.path.exists(NGROK_CACHE_PATH):
            return None
        with open(NGROK_CACHE_PATH) as f:
            data = json.load(f)
        return data.get("url")
    except Exception as e:
        _logger.debug("Failed to read ngrok cache: %s", e)
        return None


async def _ensure_ngrok_tunnel() -> str:
    """Ensure ngrok is running and return its public TCP URL."""
    # If a tunnel exists, reuse it.
    existing = await _get_ngrok_tunnel()
    if existing:
        _logger.info("Existing ngrok tunnel found: %s", existing)
        _save_tunnel_cache(existing)
        return existing

    # Check for ngrok process anyway; if running but no tunnel, it'll likely be a stale session
    proc_check = await asyncio.create_subprocess_exec(
        "pgrep",
        "-x",
        "ngrok",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc_check.communicate()
    running = bool(stdout.strip())
    _logger.info("ngrok process running: %s", running)

    # Start a new tunnel if none detected
    if not running:
        _logger.info("Starting new ngrok tunnel for port 25565...")
        process = await asyncio.create_subprocess_exec(
            *NGROK_CMD,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        _logger.info("ngrok started (PID %s)", process.pid)

    # Give ngrok API a few seconds to come online (retry loop)
    tunnel_url = None
    for _ in range(12):  # up to ~12 seconds
        await asyncio.sleep(1)
        tunnel_url = await _get_ngrok_tunnel()
        if tunnel_url:
            break

    if not tunnel_url:
        # As a last resort, if we have a cached value, surface it (may be stale)
        cached = _load_tunnel_cache()
        if cached:
            _logger.warning(
                "Using cached ngrok URL (live tunnel not confirmed): %s", cached
            )
            return cached
        raise RuntimeError("ngrok started, but no tunnel found in API response")

    _logger.info("New ngrok tunnel ready: %s", tunnel_url)
    _save_tunnel_cache(tunnel_url)
    return tunnel_url


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    if not DISCORD_AVAILABLE:
        raise RuntimeError(
            "discord.py is not installed. Install with `pip install discord.py` to run the bot."
        )

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
        raise RuntimeError(f"Launch script not found at {script_path}.")

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
    return [
        tunnel.get("public_url", "") for tunnel in tunnels if tunnel.get("public_url")
    ]


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
        "✅ Alt server is running" if status.alt_running else "⛔ Alt server is stopped"
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
def _summarize_commands_for_log(command_descriptions):
    """
    Build a short, stable string summary of the bot commands
    suitable for logging at startup.
    """
    if not command_descriptions:
        return "No commands registered."

    try:
        items = command_descriptions.items()
    except AttributeError:
        # Fallback if an iterable of pairs is passed instead of a mapping.
        items = command_descriptions

    parts = [f"{name}: {description}" for name, description in sorted(items, key=lambda pair: str(pair[0]))]
    return "; ".join(parts)
