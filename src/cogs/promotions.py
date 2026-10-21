"""Staff-controlled Roblox role assignment with a durable audit trail."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from src.services.roblox import RobloxAPIError
from src.utils.discord_helpers import require_staff, respond


class PromotionCog(commands.GroupCog, group_name="promotion", group_description="Assign approved Roblox group roles and review the audit trail."):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _role_id_for_label(self, requested_label: str) -> tuple[str, int] | None:
        roles: dict[str, int] = self.bot.settings.promotion_roles  # type: ignore[attr-defined]
        normalized = requested_label.casefold().strip()
        for label, role_id in roles.items():
            if label.casefold() == normalized:
                return label, role_id
        return None

    @app_commands.command(name="promote", description="Assign an approved Roblox group role to a verified member.")
    @app_commands.describe(member="The verified Discord member", role="A label from ROBLOX_PROMOTION_ROLES_JSON", reason="Why this role is being assigned")
    @app_commands.check(require_staff)
    @app_commands.guild_only()
    async def promote(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        role: str,
        reason: str | None = None,
    ) -> None:
        settings = self.bot.settings  # type: ignore[attr-defined]
        if not settings.promotion_is_configured:
            await respond(interaction, "Promotion is not configured yet. Add the group ID and a Roblox Open Cloud API key first.")
            return
        requested_role = self._role_id_for_label(role)
        if requested_role is None:
            allowed = ", ".join(f"`{label}`" for label in settings.promotion_roles) or "none configured"
            await respond(interaction, f"That role is not approved for Discord promotion. Available roles: {allowed}.")
            return
        if reason and len(reason) > 500:
            await respond(interaction, "Keep the promotion reason under 500 characters.")
            return

        record = await self.bot.database.get_verification(interaction.guild_id, member.id)  # type: ignore[attr-defined]
        if record is None:
            await respond(interaction, f"{member.mention} has not completed verification yet.")
            return

        target_label, target_role_id = requested_role
        if str(target_role_id) == str(record["group_role_id"]):
            await respond(interaction, f"{member.mention} is already recorded with the **{target_label}** role.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        status = "completed"
        note = ""
        try:
            current_membership = await self.bot.roblox.get_membership(record["roblox_user_id"])  # type: ignore[attr-defined]
            await self.bot.roblox.assign_role(record["roblox_user_id"], target_role_id)  # type: ignore[attr-defined]
            if settings.replace_promotion_role and current_membership.role_id != str(target_role_id):
                try:
                    await self.bot.roblox.unassign_role(record["roblox_user_id"], current_membership.role_id)  # type: ignore[attr-defined]
                except RobloxAPIError:
                    status = "assigned_old_role_retained"
                    note = " The new role was assigned, but Roblox retained the old role."
        except RobloxAPIError as exc:
            promotion_id = await self.bot.database.add_promotion(  # type: ignore[attr-defined]
                guild_id=interaction.guild_id,
                actor_discord_user_id=interaction.user.id,
                target_discord_user_id=member.id,
                roblox_user_id=record["roblox_user_id"],
                roblox_username=record["roblox_username"],
                from_role=record["group_role_name"],
                to_role=target_label,
                reason=reason,
                status="failed",
            )
            await respond(interaction, f"Promotion failed and was logged as #{promotion_id}: {exc}")
            await self.bot.audit_logger.send(  # type: ignore[attr-defined]
                interaction.guild,
                "promotion",
                "Roblox promotion failed",
                f"{interaction.user.mention} could not assign **{target_label}** to {member.mention}.",
                colour=discord.Colour.red(),
                fields=(("Roblox account", record["roblox_username"], True), ("Reason", reason or "—", False)),
            )
            return

        promotion_id = await self.bot.database.add_promotion(  # type: ignore[attr-defined]
            guild_id=interaction.guild_id,
            actor_discord_user_id=interaction.user.id,
            target_discord_user_id=member.id,
            roblox_user_id=record["roblox_user_id"],
            roblox_username=record["roblox_username"],
            from_role=record["group_role_name"],
            to_role=target_label,
            reason=reason,
            status=status,
        )
        await respond(
            interaction,
            f"Assigned **{target_label}** to {member.mention}'s Roblox account (`{record['roblox_username']}`). "
            f"Logged as #{promotion_id}.{note} Use `/verify-sync` later to refresh their Discord profile.",
        )
        await self.bot.audit_logger.send(  # type: ignore[attr-defined]
            interaction.guild,
            "promotion",
            "Roblox role assigned",
            f"{interaction.user.mention} assigned **{target_label}** to {member.mention}.",
            colour=discord.Colour.green(),
            fields=(
                ("Roblox account", f"{record['roblox_username']} ({record['roblox_user_id']})", True),
                ("Previous role", record["group_role_name"], True),
                ("Reason", reason or "—", False),
                ("Log ID", f"#{promotion_id} ({status})", True),
            ),
        )

    @app_commands.command(name="history", description="View the most recent Roblox promotion records.")
    @app_commands.check(require_staff)
    @app_commands.guild_only()
    async def history(self, interaction: discord.Interaction) -> None:
        records = await self.bot.database.recent_promotions(interaction.guild_id)  # type: ignore[attr-defined]
        if not records:
            await respond(interaction, "No promotion records have been logged yet.")
            return
        lines = []
        for record in records:
            lines.append(
                f"• **#{record['id']}** <@{record['target_discord_user_id']}> — "
                f"{record['from_role']} → **{record['to_role']}** (`{record['status']}`)"
            )
        embed = discord.Embed(title="Recent Roblox promotions", description="\n".join(lines), colour=discord.Colour.blurple())
        await respond(interaction, embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PromotionCog(bot))
