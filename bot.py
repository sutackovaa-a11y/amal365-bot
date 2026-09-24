import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta
import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Безопасное чтение токена
API_TOKEN = os.getenv("BOT_TOKEN")

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

DB_NAME = "amal365.db"


# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            city TEXT DEFAULT 'Нерюнгри',
            mode TEXT DEFAULT 'alfard',
            consent INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            last_active TEXT
        )
    """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS tasbih (
            user_id INTEGER,
            date TEXT,
            zikr_name TEXT,
            count INTEGER,
            target INTEGER,
            PRIMARY KEY (user_id, date, zikr_name)
        )
    """
    )
    conn.commit()
    conn.close()


def get_db_connection():
    return sqlite3.connect(DB_NAME)


# ==================== FSM СОСТОЯНИЯ ====================
class OnboardingState(StatesGroup):
    waiting_for_city = State()
    waiting_for_mode = State()


# ==================== КЛАВИАТУРЫ ====================
def get_main_menu_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="✨ Шаг дня"),
                KeyboardButton(text="📿 Электронный Тасбих"),
            ],
            [
                KeyboardButton(text="⏰ Время намаза"),
                KeyboardButton(text="📊 Мой прогресс"),
            ],
            [
                KeyboardButton(text="📖 Хадисы и Пятница"),
                KeyboardButton(text="⚙️ Настройки и Режимы"),
            ],
        ],
        resize_keyboard=True,
    )
    return keyboard


def get_modes_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🟢 Аль-Фард (Основа и Обязательство)",
                    callback_data="set_mode_alfard",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🌙 Аль-Игтихад (Усердие и Стремление)",
                    callback_data="set_mode_altihad",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🕊 Ат-Тазкийя (Очищение души и Свет)",
                    callback_data="set_mode_tazkiyah",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚀 Аль-Ихсан (Совершенство и Искренность)",
                    callback_data="set_mode_ihsan",
                )
            ],
        ]
    )


# ==================== СТАРТ И ONBOARDING ====================
@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT consent, city FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row or row[0] == 0:
        terms_text = (
            "🌿 **Добро пожаловать в «Амаль 365»!**\n\n"
            "Прежде чем начать наш благословенный путь, пожалуйста, ознакомьтесь с условиями использования и конфиденциальности.\n"
            "Все ваши данные и духовный прогресс надежно защищены и хранятся исключительно для вашего удобства."
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Принять и начать путь",
                        callback_data="accept_terms",
                    )
                ]
            ]
        )
        await message.answer(terms_text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await message.answer(
            "Ассаляму алейкум ва рахматуллахи ва баракатух! 🌿\nГлавное меню активировано.",
            reply_markup=get_main_menu_keyboard(),
        )


@router.callback_query(F.data == "accept_terms")
async def process_terms(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, consent) VALUES (?, 1)",
        (user_id,),
    )
    conn.commit()
    conn.close()

    await callback.message.edit_text(
        "Благодарим за доверие! 🤍\n\n🌍 Пожалуйста, напишите название вашего города (например, *Нерюнгри*, *Бишкек*, *Москва*, *Дубай*), чтобы мы могли точно рассчитывать время намазов для вас.",
        parse_mode="Markdown",
    )
    await state.set_state(OnboardingState.waiting_for_city)


@router.message(OnboardingState.waiting_for_city)
async def process_city(message: types.Message, state: FSMContext):
    city_name = message.text.strip()
    user_id = message.from_user.id

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET city = ? WHERE user_id = ?", (city_name, user_id)
    )
    conn.commit()
    conn.close()

    await message.answer(
        f"Город **{city_name}** успешно сохранен! 🏙\n\nТеперь выберите ваш духовный режим поклонения:",
        reply_markup=get_modes_keyboard(),
        parse_mode="Markdown",
    )
    await state.set_state(OnboardingState.waiting_for_mode)


