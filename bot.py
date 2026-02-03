import sqlite3
import asyncio
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor


TOKEN = "8440091071:AAGjsP1bSqLOjimx0nThir3iDSh7zcRUg7o"


bot = Bot(token=TOKEN)
dp = Dispatcher(bot)


USERS = {
    455919756: "Андрей",
    359501329: "Юля",
}


db = sqlite3.connect("tasks.db")
cur = db.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS tasks(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT,
    person TEXT,
    due TEXT,
    reminded INTEGER DEFAULT 0
)
""")
db.commit()


# ================= УТИЛИТЫ =================

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
        now = datetime.now()

        cur.execute("SELECT id, text, person, due, reminded FROM tasks WHERE due IS NOT NULL")
        rows = cur.fetchall()

        for tid, text, person, due, reminded in rows:
            due_time = parse_due(due)
            if not due_time:
                continue

            diff = (due_time - now).total_seconds()
            targets = receivers(person)

            if 0 < diff <= 86400 and reminded == 0:
                for uid in targets:
                    await bot.send_message(uid, f"📅 Завтра\n{person} — {text}\n{due}")
                cur.execute("UPDATE tasks SET reminded=1 WHERE id=?", (tid,))
                db.commit()

            if 0 < diff <= 3600 and reminded == 1:
                for uid in targets:
                    await bot.send_message(uid, f"⏰ Через час\n{person} — {text}\n{due}")
                cur.execute("UPDATE tasks SET reminded=2 WHERE id=?", (tid,))
                db.commit()

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


def people_menu():
    kb = InlineKeyboardMarkup()
    for name in ["Юля", "Андрей", "Лиза", "Елисей", "Туман"]:
        kb.add(InlineKeyboardButton(name, callback_data=f"p_{name}"))
    return kb


# ================= СТАРТ =================

@dp.message_handler(commands=["start"])
async def start(msg):
    if not allowed(msg.from_user.id):
        return

    await msg.answer(
        "Добавление задачи:\n"
        "Текст Имя, дата, время\n\n"
        "Пример:\n"
        "Танцы Лиза, 03.02.2026, 19:00",
        reply_markup=main_menu()
    )


# ================= ДОБАВИТЬ =================

@dp.callback_query_handler(lambda c: c.data == "add")
async def add_help(call):
    await call.message.answer(
        "Введи:\n"
        "Текст Имя, дата, время\n\n"
        "Пример:\n"
        "Танцы Лиза, 03.02.2026, 19:00"
    )


# ================= ДОБАВЛЕНИЕ ЧЕРЕЗ ТЕКСТ =================

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

    cur.execute(
        "INSERT INTO tasks(text, person, due) VALUES (?,?,?)",
        (text, person, due)
    )
    db.commit()

    await msg.answer("Добавлено ✅", reply_markup=main_menu())


# ================= ПРОСМОТР =================

def show(msg, rows):
    if not rows:
        return msg.answer("Пусто")

    text = "\n".join([f"{r[1]} — {r[0]} — {r[2] or 'без даты'}" for r in rows])
    return msg.answer(text)


@dp.callback_query_handler(lambda c: c.data == "list")
async def list_all(call):
    cur.execute("SELECT text, person, due FROM tasks")
    await show(call.message, cur.fetchall())


# ===== ПО ЧЕЛОВЕКУ =====

@dp.callback_query_handler(lambda c: c.data == "person")
async def choose_person(call):
    await call.message.answer("Кого показать?", reply_markup=people_menu())


@dp.callback_query_handler(lambda c: c.data.startswith("p_"))
async def show_person(call):
    name = call.data[2:]
    cur.execute("SELECT text, person, due FROM tasks WHERE person=?", (name,))
    await show(call.message, cur.fetchall())


# ===== СЕГОДНЯ/ЗАВТРА =====

@dp.callback_query_handler(lambda c: c.data == "today")
async def today(call):
    today = datetime.now().date()

    cur.execute("SELECT text, person, due FROM tasks WHERE due IS NOT NULL")
    rows = [r for r in cur.fetchall() if parse_due(r[2]) and parse_due(r[2]).date() == today]

    await show(call.message, rows)


@dp.callback_query_handler(lambda c: c.data == "tomorrow")
async def tomorrow(call):
    tomorrow = datetime.now().date() + timedelta(days=1)

    cur.execute("SELECT text, person, due FROM tasks WHERE due IS NOT NULL")
    rows = [r for r in cur.fetchall() if parse_due(r[2]) and parse_due(r[2]).date() == tomorrow]

    await show(call.message, rows)


# ===== УДАЛЕНИЕ =====

@dp.callback_query_handler(lambda c: c.data == "delete")
async def delete_menu(call):
    cur.execute("SELECT id, text FROM tasks")
    rows = cur.fetchall()

    kb = InlineKeyboardMarkup()
    for tid, text in rows:
        kb.add(InlineKeyboardButton(text[:30], callback_data=f"del_{tid}"))

    await call.message.answer("Что удалить?", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data.startswith("del_"))
async def delete_task(call):
    tid = int(call.data[4:])
    cur.execute("DELETE FROM tasks WHERE id=?", (tid,))
    db.commit()
    await call.message.answer("Удалено", reply_markup=main_menu())


# ================= ЗАПУСК =================

loop = asyncio.get_event_loop()
loop.create_task(reminder_loop())

executor.start_polling(dp)
