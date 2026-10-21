from __future__ import annotations

import unittest
from pathlib import Path

from src.config import Settings
from src.core.client import FDBot


class CommandRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = FDBot(
            Settings(
                discord_token="test-token",
                database_path=":memory:",  # type: ignore[arg-type]
                content_path=Path(__file__).resolve().parents[1] / "content" / "server_content.json",
            )
        )
        await self.bot.database.connect()
        for extension in self.bot.extensions:
            await self.bot.load_extension(extension)

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    async def test_all_feature_command_roots_are_registered(self) -> None:
        names = {command.name for command in self.bot.tree.get_commands()}
        self.assertTrue(
            {"verify", "verify-sync", "verify-status", "embed", "shift", "promotion", "server", "content", "panel"}.issubset(names)
        )

