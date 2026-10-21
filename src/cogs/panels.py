"""Persistent verification and shift panels that survive bot restarts."""

from __future__ import annotations

from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from src.services.roblox import RobloxAPIError
from src.utils.discord_helpers import discord_time, require_staff, respond


def verification_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Roblox Verification",
        description=(
            "Link your Roblox account to access the server's group-based roles and nickname.\n\n"
            "Press **Verify / Update** and enter your Roblox username. You can use the same button later "
            "to refresh your group role after a promotion."
        ),
        colour=discord.Colour.blurple(),
    )
    embed.add_field(name="Before you begin", value="Join the Roblox group first, then enter your exact username.", inline=False)
    embed.set_footer(text="Your Roblox username is stored only for verification, shift, and promotion features.")
    return embed


class VerificationModal(discord.ui.Modal, title="Verify your Roblox account"):
    def __init__(self, cog: Any, default_username: str | None = None) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.roblox_username = discord.ui.TextInput(
            label="Roblox username",
            placeholder="Example: Builderman",
            default=default_username or None,
            min_length=3,
            max_length=20,
        )
        self.add_item(self.roblox_username)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await respond(interaction, "Verification can only be completed inside the server.")
            return
        if not interaction.client.settings.roblox_group_is_configured:  # type: ignore[attr-defined]
            await respond(interaction, "Verification is not configured yet. An administrator needs to add ROBLOX_GROUP_ID first.")
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            roblox_user, membership, changes = await self.cog._verify_member(interaction.user, self.roblox_username.value)
        except RobloxAPIError as exc:
            await respond(interaction, f"Verification failed: {exc}")
            return

        embed = discord.Embed(title="Verification complete", colour=discord.Colour.green(), timestamp=discord.utils.utcnow())
        embed.add_field(
            name="Roblox",
            value=f"[{roblox_user.name}](https://www.roblox.com/users/{roblox_user.id}/profile)",
            inline=True,
        )
        embed.add_field(name="Group role", value=f"{membership.role_name} (rank {membership.rank})", inline=True)
        embed.add_field(name="Discord sync", value=", ".join(changes) if changes else "Already up to date", inline=False)
        await respond(interaction, embed=embed)
        await interaction.client.audit_logger.send(  # type: ignore[attr-defined]
            interaction.guild,
            "verification",
            "Member verified",
            f"{interaction.user.mention} linked their Discord account to Roblox from the verification panel.",
            colour=discord.Colour.green(),
            fields=(
                ("Roblox account", f"{roblox_user.name} ({roblox_user.id})", True),
                ("Group role", membership.role_name, True),
            ),
        )


class VerificationPanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Verify / Update", style=discord.ButtonStyle.primary, emoji="✅", custom_id="erlc:verification:open")
    async def verify_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            await respond(interaction, "Verification is only available inside the server.")
            return
        verification_cog = interaction.client.get_cog("VerificationCog")
        if verification_cog is None:
            await respond(interaction, "Verification is temporarily unavailable. Please try again shortly.")
            return
        record = await interaction.client.database.get_verification(interaction.guild.id, interaction.user.id)  # type: ignore[attr-defined]
        default_username = record["roblox_username"] if record else None
        await interaction.response.send_modal(VerificationModal(verification_cog, default_username))


class ShiftPanelView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Start shift", style=discord.ButtonStyle.success, emoji="🟢", custom_id="erlc:shift:start")
    async def start_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        shift_cog = interaction.client.get_cog("ShiftCog")
        if shift_cog is None:
            await respond(interaction, "Shift tracking is temporarily unavailable. Please try again shortly.")
            return
        await shift_cog.start_from_panel(interaction)

    @discord.ui.button(label="End shift", style=discord.ButtonStyle.danger, emoji="🔴", custom_id="erlc:shift:end")
    async def end_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        shift_cog = interaction.client.get_cog("ShiftCog")
        if shift_cog is None:
            await respond(interaction, "Shift tracking is temporarily unavailable. Please try again shortly.")
            return
        await shift_cog.end_from_panel(interaction)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary, emoji="🔄", custom_id="erlc:shift:refresh")
    async def refresh_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            await respond(interaction, "This panel is only available inside the server.")
            return
        panel_cog = interaction.client.get_cog("PanelCog")
        if panel_cog is None:
            await respond(interaction, "Panel refresh is temporarily unavailable. Please try again shortly.")
            return
        await panel_cog.refresh_guild_shift_panels(interaction.guild)
        await respond(interaction, "Shift panel refreshed.")


