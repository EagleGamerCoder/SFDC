"""General server helper commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from src.utils.discord_helpers import require_staff, respond


class ServerCog(commands.GroupCog, group_name="server", group_description="Helpful server information and member lookups."):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="stats", description="Show current server and bot activity counts.")
    @app_commands.guild_only()
    async def stats(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        members = guild.member_count or len(guild.members)
        bots = sum(member.bot for member in guild.members)
        verified = await self.bot.database.count_verifications(guild.id)  # type: ignore[attr-defined]
        active_shifts = await self.bot.database.count_active_shifts(guild.id)  # type: ignore[attr-defined]

        embed = discord.Embed(title=f"{guild.name} statistics", colour=discord.Colour.blurple(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Members", value=str(members), inline=True)
        embed.add_field(name="Humans", value=str(members - bots), inline=True)
        embed.add_field(name="Bots", value=str(bots), inline=True)
        embed.add_field(name="Verified", value=str(verified), inline=True)
        embed.add_field(name="On shift", value=str(active_shifts), inline=True)
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        await respond(interaction, embed=embed, ephemeral=False)

    @app_commands.command(name="member", description="View saved bot information for a server member.")
    @app_commands.describe(member="Member to look up (staff may inspect other members)")
    @app_commands.guild_only()
    async def member(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        member = member or interaction.user
        if not isinstance(member, discord.Member):
            await respond(interaction, "I could not identify that server member.")
            return
        if member.id != interaction.user.id and not await require_staff(interaction):
            return
        verification = await self.bot.database.get_verification(interaction.guild_id, member.id)  # type: ignore[attr-defined]
        active_shift = await self.bot.database.active_shift(interaction.guild_id, member.id)  # type: ignore[attr-defined]

        embed = discord.Embed(title=f"Member record: {member.display_name}", colour=member.colour or discord.Colour.blurple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Discord ID", value=str(member.id), inline=True)
        embed.add_field(name="Joined", value=discord.utils.format_dt(member.joined_at, "R") if member.joined_at else "Unknown", inline=True)
        if verification:
            embed.add_field(
                name="Roblox verification",
                value=f"{verification['roblox_username']} — {verification['group_role_name']}",
                inline=False,
            )
        else:
            embed.add_field(name="Roblox verification", value="Not verified", inline=False)
        embed.add_field(name="Shift", value="Currently active" if active_shift else "Off shift", inline=True)
        await respond(interaction, embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ServerCog(bot))

