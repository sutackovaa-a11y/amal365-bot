import os
import logging
import sqlite3
import asyncio
from datetime import datetime, timedelta
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
        resize_keyboard=True
    )

PRAYER_TIMES = {
    "Фаджр": "05:03",
    "Восход солнца": "06:54",
    "Зухр": "12:30",
    "Аср": "15:19",
    "Магриб": "18:04",
    "Иша": "19:48",
    "Тахаджуд": "03:30"
}

def get_next_prayer():
    local_now = get_local_now()
    current_time_str = local_now.strftime("%H:%M")
    # Основные намазы для расчета ближайшего
    main_prayers = [
        ("Фаджр", "05:03"),
        ("Восход солнца", "06:54"),
        ("Зухр", "12:30"),
        ("Аср", "15:19"),
        ("Магриб", "18:04"),
        ("Иша", "19:48")
    ]
    next_prayer = main_prayers[0][0]
    for name, p_time in main_prayers:
        if current_time_str < p_time:
            next_prayer = name
            break
    else:
        next_prayer = main_prayers[0][0]
    return next_prayer

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
            f"🏙 **Введите ваш город**\n\nВы выбрали: **{country}**.\n\nНапишите название вашего населенного пункта на кириллице (например: *Нерюнгри, Бишкек, Казань, Алматы*):",
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
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET city = ? WHERE user_id = ?", (city_name, user_id))
    conn.commit()
    conn.close()
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Аль-Фард (5 намазов, салават, зикр)", callback_data="rhythm_Аль-Фард")],
        [InlineKeyboardButton(text="🌿 Аль-Истикама (+ Тахаджуд, Коран)", callback_data="rhythm_Аль-Истикама")],
        [InlineKeyboardButton(text="📖 Ат-Тазкия (+ Чтение книг)", callback_data="rhythm_Ат-Тазкия")],
        [InlineKeyboardButton(text="⭐ Аль-Ихсан (Полный глубокий комплекс)", callback_data="rhythm_Аль-Ихсан")]
    ])
    await state.clear()
    await message.answer(
        f"✅ Город **{city_name}** успешно сохранен!\n\n✨ **Выберите ваш режим сопровождения**\n\nКаждый ритм создан с заботой о вашем сердце:",
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
        "Пусть этот путь принесет в ваше сердце свет, баракат и глубокую сакину (умиротворение).\n\n"
        "Здесь нет места гонке и тревоге — только вы, ваши искренние стремления и милость Всевышнего.\n\n"
        "Панель внизу всегда рядом, чтобы тихо и деликатно сопровождать вас изо дня в день."
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.message.answer("Главное меню активировано:", reply_markup=get_main_keyboard())
    await callback.answer()

# === НАМАЗЫ И ОТМЕТКИ ===
@router.message(F.text == "⏰ Время намазов")
async def cmd_prayer_times(message: types.Message):
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT city FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    city = row[0] if row else "Нерюнгри"
    
    next_p = get_next_prayer()
    
    text = (
        f"🕌 **Время намазов для г. {city}**\n\n"
        f"⏳ Ближайший намаз: **{next_p}**\n\n"
        f"• Фаджр: {PRAYER_TIMES['Фаджр']}\n"
        f"• Восход солнца: {PRAYER_TIMES['Восход солнца']}\n"
        f"• Зухр: {PRAYER_TIMES['Зухр']}\n"
        f"• Аср: {PRAYER_TIMES['Аср']}\n"
        f"• Магриб: {PRAYER_TIMES['Магриб']}\n"
        f"• Иша: {PRAYER_TIMES['Иша']}\n"
        f"• Тахаджуд (ночной рубеж): {PRAYER_TIMES['Тахаджуд']}\n\n"
        f"«Воистину, намаз предписан верующим в определенное время»."
    )
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить намазы", callback_data="mark_prayers_menu")]
    ])
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")

