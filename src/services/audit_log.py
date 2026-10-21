"""Consistent, optional channel logging for administrator review."""

from __future__ import annotations

from collections.abc import Iterable

import discord

from src.config import Settings


class AuditLogger:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send(
        self,
        guild: discord.Guild,
        category: str,
        title: str,
        description: str,
        *,
        colour: discord.Colour = discord.Colour.blurple(),
        fields: Iterable[tuple[str, str, bool]] = (),
    ) -> None:
        channel_id = self.settings.log_channels.get(category) or self.settings.log_channels.get("admin")
        if channel_id is None:
            return
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return

        embed = discord.Embed(title=title[:256], description=description[:4096], colour=colour, timestamp=discord.utils.utcnow())
        for name, value, inline in fields:
            embed.add_field(name=name[:256], value=value[:1024] or "—", inline=inline)
        try:
            await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            # Logging must not break a successful command when a channel was removed
            # or the bot temporarily cannot post to it.
            return

