

"""Process entry point."""

from __future__ import annotations

import logging

from src.config import ConfigurationError, Settings
from src.core.client import DevelopmentGuildAccessError, FDBot


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    try:
        settings = Settings.from_environment()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    bot = FDBot(settings)
    try:
        bot.run(settings.discord_token, log_handler=None)
    except DevelopmentGuildAccessError as exc:
        logging.critical("%s", exc)
