"""Editable, fixed-content embeds used for server information channels."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import discord


class ContentConfigurationError(ValueError):
    """The information-content JSON is invalid or incomplete."""


@dataclass(frozen=True, slots=True)
class InformationEmbed:
    key: str
    title: str
    description: str
    channel_id: int | None
    colour: int
    footer: str | None
    fields: tuple[tuple[str, str, bool], ...]
    links: tuple[tuple[str, str], ...]


class ContentLibrary:
    """Loads administrator-maintained information embeds from a local JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._items: dict[str, InformationEmbed] = {}

    def reload(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ContentConfigurationError(f"Content file is missing: {self.path}") from exc
        except json.JSONDecodeError as exc:
            raise ContentConfigurationError(f"Content JSON is invalid: {exc.msg} (line {exc.lineno}).") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("information_embeds"), dict):
            raise ContentConfigurationError("Content JSON must contain an 'information_embeds' object.")

        loaded: dict[str, InformationEmbed] = {}
        for key, value in raw["information_embeds"].items():
            if not isinstance(key, str) or not isinstance(value, dict):
                raise ContentConfigurationError("Each information embed needs a string key and object value.")
            loaded[key] = self._parse_item(key, value)
        self._items = loaded

    def _parse_item(self, key: str, value: dict[str, Any]) -> InformationEmbed:
        title = value.get("title")
        description = value.get("description")
        if not isinstance(title, str) or not title.strip() or len(title) > 256:
            raise ContentConfigurationError(f"'{key}.title' must be a non-empty string up to 256 characters.")
        if not isinstance(description, str) or len(description) > 4096:
            raise ContentConfigurationError(f"'{key}.description' must be a string up to 4096 characters.")

        channel_value = value.get("channel_id")
        if channel_value in (None, 0, "", "0"):
            channel_id = None
        else:
            try:
                channel_id = int(channel_value)
            except (TypeError, ValueError) as exc:
                raise ContentConfigurationError(f"'{key}.channel_id' must be a numeric Discord channel ID.") from exc

        colour = self._parse_colour(key, value.get("colour", "5865F2"))
        footer = value.get("footer")
        if footer is not None and (not isinstance(footer, str) or len(footer) > 2048):
            raise ContentConfigurationError(f"'{key}.footer' must be a string up to 2048 characters.")

        fields_raw = value.get("fields", [])
        if not isinstance(fields_raw, list) or len(fields_raw) > 25:
            raise ContentConfigurationError(f"'{key}.fields' must contain at most 25 fields.")
        fields: list[tuple[str, str, bool]] = []
        for field in fields_raw:
            if not isinstance(field, dict) or not isinstance(field.get("name"), str) or not isinstance(field.get("value"), str):
                raise ContentConfigurationError(f"Every field in '{key}' needs string 'name' and 'value' values.")
            if len(field["name"]) > 256 or len(field["value"]) > 1024:
                raise ContentConfigurationError(f"A field in '{key}' exceeds Discord's embed limits.")
            fields.append((field["name"], field["value"], bool(field.get("inline", False))))

        links_raw = value.get("links", [])
        if not isinstance(links_raw, list) or len(links_raw) > 5:
            raise ContentConfigurationError(f"'{key}.links' must contain at most five links.")
        links: list[tuple[str, str]] = []
        for link in links_raw:
            if not isinstance(link, dict) or not isinstance(link.get("label"), str) or not isinstance(link.get("url"), str):
                raise ContentConfigurationError(f"Every link in '{key}' needs string 'label' and 'url' values.")
            if not link["url"].startswith("https://"):
                raise ContentConfigurationError(f"The URL for '{key}' link '{link['label']}' must start with https://.")
            links.append((link["label"][:80], link["url"]))

        return InformationEmbed(key, title, description, channel_id, colour, footer, tuple(fields), tuple(links))

    @staticmethod
    def _parse_colour(key: str, value: Any) -> int:
        if isinstance(value, int) and 0 <= value <= 0xFFFFFF:
            return value
        if isinstance(value, str):
            try:
                colour = int(value.strip().removeprefix("#").removeprefix("0x"), 16)
            except ValueError as exc:
                raise ContentConfigurationError(f"'{key}.colour' must be a hex colour such as #5865F2.") from exc
            if 0 <= colour <= 0xFFFFFF:
                return colour
        raise ContentConfigurationError(f"'{key}.colour' must be a hex colour such as #5865F2.")

    def items(self) -> tuple[InformationEmbed, ...]:
        return tuple(self._items.values())

    def get(self, key: str) -> InformationEmbed:
        if not self._items:
            self.reload()
        try:
            return self._items[key]
        except KeyError as exc:
            raise ContentConfigurationError(f"No information embed is configured with the key '{key}'.") from exc

    @staticmethod
    def make_message(item: InformationEmbed) -> tuple[discord.Embed, discord.ui.View | None]:
        embed = discord.Embed(title=item.title, description=item.description, colour=discord.Colour(item.colour))
        for name, value, inline in item.fields:
            embed.add_field(name=name, value=value, inline=inline)
        if item.footer:
            embed.set_footer(text=item.footer)
        if not item.links:
            return embed, None
        view = discord.ui.View(timeout=None)
        for label, url in item.links:
            view.add_item(discord.ui.Button(label=label, url=url))
        return embed, view
