"""Small SQLite repository for verification, shifts, and promotion history."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """An async-safe wrapper around the bot's local SQLite database."""

    def __init__(self, path: Path | str) -> None:
        self.path = path
        self.connection: sqlite3.Connection | None = None
        self.lock = asyncio.Lock()

    async def connect(self) -> None:
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS verifications (
                guild_id INTEGER NOT NULL,
                discord_user_id INTEGER NOT NULL,
                roblox_user_id INTEGER NOT NULL,
                roblox_username TEXT NOT NULL,
                group_role_id TEXT NOT NULL,
                group_role_name TEXT NOT NULL,
                group_rank INTEGER NOT NULL,
                verified_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, discord_user_id)
            );

            CREATE TABLE IF NOT EXISTS shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                discord_user_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                note TEXT
            );

            CREATE UNIQUE INDEX IF NOT EXISTS one_active_shift_per_member
            ON shifts (guild_id, discord_user_id) WHERE status = 'active';

            CREATE TABLE IF NOT EXISTS promotions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                actor_discord_user_id INTEGER NOT NULL,
                target_discord_user_id INTEGER NOT NULL,
                roblox_user_id INTEGER NOT NULL,
                roblox_username TEXT NOT NULL,
                from_role TEXT NOT NULL,
                to_role TEXT NOT NULL,
                reason TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS panel_messages (
                guild_id INTEGER NOT NULL,
                panel_type TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                deployed_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, panel_type)
            );
            """
        )
        self.connection.commit()

    async def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def _require_connection(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("The database has not been connected.")
        return self.connection

    async def upsert_verification(
        self,
        *,
        guild_id: int,
        discord_user_id: int,
        roblox_user_id: int,
        roblox_username: str,
        group_role_id: str,
        group_role_name: str,
        group_rank: int,
    ) -> None:
        async with self.lock:
            connection = self._require_connection()
            connection.execute(
                """
                INSERT INTO verifications (
                    guild_id, discord_user_id, roblox_user_id, roblox_username,
                    group_role_id, group_role_name, group_rank, verified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, discord_user_id) DO UPDATE SET
                    roblox_user_id=excluded.roblox_user_id,
                    roblox_username=excluded.roblox_username,
                    group_role_id=excluded.group_role_id,
                    group_role_name=excluded.group_role_name,
                    group_rank=excluded.group_rank,
                    verified_at=excluded.verified_at
                """,
                (
                    guild_id,
                    discord_user_id,
                    roblox_user_id,
                    roblox_username,
                    group_role_id,
                    group_role_name,
                    group_rank,
                    _utc_now(),
                ),
            )
            connection.commit()

    async def get_verification(self, guild_id: int, discord_user_id: int) -> dict[str, Any] | None:
        async with self.lock:
            row = self._require_connection().execute(
                "SELECT * FROM verifications WHERE guild_id = ? AND discord_user_id = ?",
                (guild_id, discord_user_id),
            ).fetchone()
            return dict(row) if row else None

    async def count_verifications(self, guild_id: int) -> int:
        async with self.lock:
            row = self._require_connection().execute(
                "SELECT COUNT(*) AS total FROM verifications WHERE guild_id = ?", (guild_id,)
            ).fetchone()
            return int(row["total"])

    async def start_shift(self, guild_id: int, discord_user_id: int, note: str | None = None) -> dict[str, Any] | None:
        async with self.lock:
            connection = self._require_connection()
            try:
                cursor = connection.execute(
                    "INSERT INTO shifts (guild_id, discord_user_id, started_at, note) VALUES (?, ?, ?, ?)",
                    (guild_id, discord_user_id, _utc_now(), note),
                )
            except sqlite3.IntegrityError:
                return None
            connection.commit()
            return dict(connection.execute("SELECT * FROM shifts WHERE id = ?", (cursor.lastrowid,)).fetchone())

    async def active_shift(self, guild_id: int, discord_user_id: int) -> dict[str, Any] | None:
        async with self.lock:
            row = self._require_connection().execute(
                "SELECT * FROM shifts WHERE guild_id = ? AND discord_user_id = ? AND status = 'active'",
                (guild_id, discord_user_id),
            ).fetchone()
            return dict(row) if row else None

    async def end_shift(self, guild_id: int, discord_user_id: int) -> dict[str, Any] | None:
        async with self.lock:
            connection = self._require_connection()
            row = connection.execute(
                "SELECT * FROM shifts WHERE guild_id = ? AND discord_user_id = ? AND status = 'active'",
                (guild_id, discord_user_id),
            ).fetchone()
            if row is None:
                return None
            ended_at = _utc_now()
            connection.execute(
                "UPDATE shifts SET ended_at = ?, status = 'complete' WHERE id = ?",
                (ended_at, row["id"]),
            )
            connection.commit()
            completed = connection.execute("SELECT * FROM shifts WHERE id = ?", (row["id"],)).fetchone()
            return dict(completed)

    async def list_active_shifts(self, guild_id: int) -> list[dict[str, Any]]:
        async with self.lock:
            rows = self._require_connection().execute(
                "SELECT * FROM shifts WHERE guild_id = ? AND status = 'active' ORDER BY started_at ASC",
                (guild_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    async def list_shifts(self, guild_id: int, discord_user_id: int, limit: int = 10) -> list[dict[str, Any]]:
        async with self.lock:
            rows = self._require_connection().execute(
                """
                SELECT * FROM shifts WHERE guild_id = ? AND discord_user_id = ?
                ORDER BY started_at DESC LIMIT ?
                """,
                (guild_id, discord_user_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    async def count_active_shifts(self, guild_id: int) -> int:
        async with self.lock:
            row = self._require_connection().execute(
                "SELECT COUNT(*) AS total FROM shifts WHERE guild_id = ? AND status = 'active'", (guild_id,)
            ).fetchone()
            return int(row["total"])

    async def add_promotion(
        self,
        *,
        guild_id: int,
        actor_discord_user_id: int,
        target_discord_user_id: int,
        roblox_user_id: int,
        roblox_username: str,
        from_role: str,
        to_role: str,
        reason: str | None,
        status: str,
    ) -> int:
        async with self.lock:
            connection = self._require_connection()
            cursor = connection.execute(
                """
                INSERT INTO promotions (
                    guild_id, actor_discord_user_id, target_discord_user_id,
                    roblox_user_id, roblox_username, from_role, to_role,
                    reason, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    actor_discord_user_id,
                    target_discord_user_id,
                    roblox_user_id,
                    roblox_username,
                    from_role,
                    to_role,
                    reason,
                    status,
                    _utc_now(),
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    async def recent_promotions(self, guild_id: int, limit: int = 10) -> list[dict[str, Any]]:
        async with self.lock:
            rows = self._require_connection().execute(
                "SELECT * FROM promotions WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?",
                (guild_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    async def get_panel(self, guild_id: int, panel_type: str) -> dict[str, Any] | None:
        async with self.lock:
            row = self._require_connection().execute(
                "SELECT * FROM panel_messages WHERE guild_id = ? AND panel_type = ?",
                (guild_id, panel_type),
            ).fetchone()
            return dict(row) if row else None

    async def upsert_panel(self, guild_id: int, panel_type: str, channel_id: int, message_id: int) -> None:
        async with self.lock:
            connection = self._require_connection()
            connection.execute(
                """
                INSERT INTO panel_messages (guild_id, panel_type, channel_id, message_id, deployed_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, panel_type) DO UPDATE SET
                    channel_id=excluded.channel_id,
                    message_id=excluded.message_id,
                    deployed_at=excluded.deployed_at
                """,
                (guild_id, panel_type, channel_id, message_id, _utc_now()),
            )
            connection.commit()

    async def list_panels(self, panel_type: str, guild_id: int | None = None) -> list[dict[str, Any]]:
        async with self.lock:
            connection = self._require_connection()
            if guild_id is None:
                rows = connection.execute(
                    "SELECT * FROM panel_messages WHERE panel_type = ? ORDER BY guild_id", (panel_type,)
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM panel_messages WHERE panel_type = ? AND guild_id = ?", (panel_type, guild_id)
                ).fetchall()
            return [dict(row) for row in rows]

    async def delete_panel(self, guild_id: int, panel_type: str) -> None:
        async with self.lock:
            connection = self._require_connection()
            connection.execute(
                "DELETE FROM panel_messages WHERE guild_id = ? AND panel_type = ?", (guild_id, panel_type)
            )
            connection.commit()