class PanelCog(commands.GroupCog, group_name="panel", group_description="Deploy interactive verification and shift panels."):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def cog_unload(self) -> None:
        if self.shift_panel_refresh.is_running():
            self.shift_panel_refresh.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # Starting after the client becomes ready avoids a background task during
        # command registration, and avoids duplicate loops after reconnects.
        if not self.shift_panel_refresh.is_running():
            self.shift_panel_refresh.start()

    async def _deploy(self, guild: discord.Guild, panel_type: str, channel: discord.TextChannel) -> discord.Message:
        if panel_type == "verification":
            embed, view = verification_panel_embed(), VerificationPanelView()
        else:
            embed, view = await self.build_shift_panel(guild), ShiftPanelView()

        previous = await self.bot.database.get_panel(guild.id, panel_type)  # type: ignore[attr-defined]
        message: discord.Message | None = None
        if previous and previous["channel_id"] == channel.id:
            try:
                message = await channel.fetch_message(previous["message_id"])
                await message.edit(embed=embed, view=view)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                message = None
        if message is None:
            message = await channel.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        await self.bot.database.upsert_panel(guild.id, panel_type, channel.id, message.id)  # type: ignore[attr-defined]
        return message

    async def build_shift_panel(self, guild: discord.Guild) -> discord.Embed:
        records = await self.bot.database.list_active_shifts(guild.id)  # type: ignore[attr-defined]
        embed = discord.Embed(
            title="Shift Centre",
            description="Start or end your shift using the buttons below. Active shifts update automatically.",
            colour=discord.Colour.green() if records else discord.Colour.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        if not records:
            embed.add_field(name="Currently on shift", value="No members are currently on shift.", inline=False)
        else:
            lines: list[str] = []
            for record in records[:20]:
                member = guild.get_member(record["discord_user_id"])
                label = member.mention if member else f"<@{record['discord_user_id']}>"
                note = f" — {record['note']}" if record["note"] else ""
                lines.append(f"• {label} · started {discord_time(record['started_at'])}{note}")
            embed.add_field(name=f"Currently on shift ({len(records)})", value="\n".join(lines)[:1024], inline=False)
            if len(records) > 20:
                embed.set_footer(text=f"Showing 20 of {len(records)} active shifts. Use /shift active for the full list.")
        return embed

    async def refresh_guild_shift_panels(self, guild: discord.Guild) -> None:
        records = await self.bot.database.list_panels("shift", guild.id)  # type: ignore[attr-defined]
        if not records:
            return
        embed = await self.build_shift_panel(guild)
        for record in records:
            channel = guild.get_channel(record["channel_id"])
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                await channel.get_partial_message(record["message_id"]).edit(embed=embed, view=ShiftPanelView())
            except discord.NotFound:
                await self.bot.database.delete_panel(guild.id, "shift")  # type: ignore[attr-defined]
            except (discord.Forbidden, discord.HTTPException):
                continue

    @tasks.loop(minutes=1)
    async def shift_panel_refresh(self) -> None:
        records = await self.bot.database.list_panels("shift")  # type: ignore[attr-defined]
        for record in records:
            guild = self.bot.get_guild(record["guild_id"])
            if guild:
                await self.refresh_guild_shift_panels(guild)

    @app_commands.command(name="verification", description="Deploy or refresh the interactive verification panel.")
    @app_commands.describe(channel="The text channel that should contain the panel")
    @app_commands.check(require_staff)
    @app_commands.guild_only()
    async def verification(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            message = await self._deploy(interaction.guild, "verification", channel)
        except discord.Forbidden:
            await respond(interaction, "I cannot send or edit the panel in that channel.")
            return
        except discord.HTTPException:
            await respond(interaction, "Discord could not deploy that panel. Please try again.")
            return
        await respond(interaction, f"Verification panel ready in {channel.mention}: [open panel]({message.jump_url})")

    @app_commands.command(name="shift", description="Deploy or refresh the interactive live shift panel.")
    @app_commands.describe(channel="The text channel that should contain the panel")
    @app_commands.check(require_staff)
    @app_commands.guild_only()
    async def shift(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            message = await self._deploy(interaction.guild, "shift", channel)
        except discord.Forbidden:
            await respond(interaction, "I cannot send or edit the panel in that channel.")
            return
        except discord.HTTPException:
            await respond(interaction, "Discord could not deploy that panel. Please try again.")
            return
        await respond(interaction, f"Shift panel ready in {channel.mention}: [open panel]({message.jump_url})")

    @app_commands.command(name="status", description="Show where interactive panels are currently deployed.")
    @app_commands.check(require_staff)
    @app_commands.guild_only()
    async def status(self, interaction: discord.Interaction) -> None:
        lines = []
        for panel_type in ("verification", "shift"):
            record = await self.bot.database.get_panel(interaction.guild_id, panel_type)  # type: ignore[attr-defined]
            if record:
                lines.append(f"• **{panel_type.title()}**: <#{record['channel_id']}> ([open panel](https://discord.com/channels/{record['guild_id']}/{record['channel_id']}/{record['message_id']}))")
            else:
                lines.append(f"• **{panel_type.title()}**: not deployed")
        await respond(interaction, embed=discord.Embed(title="Panel deployments", description="\n".join(lines), colour=discord.Colour.blurple()))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PanelCog(bot))
    bot.add_view(VerificationPanelView())
    bot.add_view(ShiftPanelView())
