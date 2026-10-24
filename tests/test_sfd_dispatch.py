import os
import json
import time
import hashlib
import logging
import asyncio
from datetime import datetime, timezone

import discord
from discord.ext import commands
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
import uvicorn

from erlc_api.webhooks import (
    EventWebhookRouter,
    assert_valid_event_webhook_signature,
)

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DISPATCH_CHANNEL_ID = int(
    os.getenv("FIRE_DISPATCH_CHANNEL_ID", "0")
)
INCIDENT_LOG_CHANNEL_ID = int(
    os.getenv("INCIDENT_LOG_CHANNEL_ID", "0")
)
PORT = int(os.getenv("PORT", "8000"))

FINISH_ROLE_IDS = {
    int(role_id.strip())
    for role_id in os.getenv(
        "DISPATCH_FINISH_ROLE_IDS", ""
    ).split(",")
    if role_id.strip().isdigit()
}

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing from .env")

if not DISPATCH_CHANNEL_ID or not INCIDENT_LOG_CHANNEL_ID:
    raise RuntimeError(
        "Configure FIRE_DISPATCH_CHANNEL_ID and "
        "INCIDENT_LOG_CHANNEL_ID in .env"
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("sfd-dispatch")

# ============================================================
# DISCORD BOT
# ============================================================

intents = discord.Intents.default()

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
)

app = FastAPI()
router = EventWebhookRouter(command_prefix=";")

# Active calls are stored in memory while the bot is running.
# For persistence across restarts, use SQLite or PostgreSQL.
active_calls = {}
processed_calls = {}
state_lock = asyncio.Lock()

DEDUPLICATION_SECONDS = 3600


def get_field(data, *names, default=None):
    """Get the first available field from a dictionary."""
    if not isinstance(data, dict):
        return default

    for name in names:
        value = data.get(name)
        if value is not None:
            return value

    return default


def create_call_id(data):
    """Prefer the ER:LC call number; otherwise hash its payload."""
    number = get_field(
        data, "CallNumber", "callNumber", "call_number"
    )

    if number is not None:
        return f"call-{number}"

    canonical = json.dumps(
        data, sort_keys=True, default=str
    )
    return "call-" + hashlib.sha256(
        canonical.encode()
    ).hexdigest()[:20]


def cleanup_processed_calls():
    now = time.time()

    expired = [
        key
        for key, timestamp in processed_calls.items()
        if now - timestamp > DEDUPLICATION_SECONDS
    ]

    for key in expired:
        del processed_calls[key]


def is_fire_call(data):
    team = str(
        get_field(data, "Team", "team", default="")
    ).strip().lower()

    return team == "fire" or team.startswith("fire ")


def format_call_embed(call):
    embed = discord.Embed(
        title="🔥 SFD Fire Dispatch",
        description=call["description"][:4000],
        colour=discord.Colour.red(),
        timestamp=call["created_at"],
    )

    embed.add_field(
        name="Location",
        value=call["location"][:1024],
        inline=False,
    )

    if call.get("call_number") is not None:
        embed.add_field(
            name="ER:LC Call Number",
            value=str(call["call_number"]),
            inline=True,
        )

    embed.add_field(
        name=f"Responding ({len(call['responders'])})",
        value=(
            "\n".join(
                f"• <@{user_id}>"
                for user_id in call["responders"]
            ) or "Nobody has responded yet."
        )[:1024],
        inline=False,
    )

    embed.set_footer(
        text="Springfield Fire Department | Active Dispatch"
    )

    return embed


def can_finish_call(interaction):
    """Only configured supervisors or the server owner can close calls."""
    if interaction.guild is None:
        return False

    if interaction.guild.owner_id == interaction.user.id:
        return True

    member = interaction.user

    if not isinstance(member, discord.Member):
        return False

    return any(
        role.id in FINISH_ROLE_IDS
        for role in member.roles
    )


