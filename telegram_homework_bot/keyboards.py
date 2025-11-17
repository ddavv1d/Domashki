from __future__ import annotations

from typing import Iterable, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

MAIN_MENU_BUTTONS = [
    ("📝 Домашнее задание", "order_type:homework"),
    ("🎓 Закрыть eclass", "order_type:eclass"),
    ("💼 Проект", "order_type:project"),
    ("🔬 Лабораторная работа", "order_type:laboratory"),
]


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Build the main menu inline keyboard."""
    rows = [[InlineKeyboardButton(text, callback_data=data)] for text, data in MAIN_MENU_BUTTONS]
    # Add admin button at the end
    rows.append([InlineKeyboardButton("👤 Войти как админ", callback_data="admin_login")])
    return InlineKeyboardMarkup(rows)


def confirmation_keyboard() -> InlineKeyboardMarkup:
    """Inline keyboard for confirming or cancelling an order."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Отправить заказ", callback_data="order_confirm:yes"),
                InlineKeyboardButton("❌ Отменить", callback_data="order_confirm:no"),
            ]
        ]
    )


def group_order_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Inline keyboard attached to group order messages."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Принять заказ", callback_data=f"order_accept:{order_id}"
                ),
                InlineKeyboardButton(
                    "❌ Отклонить заказ", callback_data=f"order_decline:{order_id}"
                ),
            ]
        ]
    )


def payment_request_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("📤 Отправить квитанцию", callback_data=f"payment_upload:{order_id}")]]
    )


def payment_review_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Подтверждено", callback_data=f"payment_review:{order_id}:approve"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"payment_review:{order_id}:reject"),
            ]
        ]
    )


def admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👥 Управление администраторами", "admin_menu:admins"),
            ],
            [
                InlineKeyboardButton("📊 Статистика заказов", "admin_menu:stats"),
            ],
            [
                InlineKeyboardButton("📢 Отправить объявление", "admin_menu:broadcast"),
            ],
            [
                InlineKeyboardButton("📄 Заказы и статусы", "admin_menu:orders"),
            ],
        ]
    )


def admin_remove_keyboard(admins: Iterable[tuple[int, str]]) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []
    for user_id, label in admins:
        buttons.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"admin_remove:{user_id}",
                )
            ]
        )
    if not buttons:
        buttons = [[InlineKeyboardButton("Нет доступных админов", callback_data="noop")]]
    return InlineKeyboardMarkup(buttons)


def admin_manage_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Добавить администратора",
                    "admin_add:start",
                )
            ],
            [
                InlineKeyboardButton(
                    "➖ Удалить администратора",
                    "admin_remove:start",
                )
            ],
        ]
    )


def admin_orders_keyboard(orders: Iterable[int]) -> InlineKeyboardMarkup:
    keyboard: List[List[InlineKeyboardButton]] = []
    for order_id in orders:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"✅ Завершить #{order_id}",
                    callback_data=f"admin_complete:{order_id}",
                )
            ]
        )
    if not keyboard:
        keyboard = [[InlineKeyboardButton("Нет заказов", callback_data="noop")]]
    return InlineKeyboardMarkup(keyboard)

