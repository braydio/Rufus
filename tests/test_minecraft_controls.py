"""Tests for the Minecraft server helper utilities."""

from __future__ import annotations

import unittest

from main import (
    MINECRAFT_ALT_SCRIPT,
    MINECRAFT_PORT,
    MINECRAFT_SCRIPT,
    ServerStatus,
    _format_server_status,
    _parse_stopserver_target,
)


class FormatServerStatusTests(unittest.TestCase):
    """Verify the status formatter produces informative summaries."""

    def test_format_includes_paths_and_network_details(self) -> None:
        """Status output should reference script paths, tunnels, and LAN info."""

        status = ServerStatus(
            main_running=True,
            alt_running=False,
            ngrok_urls=["https://example.ngrok.io"],
            lan_ip="192.168.1.23",
            cloudflared_url="minecraft.example.com:25565",
        )

        result = _format_server_status(status)

        self.assertIn("Main server is running", result)
        self.assertIn(MINECRAFT_SCRIPT, result)
        self.assertIn(MINECRAFT_ALT_SCRIPT, result)
        self.assertIn("https://example.ngrok.io", result)
        self.assertIn(f"{status.lan_ip}:{MINECRAFT_PORT}", result)
        self.assertIn("Ngrok tunnels", result)
        self.assertIn("Cloudflared tunnel", result)
        self.assertIn("minecraft.example.com:25565", result)

    def test_format_handles_missing_network_details(self) -> None:
        """When no tunnels or LAN IP exist the output calls that out explicitly."""

        status = ServerStatus(
            main_running=False,
            alt_running=False,
            ngrok_urls=[],
            lan_ip=None,
            cloudflared_url=None,
        )

        result = _format_server_status(status)

        self.assertIn("none detected", result)
        self.assertIn("unavailable", result)
        self.assertIn("Cloudflared tunnel", result)


class StopServerParsingTests(unittest.TestCase):
    """Ensure the stop command target parser resolves expected values."""

    def test_defaults_to_auto_when_no_argument(self) -> None:
        """No additional tokens should leave the parser in auto mode."""

        self.assertEqual(_parse_stopserver_target("..stopserver", "..stopserver"), "auto")

    def test_detects_main_and_alt_keywords(self) -> None:
        """Keywords should route the stop command to the appropriate server."""

        self.assertEqual(_parse_stopserver_target("..stopserver main", "..stopserver"), "main")
        self.assertEqual(_parse_stopserver_target("..stopserver Alt", "..stopserver"), "alt")
        self.assertEqual(
            _parse_stopserver_target("..stopserver primary server", "..stopserver"),
            "main",
        )
        self.assertEqual(
            _parse_stopserver_target("..stopserver opticraft vr", "..stopserver"),
            "alt",
        )

    def test_unknown_arguments_fall_back_to_auto(self) -> None:
        """Unexpected tokens should not break parsing and fall back to auto mode."""

        self.assertEqual(
            _parse_stopserver_target("..stopserver somethingelse", "..stopserver"),
            "auto",
        )


if __name__ == "__main__":
    unittest.main()