class DispatchView(discord.ui.View):
    def __init__(self, call_id):
        super().__init__(timeout=None)
        self.call_id = call_id

    async def refresh_message(self, call):
        message = call.get("message")

        if message is None:
            return

        await message.edit(
            embed=format_call_embed(call),
            view=self,
        )

    @discord.ui.button(
        label="Respond to Call",
        style=discord.ButtonStyle.success,
        emoji="🚒",
        custom_id="sfd_dispatch_respond",
    )
    async def respond(self, interaction, button):
        async with state_lock:
            call = active_calls.get(self.call_id)

            if not call:
                await interaction.response.send_message(
                    "This call is no longer active.",
                    ephemeral=True,
                )
                return

            user_id = interaction.user.id

            if user_id in call["responders"]:
                await interaction.response.send_message(
                    "You are already responding to this call.",
                    ephemeral=True,
                )
                return

            call["responders"][user_id] = datetime.now(
                timezone.utc
            )

            await self.refresh_message(call)

        await interaction.response.send_message(
            "You are now marked as responding to this call.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Cancel Response",
        style=discord.ButtonStyle.secondary,
        emoji="↩️",
        custom_id="sfd_dispatch_cancel",
    )
    async def cancel(self, interaction, button):
        async with state_lock:
            call = active_calls.get(self.call_id)

            if not call:
                await interaction.response.send_message(
                    "This call is no longer active.",
                    ephemeral=True,
                )
                return

            user_id = interaction.user.id

            if user_id not in call["responders"]:
                await interaction.response.send_message(
                    "You have not responded to this call.",
                    ephemeral=True,
                )
                return

            del call["responders"][user_id]
            await self.refresh_message(call)

        await interaction.response.send_message(
            "Your response has been cancelled.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Finish Call",
        style=discord.ButtonStyle.danger,
        emoji="✅",
        custom_id="sfd_dispatch_finish",
    )
    async def finish(self, interaction, button):
        if not can_finish_call(interaction):
            await interaction.response.send_message(
                "You are not authorised to finish dispatch calls.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        async with state_lock:
            call = active_calls.get(self.call_id)

            if not call:
                await interaction.followup.send(
                    "This call has already been closed.",
                    ephemeral=True,
                )
                return

            # Build and send the audit record before removing
            # the active dispatch message.
            log_channel = bot.get_channel(
                INCIDENT_LOG_CHANNEL_ID
            )

            if log_channel is None:
                log_channel = await bot.fetch_channel(
                    INCIDENT_LOG_CHANNEL_ID
                )

            log_embed = discord.Embed(
                title="✅ Fire Call Closed",
                description=call["description"][:4000],
                colour=discord.Colour.dark_green(),
                timestamp=datetime.now(timezone.utc),
            )

            log_embed.add_field(
                name="Location",
                value=call["location"][:1024],
                inline=False,
            )

            log_embed.add_field(
                name="Closed By",
                value=interaction.user.mention,
                inline=True,
            )

            responders = call["responders"]

            log_embed.add_field(
                name=f"Responders ({len(responders)})",
                value=(
                    "\n".join(
                        f"• <@{user_id}>"
                        for user_id in responders
                    ) or "No responders recorded."
                )[:1024],
                inline=False,
            )

            if call.get("call_number") is not None:
                log_embed.add_field(
                    name="ER:LC Call Number",
                    value=str(call["call_number"]),
                    inline=True,
                )

            log_embed.add_field(
                name="Dispatch Message ID",
                value=str(call["message"].id),
                inline=False,
            )

            await log_channel.send(
                embed=log_embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )

            # Remove from active calls only after the log succeeds.
            active_calls.pop(self.call_id, None)

            try:
                await call["message"].delete()
            except discord.NotFound:
                pass
            except discord.HTTPException:
                logger.exception(
                    "Could not delete dispatch message %s",
                    self.call_id,
                )

        await interaction.followup.send(
            "Call closed and logged.",
            ephemeral=True,
        )


# ============================================================
# ER:LC WEBHOOK HANDLER
# ============================================================

@router.on_emergency_call()
async def handle_emergency_call(event):
    data = event.emergency_call or {}

    if not isinstance(data, dict):
        logger.warning("Received an unexpected call payload.")
        return {"ignored": True}

    # Only forward calls for the Fire team.
    if not is_fire_call(data):
        return {"ignored": True, "reason": "not a fire call"}

    call_id = create_call_id(data)

    description = str(
        get_field(
            data,
            "Description",
            "description",
            default="Fire emergency call",
        )
    )

    location = str(
        get_field(
            data,
            "PositionDescriptor",
            "position_descriptor",
            "Location",
            "location",
            default="Location not provided",
        )
    )

    call_number = get_field(
        data, "CallNumber", "callNumber", "call_number"
    )

    async with state_lock:
        cleanup_processed_calls()

        if call_id in processed_calls:
            logger.info("Ignoring duplicate call %s", call_id)
            return {"ignored": True, "reason": "duplicate"}

        # If this exact call is already active, don't repost it.
        if call_id in active_calls:
            return {"ignored": True, "reason": "already active"}

        channel = bot.get_channel(DISPATCH_CHANNEL_ID)

        if channel is None:
            channel = await bot.fetch_channel(
                DISPATCH_CHANNEL_ID
            )

        call = {
            "id": call_id,
            "description": description,
            "location": location,
            "call_number": call_number,
            "created_at": datetime.now(timezone.utc),
            "responders": {},
            "message": None,
        }

        view = DispatchView(call_id)

        message = await channel.send(
            embed=format_call_embed(call),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        call["message"] = message
        active_calls[call_id] = call
        processed_calls[call_id] = time.time()

    logger.info("Posted fire dispatch %s", call_id)
    return {"posted": True, "call_id": call_id}


@app.get("/")
async def health_check():
    return {"status": "online", "service": "SFD Dispatch"}


@app.post("/erlc/events")
async def receive_erlc_webhook(request: Request):
    raw_body = await request.body()

    # Validate the signature against the ORIGINAL body bytes.
    try:
        assert_valid_event_webhook_signature(
            raw_body=raw_body,
            headers=request.headers,
            max_skew_s=300,
        )
    except Exception as exc:
        logger.warning("Rejected invalid ER:LC webhook.")
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature",
        ) from exc

    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON",
        ) from exc

    if not bot.is_ready():
        raise HTTPException(
            status_code=503,
            detail="Discord bot is not ready",
        )

    try:
        results = await router.dispatch(payload)
    except Exception as exc:
        logger.exception("Failed to process ER:LC event.")
        raise HTTPException(
            status_code=500,
            detail="Webhook processing failed",
        ) from exc

    return {"status": "ok", "results": results}


# ============================================================
# BOT STARTUP
# ============================================================

@bot.event
async def on_ready():
    logger.info("Discord bot online as %s", bot.user)


async def main():
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",
    )

    server = uvicorn.Server(config)

    async with bot:
        async with asyncio.TaskGroup() as tasks:
            tasks.create_task(bot.start(DISCORD_TOKEN))
            tasks.create_task(server.serve())


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("SFD Dispatch bot stopped.")
