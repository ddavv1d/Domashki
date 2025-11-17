from __future__ import annotations

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

