from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from telegram.ext import Application

from config import Config, load_config
from database import Database
from handlers import register_handlers

LOGGER = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def run_bot(config: Config) -> None:
    """Initialize dependencies and start polling."""
    db = Database(config.database_path)
    await db.initialize()

    application = Application.builder().token(config.bot_token).build()
    register_handlers(application, config, db)

    try:
        LOGGER.info("Starting bot polling...")
        # Clear any pending updates first
        await application.bot.delete_webhook(drop_pending_updates=True)
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        
        # Wait for stop signals
        stop_event = asyncio.Event()
        
        def signal_handler(signum, frame):
            LOGGER.info("Received signal %s, shutting down...", signum)
            stop_event.set()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        await stop_event.wait()
    finally:
        LOGGER.info("Shutting down application...")
        await application.stop()
        await application.shutdown()
        with suppress(Exception):
            await db.close()


def main() -> None:
    setup_logging()
    try:
        config = load_config()
    except ValueError as exc:
        LOGGER.error("Configuration error: %s", exc)
        raise SystemExit(1) from exc

    asyncio.run(run_bot(config))


if __name__ == "__main__":
    main()

