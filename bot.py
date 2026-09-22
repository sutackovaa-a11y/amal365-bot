import os
import random
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

# --- Безопасное чтение токена из переменных окружения Render ---
TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)

# База данных пользователей
users = {}

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
    "fajr": "Фаджр",
    "dhuhr": "Зухр",
    "asr": "Аср",
    "maghrib": "Магриб",
    "isha": "Иша",
    "quran": "Коран",
    "sport": "Спорт",
    "book": "Книга"
}

NEXT_PRAYERS = {
    "fajr": "Зухр ☀️",
    "dhuhr": "Аср 🌇",
    "asr": "Магриб 🌙",
    "maghrib": "Иша ✨",
    "isha": None
}

# --- Достоверные хадисы и духовные напоминания ---
PRAISES = [
    "📖 *Пророк ﷺ сказал:* «Самое любимое деяние перед Аллахом — это молитва, совершённая в своё время» (аль-Бухари).",
    "✨ *Напоминание:* «Молитва — это свет» (Муслим). Пусть она озаряет ваш день!",
    "🤍 *Пророк ﷺ сказал:* «Самые любимые дела для Аллаха — те, которые совершаются постоянно, даже если они небольшие» (аль-Бухари, Муслим).",
    "🌿 *Напоминание:* «Ближе всего раб к своему Господу находится тогда, когда совершает земной поклон (суджуд)» (Муслим).",
    "🕌 *Пророк ﷺ сказал:* «Отрадой моих глаз была сделана молитва» (ан-Насаи).",
    "🌱 *Напоминание:* Каждый сделанный шаг и каждое поклонение приближают ваше сердце к Покой и Баракату.",
    "🌤 *Пророк ﷺ сказал:* «Тот, кто совершил утренний намаз (Фаджр), находится под защитой Аллаха» (Муслим).",
    "📖 *Напоминание:* Постоянство в добрых делах — это ключ к истикаме (устойчивости в вере)."
]

MIDDLE_PHRASES = [
    "Осталось всего {rem} отметки(ок). Двигаемся дальше с именем Аллаха!",
    "Ещё {rem} шага(ов) — и день будет закрыт с баракатом!",
    "ИншаАллах, ещё {rem} — и цель на сегодня достигнута.",
    "Шаг за шагом к довольству Всевышнего. Осталось сделать: {rem}."
]

FINISH_MESSAGES = [
    "✨ **Альхамдулиллях! Все обязательные намазы и дела на сегодня выполнены!**\n\n*Пророк ﷺ сказал:* «Пять ежедневных молитв подобны глубокой реке, протекающей у двери каждого из вас, в которой он омывается каждый день по пять раз» (Муслим). Пусть Аллах примет ваш труд! 🤍",
    "🌟 **Альхамдулиллях! День закрыт на 100%!**\n\n*Пророк ﷺ сказал:* «Будь успешен через постоянство». Вы проявили искренность и усердие, отдыхайте с миром в душе! 🌙",
    "🤍 **Какая красота! Все галочки за сегодня собраны.**\n\nПусть Всевышний дарует вам баракат, укрепит ваше сердце на истинном пути и примет каждое поклонение! 🌿",
    "✨ **Альхамдулиллях! День завершен в повиновении Аллаху.**\n\nПусть этот день станет вашей тяжелой чашей на весах добрых дел в Судный день! 📖"
]

def get_user(user_id):
    if user_id not in users:
        users[user_id] = {
            "mode": None,
            "streak": 1,
            "history": {},
            "last_praise": ""
        }
    return users[user_id]

def get_unique_praise(user):
    available = [p for p in PRAISES if p != user.get("last_praise", "")]
    praise = random.choice(available if available else PRAISES)
    user["last_praise"] = praise
    return praise

def calculate_level(streak_days):
    if streak_days >= 365:
        return "🤍 Истикама"
    elif streak_days >= 90:
        return "🌙 Усердие"
    elif streak_days >= 30:
        return "⭐ Собранность"
    elif streak_days >= 7:
        return "🌿 Постоянство"
    else:
        return "🌱 Старт"

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
        types.InlineKeyboardButton("📅 История (7 и 30 дней)", callback_data="show_history"),
        types.InlineKeyboardButton("⚙️ Сменить режим", callback_data="change_mode")
    )
    return markup

