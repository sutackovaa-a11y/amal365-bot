import os
from threading import Thread
from flask import Flask
import telebot
from telebot import types
from datetime import datetime, timedelta

# --- Заглушка веб-сервера для бесплатного тарифа Render ---
app = Flask('')

@app.route('/')
def home():
    return "Amal 365 Bot is running!"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

Thread(target=run_flask, daemon=True).start()

# --- Логика бота Amal 365 ---
TOKEN = '8944360971:AAFZ3DDUIxEB4AP5KHRZGIVkK-lTXRthvaY'
bot = telebot.TeleBot(TOKEN)

# Хранилище данных пользователей
users = {}

MOTIVATION_TEXTS = [
    "📖 Отмечено. Даже небольшой шаг, сделанный сегодня, лучше больших планов на завтра.",
    "🌱 Хорошее дело добавлено в сегодняшний день.",
    "✨ Важный шаг к регулярности выполнен.",
    "🤲 Отлично. Постоянство — ключ к успеху."
]

NEXT_PRAYER_GOALS = {
    "fajr": "🌤 Следующая цель: Зухр",
    "dhuhr": "☀️ Следующая цель: Аср",
    "asr": "🌇 Следующая цель: Магриб",
    "maghrib": "🌙 Следующая цель: Иша",
    "isha": "✨ Все обязательные намазы на сегодня отмечены!"
}

MODES = {
    "min": {
        "title": "🌱 Минимум",
        "tasks": ["fajr", "dhuhr", "asr", "maghrib", "isha"]
    },
    "dev": {
        "title": "🌿 Развитие",
        "tasks": ["fajr", "dhuhr", "asr", "maghrib", "isha", "quran"]
    },
    "growth": {
        "title": "⭐ Рост",
        "tasks": ["fajr", "dhuhr", "asr", "maghrib", "isha", "quran", "sport", "book"]
    }
}

TASK_NAMES = {
    "fajr": "🌅 Фаджр",
    "dhuhr": "☀️ Зухр",
    "asr": "🌤 Аср",
    "maghrib": "🌆 Магриб",
    "isha": "🌌 Иша",
    "quran": "📖 Коран",
    "sport": "🏃 Спорт",
    "book": "📚 Книга"
}

def get_user(user_id):
    if user_id not in users:
        users[user_id] = {
            "mode": None,
            "streak": 1,
            "history": {}  # Структура: {"2026-09-22": {"fajr", "quran"}}
        }
    return users[user_id]

def calculate_level(streak_days):
    if streak_days >= 365:
        return "🤍 Истикама (365+ дн.)"
    elif streak_days >= 90:
        return "🌙 Усердие (90+ дн.)"
    elif streak_days >= 30:
        return "⭐ Собранность (30+ дн.)"
    elif streak_days >= 7:
        return "🌿 Постоянство (7+ дн.)"
    else:
        return "🌱 Старт (0+ дн.)"

def get_today_str():
    return str(datetime.now().date())

def get_mode_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🌱 Минимум (Только 5 намазов)", callback_data="set_mode_min"),
        types.InlineKeyboardButton("🌿 Развитие (Намаз + Коран)", callback_data="set_mode_dev"),
        types.InlineKeyboardButton("⭐ Рост (Намаз + Коран + Спорт + Книга)", callback_data="set_mode_growth")
    )
    return markup

