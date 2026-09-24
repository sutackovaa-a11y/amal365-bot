import asyncio
import logging
import os
import sqlite3
import urllib.parse
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
)
from aiogram.exceptions import TelegramBadRequest

# Настройка логирования уровня Enterprise
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

API_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

DB_NAME = "amal365.db"

# ==================== ТРАНСЛИТЕРАЦИЯ ГОРОДОВ ДЛЯ API ====================
def transliterate_city(city_name: str) -> str:
    translit_map = {
        'нерюнгри': 'Neryungri',
        'москва': 'Moscow',
        'санкт-петербург': 'Saint Petersburg',
        'казань': 'Kazan',
        'уфа': 'Ufa',
        'грозный': 'Grozny',
        'махачкала': 'Makhachkala',
        'алматы': 'Almaty',
        'астана': 'Astana',
        'ташкент': 'Tashkent',
        'бишкек': 'Bishkek',
        'баку': 'Baku',
        'дубай': 'Dubai',
        'стамбул': 'Istanbul',
        'лондон': 'London'
    }
    cleaned = city_name.strip().lower()
    return translit_map.get(cleaned, city_name.strip())


# ==================== БАЗА ДАННЫХ И МИГРАЦИИ ====================
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
            milestone_40 INTEGER DEFAULT 0,
            milestone_90 INTEGER DEFAULT 0,
            milestone_365 INTEGER DEFAULT 0,
            current_zikr TEXT DEFAULT 'Субханаллях',
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
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sent_notifications (
            user_id INTEGER,
            date TEXT,
            prayer_name TEXT,
            notif_type TEXT,
            PRIMARY KEY (user_id, date, prayer_name, notif_type)
        )
    """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS completed_prayers (
            user_id INTEGER,
            date TEXT,
            prayer_name TEXT,
            PRIMARY KEY (user_id, date, prayer_name)
        )
    """
    )
    conn.commit()
    conn.close()


def get_db_connection():
    return sqlite3.connect(DB_NAME)


# ==================== БАЗА СПЕЦИАЛИЗИРОВАННЫХ ХАДИСОВ ====================
PRAYER_HADITHS = {
    "Фаджр": "«Два ракаата утреннего намаза (Фаджр) лучше этого мира и всего, что в нем». (Муслим)",
    "Зухр": "«Тот, кто совершает четыре ракаата до и четыре после полуденного намаза (Зухр), тому Аллах запретит Огонь». (Ат-Тирмизи)",
    "Аср": "«Тот, кто совершит намаз утренний (Фаджр) и предзакатный (Аср), войдет в Рай». (Аль-Бухари)",
    "Магриб": "«Совершайте закатный намаз (Магриб) вовремя, ибо ангелы записывают благословение этого часа». (Ат-Табарани)",
    "Иша": "«Если бы люди знали, какая благодать в ночном (Иша) и утреннем (Фаджр) намазах, они бы приходили на них даже ползком». (Аль-Бухари, Муслим)"
}

HADITHS_365 = [
    "«Поистине, дела оцениваются только по намерениям, и поистине, каждому человеку достанется только то, что он намеревался совершить...» (Аль-Бухари, Муслим)",
    "«Тот, кто указывает на благое, получает такую же награду, как и совершивший его». (Муслим)",
    "«Лучший из вас тот, кто изучил Коран и обучил ему других». (Аль-Бухари)",
    "«Не уверует никто из вас до тех пор, пока не станет желать своему брату того же, чего желает самому себе». (Аль-Бухари, Муслим)",
    "«Поистине, мягкость присутствует во всем, что украшает собой, и удаляется из всего, что портит его». (Муслим)",
    "«Самый любимый из людей для Аллаха — тот, кто принес больше всего пользы людям». (Ат-Табарани)",
    "«Поминайте Аллаха в благоденствии, и Он вспомнит вас в трудности». (Ат-Тирмизи)",
    "«Истинно верующий не ругает, не проклинает, не совершает непристойных поступков и не сквернословит». (Ат-Тирмизи)",
    "«Поистине, Аллах не смотрит на ваши тела и на вашу внешность, но Он смотрит на ваши сердца и ваши дела». (Муслим)",
    "«Кто молчит, тот спасается». (Ат-Тирмизи)"
]


