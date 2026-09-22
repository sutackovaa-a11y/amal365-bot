import os
from threading import Thread
from flask import Flask
import telebot
from telebot import types
from datetime import datetime

# --- Заглушка веб-сервера для бесплатного тарифа Render ---
app = Flask('')

@app.route('/')
def home():
    return "Amal 365 Bot is running!"

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

Thread(target=run_flask).start()

# --- Логика бота Amal 365 ---
TOKEN = '8944360971:AAFZ3DDUIxEB4AP5KHRZGIVkK-lTXRthvaY'
bot = telebot.TeleBot(TOKEN)

users = {}

DUAS = {
    "fajr": "🤲 Пусть Аллах сделает этот день благословенным!",
    "dhuhr": "✨ Баракат в делах и времени!",
    "asr": "🌅 Пусть ваши благие дела будут приняты!",
    "maghrib": "🌙 Приятного вечера и спокойствия душе.",
    "isha": "⭐️ Благословенной ночи и легкого пробуждения.",
    "quran": "📖 Сегодня ты сделал шаг к своей цели.",
    "sport": "🏃 Забота о теле — это тоже аманат.",
    "book": "📚 Знание — свет для сердца."
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
            "completed": set(),
            "last_date": str(datetime.now().date())
        }
    
    today = str(datetime.now().date())
    if users[user_id]["last_date"] != today:
        users[user_id]["completed"] = set()
        users[user_id]["last_date"] = today
        
    return users[user_id]

def calculate_level(streak_days):
    if streak_days >= 365:
        return "🤍 Истикама"
    elif streak_days >= 90:
        return "🌙 Стремящийся"
    elif streak_days >= 30:
        return "⭐ Собранный"
    elif streak_days >= 7:
        return "🌿 Постоянный"
    else:
        return "🌱 Начинающий"

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
    completed = user["completed"]
    markup = types.InlineKeyboardMarkup(row_width=1)

    active_tasks = MODES[mode]["tasks"]
    for task in active_tasks:
        is_done = task in completed
        icon = "✅" if is_done else "☐"
        name = TASK_NAMES[task]
        markup.add(types.InlineKeyboardButton(f"{icon} {name}", callback_data=f"task_{task}"))

    markup.add(
        types.InlineKeyboardButton("📊 Мой прогресс", callback_data="show_progress"),
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
            "Чтобы бот был удобным и не перегружал вас, выберите свой режим:",
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

    if call.data.startswith("set_mode_"):
        selected_mode = call.data.replace("set_mode_", "")
        user["mode"] = selected_mode
        bot.answer_callback_query(call.id, f"Режим установлен!")
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
        
        if task in user["completed"]:
            user["completed"].remove(task)
            bot.answer_callback_query(call.id, "Отметка снята")
        else:
            user["completed"].add(task)
            dua_text = DUAS.get(task, "✅ Отлично сделано!")
            bot.answer_callback_query(call.id, dua_text, show_alert=True)

        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_main_keyboard(call.from_user.id)
        )

    elif call.data == "show_progress":
        level = calculate_level(user["streak"])
        mode_title = MODES[user['mode']]['title'] if user['mode'] else "Не выбран"
        
        progress_text = (
            f"📊 **Ваш личный прогресс**\n\n"
            f"🔥 Серия дней: **{user['streak']} дн.**\n"
            f"⭐ Ваш уровень: **{level}**\n"
            f"⚙️ Текущий режим: **{mode_title}**\n\n"
            f"Никаких рейтингов и сравнений — только ваш путь. 🤍"
        )
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, progress_text, parse_mode="Markdown")

bot.infinity_polling()
