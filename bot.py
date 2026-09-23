import asyncio
import logging
import random
import sqlite3
from datetime import datetime, timedelta
import aiohttp
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# Токен твоего бота (интегрирован)
TOKEN = "8944360971:AAEIgnIdqu7dMIBiqOAyqQhAIsATx8-qt6w"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ==========================================
# 🗄 БАЗА ДАННЫХ SQLITE
# ==========================================


def init_db():
  conn = sqlite3.connect("amal365.db")
  cursor = conn.cursor()
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            streak INTEGER DEFAULT 0,
            tahajjud_enabled INTEGER DEFAULT 0,
            city TEXT DEFAULT 'Бишкек',
            current_step TEXT DEFAULT 'tahajjud',
            last_date TEXT
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            user_id INTEGER,
            date TEXT,
            step TEXT,
            completed INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date, step)
        )
    """)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS seen_hadiths (
            user_id INTEGER,
            hadith_id INTEGER,
            PRIMARY KEY (user_id, hadith_id)
        )
    """)
  conn.commit()
  conn.close()


init_db()

# ==========================================
# 📜 БАЗА ДОСТОВЕРНЫХ ХАДИСОВ
# ==========================================
HADITHS = [
    {
        "id": 1,
        "text": (
            "«Молитва — это свет» (Муслим). Пусть она озаряет ваш день!"
        ),
    },
    {
        "id": 2,
        "text": (
            "«Ближе всего раб к своему Господу находится тогда, когда совершает"
            " земной поклон (суджуд)» (Муслим)."
        ),
    },
    {
        "id": 3,
        "text": (
            "«Самые любимые дела для Аллаха — те, которые совершаются постоянно,"
            " даже если они небольшие» (аль-Бухари, Муслим)."
        ),
    },
    {
        "id": 4,
        "text": (
            "«Отрадой моих глаз была сделана молитва» (ан-Насаи)."
        ),
    },
    {
        "id": 5,
        "text": (
            "«Самое любимое деяние перед Аллахом — это молитва, совершённая в"
            " своё время» (аль-Бухари)."
        ),
    },
    {
        "id": 6,
        "text": (
            "«Пять ежедневных молитв подобны глубокой реке, протекающей у двери"
            " каждого из вас, в которой он омывается каждый день по пять раз»"
            " (Муслим)."
        ),
    },
    {
        "id": 7,
        "text": (
            "«Постоянство в добрых делах — это ключ к истикаме (устойчивости в"
            " вере)»."
        ),
    },
]


def get_unique_hadith(user_id: int) -> str:
  conn = sqlite3.connect("amal365.db")
  cursor = conn.cursor()

  cursor.execute(
      "SELECT hadith_id FROM seen_hadiths WHERE user_id = ?", (user_id,)
  )
  seen = {row[0] for row in cursor.fetchall()}

  available = [h for h in HADITHS if h["id"] not in seen]

  if not available:
    cursor.execute("DELETE FROM seen_hadiths WHERE user_id = ?", (user_id,))
    conn.commit()
    available = HADITHS

  chosen = random.choice(available)
  cursor.execute(
      "INSERT OR IGNORE INTO seen_hadiths (user_id, hadith_id) VALUES (?, ?)",
      (user_id, chosen["id"]),
  )
  conn.commit()
  conn.close()

  return chosen["text"]


# ==========================================
# 🚀 КОМАНДА /START И ГЛАВНОЕ МЕНЮ
# ==========================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
  user_id = message.from_user.id
  today = datetime.now().strftime("%Y-%m-%d")

  conn = sqlite3.connect("amal365.db")
  cursor = conn.cursor()
  cursor.execute(
      "SELECT streak, tahajjud_enabled, city, current_step, last_date FROM users"
      " WHERE user_id = ?",
      (user_id,),
  )
  user = cursor.fetchone()

  if not user:
    cursor.execute(
        "INSERT INTO users (user_id, streak, tahajjud_enabled, city,"
        " current_step, last_date) VALUES (?, 0, 0, 'Бишкек', 'tahajjud', ?)",
        (user_id, today),
    )
    conn.commit()
    tahajjud_en = 0
    current_step = "tahajjud"
  else:
    tahajjud_en = user[1]
    current_step = user[3]
    last_date = user[4]
    if last_date != today:
      current_step = "tahajjud" if tahajjud_en else "fajr"
      cursor.execute(
          "UPDATE users SET current_step = ?, last_date = ? WHERE user_id = ?",
          (current_step, today, user_id),
      )
      conn.commit()

  conn.close()

  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="✨ Начать / Шаг дня", callback_data="next_step")],
          [
              InlineKeyboardButton(text="📊 Мой прогресс", callback_data="progress"),
          ],
      ]
  )

  await message.answer(
      "🌙 **Амаль 365** — ваш личный духовный трекер.\n\nШаг за шагом к"
      " довольству Всевышнего. Давайте проведем этот день с баракатом!",
      reply_markup=keyboard,
      parse_mode="Markdown",
  )


# ==========================================
# 🔄 ПОШАГОВАЯ ЛОГИКА НАМАЗОВ И АЗКАРОВ
# ==========================================
STEPS_ORDER_WITH_TAHAJJUD = [
    "tahajjud",
    "fajr",
    "morning_azkar",
    "dhuhr",
    "asr",
    "evening_azkar",
    "maghrib",
    "isha",
]
STEPS_ORDER_WITHOUT_TAHAJJUD = [
    "fajr",
    "morning_azkar",
    "dhuhr",
    "asr",
    "evening_azkar",
    "maghrib",
    "isha",
]

