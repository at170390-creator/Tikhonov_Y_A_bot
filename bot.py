import os
import json
import asyncio
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor


TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)


USERS = {
    455919756: "Андрей",
    359501329: "Юля",
}


DB_FILE = "tasks.json"


# ================= ХРАНИЛИЩЕ =================

def load_tasks():
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_tasks(tasks):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(tasks, f, ensure_ascii=False)


def allowed(uid):
    return uid in USERS


def receivers(person):
    if person in ("Андрей", "Юля"):
        return [uid for uid, name in USERS.items() if name == person]
    return list(USERS.keys())


def parse_due(d):
    try:
        return datetime.strptime(d, "%d.%m.%Y %H:%M")
    except:
        return None


# ================= НАПОМИНАНИЯ =================

async def reminder_loop():
    while True:
        tasks = load_tasks()
        now = datetime.now()

        changed = False

        for t in tasks:
            if not t["due"]:
                continue

            due_time = parse_due(t["due"])
            if not due_time:
                continue

            diff = (due_time - now).total_seconds()

            if 0 < diff <= 86400 and t["reminded"] == 0:
                for uid in receivers(t["person"]):
                    await bot.send_message(uid, f"📅 Завтра\n{t['person']} — {t['text']}\n{t['due']}")
                t["reminded"] = 1
                changed = True

            if 0 < diff <= 3600 and t["reminded"] == 1:
                for uid in receivers(t["person"]):
                    await bot.send_message(uid, f"⏰ Через час\n{t['person']} — {t['text']}\n{t['due']}")
                t["reminded"] = 2
                changed = True

        if changed:
            save_tasks(tasks)

        await asyncio.sleep(60)


# ================= КНОПКИ =================

def main_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("➕ Добавить", callback_data="add"),
        InlineKeyboardButton("📋 Все", callback_data="list"),
        InlineKeyboardButton("👤 По человеку", callback_data="person"),
        InlineKeyboardButton("📅 Сегодня", callback_data="today"),
        InlineKeyboardButton("📅 Завтра", callback_data="tomorrow"),
        InlineKeyboardButton("🗑 Удалить", callback_data="delete"),
    )
    return kb


# ================= СТАРТ =================

@dp.message_handler(commands=["start"])
async def start(msg):
    if not allowed(msg.from_user.id):
        return
    await msg.answer(
        "Формат:\nТекст Имя, дата, время\n\nПример:\nТанцы Лиза, 03.02.2026, 19:00",
        reply_markup=main_menu()
    )


# ================= ДОБАВЛЕНИЕ =================

@dp.message_handler()
async def add_task(msg):
    if not allowed(msg.from_user.id):
        return

    if "," not in msg.text:
        return

    parts = [x.strip() for x in msg.text.split(",")]
    if len(parts) != 3:
        return

    first = parts[0].split()
    person = first[-1]
    text = " ".join(first[:-1])

    date = parts[1]
    time = parts[2]

    due = None
    if date != "-" and time != "-":
        due = f"{date} {time}"

    tasks = load_tasks()

    tasks.append({
        "text": text,
        "person": person,
        "due": due,
        "reminded": 0
    })

    save_tasks(tasks)

    await msg.answer("Добавлено ✅", reply_markup=main_menu())


# ================= ПРОСМОТР =================

def show(msg, rows):
    if not rows:
        return msg.answer("Пусто")
    text = "\n".join(rows)
    return msg.answer(text)


@dp.callback_query_handler(lambda c: c.data == "list")
async def list_all(call):
    tasks = load_tasks()
    rows = [f"{t['person']} — {t['text']} — {t['due'] or 'без даты'}" for t in tasks]
    await show(call.message, rows)


# ================= ЗАПУСК =================

loop = asyncio.get_event_loop()
loop.create_task(reminder_loop())

executor.start_polling(dp)
