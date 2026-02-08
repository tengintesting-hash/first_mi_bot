import asyncio
import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterable, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    CommandHandler,
    ContextTypes,
)

DB_PATH = os.getenv("DB_PATH", "/data/database.db")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")

logging.basicConfig(level=logging.INFO)


def ensure_db_dir() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


@contextmanager
def db_cursor():
    ensure_db_dir()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    finally:
        conn.close()


def get_user_by_telegram_id(telegram_id: int) -> Optional[sqlite3.Row]:
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return cursor.fetchone()


def create_user(user: dict, referrer_id: Optional[int]) -> sqlite3.Row:
    with db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO users (telegram_id, username, first_name, last_name, language_code, referrer_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user.get("id"),
                user.get("username"),
                user.get("first_name"),
                user.get("last_name"),
                user.get("language_code"),
                referrer_id,
            ),
        )
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (user.get("id"),))
        return cursor.fetchone()


def update_balance(user_id: int, pro_delta: int, tx_type: str) -> None:
    with db_cursor() as cursor:
        cursor.execute(
            "UPDATE users SET pro_balance = pro_balance + ? WHERE id = ?",
            (pro_delta, user_id),
        )
        cursor.execute(
            "INSERT INTO transactions (user_id, amount_pro, type) VALUES (?, ?, ?)",
            (user_id, pro_delta, tx_type),
        )


def get_required_channels() -> Iterable[sqlite3.Row]:
    with db_cursor() as cursor:
        cursor.execute("SELECT * FROM channels WHERE required = 1")
        return cursor.fetchall()


def set_referrer(user_id: int, referrer_id: int) -> bool:
    with db_cursor() as cursor:
        cursor.execute("SELECT referrer_id FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row or row["referrer_id"]:
            return False
        cursor.execute("UPDATE users SET referrer_id = ? WHERE id = ?", (referrer_id, user_id))
    return True


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user_data = update.effective_user
    user = get_user_by_telegram_id(user_data.id)
    referrer_id = None

    if context.args:
        raw_param = context.args[0]
        if raw_param.startswith("ref_"):
            try:
                ref_tg = int(raw_param.replace("ref_", ""))
            except ValueError:
                ref_tg = None
            if ref_tg and ref_tg != user_data.id:
                referrer = get_user_by_telegram_id(ref_tg)
                if referrer:
                    referrer_id = referrer["id"]

    if not user:
        user = create_user(user_data.to_dict(), referrer_id)
        if referrer_id:
            update_balance(referrer_id, 1000, "invite_reward")
    elif referrer_id:
        if user["referrer_id"] is None and user["id"] != referrer_id:
            if set_referrer(user["id"], referrer_id):
                update_balance(referrer_id, 1000, "invite_reward")

    if user["is_blocked"]:
        await update.message.reply_text("❌ Ваш акаунт заблоковано.")
        return

    if not await is_user_subscribed(update, context):
        await prompt_subscribe(update, context)
        return

    await send_webapp_button(update, context)


async def is_user_subscribed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    for channel in get_required_channels():
        try:
            member = await context.bot.get_chat_member(channel["telegram_id"], user_id)
        except Exception:
            return False
        if member.status not in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}:
            return False
    return True


async def prompt_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    buttons = []
    for channel in get_required_channels():
        buttons.append([InlineKeyboardButton(channel["title"], url=channel["url"])])
    buttons.append([InlineKeyboardButton("✅ Я підписався(лась), перевірити", callback_data="check_subscribe")])
    await update.message.reply_text(
        "Будь ласка, підпишіться на обов'язкові канали:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def send_webapp_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    webapp_url = os.getenv("WEBAPP_URL", "")
    buttons = [[InlineKeyboardButton("🎮 Відкрити WebApp", url=webapp_url)]]
    await update.message.reply_text(
        "Ви підписані на всі канали. Використовуйте /ref для реферального посилання.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def handle_check_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.callback_query:
        return
    await update.callback_query.answer()
    if await is_user_subscribed(update, context):
        await update.callback_query.message.reply_text("✅ Підписку підтверджено!")
        await send_webapp_button(update, context)
    else:
        await update.callback_query.message.reply_text("❌ Ви ще не підписалися на всі канали.")


async def handle_ref(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"Ваше реферальне посилання: https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    )


async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    join_request = update.chat_join_request
    if not join_request:
        return
    await join_request.approve()
    await context.bot.send_message(chat_id=join_request.from_user.id, text="✅ Заявку прийнято. Дякуємо за підписку!")


def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN is required")
    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("ref", handle_ref))
    application.add_handler(CallbackQueryHandler(handle_check_subscribe, pattern="^check_subscribe$"))
    application.add_handler(ChatJoinRequestHandler(handle_join_request))

    application.run_polling()


if __name__ == "__main__":
    main()