def get_main_keyboard(user_id):
    user = get_user(user_id)
    mode = user["mode"]
    today = get_today_str()
    today_completed = user["history"].get(today, set())

    markup = types.InlineKeyboardMarkup(row_width=1)

    active_tasks = MODES[mode]["tasks"]
    for task in active_tasks:
        is_done = task in today_completed
        icon = "✅" if is_done else "☐"
        name = TASK_NAMES[task]
        markup.add(types.InlineKeyboardButton(f"{icon} {name}", callback_data=f"task_{task}"))

    markup.add(
        types.InlineKeyboardButton("📊 Мой прогресс", callback_data="show_progress"),
        types.InlineKeyboardButton("📅 История за 7 дней", callback_data="show_history"),
        types.InlineKeyboardButton("⚙️ Сменить режим", callback_data="change_mode")
    )
    return markup

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user = get_user(message.from_user.id)
    
    if not user["mode"]:
        bot.send_message(
            message.chat.id,
            "🌙 **Ассаляму алейкум! Добро пожаловать в Амаль 365.**\n\n"
            "Выберите режим для старта:",
            reply_markup=get_mode_keyboard(),
            parse_mode="Markdown"
        )
    else:
        send_daily_tracker(message.chat.id, message.from_user.id)

def send_daily_tracker(chat_id, user_id):
    user = get_user(user_id)
    bot.send_message(
        chat_id,
        f"🌙 **Сегодня**\nРежим: {MODES[user['mode']]['title']}",
        reply_markup=get_main_keyboard(user_id),
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user = get_user(call.from_user.id)
    today = get_today_str()

    if today not in user["history"]:
        user["history"][today] = set()

    if call.data.startswith("set_mode_"):
        selected_mode = call.data.replace("set_mode_", "")
        user["mode"] = selected_mode
        bot.answer_callback_query(call.id, "Режим установлен!")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        send_daily_tracker(call.message.chat.id, call.from_user.id)

    elif call.data == "change_mode":
        bot.edit_message_text(
            "Выберите удобный режим:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_mode_keyboard()
        )

    elif call.data.startswith("task_"):
        task = call.data.replace("task_", "")
        today_completed = user["history"][today]

        if task in today_completed:
            today_completed.remove(task)
            bot.answer_callback_query(call.id, "Отметка снята")
        else:
            today_completed.add(task)
            
            # Сообщение с подсказкой и следующей целью
            if task in NEXT_PRAYER_GOALS:
                msg = NEXT_PRAYER_GOALS[task]
            else:
                msg = "🌱 Хорошее дело добавлено в сегодняшний день."

            bot.answer_callback_query(call.id, msg, show_alert=True)

        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_main_keyboard(call.from_user.id)
        )

    elif call.data == "show_progress":
        level = calculate_level(user["streak"])
        mode_title = MODES[user['mode']]['title'] if user['mode'] else "Не выбран"
        
        progress_text = (
            f"📊 **Личный прогресс**\n\n"
            f"🔥 Серия дней: **{user['streak']} дн.**\n"
            f"⭐ Уровень: **{level}**\n"
            f"⚙️ Текущий режим: **{mode_title}**\n\n"
            f"Никаких рейтингов и сравнений — только ваш личный путь. 🤍"
        )
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, progress_text, parse_mode="Markdown")

    elif call.data == "show_history":
        # Расчёт статистики за последние 7 дней
        prayers_count = 0
        quran_days = 0
        book_days = 0
        sport_days = 0

        prayer_tasks = {"fajr", "dhuhr", "asr", "maghrib", "isha"}

        for i in range(7):
            date_check = str((datetime.now() - timedelta(days=i)).date())
            day_tasks = user["history"].get(date_check, set())

            # Считаем выполненные намазы
            prayers_count += len(day_tasks.intersection(prayer_tasks))
            if "quran" in day_tasks:
                quran_days += 1
            if "book" in day_tasks:
                book_days += 1
            if "sport" in day_tasks:
                sport_days += 1

        history_text = (
            f"📅 **За последние 7 дней:**\n\n"
            f"🕌 Намазы: **{prayers_count}/35**\n"
            f"📖 Коран: **{quran_days} дн.**\n"
            f"📚 Книга: **{book_days} дн.**\n"
            f"🏃 Спорт: **{sport_days} дн.**\n\n"
            f"Каждый день — это новая возможность!"
        )
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, history_text, parse_mode="Markdown")

bot.infinity_polling()
