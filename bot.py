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
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
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
            INSERT INTO daily_progress (user_id, date, quran, books, steps, sport, tasbih, salawat, morning_adhkar, evening_adhkar, fajr_done, dhuhr_done, asr_done, maghrib_done, isha_done)
            VALUES (?, ?, '', 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        """, (user_id, today))
        conn.commit()
    conn.close()

async def fetch_prayer_times(lat, lon, date_str):
    url = f"https://api.aladhan.com/v1/timings/{date_str}?latitude={lat}&longitude={lon}&method=3"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    timings = data['data']['timings']
                    return {
                        "Фаджр": timings.get("Fajr", "05:00")[:5],
                        "Восход солнца": timings.get("Sunrise", "06:30")[:5],
                        "Зухр": timings.get("Dhuhr", "12:30")[:5],
                        "Аср": timings.get("Asr", "15:30")[:5],
                        "Магриб": timings.get("Maghrib", "18:00")[:5],
                        "Иша": timings.get("Isha", "19:30")[:5],
                        "Тахаджуд": "03:30"
                    }
        except Exception as e:
            logging.error(f"Error fetching prayer times: {e}")
    return {
        "Фаджр": "05:03", "Восход солнца": "06:54", "Зухр": "12:30",
        "Аср": "15:19", "Магриб": "18:04", "Иша": "19:48", "Тахаджуд": "03:30"
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
    return 42.8746, 74.5698

class OnboardForm(StatesGroup):
    entering_city = State()

class ActivityForm(StatesGroup):
    entering_quran = State()
    entering_books = State()
    entering_steps = State()
    entering_sport = State()
    updating_city = State()

router = Router()

# Главное меню ровно из 4 кнопок
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏰ Время намазов"), KeyboardButton(text="📿 Поминания и дуа")],
            [KeyboardButton(text="📊 Мой путь"), KeyboardButton(text="⚙️ Актуальный режим")]
        ],
        resize_keyboard=True
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
        await message.answer("🤍 **С возвращением в Amal365!**\nВаш духовный ритм активен.", reply_markup=get_main_keyboard(), parse_mode="Markdown")
        return

    text = (
        "Ассаляму алейкум ва рахматуллахи ва баракатух 🌙\n\n"
        "Добро пожаловать в **Amal365**.\n\n"
        "Мы бережно защищаем ваши данные и используем их исключительно для персонального сопровождения на пути к постоянству в благих делах.\n\n"
        "Пусть Аллах дарует пользу и баракат в этом пути 🤍"
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
        await callback.message.edit_text("Вы всегда можете вернуться к нам, когда будете готовы. Всего доброго! 🤍", reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data == "onboard_bismillah")
async def onboard_bismillah(callback: types.CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇰🇬 Кыргызстан", callback_data="country_Кыргызстан"), InlineKeyboardButton(text="🇷🇺 Россия", callback_data="country_Россия")],
        [InlineKeyboardButton(text="🇰🇿 Казахстан", callback_data="country_Казахстан"), InlineKeyboardButton(text="🇺🇿 Узбекистан", callback_data="country_Узбекистан")]
    ])
    try:
        await callback.message.edit_text("🌍 **Выбор страны**\n\nПожалуйста, выберите вашу страну:", reply_markup=markup, parse_mode="Markdown")
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
            f"🏙 **Введите ваш город или область**\n\nВы выбрали: **{country}**.\n\nНапишите название вашего населенного пункта на кириллице (например: *Нерюнгри, Бишкек, Ош, Алматы*):",
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
        [InlineKeyboardButton(text="🌱 Аль-Фард (5 намазов)", callback_data="rhythm_Аль-Фард")],
        [InlineKeyboardButton(text="🌿 Аль-Истикама (+ Тахаджуд)", callback_data="rhythm_Аль-Истикама")],
        [InlineKeyboardButton(text="📖 Ат-Тазкия (+ Книги)", callback_data="rhythm_Ат-Тазкия")],
        [InlineKeyboardButton(text="⭐ Аль-Ихсан (Полный)", callback_data="rhythm_Аль-Ихсан")]
    ])
    await state.clear()
    await message.answer(
        f"✅ Город **{city_name}** сохранен!\n\n✨ **Выберите ваш режим сопровождения**:",
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
        f"🤍 **Альхамдулиллах, намерение оформлено. Ритм «{rhythm}» бережно настроен.**\n\n"
        "Пусть этот путь принесет в ваше сердце свет и сакину."
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.message.answer("Главное меню активировано:", reply_markup=get_main_keyboard())
    await callback.answer()

# === КНОПКА «ВРЕМЯ НАМАЗОВ» В МЕНЮ ===
@router.message(F.text == "⏰ Время намазов")
async def cmd_prayer_times(message: types.Message):
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT city, latitude, longitude FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    city = row[0] if row else "Бишкек"
    lat = row[1] if row and row[1] else 42.8746
    lon = row[2] if row and row[2] else 74.5698
    
    today = get_today_str()
    times = await fetch_prayer_times(lat, lon, today)
    
    text = (
        f"🕌 **Расписание намазов для г. {city}**\n\n"
        f"• Тахаджуд: {times['Тахаджуд']}\n"
        f"• Фаджр: {times['Фаджр']}\n"
        f"• Восход солнца: {times['Восход солнца']}\n"
        f"• Зухр: {times['Зухр']}\n"
        f"• Аср: {times['Аср']}\n"
        f"• Магриб: {times['Магриб']}\n"
        f"• Иша: {times['Иша']}\n\n"
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

# === ПОМИНАНИЯ И ДУА (ПОЛНЫЕ ТЕКСТЫ АЗКАРОВ) ===
@router.message(F.text == "📿 Поминания и дуа")
async def cmd_duas(message: types.Message):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Тасбих", callback_data="tasbih_inc")],
        [InlineKeyboardButton(text="🌹 Салават", callback_data="salawat_inc")],
        [InlineKeyboardButton(text="☀️ Утренние азкары", callback_data="morning_adhkar_full")],
        [InlineKeyboardButton(text="🌙 Вечерние азкары", callback_data="evening_adhkar_full")]
    ])
    await message.answer("📿 **Поминания и дуа**\n\nВыберите нужный раздел:", reply_markup=markup, parse_mode="Markdown")

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
        "☀️ **Утренние азкары (Полный текст)**\n\n"
        "1. **Аят аль-Курси (сура «Аль-Бақара», 255) — 1 раз:**\n"
        "«Аллаху ля иляха илля хуваль хайюль кайюм, не берет Его ни дремота, ни сон. Ему принадлежит то, что на небесах, и то, что на земле...»\n\n"
        "2. **Три последние суры («Аль-Ихляс», «Аль-Фаляк», «Ан-Нас») — по 3 раза.**\n\n"
        "3. **Формула начала утра:**\n"
        "«Асбахна ва асбах аль-мульку ли-Ллях, ва-ль-хамду ли-Ллях, ля иляха илля-Ллаху вахдаху ля шарика ляh...»"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить как прочитанные", callback_data="mark_morning_done")],
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
        "🌙 **Вечерние азкары (Полный текст)**\n\n"
        "1. **Аят аль-Курси (сура «Аль-Бақара», 255) — 1 раз**\n\n"
        "2. **Три последние суры — по 3 раза**\n\n"
        "3. **Формула начала вечера:**\n"
        "«Амсайна ва амса аль-мульку ли-Ллях, ва-ль-хамду ли-Ллях, ля иляха илля-Ллаху вахдаху ля шарика ляh...»"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить как прочитанные", callback_data="mark_evening_done")],
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
               fajr_done, dhuhr_done, asr_done, maghrib_done, isha_done
        FROM daily_progress WHERE user_id = ? AND date = ?
    """, (user_id, today))
    row = cursor.fetchone()
    conn.close()
    
    quran, books, steps, sport, tasbih, salawat, m_adhkar, e_adhkar, f, d, a, m, i = row if row else ("", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    
    summary_text = (
        f"📊 **Сводка дня ({today})**\n\n"
        "🕌 **Намазы:**\n"
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
        "Пусть Аллах примет ваш труд! 🤍"
    )
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 История поклонения", callback_data="history_archive")],
        [InlineKeyboardButton(text="⛳ Внести активность", callback_data="add_activity_menu")]
    ])
    await message.answer(summary_text, reply_markup=markup, parse_mode="Markdown")