# ==================== FSM СОСТОЯНИЯ ====================
class OnboardingState(StatesGroup):
    waiting_for_city = State()
    waiting_for_mode = State()


# ==================== КЛАВИАТУРЫ ====================
def get_main_menu_keyboard():
    return ReplyKeyboardMarkup(
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
                KeyboardButton(text="🌅 Утренние и вечерние азкары"),
                KeyboardButton(text="⚙️ Настройки и Режимы"),
            ],
        ],
        resize_keyboard=True,
    )


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
    cursor.execute("SELECT consent FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    if not row or row[0] == 0:
        terms_text = (
            "🌿 **Добро пожаловать в «Амаль 365»!**\n\n"
            "Прежде чем начать наш благословенный путь, пожалуйста, подтвердите согласие на сохранение персонального прогресса. Ваши данные надежно защищены."
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

    try:
        await callback.message.edit_text(
            "Благодарим за доверие! 🤍\n\n🌍 Напишите название вашего города на любом языке (например, *Нерюнгри*, *London*, *Дубай*, *Istanbul*), чтобы мы рассчитывали расписание намазов.",
            parse_mode="Markdown",
        )
    except TelegramBadRequest:
        pass
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
        f"Город **{city_name}** сохранен! 🏙\n\nВыберите ваш духовный режим поклонения:",
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
    cursor.execute("SELECT city FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    city = row[0] if row and row[0] else "Нерюнгри"
    conn.commit()
    conn.close()

    await state.clear()

    try:
        await callback.message.edit_text(
            f"✅ Режим установлен: **{mode_code.upper()}**\n📍 Локация: **{city}**\n\nГлавное меню готово 👇",
            parse_mode="Markdown",
        )
    except TelegramBadRequest:
        pass

    await callback.message.answer(
        "Выберите раздел:", reply_markup=get_main_menu_keyboard()
    )


# ==================== ШАГ ДНЯ (Ближайший намаз) ====================
@router.message(F.text.contains("Шаг дня"))
async def menu_daily_step(message: types.Message):
    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT city FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    city = row[0] if row and row[0] else "Нерюнгри"
    conn.close()

    api_city = transliterate_city(city)
    encoded_city = urllib.parse.quote(api_city)
    api_url = f"http://api.aladhan.com/v1/timingsByCity?city={encoded_city}&country=&method=2"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as resp:
            if resp.status == 200:
                data = await resp.json()
                timings = data["data"]["timings"]
                
                prayers = {
                    "Фаджр": timings.get('Fajr'),
                    "Зухр": timings.get('Dhuhr'),
                    "Аср": timings.get('Asr'),
                    "Магриб": timings.get('Maghrib'),
                    "Иша": timings.get('Isha')
                }
                
                now = datetime.now()
                current_time_str = now.strftime("%H:%M")
                
                next_prayer_name = None
                next_prayer_time = None
                
                for name, p_time in prayers.items():
                    if p_time and p_time > current_time_str:
                        next_prayer_name = name
                        next_prayer_time = p_time
                        break
                
                if not next_prayer_name:
                    next_prayer_name = "Фаджр [Завтра]"
                    next_prayer_time = prayers.get('Fajr')
                
                step_text = (
                    f"✨ **Ваш духовный Шаг дня ({city})**\n\n"
                    f"🎯 **Ближайший намаз:**\n"
                    f"• **{next_prayer_name}** в **{next_prayer_time}**\n\n"
                    f"📚 *«Поистине, намаз предписан верующим в определенное время»* (Сура Ан-Ниса, 103).\n\n"
                    f"Нажмите кнопку после совершения молитвы:"
                )
            else:
                step_text = f"✨ **Шаг дня**\n\nНе удалось получить расписание для города *{city}*."

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Отметить выполненным", callback_data="complete_dynamic_step"
                )
            ]
        ]
    )
    await message.answer(step_text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "complete_dynamic_step")
