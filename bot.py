import os
import logging
import sqlite3
import asyncio
from datetime import datetime, timedelta
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from aiogram.exceptions import TelegramBadRequest

DB_NAME = "amal365.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            country TEXT DEFAULT 'Россия',
            city TEXT DEFAULT 'Нерюнгри',
            latitude REAL DEFAULT 56.6644,
            longitude REAL DEFAULT 124.7042,
            rhythm TEXT DEFAULT 'Аль-Фард',
            mode TEXT DEFAULT 'active',
            onboarding_completed INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_progress (
            user_id INTEGER,
            date TEXT,
            quran TEXT DEFAULT '',
            books INTEGER DEFAULT 0,
            steps INTEGER DEFAULT 0,
            sport INTEGER DEFAULT 0,
            tasbih INTEGER DEFAULT 0,
            salawat INTEGER DEFAULT 0,
            morning_adhkar INTEGER DEFAULT 0,
            evening_adhkar INTEGER DEFAULT 0,
            fajr_done INTEGER DEFAULT 0,
            dhuhr_done INTEGER DEFAULT 0,
            asr_done INTEGER DEFAULT 0,
            maghrib_done INTEGER DEFAULT 0,
            isha_done INTEGER DEFAULT 0,
            tahajjud_done INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, date)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notification_log (
            user_id INTEGER,
            date TEXT,
            prayer_key TEXT,
            notification_type TEXT,
            PRIMARY KEY (user_id, date, prayer_key, notification_type)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS local_schedules (
            city TEXT,
            date TEXT,
            fajr TEXT,
            sunrise TEXT,
            dhuhr TEXT,
            asr TEXT,
            maghrib TEXT,
            isha TEXT,
            PRIMARY KEY (city, date)
        )
    ''')
    conn.commit()
    conn.close()

def get_local_now():
    return datetime.utcnow() + timedelta(hours=9)

def get_today_str():
    return get_local_now().strftime("%Y-%m-%d")

def ensure_daily_record(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    today = get_today_str()
    cursor.execute("SELECT user_id FROM daily_progress WHERE user_id = ? AND date = ?", (user_id, today))
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO daily_progress (user_id, date, quran, books, steps, sport, tasbih, salawat, morning_adhkar, evening_adhkar, fajr_done, dhuhr_done, asr_done, maghrib_done, isha_done, tahajjud_done)
            VALUES (?, ?, '', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        """, (user_id, today))
        conn.commit()
    conn.close()

async def get_prayer_times(city, lat, lon, date_str):
    # 1. Проверяем локальную базу данных (для Якутска, Нерюнгри и т.д. по стандартам мечети / 1Muslim)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT fajr, sunrise, dhuhr, asr, maghrib, isha FROM local_schedules WHERE city = ? AND date = ?", (city, date_str))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "Тахаджуд": "03:30",
            "Фаджр": row[0],
            "Восход солнца": row[1],
            "Зухр": row[2],
            "Аср": row[3],
            "Магриб": row[4],
            "Иша": row[5]
        }
        
    # 2. Для остальных регионов (РФ, КР, КЗ, УЗ) используем API Aladhan (method=3 Мусульманская лига мира)
    url = f"https://api.aladhan.com/v1/timings/{date_str}?latitude={lat}&longitude={lon}&method=3"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    timings = data['data']['timings']
                    return {
                        "Тахаджуд": "03:30",
                        "Фаджр": timings.get("Fajr", "05:00")[:5],
                        "Восход солнца": timings.get("Sunrise", "06:30")[:5],
                        "Зухр": timings.get("Dhuhr", "12:30")[:5],
                        "Аср": timings.get("Asr", "15:30")[:5],
                        "Магриб": timings.get("Maghrib", "18:00")[:5],
                        "Иша": timings.get("Isha", "19:30")[:5],
                    }
        except Exception as e:
            logging.error(f"Error fetching prayer times: {e}")
            
    return {
        "Тахаджуд": "03:30",
        "Фаджр": "05:03", "Восход солнца": "06:54", "Зухр": "12:30",
        "Аср": "15:19", "Магриб": "18:04", "Иша": "19:48"
    }

async def get_coordinates_by_city(city_name):
    url = f"https://nominatim.openstreetmap.org/search?q={city_name}&format=json&limit=1"
    headers = {'User-Agent': 'Amal365Bot/1.0'}
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    if data:
                        return float(data[0]['lat']), float(data[0]['lon'])
        except Exception as e:
            logging.error(f"Geocoding error: {e}")
    return 56.6644, 124.7042

class OnboardForm(StatesGroup):
    entering_city = State()

class ActivityForm(StatesGroup):
    entering_quran = State()
    entering_books = State()
    entering_steps = State()
    entering_sport = State()
    updating_city = State()

router = Router()

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏰ Время намазов"), KeyboardButton(text="📿 Поминания и дуа")],
            [KeyboardButton(text="📊 Мой путь"), KeyboardButton(text="⚙️ Актуальный режим")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )

# === ОНБОРДИНГ И СТАРТ ===
@router.message(F.text == "/start")
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT onboarding_completed FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row and row[0] == 1:
        await message.answer("🤍 **С возвращением в Amal365!**\nВаш духовный ритм бережно поддерживается.", reply_markup=get_main_keyboard(), parse_mode="Markdown")
        return

    text = (
        "Ассаляму алейкум ва рахматуллахи ва баракатух 🌙\n\n"
        "Добро пожаловать в **Amal365** — ваше пространство постоянства в благих делах и душевного тепла.\n\n"
        "Мы бережно храним ваши шаги на этом пути. Пусть Всевышний дарует благословение в каждом вашем начинании 🤍"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Начать с Бисмиллах", callback_data="onboard_bismillah")],
        [InlineKeyboardButton(text="❌ Выйти", callback_data="onboard_exit")]
    ])
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")

@router.callback_query(F.data == "onboard_exit")
async def onboard_exit(callback: types.CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Начать с Бисмиллах", callback_data="onboard_bismillah")]
    ])
    try:
        await callback.message.edit_text("Двери Amal365 всегда открыты для вас. Всего доброго! 🤍", reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data == "onboard_bismillah")
async def onboard_bismillah(callback: types.CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Россия", callback_data="country_Россия"), InlineKeyboardButton(text="🇰🇬 Кыргызстан", callback_data="country_Кыргызстан")],
        [InlineKeyboardButton(text="🇰🇿 Казахстан", callback_data="country_Казахстан"), InlineKeyboardButton(text="🇺🇿 Узбекистан", callback_data="country_Узбекистан")]
    ])
    try:
        await callback.message.edit_text("🌍 **Выбор региона**\n\nПожалуйста, выберите вашу страну:", reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("country_"))
async def select_country(callback: types.CallbackQuery, state: FSMContext):
    country = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO users (user_id, country) VALUES (?, ?)", (user_id, country))
    conn.commit()
    conn.close()
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="onboard_bismillah")]
    ])
    try:
        await callback.message.edit_text(
            f"🏙 **Укажите ваш населенный пункт**\n\nВы выбрали: **{country}**.\n\nНапишите название вашего города или области на кириллице (например: *Нерюнгри, Якутск, Москва, Бишкек*):",
            reply_markup=markup, parse_mode="Markdown"
        )
    except TelegramBadRequest:
        pass
    await state.set_state(OnboardForm.entering_city)
    await callback.answer()

@router.message(OnboardForm.entering_city)
async def save_onboard_city(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    city_name = message.text.strip()
    lat, lon = await get_coordinates_by_city(city_name)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET city = ?, latitude = ?, longitude = ? WHERE user_id = ?", (city_name, lat, lon, user_id))
    conn.commit()
    conn.close()
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Аль-Фард", callback_data="rhythm_Аль-Фард")],
        [InlineKeyboardButton(text="🌿 Аль-Истикама", callback_data="rhythm_Аль-Истикама")],
        [InlineKeyboardButton(text="📖 Ат-Тазкия", callback_data="rhythm_Ат-Тазкия")],
        [InlineKeyboardButton(text="⭐ Аль-Ихсан", callback_data="rhythm_Аль-Ихсан")]
    ])
    await state.clear()
    await message.answer(
        f"✅ Город **{city_name}** успешно сохранен!\n\n"
        "✨ **Выберите ваш духовный ритм сопровождения:**\n\n"
        "• **Аль-Фард** — Фундамент веры: 5 обязательных молитв, азкары, тасбих/салават и Тахаджуд по желанию.\n"
        "• **Аль-Истикама** — Постоянство: фундамент + чтение и слушание Корана по зову сердца.\n"
        "• **Ат-Тазкия** — Очищение и знание: фундамент + полезное чтение книг и духовное развитие.\n"
        "• **Аль-Ихсан** — Вершина искренности: гармония обязательного и добровольного поклонения, Коран, книги и благородные дела.",
        reply_markup=markup, parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("rhythm_"))
async def select_rhythm(callback: types.CallbackQuery):
    rhythm = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET rhythm = ?, onboarding_completed = 1 WHERE user_id = ?", (rhythm, user_id))
    conn.commit()
    conn.close()
    
    text = (
        f"🤍 **Альхамдулиллах, намерение оформлено.**\n\n"
        f"Ритм **«{rhythm}»** бережно настроен для вас.\n"
        "Пусть этот путь принесет в ваше сердце свет, умиротворение и сакину."
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.message.answer("Главное меню активировано:", reply_markup=get_main_keyboard())
    await callback.answer()

# === ВРЕМЯ НАМАЗОВ И ОБРАТНЫЙ ОТСЧЕТ ===
@router.message(F.text == "⏰ Время намазов")
async def cmd_prayer_times(message: types.Message):
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT city, latitude, longitude FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    city = row[0] if row else "Нерюнгри"
    lat = row[1] if row and row[1] else 56.6644
    lon = row[2] if row and row[2] else 124.7042
    
    today = get_today_str()
    times = await get_prayer_times(city, lat, lon, today)
    
    now = get_local_now()
    current_time_minutes = now.hour * 60 + now.minute
    
    prayers_list = [
        ("Тахаджуд", times["Тахаджуд"]),
        ("Фаджр", times["Фаджр"]),
        ("Восход солнца", times["Восход солнца"]),
        ("Зухр", times["Зухр"]),
        ("Аср", times["Аср"]),
        ("Магриб", times["Магриб"]),
        ("Иша", times["Иша"])
    ]
    
    next_prayer_name = None
    time_diff_str = ""
    
    for p_name, p_time in prayers_list:
        p_h, p_m = map(int, p_time.split(":"))
        p_total_minutes = p_h * 60 + p_m
        if p_total_minutes > current_time_minutes:
            next_prayer_name = p_name
            diff = p_total_minutes - current_time_minutes
            hours = diff // 60
            mins = diff % 60
            time_diff_str = f"До намаза **{p_name}** осталось {f'{hours} ч. ' if hours else ''}{mins} мин."
            break
            
    if not next_prayer_name:
        next_prayer_name = "Фаджр (завтра)"
        time_diff_str = "Наступило ночное время. Пусть ваш отдых будет благословенным."

    text = (
        f"🕌 **Расписание намазов для г. {city}**\n"
        f"📅 На сегодня ({today})\n\n"
        f"• Тахаджуд: {times['Тахаджуд']}\n"
        f"• Фаджр: {times['Фаджр']}\n"
        f"• Восход солнца: {times['Восход солнца']}\n"
        f"• Зухр: {times['Зухр']}\n"
        f"• Аср: {times['Аср']}\n"
        f"• Магриб: {times['Магриб']}\n"
        f"• Иша: {times['Иша']}\n\n"
        f"⏱ *{time_diff_str}*\n\n"
        "«Воистину, намаз предписан верующим в определенное время» (сура Ан-Ниса, 103)."
    )
    await message.answer(text, parse_mode="Markdown")

# === ОТМЕТКА НАМАЗА ИЗ УВЕДОМЛЕНИЙ ===
@router.callback_query(F.data.startswith("toggle_p_"))
async def toggle_prayer(callback: types.CallbackQuery):
    p_name = callback.data.split("_")[2]
    user_id = callback.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    
    col_map = {"fajr": "fajr_done", "dhuhr": "dhuhr_done", "asr": "asr_done", "maghrib": "maghrib_done", "isha": "isha_done"}
    col = col_map.get(p_name)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f"SELECT {col} FROM daily_progress WHERE user_id = ? AND date = ?", (user_id, today))
    val = cursor.fetchone()[0]
    new_val = 0 if val else 1
    cursor.execute(f"UPDATE daily_progress SET {col} = ? WHERE user_id = ? AND date = ?", (new_val, user_id, today))
    conn.commit()
    conn.close()
    
    if new_val == 1:
        await callback.answer("Альхамдулиллах! Намаз зафиксирован 🤍", show_alert=True)
    else:
        await callback.answer("Статус намаза обновлен! 🤍")

# === ПОМИНАНИЯ И ДУА ===
@router.message(F.text == "📿 Поминания и дуа")
async def cmd_duas(message: types.Message):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Тасбих", callback_data="tasbih_inc")],
        [InlineKeyboardButton(text="🌹 Салават", callback_data="salawat_inc")],
        [InlineKeyboardButton(text="☀️ Утренние азкары", callback_data="morning_adhkar_full")],
        [InlineKeyboardButton(text="🌙 Вечерние азкары", callback_data="evening_adhkar_full")]
    ])
    await message.answer("📿 **Поминания и дуа**\n\nВыберите нужный раздел для духовного наполнения:", reply_markup=markup, parse_mode="Markdown")

@router.callback_query(F.data == "back_to_duas")
async def back_to_duas(callback: types.CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Тасбих", callback_data="tasbih_inc")],
        [InlineKeyboardButton(text="🌹 Салават", callback_data="salawat_inc")],
        [InlineKeyboardButton(text="☀️ Утренние азкары", callback_data="morning_adhkar_full")],
        [InlineKeyboardButton(text="🌙 Вечерние азкары", callback_data="evening_adhkar_full")]
    ])
    try:
        await callback.message.edit_text("📿 **Поминания и дуа**\n\nВыберите нужный раздел:", reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("tasbih_"))
async def process_tasbih(callback: types.CallbackQuery):
    action = callback.data.split("_")[1]
    user_id = callback.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT tasbih FROM daily_progress WHERE user_id = ? AND date = ?", (user_id, today))
    row = cursor.fetchone()
    count = row[0] if row else 0
    if action == "inc": count += 1
    elif action == "reset": count = 0
    cursor.execute("UPDATE daily_progress SET tasbih = ? WHERE user_id = ? AND date = ?", (count, user_id, today))
    conn.commit()
    conn.close()
    
    text = f"📿 **Тасбих**\n\nТекущий счет: **{count}**"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Нажать (+1)", callback_data="tasbih_inc")],
        [InlineKeyboardButton(text="🔄 Сбросить", callback_data="tasbih_reset")],
        [InlineKeyboardButton(text="⬅️ К выбору", callback_data="back_to_duas")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("salawat_"))
async def process_salawat(callback: types.CallbackQuery):
    action = callback.data.split("_")[1]
    user_id = callback.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT salawat FROM daily_progress WHERE user_id = ? AND date = ?", (user_id, today))
    row = cursor.fetchone()
    count = row[0] if row else 0
    if action == "inc": count += 1
    elif action == "reset": count = 0
    cursor.execute("UPDATE daily_progress SET salawat = ? WHERE user_id = ? AND date = ?", (count, user_id, today))
    conn.commit()
    conn.close()
    
    text = f"🌹 **Салават Пророку ﷺ**\n\nТекущий счет: **{count}**"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Нажать (+1)", callback_data="salawat_inc")],
        [InlineKeyboardButton(text="🔄 Сбросить", callback_data="salawat_reset")],
        [InlineKeyboardButton(text="⬅️ К выбору", callback_data="back_to_duas")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data == "morning_adhkar_full")
async def morning_adhkar_full(callback: types.CallbackQuery):
    text = (
        "☀️ **Утренние азкары**\n\n"
        "1. **Аят аль-Курси (сура «Аль-Бақара», 255) — 1 раз:**\n"
        "«Аллаху ля иляха илля хуваль хайюль кайюм, не берет Его ни дремота, ни сон. Ему принадлежит то, что на небесах, и то, что на земле...»\n\n"
        "2. **Три последние суры («Аль-Ихляс», «Аль-Фаляк», «Ан-Нас») — по 3 раза.**\n\n"
        "3. **Формула начала утра:**\n"
        "«Асбахна ва асбах аль-мульку ли-Ллях, ва-ль-хамду ли-Ллях, ля иляха илля-Ллаху вахдаху ля шарика ляh...»"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить азкары", callback_data="mark_morning_done")],
        [InlineKeyboardButton(text="⬅️ Назад к поминаниям", callback_data="back_to_duas")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data == "mark_morning_done")
async def mark_morning_done(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE daily_progress SET morning_adhkar = 1 WHERE user_id = ? AND date = ?", (user_id, today))
    conn.commit()
    conn.close()
    await callback.answer("Утренние азкары зафиксированы! 🤍", show_alert=True)

@router.callback_query(F.data == "evening_adhkar_full")
async def evening_adhkar_full(callback: types.CallbackQuery):
    text = (
        "🌙 **Вечерние азкары**\n\n"
        "1. **Аят аль-Курси (сура «Аль-Бақара», 255) — 1 раз**\n\n"
        "2. **Три последние суры («Аль-Ихляс», «Аль-Фаляк», «Ан-Нас») — по 3 раза**\n\n"
        "3. **Формула начала вечера:**\n"
        "«Амсайна ва амса аль-мульку ли-Ллях, ва-ль-хамду ли-Ллях, ля иляха илля-Ллаху вахдаху ля шарика ляh...»"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить азкары", callback_data="mark_evening_done")],
        [InlineKeyboardButton(text="⬅️ Назад к поминаниям", callback_data="back_to_duas")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data == "mark_evening_done")
async def mark_evening_done(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE daily_progress SET evening_adhkar = 1 WHERE user_id = ? AND date = ?", (user_id, today))
    conn.commit()
    conn.close()
    await callback.answer("Вечерние азкары зафиксированы! 🤍", show_alert=True)

# === МОЙ ПУТЬ ===
@router.message(F.text == "📊 Мой путь")
async def cmd_my_path(message: types.Message):
    user_id = message.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT quran, books, steps, sport, tasbih, salawat, morning_adhkar, evening_adhkar,
               fajr_done, dhuhr_done, asr_done, maghrib_done, isha_done, tahajjud_done
        FROM daily_progress WHERE user_id = ? AND date = ?
    """, (user_id, today))
    row = cursor.fetchone()
    conn.close()
    
    quran, books, steps, sport, tasbih, salawat, m_adhkar, e_adhkar, f, d, a, m, i, t = row if row else ("", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    
    summary_text = (
        f"📊 **Сводка дня ({today})**\n\n"
        "🕌 **Намазы и ночь:**\n"
        f"• Тахаджуд: {'✅' if t else '⬜'}\n"
        f"• Фаджр: {'✅' if f else '⬜'}\n"
        f"• Зухр: {'✅' if d else '⬜'}\n"
        f"• Аср: {'✅' if a else '⬜'}\n"
        f"• Магриб: {'✅' if m else '⬜'}\n"
        f"• Иша: {'✅' if i else '⬜'}\n\n"
        f"📖 **Коран:** {quran if quran else 'Не записано'}\n"
        f"📚 **Книги:** {books} стр. | 👣 **Шаги:** {steps} | ⚽ **Спорт:** {sport} мин.\n"
        f"📿 **Тасбих:** {tasbih} | 🌹 **Салават:** {salawat}\n"
        f"☀️ **Утренние азкары:** {'✅' if m_adhkar else '⬜'}\n"
        f"🌙 **Вечерние азкары:** {'✅' if e_adhkar else '⬜'}\n\n"
        "Пусть Всевышний примет ваш труд! 🤍"
    )
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 История поклонения", callback_data="history_archive")],
        [InlineKeyboardButton(text="⛳ Внести активность", callback_data="add_activity_menu")]
    ])
    await message.answer(summary_text, reply_markup=markup, parse_mode="Markdown")

@router.callback_query(F.data == "history_archive")
async def history_archive(callback: types.CallbackQuery):
    text = "📜 **История поклонения**\n\nЗдесь бережно хранится ваш архив достижений и благородных стремлений 🤍."
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад к сводке", callback_data="back_to_summary")]])
    try: await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest: pass
    await callback.answer()

@router.callback_query(F.data == "back_to_summary")
async def back_to_summary(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT quran, books, steps, sport, tasbih, salawat, morning_adhkar, evening_adhkar,
               fajr_done, dhuhr_done, asr_done, maghrib_done, isha_done, tahajjud_done
        FROM daily_progress WHERE user_id = ? AND date = ?
    """, (user_id, today))
    row = cursor.fetchone()
    conn.close()
    quran, books, steps, sport, tasbih, salawat, m_adhkar, e_adhkar, f, d, a, m, i, t = row if row else ("", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    summary_text = (
        f"📊 **Сводка дня ({today})**\n\n"
        f"🕌 Намазы: Тахаджуд {'✅' if t else '⬜'} | Фаджр {'✅' if f else '⬜'} | Зухр {'✅' if d else '⬜'} | Аср {'✅' if a else '⬜'} | Магриб {'✅' if m else '⬜'} | Иша {'✅' if i else '⬜'}\n\n"
        "Пусть Аллах примет ваш труд! 🤍"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 История поклонения", callback_data="history_archive")],
        [InlineKeyboardButton(text="⛳ Внести активность", callback_data="add_activity_menu")]
    ])
    try: await callback.message.edit_text(summary_text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest: pass
    await callback.answer()

@router.callback_query(F.data == "add_activity_menu")
async def add_activity_menu(callback: types.CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Коран", callback_data="act_quran"), InlineKeyboardButton(text="📚 Книги", callback_data="act_books")],
        [InlineKeyboardButton(text="👣 Шаги", callback_data="act_steps"), InlineKeyboardButton(text="⚽ Спорт", callback_data="act_sport")],
        [InlineKeyboardButton(text="⬅️ К сводке", callback_data="back_to_summary")]
    ])
    try: await callback.message.edit_text("⛳ **Выберите категорию для записи активности:**", reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest: pass
    await callback.answer()

@router.callback_query(F.data == "act_quran")
async def act_quran(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Напишите, какую суру или аяты вы прочитали сегодня:")
    await state.set_state(ActivityForm.entering_quran)
    await callback.answer()

@router.message(ActivityForm.entering_quran)
async def save_quran(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    text = message.text
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE daily_progress SET quran = ? WHERE user_id = ? AND date = ?", (text, user_id, today))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer(f"Машаллах! Записано чтение Корана: **{text}**. 🤍", parse_mode="Markdown", reply_markup=get_main_keyboard())

@router.callback_query(F.data == "act_books")
async def act_books(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Сколько страниц книги вы прочитали сегодня? (введите число):")
    await state.set_state(ActivityForm.entering_books)
    await callback.answer()

@router.message(ActivityForm.entering_books)
async def save_books(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    try: val = int(message.text)
    except ValueError:
        await message.answer("Пожалуйста, введите число.")
        return
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE daily_progress SET books = books + ? WHERE user_id = ? AND date = ?", (val, user_id, today))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer(f"Записано: **{val}** страниц книг. 🤍", parse_mode="Markdown", reply_markup=get_main_keyboard())

@router.callback_query(F.data == "act_steps")
async def act_steps(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите количество шагов:")
    await state.set_state(ActivityForm.entering_steps)
    await callback.answer()

@router.message(ActivityForm.entering_steps)
async def save_steps(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    try: val = int(message.text)
    except ValueError:
        await message.answer("Пожалуйста, введите число.")
        return
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE daily_progress SET steps = steps + ? WHERE user_id = ? AND date = ?", (val, user_id, today))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer(f"Записано: **{val}** шагов. 🤍", parse_mode="Markdown", reply_markup=get_main_keyboard())

@router.callback_query(F.data == "act_sport")
async def act_sport(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите количество минут спорта или легкой разминки:")
    await state.set_state(ActivityForm.entering_sport)
    await callback.answer()

@router.message(ActivityForm.entering_sport)
async def save_sport(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    try: val = int(message.text)
    except ValueError:
        await message.answer("Пожалуйста, введите число.")
        return
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE daily_progress SET sport = sport + ? WHERE user_id = ? AND date = ?", (val, user_id, today))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer(f"Записано: **{val}** минут активности. 🤍", parse_mode="Markdown", reply_markup=get_main_keyboard())

# === АКТУАЛЬНЫЙ РЕЖИМ И ДЕЛИКАТНАЯ ПАУЗА ===
@router.message(F.text == "⚙️ Актуальный режим")
async def cmd_current_mode(message: types.Message):
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT city, mode, rhythm FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    city = row[0] if row else "Нерюнгри"
    mode = row[1] if row else "active"
    rhythm = row[2] if row else "Аль-Фард"
    
    if mode == "pause":
        text = (
            "🌸 **Деликатная пауза активна** 🌸\n\n"
            "Дорогая сестра! В эти дни Всевышний проявил к тебе особую заботу, освободив от обязательных молитв и постов. "
            "Это священное время отдыха, умиротворения и бережного отношения к себе. Напоминания о намазах временно отключены, чтобы твое сердце могло полностью расслабиться.\n\n"
            "Твой духовный прогресс находится в абсолютной безопасности. Если почувствуешь внутренний отклик, ты всегда можешь произносить зикры и салаваты, "
            "слушать или читать Коран (наизусть или с экрана, не касаясь мусхафа), а также уделять время чтению книг, прогулкам или мягкой активности.\n\n"
            "Позволь себе этот отдых с чистой душой. Аллах видит твое стремление и любит каждый твой вдох 🤍."
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏙 Сменить город", callback_data="change_city")],
            [InlineKeyboardButton(text="🌱 Сменить режим", callback_data="change_rhythm_start")],
            [InlineKeyboardButton(text="▶️ Завершить паузу", callback_data="end_pause")]
        ])
    else:
        text = (
            f"⚙️ **Актуальный режим**\n\n"
            f"🏙 Текущий город: **{city}**\n"
            f"🌱 Духовный ритм: **{rhythm}**\n"
            f"✨ Статус: **Активный ритм**\n\n"
            "Вы находитесь в гармоничном потоке поклонения 🤍."
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏙 Сменить город", callback_data="change_city")],
            [InlineKeyboardButton(text="🌱 Сменить режим", callback_data="change_rhythm_start")],
            [InlineKeyboardButton(text="🌸 Включить деликатную паузу", callback_data="set_pause_special")]
        ])
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")

@router.callback_query(F.data == "change_city")
async def change_city_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название вашего города или области на кириллице (например, Нерюнгри, Якутск, Москва, Бишкек):")
    await state.set_state(ActivityForm.updating_city)
    await callback.answer()

@router.message(ActivityForm.updating_city)
async def save_city_update(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    city_name = message.text.strip()
    lat, lon = await get_coordinates_by_city(city_name)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET city = ?, latitude = ?, longitude = ? WHERE user_id = ?", (city_name, lat, lon, user_id))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"Город успешно изменен на: **{city_name}** 🤍", parse_mode="Markdown", reply_markup=get_main_keyboard())

@router.callback_query(F.data == "change_rhythm_start")
async def change_rhythm_start(callback: types.CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Аль-Фард", callback_data="rhythm_Аль-Фард")],
        [InlineKeyboardButton(text="🌿 Аль-Истикама", callback_data="rhythm_Аль-Истикама")],
        [InlineKeyboardButton(text="📖 Ат-Тазкия", callback_data="rhythm_Аль-Тазкия")],
        [InlineKeyboardButton(text="⭐ Аль-Ихсан", callback_data="rhythm_Аль-Ихсан")]
    ])
    try: await callback.message.edit_text("✨ **Выберите новый духовный ритм:**", reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest: pass
    await callback.answer()

@router.callback_query(F.data == "set_pause_special")
async def set_pause_special(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET mode = 'pause' WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    text = (
        "🌸 **Деликатная пауза активна** 🌸\n\n"
        "Дорогая сестра! В эти дни Всевышний проявил к тебе особую заботу, освободив от обязательных молитв и постов. "
        "Это священное время отдыха, умиротворения и бережного отношения к себе. Напоминания о намазах временно отключены, чтобы твое сердце могло полностью расслабиться.\n\n"
        "Твой духовный прогресс находится в абсолютной безопасности. Если почувствуешь внутренний отклик, ты всегда можешь произносить зикры и салаваты, "
        "слушать или читать Коран (наизусть или с экрана, не касаясь мусхафа), а также уделять время чтению книг, прогулкам или мягкой активности.\n\n"
        "Позволь себе этот отдых с чистой душой. Аллах видит твое стремление и любит каждый твой вдох 🤍."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏙 Сменить город", callback_data="change_city")],
        [InlineKeyboardButton(text="🌱 Сменить режим", callback_data="change_rhythm_start")],
        [InlineKeyboardButton(text="▶️ Завершить паузу", callback_data="end_pause")]
    ])
    try:
        msg = await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
        await msg.pin()
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data == "end_pause")
async def end_pause(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET mode = 'active' WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    try:
        await callback.message.unpin()
    except Exception:
        pass
        
    text = (
        "✨ **С возвращением к молитве, дорогая сестра!** 🤍\n\n"
        "Позади дни отдыха, подаренные Всевышним. Теперь твое сердце снова готово к предстоянию перед Ним.\n\n"
        "Прими полное омовение (гусль), обнови свое намерение и соверши этот первый намаз из наилучшего состояния — с трепетом, любовью и искренней надеждой на Его довольство и милость.\n\n"
        "Напоминания о намазах снова бережно включены. Пусть каждый твой поклон будет источником света и мира в душе 🌿."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏙 Сменить город", callback_data="change_city")],
        [InlineKeyboardButton(text="🌱 Сменить режим", callback_data="change_rhythm_start")],
        [InlineKeyboardButton(text="🌸 Включить деликатную паузу", callback_data="set_pause_special")]
    ])
    try: await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest: pass
    await callback.answer()

# === ВЕЧЕРНИЙ ОПРОС И ПОДДЕРЖКА ===
@router.callback_query(F.data.startswith("evening_mood_"))
async def process_evening_mood(callback: types.CallbackQuery):
    mood = callback.data.split("_")[2]
    if mood == "good":
        text = "Альхамдулиллах! Пусть этот внутренний свет и благодать сопровождают вас и в новом дне 🤍."
    elif mood == "neutral":
        text = "Тихий и умиротворенный день полон скрытой мудрости и милости Творца 🤍."
    else:
        text = "Аллах видит ваше терпение, каждую трудность и искренний труд сердца. Отдохните, ведь даже малое обращение к Нему в этот час ценно и любимо 🤍."
    
    try:
        await callback.message.edit_text(text, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

# === ФОНОВЫЙ ПУЛЬС (УВЕДОМЛЕНИЯ, РОТАЦИЯ НАЗИДАНИЙ И ВЕЧЕРНИЙ ЧЕК-ИН) ===
async def background_scheduler(bot: Bot):
    # Духовные назидания для ротации за 5 минут до намаза
    reminders_pool = [
        ("📖 **Аят из Корана:**\n«Воистину, намаз предписан верующим в определенное время» (сура Ан-Ниса, 103).", "ayat"),
        ("🌹 **Хадис Пророка ﷺ:**\n«Первое, о чем будет спрошен раб в Судный день — это намаз. Если он будет в порядке, то преуспеет и спасается...»", "hadith"),
        ("📜 **История из жизни пророков:**\nПророк Ибрахим (мир ему) обращался к Всемувышнему: «Господи! Сделай меня и мое потомство совершающими намаз...»", "prophet_story"),
        ("✨ **Предание о сподвижниках:**\nСподвижники спешили к намазу с трепетом в сердце, чувствуя себя гостями перед Великим Царем миров.", "companion_story")
    ]

    while True:
        try:
            now = get_local_now()
            current_time_str = now.strftime("%H:%M")
            today = now.strftime("%Y-%m-%d")
            is_friday = (now.weekday() == 4) # Пятница
            
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, city, mode, latitude, longitude FROM users WHERE onboarding_completed = 1")
            users = cursor.fetchall()
            
            for user_id, city, mode, lat, lon in users:
                # Пятничный модуль (в 08:00 утра напоминаем о суре Аль-Кахф и салаватах)
                if is_friday and current_time_str == "08:00":
                    cursor.execute("SELECT 1 FROM notification_log WHERE user_id = ? AND date = ? AND prayer_key = 'friday_reminder' AND notification_type = 'friday'", (user_id, today))
                    if not cursor.fetchone():
                        friday_text = (
                            "✨ **Благословенная пятница (Джумуа)** ✨\n\n"
                            "Пусть этот день наполнит ваше сердце светом и баракатом!\n"
                            "• Не забудьте прочитать суру «Аль-Кахф».\n"
                            "• Увеличьте количество благословений и салаватов нашему Пророку Мухаммаду ﷺ.\n"
                            "• Помните о часе принятия дуа перед заходом солнца 🤍."
                        )
                        try:
                            await bot.send_message(user_id, friday_text, parse_mode="Markdown")
                            cursor.execute("INSERT OR IGNORE INTO notification_log (user_id, date, prayer_key, notification_type) VALUES (?, ?, 'friday_reminder', 'friday')", (user_id, today))
                            conn.commit()
                        except Exception as e:
                            logging.error(f"Failed to send Friday reminder: {e}")

                # Вечерний опрос (21:30) отправляем даже во время деликатной паузы
                if current_time_str == "21:30":
                    cursor.execute("SELECT 1 FROM notification_log WHERE user_id = ? AND date = ? AND prayer_key = 'evening_mood' AND notification_type = 'prompt'", (user_id, today))
                    if not cursor.fetchone():
                        mood_text = "🌙 **Вечерний вдох**\n\nКак чувствует себя ваше сердце сегодня?"
                        markup = InlineKeyboardMarkup(inline_keyboard=[
                            [
                                InlineKeyboardButton(text="😇 Светло и радостно", callback_data="evening_mood_good"),
                                InlineKeyboardButton(text="🙂 Спокойно", callback_data="evening_mood_neutral"),
                                InlineKeyboardButton(text="🥺 Устала / тяжело", callback_data="evening_mood_hard")
                            ]
                        ])
                        try:
                            await bot.send_message(user_id, mood_text, reply_markup=markup, parse_mode="Markdown")
                            cursor.execute("INSERT OR IGNORE INTO notification_log (user_id, date, prayer_key, notification_type) VALUES (?, ?, 'evening_mood', 'prompt')", (user_id, today))
                            conn.commit()
                        except Exception as e:
                            logging.error(f"Failed to send evening mood prompt: {e}")

                # Если активна деликатная пауза, уведомления о намазах не приходят
                if mode == "pause":
                    continue
                
                ensure_daily_record(user_id)
                prayer_times = await get_prayer_times(city, lat, lon, today)
                
                prayer_keys = [
                    ("Фаджр", "fajr", "fajr_done"),
                    ("Зухр", "dhuhr", "dhuhr_done"),
                    ("Аср", "asr", "asr_done"),
                    ("Магриб", "maghrib", "maghrib_done"),
                    ("Иша", "isha", "isha_done")
                ]
                
                for idx, (p_name, p_key, p_done_col) in enumerate(prayer_keys):
                    p_time_str = prayer_times.get(p_name, "12:00")
                    try:
                        p_dt = datetime.strptime(p_time_str, "%H:%M")
                    except ValueError:
                        continue
                    
                    minus_5 = (p_dt - timedelta(minutes=5)).strftime("%H:%M")
                    
                    # 1. Уведомление за 5 минут с ротацией назиданий
                    if current_time_str == minus_5:
                        cursor.execute("""
                            SELECT 1 FROM notification_log 
                            WHERE user_id = ? AND date = ? AND prayer_key = ? AND notification_type = '5min'
                        """, (user_id, today, p_key))
                        if not cursor.fetchone():
                            # Выбираем назидание по циклу индекса намаза
                            reminder_text, _ = reminders_pool[idx % len(reminders_pool)]
                            sense_text = (
                                f"🕌 **Приближается время намаза: {p_name}** ({p_time_str}, через 5 минут)\n\n"
                                f"{reminder_text}\n\n"
                                "Пусть связь со Всевышним укрепится в этот час 🤍."
                            )
                            markup = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🤍 Альхамдулиллах", callback_data=f"toggle_p_{p_key}")]
                            ])
                            try:
                                await bot.send_message(user_id, sense_text, reply_markup=markup, parse_mode="Markdown")
                                cursor.execute("INSERT OR IGNORE INTO notification_log (user_id, date, prayer_key, notification_type) VALUES (?, ?, ?, '5min')", (user_id, today, p_key))
                                conn.commit()
                            except Exception as e:
                                logging.error(f"Failed to send 5min reminder: {e}")

                    # 2. Второе (повторное) напоминание в момент наступления намаза
                    if current_time_str == p_time_str:
                        cursor.execute("""
                            SELECT 1 FROM notification_log 
                            WHERE user_id = ? AND date = ? AND prayer_key = ? AND notification_type = 'exact'
                        """, (user_id, today, p_key))
                        if not cursor.fetchone():
                            exact_text = f"⏰ **Время намаза {p_name} наступило.** Пусть Всевышний примет ваше поклонение и дарует мир сердцу 🤍."
                            markup = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🤍 Альхамдулиллах", callback_data=f"toggle_p_{p_key}")]
                            ])
                            try:
                                await bot.send_message(user_id, exact_text, reply_markup=markup, parse_mode="Markdown")
                                cursor.execute("INSERT OR IGNORE INTO notification_log (user_id, date, prayer_key, notification_type) VALUES (?, ?, ?, 'exact')", (user_id, today, p_key))
                                conn.commit()
                            except Exception as e:
                                logging.error(f"Failed to send exact time reminder: {e}")

            conn.close()
        except Exception as ex:
            logging.error(f"Scheduler error: {ex}")
        await asyncio.sleep(60)

async def handle_ping(request):
    return web.Response(text="Amal365 Bot is active and running! 🤍")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server started on port {port}")

async def main():
    init_db()
    logging.basicConfig(level=logging.INFO)
    token = os.getenv("BOT_TOKEN")
    if not token:
        logging.error("Не найден токен бота! Проверьте вкладку Environment на Render.")
        return
    bot = Bot(token=token)
    
    # Настройка синего Bot Command меню слева (Вариант 3)
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="prayer", description="⏰ Время намазов"),
        BotCommand(command="duas", description="📿 Поминания и дуа"),
        BotCommand(command="path", description="📊 Мой путь"),
        BotCommand(command="mode", description="⚙️ Актуальный режим")
    ])

    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)
    
    await start_web_server()
    asyncio.create_task(background_scheduler(bot))
    
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped!")
