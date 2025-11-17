from __future__ import annotations

import html
import logging
import re
from functools import partial
from typing import Any, Dict, Optional, Tuple

from telegram import (
    ForceReply,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import Config
from database import Database, OrderRecord
from keyboards import (
    confirmation_keyboard,
    group_order_keyboard,
    main_menu_keyboard,
)

LOGGER = logging.getLogger(__name__)

# Conversation states
CHOOSING_TYPE, ENTERING_SUBJECT, ENTERING_DESCRIPTION, ENTERING_ADDITIONAL, ENTERING_DEADLINE, ENTERING_BUDGET, CONFIRMING = range(
    7
)

STATE_NAMES = {
    CHOOSING_TYPE: "CHOOSING_TYPE",
    ENTERING_SUBJECT: "ENTERING_SUBJECT",
    ENTERING_DESCRIPTION: "ENTERING_DESCRIPTION",
    ENTERING_ADDITIONAL: "ENTERING_ADDITIONAL",
    ENTERING_DEADLINE: "ENTERING_DEADLINE",
    ENTERING_BUDGET: "ENTERING_BUDGET",
    CONFIRMING: "CONFIRMING",
}

# Order type labels for display
ORDER_TYPES = {
    "homework": "Домашнее задание",
    "eclass": "Закрыть eclass",
    "project": "Проект",
    "laboratory": "Лабораторная работа",
}

# User-facing messages
GREETING_MESSAGE = (
    "Привет! Этот бот поможет оформить анонимный заказ на выполнение учебной работы.\n\n"
    "Выберите тип задания из меню ниже:"
)

HELP_MESSAGE = (
    "Чтобы оформить заказ, нажмите /start и следуйте инструкциям бота.\n\n"
    "Команды:\n"
    "/start — начать оформление заказа\n"
    "/help — показать справку\n"
    "/cancel — отменить оформление заказа"
)

PROMPT_SUBJECT = "Введите полное название предмета:"
PROMPT_DESCRIPTION = (
    "Отправьте файл с требованиями из eclass или опишите задачу текстом:"
)
PROMPT_ADDITIONAL = (
    "Есть ли дополнительные пожелания? Опишите что конкретно хотите, или напишите 'нет'"
)
PROMPT_DEADLINE = (
    "Укажите дедлайн (например: 15.12.2024 18:00) или напишите 'нет', если его нет:"
)
PROMPT_BUDGET = "Укажите ваш бюджет (сумму в сумах или тенге):"
ERROR_INVALID_BUDGET = "Пожалуйста, укажите бюджет числом. Попробуйте ещё раз."
CONFIRMATION_MESSAGE_TITLE = "Проверьте, всё ли верно:"
ORDER_SUBMITTED_MESSAGE = (
    "✅ Ваш заказ #{order_id} отправлен в группу исполнителей. Мы сообщим, когда его примут в работу."
)
ORDER_ACCEPTED_USER_MESSAGE = (
    "✅ Ваш заказ #{order_id} принят в работу! Исполнитель свяжется с вами."
)
ORDER_DECLINED_USER_MESSAGE = (
    "❌ Ваш заказ #{order_id} отклонен.\n\n"
    "Причина: {reason}\n\n"
    "Вы можете создать новый заказ с учетом замечаний. Нажмите /start"
)
ORDER_CANCELLED_MESSAGE = "Создание заказа отменено. Если захотите попробовать снова, введите /start."
DECLINE_REASON_PROMPT_TEMPLATE = (
    "@{username}, укажите причину отклонения заказа #{order_id} в сообщении ответом на это."
)
DECLINE_REASON_REQUIRED_MESSAGE = "Причина обязательна для отклонения заказа. Пожалуйста, ответьте на запрос."
ORDER_ALREADY_PROCESSED_MESSAGE = "Этот заказ уже обработан."
ORDER_NOT_FOUND_MESSAGE = "Заказ не найден."
DECLINE_REASON_ACK = "❌ ЗАКАЗ ОТКЛОНЕН\nПричина: {reason}"
DECLINE_REASON_PENDING = "⏳ Ожидается причина отклонения от @{username}"
DECLINE_REASON_TAKEN = (
    "✅ @{username} взял(а) на себя выполнение заказа #{order_id} (Бюджет: {budget})"
)
GENERIC_ERROR_MESSAGE = (
    "Произошла непредвиденная ошибка. Попробуйте ещё раз позже или начните заново с /start."
)

DECLINE_REASON_WAITLIST: Dict[int, Dict[str, Any]] = {}

BUDGET_PATTERN = re.compile(r"^\d+([.,]\d+)?$")


def _format_user_line(order_data: Dict[str, Any]) -> str:
    username = f"@{html.escape(order_data.get('username'))}" if order_data.get("username") else "—"
    first_name = html.escape(order_data.get("first_name") or "")
    last_name = html.escape(order_data.get("last_name") or "")
    return (
        f"👤 Контакт студента:\n"
        f"   ID: {order_data['user_id']}\n"
        f"   Username: {username}\n"
        f"   Имя: {first_name} {last_name}".strip()
    )


def format_group_message(order: OrderRecord, extra_block: Optional[str] = None) -> str:
    additional_info = order.additional_info or "—"
    deadline = order.deadline or "—"
    description = order.description or "—"

    username_display = f"@{html.escape(order.username)}" if order.username else "—"
    first_name = html.escape(order.first_name or "")
    last_name = html.escape(order.last_name or "")

    text = (
        f"🆕 НОВЫЙ ЗАКАЗ #{order.order_id}\n\n"
        f"📋 Тип: {html.escape(order.order_type)}\n"
        f"📚 Предмет: {html.escape(order.subject)}\n"
        f"📄 Описание: {html.escape(description)}\n"
        f"💡 Доп. информация: {html.escape(additional_info)}\n"
        f"⏰ Дедлайн: {html.escape(deadline)}\n"
        f"💰 Бюджет: {html.escape(order.budget)}\n"
        f"👤 Контакт студента:\n"
        f"   ID: {order.user_id}\n"
        f"   Username: {username_display}\n"
        f"   Имя: {first_name} {last_name}"
    )

    if extra_block:
        text = f"{text}\n\n{html.escape(extra_block)}"
    return text


def _build_order_record_from_user_data(order_id: int, user_data: Dict[str, Any]) -> OrderRecord:
    return OrderRecord(
        order_id=order_id,
        user_id=user_data["user_id"],
        username=user_data.get("username"),
        first_name=user_data.get("first_name"),
        last_name=user_data.get("last_name"),
        order_type=user_data["order_type_label"],
        subject=user_data["subject"],
        description=user_data["description"],
        file_id=user_data.get("file_id"),
        file_type=user_data.get("file_type"),
        additional_info=user_data.get("additional_info"),
        deadline=user_data.get("deadline"),
        budget=user_data["budget"],
        status="pending",
        executor_id=None,
        executor_username=None,
        group_message_id=None,
        decline_reason=None,
    )


async def _persist_state(
    db: Database,
    user_id: int,
    state: Optional[int],
    user_data: Dict[str, Any],
) -> None:
    state_name = STATE_NAMES.get(state) if state is not None else None
    await db.set_user_state(user_id=user_id, state=state_name, data=user_data)


async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> int:
    """Entry point: send greeting and main menu."""
    user = update.effective_user
    assert user is not None

    context.user_data.clear()
    context.user_data.update(
        {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
    )

    if update.message:
        await update.message.reply_text(GREETING_MESSAGE, reply_markup=main_menu_keyboard())
    else:
        await update.effective_chat.send_message(GREETING_MESSAGE, reply_markup=main_menu_keyboard())

    await _persist_state(db, user.id, CHOOSING_TYPE, context.user_data)
    return CHOOSING_TYPE


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> None:
    """Display help message."""
    if update.message:
        await update.message.reply_text(HELP_MESSAGE)


async def cancel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> int:
    """Cancel the ongoing conversation."""
    user = update.effective_user
    if user:
        await db.clear_user_state(user.id)
    context.user_data.clear()
    if update.message:
        await update.message.reply_text(ORDER_CANCELLED_MESSAGE)
    return ConversationHandler.END


async def handle_order_type_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> int:
    query = update.callback_query
    if not query:
        return CHOOSING_TYPE
    await query.answer()

    payload = query.data or ""
    _, order_type = payload.split(":", 1)
    label = ORDER_TYPES.get(order_type)
    if not label:
        await query.edit_message_text("Неизвестный тип заказа. Попробуйте ещё раз.", reply_markup=main_menu_keyboard())
        return CHOOSING_TYPE

    context.user_data["order_type"] = order_type
    context.user_data["order_type_label"] = label

    await query.edit_message_text(f"Вы выбрали: {label}\n\n{PROMPT_SUBJECT}")
    await _persist_state(db, query.from_user.id, ENTERING_SUBJECT, context.user_data)
    return ENTERING_SUBJECT


async def handle_subject(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> int:
    message = update.message
    if not message or not message.text:
        return ENTERING_SUBJECT

    context.user_data["subject"] = message.text.strip()
    await message.reply_text(PROMPT_DESCRIPTION)
    await _persist_state(db, message.from_user.id, ENTERING_DESCRIPTION, context.user_data)
    return ENTERING_DESCRIPTION


def _extract_file_info(message: Message) -> Tuple[Optional[str], Optional[str]]:
    if message.document:
        return message.document.file_id, "document"
    if message.photo:
        return message.photo[-1].file_id, "photo"
    if message.audio:
        return message.audio.file_id, "audio"
    if message.voice:
        return message.voice.file_id, "voice"
    if message.video:
        return message.video.file_id, "video"
    if message.video_note:
        return message.video_note.file_id, "video_note"
    if message.sticker:
        return message.sticker.file_id, "sticker"
    return None, None


async def handle_description(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> int:
    message = update.message
    if not message:
        return ENTERING_DESCRIPTION

    file_id, file_type = _extract_file_info(message)

    if file_id:
        context.user_data["file_id"] = file_id
        context.user_data["file_type"] = file_type
        context.user_data["description"] = "Файл прикреплен"
    elif message.text:
        context.user_data["description"] = message.text.strip()
        context.user_data.pop("file_id", None)
        context.user_data.pop("file_type", None)
    else:
        await message.reply_text("Пожалуйста, отправьте файл или опишите задачу текстом.")
        return ENTERING_DESCRIPTION

    await message.reply_text(PROMPT_ADDITIONAL)
    await _persist_state(db, message.from_user.id, ENTERING_ADDITIONAL, context.user_data)
    return ENTERING_ADDITIONAL


async def handle_additional(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> int:
    message = update.message
    if not message or not message.text:
        return ENTERING_ADDITIONAL

    context.user_data["additional_info"] = message.text.strip()
    await message.reply_text(PROMPT_DEADLINE)
    await _persist_state(db, message.from_user.id, ENTERING_DEADLINE, context.user_data)
    return ENTERING_DEADLINE


async def handle_deadline(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> int:
    message = update.message
    if not message or not message.text:
        return ENTERING_DEADLINE

    context.user_data["deadline"] = message.text.strip()
    await message.reply_text(PROMPT_BUDGET)
    await _persist_state(db, message.from_user.id, ENTERING_BUDGET, context.user_data)
    return ENTERING_BUDGET


async def handle_budget(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> int:
    message = update.message
    if not message or not message.text:
        return ENTERING_BUDGET

    budget_raw = message.text.strip().replace(",", ".")
    if not BUDGET_PATTERN.match(budget_raw):
        await message.reply_text(ERROR_INVALID_BUDGET)
        return ENTERING_BUDGET

    context.user_data["budget"] = budget_raw

    summary_lines = [
        f"📋 Тип: {context.user_data['order_type_label']}",
        f"📚 Предмет: {context.user_data['subject']}",
        f"📄 Описание: {context.user_data['description']}",
        f"💡 Доп. информация: {context.user_data.get('additional_info', '—')}",
        f"⏰ Дедлайн: {context.user_data.get('deadline', '—')}",
        f"💰 Бюджет: {context.user_data['budget']}",
    ]
    summary = f"{CONFIRMATION_MESSAGE_TITLE}\n\n" + "\n".join(summary_lines)

    await message.reply_text(summary, reply_markup=confirmation_keyboard())
    await _persist_state(db, message.from_user.id, CONFIRMING, context.user_data)
    return CONFIRMING


async def handle_confirmation(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> int:
    query = update.callback_query
    if not query:
        return CONFIRMING

    await query.answer()
    decision = query.data or ""
    if decision.endswith(":no"):
        await query.edit_message_text("Заказ отменен. Нажмите /start, чтобы начать заново.")
        await db.clear_user_state(query.from_user.id)
        context.user_data.clear()
        return ConversationHandler.END

    user_data = context.user_data.copy()
    order_id = await db.create_order(user_data)

    order_record = _build_order_record_from_user_data(order_id, user_data)

    # Send order to group
    group_message_id = await _send_order_to_group(
        context=context,
        config=config,
        order=order_record,
    )
    await db.store_group_message(order_id, group_message_id)

    await query.edit_message_text(ORDER_SUBMITTED_MESSAGE.format(order_id=order_id))
    await db.clear_user_state(query.from_user.id)
    context.user_data.clear()
    return ConversationHandler.END


async def _send_order_to_group(
    *,
    context: CallbackContext,
    config: Config,
    order: OrderRecord,
) -> int:
    order_text = format_group_message(order)
    keyboard = group_order_keyboard(order.order_id)

    message = await context.bot.send_message(
        chat_id=config.group_chat_id,
        text=order_text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    await _forward_attachment_if_any(context, config, order)
    return message.message_id


async def _forward_attachment_if_any(
    context: CallbackContext,
    config: Config,
    order: OrderRecord,
) -> None:
    if not order.file_id or not order.file_type:
        return

    try:
        file_id = order.file_id
        chat_id = config.group_chat_id
        if order.file_type == "document":
            await context.bot.send_document(chat_id=chat_id, document=file_id)
        elif order.file_type == "photo":
            await context.bot.send_photo(chat_id=chat_id, photo=file_id)
        elif order.file_type == "audio":
            await context.bot.send_audio(chat_id=chat_id, audio=file_id)
        elif order.file_type == "voice":
            await context.bot.send_voice(chat_id=chat_id, voice=file_id)
        elif order.file_type == "video":
            await context.bot.send_video(chat_id=chat_id, video=file_id)
        elif order.file_type == "video_note":
            await context.bot.send_video_note(chat_id=chat_id, video_note=file_id)
        elif order.file_type == "sticker":
            await context.bot.send_sticker(chat_id=chat_id, sticker=file_id)
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ Невозможно переслать файл: неподдерживаемый тип.",
            )
    except TelegramError as exc:
        LOGGER.error("Unable to forward attachment for order %s: %s", order.order_id, exc)


async def handle_order_accept(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    order_id = int(query.data.split(":", 1)[1])
    order = await db.get_order(order_id)
    if not order:
        await query.edit_message_text(ORDER_NOT_FOUND_MESSAGE)
        return

    if order.status not in ("pending", "awaiting_decline_reason"):
        await query.answer(ORDER_ALREADY_PROCESSED_MESSAGE, show_alert=True)
        return

    executor = query.from_user
    executor_username = executor.username or executor.full_name

    await db.update_order_status(
        order_id,
        "accepted",
        executor_id=executor.id,
        executor_username=executor.username,
    )

    extra_text = (
        f"✅ ЗАКАЗ ПРИНЯТ\nИсполнитель: @{executor.username}"
        if executor.username
        else f"✅ ЗАКАЗ ПРИНЯТ\nИсполнитель: {executor.full_name}"
    )

    try:
        await context.bot.edit_message_text(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text=format_group_message(order, extra_block=extra_text),
            parse_mode=ParseMode.HTML,
        )
    except TelegramError as exc:
        LOGGER.error("Failed to edit group message for accepted order %s: %s", order_id, exc)

    student_message = ORDER_ACCEPTED_USER_MESSAGE.format(order_id=order_id)
    try:
        await context.bot.send_message(order.user_id, student_message)
    except Forbidden:
        LOGGER.warning("Cannot notify user %s about accepted order %s", order.user_id, order_id)
    except TelegramError as exc:
        LOGGER.error("Error notifying user about accepted order %s: %s", order_id, exc)

    group_text = DECLINE_REASON_TAKEN.format(
        username=executor.username or executor.full_name,
        order_id=order_id,
        budget=order.budget,
    )
    await context.bot.send_message(config.group_chat_id, group_text)


async def handle_order_decline(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    order_id = int(query.data.split(":", 1)[1])
    order = await db.get_order(order_id)
    if not order:
        await query.edit_message_text(ORDER_NOT_FOUND_MESSAGE)
        return

    if order.status != "pending":
        await query.answer(ORDER_ALREADY_PROCESSED_MESSAGE, show_alert=True)
        return

    executor = query.from_user
    await db.update_order_status(
        order_id,
        "awaiting_decline_reason",
        executor_id=executor.id,
        executor_username=executor.username,
    )

    for msg_id, payload in list(DECLINE_REASON_WAITLIST.items()):
        if payload.get("order_id") == order_id:
            DECLINE_REASON_WAITLIST.pop(msg_id, None)

    extra_text = DECLINE_REASON_PENDING.format(username=executor.username or executor.full_name)
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            reply_markup=None,
        )
    except TelegramError as exc:
        LOGGER.error("Failed to remove buttons for order %s: %s", order_id, exc)

    try:
        await context.bot.edit_message_text(
            chat_id=query.message.chat_id,
            message_id=query.message.message_id,
            text=format_group_message(order, extra_block=extra_text),
            parse_mode=ParseMode.HTML,
        )
    except TelegramError as exc:
        LOGGER.error("Failed updating message while awaiting decline reason %s: %s", order_id, exc)

    prompt = DECLINE_REASON_PROMPT_TEMPLATE.format(
        username=executor.username or executor.full_name,
        order_id=order_id,
    )
    prompt_message = await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=prompt,
        reply_markup=ForceReply(selective=True),
    )

    DECLINE_REASON_WAITLIST[prompt_message.message_id] = {
        "order_id": order_id,
        "executor_id": executor.id,
    }

    await query.answer("Пожалуйста, укажите причину отклонения ответом на сообщение.")


async def handle_decline_reason_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> None:
    message = update.message
    if not message or not message.reply_to_message:
        return

    reply_id = message.reply_to_message.message_id
    payload = DECLINE_REASON_WAITLIST.get(reply_id)
    if not payload:
        return

    order_id = payload["order_id"]
    executor_id = payload["executor_id"]

    if message.from_user.id != executor_id:
        await message.reply_text(DECLINE_REASON_REQUIRED_MESSAGE)
        return

    reason_text = message.text.strip() if message.text else ""
    if not reason_text:
        await message.reply_text(DECLINE_REASON_REQUIRED_MESSAGE)
        return

    order = await db.get_order(order_id)
    if not order:
        await message.reply_text(ORDER_NOT_FOUND_MESSAGE)
        return

    await db.update_order_status(
        order_id,
        "declined",
        decline_reason=reason_text,
    )

    DECLINE_REASON_WAITLIST.pop(reply_id, None)

    extra_text = DECLINE_REASON_ACK.format(reason=reason_text)
    try:
        await context.bot.edit_message_text(
            chat_id=config.group_chat_id,
            message_id=order.group_message_id,
            text=format_group_message(order, extra_block=extra_text),
            parse_mode=ParseMode.HTML,
        )
    except TelegramError as exc:
        LOGGER.error("Failed to update declined order message %s: %s", order_id, exc)

    decline_notice = ORDER_DECLINED_USER_MESSAGE.format(
        order_id=order_id,
        reason=reason_text,
    )
    try:
        await context.bot.send_message(order.user_id, decline_notice)
    except Forbidden:
        LOGGER.warning("Cannot notify user %s about declined order %s", order.user_id, order_id)
    except TelegramError as exc:
        LOGGER.error("Error notifying user about declined order %s: %s", order_id, exc)


def build_conversation_handler(config: Config, db: Database) -> ConversationHandler:
    """Create the conversation handler with all states."""
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", partial(start_command, config=config, db=db)),
        ],
        states={
            CHOOSING_TYPE: [
                CallbackQueryHandler(
                    partial(handle_order_type_selection, config=config, db=db),
                    pattern=r"^order_type:",
                )
            ],
            ENTERING_SUBJECT: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    partial(handle_subject, config=config, db=db),
                )
            ],
            ENTERING_DESCRIPTION: [
                MessageHandler(
                    (filters.TEXT | filters.Document.ALL | filters.PHOTO | filters.AUDIO | filters.VOICE | filters.VIDEO | filters.Sticker.ALL | filters.VIDEO_NOTE)
                    & ~filters.COMMAND,
                    partial(handle_description, config=config, db=db),
                )
            ],
            ENTERING_ADDITIONAL: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    partial(handle_additional, config=config, db=db),
                )
            ],
            ENTERING_DEADLINE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    partial(handle_deadline, config=config, db=db),
                )
            ],
            ENTERING_BUDGET: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    partial(handle_budget, config=config, db=db),
                )
            ],
            CONFIRMING: [
                CallbackQueryHandler(
                    partial(handle_confirmation, config=config, db=db),
                    pattern=r"^order_confirm:",
                )
            ],
        },
        fallbacks=[
            CommandHandler("cancel", partial(cancel_command, config=config, db=db))
        ],
        name="order_conversation",
        persistent=False,
        per_chat=True,
        per_user=True,
        per_message=False,
    )


def register_handlers(application: Application, config: Config, db: Database) -> None:
    """Register all bot handlers."""
    conversation = build_conversation_handler(config, db)
    application.add_handler(conversation)
    application.add_handler(
        CommandHandler("help", partial(help_command, config=config, db=db))
    )
    application.add_handler(
        CommandHandler("cancel", partial(cancel_command, config=config, db=db))
    )
    application.add_handler(
        CallbackQueryHandler(
            partial(handle_order_accept, config=config, db=db),
            pattern=r"^order_accept:",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            partial(handle_order_decline, config=config, db=db),
            pattern=r"^order_decline:",
        )
    )
    application.add_handler(
        MessageHandler(
            filters.REPLY & filters.ChatType.GROUPS,
            partial(handle_decline_reason_message, config=config, db=db),
        )
    )
    application.add_error_handler(partial(error_handler, config=config, db=db))


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> None:
    LOGGER.exception("Exception while handling update: %s", context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(GENERIC_ERROR_MESSAGE)
        except TelegramError:
            LOGGER.debug("Failed to send error message to user.")

