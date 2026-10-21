"""Staff commands for publishing the fixed information-content library."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from src.services.content_library import ContentConfigurationError
from src.utils.discord_helpers import require_staff, respond


class ContentCog(commands.GroupCog, group_name="content", group_description="Publish and manage fixed information embeds."):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def library(self):
        return self.bot.content_library  # type: ignore[attr-defined]

    @app_commands.command(name="list", description="List the fixed information embeds available to publish.")
    @app_commands.check(require_staff)
    @app_commands.guild_only()
    async def list_content(self, interaction: discord.Interaction) -> None:
        try:
            self.library.reload()
        except ContentConfigurationError as exc:
            await respond(interaction, f"The content configuration needs attention: {exc}")
            return
        items = self.library.items()
        if not items:
            await respond(interaction, "No information embeds are configured yet.")
            return
        lines = []
        for item in items:
            destination = f"<#{item.channel_id}>" if item.channel_id else "no default channel"
            lines.append(f"• `{item.key}` — {item.title} ({destination})")
        embed = discord.Embed(title="Information embed library", description="\n".join(lines), colour=discord.Colour.blurple())
        embed.set_footer(text="Edit content/server_content.json, then use /content reload.")
        await respond(interaction, embed=embed)

    @app_commands.command(name="publish", description="Publish a fixed information embed from the content library.")
    @app_commands.describe(key="The template key from /content list", channel="Optional override for the configured channel")
    @app_commands.check(require_staff)
    @app_commands.guild_only()
    async def publish(self, interaction: discord.Interaction, key: str, channel: discord.TextChannel | None = None) -> None:
        try:
            item = self.library.get(key)
        except ContentConfigurationError as exc:
            await respond(interaction, str(exc))
            return
        destination = channel
        if destination is None and item.channel_id:
            destination = interaction.guild.get_channel(item.channel_id)
        if not isinstance(destination, discord.TextChannel):
            await respond(
                interaction,
                "Choose a text channel or set a numeric `channel_id` for this template in `content/server_content.json`.",
            )
            return
        embed, view = self.library.make_message(item)
        try:
            message = await destination.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            await respond(interaction, "I cannot send messages in that channel.")
            return
        except discord.HTTPException:
            await respond(interaction, "Discord could not publish that information embed. Please try again.")
            return
        await respond(interaction, f"Published `{item.key}` in {destination.mention}: [open message]({message.jump_url})")
        await self.bot.audit_logger.send(  # type: ignore[attr-defined]
            interaction.guild,
            "admin",
            "Information content published",
            f"{interaction.user.mention} published `{item.key}` in {destination.mention}.",
            fields=(("Template", item.title, False),),
        )

    @app_commands.command(name="reload", description="Reload content/server_content.json after an administrator edits it.")
    @app_commands.check(require_staff)
    @app_commands.guild_only()
    async def reload_content(self, interaction: discord.Interaction) -> None:
        try:
            self.library.reload()
        except ContentConfigurationError as exc:
            await respond(interaction, f"The file was not reloaded: {exc}")
            return
        await respond(interaction, f"Reloaded {len(self.library.items())} information embed template(s).")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ContentCog(bot))
