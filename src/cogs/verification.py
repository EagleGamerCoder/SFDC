"""Roblox group verification and Discord identity synchronisation."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from src.services.roblox import GroupMembership, RobloxAPIError, RobloxUser
from src.utils.discord_helpers import nickname_from_template, respond


class VerificationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def roblox(self):
        service = self.bot.roblox  # type: ignore[attr-defined]
        if service is None:
            raise RuntimeError("Roblox service is not ready.")
        return service

    async def _apply_discord_identity(
        self,
        member: discord.Member,
        roblox_user: RobloxUser,
        membership: GroupMembership,
    ) -> list[str]:
        """Apply the configured Discord roles and nickname, returning changes made."""
        settings = self.bot.settings  # type: ignore[attr-defined]
        changes: list[str] = []

        managed_rank_role_ids = set(settings.roblox_role_map.values())
        role_ids_to_add = {settings.roblox_role_map.get(membership.role_id)}
        if settings.verified_role_id:
            role_ids_to_add.add(settings.verified_role_id)
        role_ids_to_add.discard(None)

        roles_to_remove = [role for role in member.roles if role.id in managed_rank_role_ids and role.id not in role_ids_to_add]
        roles_to_add = [
            role
            for role_id in role_ids_to_add
            if (role := member.guild.get_role(role_id)) is not None and role not in member.roles
        ]
        try:
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="Roblox verification role sync")
                changes.append("updated Discord rank roles")
            if roles_to_add:
                await member.add_roles(*roles_to_add, reason="Roblox verification role sync")
                changes.append("added verification role")
        except discord.Forbidden:
            changes.append("could not update roles (check the bot role hierarchy)")
        except discord.HTTPException:
            changes.append("could not update roles")

        try:
            nickname = nickname_from_template(
                settings,
                roblox_name=roblox_user.name,
                roblox_id=roblox_user.id,
                group_role=membership.role_name,
                group_rank=membership.rank,
            )
            if member.nick != nickname:
                await member.edit(nick=nickname, reason="Roblox verification nickname sync")
                changes.append("updated nickname")
        except ValueError:
            changes.append("could not update nickname (check NICKNAME_TEMPLATE)")
        except discord.Forbidden:
            changes.append("could not update nickname (check the bot role hierarchy)")
        except discord.HTTPException:
            changes.append("could not update nickname")
        return changes

    async def _verify_member(self, member: discord.Member, username: str) -> tuple[RobloxUser, GroupMembership, list[str]]:
        roblox_user = await self.roblox.resolve_username(username)
        membership = await self.roblox.get_membership(roblox_user.id)
        changes = await self._apply_discord_identity(member, roblox_user, membership)
        await self.bot.database.upsert_verification(  # type: ignore[attr-defined]
            guild_id=member.guild.id,
            discord_user_id=member.id,
            roblox_user_id=roblox_user.id,
            roblox_username=roblox_user.name,
            group_role_id=membership.role_id,
            group_role_name=membership.role_name,
            group_rank=membership.rank,
        )
        return roblox_user, membership, changes

    @app_commands.command(name="verify", description="Verify your Roblox account against the configured group.")
    @app_commands.describe(roblox_username="Your exact Roblox username")
    @app_commands.guild_only()
    async def verify(self, interaction: discord.Interaction, roblox_username: str) -> None:
        if not self.bot.settings.roblox_group_is_configured:  # type: ignore[attr-defined]
            await respond(interaction, "Verification is not configured yet. An administrator needs to add ROBLOX_GROUP_ID first.")
            return
        if not isinstance(interaction.user, discord.Member):
            await respond(interaction, "I could not identify your server membership.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            roblox_user, membership, changes = await self._verify_member(interaction.user, roblox_username)
        except RobloxAPIError as exc:
            await respond(interaction, f"Verification failed: {exc}")
            return

        embed = discord.Embed(title="Verification complete", colour=discord.Colour.green(), timestamp=discord.utils.utcnow())
        embed.add_field(name="Roblox", value=f"[{roblox_user.name}](https://www.roblox.com/users/{roblox_user.id}/profile)", inline=True)
        embed.add_field(name="Group role", value=f"{membership.role_name} (rank {membership.rank})", inline=True)
        embed.add_field(name="Discord sync", value=", ".join(changes) if changes else "Already up to date", inline=False)
        await respond(interaction, embed=embed)
        await self.bot.audit_logger.send(  # type: ignore[attr-defined]
            interaction.guild,
            "verification",
            "Member verified",
            f"{interaction.user.mention} linked their Discord account to Roblox.",
            colour=discord.Colour.green(),
            fields=(
                ("Roblox account", f"{roblox_user.name} ({roblox_user.id})", True),
                ("Group role", membership.role_name, True),
            ),
        )

    @app_commands.command(name="verify-sync", description="Recheck your saved Roblox account and refresh Discord roles.")
    @app_commands.guild_only()
    async def verify_sync(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.user, discord.Member):
            await respond(interaction, "I could not identify your server membership.")
            return
        record = await self.bot.database.get_verification(interaction.guild_id, interaction.user.id)  # type: ignore[attr-defined]
        if record is None:
            await respond(interaction, "You have not verified yet. Use `/verify` first.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            roblox_user, membership, changes = await self._verify_member(interaction.user, record["roblox_username"])
        except RobloxAPIError as exc:
            await respond(interaction, f"Sync failed: {exc}")
            return
        await respond(
            interaction,
            f"Synced **{roblox_user.name}** as **{membership.role_name}**. "
            f"{', '.join(changes) if changes else 'Your Discord profile was already up to date.'}",
        )

    @app_commands.command(name="verify-status", description="View your saved Roblox verification status.")
    @app_commands.guild_only()
    async def verify_status(self, interaction: discord.Interaction) -> None:
        record = await self.bot.database.get_verification(interaction.guild_id, interaction.user.id)  # type: ignore[attr-defined]
        if record is None:
            await respond(interaction, "You are not verified. Use `/verify` when you are in the Roblox group.")
            return
        embed = discord.Embed(title="Verification status", colour=discord.Colour.blurple())
        embed.add_field(name="Roblox account", value=f"{record['roblox_username']} ({record['roblox_user_id']})", inline=False)
        embed.add_field(name="Last known group role", value=f"{record['group_role_name']} (rank {record['group_rank']})", inline=True)
        embed.add_field(name="Last sync", value=record["verified_at"], inline=True)
        await respond(interaction, embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VerificationCog(bot))