async def complete_dynamic_step(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    day_of_year = datetime.now().timetuple().tm_yday
    hadith = HADITHS_365[day_of_year % len(HADITHS_365)]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT streak, milestone_40, milestone_90, milestone_365 FROM users WHERE user_id = ?", (user_id,))
    u_row = cursor.fetchone()
    if u_row:
        streak = u_row[0]
        new_streak = streak + 1
        cursor.execute("UPDATE users SET streak = ? WHERE user_id = ?", (new_streak, user_id))
        conn.commit()
    conn.close()

    completion_text = (
        f"{callback.message.text}\n\n"
        f"**✅ ВЫПОЛНЕНО! Машааллах, баракаллаху фикум.** 🤍\n\n"
        f"📖 **Хадис дня:**\n{hadith}\n\n"
        f"🎯 *Шаг зачтен. Продолжайте в том же духе!*"
    )
    try:
        await callback.message.edit_text(completion_text, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer("Шаг успешно засчитан!")


# ==================== ЭЛЕКТРОННЫЙ ТАСБИХ (Автопереключение) ====================
ZIKRS_LIST = [
    {"name": "Субханаллах", "arabic": "سُبْحَانَ اللَّهِ", "target": 33},
    {"name": "Альхамдулиллях", "arabic": "الْحَمْدُ لِلَّهِ", "target": 33},
    {"name": "Аллаху Акбар", "arabic": "اللَّهُ أَكْبَرُ", "target": 33},
    {"name": "Астагфируллах", "arabic": "أَسْتَغْفِرُ اللَّهَ", "target": 100}
]

def get_tasbih_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ НАЖАТЬ ЗИКР (+1)", callback_data="tasbih_inc"
                )
            ],
            [
                InlineKeyboardButton(text="🔄 Сброс", callback_data="tasbih_reset"),
                InlineKeyboardButton(text="🔀 Другой зикр", callback_data="tasbih_change"),
            ],
        ]
    )


@router.message(F.text.contains("Тасбих"))
async def menu_tasbih(message: types.Message):
    user_id = message.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT current_zikr FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    current_zikr_name = row[0] if row and row[0] else "Субханаллах"

    active_zikr = next((z for z in ZIKRS_LIST if z["name"] == current_zikr_name), ZIKRS_LIST[0])

    cursor.execute(
        "SELECT count, target FROM tasbih WHERE user_id = ? AND date = ? AND zikr_name = ?",
        (user_id, today, active_zikr["name"]),
    )
    t_row = cursor.fetchone()
    count = t_row[0] if t_row else 0
    target = t_row[1] if t_row else active_zikr["target"]
    conn.close()

    tasbih_text = (
        f"📿 **Электронный Тасбих**\n\n"
        f"✨ **{active_zikr['name']}** ({active_zikr['arabic']})\n\n"
        f"📊 Счёт: **{count} / {target}**"
    )
    await message.answer(tasbih_text, reply_markup=get_tasbih_keyboard(), parse_mode="Markdown")


