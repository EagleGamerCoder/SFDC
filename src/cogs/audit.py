"""Passive Discord-side administration audit logging."""

from __future__ import annotations

import discord
from discord.ext import commands


class AuditCog(commands.Cog):
    """Records important server lifecycle events in the optional log channels."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self.bot.audit_logger.send(  # type: ignore[attr-defined]
            member.guild,
            "member",
            "Member joined",
            f"{member.mention} joined the server.",
            colour=discord.Colour.green(),
            fields=(("Account created", discord.utils.format_dt(member.created_at, "d"), True), ("Member ID", str(member.id), True)),
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self.bot.audit_logger.send(  # type: ignore[attr-defined]
            member.guild,
            "member",
            "Member left",
            f"**{member}** (`{member.id}`) left or was removed from the server.",
            colour=discord.Colour.orange(),
        )

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User | discord.Member) -> None:
        await self.bot.audit_logger.send(  # type: ignore[attr-defined]
            guild,
            "moderation",
            "Member banned",
            f"**{user}** (`{user.id}`) was banned.",
            colour=discord.Colour.red(),
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        await self.bot.audit_logger.send(  # type: ignore[attr-defined]
            guild,
            "moderation",
            "Member unbanned",
            f"**{user}** (`{user.id}`) was unbanned.",
            colour=discord.Colour.green(),
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.nick == after.nick and before.roles == after.roles:
            return
        changed: list[tuple[str, str, bool]] = []
        if before.nick != after.nick:
            changed.append(("Nickname", f"{before.nick or 'None'} → {after.nick or 'None'}", False))
        if before.roles != after.roles:
            before_ids = {role.id for role in before.roles}
            added = [role.mention for role in after.roles if role.id not in before_ids and not role.is_default()]
            after_ids = {role.id for role in after.roles}
            removed = [role.name for role in before.roles if role.id not in after_ids and not role.is_default()]
            if added:
                changed.append(("Roles added", ", ".join(added), False))
            if removed:
                changed.append(("Roles removed", ", ".join(removed), False))
        await self.bot.audit_logger.send(  # type: ignore[attr-defined]
            after.guild,
            "admin",
            "Member updated",
            f"{after.mention}'s server record changed.",
            fields=changed,
        )

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        await self.bot.audit_logger.send(  # type: ignore[attr-defined]
            channel.guild,
            "admin",
            "Channel created",
            f"{channel.mention if hasattr(channel, 'mention') else channel.name} was created.",
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self.bot.audit_logger.send(  # type: ignore[attr-defined]
            channel.guild,
            "admin",
            "Channel deleted",
            f"**{channel.name}** was deleted.",
            colour=discord.Colour.orange(),
        )

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        await self.bot.audit_logger.send(  # type: ignore[attr-defined]
            role.guild,
            "admin",
            "Role created",
            f"{role.mention} was created.",
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        await self.bot.audit_logger.send(  # type: ignore[attr-defined]
            role.guild,
            "admin",
            "Role deleted",
            f"**{role.name}** was deleted.",
            colour=discord.Colour.orange(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AuditCog(bot))

