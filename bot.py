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
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            country TEXT DEFAULT 'Россия',
            city TEXT DEFAULT 'Нерюнгри',
            latitude REAL DEFAULT 56.6644,
            longitude REAL DEFAULT 124.7042,
            rhythm TEXT DEFAULT 'Аль-Фард',
            rhythm_start_date TEXT,
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
    city_lower = city.strip().lower()
    if "нерюнгри" in city_lower:
        return {
            "Тахаджуд": "03:30",
            "Фаджр": "04:58",
            "Восход солнца": "07:02",
            "Зухр": "12:29",
            "Аср": "15:11",
            "Магриб": "17:54",
            "Иша": "19:52"
        }
    elif "якутск" in city_lower:
        return {
            "Тахаджуд": "03:30",
            "Фаджр": "04:53",
            "Восход солнца": "07:00",
            "Зухр": "12:29",
            "Аср": "15:13",
            "Магриб": "17:56",
            "Иша": "19:55"
        }
        
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
        "Фаджр": "04:58", "Восход солнца": "07:02", "Зухр": "12:29",
        "Аср": "15:11", "Магриб": "17:54", "Иша": "19:52"
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
@router.message(F.text.in_(["/start", "🏠 Главное меню"]))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    fname = message.from_user.first_name or ""
    uname = message.from_user.username or ""
    
    try:
        await message.delete()
    except Exception:
        pass

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT onboarding_completed FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.execute("INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)", (user_id, uname, fname))
        conn.commit()
    else:
        cursor.execute("UPDATE users SET username = ?, first_name = ? WHERE user_id = ?", (uname, fname, user_id))
        conn.commit()
    conn.close()
    
    if row and row[0] == 1:
        await message.answer("🤍 **С возвращением в Amal365!**\nВаш духовный ритм бережно поддерживается.", reply_markup=get_main_keyboard(), parse_mode="Markdown")
        return

    text = (
        "Ассаляму алейкум ва рахматуллахи ва баракатух 🌙\n\n"
        "Добро пожаловать в **Amal365** — Ваше благословенное пространство постоянства в благих делах, душевного тепла и внутреннего мира.\n\n"
        "Мы бережно сохраним каждый Ваш шаг на этом светлом пути. Пусть Всевышний дарует благословение в каждом Вашем начинании 🤍"
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
        await callback.message.edit_text("Двери Amal365 всегда открыты для Вас. Всего доброго! 🤍", reply_markup=markup, parse_mode="Markdown")
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
        await callback.message.edit_text("🌍 **Выбор региона**\n\nПожалуйста, выберите Вашу страну:", reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("country_"))
async def select_country(callback: types.CallbackQuery, state: FSMContext):
    country = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET country = ? WHERE user_id = ?", (country, user_id))
    conn.commit()
    conn.close()
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="onboard_bismillah")]
    ])
    try:
        await callback.message.edit_text(
            f"🏙 **Укажите Ваш населенный пункт**\n\nВы выбрали: **{country}**.\n\nНапишите название Вашего города или области на кириллице (например: *Нерюнгри, Якутск, Москва, Бишкек*):",
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
    
    try:
        await message.delete()
    except Exception:
        pass

    await message.answer(
        f"✅ Город **{city_name}** успешно сохранен!\n\n"
        "✨ **Выберите Ваш духовный ритм сопровождения:**\n\n"
        "• 🌱 **Аль-Фард** — *Фундамент веры:* 5 обязательных молитв, утренние и вечерние азкары, тасбих/салават (Тахаджуд по желанию).\n"
        "• 🌿 **Аль-Истикама** — *Постоянство:* фундамент Аль-Фард + чтение и слушание Корана по зову сердца.\n"
        "• 📖 **Ат-Тазкия** — *Очищение и знание:* фундамент Аль-Фард + чтение полезных книг и духовное развитие.\n"
        "• ⭐ **Аль-Ихсан** — *Вершина искренности:* гармония обязательного и добровольного поклонения, Коран, книги и благородные дела.",
        reply_markup=markup, parse_mode="Markdown"
    )

@router.callback_query(F.data.startswith("rhythm_"))
async def select_rhythm(callback: types.CallbackQuery):
    rhythm = callback.data.split("_")[1]
    user_id = callback.from_user.id
    today = get_today_str()
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET rhythm = ?, rhythm_start_date = ?, onboarding_completed = 1 WHERE user_id = ?", (rhythm, today, user_id))
    conn.commit()
    conn.close()
    
    text = (
        f"🤍 **Альхамдулиллах, намерение оформлено.**\n\n"
        f"Ритм **«{rhythm}»** бережно настроен для Вас.\n"
        "Пусть этот путь принесет в Ваше сердце свет, умиротворение и сакину."
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.message.answer("Главное меню активировано:", reply_markup=get_main_keyboard())
    await callback.answer()

# === ВРЕМЯ НАМАЗОВ И ОБРАТНЫЙ ОТСЧЕТ ===
@router.message(F.text.in_(["/prayer", "⏰ Время намазов"]))
async def cmd_prayer_times(message: types.Message):
    try:
        await message.delete()
    except Exception:
        pass

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
        time_diff_str = "Наступило ночное время. Пусть Ваш отдых будет благословенным."

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
        guide_text = (
            "✨ **Альхамдулиллах! Намаз бережно зафиксирован в Вашем дневнике.** 🤍\n\n"
            "Если у Вас есть искреннее желание наполнить душу дополнительным светом и покоем, "
            "Вы всегда можете зайти в раздел **«Поминания и дуа»** для совершения азкаров, тасбиха или салавата."
        )
        try:
            await callback.message.reply(guide_text, parse_mode="Markdown")
        except Exception:
            pass
    else:
        await callback.answer("Статус намаза обновлен! 🤍")

# === ПОМИНАНИЯ И ДУА ===
@router.message(F.text.in_(["/duas", "📿 Поминания и дуа"]))
async def cmd_duas(message: types.Message):
    try:
        await message.delete()
    except Exception:
        pass

    text = (
        "📿 **Поминания и дуа**\n\n"
        "«Поминайте Меня, и Я буду помнить вас» (сура Аль-Бақара, 152).\n\n"
        "Выберите нужный раздел для духовного наполнения сердца:"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Тасбих", callback_data="tasbih_open")],
        [InlineKeyboardButton(text="🌹 Салават", callback_data="salawat_open")],
        [InlineKeyboardButton(text="☀️ Утренние азкары", callback_data="morning_adhkar_full")],
        [InlineKeyboardButton(text="🌙 Вечерние азкары", callback_data="evening_adhkar_full")]
    ])
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")

@router.callback_query(F.data == "back_to_duas")
async def back_to_duas(callback: types.CallbackQuery):
    text = (
        "📿 **Поминания и дуа**\n\n"
        "«Поминайте Меня, и Я буду помнить вас» (сура Аль-Бақара, 152).\n\n"
        "Выберите нужный раздел:"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Тасбих", callback_data="tasbih_open")],
        [InlineKeyboardButton(text="🌹 Салават", callback_data="salawat_open")],
        [InlineKeyboardButton(text="☀️ Утренние азкары", callback_data="morning_adhkar_full")],
        [InlineKeyboardButton(text="🌙 Вечерние азкары", callback_data="evening_adhkar_full")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data == "tasbih_open")
async def tasbih_open(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(session_tasbih=0)
    text = (
        "📿 **Тасбих**\n\n"
        "«Воистину, в поминании Аллаха находят успокоение сердца» (сура Ар-Рад, 28).\n\n"
        "Текущий круг: **0**"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Нажать (+1)", callback_data="tasbih_inc")],
        [InlineKeyboardButton(text="🔄 Сбросить круг", callback_data="tasbih_reset")],
        [InlineKeyboardButton(text="⬅️ К выбору", callback_data="back_to_duas")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("tasbih_"))
async def process_tasbih(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data.split("_")[1]
    if action == "open": return
    
    user_id = callback.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    
    data = await state.get_data()
    session_count = data.get("session_tasbih", 0)
    
    if action == "inc":
        session_count += 1
        await state.update_data(session_tasbih=session_count)
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE daily_progress SET tasbih = tasbih + 1 WHERE user_id = ? AND date = ?", (user_id, today))
        conn.commit()
        conn.close()
    elif action == "reset":
        session_count = 0
        await state.update_data(session_tasbih=0)

    text = (
        "📿 **Тасбих**\n\n"
        "«Воистину, в поминании Аллаха находят успокоение сердца» (сура Ар-Рад, 28).\n\n"
        f"Текущий круг: **{session_count}**"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Нажать (+1)", callback_data="tasbih_inc")],
        [InlineKeyboardButton(text="🔄 Сбросить круг", callback_data="tasbih_reset")],
        [InlineKeyboardButton(text="⬅️ К выбору", callback_data="back_to_duas")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data == "salawat_open")
async def salawat_open(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(session_salawat=0)
    text = (
        "🌹 **Салават Пророку ﷺ**\n\n"
        "«Воистину, Аллах и Его ангелы благословляют Пророка...» (сура Аль-Ахзаб, 56).\n\n"
        "Текущий круг: **0**"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Нажать (+1)", callback_data="salawat_inc")],
        [InlineKeyboardButton(text="🔄 Сбросить круг", callback_data="salawat_reset")],
        [InlineKeyboardButton(text="⬅️ К выбору", callback_data="back_to_duas")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("salawat_"))
async def process_salawat(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data.split("_")[1]
    if action == "open": return
    
    user_id = callback.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    
    data = await state.get_data()
    session_count = data.get("session_salawat", 0)
    
    if action == "inc":
        session_count += 1
        await state.update_data(session_salawat=session_count)
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE daily_progress SET salawat = salawat + 1 WHERE user_id = ? AND date = ?", (user_id, today))
        conn.commit()
        conn.close()
    elif action == "reset":
        session_count = 0
        await state.update_data(session_salawat=0)

    text = (
        "🌹 **Салават Пророку ﷺ**\n\n"
        "«Воистину, Аллах и Его ангелы благословляют Пророка...» (сура Аль-Ахзаб, 56).\n\n"
        f"Текущий круг: **{session_count}**"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Нажать (+1)", callback_data="salawat_inc")],
        [InlineKeyboardButton(text="🔄 Сбросить круг", callback_data="salawat_reset")],
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
        "«Аллаху ля иляха илля хуваль-Хайюль-Кайюм. Ля та'хузуху синатув-ва ля наум. Ляху ма фис-самавати ва ма филь-ард. Ман зал-лязи яшфа‘у ‘индаху илля би-изних. Я‘ляму ма байна айдихим ва ма хальфахум. Ва ля юхитуна би-шай'им-мин ‘ильмихи илля би-ма ша'а. Васи‘а курсийюхус-самавати валь-арда, ва ля я'удуху хифзухума, ва хуваль-‘Алийюль-‘Азим».\n\n"
        "2. **Три последние суры («Аль-Ихляс», «Аль-Фаляк», «Ан-Нас») — по 3 раза.**\n\n"
        "3. **Формула начала утра:**\n"
        "«Асбахна ва асбах аль-мульку ли-Ллях, ва-ль-хамду ли-Ллях, ля иляха илля-Ллаху вахдаху ля шарика ляh, ляhуль-мульку ва ляhуль-хамду ва хува ‘аля кулли шай'ин кадир...»"
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
    await callback.answer("Машаллах! Пусть эти утренние поминания станут Вашей надежной защитой, светом и крепостью на весь предстоящий день 🤍", show_alert=True)

@router.callback_query(F.data == "evening_adhkar_full")
async def evening_adhkar_full(callback: types.CallbackQuery):
    text = (
        "🌙 **Вечерние азкары**\n\n"
        "1. **Аят аль-Курси (сура «Аль-Бақара», 255) — 1 раз:**\n"
        "«Аллаху ля иляха илля хуваль-Хайюль-Кайюм. Ля та'хузуху синатув-ва ля наум. Ляху ма фис-самавати ва ма филь-ард. Ман зал-лязи яшфа‘у ‘индаху илля би-изних...»\n\n"
        "2. **Три последние суры («Аль-Ихляс», «Аль-Фаляк», «Ан-Нас») — по 3 раза.**\n\n"
        "3. **Формула начала вечера:**\n"
        "«Амсайна ва амса аль-мульку ли-Ллях, ва-ль-хамду ли-Ллях, ля иляха илля-Ллаху вахдаху ля шарика ляh, ляhуль-мульку ва ляhуль-хамду ва хува ‘аля кулли шай'ин кадир...»"
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
    await callback.answer("Альхамдулиллах! Пусть поминание Всевышнего принесет Вашему сердцу покой, мир и сакину в этот вечер 🌙🤍", show_alert=True)

# === МОЙ ПУТЬ ===
@router.message(F.text.in_(["/path", "📊 Мой путь"]))
async def cmd_my_path(message: types.Message):
    try:
        await message.delete()
    except Exception:
        pass

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
        "Пусть Всевышний примет Ваш труд и украсит Ваши дни поминанием! 🤍"
    )
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 История поклонения", callback_data="history_archive")],
        [InlineKeyboardButton(text="⛳ Внести активность", callback_data="add_activity_menu")]
    ])
    await message.answer(summary_text, reply_markup=markup, parse_mode="Markdown")

@router.callback_query(F.data == "history_archive")
async def history_archive(callback: types.CallbackQuery):
    text = "📜 **История поклонения**\n\nЗдесь бережно хранится Ваш архив достижений и благородных стремлений 🤍."
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
        f"📖 Коран: {quran if quran else 'Не записано'}\n"
        f"📚 Книги: {books} стр. | 👣 Шаги: {steps} | ⚽ Спорт: {sport} мин.\n"
        f"📿 Тасбих: {tasbih} | 🌹 Салават: {salawat}\n\n"
        "Пусть Аллах примет Ваш труд! 🤍"
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
    text = (
        "⛳ **Внесение активности**\n\n"
        "«Стремитесь же к благим делам» (сура Аль-Маида, 48).\n\n"
        "Выберите категорию для записи:"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Коран (+1 аят)", callback_data="act_quran_plus")],
        [InlineKeyboardButton(text="📚 Книги (+5 стр)", callback_data="act_books_plus"), InlineKeyboardButton(text="📚 Книги (+10 стр)", callback_data="act_books_plus10")],
        [InlineKeyboardButton(text="👣 Шаги (+1000)", callback_data="act_steps_plus"), InlineKeyboardButton(text="👣 Шаги (+5000)", callback_data="act_steps_plus5000")],
        [InlineKeyboardButton(text="⚽ Спорт (+15 мин)", callback_data="act_sport_plus"), InlineKeyboardButton(text="⚽ Спорт (+30 мин)", callback_data="act_sport_plus30")],
        [InlineKeyboardButton(text="⬅️ К сводке", callback_data="back_to_summary")]
    ])
    try: await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest: pass
    await callback.answer()

# === ИНТЕРАКТИВНОЕ ВНЕСЕНИЕ АКТИВНОСТИ ЧЕРЕЗ КНОПКИ (БЕЗ ЗАСОРА ЧАТА) ===
@router.callback_query(F.data.startswith("act_"))
async def process_activity_buttons(callback: types.CallbackQuery):
    action = callback.data
    user_id = callback.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    if action == "act_quran_plus":
        cursor.execute("SELECT quran FROM daily_progress WHERE user_id = ? AND date = ?", (user_id, today))
        row = cursor.fetchone()
        current = row[0] if row else ""
        try:
            num = int(current.split()[0]) + 1 if current and current.split()[0].isdigit() else 1
        except:
            num = 1
        val_str = f"{num} аятов"
        cursor.execute("UPDATE daily_progress SET quran = ? WHERE user_id = ? AND date = ?", (val_str, user_id, today))
        notice = f"🌿 Добавлен аят! Всего: **{val_str}**"
    elif action == "act_books_plus":
        cursor.execute("UPDATE daily_progress SET books = books + 5 WHERE user_id = ? AND date = ?", (user_id, today))
        notice = "📚 Добавлено **5** страниц книг."
    elif action == "act_books_plus10":
        cursor.execute("UPDATE daily_progress SET books = books + 10 WHERE user_id = ? AND date = ?", (user_id, today))
        notice = "📚 Добавлено **10** страниц книг."
    elif action == "act_steps_plus":
        cursor.execute("UPDATE daily_progress SET steps = steps + 1000 WHERE user_id = ? AND date = ?", (user_id, today))
        notice = "👣 Добавлено **1000** шагов."
    elif action == "act_steps_plus5000":
        cursor.execute("UPDATE daily_progress SET steps = steps + 5000 WHERE user_id = ? AND date = ?", (user_id, today))
        notice = "👣 Добавлено **5000** шагов."
    elif action == "act_sport_plus":
        cursor.execute("UPDATE daily_progress SET sport = sport + 15 WHERE user_id = ? AND date = ?", (user_id, today))
        notice = "⚽ Добавлено **15** минут спорта."
    elif action == "act_sport_plus30":
        cursor.execute("UPDATE daily_progress SET sport = sport + 30 WHERE user_id = ? AND date = ?", (user_id, today))
        notice = "⚽ Добавлено **30** минут спорта."
    else:
        conn.close()
        await callback.answer()
        return

    conn.commit()
    
    # Получаем актуальную сводку дня для отрисовки в том же сообщении
    cursor.execute("""
        SELECT quran, books, steps, sport, tasbih, salawat, morning_adhkar, evening_adhkar,
               fajr_done, dhuhr_done, asr_done, maghrib_done, isha_done, tahajjud_done
        FROM daily_progress WHERE user_id = ? AND date = ?
    """, (user_id, today))
    row = cursor.fetchone()
    conn.close()
    
    quran, books, steps, sport, tasbih, salawat, m_adhkar, e_adhkar, f, d, a, m, i, t = row if row else ("", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    
    summary_text = (
        f"{notice} 🤍\n\n"
        f"📊 **Сводка дня ({today})**\n\n"
        f"🕌 Намазы: Тахаджуд {'✅' if t else '⬜'} | Фаджр {'✅' if f else '⬜'} | Зухр {'✅' if d else '⬜'} | Аср {'✅' if a else '⬜'} | Магриб {'✅' if m else '⬜'} | Иша {'✅' if i else '⬜'}\n\n"
        f"📖 Коран: {quran if quran else 'Не записано'}\n"
        f"📚 Книги: {books} стр. | 👣 Шаги: {steps} | ⚽ Спорт: {sport} мин.\n"
        f"📿 Тасбих: {tasbih} | 🌹 Салават: {salawat}\n\n"
        "Пусть Всевышний примет Ваш труд! 🤍"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 История поклонения", callback_data="history_archive")],
        [InlineKeyboardButton(text="⛳ Внести еще активность", callback_data="add_activity_menu")]
    ])
    
    try:
        await callback.message.edit_text(summary_text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer("Успешно записано! 🤍")

# === АКТУАЛЬНЫЙ РЕЖИМ И ДЕЛИКАТНАЯ ПАУЗА ===
@router.message(F.text.in_(["/mode", "⚙️ Актуальный режим"]))
async def cmd_current_mode(message: types.Message):
    try:
        await message.delete()
    except Exception:
        pass

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
            "Дорогая сестра! В эти дни Всевышний проявил к Вам особую заботу, освободив от обязательных молитв и постов. "
            "Это священное время отдыха, умиротворения и бережного отношения к себе. Напоминания о намазах временно отключены, чтобы Ваше сердце могло полностью расслабиться.\n\n"
            "Ваш духовный прогресс находится в абсолютной безопасности. Если почувствуете внутренний отклик, Вы всегда можете произносить зикры и салаваты, "
            "слушать или читать Коран (наизусть или с экрана, не касаясь мусхафа), а также уделять время чтению книг, прогулкам или мягкой активности.\n\n"
            "Позвольте себе этот отдых с чистой душой. Аллах видит Ваше стремление и любит каждый Ваш вдох 🤍."
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

@router.callback_query(F.data == "back_to_current_mode")
async def back_to_current_mode(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT city, mode, rhythm FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    city = row[0] if row else "Нерюнгри"
    mode = row[1] if row else "active"
    rhythm = row[2] if row else "Аль-Фард"
    
    if mode == "pause":
        text = "🌸 **Деликатная пауза активна** 🌸\n\nОтдыхайте с чистой душой 🤍."
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
            f"✨ Статус: **Активный ритм**"
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏙 Сменить город", callback_data="change_city")],
            [InlineKeyboardButton(text="🌱 Сменить режим", callback_data="change_rhythm_start")],
            [InlineKeyboardButton(text="🌸 Включить деликатную паузу", callback_data="set_pause_special")]
        ])
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data == "change_city")
async def change_city_start(callback: types.CallbackQuery, state: FSMContext):
    msg = await callback.message.edit_text("Введите название Вашего города или области на кириллице (например, Нерюнгри, Якутск, Москва, Бишкек):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_current_mode")]]))
    await state.update_data(prompt_msg_id=msg.message_id)
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
    try:
        await message.delete()
    except Exception:
        pass
        
    await message.answer(f"Город успешно изменен на: **{city_name}** 🤍", parse_mode="Markdown", reply_markup=get_main_keyboard())

@router.callback_query(F.data == "change_rhythm_start")
async def change_rhythm_start(callback: types.CallbackQuery):
    text = (
        "✨ **Выберите Ваш духовный ритм сопровождения:**\n\n"
        "• 🌱 **Аль-Фард** — *Фундамент веры:* 5 обязательных молитв, утренние и вечерние азкары, тасбих/салават (Тахаджуд по желанию).\n"
        "• 🌿 **Аль-Истикама** — *Постоянство:* фундамент Аль-Фард + чтение и слушание Корана по зову сердца.\n"
        "• 📖 **Ат-Тазкия** — *Очищение и знание:* фундамент Аль-Фард + чтение полезных книг и духовное развитие.\n"
        "• ⭐ **Аль-Ихсан** — *Вершина искренности:* гармония обязательного и добровольного поклонения, Коран, книги и благородные дела."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Аль-Фард", callback_data="rhythm_Аль-Фард")],
        [InlineKeyboardButton(text="🌿 Аль-Истикама", callback_data="rhythm_Аль-Истикама")],
        [InlineKeyboardButton(text="📖 Ат-Тазкия", callback_data="rhythm_Ат-Тазкия")],
        [InlineKeyboardButton(text="⭐ Аль-Ихсан", callback_data="rhythm_Аль-Ихсан")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_current_mode")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
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
        "Дорогая сестра! В эти дни Всевышний проявил к Вам особую заботу, освободив от обязательных молитв и постов. "
        "Это священное время отдыха, умиротворения и бережного отношения к себе. Напоминания о намазах временно отключены, чтобы Ваше сердце могло полностью расслабиться.\n\n"
        "Ваш духовный прогресс находится в абсолютной безопасности. Если почувствуете внутренний отклик, Вы всегда можете произносить зикры и салаваты, "
        "слушать или читать Коран (наизусть или с экрана, не касаясь мусхафа), а также уделять время чтению книг, прогулкам или мягкой активности.\n\n"
        "Позвольте себе этот отдых с чистой душой. Аллах видит Ваше стремление и любит каждый Ваш вдох 🤍."
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
        await callback.bot.unpin_all_chat_messages(chat_id=callback.message.chat.id)
    except Exception:
        try:
            await callback.message.unpin()
        except Exception:
            pass
        
    text = (
        "✨ **С возвращением к молитве, дорогая сестра!** 🤍\n\n"
        "Позади дни отдыха, подаренные Всевышним. Теперь Ваше сердце снова готово к предстоянию перед Ним.\n\n"
        "Примите полное омовение (гусль), обновите свое намерение и совершите этот первый намаз из наилучшего состояния — с трепетом, любовью и искренней надеждой на Его довольство и милость.\n\n"
        "Напоминания о намазах снова бережно включены. Пусть каждый Ваш поклон будет источником света и мира в душе 🌿."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏙 Сменить город", callback_data="change_city")],
        [InlineKeyboardButton(text="🌱 Сменить режим", callback_data="change_rhythm_start")],
        [InlineKeyboardButton(text="🌸 Включить деликатную паузу", callback_data="set_pause_special")]
    ])
    try: await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest: pass
    await callback.answer()

@router.callback_query(F.data.startswith("evening_mood_"))
async def process_evening_mood(callback: types.CallbackQuery):
    mood = callback.data.split("_")[2]
    if mood == "good":
        text = "Альхамдулиллах! Пусть этот внутренний свет и благодать сопровождают Вас и в новом дне 🤍."
    elif mood == "neutral":
        text = "Тихий и умиротворенный день полон скрытой мудрости и милости Творца 🤍."
    else:
        text = "Аллах видит Ваше терпение, каждую трудность и искренний труд сердца. Отдохните, ведь даже малое обращение к Нему в этот час ценно и любимо 🤍."
    
    try:
        await callback.message.edit_text(text, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

async def background_scheduler(bot: Bot):
    reminders_pool = [
        ("📖 **Аят из Корана:**\n«Воистину, намаз предписан верующим в определенное время» (сура Ан-Ниса, 103).", "ayat"),
        ("🌹 **Хадис Пророка ﷺ:**\n«Первое, о чем будет спрошен раб в Судный день — это намаз. Если он будет в порядке, то преуспеет и спасется...»", "hadith"),
        ("📜 **История из жизни пророков:**\nПророк Ибрахим (мир ему) обращался к Всевышнему: «Господи! Сделай меня и мое потомство совершающими намаз...»", "prophet_story"),
        ("✨ **Предание о сподвижниках:**\nСподвижники спешили к намазу с трепетом в сердце, чувствуя себя гостями перед Великим Царем миров.", "companion_story")
    ]

    while True:
        try:
            now = get_local_now()
            current_time_str = now.strftime("%H:%M")
            current_time_minutes = now.hour * 60 + now.minute
            today = now.strftime("%Y-%m-%d")
            today_dt = datetime.strptime(today, "%Y-%m-%d")
            is_friday = (now.weekday() == 4)
            
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, username, first_name, city, mode, rhythm, rhythm_start_date, latitude, longitude FROM users WHERE onboarding_completed = 1")
            users = cursor.fetchall()
            
            for user_id, username, first_name, city, mode, rhythm, r_start_date, lat, lon in users:
                user_disp_name = first_name if first_name else (f"@{username}" if username else "уважаемый(ая)")
                
                if current_time_str == "12:00" and r_start_date:
                    try:
                        start_dt = datetime.strptime(r_start_date, "%Y-%m-%d")
                        days_passed = (today_dt - start_dt).days
                        if days_passed in [40, 60, 90, 365]:
                            cursor.execute("SELECT 1 FROM notification_log WHERE user_id = ? AND date = ? AND prayer_key = ? AND notification_type = 'milestone'", (user_id, today, f"milestone_{days_passed}"))
                            if not cursor.fetchone():
                                milestone_text = (
                                    f"✨ **Машаллах, {user_disp_name}!** ✨\n\n"
                                    f"Прошло ровно **{days_passed} дней** Вашего постоянства в ритме **«{rhythm}»**.\n\n"
                                    "Труды и стойкость Вашего сердца — это благословенный дар. "
                                    "Чувствуете ли Вы внутреннюю готовность сделать мягкий шаг к следующей ступени роста или желаете продолжить текущий умиротворенный ритм?"
                                )
                                markup = InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="🌱 Сменить духовный ритм", callback_data="change_rhythm_start")],
                                    [InlineKeyboardButton(text="🤍 Сохранить текущий ритм", callback_data="back_to_current_mode")]
                                ])
                                await bot.send_message(user_id, milestone_text, reply_markup=markup, parse_mode="Markdown")
                                cursor.execute("INSERT OR IGNORE INTO notification_log (user_id, date, prayer_key, notification_type) VALUES (?, ?, ?, 'milestone')", (user_id, today, f"milestone_{days_passed}"))
                                conn.commit()
                    except Exception as e:
                        logging.error(f"Milestone error: {e}")

                if current_time_str == "13:00":
                    cursor.execute("""
                        SELECT COUNT(*) FROM daily_progress 
                        WHERE user_id = ? AND (quran != '' OR books > 0 OR steps > 0 OR sport > 0 OR tasbih > 0 OR salawat > 0 OR fajr_done > 0 OR dhuhr_done > 0 OR asr_done > 0 OR maghrib_done > 0 OR isha_done > 0)
                        AND date >= ?
                    """, (user_id, (today_dt - timedelta(days=3)).strftime("%Y-%m-%d")))
                    activity_count = cursor.fetchone()[0]
                    
                    if activity_count == 0:
                        cursor.execute("SELECT 1 FROM notification_log WHERE user_id = ? AND date = ? AND prayer_key = 'care_3days' AND notification_type = 'inactivity'", (user_id, today))
                        if not cursor.fetchone():
                            care_text = (
                                f"🌙 **Мир Вам и благословение Всевышнего, {user_disp_name}!**\n\n"
                                "Мы заметили, что в последние три дня в Вашем духовном дневнике тишина. Надеемся, что с Вашим здоровьем и близкими всё в порядке 🤍.\n\n"
                                "Жизнь бывает наполнена суетой и усталостью, и иногда сердце теряет прежний ритм. Но помните: **намаз — это Ваша главная опора и свет, соединяющий с Творцом**. Упущение молитвы ослабляет душу, однако Всевышний всегда ждёт Вашего возвращения.\n\n"
                                "Если Вы пропустили молитву или почувствовали усталость — просто сделайте омовение прямо сейчас и встаньте на коврик. Один искренний поклон способен вернуть в сердце утраченный мир и сакину 🌿."
                            )
                            markup = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="⏰ Время намазов", callback_data="prayer"), InlineKeyboardButton(text="📿 Поминания", callback_data="back_to_duas")]
                            ])
                            try:
                                await bot.send_message(user_id, care_text, reply_markup=markup, parse_mode="Markdown")
                                cursor.execute("INSERT OR IGNORE INTO notification_log (user_id, date, prayer_key, notification_type) VALUES (?, ?, 'care_3days', 'inactivity')", (user_id, today))
                                conn.commit()
                            except Exception as e:
                                logging.error(f"Failed to send 3-day care reminder: {e}")

                if is_friday and current_time_str == "08:00":
                    cursor.execute("SELECT 1 FROM notification_log WHERE user_id = ? AND date = ? AND prayer_key = 'friday_reminder' AND notification_type = 'friday'", (user_id, today))
                    if not cursor.fetchone():
                        friday_text = (
                            "✨ **Благословенная пятница (Джумуа)** ✨\n\n"
                            "Пусть этот день наполнит Ваше сердце светом и баракатом!\n"
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

                if current_time_str == "21:30":
                    cursor.execute("SELECT 1 FROM notification_log WHERE user_id = ? AND date = ? AND prayer_key = 'evening_mood' AND notification_type = 'prompt'", (user_id, today))
                    if not cursor.fetchone():
                        mood_text = "🌙 **Вечерний вдох**\n\nКак чувствует себя Ваше сердце сегодня?"
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
                        p_h, p_m = map(int, p_time_str.split(":"))
                        p_total_minutes = p_h * 60 + p_m
                    except ValueError:
                        continue
                    
                    # 1. Уведомление за 5 минут до намаза (надежный минутный диапазон)
                    if current_time_minutes >= (p_total_minutes - 5) and current_time_minutes < p_total_minutes:
                        cursor.execute("""
                            SELECT 1 FROM notification_log 
                            WHERE user_id = ? AND date = ? AND prayer_key = ? AND notification_type = '5min'
                        """, (user_id, today, p_key))
                        if not cursor.fetchone():
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

                    # 2. Наступление точного времени намаза
                    if current_time_minutes >= p_total_minutes and current_time_minutes < (p_total_minutes + 20):
                        cursor.execute("""
                            SELECT 1 FROM notification_log 
                            WHERE user_id = ? AND date = ? AND prayer_key = ? AND notification_type = 'exact'
                        """, (user_id, today, p_key))
                        if not cursor.fetchone():
                            exact_text = f"⏰ **Время намаза {p_name} наступило.** Пусть Всевышний примет Ваше поклонение и дарует мир сердцу 🤍."
                            markup = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text="🤍 Альхамдулиллах", callback_data=f"toggle_p_{p_key}")]
                            ])
                            try:
                                await bot.send_message(user_id, exact_text, reply_markup=markup, parse_mode="Markdown")
                                cursor.execute("INSERT OR IGNORE INTO notification_log (user_id, date, prayer_key, notification_type) VALUES (?, ?, 'exact')", (user_id, today, p_key))
                                conn.commit()
                            except Exception as e:
                                logging.error(f"Failed to send exact time reminder: {e}")

                    # 3. Напоминание через 20 минут, если намаз не отмечен
                    if current_time_minutes >= (p_total_minutes + 20):
                        cursor.execute(f"SELECT {p_done_col} FROM daily_progress WHERE user_id = ? AND date = ?", (user_id, today))
                        p_val = cursor.fetchone()
                        if p_val and p_val[0] == 0:
                            cursor.execute("""
                                SELECT 1 FROM notification_log 
                                WHERE user_id = ? AND date = ? AND prayer_key = ? AND notification_type = 'plus20'
                            """, (user_id, today, p_key))
                            if not cursor.fetchone():
                                repeat_text = f"🌿 **Тихое напоминание о намазе {p_name}:**\nЕсли Вы ещё не совершили молитву — сейчас благословенное время, чтобы сделать омовение и уделить несколько минут предстоянию перед Всевышним 🤍."
                                markup = InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text="🤍 Альхамдулиллах", callback_data=f"toggle_p_{p_key}")]
                                ])
                                try:
                                    await bot.send_message(user_id, repeat_text, reply_markup=markup, parse_mode="Markdown")
                                    cursor.execute("INSERT OR IGNORE INTO notification_log (user_id, date, prayer_key, notification_type) VALUES (?, ?, 'plus20')", (user_id, today, p_key))
                                    conn.commit()
                                except Exception as e:
                                    logging.error(f"Failed to send repeat reminder: {e}")

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
