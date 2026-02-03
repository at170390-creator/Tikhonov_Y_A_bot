# bot.py
import os
import json
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor

# Нужен для web-сервера (чтобы Render видел открытый порт)
from aiohttp import web


# ---- ЛОГИ ----
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("family-bot")


# ---- НАСТРОЙКИ ----
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    log.error("BOT_TOKEN не задан. Поставь переменную окружения BOT_TOKEN в Render (Environment).")
    # не выходим — позволим ошибке проявиться при запуске бота, но предупредим в лог
DB_FILE = "tasks.json"

# Пользователи (telegram user_id -> имя)
USERS = {
    455919756: "Андрей",
    359501329: "Юля",
}

# Участники, которые могут фигурировать в задачах (для клавиатуры "по человеку")
PARTICIPANTS = ["Юля", "Андрей", "Лиза", "Елисей", "Туман"]


# ---- ХРАНИЛИЩЕ (JSON) ----
def load_tasks():
    if not os.path.exists(DB_FILE):
        return []
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.exception("Не удалось загрузить tasks.json, возвращаю пустой список")
        return []


def save_tasks(tasks):
    try:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)
    except Exception:
        log.exception("Ошибка при сохранении tasks.json")


# ---- УТИЛИТЫ ----
def allowed(uid: int) -> bool:
    return uid in USERS


def receivers(person: str) -> list:
    """
    Кому слать уведомление:
    - если person == "Андрей" или "Юля" -> только этому человеку (если он в USERS)
    - для остальных (дети и т.д.) — родителям (список USERS.keys())
    """
    if person in ("Андрей", "Юля"):
        return [uid for uid, name in USERS.items() if name == person]
    # По задаче: Liza/Eл. -> уведомлять Юлю и Андрея, USERS содержит только их
    return list(USERS.keys())


def parse_due(text: str):
    """Ожидаем формат 'DD.MM.YYYY HH:MM' — возвращаем datetime или None"""
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d.%m.%Y %H:%M")
    except Exception:
        return None


# ---- КНОПКИ ----
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
    for name in PARTICIPANTS:
        kb.add(InlineKeyboardButton(name, callback_data=f"p_{name}"))
    return kb


# ---- ИНИЦИАЛИЗАЦИЯ БОТА ----
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)


# ---- НАПОМИНАНИЯ ----
async def reminder_loop():
    """
    Периодически (каждую минуту) проверяем задачи и шлём напоминания:
    - за сутки (reminded == 0 -> 1)
    - за час (reminded == 1 -> 2)
    Важное: проверяем и сохраняем изменения в tasks.json
    """
    while True:
        try:
            tasks = load_tasks()
            now = datetime.now()
            changed = False

            for t in tasks:
                due_text = t.get("due")
                if not due_text:
                    continue

                due_dt = parse_due(due_text)
                if not due_dt:
                    continue

                diff = (due_dt - now).total_seconds()
                # за сутки
                if 0 < diff <= 86400 and t.get("reminded", 0) == 0:
                    for uid in receivers(t.get("person", "")):
                        try:
                            await bot.send_message(uid, f"📅 Завтра\n{t.get('person','')} — {t.get('text','')}\n{due_text}")
                        except Exception:
                            log.exception("Не удалось отправить напоминание (24h)")
                    t["reminded"] = 1
                    changed = True

                # за час
                if 0 < diff <= 3600 and t.get("reminded", 0) == 1:
                    for uid in receivers(t.get("person", "")):
                        try:
                            await bot.send_message(uid, f"⏰ Через час\n{t.get('person','')} — {t.get('text','')}\n{due_text}")
                        except Exception:
                            log.exception("Не удалось отправить напоминание (1h)")
                    t["reminded"] = 2
                    changed = True

            if changed:
                save_tasks(tasks)
        except Exception:
            log.exception("Ошибка в reminder_loop")
        await asyncio.sleep(60)


# ---- HANDLERS ----

@dp.message_handler(commands=["start"])
async def cmd_start(msg: types.Message):
    if not allowed(msg.from_user.id):
        # если неподтверждённый пользователь — ничего не отвечаем
        return
    await msg.answer(
        "Привет! Формат добавления задачи:\n"
        "Текст Имя, DD.MM.YYYY, HH:MM\n\n"
        "Пример:\n"
        "Танцы Лиза, 03.02.2026, 19:00",
        reply_markup=main_menu()
    )