@router.callback_query(F.data == "history_archive")
async def history_archive(callback: types.CallbackQuery):
    text = "📜 **История поклонения**\n\nЗдесь хранится ваш бессрочный архив достижений 🤍."
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
               fajr_done, dhuhr_done, asr_done, maghrib_done, isha_done
        FROM daily_progress WHERE user_id = ? AND date = ?
    """, (user_id, today))
    row = cursor.fetchone()
    conn.close()
    quran, books, steps, sport, tasbih, salawat, m_adhkar, e_adhkar, f, d, a, m, i = row if row else ("", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    summary_text = (
        f"📊 **Сводка дня ({today})**\n\n"
        f"🕌 Намазы: Фаджр {'✅' if f else '⬜'} | Зухр {'✅' if d else '⬜'} | Аср {'✅' if a else '⬜'} | Магриб {'✅' if m else '⬜'} | Иша {'✅' if i else '⬜'}\n\n"
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
    await callback.message.answer("Введите количество минут спорта:")
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
    await message.answer(f"Записано: **{val}** минут спорта. 🤍", parse_mode="Markdown", reply_markup=get_main_keyboard())

# === АКТУАЛЬНЫЙ РЕЖИМ И ДЕЛИКАТНАЯ ПАУЗА ===
@router.message(F.text == "⚙️ Актуальный режим")
async def cmd_current_mode(message: types.Message):
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT city, mode, rhythm FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    city = row[0] if row else "Бишкек"
    mode = row[1] if row else "active"
    rhythm = row[2] if row else "Аль-Фард"
    
    if mode == "pause":
        text = (
            "🌸 **СТАТУС НАВЕРХУ: ДЕЛИКАТНАЯ ПАУЗА АКТИВНА** 🌸\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Дорогая сестра! В эти дни Всевышний проявил к тебе особую заботу. Это время созерцания и отдыха.\n\n"
            "Ваш прогресс в абсолютной безопасности."
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
    await callback.message.answer("Введите название вашего города или области на кириллице (например, Нерюнгри, Бишкек, Ош):")
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
    text = "🌸 **СТАТУС НАВЕРХУ: ДЕЛИКАТНАЯ ПАУЗА АКТИВНА** 🌸\n\nВаш прогресс надежно защищен."
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏙 Сменить город", callback_data="change_city")],
        [InlineKeyboardButton(text="🌱 Сменить режим", callback_data="change_rhythm_start")],
        [InlineKeyboardButton(text="▶️ Завершить паузу", callback_data="end_pause")]
    ])
    try: await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest: pass
    await callback.answer()

@router.callback_query(F.data == "end_pause")
async def end_pause(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET mode = 'active' WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    text = "⚙️ **Актуальный режим**\n\n✨ Режим паузы завершен 🤍."
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏙 Сменить город", callback_data="change_city")],
        [InlineKeyboardButton(text="🌱 Сменить режим", callback_data="change_rhythm_start")],
        [InlineKeyboardButton(text="🌸 Включить деликатную паузу", callback_data="set_pause_special")]
    ])
    try: await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest: pass
    await callback.answer()

# === ФОНОВЫЙ ПУЛЬС ===
async def background_scheduler(bot: Bot):
    while True:
        try:
            now = get_local_now()
            current_time_str = now.strftime("%H:%M")
            today = now.strftime("%Y-%m-%d")
            
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, mode, latitude, longitude FROM users WHERE onboarding_completed = 1")
            users = cursor.fetchall()
            
            for user_id, mode, lat, lon in users:
                if mode == "pause":
                    continue
                
                ensure_daily_record(user_id)
                prayer_times = await fetch_prayer_times(lat, lon, today)
                
                prayer_keys = [
                    ("Фаджр", "fajr", "fajr_done"),
                    ("Зухр", "dhuhr", "dhuhr_done"),
                    ("Аср", "asr", "asr_done"),
                    ("Магриб", "maghrib", "maghrib_done"),
                    ("Иша", "isha", "isha_done")
                ]
                
                for p_name, p_key, p_done_col in prayer_keys:
                    p_time_str = prayer_times.get(p_name, "12:00")
                    try:
                        p_dt = datetime.strptime(p_time_str, "%H:%M")
                    except ValueError:
                        continue
                    
                    minus_5 = (p_dt - timedelta(minutes=5)).strftime("%H:%M")
                    
                    if current_time_str == minus_5:
                        cursor.execute("""
                            SELECT 1 FROM notification_log 
                            WHERE user_id = ? AND date = ? AND prayer_key = ? AND notification_type = '5min'
                        """, (user_id, today, p_key))
                        if not cursor.fetchone():
                            sense_text = f"🕌 **Приближается время намаза: {p_name}** ({p_time_str}, через 5 минут). Пусть связь со Всевышним укрепится в этот час 🤍."
                            markup = InlineKeyboardMarkup(inline_keyboard=[
                                [InlineKeyboardButton(text=f"✅ Отметить выполненным ({p_name})", callback_data=f"toggle_p_{p_key}")]
                            ])
                            try:
                                await bot.send_message(user_id, sense_text, reply_markup=markup, parse_mode="Markdown")
                                cursor.execute("INSERT OR IGNORE INTO notification_log (user_id, date, prayer_key, notification_type) VALUES (?, ?, ?, '5min')", (user_id, today, p_key))
                                conn.commit()
                            except Exception as e:
                                logging.error(f"Failed to send reminder: {e}")
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
