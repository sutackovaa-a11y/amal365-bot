import asyncio
import logging
import os
import sqlite3
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
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

# Настройка логирования
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

# ==================== КЭШ И ТОЧНЫЙ ГЕОКОДИНГ С ЧАСОВЫМ ПОЯСОМ ====================
TIMINGS_CACHE = {}

def translit_city(text: str) -> str:
    mapping = {
        'нерюнгри': 'Neryungri',
        'москва': 'Moscow',
        'санкт-петербург': 'Saint Petersburg',
        'казань': 'Kazan',
        'новосибирск': 'Novosibirsk',
        'екатеринбург': 'Yekaterinburg',
        'уфа': 'Ufa',
        'грозный': 'Grozny',
        'махачкала': 'Makhachkala',
        'якутск': 'Yakutsk',
        'алматы': 'Almaty',
        'ташкент': 'Tashkent',
        'бишкек': 'Bishkek',
        'дубай': 'Dubai',
        'стамбул': 'Istanbul'
    }
    text_lower = text.lower().strip()
    if text_lower in mapping:
        return mapping[text_lower]
    
    cyr_to_lat = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e', 'ж': 'zh',
        'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
        'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'ts',
        'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
    }
    return ''.join(cyr_to_lat.get(char, char) for char in text_lower).capitalize()

