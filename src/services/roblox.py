"""Roblox public-profile and Open Cloud group integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import aiohttp


class RobloxAPIError(RuntimeError):
    """A user-safe failure returned by a Roblox endpoint."""


@dataclass(frozen=True, slots=True)
class RobloxUser:
    id: int
    name: str
    display_name: str


@dataclass(frozen=True, slots=True)
class GroupMembership:
    user_id: int
    role_id: str
    role_name: str
    rank: int
    role_path: str | None = None


class RobloxService:
    PUBLIC_USERS_URL = "https://users.roblox.com/v1/usernames/users"
    PUBLIC_GROUPS_URL = "https://groups.roblox.com/v2/users/{user_id}/groups/roles"
    CLOUD_BASE_URL = "https://apis.roblox.com/cloud/v2"

    def __init__(self, session: aiohttp.ClientSession, *, group_id: int | None, api_key: str | None) -> None:
        self.session = session
        self.group_id = group_id
        self.api_key = api_key

    async def _json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            async with self.session.request(method, url, **kwargs) as response:
                if response.status >= 400:
                    detail = (await response.text())[:300]
                    raise RobloxAPIError(f"Roblox returned {response.status}: {detail or 'request failed'}")
                return await response.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise RobloxAPIError("Roblox could not be reached. Please try again shortly.") from exc

    async def resolve_username(self, username: str) -> RobloxUser:
        normalized = username.strip()
        if not normalized or len(normalized) > 20:
            raise RobloxAPIError("Enter a valid Roblox username.")
        response = await self._json(
            "POST",
            self.PUBLIC_USERS_URL,
            json={"usernames": [normalized], "excludeBannedUsers": False},
        )
        users = response.get("data", [])
        if not users:
            raise RobloxAPIError("That Roblox username could not be found.")
        user = users[0]
        return RobloxUser(id=int(user["id"]), name=str(user["name"]), display_name=str(user.get("displayName", user["name"])))

    async def get_membership(self, user_id: int) -> GroupMembership:
        if self.group_id is None:
            raise RobloxAPIError("Roblox group verification has not been configured yet.")
        response = await self._json("GET", self.PUBLIC_GROUPS_URL.format(user_id=user_id))
        for entry in response.get("data", []):
            group = entry.get("group", {})
            if int(group.get("id", 0)) != self.group_id:
                continue
            role = entry.get("role", {})
            return GroupMembership(
                user_id=user_id,
                role_id=str(role.get("id", "")),
                role_name=str(role.get("name", "Member")),
                rank=int(role.get("rank", 0)),
                role_path=f"groups/{self.group_id}/roles/{role.get('id')}",
            )
        raise RobloxAPIError("That Roblox account is not a member of the configured group.")

    async def assign_role(self, user_id: int, role_id: int) -> None:
        """Assign a role through Roblox Open Cloud, never with a user cookie."""
        if self.group_id is None or not self.api_key:
            raise RobloxAPIError("Roblox promotion is not configured yet.")
        await self._json(
            "POST",
            f"{self.CLOUD_BASE_URL}/groups/{self.group_id}/memberships/{user_id}:assignRole",
            headers={"x-api-key": self.api_key},
            json={"role": f"groups/{self.group_id}/roles/{role_id}"},
        )

    async def unassign_role(self, user_id: int, role_id: str) -> None:
        if self.group_id is None or not self.api_key:
            raise RobloxAPIError("Roblox promotion is not configured yet.")
        await self._json(
            "POST",
            f"{self.CLOUD_BASE_URL}/groups/{self.group_id}/memberships/{user_id}:unassignRole",
            headers={"x-api-key": self.api_key},
            json={"role": f"groups/{self.group_id}/roles/{role_id}"},
        )

