"""Staff-controlled information embeds."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from src.utils.discord_helpers import require_staff, respond


def _parse_colour(value: str | None) -> discord.Colour:
    if not value:
        return discord.Colour.blurple()
    normalized = value.strip().removeprefix("#")
    if len(normalized) != 6:
        raise ValueError("Colour must be a six-digit hex value, for example #5865F2.")
    try:
        return discord.Colour(int(normalized, 16))
    except ValueError as exc:
        raise ValueError("Colour must be a six-digit hex value, for example #5865F2.") from exc


class EmbedCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="embed", description="Send a polished information embed to a text channel.")
    @app_commands.describe(
        title="Embed heading",
        message="Embed body",
        channel="Where to send it (defaults to this channel)",
        colour="Optional hex colour, e.g. #5865F2",
        footer="Optional small footer text",
    )
    @app_commands.check(require_staff)
    @app_commands.guild_only()
    async def send_embed(
        self,
        interaction: discord.Interaction,
        title: str,
        message: str,
        channel: discord.TextChannel | None = None,
        colour: str | None = None,
        footer: str | None = None,
    ) -> None:
        if len(title) > 256 or len(message) > 4096 or (footer and len(footer) > 2048):
            await respond(interaction, "Keep the title under 256 characters, the message under 4,096, and the footer under 2,048.")
            return
        try:
            embed_colour = _parse_colour(colour)
        except ValueError as exc:
            await respond(interaction, str(exc))
            return

        destination = channel or interaction.channel
        if not isinstance(destination, discord.TextChannel):
            await respond(interaction, "Choose a standard text channel for this embed.")
            return
        embed = discord.Embed(title=title, description=message, colour=embed_colour, timestamp=discord.utils.utcnow())
        if footer:
            embed.set_footer(text=footer)
        try:
            sent = await destination.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            await respond(interaction, "I cannot send messages in that channel.")
            return
        except discord.HTTPException:
            await respond(interaction, "Discord could not send that embed. Please try again.")
            return

        await respond(interaction, f"Embed sent to {destination.mention}: [open message]({sent.jump_url})")
        await self.bot.audit_logger.send(  # type: ignore[attr-defined]
            interaction.guild,
            "admin",
            "Information embed sent",
            f"{interaction.user.mention} sent an embed to {destination.mention}.",
            fields=(("Title", title, False),),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EmbedCog(bot))

