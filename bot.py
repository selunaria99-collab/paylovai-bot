import os
import sqlite3
import asyncio
from dotenv import load_dotenv
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_NAME = "payments.db"


def db():
    return sqlite3.connect(DB_NAME)


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            text TEXT NOT NULL,
            is_active INTEGER DEFAULT 0
        )
    """)
cur.execute("""
    CREATE TABLE IF NOT EXISTS allowed_users (
        telegram_id INTEGER PRIMARY KEY
    )
""")
    conn.commit()
    conn.close()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def main_keyboard(user_id: int):
    kb = ReplyKeyboardBuilder()
    kb.button(text="Получить платежку")

    if is_admin(user_id):
        kb.button(text="Админка")

    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True)


@dp.message(CommandStart())
async def start(message: Message):
    await message.answer(
        "Привет. Нажми кнопку, чтобы получить актуальную платежку.",
        reply_markup=main_keyboard(message.from_user.id)
    )


@dp.message(F.text == "Получить платежку")
async def get_payment(message: Message):
    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT name, text FROM payments WHERE is_active = 1 LIMIT 1")
    payment = cur.fetchone()

    conn.close()

    if not payment:
        await message.answer("Сейчас нет активной платежки.")
        return

    name, text = payment
    await message.answer(f"✅ Актуальная платежка:\n\n{name}\n\n{text}")


@dp.message(F.text == "Админка")
@dp.message(Command("admin"))
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа.")
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить платежку", callback_data="add_payment")
    kb.button(text="📋 Список платежек", callback_data="list_payments")
    kb.button(text="⛔ Выключить активную", callback_data="disable_active")
    kb.adjust(1)

    await message.answer("Админка:", reply_markup=kb.as_markup())


@dp.callback_query(F.data == "list_payments")
async def list_payments(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа")
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT id, name, is_active FROM payments ORDER BY id DESC")
    rows = cur.fetchall()

    conn.close()

    if not rows:
        await callback.message.answer("Платежек пока нет.")
        return

    for payment_id, name, is_active in rows:
        status = "✅ активна" if is_active else "⚪ выключена"

        kb = InlineKeyboardBuilder()
        kb.button(text="Сделать активной", callback_data=f"activate:{payment_id}")
        kb.button(text="Удалить", callback_data=f"delete:{payment_id}")
        kb.adjust(1)

        await callback.message.answer(
            f"#{payment_id} — {name}\nСтатус: {status}",
            reply_markup=kb.as_markup()
        )


@dp.callback_query(F.data.startswith("activate:"))
async def activate_payment(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа")
        return

    payment_id = int(callback.data.split(":")[1])

    conn = db()
    cur = conn.cursor()

    cur.execute("UPDATE payments SET is_active = 0")
    cur.execute("UPDATE payments SET is_active = 1 WHERE id = ?", (payment_id,))

    conn.commit()
    conn.close()

    await callback.message.answer("✅ Эта платежка теперь активная.")


@dp.callback_query(F.data == "disable_active")
async def disable_active(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа")
        return

    conn = db()
    cur = conn.cursor()

    cur.execute("UPDATE payments SET is_active = 0")

    conn.commit()
    conn.close()

    await callback.message.answer("⛔ Активная платежка выключена.")


@dp.callback_query(F.data.startswith("delete:"))
async def delete_payment(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа")
        return

    payment_id = int(callback.data.split(":")[1])

    conn = db()
    cur = conn.cursor()

    cur.execute("DELETE FROM payments WHERE id = ?", (payment_id,))

    conn.commit()
    conn.close()

    await callback.message.answer("🗑 Платежка удалена.")


@dp.callback_query(F.data == "add_payment")
async def add_payment_instruction(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа")
        return

    await callback.message.answer(
        "Чтобы добавить платежку, отправь сообщение в формате:\n\n"
        "/add Название платежки | Текст платежки\n\n"
        "Пример:\n"
        "/add Сбер 1 | Карта 4276 0000 0000 0000 Иван И."
    )


@dp.message(Command("add"))
async def add_payment(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("У тебя нет доступа.")
        return

    raw = message.text.replace("/add", "", 1).strip()

    if "|" not in raw:
        await message.answer("Неверный формат. Используй:\n/add Название | Текст платежки")
        return

    name, text = raw.split("|", 1)
    name = name.strip()
    text = text.strip()

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO payments (name, text, is_active) VALUES (?, ?, 0)",
        (name, text)
    )

    conn.commit()
    conn.close()

    await message.answer("✅ Платежка добавлена.")
    
async def health_check(request):
    return web.Response(text="OK")


async def start_health_server():
    port = int(os.getenv("PORT", 10000))

    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/healthz", health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
async def main():
    init_db()
    await start_health_server()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