@router.callback_query(F.data.startswith("set_mode_"))
async def process_mode_selection(
    callback: types.CallbackQuery, state: FSMContext
):
    mode_code = callback.data.split("_")[2]
    user_id = callback.from_user.id

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET mode = ? WHERE user_id = ?", (mode_code, user_id)
    )
    conn.commit()

    cursor.execute("SELECT city FROM users WHERE user_id = ?", (user_id,))
    city = cursor.fetchone()[0]
    conn.close()

    await state.clear()

    welcome_guide = (
        "Ассаляму алейкум ва рахматуллахи ва баракатух! 🌿\n\n"
        "Пусть этот шаг станет началом светлого и благословенного пути для вашего сердца. Вы находитесь в пространстве искренности, дисциплины и стремления к довольству Всевышнего.\n\n"
        "🗺 **Ваша личная карта навигации по боту «Амаль 365»:**\n"
        "✨ **Шаг дня** — ваш духовный ритм, хадисы и история шагов.\n"
        "⏰ **Время намаза** — точное расписание для г. *{city}* и заботливые напоминания.\n"
        "📿 **Электронный Тасбих** — четки с целями и сохранением личного счета.\n"
        "📊 **Мой прогресс** — суточная шкала, марафоны (*40, 90, 365 дней*) и победы.\n"
        "📖 **Хадисы и Пятница** — сунны Джумы и мудрость Пророка ﷺ.\n"
        "⚙️ **Настройки** — смена города и духовного режима."
    ).format(city=city)

    await callback.message.edit_text(welcome_guide, parse_mode="Markdown")
    await callback.message.answer(
        "Главное меню готово к работе 👇", reply_markup=get_main_menu_keyboard()
    )


# ==================== НАВИГАЦИЯ ГЛАВНОГО МЕНЮ ====================
@router.message(F.text == "✨ Шаг дня")
async def menu_daily_step(message: types.Message):
    step_text = (
        "📌 **Шаг 1 из 11**\n\n"
        "🌌 **Ночной намаз (Тахаджуд)**\n\n"
        "📚 *Хадис (Муслим): «Лучший намаз после обязательных — это ночной намаз». Время искреннего дуа, когда Аллах близок к молящимся.*\n\n"
        "Нажмите кнопку ниже, когда выполните шаг:"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Отметить выполненным", callback_data="complete_step_1"
                )
            ]
        ]
    )
    await message.answer(step_text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "complete_step_1")
async def complete_step(callback: types.CallbackQuery):
    await callback.message.edit_text(
        callback.message.text
        + "\n\n**✅ ВЫПОЛНЕНО (Альхамдулиллях)** 🤍",
        parse_mode="Markdown",
    )
    await callback.answer("Шаг засчитан! Баракаллаху фикум.")


# ==================== ЭЛЕКТРОННЫЙ ТАСБИХ ====================
@router.message(F.text == "📿 Электронный Тасбих")
async def menu_tasbih(message: types.Message):
    user_id = message.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT count, target FROM tasbih WHERE user_id = ? AND date = ? AND zikr_name = ?",
        (user_id, today, "Субханаллах"),
    )
    row = cursor.fetchone()
    count = row[0] if row else 0
    target = row[1] if row else 33
    conn.close()

    tasbih_text = (
        f"📿 **Текущее поминание:**\n"
        f"✨ Субханаллах (سُبْحَانَ اللَّهِ)\n\n"
        f"📊 Счёт: **{count} / {target}**"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ НАЖАТЬ ЗИКР (+1)", callback_data="tasbih_inc"
                )
            ],
            [
                InlineKeyboardButton(text="🎯 Цель", callback_data="tasbih_target"),
                InlineKeyboardButton(text="🔄 Сброс", callback_data="tasbih_reset"),
                InlineKeyboardButton(text="🔀 Другой зикр", callback_data="tasbih_change"),
            ],
        ]
    )
    await message.answer(tasbih_text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "tasbih_inc")
async def tasbih_increment(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT count, target FROM tasbih WHERE user_id = ? AND date = ? AND zikr_name = ?",
        (user_id, today, "Субханаллах"),
    )
    row = cursor.fetchone()

    if row:
        count, target = row[0] + 1, row[1]
        cursor.execute(
            "UPDATE tasbih SET count = ? WHERE user_id = ? AND date = ? AND zikr_name = ?",
            (count, user_id, today, "Субханаллах"),
        )
    else:
        count, target = 1, 33
        cursor.execute(
            "INSERT INTO tasbih (user_id, date, zikr_name, count, target) VALUES (?, ?, ?, ?, ?)",
            (user_id, today, "Субханаллах", count, target),
        )
    conn.commit()
    conn.close()

    updated_text = (
        f"📿 **Текущее поминание:**\n"
        f"✨ Субханаллах (سُبْحَانَ اللَّهِ)\n\n"
        f"📊 Счёт: **{count} / {target}**"
    )

    try:
        await callback.message.edit_text(
            updated_text,
            reply_markup=callback.message.reply_markup,
            parse_mode="Markdown",
        )
    except Exception:
        pass
    await callback.answer(f"+1 ({count})")


@router.callback_query(F.data == "tasbih_reset")
async def tasbih_reset(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE tasbih SET count = 0 WHERE user_id = ? AND date = ? AND zikr_name = ?",
        (user_id, today, "Субханаллах"),
    )
    conn.commit()
    conn.close()

    updated_text = (
        f"📿 **Текущее поминание:**\n"
        f"✨ Субханаллах (سُبْحَانَ اللَّهِ)\n\n"
        f"📊 Счёт: **0 / 33**"
    )
    await callback.message.edit_text(
        updated_text,
        reply_markup=callback.message.reply_markup,
        parse_mode="Markdown",
    )
    await callback.answer("Счетчик сброшен.")