@dp.message_handler()
async def text_handler(msg: types.Message):
    """
    Ожидаем формат через запятую: 'Текст Имя, дата, время'
    Если не подходит — игнорируем (так удобнее).
    """
    if not allowed(msg.from_user.id):
        return

    text = msg.text.strip()
    if "," not in text:
        # можно добавить подсказку, но чтобы не спамить — пропускаем
        return

    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 3:
        return

    first_part = parts[0].split()
    if not first_part:
        return
    person = first_part[-1]
    task_text = " ".join(first_part[:-1]).strip()
    date_part = parts[1]
    time_part = parts[2]

    due = None
    if date_part != "-" and time_part != "-":
        due = f"{date_part} {time_part}"

    tasks = load_tasks()
    new_task = {
        "id": int(datetime.now().timestamp()),  # простой уникальный id
        "text": task_text,
        "person": person,
        "due": due,
        "reminded": 0
    }
    tasks.append(new_task)
    save_tasks(tasks)

    await msg.answer("✅ Добавлено", reply_markup=main_menu())


# ---- CALLBACKS ----

@dp.callback_query_handler(lambda c: c.data == "add")
async def cb_add(call: types.CallbackQuery):
    await call.answer()
    await call.message.answer("Введи задачу текстом по шаблону:\nТекст Имя, DD.MM.YYYY, HH:MM")


@dp.callback_query_handler(lambda c: c.data == "list")
async def cb_list(call: types.CallbackQuery):
    await call.answer()
    tasks = load_tasks()
    if not tasks:
        await call.message.answer("Пусто")
        return
    lines = [f"{t['person']} — {t['text']} — {t['due'] or 'без даты'}" for t in tasks]
    await call.message.answer("\n".join(lines))


@dp.callback_query_handler(lambda c: c.data == "person")
async def cb_person(call: types.CallbackQuery):
    await call.answer()
    await call.message.answer("Кого показать?", reply_markup=people_menu())


@dp.callback_query_handler(lambda c: c.data.startswith("p_"))
async def cb_show_person(call: types.CallbackQuery):
    await call.answer()
    name = call.data[2:]
    tasks = load_tasks()
    rows = [t for t in tasks if t.get("person") == name]
    if not rows:
        await call.message.answer("Пусто")
        return
    text = "\n".join(f"{t['person']} — {t['text']} — {t['due'] or 'без даты'}" for t in rows)
    await call.message.answer(text)


@dp.callback_query_handler(lambda c: c.data == "today")
async def cb_today(call: types.CallbackQuery):
    await call.answer()
    today = datetime.now().date()
    tasks = load_tasks()
    rows = [t for t in tasks if t.get("due") and parse_due(t["due"]) and parse_due(t["due"]).date() == today]
    if not rows:
        await call.message.answer("Сегодня пусто")
        return
    await call.message.answer("\n".join(f"{t['person']} — {t['text']}" for t in rows))


@dp.callback_query_handler(lambda c: c.data == "tomorrow")
async def cb_tomorrow(call: types.CallbackQuery):
    await call.answer()
    tomorrow = datetime.now().date() + timedelta(days=1)
    tasks = load_tasks()
    rows = [t for t in tasks if t.get("due") and parse_due(t["due"]) and parse_due(t["due"]).date() == tomorrow]
    if not rows:
        await call.message.answer("Завтра пусто")
        return
    await call.message.answer("\n".join(f"{t['person']} — {t['text']}" for t in rows))


@dp.callback_query_handler(lambda c: c.data == "delete")
async def cb_delete_menu(call: types.CallbackQuery):
    await call.answer()
    tasks = load_tasks()
    if not tasks:
        await call.message.answer("Нечего удалять")
        return
    kb = InlineKeyboardMarkup()
    for t in tasks:
        kb.add(InlineKeyboardButton(f"{t['person']} — {t['text'][:30]}", callback_data=f"del_{t['id']}"))
    await call.message.answer("Выберите задачу для удаления", reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data.startswith("del_"))
async def cb_delete(call: types.CallbackQuery):
    await call.answer()
    try:
        tid = int(call.data.split("_", 1)[1])
    except Exception:
        await call.message.answer("Неверный id")
        return
    tasks = load_tasks()
    new_tasks = [t for t in tasks if t.get("id") != tid]
    save_tasks(new_tasks)
    await call.message.answer("Удалено ✅", reply_markup=main_menu())


# ---- Небольшой веб-сервер, чтобы Render видел порт ----
async def start_webserver():
    try:
        port = int(os.getenv("PORT", "8000"))
    except Exception:
        port = 8000

    async def hello(request):
        return web.Response(text="OK")

    app = web.Application()
    app.router.add_get("/", hello)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info(f"Web server started on port {port}")


# ---- СТАРТ всего ----
if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    # задём фоновые задачи
    loop.create_task(reminder_loop())
    loop.create_task(start_webserver())
    # запуск polling (aiogram)
    executor.start_polling(dp, skip_updates=True)
