from __future__ import annotations

import unittest

from src.data.database import Database


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.database = Database(":memory:")
        await self.database.connect()

    async def asyncTearDown(self) -> None:
        await self.database.close()

    async def test_only_one_active_shift_per_member(self) -> None:
        first = await self.database.start_shift(1, 2, "Patrol")
        duplicate = await self.database.start_shift(1, 2, "Second patrol")
        finished = await self.database.end_shift(1, 2)

        self.assertIsNotNone(first)
        self.assertIsNone(duplicate)
        self.assertEqual(finished["status"], "complete")

    async def test_verification_is_replaced_on_resync(self) -> None:
        await self.database.upsert_verification(
            guild_id=1,
            discord_user_id=2,
            roblox_user_id=3,
            roblox_username="FirstName",
            group_role_id="10",
            group_role_name="Cadet",
            group_rank=1,
        )
        await self.database.upsert_verification(
            guild_id=1,
            discord_user_id=2,
            roblox_user_id=3,
            roblox_username="NewName",
            group_role_id="20",
            group_role_name="Officer",
            group_rank=2,
        )

        record = await self.database.get_verification(1, 2)
        self.assertEqual(record["roblox_username"], "NewName")
        self.assertEqual(record["group_role_name"], "Officer")

    async def test_panel_deployment_is_replaced_and_removable(self) -> None:
        await self.database.upsert_panel(1, "shift", 10, 20)
        await self.database.upsert_panel(1, "shift", 11, 21)

        panel = await self.database.get_panel(1, "shift")
        self.assertEqual(panel["channel_id"], 11)
        self.assertEqual(panel["message_id"], 21)

        await self.database.delete_panel(1, "shift")
        self.assertIsNone(await self.database.get_panel(1, "shift"))