STEP_NAMES = {
    "tahajjud": "🌙 Тахаджуд",
    "fajr": "🌅 Фаджр",
    "morning_azkar": "☀️ Утренние азкары",
    "dhuhr": "☀️ Зухр",
    "asr": " عصر Аср",
    "evening_azkar": "🌆 Вечерние азкары",
    "maghrib": "🌇 Магриб",
    "isha": "🌃 Иша",
}


@dp.callback_query(F.data == "next_step")
async def process_next_step(callback: types.CallbackQuery):
  user_id = callback.from_user.id
  conn = sqlite3.connect("amal365.db")
  cursor = conn.cursor()

  cursor.execute(
      "SELECT tahajjud_enabled, current_step FROM users WHERE user_id = ?",
      (user_id,),
  )
  res = cursor.fetchone()
  tahajjud_en, current_step = res[0], res[1]

  order = (
      STEPS_ORDER_WITH_TAHAJJUD if tahajjud_en else STEPS_ORDER_WITHOUT_TAHAJJUD
  )

  if current_step not in order:
    await callback.message.answer(
        "Альхамдулиллах! Все обязательные шаги на сегодня уже выполнены! 🌟"
    )
    conn.close()
    return

  hadith = get_unique_hadith(user_id)
  step_title = STEP_NAMES[current_step]

  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text=f"✅ Отметить {step_title}",
                  callback_data=f"done_{current_step}",
              )
          ]
      ]
  )

  await callback.message.answer(
      f"📖 **Полезное напоминание:**\n{hadith}\n\nЦель на сейчас:"
      f" **{step_title}**",
      reply_markup=keyboard,
      parse_mode="Markdown",
  )
  conn.close()
  await callback.answer()


@dp.callback_query(F.data.startswith("done_"))
async def mark_step_done(callback: types.CallbackQuery):
  user_id = callback.from_user.id
  step_done = callback.data.split("_")[1]
  today = datetime.now().strftime("%Y-%m-%d")

  conn = sqlite3.connect("amal365.db")
  cursor = conn.cursor()

  cursor.execute(
      "INSERT OR REPLACE INTO progress (user_id, date, step, completed) VALUES"
      " (?, ?, ?, 1)",
      (user_id, today, step_done),
  )

  cursor.execute(
      "SELECT tahajjud_enabled, current_step FROM users WHERE user_id = ?",
      (user_id,),
  )
  res = cursor.fetchone()
  tahajjud_en, current_step = res[0], res[1]

  order = (
      STEPS_ORDER_WITH_TAHAJJUD if tahajjud_en else STEPS_ORDER_WITHOUT_TAHAJJUD
  )

  try:
    current_index = order.index(step_done)
    if current_index + 1 < len(order):
      next_step = order[current_index + 1]
      cursor.execute(
          "UPDATE users SET current_step = ? WHERE user_id = ?",
          (next_step, user_id),
      )
      conn.commit()
      conn.close()

      await callback.message.edit_text(
          f"✅ {STEP_NAMES[step_done]} успешно отмечен!\nДвигаемся дальше к"
          f" {STEP_NAMES[next_step]} 🚀"
      )
      fake_callback = callback
      fake_callback.data = "next_step"
      await process_next_step(fake_callback)
    else:
      cursor.execute(
          "UPDATE users SET current_step = 'completed', streak = streak + 1"
          " WHERE user_id = ?",
          (user_id,),
      )
      conn.commit()
      conn.close()
      await callback.message.edit_text(
          "✨ **Альхамдулиллах!** Все намазы и азкары на сегодня выполнены!"
          " Пусть Всевышний примет ваш труд! 🤍"
      )
  except Exception as e:
    conn.close()
    await callback.message.answer(
        "Произошла ошибка при обновлении шага. Нажмите /start"
    )

  await callback.answer()


# ==========================================
# 📊 МОЙ ПРОГРЕСС
# ==========================================
@dp.message(Command("progress"))
@dp.callback_query(F.data == "progress")
async def show_progress(event: types.Message | types.CallbackQuery):
  user_id = event.from_user.id if isinstance(event, types.Message) else event.from_user.id
  conn = sqlite3.connect("amal365.db")
  cursor = conn.cursor()
  cursor.execute(
      "SELECT streak, tahajjud_enabled, city FROM users WHERE user_id = ?",
      (user_id,),
  )
  user = cursor.fetchone()
  conn.close()

  streak = user[0] if user else 0
  tahajjud_status = "Включен ✅" if user and user[1] else "Выключен ❌"
  city = user[2] if user else "Бишкек"

  warm_phrases = [
      "Никаких рейтингов и сравнений — только ваш личный путь. 🤍",
      "Шаг за шагом вы растете духовно. Маленькие постоянные дела любимы Аллахом.",
      "Пусть каждый намаз укрепляет ваше сердце и приносит мир.",
  ]
  phrase = random.choice(warm_phrases)

  text = (
      f"📊 **Личный прогресс**\n\n🔥 Серия дней: **{streak} дн.**\n🌙 Тахаджуд:"
      f" {tahajjud_status}\n🌍 Город: {city}\n\n_{phrase}_"
  )

  if isinstance(event, types.Message):
    await event.answer(text, parse_mode="Markdown")
  else:
    await event.message.answer(text, parse_mode="Markdown")
    await event.answer()


async def set_bot_commands():
  commands = [
      BotCommand(command="start", description="🏠 Главное меню"),
      BotCommand(command="progress", description="📊 Мой прогресс"),
  ]
  await bot.set_my_commands(commands)


async def main():
  await set_bot_commands()
  await dp.start_polling(bot)


if __name__ == "__main__":
  asyncio.run(main())
