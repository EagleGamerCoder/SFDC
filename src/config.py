"""Configuration loading and validation for the bot.

Secrets deliberately come only from environment variables. This keeps tokens and
Roblox API keys out of source control while leaving non-secret server mappings
easy to adjust in a deployment environment.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


class ConfigurationError(RuntimeError):
    """Raised when a required configuration value is absent or malformed."""


def _load_local_env_file() -> None:
    """Load a simple local .env file without adding another runtime dependency.

    Real deployment platforms normally inject environment variables themselves;
    this merely makes local first-run setup convenient. Existing environment
    values always win over the file.
    """
    env_file = Path(__file__).resolve().parents[1] / ".env"
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a numeric ID.") from exc


def _boolean(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"{name} must be true or false.")


def _id_mapping(name: str) -> dict[str, int]:
    raw = os.getenv(name, "{}").strip() or "{}"
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"{name} must contain valid JSON.") from exc
    if not isinstance(mapping, dict):
        raise ConfigurationError(f"{name} must be a JSON object.")

    parsed: dict[str, int] = {}
    for key, value in mapping.items():
        try:
            parsed[str(key)] = int(value)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(f"Every value in {name} must be a numeric ID.") from exc
    return parsed


def _staff_role_ids() -> frozenset[int]:
    raw = os.getenv("STAFF_ROLE_IDS", "")
    if not raw.strip():
        return frozenset()
    try:
        return frozenset(int(role_id.strip()) for role_id in raw.split(",") if role_id.strip())
    except ValueError as exc:
        raise ConfigurationError("STAFF_ROLE_IDS must be a comma-separated list of role IDs.") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    database_path: Path
    content_path: Path
    development_guild_id: int | None = None
    roblox_group_id: int | None = None
    roblox_open_cloud_api_key: str | None = None
    roblox_role_map: dict[str, int] = field(default_factory=dict)
    promotion_roles: dict[str, int] = field(default_factory=dict)
    replace_promotion_role: bool = False
    staff_role_ids: frozenset[int] = field(default_factory=frozenset)
    verified_role_id: int | None = None
    nickname_template: str = "[{group_role}] {roblox_name}"
    shift_requires_verification: bool = False
    log_channels: dict[str, int] = field(default_factory=dict)

    @property
    def roblox_group_is_configured(self) -> bool:
        return self.roblox_group_id is not None

    @property
    def promotion_is_configured(self) -> bool:
        return self.roblox_group_id is not None and bool(self.roblox_open_cloud_api_key)

    @classmethod
    def from_environment(cls) -> "Settings":
        _load_local_env_file()
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token or token == "put-your-bot-token-here":
            raise ConfigurationError("DISCORD_TOKEN is required. Copy .env.example and add the bot token.")

        template = os.getenv("NICKNAME_TEMPLATE", "[{group_role}] {roblox_name}").strip()
        if not template:
            raise ConfigurationError("NICKNAME_TEMPLATE cannot be blank.")

        root = Path(__file__).resolve().parents[1]
        return cls(
            discord_token=token,
            database_path=root / "data" / "bot.sqlite3",
            content_path=root / "content" / "server_content.json",
            development_guild_id=_optional_int("DISCORD_GUILD_ID"),
            roblox_group_id=_optional_int("ROBLOX_GROUP_ID"),
            roblox_open_cloud_api_key=os.getenv("ROBLOX_OPEN_CLOUD_API_KEY", "").strip() or None,
            roblox_role_map=_id_mapping("ROBLOX_ROLE_MAP_JSON"),
            promotion_roles=_id_mapping("ROBLOX_PROMOTION_ROLES_JSON"),
            replace_promotion_role=_boolean("ROBLOX_REPLACE_PROMOTION_ROLE"),
            staff_role_ids=_staff_role_ids(),
            verified_role_id=_optional_int("VERIFIED_ROLE_ID"),
            nickname_template=template,
            shift_requires_verification=_boolean("SHIFT_REQUIRE_VERIFICATION"),
            log_channels=_id_mapping("LOG_CHANNELS_JSON"),
        )

