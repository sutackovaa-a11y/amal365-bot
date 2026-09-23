import os
import asyncio
import datetime
import logging
import sqlite3
import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, 
    ReplyKeyboardMarkup, KeyboardButton, 
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
DB_FILE = "bot_database.db"

# ----------------- БАЗА ДАННЫХ -----------------

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
            step_index INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS progress_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date TEXT UNIQUE,
            completed_steps INTEGER,
            total_steps INTEGER
        )
    """)
    # Таблица для тасбиха: хранит текущий зикр, цель и счетчики
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasbih_state (
            user_id INTEGER PRIMARY KEY,
            current_dhikr TEXT DEFAULT 'subhanallah',
            target INTEGER DEFAULT 33
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasbih_data (
            user_id INTEGER,
            dhikr_type TEXT,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, dhikr_type)
        )
    """)
    conn.commit()
    conn.close()

def get_user_profile(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, city, mode, streak, last_completed_date, step_index FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, city, mode, streak, last_completed_date, step_index) VALUES (?, 'Нерюнгри', 'full', 0, NULL, 0)", (user_id,))
        conn.commit()
        row = (user_id, 'Нерюнгри', 'full', 0, None, 0)
    conn.close()
    return {
        "user_id": row[0],
        "city": row[1],
        "mode": row[2],
        "streak": row[3],
        "last_completed_date": row[4],
        "step_index": row[5]
    }

def update_user_profile(user_id: int, **kwargs):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
    values = list(kwargs.values()) + [user_id]
    cursor.execute(f"UPDATE users SET {fields} WHERE user_id = ?", values)
    conn.commit()
    conn.close()

# --- Работа с Тасбихом ---

DHIKR_TITLES = {
    "subhanallah": "Субханаллах (سُبْحَانَ ٱللَّٰهِ)",
    "alhamdulillah": "Альхамдулиллях (ٱلْحَمْدُ لِلَّٰهِ)",
    "allahuakbar": "Аллаху Акбар (ٱللَّٰهُ أَكْبَرُ)",
    "astaghfirullah": "Астагфируллах (أَسْتَغْفِرُ ٱللَّٰهَ)",
    "salawat": "Салават Пророку ﷺ",
    "la_ilaha_illallah": "Ля иляха илля Ллах (لَا إِلَٰهَ إِلَّا ٱللَّٰهُ)"
}