async def get_timings_data(city: str):
    today = datetime.now().strftime("%Y-%m-%d")
    cache_key = (city.lower().strip(), today)
    
    if cache_key in TIMINGS_CACHE:
        return TIMINGS_CACHE[cache_key]
    
    lat_city = translit_city(city)
    async with aiohttp.ClientSession() as session:
        # Уровень 1: Поиск по городу со страной
        try:
            url_1 = f"http://api.aladhan.com/v1/timingsByCity?city={urllib.parse.quote(lat_city)}&country=Russia&method=2"
            async with session.get(url_1, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == 200:
                        res = {
                            "timings": data["data"]["timings"],
                            "timezone": data["data"]["meta"].get("timezone", "UTC")
                        }
                        TIMINGS_CACHE[cache_key] = res
                        return res
        except Exception as e:
            logger.error(f"Level 1 timing error: {e}")

        # Уровень 2: Поиск по адресу (универсальный геокодинг)
        try:
            url_2 = f"http://api.aladhan.com/v1/timingsByAddress?address={urllib.parse.quote(city)}&method=2"
            async with session.get(url_2, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == 200:
                        res = {
                            "timings": data["data"]["timings"],
                            "timezone": data["data"]["meta"].get("timezone", "UTC")
                        }
                        TIMINGS_CACHE[cache_key] = res
                        return res
        except Exception as e:
            logger.error(f"Level 2 timing error: {e}")

    return None

def get_local_now(timezone_str: str) -> datetime:
    try:
        return datetime.now(ZoneInfo(timezone_str))
    except Exception:
        return datetime.now()


# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            city TEXT DEFAULT 'Нерюнгри',
            mode TEXT DEFAULT 'Аль-Фард (Основа и Обязательство)',
            consent INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            health_streak INTEGER DEFAULT 0,
            current_zikr TEXT DEFAULT 'Субханаллах',
            tasbih_target INTEGER DEFAULT 33,
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
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS completed_health (
            user_id INTEGER,
            date TEXT,
            PRIMARY KEY (user_id, date)
        )
    """
    )
    conn.commit()
    conn.close()


def get_db_connection():
    return sqlite3.connect(DB_NAME)


# ==================== БАЗА ХАДИСОВ ====================
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
    "«Истинно верующий не ругает, не проклинает, не совершает непристойных поступков и не сквернословит». (Ат-Тирмизи)"
]


# ==================== FSM СОСТОЯНИЯ ====================
class OnboardingState(StatesGroup):
    waiting_for_city = State()
    waiting_for_mode = State()
    changing_city = State()


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
            [InlineKeyboardButton(text="🟢 Аль-Фард (Основа и Обязательство)", callback_data="set_mode_alfard")],
            [InlineKeyboardButton(text="🌙 Аль-Игтихад (Усердие и Стремление)", callback_data="set_mode_altihad")],
            [InlineKeyboardButton(text="🕊 Ат-Тазкийя (Очищение души и Свет)", callback_data="set_mode_tazkiyah")],
            [InlineKeyboardButton(text="🚀 Аль-Ихсан (Совершенство и Искренность)", callback_data="set_mode_ihsan")],
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
            "🌿 **Добро пожаловать в духовный компаньон «Амаль 365»!**\n\n"
            "Прежде чем начать наш благословенный путь, пожалуйста, подтвердите согласие на сохранение личного прогресса. Ваши данные в абсолютной безопасности."
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="✅ Принять и начать путь", callback_data="accept_terms")]]
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
    cursor.execute("INSERT OR REPLACE INTO users (user_id, consent) VALUES (?, 1)", (user_id,))
    conn.commit()
    conn.close()

    await callback.message.edit_text(
        "Благодарим за доверие! 🤍\n\n🌍 Напишите название вашего города или региона (например, *Нерюнгри*, *Москва*, *Казань*), чтобы система точно определила расписание намазов.",
        parse_mode="Markdown",
    )
    await state.set_state(OnboardingState.waiting_for_city)


@router.message(OnboardingState.waiting_for_city)
async def process_city(message: types.Message, state: FSMContext):
    city_name = message.text.strip()
    if city_name.startswith("/") or city_name in ["✨ Шаг дня", "📿 Электронный Тасбих", "⏰ Время намаза", "📊 Мой прогресс", "🌅 Утренние и вечерние азкары", "⚙️ Настройки и Режимы"]:
        await message.answer("Пожалуйста, введите название вашего населенного пункта текстом (например: *Нерюнгри*).")
        return

    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET city = ? WHERE user_id = ?", (city_name, user_id))
    conn.commit()
    conn.close()

    await message.answer(
        f"Локация **{city_name}** успешно сохранена! 🏙\n\nТеперь выберите ваш духовный режим поклонения:",
        reply_markup=get_modes_keyboard(),
        parse_mode="Markdown",
    )
    await state.set_state(OnboardingState.waiting_for_mode)


@router.message(OnboardingState.changing_city)
async def process_city_change(message: types.Message, state: FSMContext):
    city_name = message.text.strip()
    if city_name.startswith("/"):
        await message.answer("Введите корректное название города текстом.")
        return

    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET city = ? WHERE user_id = ?", (city_name, user_id))
    conn.commit()
    conn.close()

    await state.clear()
    await message.answer(f"✅ Город/регион успешно изменен на: **{city_name}**", reply_markup=get_main_menu_keyboard(), parse_mode="Markdown")


MODE_NAMES_MAP = {
    "alfard": "Аль-Фард (Основа и Обязательство)",
    "altihad": "Аль-Игтихад (Усердие и Стремление)",
    "tazkiyah": "Ат-Тазкийя (Очищение души и Свет)",
    "ihsan": "Аль-Ихсан (Совершенство и Искренность)"
}

@router.callback_query(F.data.startswith("set_mode_"))
async def process_mode_selection(callback: types.CallbackQuery, state: FSMContext):
    mode_code = callback.data.split("_")[2]
    mode_rus = MODE_NAMES_MAP.get(mode_code, "Аль-Фард (Основа и Обязательство)")
    user_id = callback.from_user.id

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET mode = ? WHERE user_id = ?", (mode_rus, user_id))
    cursor.execute("SELECT city FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    city = row[0] if row and row[0] else "Нерюнгри"
    conn.commit()
    conn.close()

    await state.clear()
    try:
        await callback.message.edit_text(
            f"✅ Режим установлен: **{mode_rus}**\n📍 Локация: **{city}**\n\nГлавное меню готово 👇",
            parse_mode="Markdown",
        )
    except Exception:
        pass
    await callback.message.answer("Выберите нужный раздел в меню:", reply_markup=get_main_menu_keyboard())


# ==================== ШАГ ДНЯ (С точным расчетом по часовому поясу) ====================
@router.message(F.text == "✨ Шаг дня")
async def menu_daily_step(message: types.Message):
    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT city FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    city = row[0] if row and row[0] else "Нерюнгри"
    conn.close()

    res = await get_timings_data(city)
    
    if res:
        timings = res["timings"]
        tz_str = res["timezone"]
        
        prayers = {
            "Фаджр": timings.get('Fajr'),
            "Зухр": timings.get('Dhuhr'),
            "Аср": timings.get('Asr'),
            "Магриб": timings.get('Maghrib'),
            "Иша": timings.get('Isha')
        }
        
        local_now = get_local_now(tz_str)
        current_time_str = local_now.strftime("%H:%M")
        
        next_prayer_name, next_prayer_time = None, None
        
        for name, p_time in prayers.items():
            if p_time and p_time > current_time_str:
                next_prayer_name = name
                next_prayer_time = p_time
                break
        
        if not next_prayer_name:
            next_prayer_name = "Фаджр [Завтра]"
            next_prayer_time = prayers.get('Fajr')
        
        step_text = (
            f"✨ **Шаг дня ({city})**\n\n"
            f"🎯 **Ближайший намаз:**\n"
            f"• **{next_prayer_name}** в **{next_prayer_time}**\n\n"
            f"📚 *«Поистине, намаз предписан верующим в определенное время»* (Сура Ан-Ниса, 103).\n\n"
            f"🏃‍♂️ *Сильный и здоровый верующий любимее Аллаха, чем слабый. Не забывайте про физическую активность (шаги, спорт)!*\n\n"
            f"Выберите действие ниже:"
        )
    else:
        step_text = f"✨ **Шаг дня**\n\nНе удалось загрузить расписание для региона *{city}*. Проверьте название в настройках."

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отметить намаз выполненным", callback_data="complete_dynamic_step")],
            [InlineKeyboardButton(text="🏃‍♂️ Отметить активность (Спорт/Шаги)", callback_data="complete_health_step")]
        ]
    )
    await message.answer(step_text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "complete_dynamic_step")
async def complete_dynamic_step(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    day_of_year = datetime.now().timetuple().tm_yday
    hadith = HADITHS_365[day_of_year % len(HADITHS_365)]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT streak FROM users WHERE user_id = ?", (user_id,))
    u_row = cursor.fetchone()
    if u_row:
        streak = u_row[0] if u_row[0] is not None else 0
        cursor.execute("UPDATE users SET streak = ? WHERE user_id = ?", (streak + 1, user_id))
        conn.commit()
    conn.close()

    completion_text = (
        f"{callback.message.text}\n\n"
        f"**✅ НАМАЗ ВЫПОЛНЕН! Машааллах, баракаллаху фикум.** 🤍\n\n"
        f"📖 **Хадис дня:**\n{hadith}\n\n"
        f"🎯 *Духовный шаг зачтен. Ваша серия растет!*"
    )
    try:
        await callback.message.edit_text(completion_text, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer("Намаз успешно зачтен!")


@router.callback_query(F.data == "complete_health_step")
async def complete_health_step(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM completed_health WHERE user_id = ? AND date = ?", (user_id, today))
    already_done = cursor.fetchone()

    if not already_done:
        cursor.execute("INSERT INTO completed_health (user_id, date) VALUES (?, ?)", (user_id, today))
        cursor.execute("SELECT health_streak FROM users WHERE user_id = ?", (user_id,))
        h_row = cursor.fetchone()
        h_streak = h_row[0] if h_row and h_row[0] is not None else 0
        cursor.execute("UPDATE users SET health_streak = ? WHERE user_id = ?", (h_streak + 1, user_id))
        conn.commit()
    conn.close()

    msg = (
        f"{callback.message.text}\n\n"
        f"**💪 АКТИВНОСТЬ ЗАСЧИТАНА! Баракаллаху фикум.** ✨\n\n"
        f"🌿 *«Сильный верующий лучше и любимее перед Аллахом, чем верующий слабый, хотя в каждом из них есть благо»* (Муслим).\n\n"
        f"Забота о теле — это проявление благодарности Всевышнему!"
    )
    try:
        await callback.message.edit_text(msg, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer("Активность успешно сохранена!")


# ==================== ЭЛЕКТРОННЫЙ ТАСБИХ (33 / 99 / ♾️) ====================
ZIKRS_LIST = [
    {"name": "Субханаллах", "arabic": "سُبْحَانَ اللَّهِ"},
    {"name": "Альхамдулиллях", "arabic": "الْحَمْدُ لِلَّهِ"},
    {"name": "Аллаху Акбар", "arabic": "اللَّهُ أَكْبَرُ"},
    {"name": "Астагфируллах", "arabic": "أَسْتَغْفِرُ اللَّهَ"}
]

def get_tasbih_keyboard(target_val):
    target_display = str(target_val) if target_val > 0 else "♾️"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ НАЖАТЬ ЗИКР (+1)", callback_data="tasbih_inc")],
            [InlineKeyboardButton(text=f"🎯 Цель: {target_display}", callback_data="tasbih_toggle_target"),
             InlineKeyboardButton(text="🔄 Сброс", callback_data="tasbih_reset")],
            [InlineKeyboardButton(text="🔀 Следующий зикр", callback_data="tasbih_change")],
        ]
    )


@router.message(F.text == "📿 Электронный Тасбих")
async def menu_tasbih(message: types.Message):
    user_id = message.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT current_zikr, tasbih_target FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    current_zikr_name = row[0] if row and row[0] else "Субханаллах"
    target = row[1] if row and row[1] is not None else 33

    active_zikr = next((z for z in ZIKRS_LIST if z["name"] == current_zikr_name), ZIKRS_LIST[0])
    cursor.execute("SELECT count FROM tasbih WHERE user_id = ? AND date = ? AND zikr_name = ?", (user_id, today, active_zikr["name"]))
    t_row = cursor.fetchone()
    count = t_row[0] if t_row else 0
    conn.close()

    target_str = str(target) if target > 0 else "♾️"
    tasbih_text = (
        f"📿 **Электронный Тасбих**\n\n"
        f"✨ **{active_zikr['name']}** ({active_zikr['arabic']})\n\n"
        f"📊 Счёт: **{count} / {target_str}**"
    )
    await message.answer(tasbih_text, reply_markup=get_tasbih_keyboard(target), parse_mode="Markdown")


@router.callback_query(F.data == "tasbih_inc")
async def tasbih_increment(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT current_zikr, tasbih_target FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    current_zikr_name = row[0] if row and row[0] else "Субханаллах"
    target = row[1] if row and row[1] is not None else 33

    active_zikr = next((z for z in ZIKRS_LIST if z["name"] == current_zikr_name), ZIKRS_LIST[0])
    cursor.execute("SELECT count FROM tasbih WHERE user_id = ? AND date = ? AND zikr_name = ?", (user_id, today, active_zikr["name"]))
    t_row = cursor.fetchone()
    current_count = t_row[0] if t_row else 0

    new_count = current_count + 1
    notification_msg = f"+1 ({new_count})"

    if target > 0 and new_count >= target:
        cursor.execute("INSERT OR REPLACE INTO tasbih (user_id, date, zikr_name, count, target) VALUES (?, ?, ?, ?, ?)", (user_id, today, active_zikr["name"], target, target))
        conn.commit()
        count = target
        notification_msg = f"🎉 Цель {target} выполнена!"
    else:
        cursor.execute("INSERT OR REPLACE INTO tasbih (user_id, date, zikr_name, count, target) VALUES (?, ?, ?, ?, ?)", (user_id, today, active_zikr["name"], new_count, target))
        conn.commit()
        count = new_count
    conn.close()

    target_str = str(target) if target > 0 else "♾️"
    updated_text = (
        f"📿 **Электронный Тасбих**\n\n"
        f"✨ **{active_zikr['name']}** ({active_zikr['arabic']})\n\n"
        f"📊 Счёт: **{count} / {target_str}**"
    )
    try:
        await callback.message.edit_text(updated_text, reply_markup=get_tasbih_keyboard(target), parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer(notification_msg)


@router.callback_query(F.data == "tasbih_toggle_target")
async def tasbih_toggle_target(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT tasbih_target, current_zikr FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    current_target = row[0] if row and row[0] is not None else 33
    current_zikr_name = row[1] if row and row[1] else "Субханаллах"

    new_target = 99 if current_target == 33 else (-1 if current_target == 99 else 33)
    cursor.execute("UPDATE users SET tasbih_target = ? WHERE user_id = ?", (new_target, user_id))
    conn.commit()

    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT count FROM tasbih WHERE user_id = ? AND date = ? AND zikr_name = ?", (user_id, today, current_zikr_name))
    t_row = cursor.fetchone()
    count = t_row[0] if t_row else 0
    conn.close()

    active_zikr = next((z for z in ZIKRS_LIST if z["name"] == current_zikr_name), ZIKRS_LIST[0])
    target_str = str(new_target) if new_target > 0 else "♾️"
    updated_text = (
        f"📿 **Электронный Тасбих**\n\n"
        f"✨ **{active_zikr['name']}** ({active_zikr['arabic']})\n\n"
        f"📊 Счёт: **{count} / {target_str}**"
    )
    await callback.message.edit_text(updated_text, reply_markup=get_tasbih_keyboard(new_target), parse_mode="Markdown")
    await callback.answer(f"Цель: {target_str}")


@router.callback_query(F.data == "tasbih_reset")
async def tasbih_reset(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT current_zikr, tasbih_target FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    current_zikr_name = row[0] if row and row[0] else "Субханаллах"
    target = row[1] if row and row[1] is not None else 33
    active_zikr = next((z for z in ZIKRS_LIST if z["name"] == current_zikr_name), ZIKRS_LIST[0])

    cursor.execute("UPDATE tasbih SET count = 0 WHERE user_id = ? AND date = ? AND zikr_name = ?", (user_id, today, active_zikr["name"]))
    conn.commit()
    conn.close()

    target_str = str(target) if target > 0 else "♾️"
    updated_text = (
        f"📿 **Электронный Тасбих**\n\n"
        f"✨ **{active_zikr['name']}** ({active_zikr['arabic']})\n\n"
        f"📊 Счёт: **0 / {target_str}**"
    )
    await callback.message.edit_text(updated_text, reply_markup=get_tasbih_keyboard(target), parse_mode="Markdown")
    await callback.answer("Счетчик обнулен.")


@router.callback_query(F.data == "tasbih_change")
async def tasbih_change(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT current_zikr, tasbih_target FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    current_zikr_name = row[0] if row and row[0] else "Субханаллах"
    target = row[1] if row and row[1] is not None else 33

    current_idx = next((i for i, z in enumerate(ZIKRS_LIST) if z["name"] == current_zikr_name), 0)
    next_zikr = ZIKRS_LIST[(current_idx + 1) % len(ZIKRS_LIST)]

    cursor.execute("UPDATE users SET current_zikr = ? WHERE user_id = ?", (next_zikr["name"], user_id))
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT count FROM tasbih WHERE user_id = ? AND date = ? AND zikr_name = ?", (user_id, today, next_zikr["name"]))
    t_row = cursor.fetchone()
    count = t_row[0] if t_row else 0
    conn.commit()
    conn.close()

    target_str = str(target) if target > 0 else "♾️"
    updated_text = (
        f"📿 **Электронный Тасбих**\n\n"
        f"✨ **{next_zikr['name']}** ({next_zikr['arabic']})\n\n"
        f"📊 Счёт: **{count} / {target_str}**"
    )
    await callback.message.edit_text(updated_text, reply_markup=get_tasbih_keyboard(target), parse_mode="Markdown")
    await callback.answer(f"Зикр: {next_zikr['name']}")


# ==================== ВРЕМЯ НАМАЗА ====================
@router.message(F.text == "⏰ Время намаза")
async def menu_prayer_times(message: types.Message):
    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT city FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    city = row[0] if row and row[0] else "Нерюнгри"
    conn.close()

    res = await get_timings_data(city)
    
    if res:
        timings = res["timings"]
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
        prayer_text = f"Не удалось загрузить расписание для региона *{city}*. Проверьте правильность написания в настройках."

    await message.answer(prayer_text, parse_mode="Markdown")


# ==================== АЗКАРЫ (РАЗДЕЛЬНОЕ МЕНЮ) ====================
@router.message(F.text == "🌅 Утренние и вечерние азкары")
async def menu_adhkar(message: types.Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="☀️ Утренние азкары", callback_data="adhkar_morning")],
            [InlineKeyboardButton(text="🌙 Вечерние азкары", callback_data="adhkar_evening")]
        ]
    )
    await message.answer(
        "🌅 **Утренние и вечерние азкары**\n\nВыберите нужный раздел для чтения защиты и поминания:",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "adhkar_morning")
async def show_morning_adhkar(callback: types.CallbackQuery):
    text = (
        "🌅 **Утренние азкары (Защита и Поминание)**\n\n"
        "• Рекомендовано читать после утреннего намаза (Фаджр).\n\n"
        "🛡 **Основа защиты:**\n"
        "1. Аят аль-Курси (Сура «Аль-Бакара», 255).\n"
        "2. Суры «Аль-Ихляс», «Аль-Фаляк», «Ан-Нас» (по 3 раза).\n"
        "3. *«Аллахумма бика асбахна ва бика амсайна, ва бика нахья ва бика намуту ва иляйка ан-нушур»*\n\n"
        "🕊 Пусть этот день начнется с благословения и защиты Всевышнего."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад к выбору азкаров", callback_data="back_to_adhkar")]]
    )
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data == "adhkar_evening")
async def show_evening_adhkar(callback: types.CallbackQuery):
    text = (
        "🌙 **Вечерние азкары (Защита и Покой)**\n\n"
        "• Рекомендовано читать после закатного намаза (Магриб).\n\n"
        "🛡 **Основа защиты:**\n"
        "1. Аят аль-Курси (Сура «Аль-Бакара», 255).\n"
        "2. Суры «Аль-Ихляс», «Аль-Фаляк», «Ан-Нас» (по 3 раза).\n"
        "3. *«Аллахумма бика амсайна ва бика асбахна, ва бика нахья ва бика намуту ва иляйка аль-масир»*\n\n"
        "🕊 Пусть вечер принесет умиротворение вашему сердцу."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад к выбору азкаров", callback_data="back_to_adhkar")]]
    )
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data == "back_to_adhkar")
async def back_to_adhkar(callback: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="☀️ Утренние азкары", callback_data="adhkar_morning")],
            [InlineKeyboardButton(text="🌙 Вечерние азкары", callback_data="adhkar_evening")]
        ]
    )
    try:
        await callback.message.edit_text(
            "🌅 **Утренние и вечерние азкары**\n\nВыберите нужный раздел для чтения защиты и поминания:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception:
        pass
    await callback.answer()


# ==================== ПРОГРЕСС И НАСТРОЙКИ ====================
@router.message(F.text == "📊 Мой прогресс")
async def menu_progress(message: types.Message):
    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT streak, health_streak FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    streak = row[0] if row and row[0] is not None else 0
    health_streak = row[1] if row and row[1] is not None else 0
    conn.close()

    progress_text = (
        f"📊 **Ваш комплексный прогресс**\n\n"
        f"🔥 Духовная серия (намазы): **{streak} дн.**\n"
        f"💪 Физическая активность (спорт/шаги): **{health_streak} дн.**\n\n"
        f"🏆 Вехи постоянства (40 / 90 / 365 дней): Активны и сохраняются навсегда!"
    )
    await message.answer(progress_text, parse_mode="Markdown")


@router.message(F.text == "⚙️ Настройки и Режимы")
async def menu_settings(message: types.Message):
    user_id = message.from_user.id
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT city, mode FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    city = row[0] if row and row[0] else "Нерюнгри"
    mode = row[1] if row and row[1] else "Аль-Фард (Основа и Обязательство)"

    settings_text = (
        f"⚙️ **Настройки профиля**\n\n"
        f"📍 Город / регион: **{city}**\n"
        f"🎯 Режим поклонения: **{mode}**\n\n"
        f"Выберите нужное действие ниже:"
    )
    
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌍 Изменить город или регион", callback_data="change_city_btn")],
            [InlineKeyboardButton(text="🟢 Аль-Фард", callback_data="set_mode_alfard"),
             InlineKeyboardButton(text="🌙 Аль-Игтихад", callback_data="set_mode_altihad")],
            [InlineKeyboardButton(text="🕊 Ат-Тазкийя", callback_data="set_mode_tazkiyah"),
             InlineKeyboardButton(text="🚀 Аль-Ихсан", callback_data="set_mode_ihsan")]
        ]
    )
    await message.answer(settings_text, reply_markup=keyboard, parse_mode="Markdown")


@router.callback_query(F.data == "change_city_btn")
async def callback_change_city(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🌍 Введите новое название вашего города или региона (например: *Нерюнгри*, *Москва*, *Республика Саха*):", parse_mode="Markdown")
    await state.set_state(OnboardingState.changing_city)
    await callback.answer()


# ==================== ФОНОВЫЙ ПЛАНИРОВЩИК УВЕДОМЛЕНИЙ ====================
async def prayer_notification_loop():
    while True:
        try:
            await asyncio.sleep(60)
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, city FROM users WHERE consent = 1")
            users = cursor.fetchall()
            conn.close()
            
            for user_id, city in users:
                if not city:
                    city = "Нерюнгри"
                
                res = await get_timings_data(city)
                if not res:
                    continue
                
                timings = res["timings"]
                tz_str = res["timezone"]
                local_now = get_local_now(tz_str)
                current_date = local_now.strftime("%Y-%m-%d")
                current_time_str = local_now.strftime("%H:%M")
                
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
                    
                    # 1. За 5 минут до намаза
                    notify_5_dt = p_dt - timedelta(minutes=5)
                    if current_time_str == notify_5_dt.strftime("%H:%M"):
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("SELECT 1 FROM sent_notifications WHERE user_id = ? AND date = ? AND prayer_name = ? AND notif_type = '5_min'", (user_id, current_date, p_name))
                        if not cursor.fetchone():
                            hadith = PRAYER_HADITHS.get(p_name, "«Поминайте Аллаха и стремитесь к благому».")
                            text = (
                                f"⏰ **До намаза {p_name} осталось 5 минут!**\n\n"
                                f"📖 **Хадис о намазе:**\n{hadith}\n\n"
                                f"Подготовьтесь к молитве."
                            )
                            try:
                                await bot.send_message(user_id, text, parse_mode="Markdown")
                                cursor.execute("INSERT INTO sent_notifications (user_id, date, prayer_name, notif_type) VALUES (?, ?, ?, '5_min')", (user_id, current_date, p_name))
                                conn.commit()
                            except Exception as e:
                                logger.error(f"Error sending 5_min: {e}")
                        conn.close()

                    # 2. Догоняющее напоминание через 15 минут
                    catch_up_dt = p_dt + timedelta(minutes=15)
                    if current_time_str == catch_up_dt.strftime("%H:%M"):
                        conn = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute("SELECT 1 FROM completed_prayers WHERE user_id = ? AND date = ? AND prayer_name = ?", (user_id, current_date, p_name))
                        completed = cursor.fetchone()
                        cursor.execute("SELECT 1 FROM sent_notifications WHERE user_id = ? AND date = ? AND prayer_name = ? AND notif_type = 'catch_up'", (user_id, current_date, p_name))
                        sent = cursor.fetchone()

                        if not completed and not sent:
                            text = (
                                f"🌿 **Напоминание о фарзе!**\n\n"
                                f"Время намаза **{p_name}** уже идет. Обязательная молитва — ваша защита и связь со Всевышним. Поторопитесь совершить этот шаг!"
                            )
                            try:
                                await bot.send_message(user_id, text, parse_mode="Markdown")
                                cursor.execute("INSERT INTO sent_notifications (user_id, date, prayer_name, notif_type) VALUES (?, ?, ?, 'catch_up')", (user_id, current_date, p_name))
                                conn.commit()
                            except Exception as e:
                                logger.error(f"Error sending catch_up: {e}")
                        conn.close()

                    # 3. Вечерний итог после Иша (+1 час)
                    if p_name == "Иша":
                        isha_end_dt = p_dt + timedelta(hours=1)
                        if current_time_str == isha_end_dt.strftime("%H:%M"):
                            conn = get_db_connection()
                            cursor = conn.cursor()
                            cursor.execute("SELECT 1 FROM sent_notifications WHERE user_id = ? AND date = ? AND prayer_name = 'Isha_End' AND notif_type = 'evening'", (user_id, current_date))
                            if not cursor.fetchone():
                                evening_text = (
                                    "🌙 **День подошел к концу, и все предписанное выполнено перед Всевышним. Спокойной ночи!** ✨"
                                )
                                try:
                                    await bot.send_message(user_id, evening_text, parse_mode="Markdown")
                                    cursor.execute("INSERT INTO sent_notifications (user_id, date, prayer_name, notif_type) VALUES (?, ?, 'Isha_End', 'evening')", (user_id, current_date))
                                    conn.commit()
                                except Exception as e:
                                    logger.error(f"Error sending evening message: {e}")
                            conn.close()
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
    logger.info("Bot «Амаль 365» fully re-initialized with Timezone support.")
    
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot),
        prayer_notification_loop()
    )


if __name__ == "__main__":
    asyncio.run(main())