@router.callback_query(F.data == "mark_prayers_menu")
async def mark_prayers_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT fajr_done, dhuhr_done, asr_done, maghrib_done, isha_done 
        FROM daily_progress WHERE user_id = ? AND date = ?
    """, (user_id, today))
    row = cursor.fetchone()
    conn.close()
    
    f, d, a, m, i = row if row else (0, 0, 0, 0, 0)
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("✅ Фаджр" if f else "⬜ Фаджр"), callback_data="toggle_p_fajr"),
         InlineKeyboardButton(text=("✅ Зухр" if d else "⬜ Зухр"), callback_data="toggle_p_dhuhr")],
        [InlineKeyboardButton(text=("✅ Аср" if a else "⬜ Аср"), callback_data="toggle_p_asr"),
         InlineKeyboardButton(text=("✅ Магриб" if m else "⬜ Магриб"), callback_data="toggle_p_maghrib")],
        [InlineKeyboardButton(text=("✅ Иша" if i else "⬜ Иша"), callback_data="toggle_p_isha")]
    ])
    try:
        await callback.message.edit_text("🕌 **Отметка выполнения намазов на сегодня:**", reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("toggle_p_"))
async def toggle_prayer(callback: types.CallbackQuery):
    p_name = callback.data.split("_")[2]
    user_id = callback.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    
    col_map = {
        "fajr": "fajr_done",
        "dhuhr": "dhuhr_done",
        "asr": "asr_done",
        "maghrib": "maghrib_done",
        "isha": "isha_done"
    }
    col = col_map.get(p_name)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f"SELECT {col} FROM daily_progress WHERE user_id = ? AND date = ?", (user_id, today))
    val = cursor.fetchone()[0]
    new_val = 0 if val else 1
    cursor.execute(f"UPDATE daily_progress SET {col} = ? WHERE user_id = ? AND date = ?", (new_val, user_id, today))
    conn.commit()
    
    cursor.execute("""
        SELECT fajr_done, dhuhr_done, asr_done, maghrib_done, isha_done 
        FROM daily_progress WHERE user_id = ? AND date = ?
    """, (user_id, today))
    f, d, a, m, i = cursor.fetchone()
    conn.close()
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=("✅ Фаджр" if f else "⬜ Фаджр"), callback_data="toggle_p_fajr"),
         InlineKeyboardButton(text=("✅ Зухр" if d else "⬜ Зухр"), callback_data="toggle_p_dhuhr")],
        [InlineKeyboardButton(text=("✅ Аср" if a else "⬜ Аср"), callback_data="toggle_p_asr"),
         InlineKeyboardButton(text=("✅ Магриб" if m else "⬜ Магриб"), callback_data="toggle_p_maghrib")],
        [InlineKeyboardButton(text=("✅ Иша" if i else "⬜ Иша"), callback_data="toggle_p_isha")]
    ])
    try:
        await callback.message.edit_reply_markup(reply_markup=markup)
    except TelegramBadRequest:
        pass
    
    if new_val == 1:
        await callback.answer("Альхамдулиллах! Намаз зафиксирован 🤍\n\n💡 Если хотите наполнить сердце дополнительным светом, загляните в раздел «📿 Поминания и дуа» для зикра или салаватов.", show_alert=True)
    else:
        await callback.answer("Статус намаза обновлен! 🤍")

# === ПОМИНАНИЯ И ДУА (Свободные счетчики) ===
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
    
    if action == "inc":
        count += 1
    elif action == "reset":
        count = 0
        
    cursor.execute("UPDATE daily_progress SET tasbih = ? WHERE user_id = ? AND date = ?", (count, user_id, today))
    conn.commit()
    conn.close()
    
    text = f"📿 **Тасбих**\n\nПовторяйте зикр с искренностью в сердце.\n\nТекущий счет: **{count}**"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Нажать (+1)", callback_data="tasbih_inc")],
        [InlineKeyboardButton(text="🔄 Сбросить", callback_data="tasbih_reset")],
        [InlineKeyboardButton(text="⬅️ К выбору поминаний", callback_data="back_to_duas")]
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
    
    if action == "inc":
        count += 1
    elif action == "reset":
        count = 0
        
    cursor.execute("UPDATE daily_progress SET salawat = ? WHERE user_id = ? AND date = ?", (count, user_id, today))
    conn.commit()
    conn.close()
    
    text = f"🌹 **Салават Пророку ﷺ**\n\n«Поистине, Аллах и Его ангелы благословляют Пророка...»\n\nТекущий счет: **{count}**"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Нажать (+1)", callback_data="salawat_inc")],
        [InlineKeyboardButton(text="🔄 Сбросить", callback_data="salawat_reset")],
        [InlineKeyboardButton(text="⬅️ К выбору поминаний", callback_data="back_to_duas")]
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
        "1. **Аят аль-Курси (1 раз):**\n"
        "«Аллаху ля иляха илля хуваль хайюль кайюм, не берет Его ни дремота, ни сон...»\n\n"
        "2. **Три последние суры (по 3 раза):**\n"
        "Сура «Аль-Ихляс», сура «Аль-Фаляк», сура «Ан-Нас».\n\n"
        "3. **Формула начала утра:**\n"
        "«Асбахна ва асбах аль-мульку ли-Ллях...»"
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
        "1. **Аят аль-Курси (1 раз):**\n"
        "«Аллаху ля иляха илля хуваль хайюль кайюм...»\n\n"
        "2. **Три последние суры (по 3 раза):**\n"
        "Сура «Аль-Ихляс», сура «Аль-Фаляк», сура «Ан-Нас».\n\n"
        "3. **Формула начала вечера:**\n"
        "«Амсайна ва амса аль-мульку ли-Ллях...»"
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

# === МОЙ ПУТЬ И ВЕЧЕРНИЙ ЧЕК-ИН (😇, 🙂, 🥺) ===
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
        f"📚 **Книги:** {books} страниц\n"
        f"👣 **Шаги:** {steps} шагов\n"
        f"⚽ **Спорт:** {sport} минут\n"
        f"📿 **Тасбих:** {tasbih} раз\n"
        f"🌹 **Салават:** {salawat} раз\n"
        f"☀️ **Утренние азкары:** {'✅ Выполнено' if m_adhkar else 'В процессе'}\n"
        f"🌙 **Вечерние азкары:** {'✅ Выполнено' if e_adhkar else 'В процессе'}\n\n"
        "Пусть Аллах примет ваш труд! 🤍"
    )
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 История поклонения", callback_data="history_archive")],
        [InlineKeyboardButton(text="⛳ Внести активность", callback_data="add_activity_menu")]
    ])
    await message.answer(summary_text, reply_markup=markup, parse_mode="Markdown")

@router.callback_query(F.data == "history_archive")
async def history_archive(callback: types.CallbackQuery):
    text = (
        "📜 **История поклонения**\n\n"
        "Здесь хранится ваш бессрочный архив достижений за недели, месяц, год. "
        "База устроена так, что ни одно усилие, ни один зикр или шаг не стираются со временем 🤍."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к сводке", callback_data="back_to_summary")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
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
        "🕌 **Намазы:**\n"
        f"• Фаджр: {'✅' if f else '⬜'}\n"
        f"• Зухр: {'✅' if d else '⬜'}\n"
        f"• Аср: {'✅' if a else '⬜'}\n"
        f"• Магриб: {'✅' if m else '⬜'}\n"
        f"• Иша: {'✅' if i else '⬜'}\n\n"
        f"📖 **Коран:** {quran if quran else 'Не записано'}\n"
        f"📚 **Книги:** {books} страниц\n"
        f"👣 **Шаги:** {steps} шагов\n"
        f"⚽ **Спорт:** {sport} минут\n"
        f"📿 **Тасбих:** {tasbih} раз\n"
        f"🌹 **Салават:** {salawat} раз\n"
        f"☀️ **Утренние азкары:** {'✅ Выполнено' if m_adhkar else 'В процессе'}\n"
        f"🌙 **Вечерние азкары:** {'✅ Выполнено' if e_adhkar else 'В процессе'}\n\n"
        "Пусть Аллах примет ваш труд! 🤍"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 История поклонения", callback_data="history_archive")],
        [InlineKeyboardButton(text="⛳ Внести активность", callback_data="add_activity_menu")]
    ])
    try:
        await callback.message.edit_text(summary_text, reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data == "add_activity_menu")
async def add_activity_menu(callback: types.CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Коран", callback_data="act_quran"), InlineKeyboardButton(text="📚 Книги", callback_data="act_books")],
        [InlineKeyboardButton(text="👣 Шаги", callback_data="act_steps"), InlineKeyboardButton(text="⚽ Спорт", callback_data="act_sport")],
        [InlineKeyboardButton(text="⬅️ К сводке", callback_data="back_to_summary")]
    ])
    try:
        await callback.message.edit_text("⛳ **Выберите категорию для записи активности:**", reply_markup=markup, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
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
    try:
        val = int(message.text)
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
    await callback.message.answer("Введите количество шагов (например, 5000):")
    await state.set_state(ActivityForm.entering_steps)
    await callback.answer()

@router.message(ActivityForm.entering_steps)
async def save_steps(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    try:
        val = int(message.text)
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
    await callback.message.answer("Введите количество минут спорта (например, 30):")
    await state.set_state(ActivityForm.entering_sport)
    await callback.answer()

@router.message(ActivityForm.entering_sport)
async def save_sport(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    try:
        val = int(message.text)
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

# Обработка вечернего чек-ина (смайлики 😇, 🙂, 🥺)
@router.callback_query(F.data.startswith("evening_mood_"))
async def process_evening_mood(callback: types.CallbackQuery):
    mood = callback.data.split("_")[2]
    
    if mood == "good":
        text = "Альхамдулиллах! Сегодня вы прошли этот путь с благодарением в сердце. Каждое ваше усилие записано у Творца, и пусть этот свет сопровождает вас и завтра 🤍."
    elif mood == "neutral":
        text = "Тихий и спокойный день тоже полон скрытой мудрости. Главное — ваше сердце помнит о Нем, и каждое малое движение навстречу милости Всевышнего ценно 🤍."
    else: # hard / 🥺
        text = "Даже в самые сложные и уставшие моменты вы не теряете связь со своим Творцом. Аллах видит ваше терпение и труд. Позвольте себе отдохнуть, ведь искреннее обращение к Нему в усталости выше тысяч слов 🤍."
        
    try:
        await callback.message.edit_text(text, parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

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
            "🌸 **ДЕЛИКАТНАЯ ПАУЗА АКТИВНА (Особенные дни)**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Дорогая сестра! В эти дни Всевышний сам освободил тебя от ряда обязанностей по Мудрости Своей, проявив к тебе особую милость и заботу. Это время не упущения, а особого состояния созерцания, душевного тепла и отдыха.\n\n"
            "💡 **Что можно делать в этот период:**\n"
            "• Чтение Благородного Корана наизусть или с экрана телефона/планшета (не касаясь физического мусхафа).\n"
            "• Прослушивание Корана с трепетом в сердце.\n"
            "• Обильное поминание Аллаха (зикр), тасбих и салават Пророку ﷺ.\n"
            "• Искренние дуа и мольбы к Творцу.\n\n"
            "Ваш прогресс и серия дней в абсолютной безопасности."
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏙 Изменить город", callback_data="change_city")],
            [InlineKeyboardButton(text="▶️ Завершить паузу и вернуться в ритм", callback_data="end_pause")]
        ])
    else:
        text = (
            f"⚙️ **Актуальный режим**\n\n"
            f"🏙 Текущий город: **{city}**\n"
            f"🌱 Духовный ритм: **{rhythm}**\n"
            f"✨ Статус: **Активный ритм**\n\n"
            "Вы находитесь в гармоничном потоке ежедневного поклонения и заботы о себе. Пусть каждый шаг на этом пути приносит свет вашему сердцу 🤍."
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏙 Изменить город", callback_data="change_city")],
            [InlineKeyboardButton(text="🌸 Включить деликатную паузу", callback_data="set_pause_special")]
        ])
        
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")

@router.callback_query(F.data == "change_city")
async def change_city_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название вашего города на кириллице (например, Нерюнгри, Москва, Бишкек):")
    await state.set_state(ActivityForm.updating_city)
    await callback.answer()

@router.message(ActivityForm.updating_city)
async def save_city_update(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    city_name = message.text.strip()
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET city = ? WHERE user_id = ?", (city_name, user_id))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"Город успешно изменен на: **{city_name}** 🤍", parse_mode="Markdown", reply_markup=get_main_keyboard())

@router.callback_query(F.data == "set_pause_special")
async def set_pause_special(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET mode = 'pause' WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    text = (
        "🌸 **ДЕЛИКАТНАЯ ПАУЗА АКТИВНА (Особенные дни)**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Дорогая сестра! В эти дни Всевышний проявил к тебе особую заботу. Это время созерцания, душевного тепла и отдыха.\n\n"
        "💡 **Что поддержит вас:**\n"
        "• Чтение Корана наизусть или с экрана (не касаясь мусхафа).\n"
        "• Прослушивание благородного Корана.\n"
        "• Обильный зикр, тасбих, салават и искренние дуа.\n\n"
        "Ваш прогресс надежно защищен."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Завершить паузу", callback_data="end_pause")]
    ])
    try:
        await callback.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
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
        await callback.message.edit_text("✨ **С возвращением!**\nРежим паузы завершен, ваш активный путь продолжается с новыми силами 🤍.", parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

# === ФОНОВЫЙ ПУЛЬС: НАМАЗЫ, ХАДИСЫ, ТАХАДЖУД И ВЕЧЕРНИЙ ЧЕК-ИН ===
async def background_scheduler(bot: Bot):
    while True:
        try:
            now = get_local_now()
            current_time_str = now.strftime("%H:%M")
            today = now.strftime("%Y-%m-%d")
            weekday = now.weekday() # 4 - пятница (Джума)
            
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, mode FROM users WHERE onboarding_completed = 1")
            users = cursor.fetchall()
            
            for user_id, mode in users:
                if mode == "pause":
                    continue
                
                ensure_daily_record(user_id)
                
                prayer_keys = [
                    ("Фаджр", "fajr", "fajr_done"),
                    ("Зухр", "dhuhr", "dhuhr_done"),
                    ("Аср", "asr", "asr_done"),
                    ("Магриб", "maghrib", "maghrib_done"),
                    ("Иша", "isha", "isha_done")
                ]
                
                for p_name, p_key, p_done_col in prayer_keys:
                    p_time_str = PRAYER_TIMES[p_name]
                    p_dt = datetime.strptime(p_time_str, "%H:%M")
                    
                    minus_5 = (p_dt - timedelta(minutes=5)).strftime("%H:%M")
                    plus_20 = (p_dt + timedelta(minutes=20)).strftime("%H:%M")
                    
                    # 1. Напоминание за 5 минут с нейтральными глубокими текстами, аятами и хадисами
                    if current_time_str == minus_5:
                        cursor.execute("""
                            SELECT 1 FROM notification_log 
                            WHERE user_id = ? AND date = ? AND prayer_key = ? AND notification_type = '5min'
                        """, (user_id, today, p_key))
                        if not cursor.fetchone():
                            if weekday == 4: # Пятница (Джума)
                                sense_text = (
                                    f"🕌 **Приближается благословенный намаз: {p_name}** (через 5 минут).\n\n"
                                    "✨ *Пятница (Джума):* Пророк ﷺ сказал:\n"
                                    "«Поистине, лучший из ваших дней — это пятница... Чаще призывайте на меня благословения в этот день» (Абу Дауд). Также не забудьте о чтении суры «Аль-Кяхф». Пусть эта молитва наполнит сердце светом 🤍."
                                )
                            elif p_name == "Фаджр":
                                sense_text = (
                                    "🕌 **Приближается Фаджр** (через 5 минут).\n\n"
                                    "🌅 *Особенность часа:* Пророк ﷺ сказал:\n"
                                    "«Два ракката сунны утреннего намаза лучше этого мира и всего, что в нем» (Муслим). Начните день со встречи с Творцом 🤍."
                                )
                            elif weekday % 3 == 0:
                                sense_text = (
                                    f"🕌 **Приближается время намаза: {p_name}** (через 5 минут).\n\n"
                                    "📖 *Аят о молитве:* «Воистину, намаз предписан верующим в определенное время» (сура Ан-Ниса, 103). Пусть связь со Всевышним укрепится в этот час 🤍."
                                )
                            elif weekday % 3 == 1:
                                sense_text = (
                                    f"🕌 **Приближается время намаза: {p_name}** (через 5 минут).\n\n"
                                    "✨ *История пророков:* Пророк Ибрахим (мир ему) обращался к Аллаху с мольбой:\n"
                                    "«Господи! Сделай меня и часть моего потомства совершающими намаз» (сура Ибрахим, 40) 🤍."
                                )
                            else:
                                sense_text = (
                                    f"🕌 **Приближается время намаза: {p_name}** (через 5 минут).\n\n"
                                    "🌿 *Путь сподвижников:* Сподвижники находили в намазе истинное умиротворение и защиту от мирской суеты. Пусть и для вашего сердца эта молитва станет оазисом покоя 🤍."
                                )
                            
                            try:
                                await bot.send_message(user_id, sense_text, parse_mode="Markdown")
                                cursor.execute("""
                                    INSERT OR IGNORE INTO notification_log (user_id, date, prayer_key, notification_type)
                                    VALUES (?, ?, ?, '5min')
                                """, (user_id, today, p_key))
                                conn.commit()
                            except Exception as e:
                                logging.error(f"Failed to send 5min reminder to {user_id}: {e}")
                    
                    # 2. Мягкое напоминание через 20 минут
                    if current_time_str == plus_20:
                        cursor.execute(f"SELECT {p_done_col} FROM daily_progress WHERE user_id = ? AND date = ?", (user_id, today))
                        row = cursor.fetchone()
                        is_done = row[0] if row else 0
                        
                        if not is_done:
                            cursor.execute("""
                                SELECT 1 FROM notification_log 
                                WHERE user_id = ? AND date = ? AND prayer_key = ? AND notification_type = '20min'
                            """, (user_id, today, p_key))
                            if not cursor.fetchone():
                                soft_text = (
                                    f"🌿 **Бережное напоминание о намазе ({p_name})**\n\n"
                                    "Время намаза наступило, а вы, возможно, погружены в дела. Пожалуйста, уделите несколько минут Творцу, когда появится возможность 🤍."
                                )
                                markup = InlineKeyboardMarkup(inline_keyboard=[
                                    [InlineKeyboardButton(text=f"✅ Отметить выполненным ({p_name})", callback_data=f"toggle_p_{p_key}")]
                                ])
                                try:
                                    await bot.send_message(user_id, soft_text, reply_markup=markup, parse_mode="Markdown")
                                    cursor.execute("""
                                        INSERT OR IGNORE INTO notification_log (user_id, date, prayer_key, notification_type)
                                        VALUES (?, ?, ?, '20min')
                                    """, (user_id, today, p_key))
                                    conn.commit()
                                except Exception as e:
                                    logging.error(f"Failed to send 20min reminder to {user_id}: {e}")
                
                # 3. Вопрос после Иша о Тахаджуде (в 20:30)
                if current_time_str == "20:30":
                    cursor.execute("""
                        SELECT 1 FROM notification_log 
                        WHERE user_id = ? AND date = ? AND prayer_key = 'tahajjud_prompt' AND notification_type = 'prompt'
                    """, (user_id, today))
                    if not cursor.fetchone():
                        tahajjud_text = (
                            "🌙 **Тихий час ночи...**\n\n"
                            "День подошел к концу. Если в сердце живет трепетный порыв уединиться с Творцом в тишине ночи, помните о благословенном времени Тахаджуда. Ближе к рассвету Всевышний нисходит на ближнее небо, внимая каждой искренней мольбе 🤍."
                        )
                        try:
                            await bot.send_message(user_id, tahajjud_text, parse_mode="Markdown")
                            cursor.execute("""
                                INSERT OR IGNORE INTO notification_log (user_id, date, prayer_key, notification_type)
                                VALUES (?, ?, 'tahajjud_prompt', 'prompt')
                            """, (user_id, today))
                            conn.commit()
                        except Exception as e:
                            logging.error(f"Failed to send tahajjud prompt: {e}")

                # 4. Вечерний чек-ин настроения (в 21:30)
                if current_time_str == "21:30":
                    cursor.execute("""
                        SELECT 1 FROM notification_log 
                        WHERE user_id = ? AND date = ? AND prayer_key = 'evening_mood' AND notification_type = 'prompt'
                    """, (user_id, today))
                    if not cursor.fetchone():
                        mood_text = (
                            "🌙 **Вечерний вдох**\n\n"
                            "Как чувствует себя ваше сердце сегодня? Поделитесь своим состоянием:"
                        )
                        markup = InlineKeyboardMarkup(inline_keyboard=[
                            [
                                InlineKeyboardButton(text="😇 Светло и радостно", callback_data="evening_mood_good"),
                                InlineKeyboardButton(text="🙂 Спокойно", callback_data="evening_mood_neutral"),
                                InlineKeyboardButton(text="🥺 Устала / тяжело", callback_data="evening_mood_hard")
                            ]
                        ])
                        try:
                            await bot.send_message(user_id, mood_text, reply_markup=markup, parse_mode="Markdown")
                            cursor.execute("""
                                INSERT OR IGNORE INTO notification_log (user_id, date, prayer_key, notification_type)
                                VALUES (?, ?, 'evening_mood', 'prompt')
                            """, (user_id, today))
                            conn.commit()
                        except Exception as e:
                            logging.error(f"Failed to send evening mood prompt: {e}")
            
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
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
