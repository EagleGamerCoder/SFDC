from __future__ import annotations

from datetime import datetime

import discord

from src.config import Settings


async def respond(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    ephemeral: bool = True,
) -> None:
    """Reply whether an interaction has already been deferred or not."""
    if interaction.response.is_done():
        await interaction.followup.send(content, embed=embed, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content, embed=embed, ephemeral=ephemeral)


async def require_staff(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await respond(interaction, "This command can only be used in the server.")
        return False
    settings: Settings = interaction.client.settings  # type: ignore[attr-defined]
    permissions = interaction.user.guild_permissions
    allowed = permissions.administrator or permissions.manage_guild
    allowed = allowed or bool(settings.staff_role_ids.intersection(role.id for role in interaction.user.roles))
    if not allowed:
        await respond(interaction, "You need a configured staff role or Manage Server permission to use this command.")
        return False
    return True


def display_duration(started_at: str, ended_at: str | None = None) -> str:
    start = datetime.fromisoformat(started_at)
    end = datetime.fromisoformat(ended_at) if ended_at else discord.utils.utcnow()
    seconds = max(0, int((end - start).total_seconds()))
    hours, remaining = divmod(seconds, 3600)
    minutes, seconds = divmod(remaining, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def discord_time(iso_datetime: str, style: str = "R") -> str:
    timestamp = int(datetime.fromisoformat(iso_datetime).timestamp())
    return f"<t:{timestamp}:{style}>"


def nickname_from_template(settings: Settings, *, roblox_name: str, roblox_id: int, group_role: str, group_rank: int) -> str:
    try:
        nickname = settings.nickname_template.format(
            roblox_name=roblox_name,
            roblox_id=roblox_id,
            group_role=group_role,
            group_rank=group_rank,
        )
    except (KeyError, ValueError) as exc:
        raise ValueError("NICKNAME_TEMPLATE contains an unsupported field.") from exc
    nickname = " ".join(nickname.split())
    return nickname[:32] or roblox_name[:32]
