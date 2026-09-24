import os
import asyncio
import datetime
import logging
import sqlite3
import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, 
    ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Логирование
logging.basicConfig(level=logging.INFO)

# Токен бота
BOT_TOKEN = os.getenv("BOT_TOKEN", "8944360971:AAHDP5g0ECefyVgiAW4OikkxUpKlYdOqfPw")
DB_FILE = "amal365_database.db"

# ----------------- БАЗА ДАННЫХ И СТАТИСТИКА -----------------

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            city TEXT DEFAULT 'Нерюнгри',
            mode TEXT DEFAULT 'full',
            streak INTEGER DEFAULT 0,
            last_completed_date TEXT,
            step_index INTEGER DEFAULT 0,
            tasbih_count INTEGER DEFAULT 0,
            tasbih_target INTEGER DEFAULT 33,
            tasbih_dhikr TEXT DEFAULT 'Субханаллах (سُبْحَانَ ٱللَّهِ)'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS progress_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT,
            completed_steps INTEGER,
            total_steps INTEGER,
            UNIQUE(user_id, date)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sent_notifications (
            user_id INTEGER,
            date TEXT,
            prayer TEXT,
            PRIMARY KEY (user_id, date, prayer)
        )
    """)
    conn.commit()
    conn.close()

def get_user_profile(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, city, mode, streak, last_completed_date, step_index, tasbih_count, tasbih_target, tasbih_dhikr FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, city, mode, streak, last_completed_date, step_index, tasbih_count, tasbih_target, tasbih_dhikr) VALUES (?, 'Нерюнгри', 'full', 0, NULL, 0, 0, 33, 'Субханаллах (سُبْحَانَ ٱللَّهِ)')", (user_id,))
        conn.commit()
        row = (user_id, 'Нерюнгри', 'full', 0, None, 0, 0, 33, 'Субханаллах (سُبْحَانَ ٱللَّهِ)')
    conn.close()
    return {
        "user_id": row[0],
        "city": row[1],
        "mode": row[2],
        "streak": row[3],
        "last_completed_date": row[4],
        "step_index": row[5],
        "tasbih_count": row[6],
        "tasbih_target": row[7],
        "tasbih_dhikr": row[8]
    }

def update_user_profile(user_id: int, **kwargs):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
    values = list(kwargs.values()) + [user_id]
    cursor.execute(f"UPDATE users SET {fields} WHERE user_id = ?", values)
    conn.commit()
    conn.close()

def save_daily_history(user_id: int, completed: int, total: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    today_str = str(datetime.date.today())
    cursor.execute("""
        INSERT INTO progress_history (user_id, date, completed_steps, total_steps)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET completed_steps = ?, total_steps = ?
    """, (user_id, today_str, completed, total, completed, total))
    conn.commit()
    conn.close()

def get_user_stats(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM progress_history WHERE user_id = ?", (user_id,))
    total_days = cursor.fetchone()[0]
    conn.close()
    return total_days

def get_global_stats():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT mode, COUNT(*) FROM users GROUP BY mode")
    modes_dist = cursor.fetchall()
    conn.close()
    return total_users, modes_dist

# ----------------- СПИСОК ШАГОВ ПО РЕЖИМАМ -----------------

ALL_STEPS = [
    {
        "id": "tahajjud",
        "title": "🌌 Ночной намаз (Тахаджуд)",
        "hadith": "📖 *Хадис (Муслим):* «Лучший намаз после обязательных — это ночной намаз». Время искреннего дуа, когда Аллах близок к молящимся.",
        "modes": ["basic", "spiritual", "full"]
    },
    {
        "id": "fajr",
        "title": "🌅 Утренний намаз (Фаджр)",
        "hadith": "📖 *Хадис (Муслим):* «Тот, кто совершил утренний намаз, находится под защитой Аллаха». 2 ракаата сунны лучше всего мира.",
        "modes": ["minimum", "basic", "spiritual", "full"]
    },
    {
        "id": "morning_azkar",
        "title": "☀️ Утренние азкары и поминания",
        "hadith": "📜 *Сунна:* Чтение Аят аль-Курси, сур защиты (Ихляс, Фаляк, Нас) и утреннего дуа для защиты и благословения дня.",
        "modes": ["spiritual", "full"]
    },
    {
        "id": "quran",
        "title": "📖 Чтение Священного Корана",
        "hadith": "📖 *Хадис (Муслим):* «Читайте Коран, ибо в День воскрешения он придет заступником за тех, кто его читал».",
        "modes": ["spiritual", "full"]
    },
    {
        "id": "salawat",
        "title": "📿 Салават Пророку Мухаммаду ﷺ",
        "hadith": "📖 *Хадис (Муслим):* «Кто призовет на меня благословение 1 раз, того Аллах благословит за это 10 раз».",
        "modes": ["minimum", "basic", "spiritual", "full"]
    },
    {
        "id": "sport",
        "title": "🏃‍♂️ Физическая активность и здоровье",
        "hadith": "📖 *Хадис (Муслим):* «Сильный верующий лучше и любимее Аллаху, чем слабый верующий».",
        "modes": ["full"]
    },
    {
        "id": "dhuhr",
        "title": "🏙 Полуденный намаз (Зухр)",
        "hadith": "📖 *Хадис (Тирмизи):* «Первое, за что будет спрошен раб в День суда — это его намаз».",
        "modes": ["minimum", "basic", "spiritual", "full"]
    },
    {
        "id": "books",
        "title": "📚 Саморазвитие и книги",
        "hadith": "📖 *Хадис (Ибн Маджа):* «Стремление к знаниям — обязанность каждого мусульманина».",
        "modes": ["full"]
    },
    {
        "id": "asr",
        "title": "🌇 Послеполуденный намаз (Аср)",
        "hadith": "📖 *Хадис (Бухари):* «Кто упустит намаз Аср, тот словно лишился семьи и имущества».",
        "modes": ["minimum", "basic", "spiritual", "full"]
    },
    {
        "id": "maghrib",
        "title": "🌆 Вечерний намаз (Магриб)",
        "hadith": "📖 *Хадис (Тирмизи):* «Молитва — это опора религии». Встречайте вечер с благодарностью.",
        "modes": ["minimum", "basic", "spiritual", "full"]
    },
    {
        "id": "isha",
        "title": "🌌 Ночной намаз (Иша)",
        "hadith": "📖 *Хадис (Муслим):* «Кто совершит Иша в джамаате, словно молился половину ночи».",
        "modes": ["minimum", "basic", "spiritual", "full"]
    },
    {
        "id": "evening_azkar",
        "title": "🌙 Вечерние азкары",
        "hadith": "📜 *Сунна:* Защитные молитвы и вечернее вверение себя под опеку Всевышнего Аллаха.",
        "modes": ["spiritual", "full"]
    },
    {
        "id": "tasbih_step",
        "title": "📿 Ежедневный Зикр и Тасбих",
        "hadith": "📖 *Хадис (Бухари):* «Два слова, легкие на языке, но тяжелые на Весах... Субханаллахи ва бихамдихи, Субханаллахиль-'Азым».",
        "modes": ["minimum", "basic", "spiritual", "full"]
    }
]

# ----------------- РАСЧЕТ ВРЕМЕНИ НАМАЗОВ ДЛЯ ВСЕГО МИРА -----------------

KNOWN_CITIES = {
    "нерюнгри": (56.6667, 124.7167),
    "москва": (55.7558, 37.6173),
    "бишкек": (42.8746, 74.5698),
    "якутск": (62.0355, 129.6755),
    "казань": (55.7887, 49.1221),
    "дубай": (25.2048, 55.2708),
    "стамбул": (41.0082, 28.9784),
    "ташкент": (41.2995, 69.2401)
}

async def get_prayer_data_with_tz(city_name: str):
    city_clean = city_name.strip().lower()
    lat, lng = KNOWN_CITIES.get(city_clean, (None, None))

    async with aiohttp.ClientSession() as session:
        if not lat or not lng:
            try:
                geo_url = f"https://nominatim.openstreetmap.org/search?q={city_name}&format=json&limit=1"
                headers = {"User-Agent": "Amal365Bot/4.0"}
                async with session.get(geo_url, headers=headers) as geo_res:
                    if geo_res.status == 200:
                        geo_json = await geo_res.json()
                        if geo_json:
                            lat = float(geo_json[0]["lat"])
                            lng = float(geo_json[0]["lon"])
            except Exception:
                pass

        if lat and lng:
            url = f"http://api.aladhan.com/v1/timings?latitude={lat}&longitude={lng}&method=3"
        else:
            url = f"http://api.aladhan.com/v1/timingsByCity?city={city_name}&country=&method=3"

        async with session.get(url) as response:
            if response.status == 200:
                json_res = await response.json()
                if json_res.get("code") == 200:
                    data = json_res['data']
                    timings = data['timings']
                    tz_name = data.get('meta', {}).get('timezone', 'UTC')

                    fmt = "%H:%M"
                    try:
                        isha_dt = datetime.datetime.strptime(timings['Isha'], fmt)
                        fajr_dt = datetime.datetime.strptime(timings['Fajr'], fmt)
                        if fajr_dt <= isha_dt:
                            fajr_dt += datetime.timedelta(days=1)
                        night_dur = fajr_dt - isha_dt
                        tahajjud_dt = isha_dt + (night_dur * (2/3))
                        tahajjud_str = tahajjud_dt.strftime("%H:%M")
                    except Exception:
                        tahajjud_str = "02:30"

                    return {
                        "timings": {
                            "Fajr": timings.get("Fajr"),
                            "Sunrise": timings.get("Sunrise"),
                            "Dhuhr": timings.get("Dhuhr"),
                            "Asr": timings.get("Asr"),
                            "Maghrib": timings.get("Maghrib"),
                            "Isha": timings.get("Isha"),
                            "Tahajjud": tahajjud_str
                        },
                        "timezone": tz_name
                    }
    return None

# ----------------- КЛАВИАТУРЫ И СОСТОЯНИЯ -----------------

class Form(StatesGroup):
    city = State()

def main_keyboard():
    kb = [
        [KeyboardButton(text="✨ Шаг дня"), KeyboardButton(text="📿 Электронный Тасбих")],
        [KeyboardButton(text="⏰ Время намаза"), KeyboardButton(text="📊 Мой прогресс (7/90/365)")],
        [KeyboardButton(text="📖 Хадисы и Пятница"), KeyboardButton(text="⚙️ Настройки и Режимы")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

@dp.message(CommandStart())
async def cmd_start(message: Message):
    profile = get_user_profile(message.from_user.id)
    mode_name = {
        "minimum": "🟢 Минимум (5 намазов + Салават + Зикр)",
        "basic": "🌙 Базовый (5 намазов + Тахаджуд)",
        "spiritual": "🕊 Душевный рост (Намазы + Коран + Азкары)",
        "full": "🚀 Полный рост (Самореализация и все практики)"
    }.get(profile['mode'], "Полный рост")

    text = (
        "Ассаляму алейкум! Добро пожаловать в «Амаль 365» — ваш духовный трекер!\n\n"
        "Маленькие регулярные дела любимы Всевышним больше всего.\n\n"
        f"📍 **Город:** {profile['city'].title()}\n"
        f"🎯 **Режим:** {mode_name}\n"
        f"🔥 **Серия дней:** {profile['streak']} дн."
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=main_keyboard())

# ----------------- ЭЛЕКТРОННЫЙ ТАСБИХ -----------------

@dp.message(F.text == "📿 Электронный Тасбих")
async def show_tasbih(message: Message):
    profile = get_user_profile(message.from_user.id)
    count = profile['tasbih_count']
    target = profile['tasbih_target']
    dhikr = profile['tasbih_dhikr']
    target_str = str(target) if target != 999999 else "∞"

    text = (
        "📿 **Электронный Тасбих**\n\n"
        f"Текущее поминание:\n✨ **{dhikr}**\n\n"
        f"📊 Счёт: **{count} / {target_str}**"
    )

    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Нажать (+1)", callback_data="tasbih_inc")],
        [
            InlineKeyboardButton(text="🔄 Сброс", callback_data="tasbih_reset"),
            InlineKeyboardButton(text="🎯 Цель", callback_data="tasbih_target_menu")
        ],
        [InlineKeyboardButton(text="📖 Выбрать зикр", callback_data="tasbih_select")]
    ])
    await message.answer(text, parse_mode="Markdown", reply_markup=ikb)

@dp.callback_query(F.data == "tasbih_inc")
async def tasbih_inc_cb(callback: CallbackQuery):
    profile = get_user_profile(callback.from_user.id)
    count = profile['tasbih_count'] + 1
    target = profile['tasbih_target']
    
    if target != 999999 and count > target:
        count = 1

    dhikr = profile['tasbih_dhikr']
    update_user_profile(callback.from_user.id, tasbih_count=count)
    target_str = str(target) if target != 999999 else "∞"

    text = (
        "📿 **Электронный Тасбих**\n\n"
        f"Текущее поминание:\n✨ **{dhikr}**\n\n"
        f"📊 Счёт: **{count} / {target_str}**"
    )
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Нажать (+1)", callback_data="tasbih_inc")],
        [
            InlineKeyboardButton(text="🔄 Сброс", callback_data="tasbih_reset"),
            InlineKeyboardButton(text="🎯 Цель", callback_data="tasbih_target_menu")
        ],
        [InlineKeyboardButton(text="📖 Выбрать зикр", callback_data="tasbih_select")]
    ])
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=ikb)
    except Exception:
        pass
    await callback.answer(f"+1 ({count}/{target_str})")

@dp.callback_query(F.data == "tasbih_reset")
async def tasbih_reset_cb(callback: CallbackQuery):
    profile = get_user_profile(callback.from_user.id)
    dhikr = profile['tasbih_dhikr']
    target = profile['tasbih_target']
    update_user_profile(callback.from_user.id, tasbih_count=0)
    target_str = str(target) if target != 999999 else "∞"

    text = (
        "📿 **Электронный Тасбих**\n\n"
        f"Текущее поминание:\n✨ **{dhikr}**\n\n"
        f"📊 Счёт: **0 / {target_str}**"
    )
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Нажать (+1)", callback_data="tasbih_inc")],
        [
            InlineKeyboardButton(text="🔄 Сброс", callback_data="tasbih_reset"),
            InlineKeyboardButton(text="🎯 Цель", callback_data="tasbih_target_menu")
        ],
        [InlineKeyboardButton(text="📖 Выбрать зикр", callback_data="tasbih_select")]
    ])
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=ikb)
    except Exception:
        pass
    await callback.answer("Счетчик сброшен!")

@dp.callback_query(F.data == "tasbih_target_menu")
async def tasbih_target_menu_cb(callback: CallbackQuery):
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="33", callback_data="set_target_33"),
         InlineKeyboardButton(text="99", callback_data="set_target_99"),
         InlineKeyboardButton(text="100", callback_data="set_target_100")],
        [InlineKeyboardButton(text="∞ (Бесконечно)", callback_data="set_target_inf")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="tasbih_back")]
    ])
    try:
        await callback.message.edit_text("🎯 Выберите цель для счета:", reply_markup=ikb)
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data.startswith("set_target_"))
async def set_target_cb(callback: CallbackQuery):
    val = callback.data.replace("set_target_", "")
    target = 999999 if val == "inf" else int(val)
    update_user_profile(callback.from_user.id, tasbih_target=target, tasbih_count=0)
    
    profile = get_user_profile(callback.from_user.id)
    dhikr = profile['tasbih_dhikr']
    target_str = str(target) if target != 999999 else "∞"

    text = (
        "📿 **Электронный Тасбих**\n\n"
        f"Текущее поминание:\n✨ **{dhikr}**\n\n"
        f"📊 Счёт: **0 / {target_str}**"
    )
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Нажать (+1)", callback_data="tasbih_inc")],
        [
            InlineKeyboardButton(text="🔄 Сброс", callback_data="tasbih_reset"),
            InlineKeyboardButton(text="🎯 Цель", callback_data="tasbih_target_menu")
        ],
        [InlineKeyboardButton(text="📖 Выбрать зикр", callback_data="tasbih_select")]
    ])
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=ikb)
    except Exception:
        pass
    await callback.answer("Цель обновлена!")

@dp.callback_query(F.data == "tasbih_select")
async def tasbih_select_cb(callback: CallbackQuery):
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Субханаллах", callback_data="set_dhikr_Subhanallah")],
        [InlineKeyboardButton(text="Альхамдулиллах", callback_data="set_dhikr_Alhamdulillah")],
        [InlineKeyboardButton(text="Аллаху Акбар", callback_data="set_dhikr_AllahuAkbar")],
        [InlineKeyboardButton(text="Астагфируллах", callback_data="set_dhikr_Astaghfirullah")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="tasbih_back")]
    ])
    try:
        await callback.message.edit_text("Выберите поминание (зикр):", reply_markup=ikb)
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data == "tasbih_back")
async def tasbih_back_cb(callback: CallbackQuery):
    profile = get_user_profile(callback.from_user.id)
    count = profile['tasbih_count']
    target = profile['tasbih_target']
    dhikr = profile['tasbih_dhikr']
    target_str = str(target) if target != 999999 else "∞"

    text = (
        "📿 **Электронный Тасбих**\n\n"
        f"Текущее поминание:\n✨ **{dhikr}**\n\n"
        f"📊 Счёт: **{count} / {target_str}**"
    )
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Нажать (+1)", callback_data="tasbih_inc")],
        [
            InlineKeyboardButton(text="🔄 Сброс", callback_data="tasbih_reset"),
            InlineKeyboardButton(text="🎯 Цель", callback_data="tasbih_target_menu")
        ],
        [InlineKeyboardButton(text="📖 Выбрать зикр", callback_data="tasbih_select")]
    ])
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=ikb)
    except Exception:
        pass
    await callback.answer()

@dp.callback_query(F.data.startswith("set_dhikr_"))
async def set_dhikr_cb(callback: CallbackQuery):
    dhikr_key = callback.data.replace("set_dhikr_", "")
    dhikr_dict = {
        "Subhanallah": "Субханаллах (سُبْحَانَ ٱللَّهِ)",
        "Alhamdulillah": "Альхамдулиллах (ٱلْحَمْدُ لِلَّهِ)",
        "AllahuAkbar": "Аллаху Акбар (ٱللَّهُ أَكْبَرُ)",
        "Astaghfirullah": "Астагфируллах (أَسْتَغْفِرُ ٱللََّهَ)"
    }
    new_dhikr = dhikr_dict.get(dhikr_key, "Субханаллах (سُبْحَانَ ٱللَّهِ)")
    profile = get_user_profile(callback.from_user.id)
    target = profile['tasbih_target']
    update_user_profile(callback.from_user.id, tasbih_dhikr=new_dhikr, tasbih_count=0)
    target_str = str(target) if target != 999999 else "∞"

    text = (
        "📿 **Электронный Тасбих**\n\n"
        f"Текущее поминание:\n✨ **{new_dhikr}**\n\n"
        f"📊 Счёт: **0 / {target_str}**"
    )
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Нажать (+1)", callback_data="tasbih_inc")],
        [
            InlineKeyboardButton(text="🔄 Сброс", callback_data="tasbih_reset"),
            InlineKeyboardButton(text="🎯 Цель", callback_data="tasbih_target_menu")
        ],
        [InlineKeyboardButton(text="📖 Выбрать зикр", callback_data="tasbih_select")]
    ])
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=ikb)
    except Exception:
        pass
    await callback.answer("Зикр изменен!")

# ----------------- ВРЕМЯ НАМАЗА -----------------

@dp.message(F.text == "⏰ Время намаза")
async def show_prayer_times(message: Message):
    profile = get_user_profile(message.from_user.id)
    city = profile['city']
    res = await get_prayer_data_with_tz(city)

    if not res:
        await message.answer(f"⚠️ Не удалось загрузить время для города **{city.title()}**. Укажите город в настройках.", parse_mode="Markdown")
        return

    data = res["timings"]
    text = (
        f"🕌 **Расписание намазов — {city.title()}**\n\n"
        f"🌃 **Тахаджуд**: ~{data['Tahajjud']}\n"
        f"🌅 **Фаджр**: {data['Fajr']}\n"
        f"☀️ **Восход**: {data['Sunrise']}\n"
        f"🏙 **Зухр**: {data['Dhuhr']}\n"
        f"🌇 **Аср**: {data['Asr']}\n"
        f"🌆 **Магриб**: {data['Maghrib']}\n"
        f"🌌 **Иша**: {data['Isha']}\n\n"
        f"🔔 *Напоминание:* Бот пришлет уведомление за 5 минут до каждого намаза!"
    )
    await message.answer(text, parse_mode="Markdown")

# ----------------- ШАГИ ДНЯ (ЦЕПОЧКА В ЧАТЕ) -----------------

@dp.message(F.text == "✨ Шаг дня")
async def show_step_of_day(message: Message):
    await render_step_initial(message)

async def render_step_initial(message: Message):
    user_id = message.from_user.id
    profile = get_user_profile(user_id)
    user_mode = profile['mode']
    active_steps = [s for s in ALL_STEPS if user_mode in s['modes']]
    idx = profile['step_index']

    if idx >= len(active_steps):
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Начать новый день", callback_data="reset_steps")]
        ])
        await message.answer("🎉 **МашаАллах! Вы выполнили все шаги на сегодня!**\nПусть Всевышний примет ваше поклонение.", parse_mode="Markdown", reply_markup=ikb)
        return

    step = active_steps[idx]
    text = (
        f"📌 **Шаг {idx + 1} из {len(active_steps)}**\n\n"
        f"**{step['title']}**\n\n"
        f"{step['hadith']}"
    )

    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить выполненным", callback_data="complete_step")]
    ])
    await message.answer(text, parse_mode="Markdown", reply_markup=ikb)

@dp.callback_query(F.data == "complete_step")
async def complete_step_callback(callback: CallbackQuery):
    user_id = callback.from_user.id
    profile = get_user_profile(user_id)
    user_mode = profile['mode']
    active_steps = [s for s in ALL_STEPS if user_mode in s['modes']]
    idx = profile['step_index']

    # 1. Редактируем текущее сообщение: убираем кнопки и пишем ✅ ВЫПОЛНЕНО
    try:
        old_text = callback.message.text or callback.message.caption or ""
        await callback.message.edit_text(
            f"{old_text}\n\n**✅ ВЫПОЛНЕНО**",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    new_index = idx + 1
    update_user_profile(user_id, step_index=new_index)

    if new_index >= len(active_steps):
        new_streak = profile['streak'] + 1
        today_str = str(datetime.date.today())
        update_user_profile(user_id, streak=new_streak, last_completed_date=today_str)
        save_daily_history(user_id, len(active_steps), len(active_steps))

        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Начать новый день", callback_data="reset_steps")]
        ])
        await callback.message.answer(
            "🎉 **Альхамдулиллах! Все шаги дня успешно завершены!**\n\n"
            f"🔥 Ваша непрерывная серия: **{new_streak} дн.**",
            parse_mode="Markdown",
            reply_markup=ikb
        )
    else:
        # 2. Присылаем следующий шаг новым сообщением (цепочка сохраняется в чате)
        step = active_steps[new_index]
        text = (
            f"📌 **Шаг {new_index + 1} из {len(active_steps)}**\n\n"
            f"**{step['title']}**\n\n"
            f"{step['hadith']}"
        )
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отметить выполненным", callback_data="complete_step")]
        ])
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=ikb)

    await callback.answer("Шаг выполнен! ✅")

@dp.callback_query(F.data == "reset_steps")
async def reset_steps_callback(callback: CallbackQuery):
    update_user_profile(callback.from_user.id, step_index=0)
    await callback.answer("Новый день начат!")
    await callback.message.answer("🔄 **Новый день начат с блага!** Нажмите «✨ Шаг дня», чтобы продолжить.", parse_mode="Markdown")

# ----------------- ПРОГРЕСС И СТАТИСТИКА -----------------

@dp.message(F.text == "📊 Мой прогресс (7/90/365)")
async def show_progress(message: Message):
    profile = get_user_profile(message.from_user.id)
    total_completed_days = get_user_stats(message.from_user.id)
    streak = profile['streak']
    total_users, modes_dist = get_global_stats()

    p7 = min(100, int((streak / 7) * 100))
    p90 = min(100, int((streak / 90) * 100))
    p365 = min(100, int((streak / 365) * 100))

    modes_text = "\n".join([f"• Режим `{m}`: выбор {c} польз." for m, c in modes_dist])

    text = (
        "📊 **Ваш прогресс и статистика**\n\n"
        f"🔥 **Текущая серия:** {streak} дн.\n"
        f"📅 **Успешных дней всего:** {total_completed_days} дн.\n\n"
        f"🎯 **Цели и марафоны:**\n"
        f"• **7 дней (1 неделя):** {p7}% {'✅' if p7 >= 100 else '⏳'}\n"
        f"• **90 дней (Трансформация):** {p90}% {'✅' if p90 >= 100 else '⏳'}\n"
        f"• **365 дней (Год роста):** {p365}% {'✅' if p365 >= 100 else '⏳'}\n\n"
        f"👥 **Статистика базы данных:**\n"
        f"• Всего пользователей: {total_users}\n"
        f"{modes_text}"
    )
    await message.answer(text, parse_mode="Markdown")

# ----------------- ХАДИСЫ И НАСТРОЙКИ -----------------

@dp.message(F.text == "📖 Хадисы и Пятница")
async def show_hadiths_and_friday(message: Message):
    text = (
        "📖 **Достоверные хадисы:**\n\n"
        "1️⃣ «Поистине, дела оцениваются по намерениям» (Бухари, Муслим).\n"
        "2️⃣ «Лучший из вас тот, кто изучил Коран и обучил ему других» (Бухари).\n\n"
        "🕌 **Пятничные Сунны (Джума):**\n"
        "• Полное омовение (гусль) и чистая одежда\n"
        "• Чтение суры «Аль-Кахф»\n"
        "• Многократный салават Пророку ﷺ"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(F.text == "⚙️ Настройки и Режимы")
async def show_settings(message: Message):
    profile = get_user_profile(message.from_user.id)
    
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Минимум (5 намазов + Салават + Зикр)", callback_data="set_mode_minimum")],
        [InlineKeyboardButton(text="🌙 Базовый (5 намазов + Тахаджуд)", callback_data="set_mode_basic")],
        [InlineKeyboardButton(text="🕊 Душевный рост (Намазы + Коран + Азкары)", callback_data="set_mode_spiritual")],
        [InlineKeyboardButton(text="🚀 Полный рост (Самореализация)", callback_data="set_mode_full")],
        [InlineKeyboardButton(text="🌆 Изменить город мира", callback_data="change_city")]
    ])

    await message.answer(
        f"⚙️ **Настройки профиля**\n\n"
        f"📍 **Текущий город:** {profile['city'].title()}\n"
        f"🎯 **Текущий режим:** `{profile['mode']}`\n\n"
        f"Выберите желаемый режим ниже:",
        parse_mode="Markdown",
        reply_markup=ikb
    )

@dp.callback_query(F.data == "open_settings")
async def open_settings_cb(callback: CallbackQuery):
    await show_settings(callback.message)
    await callback.answer()

@dp.callback_query(F.data.startswith("set_mode_"))
async def set_mode_cb(callback: CallbackQuery):
    new_mode = callback.data.replace("set_mode_", "")
    update_user_profile(callback.from_user.id, mode=new_mode, step_index=0)
    await callback.answer("Режим успешно обновлен!")
    await show_settings(callback.message)

@dp.callback_query(F.data == "change_city")
async def change_city_cb(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.city)
    await callback.message.answer(
        "✍️ **Введите название любого города или региона мира** (например: `Нерюнгри`, `Москва`, `Бишкек`, `Dubai`, `Istanbul`):",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(Form.city)
async def process_city_input(message: Message, state: FSMContext):
    new_city = message.text.strip().replace("*", "")
    update_user_profile(message.from_user.id, city=new_city)
    await state.clear()
    await message.answer(
        f"✅ Город успешно изменен на **{new_city.title()}**!\nРасписание намазов обновлено.",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

# ----------------- ФОНОВЫЕ PUSH-УВЕДОМЛЕНИЯ ЗА 5 МИНУТ -----------------

async def prayer_notification_loop():
    while True:
        try:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, city FROM users")
            users = cursor.fetchall()
            conn.close()

            city_map = {}
            for u_id, city in users:
                city_map.setdefault(city, []).append(u_id)

            for city, u_ids in city_map.items():
                res = await get_prayer_data_with_tz(city)
                if not res:
                    continue

                timings = res["timings"]
                tz_name = res["timezone"]

                try:
                    import zoneinfo
                    tz = zoneinfo.ZoneInfo(tz_name)
                except Exception:
                    tz = datetime.timezone.utc

                now_city = datetime.datetime.now(tz)
                target_time = (now_city + datetime.timedelta(minutes=5)).strftime("%H:%M")
                today_str = now_city.strftime("%Y-%m-%d")

                prayer_labels = {
                    "Fajr": "Фаджра",
                    "Dhuhr": "Зухра",
                    "Asr": "Асра",
                    "Maghrib": "Магриба",
                    "Isha": "Иша"
                }

                for p_key, p_name in prayer_labels.items():
                    p_time = timings.get(p_key)
                    if p_time and p_time == target_time:
                        for u_id in u_ids:
                            conn = sqlite3.connect(DB_FILE)
                            c = conn.cursor()
                            c.execute("SELECT 1 FROM sent_notifications WHERE user_id = ? AND date = ? AND prayer = ?", (u_id, today_str, p_key))
                            already_sent = c.fetchone()
                            if not already_sent:
                                c.execute("INSERT INTO sent_notifications (user_id, date, prayer) VALUES (?, ?, ?)", (u_id, today_str, p_key))
                                conn.commit()
                                conn.close()
                                try:
                                    msg = f"🔔 До наступления намаза {p_name} осталось 5 минут! Время совершить омовение и идти навстречу к Аллаху."
                                    await bot.send_message(u_id, msg, parse_mode="Markdown")
                                except Exception as err:
                                    logging.error(f"Failed to send PUSH to {u_id}: {err}")
                            else:
                                conn.close()
        except Exception as e:
            logging.error(f"Error in notification loop: {e}")

        await asyncio.sleep(40)

# ----------------- WEB SERVER ДЛЯ ХОСТИНГА (RENDER) -----------------

async def handle_ping(request):
    return web.Response(text="Amal365 Bot Active!", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    app.router.add_get('/health', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Web server active on port {port}")

async def main():
    init_db()
    await start_web_server()
    asyncio.create_task(prayer_notification_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
