#!/usr/bin/env python3
"""Simple script to get chat ID when bot receives a message."""
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from config import load_config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

async def get_chat_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Print chat information."""
    chat = update.effective_chat
    user = update.effective_user

    print("\n" + "="*50)
    print(f"Chat Type: {chat.type}")
    print(f"Chat ID: {chat.id}")
    print(f"Chat Title: {chat.title if chat.title else 'N/A'}")
    print(f"User ID: {user.id if user else 'N/A'}")
    print(f"Username: @{user.username if user and user.username else 'N/A'}")
    print("="*50 + "\n")

    if chat.type in ['group', 'supergroup']:
        await update.message.reply_text(
            f"✅ ID этой группы: {chat.id}\n"
            f"Добавьте это значение в inputapi.env:\n"
            f"GROUP_CHAT_ID={chat.id}"
        )

async def main():
    config = load_config()
    application = Application.builder().token(config.bot_token).build()

    application.add_handler(MessageHandler(filters.ALL, get_chat_info))

    print("\n🤖 Бот запущен!")
    print("📝 Отправьте любое сообщение в группу, чтобы получить её ID")
    print("🛑 Нажмите Ctrl+C для остановки\n")

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    # Keep running
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        print("\n🛑 Остановка...")
    finally:
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
