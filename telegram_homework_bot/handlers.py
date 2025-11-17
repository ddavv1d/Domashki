from __future__ import annotations

import html
import html
import logging
import re
from functools import partial
from typing import Any, Dict, List, Optional, Tuple

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
    admin_main_keyboard,
    admin_manage_keyboard,
    admin_orders_keyboard,
    admin_remove_keyboard,
    confirmation_keyboard,
    group_order_keyboard,
    main_menu_keyboard,
    payment_request_keyboard,
    payment_review_keyboard,
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
ADMIN_ONLY_MESSAGE = "🚫 <b>Доступ запрещен</b>\n\nУ вас нет прав администратора."
ADMIN_MENU_MESSAGE = (
    "🔐 <b>ПАНЕЛЬ АДМИНИСТРАТОРА</b>\n\n"
    "Добро пожаловать! Выберите нужный раздел:"
)
ADMIN_BROADCAST_PROMPT = (
    "📢 <b>Рассылка объявления</b>\n\n"
    "Введите текст объявления, которое будет отправлено <b>всем пользователям</b> бота.\n\n"
    "💡 <i>Можно использовать форматирование: жирный, курсив, код</i>"
)
ADMIN_BROADCAST_DONE = "✅ <b>Объявление успешно разослано!</b>"
ADMIN_ADD_PROMPT = (
    "➕ <b>Добавление администратора</b>\n\n"
    "Введите <b>Telegram ID</b> пользователя, которого хотите сделать администратором.\n\n"
    "💡 <i>ID можно узнать через @userinfobot</i>"
)
ADMIN_REMOVE_PROMPT = (
    "➖ <b>Удаление администратора</b>\n\n"
    "Выберите администратора для удаления из списка ниже:"
)
ADMIN_ORDER_PROMPT = (
    "📄 <b>Управление заказами</b>\n\n"
    "Нажмите на кнопку, чтобы отметить заказ как <b>выполненный</b>:"
)
ORDER_COMPLETED_USER_MESSAGE = (
    "✅ Ваш заказ #{order_id} отмечен как выполненный. Спасибо, что воспользовались ботом!"
)
ORDER_COMPLETED_GROUP_MESSAGE = "✅ Заказ #{order_id} отмечен как выполненный администратором."

ADMIN_CARD_NUMBER = "7777888899990000"
PAYMENT_INSTRUCTION_MESSAGE = (
    "✅ Ваш заказ #{order_id} принят.\n\n"
    "Пожалуйста, отправьте {budget} на карту {card}. После перевода нажмите кнопку ниже и отправьте квитанцию или скриншот об оплате."
)
PAYMENT_RECEIPT_PROMPT = (
    "Отправьте квитанцию или скриншот оплаты для заказа #{order_id}. Можно прикрепить фото, документ или видео."
)
PAYMENT_RECEIPT_RECEIVED = (
    "Спасибо! Мы отправили квитанцию на проверку. О результате сообщим дополнительно."
)
PAYMENT_APPROVED_USER_MESSAGE = (
    "✅ Оплата по заказу #{order_id} подтверждена. Работа начнётся в ближайшее время."
)
PAYMENT_REJECTED_USER_MESSAGE = (
    "❌ Оплата по заказу #{order_id} не подтверждена. Пожалуйста, проверьте данные и загрузите квитанцию повторно."
)

DECLINE_REASON_WAITLIST: Dict[int, Dict[str, Any]] = {}
ADMIN_ACTION_KEY = "admin_action"
ADMIN_ACTION_PAYLOAD_KEY = "admin_action_payload"
PAYMENT_UPLOAD_ORDER_KEY = "payment_upload_order"

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
        f"📌 Статус: {html.escape(order.status or '—')}\n"
        f"💳 Оплата: {html.escape(order.payment_status or 'не запрошено')}\n"
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
        payment_status="not_requested",
        payment_receipt_file_id=None,
        payment_receipt_type=None,
        payment_submitted_at=None,
        payment_reviewed_by=None,
        payment_reviewed_at=None,
        payment_notes=None,
        completed_at=None,
    )


async def _user_is_admin(user_id: int, db: Database) -> bool:
    return await db.is_admin(user_id)


def _format_order_summary(order: OrderRecord) -> str:
    return (
        f"#{order.order_id}: {order.subject} — {order.status}"
        f" (оплата: {order.payment_status or '—'})"
    )


