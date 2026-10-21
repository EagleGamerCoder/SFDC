"""Discord client lifecycle and command registration."""

from __future__ import annotations

import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from src.config import Settings
from src.data.database import Database
from src.services.audit_log import AuditLogger
from src.services.content_library import ContentLibrary
from src.services.roblox import RobloxService
from src.utils.discord_helpers import respond

LOGGER = logging.getLogger(__name__)


class DevelopmentGuildAccessError(RuntimeError):
    """The configured development server does not contain this Discord app."""


class FDBot(commands.Bot):
    """The application container shared by all command modules."""

    extensions = (
        "src.cogs.verification",
        "src.cogs.embeds",
        "src.cogs.shifts",
        "src.cogs.promotions",
        "src.cogs.server",
        "src.cogs.audit",
        "src.cogs.content",
        "src.cogs.panels",
    )

    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.members = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.settings = settings
        self.database = Database(settings.database_path)
        self.http_session: aiohttp.ClientSession | None = None
        self.roblox: RobloxService | None = None
        self.audit_logger = AuditLogger(settings)
        self.content_library = ContentLibrary(settings.content_path)

    async def setup_hook(self) -> None:
        await self.database.connect()
        self.http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        self.roblox = RobloxService(
            self.http_session,
            group_id=self.settings.roblox_group_id,
            api_key=self.settings.roblox_open_cloud_api_key,
        )
        self.content_library.reload()

        for extension in self.extensions:
            await self.load_extension(extension)

        if self.settings.development_guild_id:
            guild = discord.Object(id=self.settings.development_guild_id)
            self.tree.copy_global_to(guild=guild)
            try:
                await self.tree.sync(guild=guild)
            except discord.Forbidden as exc:
                raise DevelopmentGuildAccessError(
                    f"Discord could not access development guild {guild.id}. "
                    "Check that DISCORD_GUILD_ID is the server ID (not the application ID) "
                    "and that this bot from the same Discord application is installed in that server."
                ) from exc
            LOGGER.info("Synced application commands to development guild %s", guild.id)
        else:
            await self.tree.sync()
            LOGGER.info("Synced global application commands")

    async def on_ready(self) -> None:
        if self.user:
            LOGGER.info("Logged in as %s (%s)", self.user, self.user.id)

    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if interaction.response.is_done():
            return
        if isinstance(error, app_commands.CheckFailure):
            await respond(interaction, "You do not have permission to use this command.")
            return
        if isinstance(error, app_commands.CommandInvokeError):
            LOGGER.exception("Application command failed", exc_info=error.original)
        else:
            LOGGER.exception("Application command failed", exc_info=error)
        await respond(interaction, "Something went wrong while running that command. The incident has been logged.")

    async def close(self) -> None:
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
        await self.database.close()
        await super().close()