@bot.message_handler(commands=['start'])
def start_cmd(message):
    try:
        user = get_user(message.from_user.id)
        if not user["mode"]:
            bot.send_message(
                message.chat.id,
                "🌙 **Ассаляму алейкум! Добро пожаловать в Амаль 365.**\n\n"
                "Выберите удобный режим для старта:",
                reply_markup=get_mode_keyboard(),
                parse_mode="Markdown"
            )
        else:
            send_daily_tracker(message.chat.id, message.from_user.id)
    except Exception as e:
        print(f"Error in start_cmd: {e}")

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
    try:
        user = get_user(call.from_user.id)
        today = get_today_str()

        if today not in user["history"]:
            user["history"][today] = set()

        if call.data.startswith("set_mode_"):
            selected_mode = call.data.replace("set_mode_", "")
            user["mode"] = selected_mode
            bot.answer_callback_query(call.id, "Режим установлен!")
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except Exception:
                pass
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
                bot.answer_callback_query(call.id)

                praise = get_unique_praise(user)
                task_title = TASK_NAMES.get(task, task)
                active_tasks = MODES[user["mode"]]["tasks"]
                total_count = len(active_tasks)
                current_count = len(today_completed)
                rem = total_count - current_count
                next_step = NEXT_PRAYERS.get(task)

                if current_count == total_count:
                    finish = random.choice(FINISH_MESSAGES)
                    msg_text = (
                        f"✅ **{task_title}** — это ваша {current_count}-я галочка!\n\n"
                        f"{finish}"
                    )
                elif next_step:
                    middle_tmpl = random.choice(MIDDLE_PHRASES)
                    middle_str = middle_tmpl.format(rem=rem)
                    msg_text = (
                        f"{praise}\n\n"
                        f"Ловите {current_count}-ю галочку ✅ (**{task_title}**).\n"
                        f"{middle_str} "
                        f"Следующий шаг: **{next_step}**."
                    )
                else:
                    msg_text = (
                        f"{praise}\n\n"
                        f"Ловите {current_count}-ю галочку ✅ (**{task_title}**).\n"
                        f"Уже **{current_count} из {total_count}** выполнено!"
                    )

                bot.send_message(call.message.chat.id, msg_text, parse_mode="Markdown")

            try:
                bot.edit_message_reply_markup(
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=get_main_keyboard(call.from_user.id)
                )
            except Exception:
                pass

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
            prayer_tasks = {"fajr", "dhuhr", "asr", "maghrib", "isha"}
            
            p_7, q_7, b_7, s_7 = 0, 0, 0, 0
            p_30, q_30, b_30, s_30 = 0, 0, 0, 0

            for i in range(30):
                date_check = str((datetime.now() - timedelta(days=i)).date())
                day_tasks = user["history"].get(date_check, set())

                prayers_done = len(day_tasks.intersection(prayer_tasks))

                p_30 += prayers_done
                if "quran" in day_tasks: q_30 += 1
                if "book" in day_tasks: b_30 += 1
                if "sport" in day_tasks: s_30 += 1

                if i < 7:
                    p_7 += prayers_done
                    if "quran" in day_tasks: q_7 += 1
                    if "book" in day_tasks: b_7 += 1
                    if "sport" in day_tasks: s_7 += 1

            history_text = (
                f"📅 **История вашей активности:**\n\n"
                f"🗓 **За 7 дней:**\n"
                f"🕌 Намазы: **{p_7}/35**\n"
                f"📖 Коран: **{q_7} дн.**\n"
                f"📚 Книга: **{b_7} дн.**\n"
                f"🏃 Спорт: **{s_7} дн.**\n\n"
                f"📊 **За 30 дней (месяц):**\n"
                f"🕌 Намазы: **{p_30}/150**\n"
                f"📖 Коран: **{q_30} дн.**\n"
                f"📚 Книга: **{b_30} дн.**\n"
                f"🏃 Спорт: **{s_30} дн.**\n\n"
                f"Каждый день — это шаг к постоянству! 🤍"
            )
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, history_text, parse_mode="Markdown")
    except Exception as e:
        print(f"Error in handle_callbacks: {e}")

bot.infinity_polling(timeout=10, long_polling_timeout=5)
