from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    """Application configuration loaded from environment variables."""

    bot_token: str
    group_chat_id: int
    database_path: str = "orders.db"


def load_config(env_file: str = "inputapi.env") -> Config:
    """Load configuration values using python-dotenv."""
    load_dotenv(env_file)

    bot_token = os.getenv("BOT_TOKEN")
    group_chat_id_raw: Optional[str] = os.getenv("GROUP_CHAT_ID")

    if not bot_token:
        raise ValueError("BOT_TOKEN is not set in environment variables.")

    if not group_chat_id_raw:
        raise ValueError("GROUP_CHAT_ID is not set in environment variables.")

    try:
        group_chat_id = int(group_chat_id_raw)
    except ValueError as exc:
        raise ValueError("GROUP_CHAT_ID must be a valid integer.") from exc

    return Config(bot_token=bot_token, group_chat_id=group_chat_id)