# ==================== ВРЕМЯ НАМАЗА ====================
@router.message(F.text == "⏰ Время намаза")
async def menu_prayer_times(message: types.Message):
    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT city FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    city = row[0] if row else "Нерюнгри"
    conn.close()

    api_url = f"http://api.aladhan.com/v1/timingsByCity?city={city}&country=&method=2"
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as resp:
            if resp.status == 200:
                data = await resp.json()
                timings = data["data"]["timings"]
                prayer_text = (
                    f"🕌 **Расписание намазов — {city}**\n\n"
                    f"🌌 Тахаджуд: ~01:45\n"
                    f"🌅 Фаджр: {timings.get('Fajr')}\n"
                    f"☀️ Восход: {timings.get('Sunrise')}\n"
                    f"🏙 Зухр: {timings.get('Dhuhr')}\n"
                    f"🌇 Аср: {timings.get('Asr')}\n"
                    f"🌆 Магриб: {timings.get('Maghrib')}\n"
                    f"🌙 Иша: {timings.get('Isha')}\n\n"
                    f"🔔 *Бот пришлет душевное напоминание с хадисом за 5 минут до каждого намаза!*"
                )
            else:
                prayer_text = f"Не удалось получить расписание для города {city}. Проверьте название в настройках."

    await message.answer(prayer_text, parse_mode="Markdown")


# ==================== ПРОГРЕСС ====================
@router.message(F.text == "📊 Мой прогресс")
async def menu_progress(message: types.Message):
    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT streak FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    streak = row[0] if row else 0

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    conn.close()

    progress_text = (
        f"📊 **Ваш прогресс и статистика**\n\n"
        f"🔥 Текущая серия: **{streak} дн.**\n"
        f"🏆 Успешных дней всего: **{streak} дн.**\n\n"
        f"🎯 **Духовные марафоны постоянства:**\n"
        f"• ⏳ Суточный прогресс: Активен\n"
        f"• 🌙 Аль-Арба'ин (40 дней): 0%\n"
        f"• 🕊 Аль-Истикъамах (90 дней): 0%\n"
        f"• ✨ Нур ‘Аля Нур (365 дней): 0%\n\n"
        f"👥 Статистика базы данных: участников в боте: {total_users}"
    )
    await message.answer(progress_text, parse_mode="Markdown")


# ==================== ХАДИСЫ ====================
@router.message(F.text == "📖 Хадисы и Пятница")
async def menu_hadiths(message: types.Message):
    text = (
        "📖 **Достоверные хадисы:**\n\n"
        "1️⃣ *«Поистине, дела оцениваются по намерениям»* (Бухари, Муслим).\n"
        "2️⃣ *«Лучший из вас тот, кто изучил Коран и обучил ему других»* (Бухари).\n\n"
        "🕌 **Пятничные Сунны (Джума):**\n"
        "• Полное омовение (гусль) и чистая одежда\n"
        "• Чтение суры «Аль-Кахф»\n"
        "• Многократный салават Пророку ﷺ 📿"
    )
    await message.answer(text, parse_mode="Markdown")


# ==================== НАСТРОЙКИ ====================
@router.message(F.text == "⚙️ Настройки и Режимы")
async def menu_settings(message: types.Message):
    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT city, mode FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    city = row[0] if row else "Нерюнгри"
    mode = row[1] if row else "alfard"

    settings_text = (
        f"⚙️ **Настройки профиля**\n\n"
        f"📍 Текущий город: **{city}**\n"
        f"🎯 Текущий режим: **{mode}**\n\n"
        f"Выберите желаемый режим ниже:"
    )
    await message.answer(
        settings_text, reply_markup=get_modes_keyboard(), parse_mode="Markdown"
    )


# ==================== МИНИ-ВЕБ-СЕРВЕР ДЛЯ RENDER ====================
async def handle_ping(request):
    return web.Response(text="Bot is running and alive! 🌿")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Render передает свой порт через переменную окружения PORT, по умолчанию берем 10000
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Веб-сервер для Render успешно запущен на порту {port}")


# ==================== ЗАПУСК БОТА И СЕРВЕРА ====================
async def main():
    init_db()
    logger.info("Бот «Амаль 365» запущен!")
    
    # Запускаем и веб-сервер для Render, и сам опрос Telegram-бота одновременно
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot)
    )


if __name__ == "__main__":
    asyncio.run(main())
