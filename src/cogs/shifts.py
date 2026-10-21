"""Shift tracking commands for active ER:LC members."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from src.utils.discord_helpers import discord_time, display_duration, require_staff, respond


class ShiftCog(commands.GroupCog, group_name="shift", group_description="Start, finish, and review server shifts."):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _check_verification(self, interaction: discord.Interaction) -> bool:
        settings = self.bot.settings  # type: ignore[attr-defined]
        if not settings.shift_requires_verification:
            return True
        record = await self.bot.database.get_verification(interaction.guild_id, interaction.user.id)  # type: ignore[attr-defined]
        if record:
            return True
        await respond(interaction, "You must verify with `/verify` before starting a shift.")
        return False

    async def _refresh_shift_panels(self, guild: discord.Guild) -> None:
        panel_cog = self.bot.get_cog("PanelCog")
        if panel_cog is not None:
            await panel_cog.refresh_guild_shift_panels(guild)

    @app_commands.command(name="start", description="Start a shift timer.")
    @app_commands.describe(note="Optional duty, division, or patrol note")
    @app_commands.guild_only()
    async def start(self, interaction: discord.Interaction, note: str | None = None) -> None:
        await self.start_from_panel(interaction, note)

    async def start_from_panel(self, interaction: discord.Interaction, note: str | None = None) -> None:
        """Shared behaviour for the slash command and persistent shift panel."""
        if interaction.guild is None:
            await respond(interaction, "Shifts can only be started inside the server.")
            return
        if not await self._check_verification(interaction):
            return
        if note and len(note) > 250:
            await respond(interaction, "Keep the shift note under 250 characters.")
            return
        shift = await self.bot.database.start_shift(interaction.guild_id, interaction.user.id, note)  # type: ignore[attr-defined]
        if shift is None:
            active = await self.bot.database.active_shift(interaction.guild_id, interaction.user.id)  # type: ignore[attr-defined]
            when = discord_time(active["started_at"]) if active else "earlier"
            await respond(interaction, f"You already have an active shift started {when}.")
            return
        await respond(interaction, f"Shift started {discord_time(shift['started_at'])}. Stay safe out there!")
        await self.bot.audit_logger.send(  # type: ignore[attr-defined]
            interaction.guild,
            "shift",
            "Shift started",
            f"{interaction.user.mention} started a shift.",
            colour=discord.Colour.green(),
            fields=(("Note", note or "—", False),),
        )
        await self._refresh_shift_panels(interaction.guild)

    @app_commands.command(name="end", description="Finish your current shift timer.")
    @app_commands.guild_only()
    async def end(self, interaction: discord.Interaction) -> None:
        await self.end_from_panel(interaction)

    async def end_from_panel(self, interaction: discord.Interaction) -> None:
        """Shared behaviour for the slash command and persistent shift panel."""
        if interaction.guild is None:
            await respond(interaction, "Shifts can only be ended inside the server.")
            return
        shift = await self.bot.database.end_shift(interaction.guild_id, interaction.user.id)  # type: ignore[attr-defined]
        if shift is None:
            await respond(interaction, "You do not have an active shift.")
            return
        duration = display_duration(shift["started_at"], shift["ended_at"])
        await respond(interaction, f"Shift ended. You were active for **{duration}**.")
        await self.bot.audit_logger.send(  # type: ignore[attr-defined]
            interaction.guild,
            "shift",
            "Shift completed",
            f"{interaction.user.mention} finished a shift after **{duration}**.",
            colour=discord.Colour.red(),
            fields=(("Started", discord_time(shift["started_at"], "f"), True), ("Note", shift["note"] or "—", True)),
        )
        await self._refresh_shift_panels(interaction.guild)

    @app_commands.command(name="status", description="See whether your shift timer is active.")
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction) -> None:
        shift = await self.bot.database.active_shift(interaction.guild_id, interaction.user.id)  # type: ignore[attr-defined]
        if shift is None:
            await respond(interaction, "You are currently off shift.")
            return
        await respond(
            interaction,
            f"You have been on shift for **{display_duration(shift['started_at'])}** "
            f"(started {discord_time(shift['started_at'])}).\nNote: {shift['note'] or '—'}",
        )

    @app_commands.command(name="history", description="Review recent shift records.")
    @app_commands.describe(member="A member to review (staff only when viewing someone else)")
    @app_commands.guild_only()
    async def history(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        member = member or interaction.user
        if not isinstance(member, discord.Member):
            await respond(interaction, "I could not identify that server member.")
            return
        if member.id != interaction.user.id and not await require_staff(interaction):
            return
        records = await self.bot.database.list_shifts(interaction.guild_id, member.id)  # type: ignore[attr-defined]
        if not records:
            await respond(interaction, f"No shift records were found for {member.mention}.")
            return
        lines = []
        for record in records:
            duration = display_duration(record["started_at"], record["ended_at"]) if record["ended_at"] else "active"
            lines.append(f"• {discord_time(record['started_at'], 'd')} — **{duration}** ({record['note'] or 'no note'})")
        embed = discord.Embed(title=f"Recent shifts: {member.display_name}", description="\n".join(lines), colour=discord.Colour.blurple())
        await respond(interaction, embed=embed)

    @app_commands.command(name="active", description="List members currently on shift.")
    @app_commands.check(require_staff)
    @app_commands.guild_only()
    async def active(self, interaction: discord.Interaction) -> None:
        records = await self.bot.database.list_active_shifts(interaction.guild_id)  # type: ignore[attr-defined]
        if not records:
            await respond(interaction, "No one is currently on shift.")
            return
        lines = []
        for record in records[:25]:
            member = interaction.guild.get_member(record["discord_user_id"])
            label = member.mention if member else f"<@{record['discord_user_id']}>"
            lines.append(f"• {label} — {display_duration(record['started_at'])} ({record['note'] or 'no note'})")
        embed = discord.Embed(title=f"Active shifts ({len(records)})", description="\n".join(lines), colour=discord.Colour.green())
        if len(records) > 25:
            embed.set_footer(text=f"Showing the first 25 of {len(records)} active shifts.")
        await respond(interaction, embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ShiftCog(bot))