@router.callback_query(F.data == "tasbih_inc")
async def tasbih_increment(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT current_zikr FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    current_zikr_name = row[0] if row and row[0] else "Субханаллах"

    active_zikr = next((z for z in ZIKRS_LIST if z["name"] == current_zikr_name), ZIKRS_LIST[0])

    cursor.execute(
        "SELECT count, target FROM tasbih WHERE user_id = ? AND date = ? AND zikr_name = ?",
        (user_id, today, active_zikr["name"]),
    )
    t_row = cursor.fetchone()
    current_count = t_row[0] if t_row else 0
    target = t_row[1] if t_row else active_zikr["target"]

    new_count = current_count + 1
    notification_msg = f"+1 ({new_count})"

    if new_count >= target:
        cursor.execute(
            "INSERT OR REPLACE INTO tasbih (user_id, date, zikr_name, count, target) VALUES (?, ?, ?, ?, ?)",
            (user_id, today, active_zikr["name"], target, target),
        )
        
        current_idx = next((i for i, z in enumerate(ZIKRS_LIST) if z["name"] == current_zikr_name), 0)
        next_idx = (current_idx + 1) % len(ZIKRS_LIST)
        next_zikr = ZIKRS_LIST[next_idx]

        cursor.execute("UPDATE users SET current_zikr = ? WHERE user_id = ?", (next_zikr["name"], user_id))
        conn.commit()

        cursor.execute(
            "SELECT count, target FROM tasbih WHERE user_id = ? AND date = ? AND zikr_name = ?",
            (user_id, today, next_zikr["name"]),
        )
        next_t_row = cursor.fetchone()
        count = next_t_row[0] if next_t_row else 0
        target = next_t_row[1] if next_t_row else next_zikr["target"]
        active_zikr = next_zikr

        notification_msg = f"🎉 Цель выполнена! Автопереход на: {active_zikr['name']}"
    else:
        cursor.execute(
            "INSERT OR REPLACE INTO tasbih (user_id, date, zikr_name, count, target) VALUES (?, ?, ?, ?, ?)",
            (user_id, today, active_zikr["name"], new_count, target),
        )
        conn.commit()
        count = new_count

    conn.close()

    updated_text = (
        f"📿 **Электронный Тасбих**\n\n"
        f"✨ **{active_zikr['name']}** ({active_zikr['arabic']})\n\n"
        f"📊 Счёт: **{count} / {target}**"
    )

    try:
        await callback.message.edit_text(updated_text, reply_markup=get_tasbih_keyboard(), parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer(notification_msg)


@router.callback_query(F.data == "tasbih_reset")
async def tasbih_reset(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT current_zikr FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    current_zikr_name = row[0] if row and row[0] else "Субханаллах"
    active_zikr = next((z for z in ZIKRS_LIST if z["name"] == current_zikr_name), ZIKRS_LIST[0])

    cursor.execute(
        "UPDATE tasbih SET count = 0 WHERE user_id = ? AND date = ? AND zikr_name = ?",
        (user_id, today, active_zikr["name"]),
    )
    conn.commit()
    conn.close()

    updated_text = (
        f"📿 **Электронный Тасбих**\n\n"
        f"✨ **{active_zikr['name']}** ({active_zikr['arabic']})\n\n"
        f"📊 Счёт: **0 / {active_zikr['target']}**"
    )
    try:
        await callback.message.edit_text(updated_text, reply_markup=get_tasbih_keyboard(), parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer("Счетчик сброшен.")


@router.callback_query(F.data == "tasbih_change")
async def tasbih_change(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT current_zikr FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    current_zikr_name = row[0] if row and row[0] else "Субханаллах"

    current_idx = next((i for i, z in enumerate(ZIKRS_LIST) if z["name"] == current_zikr_name), 0)
    next_idx = (current_idx + 1) % len(ZIKRS_LIST)
    next_zikr = ZIKRS_LIST[next_idx]

    cursor.execute("UPDATE users SET current_zikr = ? WHERE user_id = ?", (next_zikr["name"], user_id))
    
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute(
        "SELECT count, target FROM tasbih WHERE user_id = ? AND date = ? AND zikr_name = ?",
        (user_id, today, next_zikr["name"]),
    )
    t_row = cursor.fetchone()
    count = t_row[0] if t_row else 0
    target = t_row[1] if t_row else next_zikr["target"]
    conn.commit()
    conn.close()

    updated_text = (
        f"📿 **Электронный Тасбих**\n\n"
        f"✨ **{next_zikr['name']}** ({next_zikr['arabic']})\n\n"
        f"📊 Счёт: **{count} / {target}**"
    )
    try:
        await callback.message.edit_text(updated_text, reply_markup=get_tasbih_keyboard(), parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer(f"Зикр: {next_zikr['name']}")


# ==================== ВРЕМЯ НАМАЗА ====================
@router.message(F.text.contains("Время намаза"))
async def menu_prayer_times(message: types.Message):
    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT city FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    city = row[0] if row and row[0] else "Нерюнгри"
    conn.close()

    api_city = transliterate_city(city)
    encoded_city = urllib.parse.quote(api_city)
    api_url = f"http://api.aladhan.com/v1/timingsByCity?city={encoded_city}&country=&method=2"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as resp:
            if resp.status == 200:
                data = await resp.json()
                timings = data["data"]["timings"]
                prayer_text = (
                    f"🕌 **Расписание намазов — {city}**\n\n"
                    f"🌅 Фаджр: {timings.get('Fajr')}\n"
                    f"☀️ Восход: {timings.get('Sunrise')}\n"
                    f"🏙 Зухр: {timings.get('Dhuhr')}\n"
                    f"🌇 Аср: {timings.get('Asr')}\n"
                    f"🌆 Магриб: {timings.get('Maghrib')}\n"
                    f"🌙 Иша: {timings.get('Isha')}"
                )
            else:
                prayer_text = f"Не удалось получить расписание для города *{city}*."

    await message.answer(prayer_text, parse_mode="Markdown")


# ==================== АЗКАРЫ И ПРОГРЕСС ====================
@router.message(F.text.contains("азкары"))
async def menu_adhkar(message: types.Message):
    text = (
        "🌅 **Утренние и вечерние азкары**\n\n"
        "🛡 **Утренние (после Фаджра):** Аят аль-Курси, Аль-Ихляс, Аль-Фаляк, Ан-Нас (по 3 раза).\n\n"
        "🌙 **Вечерние (после Магриба):** Аят аль-Курси, Аль-Ихляс, Аль-Фаляк, Ан-Нас (по 3 раза)."
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(F.text.contains("Мой прогресс"))
async def menu_progress(message: types.Message):
    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT streak FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    streak = row[0] if row and row[0] is not None else 0
    conn.close()

    progress_text = (
        f"📊 **Ваш прогресс**\n\n"
        f"🔥 Текущая серия (стрик): **{streak} дн.**\n"
        f"🏆 Вехи постоянства (40 / 90 / 365): Активны и сохраняются навсегда!"
    )
    await message.answer(progress_text, parse_mode="Markdown")


@router.message(F.text.contains("Настройки"))
async def menu_settings(message: types.Message):
    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT city, mode FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    city = row[0] if row and row[0] else "Нерюнгри"
    mode = row[1] if row and row[1] else "alfard"

    settings_text = (
        f"⚙️ **Настройки профиля**\n\n"
        f"📍 Город: **{city}**\n"
        f"🎯 Режим: **{mode.upper()}**\n\n"
        f"Выберите новый режим ниже:"
    )
    await message.answer(settings_text, reply_markup=get_modes_keyboard(), parse_mode="Markdown")


# ==================== ФОНОВЫЙ ПЛАНИРОВЩИК УВЕДОМЛЕНИЙ ====================
async def prayer_notification_loop():
    while True:
        try:
            await asyncio.sleep(60)
            now = datetime.now()
            current_date = now.strftime("%Y-%m-%d")
            current_time_str = now.strftime("%H:%M")
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, city FROM users WHERE consent = 1")
            users = cursor.fetchall()
            conn.close()
            
            for user_id, city in users:
                if not city:
                    city = "Нерюнгри"
                
                api_city = transliterate_city(city)
                encoded_city = urllib.parse.quote(api_city)
                api_url = f"http://api.aladhan.com/v1/timingsByCity?city={encoded_city}&country=&method=2"
                
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(api_url, timeout=5) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                timings = data["data"]["timings"]
                                
                                prayers = {
                                    "Фаджр": timings.get('Fajr'),
                                    "Зухр": timings.get('Dhuhr'),
                                    "Аср": timings.get('Asr'),
                                    "Магриб": timings.get('Maghrib'),
                                    "Иша": timings.get('Isha')
                                }
                                
                                for p_name, p_time in prayers.items():
                                    if not p_time:
                                        continue
                                    
                                    p_dt = datetime.strptime(f"{current_date} {p_time}", "%Y-%m-%d %H:%M")
                                    
                                    # 1. За 5 минут до намаза (специфичный хадис)
                                    notify_5_dt = p_dt - timedelta(minutes=5)
                                    if current_time_str == notify_5_dt.strftime("%H:%M"):
                                        conn = get_db_connection()
                                        cursor = conn.cursor()
                                        cursor.execute(
                                            "SELECT 1 FROM sent_notifications WHERE user_id = ? AND date = ? AND prayer_name = ? AND notif_type = '5_min'",
                                            (user_id, current_date, p_name)
                                        )
                                        if not cursor.fetchone():
                                            hadith = PRAYER_HADITHS.get(p_name, "«Поминайте Аллаха и стремитесь к благому».")
                                            text = (
                                                f"⏰ **До намаза {p_name} осталось 5 минут!**\n\n"
                                                f"📖 **Хадис о намазе:**\n{hadith}\n\n"
                                                f"Подготовьтесь к молитве."
                                            )
                                            try:
                                                await bot.send_message(user_id, text, parse_mode="Markdown")
                                                cursor.execute(
                                                    "INSERT INTO sent_notifications (user_id, date, prayer_name, notif_type) VALUES (?, ?, ?, '5_min')",
                                                    (user_id, current_date, p_name)
                                                )
                                                conn.commit()
                                            except Exception as e:
                                                logger.error(f"Error sending 5_min: {e}")
                                        conn.close()

                                    # 2. Догоняющее напоминание через 10-15 минут после начала намаза
                                    catch_up_dt = p_dt + timedelta(minutes=15)
                                    if current_time_str == catch_up_dt.strftime("%H:%M"):
                                        conn = get_db_connection()
                                        cursor = conn.cursor()
                                        cursor.execute(
                                            "SELECT 1 FROM completed_prayers WHERE user_id = ? AND date = ? AND prayer_name = ?",
                                            (user_id, current_date, p_name)
                                        )
                                        completed = cursor.fetchone()
                                        
                                        cursor.execute(
                                            "SELECT 1 FROM sent_notifications WHERE user_id = ? AND date = ? AND prayer_name = ? AND notif_type = 'catch_up'",
                                            (user_id, current_date, p_name)
                                        )
                                        sent = cursor.fetchone()

                                        if not completed and not sent:
                                            text = (
                                                f"🌿 **Напоминание о фарзе!**\n\n"
                                                f"Время намаза **{p_name}** уже идет. Обязательная молитва — ваша защита и связь со Всевышним. Поторопитесь совершить этот шаг!"
                                            )
                                            try:
                                                await bot.send_message(user_id, text, parse_mode="Markdown")
                                                cursor.execute(
                                                    "INSERT INTO sent_notifications (user_id, date, prayer_name, notif_type) VALUES (?, ?, ?, 'catch_up')",
                                                    (user_id, current_date, p_name)
                                                )
                                                conn.commit()
                                            except Exception as e:
                                                logger.error(f"Error sending catch_up: {e}")
                                        conn.close()

                                    # 3. Вечерний итог после Иша (+1 час после Иша) — короткий и емкий
                                    if p_name == "Иша":
                                        isha_end_dt = p_dt + timedelta(hours=1)
                                        if current_time_str == isha_end_dt.strftime("%H:%M"):
                                            conn = get_db_connection()
                                            cursor = conn.cursor()
                                            cursor.execute(
                                                "SELECT 1 FROM sent_notifications WHERE user_id = ? AND date = ? AND prayer_name = 'Isha_End' AND notif_type = 'evening'",
                                                (user_id, current_date)
                                            )
                                            if not cursor.fetchone():
                                                evening_text = (
                                                    "🌙 **День подошел к концу, и все предписанное выполнено перед Всевышним. Вы сделали всё, что планировали. Спокойной ночи!** ✨"
                                                )
                                                try:
                                                    await bot.send_message(user_id, evening_text, parse_mode="Markdown")
                                                    cursor.execute(
                                                        "INSERT INTO sent_notifications (user_id, date, prayer_name, notif_type) VALUES (?, ?, 'Isha_End', 'evening')",
                                                        (user_id, current_date)
                                                    )
                                                    conn.commit()
                                                except Exception as e:
                                                    logger.error(f"Error sending evening message: {e}")
                                            conn.close()

                except Exception as e:
                    logger.error(f"API prayer error for {city}: {e}")
        except Exception as e:
            logger.error(f"Loop error: {e}")


# ==================== ВЕБ-СЕРВЕР ДЛЯ RENDER ====================
async def handle_ping(request):
    return web.Response(text="Bot is running and alive! 🌿")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server started on port {port}")


# ==================== ЗАПУСК ====================
async def main():
    init_db()
    logger.info("Bot «Амаль 365» initialized successfully.")
    
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot),
        prayer_notification_loop()
    )


if __name__ == "__main__":
    asyncio.run(main())