def get_user_tasbih_settings(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT current_dhikr, target FROM tasbih_state WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO tasbih_state (user_id, current_dhikr, target) VALUES (?, 'subhanallah', 33)", (user_id,))
        conn.commit()
        current_dhikr, target = 'subhanallah', 33
    else:
        current_dhikr, target = row
    conn.close()
    return current_dhikr, target

def update_user_tasbih_settings(user_id: int, current_dhikr: str = None, target: int = None):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT current_dhikr, target FROM tasbih_state WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    curr = current_dhikr if current_dhikr is not None else (row[0] if row else 'subhanallah')
    tgt = target if target is not None else (row[1] if row else 33)
    
    cursor.execute("""
        INSERT INTO tasbih_state (user_id, current_dhikr, target)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET current_dhikr = ?, target = ?
    """, (user_id, curr, tgt, curr, tgt))
    conn.commit()
    conn.close()

def get_dhikr_count(user_id: int, dhikr_type: str):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT count FROM tasbih_data WHERE user_id = ? AND dhikr_type = ?", (user_id, dhikr_type))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def update_dhikr_count(user_id: int, dhikr_type: str, count: int):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO tasbih_data (user_id, dhikr_type, count)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, dhikr_type) DO UPDATE SET count = ?
    """, (user_id, dhikr_type, count, count))
    conn.commit()
    conn.close()

# ----------------- ШАГИ ДНЯ -----------------

ALL_STEPS = [
    {
        "id": "tahajjud",
        "title": "🌌 <b>Ночной намаз (Тахаджуд)</b>",
        "hadith": "📖 <b>Хадис:</b> «Лучший намаз после обязательных — это ночной намаз (Тахаджуд)». (Муслим)",
        "modes": ["basic", "spiritual", "full"],
        "hour_start": 1
    },
    {
        "id": "fajr",
        "title": "🌅 <b>Утренний намаз (Фаджр)</b>",
        "hadith": "📖 <b>Хадис:</b> «Тот, кто совершил утренний намаз, находится под защитой Аллаха». (Муслим)",
        "modes": ["minimum", "basic", "spiritual", "full"],
        "hour_start": 4
    },
    {
        "id": "morning_azkar",
        "title": "☀️ <b>Утренние азкары</b>",
        "hadith": "📜 <b>Утренние поминания:</b> Аят аль-Курси, 3 суры защиты, «Бисми-Лляхи ллязи...», «Радыйту би-Лляхи...»",
        "modes": ["spiritual", "full"],
        "hour_start": 6
    },
    {
        "id": "quran",
        "title": "📖 <b>Чтение Священного Корана</b>",
        "hadith": "📖 <b>Хадис:</b> «Читайте Коран, ибо в День воскрешения он придет заступником за тех, кто его читал». (Муслим)",
        "modes": ["spiritual", "full"],
        "hour_start": 8
    },
    {
        "id": "salawat",
        "title": "📿 <b>Салават Пророку Мухаммаду ﷺ</b>",
        "hadith": "📖 <b>Хадис:</b> «Кто призовет на меня благословение один раз, того Аллах благословит за это десять раз». (Муслим)",
        "modes": ["spiritual", "full"],
        "hour_start": 10
    },
    {
        "id": "sport",
        "title": "🏃‍♂️ <b>Спорт, здоровье и активность</b>",
        "hadith": "📖 <b>Хадис:</b> «Сильный верующий лучше и любимее Аллаху, чем слабый верующий...» (Муслим)",
        "modes": ["full"],
        "hour_start": 11
    },
    {
        "id": "dhuhr",
        "title": "🏙 <b>Полуденный намаз (Зухр)</b>",
        "hadith": "📖 <b>Хадис:</b> «Первое, за что будет спрошен раб в День суда — это его намаз». (Тирмизи)",
        "modes": ["minimum", "basic", "spiritual", "full"],
        "hour_start": 12
    },
    {
        "id": "books",
        "title": "📚 <b>Книги и саморазвитие</b>",
        "hadith": "📖 <b>Хадис:</b> «Стремление к знаниям — обязанность каждого мусульманина». (Ибн Маджа)",
        "modes": ["full"],
        "hour_start": 14
    },
    {
        "id": "asr",
        "title": "🌇 <b>Послеполуденный намаз (Аср)</b>",
        "hadith": "📖 <b>Хадис:</b> «Кто упустит намаз Аср, тот словно лишился семьи и своего имущества». (Аль-Бухари)",
        "modes": ["minimum", "basic", "spiritual", "full"],
        "hour_start": 15
    },
    {
        "id": "maghrib",
        "title": "🌆 <b>Вечерний намаз (Магриб)</b>",
        "hadith": "📖 <b>Хадис:</b> «Молитва — это опора религии». (Тирмизи)",
        "modes": ["minimum", "basic", "spiritual", "full"],
        "hour_start": 18
    },
    {
        "id": "isha",
        "title": "🌌 <b>Ночной намаз (Иша)</b>",
        "hadith": "📖 <b>Хадис:</b> «Кто совершит Иша в джамаате, словно молился половину ночи». (Муслим)",
        "modes": ["minimum", "basic", "spiritual", "full"],
        "hour_start": 20
    },
    {
        "id": "evening_azkar",
        "title": "🌙 <b>Вечерние азкары</b>",
        "hadith": "📜 <b>Вечерние поминания:</b> Аят аль-Курси, 3 суры защиты, «А'узу би-калимати-Лляхи...», «Астагфируллах...»",
        "modes": ["spiritual", "full"],
        "hour_start": 21
    },
    {
        "id": "reflection",
        "title": "🤍 <b>Самоанализ и Дуа перед сном</b>",
        "hadith": "✨ <b>Итог дня:</b> Простите всех, кто обидел вас, и спите с чистой душой.",
        "modes": ["minimum", "basic", "spiritual", "full"],
        "hour_start": 22
    }
]

# ----------------- РАСПИСАНИЕ НАМАЗОВ -----------------

KNOWN_CITIES = {
    "нерюнгри": (56.6667, 124.7167),
    "бишкек": (42.8746, 74.5698),
    "якутск": (62.0355, 129.6755),
    "москва": (55.7558, 37.6173)
}

async def get_prayer_data_with_tz(city_name: str):
    city_clean = city_name.strip().lower()
    lat, lng = KNOWN_CITIES.get(city_clean, (None, None))

    async with aiohttp.ClientSession() as session:
        if not lat or not lng:
            try:
                geo_url = f"https://nominatim.openstreetmap.org/search?q={city_name}&format=json&limit=1"
                headers = {"User-Agent": "Amal365GlobalBot/3.0"}
                async with session.get(geo_url, headers=headers) as geo_res:
                    if geo_res.status == 200:
                        geo_json = await geo_res.json()
                        if geo_json:
                            lat = float(geo_json[0]["lat"])
                            lng = float(geo_json[0]["lon"])
            except Exception:
                pass

        url = f"http://api.aladhan.com/v1/timings?latitude={lat}&longitude={lng}&method=3" if lat else f"http://api.aladhan.com/v1/timingsByCity?city={city_name}&country=&method=3"

        async with session.get(url) as response:
            if response.status == 200:
                json_res = await response.json()
                if json_res.get("code") == 200:
                    data = json_res['data']
                    timings = data['timings']
                    
                    fmt = "%H:%M"
                    try:
                        isha_str = timings['Isha'].split()[0]
                        fajr_str = timings['Fajr'].split()[0]
                        isha_dt = datetime.datetime.strptime(isha_str, fmt)
                        fajr_dt = datetime.datetime.strptime(fajr_str, fmt)
                        if fajr_dt <= isha_dt:
                            fajr_dt += datetime.timedelta(days=1)
                        tahajjud_dt = isha_dt + ((fajr_dt - isha_dt) * (2/3))
                        tahajjud_str = tahajjud_dt.strftime("%H:%M")
                    except Exception:
                        tahajjud_str = "02:30"

                    return {
                        "timings": {
                            "Fajr": timings.get("Fajr").split()[0],
                            "Sunrise": timings.get("Sunrise").split()[0],
                            "Dhuhr": timings.get("Dhuhr").split()[0],
                            "Asr": timings.get("Asr").split()[0],
                            "Maghrib": timings.get("Maghrib").split()[0],
                            "Isha": timings.get("Isha").split()[0],
                            "Tahajjud": tahajjud_str
                        }
                    }
    return None

# ----------------- КЛАВИАТУРЫ И МЕНЮ -----------------

class Form(StatesGroup):
    city = State()

def main_keyboard():
    kb = [
        [KeyboardButton(text="✨ Шаг дня"), KeyboardButton(text="📿 Тасбих (Четки)")],
        [KeyboardButton(text="☀️ Утренние и вечерние азкары"), KeyboardButton(text="⏰ Время намаза")],
        [KeyboardButton(text="🏃‍♂️ Спорт"), KeyboardButton(text="📊 Прогресс")],
        [KeyboardButton(text="⚙️ Настройки режима")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

@dp.message(CommandStart())
async def cmd_start(message: Message):
    profile = get_user_profile(message.from_user.id)
    text = (
        "✨ <b>Ассаляму алейкум!</b>\n\n"
        "Добро пожаловать в «Амаль 365» — ваш духовный и интеллектуальный трекер!\n\n"
        f"📍 <b>Город:</b> {profile['city']}\n"
        f"🔥 <b>Серия дней:</b> {profile['streak']} дн."
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_keyboard())

# ----------------- 📿 ЭЛЕКТРОННЫЙ ТАСБИХ (КОМПАКТНЫЙ РЕЖИМ С ЦЕЛЯМИ) -----------------

def get_tasbih_inline_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 НАЖАТЬ ДЛЯ СЧЕТА ➕", callback_data="tasbih_click")],
        [InlineKeyboardButton(text="🔄 Сброс", callback_data="tasbih_reset"), InlineKeyboardButton(text="🎯 Цель", callback_data="tasbih_change_target")],
        [InlineKeyboardButton(text="📖 Выбрать другое поминание", callback_data="tasbih_select_list")]
    ])

@dp.message(F.text == "📿 Тасбих (Четки)")
async def show_tasbih(message: Message):
    current_dhikr, target = get_user_tasbih_settings(message.from_user.id)
    count = get_dhikr_count(message.from_user.id, current_dhikr)
    title = DHIKR_TITLES.get(current_dhikr, current_dhikr)
    
    target_str = str(target) if target > 0 else "∞"

    text = (
        "📿 <b>Электронный Тасбих</b>\n\n"
        f"<b>Текущее поминание:</b>\n✨ {title}\n\n"
        f"📊 Счёт: <b>{count} / {target_str}</b>\n\n"
        "Нажимайте на кнопку ниже, чтобы вести счет:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_tasbih_inline_keyboard())

@dp.callback_query(F.data == "tasbih_click")
async def tasbih_click_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    current_dhikr, target = get_user_tasbih_settings(user_id)
    count = get_dhikr_count(user_id, current_dhikr) + 1
    
    update_dhikr_count(user_id, current_dhikr, count)
    
    title = DHIKR_TITLES.get(current_dhikr, current_dhikr)
    target_str = str(target) if target > 0 else "∞"

    if target > 0 and count == target:
        await callback.answer(f"🎉 МашаАллах! Цель ({target}) выполнена!", show_alert=True)
    else:
        await callback.answer(f"+1 ({count})")

    text = (
        "📿 <b>Электронный Тасбих</b>\n\n"
        f"<b>Текущее поминание:</b>\n✨ {title}\n\n"
        f"📊 Счёт: <b>{count} / {target_str}</b>\n\n"
        "Нажимайте на кнопку ниже, чтобы вести счет:"
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_tasbih_inline_keyboard())
    except Exception:
        pass

@dp.callback_query(F.data == "tasbih_reset")
async def tasbih_reset_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    current_dhikr, target = get_user_tasbih_settings(user_id)
    update_dhikr_count(user_id, current_dhikr, 0)
    
    title = DHIKR_TITLES.get(current_dhikr, current_dhikr)
    target_str = str(target) if target > 0 else "∞"

    text = (
        "📿 <b>Электронный Тасбих</b>\n\n"
        f"<b>Текущее поминание:</b>\n✨ {title}\n\n"
        f"📊 Счёт: <b>0 / {target_str}</b>\n\n"
        "Нажимайте на кнопку ниже, чтобы вести счет:"
    )
    await callback.answer("Счетчик сброшен!")
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_tasbih_inline_keyboard())
    except Exception:
        pass

@dp.callback_query(F.data == "tasbih_change_target")
async def tasbih_change_target_cb(callback: CallbackQuery):
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="33", callback_data="set_target_33"), InlineKeyboardButton(text="99", callback_data="set_target_99"), InlineKeyboardButton(text="100", callback_data="set_target_100")],
        [InlineKeyboardButton(text="∞ (Бесконечно)", callback_data="set_target_0")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_tasbih")]
    ])
    await callback.message.edit_text("🎯 <b>Выберите цель поминания:</b>", parse_mode="HTML", reply_markup=ikb)
    await callback.answer()

@dp.callback_query(F.data.startswith("set_target_"))
async def set_target_value_cb(callback: CallbackQuery):
    target = int(callback.data.replace("set_target_", ""))
    update_user_tasbih_settings(callback.from_user.id, target=target)
    await callback.answer(f"Цель установлена: {target if target > 0 else '∞'}")
    
    # Возвращаемся в главное меню тасбиха
    user_id = callback.from_user.id
    current_dhikr, _ = get_user_tasbih_settings(user_id)
    count = get_dhikr_count(user_id, current_dhikr)
    title = DHIKR_TITLES.get(current_dhikr, current_dhikr)
    target_str = str(target) if target > 0 else "∞"

    text = (
        "📿 <b>Электронный Тасбих</b>\n\n"
        f"<b>Текущее поминание:</b>\n✨ {title}\n\n"
        f"📊 Счёт: <b>{count} / {target_str}</b>\n\n"
        "Нажимайте на кнопку ниже, чтобы вести счет:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_tasbih_inline_keyboard())

@dp.callback_query(F.data == "tasbih_select_list")
async def tasbih_select_list_cb(callback: CallbackQuery):
    ikb = []
    for key, title in DHIKR_TITLES.items():
        ikb.append([InlineKeyboardButton(text=title, callback_data=f"select_dhikr_{key}")])
    ikb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_tasbih")])
    
    await callback.message.edit_text("📖 <b>Выберите поминание из списка:</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=ikb))
    await callback.answer()

@dp.callback_query(F.data.startswith("select_dhikr_"))
async def select_dhikr_cb(callback: CallbackQuery):
    dhikr_key = callback.data.replace("select_dhikr_", "")
    update_user_tasbih_settings(callback.from_user.id, current_dhikr=dhikr_key)
    
    user_id = callback.from_user.id
    _, target = get_user_tasbih_settings(user_id)
    count = get_dhikr_count(user_id, dhikr_key)
    title = DHIKR_TITLES.get(dhikr_key, dhikr_key)
    target_str = str(target) if target > 0 else "∞"

    text = (
        "📿 <b>Электронный Тасбих</b>\n\n"
        f"<b>Текущее поминание:</b>\n✨ {title}\n\n"
        f"📊 Счёт: <b>{count} / {target_str}</b>\n\n"
        "Нажимайте на кнопку ниже, чтобы вести счет:"
    )
    await callback.answer("Поминание выбрано!")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_tasbih_inline_keyboard())

@dp.callback_query(F.data == "back_to_tasbih")
async def back_to_tasbih_cb(callback: CallbackQuery):
    user_id = callback.from_user.id
    current_dhikr, target = get_user_tasbih_settings(user_id)
    count = get_dhikr_count(user_id, current_dhikr)
    title = DHIKR_TITLES.get(current_dhikr, current_dhikr)
    target_str = str(target) if target > 0 else "∞"

    text = (
        "📿 <b>Электронный Тасбих</b>\n\n"
        f"<b>Текущее поминание:</b>\n✨ {title}\n\n"
        f"📊 Счёт: <b>{count} / {target_str}</b>\n\n"
        "Нажимайте на кнопку ниже, чтобы вести счет:"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_tasbih_inline_keyboard())
    await callback.answer()

# ----------------- ШАГ ДНЯ -----------------

def step_inline_keyboard(current_idx: int, total_steps: int):
    nav_buttons = []
    if current_idx > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Пред. шаг", callback_data=f"step_nav_{current_idx - 1}"))
    if current_idx < total_steps - 1:
        nav_buttons.append(InlineKeyboardButton(text="След. шаг ➡️", callback_data=f"step_nav_{current_idx + 1}"))

    ikb = [
        [InlineKeyboardButton(text="✅ Отметить выполненным", callback_data=f"complete_step_{current_idx}")],
        nav_buttons,
        [InlineKeyboardButton(text="⚙️ Настройки режима", callback_data="open_settings")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=[b for b in ikb if b])

@dp.message(F.text == "✨ Шаг дня")
async def show_step_of_day(message: Message):
    profile = get_user_profile(message.from_user.id)
    active_steps = [s for s in ALL_STEPS if profile['mode'] in s['modes']]
    idx = profile['step_index']
    
    step = active_steps[min(idx, len(active_steps) - 1)]

    text = (
        f"📌 <b>Шаг {idx + 1} из {len(active_steps)}</b>\n\n"
        f"{step['title']}\n\n"
        f"{step['hadith']}"
    )

    await message.answer(text, parse_mode="HTML", reply_markup=step_inline_keyboard(idx, len(active_steps)))

@dp.callback_query(F.data.startswith("step_nav_"))
async def step_nav_cb(callback: CallbackQuery):
    new_idx = int(callback.data.replace("step_nav_", ""))
    profile = get_user_profile(callback.from_user.id)
    active_steps = [s for s in ALL_STEPS if profile['mode'] in s['modes']]

    if 0 <= new_idx < len(active_steps):
        update_user_profile(callback.from_user.id, step_index=new_idx)
        step = active_steps[new_idx]
        text = (
            f"📌 <b>Шаг {new_idx + 1} из {len(active_steps)}</b>\n\n"
            f"{step['title']}\n\n"
            f"{step['hadith']}"
        )
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=step_inline_keyboard(new_idx, len(active_steps)))
        except Exception:
            pass
    await callback.answer()

@dp.callback_query(F.data.startswith("complete_step_"))
async def complete_step_callback(callback: CallbackQuery):
    step_idx = int(callback.data.replace("complete_step_", ""))
    profile = get_user_profile(callback.from_user.id)
    active_steps = [s for s in ALL_STEPS if profile['mode'] in s['modes']]

    next_idx = step_idx + 1
    update_user_profile(callback.from_user.id, step_index=next_idx)

    if next_idx >= len(active_steps):
        new_streak = profile['streak'] + 1
        update_user_profile(callback.from_user.id, streak=new_streak, step_index=0)
        await callback.message.answer(
            "🎉 <b>Альхамдулиллах! Все шаги дня успешно выполнены!</b>\n\n"
            f"🔥 Ваша текущая серия: <b>{new_streak} дн.</b>",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )
    else:
        step = active_steps[next_idx]
        text = (
            f"✅ <b>Отлично! Следующий шаг:</b>\n\n"
            f"📌 <b>Шаг {next_idx + 1} из {len(active_steps)}</b>\n\n"
            f"{step['title']}\n\n"
            f"{step['hadith']}"
        )
        await callback.message.answer(text, parse_mode="HTML", reply_markup=step_inline_keyboard(next_idx, len(active_steps)))
    
    await callback.answer("Шаг отмечен!")

# ----------------- ПРОГРЕСС И ОСТАЛЬНЫЕ КОМАНДЫ -----------------

@dp.message(F.text.contains("Прогресс"))
@dp.message(Command("progress"))
async def show_progress(message: Message):
    profile = get_user_profile(message.from_user.id)
    streak = profile['streak']

    p7 = min(100, int((streak / 7) * 100))
    p90 = min(100, int((streak / 90) * 100))
    p365 = min(100, int((streak / 365) * 100))

    text = (
        "📊 <b>Ваш личный прогресс роста</b>\n\n"
        f"🔥 <b>Серия дней подряд:</b> {streak} дн.\n\n"
        f"🎯 <b>Цели:</b>\n"
        f"• 7 дней: {p7}% {'✅' if p7 >= 100 else '⏳'}\n"
        f"• 90 дней: {p90}% {'✅' if p90 >= 100 else '⏳'}\n"
        f"• 365 дней: {p365}% {'✅' if p365 >= 100 else '⏳'}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_keyboard())

@dp.message(F.text == "⏰ Время намаза")
async def show_prayer_times(message: Message):
    profile = get_user_profile(message.from_user.id)
    res = await get_prayer_data_with_tz(profile['city'])
    if not res:
        await message.answer(f"⚠️ Ошибка загрузки времени для города {profile['city']}.")
        return

    data = res["timings"]
    text = (
        f"🕌 <b>Расписание намазов — {profile['city']}</b>\n\n"
        f"🌃 <b>Тахаджуд</b>: ~{data['Tahajjud']}\n"
        f"🌅 <b>Фаджр</b>: {data['Fajr']}\n"
        f"☀️ <b>Восход</b>: {data['Sunrise']}\n"
        f"🏙 <b>Зухр</b>: {data['Dhuhr']}\n"
        f"🌇 <b>Аср</b>: {data['Asr']}\n"
        f"🌆 <b>Магриб</b>: {data['Maghrib']}\n"
        f"🌌 <b>Иша</b>: {data['Isha']}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_keyboard())

@dp.message(F.text == "🏃‍♂️ Спорт")
async def show_sport_direct(message: Message):
    text = (
        "🏃‍♂️ <b>Спорт и физическая активность</b>\n\n"
        "📖 <b>Хадис:</b> «Сильный верующий лучше и любимее Аллаху, чем слабый верующий, хотя в обоих есть благо». (Муслим)\n\n"
        "💪 <b>Рекомендация:</b> 15-20 минут утренней зарядки или 10 000 шагов на свежем воздухе."
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_keyboard())

@dp.message(F.text == "☀️ Утренние и вечерние азкары")
async def show_azkar_direct(message: Message):
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☀️ Утренние азкары", callback_data="view_morning_azkar")],
        [InlineKeyboardButton(text="🌙 Вечерние азкары", callback_data="view_evening_azkar")]
    ])
    await message.answer("🤲 <b>Выберите поминания:</b>", parse_mode="HTML", reply_markup=ikb)

@dp.callback_query(F.data == "view_morning_azkar")
async def view_morning_azkar_cb(callback: CallbackQuery):
    azkar = next(s for s in ALL_STEPS if s['id'] == 'morning_azkar')
    await callback.message.answer(f"{azkar['title']}\n\n{azkar['hadith']}", parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "view_evening_azkar")
async def view_evening_azkar_cb(callback: CallbackQuery):
    azkar = next(s for s in ALL_STEPS if s['id'] == 'evening_azkar')
    await callback.message.answer(f"{azkar['title']}\n\n{azkar['hadith']}", parse_mode="HTML")
    await callback.answer()

@dp.message(F.text == "⚙️ Настройки режима")
async def show_settings(message: Message):
    profile = get_user_profile(message.from_user.id)
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Минимум", callback_data="set_mode_minimum")],
        [InlineKeyboardButton(text="🌙 Базовый", callback_data="set_mode_basic")],
        [InlineKeyboardButton(text="🕊 Душевный рост", callback_data="set_mode_spiritual")],
        [InlineKeyboardButton(text="🚀 Полный рост", callback_data="set_mode_full")],
        [InlineKeyboardButton(text="🌆 Изменить город", callback_data="change_city")]
    ])
    await message.answer(f"⚙️ <b>Настройки</b>\n\n📍 <b>Город:</b> {profile['city']}\n🎯 <b>Режим:</b> {profile['mode']}", parse_mode="HTML", reply_markup=ikb)

@dp.callback_query(F.data == "open_settings")
async def open_settings_cb(callback: CallbackQuery):
    await show_settings(callback.message)
    await callback.answer()

@dp.callback_query(F.data.startswith("set_mode_"))
async def set_mode_cb(callback: CallbackQuery):
    new_mode = callback.data.replace("set_mode_", "")
    update_user_profile(callback.from_user.id, mode=new_mode, step_index=0)
    await callback.answer("Режим обновлен!")
    await show_settings(callback.message)

@dp.callback_query(F.data == "change_city")
async def change_city_cb(callback: CallbackQuery, state: FSMContext):
    await state.set_state(Form.city)
    await callback.message.answer("✍️ <b>Напишите название города:</b>", parse_mode="HTML")
    await callback.answer()

@dp.message(Form.city)
async def process_city_input(message: Message, state: FSMContext):
    new_city = message.text.strip()
    update_user_profile(message.from_user.id, city=new_city)
    await state.clear()
    await message.answer(f"✅ Город изменен на <b>{new_city}</b>!", parse_mode="HTML", reply_markup=main_keyboard())

# ----------------- WEB SERVER ДЛЯ RENDER -----------------

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

async def main():
    init_db()
    await start_web_server()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