async def _persist_state(
    db: Database,
    user_id: int,
    state: Optional[int],
    user_data: Dict[str, Any],
) -> None:
    state_name = STATE_NAMES.get(state) if state is not None else None
    await db.set_user_state(user_id=user_id, state=state_name, data=user_data)


async def _send_payment_request_to_student(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    order: OrderRecord,
) -> None:
    message = PAYMENT_INSTRUCTION_MESSAGE.format(
        order_id=order.order_id,
        budget=order.budget,
        card=ADMIN_CARD_NUMBER,
    )
    try:
        await context.bot.send_message(
            chat_id=order.user_id,
            text=message,
            reply_markup=payment_request_keyboard(order.order_id),
        )
    except Forbidden:
        LOGGER.warning("Cannot send payment request to user %s", order.user_id)
    except TelegramError as exc:
        LOGGER.error("Failed to send payment request for order %s: %s", order.order_id, exc)


async def _send_file_to_chat(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    file_type: str,
    file_id: str,
    caption: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> Message:
    if file_type == "document":
        return await context.bot.send_document(
            chat_id=chat_id,
            document=file_id,
            caption=caption,
            reply_markup=reply_markup,
        )
    if file_type == "photo":
        return await context.bot.send_photo(
            chat_id=chat_id,
            photo=file_id,
            caption=caption,
            reply_markup=reply_markup,
        )
    if file_type == "audio":
        return await context.bot.send_audio(
            chat_id=chat_id,
            audio=file_id,
            caption=caption,
            reply_markup=reply_markup,
        )
    if file_type == "voice":
        return await context.bot.send_voice(
            chat_id=chat_id,
            voice=file_id,
            caption=caption,
            reply_markup=reply_markup,
        )
    if file_type == "video":
        return await context.bot.send_video(
            chat_id=chat_id,
            video=file_id,
            caption=caption,
            reply_markup=reply_markup,
        )
    if file_type == "video_note":
        return await context.bot.send_video_note(
            chat_id=chat_id,
            video_note=file_id,
        )
    if file_type == "sticker":
        return await context.bot.send_sticker(
            chat_id=chat_id,
            sticker=file_id,
        )
    raise ValueError(f"Unsupported file type: {file_type}")


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

    LOGGER.info("Start command received from user %s (ID: %s)", user.username, user.id)

    context.user_data.clear()
    context.user_data.update(
        {
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }
    )

    chat = update.effective_chat
    if chat:
        await db.upsert_user_profile(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            chat_id=chat.id,
        )

    # Check if user is admin
    is_admin = await _user_is_admin(user.id, db)

    if update.message:
        await update.message.reply_text(GREETING_MESSAGE, reply_markup=main_menu_keyboard(is_admin=is_admin))
    else:
        await update.effective_chat.send_message(GREETING_MESSAGE, reply_markup=main_menu_keyboard(is_admin=is_admin))

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
        is_admin = await _user_is_admin(query.from_user.id, db)
        await query.edit_message_text("Неизвестный тип заказа. Попробуйте ещё раз.", reply_markup=main_menu_keyboard(is_admin=is_admin))
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


async def handle_payment_upload_request(
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
    _, order_id_str = query.data.split(":")
    order_id = int(order_id_str)
    order = await db.get_order(order_id)
    user = query.from_user

    if not order or order.user_id != user.id:
        await query.answer("Этот заказ вам не принадлежит.", show_alert=True)
        return

    if order.status not in ("awaiting_payment", "payment_review"):
        await query.answer("По этому заказу не требуется квитанция.", show_alert=True)
        return

    context.user_data[PAYMENT_UPLOAD_ORDER_KEY] = order_id
    await query.message.reply_text(PAYMENT_RECEIPT_PROMPT.format(order_id=order_id))


async def handle_payment_receipt_submission(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> None:
    message = update.message
    if not message or not message.from_user:
        return

    # работаем только в приватных чатах
    if update.effective_chat and update.effective_chat.type != "private":
        return

    order_id = context.user_data.get(PAYMENT_UPLOAD_ORDER_KEY)
    if not order_id:
        return

    file_id, file_type = _extract_file_info(message)
    if not file_id or not file_type:
        await message.reply_text("Прикрепите файл или фото квитанции.")
        return

    order = await db.get_order(order_id)
    if not order or order.user_id != message.from_user.id:
        await message.reply_text("Не удалось сопоставить заказ. Нажмите кнопку ещё раз.")
        context.user_data.pop(PAYMENT_UPLOAD_ORDER_KEY, None)
        return

    await db.save_payment_receipt(
        order_id=order_id,
        file_id=file_id,
        file_type=file_type,
        submitted_by=message.from_user.id,
    )
    await db.update_order_status(order_id, "payment_review")
    await db.update_payment_status(
        order_id=order_id,
        status="submitted",
    )
    context.user_data.pop(PAYMENT_UPLOAD_ORDER_KEY, None)
    await message.reply_text(PAYMENT_RECEIPT_RECEIVED)

    # Отправляем файл в группу
    caption = (
        f"💳 Квитанция по заказу #{order_id}\n"
        f"Студент: @{message.from_user.username or message.from_user.full_name}"
    )

    try:
        await _send_file_to_chat(
            context=context,
            chat_id=config.group_chat_id,
            file_type=file_type,
            file_id=file_id,
            caption=caption,
        )
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.error("Failed to send receipt file to group: %s", exc)

    review_text = (
        f"Проверьте оплату заказа #{order_id}. "
        "Если деньги поступили, подтвердите квитанцию."
    )
    await context.bot.send_message(
        chat_id=config.group_chat_id,
        text=review_text,
        reply_markup=payment_review_keyboard(order_id),
    )


async def handle_payment_review_callback(
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
    _, order_id_str, decision = query.data.split(":")
    order_id = int(order_id_str)
    user = query.from_user

    if not await _user_is_admin(user.id, db):
        await query.answer(ADMIN_ONLY_MESSAGE, show_alert=True)
        return

    order = await db.get_order(order_id)
    if not order:
        await query.answer(ORDER_NOT_FOUND_MESSAGE, show_alert=True)
        return

    if decision == "approve":
        await db.update_payment_status(
            order_id=order_id,
            status="confirmed",
            reviewer_id=user.id,
        )
        await db.update_order_status(order_id, "in_progress")
        decision_text = "✅ Оплата подтверждена администратором."
        user_text = PAYMENT_APPROVED_USER_MESSAGE.format(order_id=order_id)
    else:
        await db.update_payment_status(
            order_id=order_id,
            status="rejected",
            reviewer_id=user.id,
        )
        await db.update_order_status(order_id, "awaiting_payment")
        decision_text = "❌ Оплата не подтверждена. Требуется новая квитанция."
        user_text = PAYMENT_REJECTED_USER_MESSAGE.format(order_id=order_id)
        await _send_payment_request_to_student(context=context, order=order)

    # обновляем сообщение в группе
    try:
        if query.message and query.message.caption:
            await query.edit_message_caption(
                caption=f"{query.message.caption}\n\n{decision_text}",
                reply_markup=None,
            )
        else:
            await query.edit_message_text(
                text=f"{query.message.text}\n\n{decision_text}",
                reply_markup=None,
            )
    except TelegramError as exc:
        LOGGER.error("Failed to edit payment review message %s: %s", order_id, exc)

    # уведомляем студента
    try:
        await context.bot.send_message(order.user_id, user_text)
    except Forbidden:
        LOGGER.warning("Cannot notify user %s about payment decision %s", order.user_id, order_id)
    except TelegramError as exc:
        LOGGER.error("Error sending payment decision for order %s: %s", order_id, exc)

    await context.bot.send_message(
        chat_id=config.group_chat_id,
        text=f"Статус оплаты заказа #{order_id}: {decision_text}",
    )
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
        "awaiting_payment",
        executor_id=executor.id,
        executor_username=executor.username,
    )
    await db.update_payment_status(order_id=order_id, status="requested")
    order.status = "awaiting_payment"
    order.executor_id = executor.id
    order.executor_username = executor.username
    order.payment_status = "requested"

    extra_text = (
        f"✅ ЗАКАЗ ПРИНЯТ\nИсполнитель: @{executor.username}"
        if executor.username
        else f"✅ ЗАКАЗ ПРИНЯТ\nИсполнитель: {executor.full_name}"
    )
    extra_text = f"{extra_text}\n💳 Ожидается подтверждение оплаты."

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

    await _send_payment_request_to_student(context=context, order=order)

    group_text = DECLINE_REASON_TAKEN.format(
        username=executor.username or executor.full_name,
        order_id=order_id,
        budget=order.budget,
    )
    await context.bot.send_message(config.group_chat_id, f"{group_text}\n💳 Ожидаем квитанцию от студента.")


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


async def handle_admin_login_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> None:
    """Handle admin login button from main menu."""
    query = update.callback_query
    if not query or not query.from_user:
        return

    await query.answer()

    if not await _user_is_admin(query.from_user.id, db):
        await query.message.reply_text(ADMIN_ONLY_MESSAGE, parse_mode=ParseMode.HTML)
        return

    await query.message.reply_text(
        ADMIN_MENU_MESSAGE,
        reply_markup=admin_main_keyboard(),
        parse_mode=ParseMode.HTML,
    )


async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> None:
    message = update.message
    if not message or not update.effective_user:
        return

    if not await _user_is_admin(update.effective_user.id, db):
        await message.reply_text(ADMIN_ONLY_MESSAGE, parse_mode=ParseMode.HTML)
        return

    await message.reply_text(
        ADMIN_MENU_MESSAGE,
        reply_markup=admin_main_keyboard(),
        parse_mode=ParseMode.HTML,
    )


async def handle_admin_menu_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    if not await _user_is_admin(query.from_user.id, db):
        await query.answer(ADMIN_ONLY_MESSAGE, show_alert=True)
        return

    await query.answer()
    action = query.data.split(":", 1)[1]

    if action == "back":
        await query.edit_message_text(
            ADMIN_MENU_MESSAGE,
            reply_markup=admin_main_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return

    if action == "admins":
        await query.message.reply_text(
            "👥 <b>Управление администраторами</b>\n\nВыберите действие:",
            reply_markup=admin_manage_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return

    if action == "stats":
        stats = await db.get_order_stats()

        status_emoji = {
            "pending": "⏳",
            "awaiting_payment": "💳",
            "payment_review": "🔍",
            "in_progress": "🔄",
            "completed": "✅",
            "declined": "❌",
        }

        lines = [
            "📊 <b>СТАТИСТИКА ЗАКАЗОВ</b>\n",
        ]
        total = 0
        for status, count in stats.items():
            emoji = status_emoji.get(status, "•")
            lines.append(f"{emoji} <b>{status}:</b> {count}")
            total += count
        lines.append(f"\n<b>📈 Всего заказов: {total}</b>")
        await query.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)
        return

    if action == "broadcast":
        context.user_data[ADMIN_ACTION_KEY] = "broadcast"
        await query.message.reply_text(ADMIN_BROADCAST_PROMPT, parse_mode=ParseMode.HTML)
        return

    if action == "orders":
        orders = await db.list_orders(
            statuses=("pending", "awaiting_payment", "payment_review", "in_progress"),
            limit=10,
        )
        if not orders:
            await query.message.reply_text(
                "📭 <b>Нет активных заказов</b>\n\nВсе заказы обработаны.",
                parse_mode=ParseMode.HTML,
            )
            return
        lines = [ADMIN_ORDER_PROMPT, ""]
        actionable_ids: List[int] = []
        for order in orders:
            lines.append(f"• {_format_order_summary(order)}")
            if order.status != "completed":
                actionable_ids.append(order.order_id)
        await query.message.reply_text(
            "\n".join(lines),
            reply_markup=admin_orders_keyboard(actionable_ids),
            parse_mode=ParseMode.HTML,
        )
        return


async def handle_admin_manage_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    if not await _user_is_admin(query.from_user.id, db):
        await query.answer(ADMIN_ONLY_MESSAGE, show_alert=True)
        return

    data = query.data
    await query.answer()

    if data == "admin_add:start":
        context.user_data[ADMIN_ACTION_KEY] = "add_admin"
        await query.message.reply_text(ADMIN_ADD_PROMPT)
        return

    if data == "admin_remove:start":
        admins = await db.list_admins()
        entries = []
        for admin in admins:
            label = admin.username or f"{admin.first_name or ''} {admin.last_name or ''}".strip() or str(admin.user_id)
            entries.append((admin.user_id, label))
        await query.message.reply_text(
            ADMIN_REMOVE_PROMPT,
            reply_markup=admin_remove_keyboard(entries),
        )
        return

    if data.startswith("admin_remove:"):
        target_id = int(data.split(":", 1)[1])
        if target_id == query.from_user.id:
            await query.message.reply_text("Нельзя удалить самого себя.")
            return
        await db.remove_admin(target_id)
        await query.message.reply_text(f"Пользователь {target_id} больше не администратор.")
        return

    if data.startswith("admin_complete:"):
        order_id = int(data.split(":", 1)[1])
        order = await db.get_order(order_id)
        if not order:
            await query.message.reply_text(ORDER_NOT_FOUND_MESSAGE)
            return
        await db.mark_order_completed(order_id)
        updated_order = await db.get_order(order_id)
        extra_text = "✅ Работа завершена администратором."
        if updated_order and updated_order.group_message_id:
            try:
                await context.bot.edit_message_text(
                    chat_id=config.group_chat_id,
                    message_id=updated_order.group_message_id,
                    text=format_group_message(updated_order, extra_block=extra_text),
                    parse_mode=ParseMode.HTML,
                )
            except TelegramError as exc:
                LOGGER.error("Failed to update group message for completion %s: %s", order_id, exc)

        try:
            await context.bot.send_message(
                updated_order.user_id if updated_order else order.user_id,
                ORDER_COMPLETED_USER_MESSAGE.format(order_id=order_id),
            )
        except TelegramError:
            LOGGER.warning("Cannot notify user about completed order %s", order_id)

        await context.bot.send_message(
            config.group_chat_id,
            ORDER_COMPLETED_GROUP_MESSAGE.format(order_id=order_id),
        )
        await query.message.reply_text(f"Заказ #{order_id} отмечен как выполненный.")
        return


async def handle_admin_text_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> None:
    message = update.message
    user = update.effective_user
    if not message or not user:
        return

    action = context.user_data.get(ADMIN_ACTION_KEY)
    if not action:
        return

    if not await _user_is_admin(user.id, db):
        context.user_data.pop(ADMIN_ACTION_KEY, None)
        return

    if action == "add_admin":
        text = message.text.strip()
        if not text.isdigit():
            await message.reply_text("Укажите числовой ID пользователя.")
            return
        new_admin_id = int(text)
        username = None
        first_name = None
        last_name = None
        try:
            chat = await context.bot.get_chat(new_admin_id)
            username = chat.username
            first_name = chat.first_name
            last_name = chat.last_name
        except TelegramError:
            pass
        await db.add_admin(
            user_id=new_admin_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            added_by=user.id,
        )
        await message.reply_text(f"Пользователь {new_admin_id} назначен администратором.")
        context.user_data.pop(ADMIN_ACTION_KEY, None)
        return

    if action == "broadcast":
        text = message.text.strip()
        chat_ids = await db.get_all_user_chat_ids()
        delivered = 0
        for chat_id in chat_ids:
            try:
                await context.bot.send_message(chat_id, text)
                delivered += 1
            except TelegramError:
                continue
        await message.reply_text(f"{ADMIN_BROADCAST_DONE} (доставлено: {delivered})")
        context.user_data.pop(ADMIN_ACTION_KEY, None)
        return


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
        CommandHandler("admin", partial(admin_command, config=config, db=db))
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
        CallbackQueryHandler(
            partial(handle_payment_upload_request, config=config, db=db),
            pattern=r"^payment_upload:",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            partial(handle_payment_review_callback, config=config, db=db),
            pattern=r"^payment_review:",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            partial(handle_admin_login_callback, config=config, db=db),
            pattern=r"^admin_login$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            partial(handle_admin_menu_callback, config=config, db=db),
            pattern=r"^admin_menu:",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            partial(handle_admin_manage_callback, config=config, db=db),
            pattern=r"^admin_(?:add|remove|complete):",
        )
    )
    application.add_handler(
        MessageHandler(
            filters.REPLY & filters.ChatType.GROUPS,
            partial(handle_decline_reason_message, config=config, db=db),
        )
    )
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & filters.TEXT
            & ~filters.COMMAND,
            partial(handle_admin_text_input, config=config, db=db),
        )
    )
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & (
                filters.Document.ALL
                | filters.PHOTO
                | filters.VIDEO
                | filters.AUDIO
                | filters.VOICE
                | filters.VIDEO_NOTE
            ),
            partial(handle_payment_receipt_submission, config=config, db=db),
        )
    )
    # Fallback handler for lost conversation states (must be last)
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
            partial(handle_fallback_message, config=config, db=db),
        ),
        group=1,
    )
    application.add_error_handler(partial(error_handler, config=config, db=db))


async def handle_fallback_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    config: Config,
    db: Database,
) -> None:
    """Handle messages when conversation state is lost."""
    user = update.effective_user
    if not user or not update.message:
        return

    # Clear any saved state
    await db.clear_user_state(user.id)
    context.user_data.clear()

    # Send simple message to use /start
    await update.message.reply_text(
        "Используйте /start для оформления заказа",
        parse_mode=ParseMode.HTML,
    )


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

