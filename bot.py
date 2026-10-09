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
            city TEXT DEFAULT 'Нерюнгри',
            mode TEXT DEFAULT 'active',
            pause_reason TEXT
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
            PRIMARY KEY (user_id, date)
        )
    ''')
    conn.commit()
    conn.close()

def get_local_now():
    # Местное время для Нерюнгри (UTC+9)
    return datetime.utcnow() + timedelta(hours=9)

def get_today_str():
    return get_local_now().strftime("%Y-%m-%d")

def ensure_daily_record(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    today = get_today_str()
    cursor.execute("SELECT * FROM daily_progress WHERE user_id = ? AND date = ?", (user_id, today))
    if not cursor.fetchone():
        cursor.execute("""
            INSERT INTO daily_progress (user_id, date, quran, books, steps, sport, tasbih, salawat, morning_adhkar, evening_adhkar)
            VALUES (?, ?, '', 0, 0, 0, 0, 0, 0, 0)
        """, (user_id, today))
        conn.commit()
    conn.close()

class Form(StatesGroup):
    entering_quran = State()
    entering_books = State()
    entering_steps = State()
    entering_sport = State()
    entering_city = State()

router = Router()

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏰ Время намазов"), KeyboardButton(text="📿 Поминания и дуа")],
            [KeyboardButton(text="📊 Мой путь"), KeyboardButton(text="⚙️ Актуальный режим")]
        ],
        resize_keyboard=True
    )

def get_next_prayer():
    local_now = get_local_now()
    current_time_str = local_now.strftime("%H:%M")
    
    # Актуальное расписание для Нерюнгри
    prayers = [
        ("Фаджр", "05:03"),
        ("Восход солнца", "06:54"),
        ("Зухр", "12:30"),
        ("Аср", "15:19"),
        ("Магриб", "18:04"),
        ("Иша", "19:48")
    ]
    next_prayer = prayers[0][0]
    for name, p_time in prayers:
        if current_time_str < p_time:
            next_prayer = name
            break
    else:
        next_prayer = prayers[0][0]
    return next_prayer

@router.message(F.text == "/start")
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()
    
    text = (
        "🤍 **Альхамдулиллах, намерение оформлено. Ритм «Аль-Фард» бережно настроен.**\n\n"
        "Пусть этот путь принесет в ваше сердце свет, баракат и глубокую сакину.\n\n"
        "Панель внизу всегда рядом, чтобы тихо и деликатно сопровождать вас изо дня в день."
    )
    await message.answer(text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

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
        f"• Фаджр: 05:03\n"
        f"• Восход солнца: 06:54\n"
        f"• Зухр: 12:30\n"
        f"• Аср: 15:19\n"
        f"• Магриб: 18:04\n"
        f"• Иша: 19:48\n\n"
        f"«Воистину, намаз предписан верующим в определенное время»."
    )
    await message.answer(text, parse_mode="Markdown")

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
        [InlineKeyboardButton(text="⬅️ К выбору целей", callback_data="back_to_duas")]
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
        [InlineKeyboardButton(text="⬅️ К выбору целей", callback_data="back_to_duas")]
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
        "«Аллаху ля иляха илля хуваль хайюль кайюм, не берет Его ни дремота, ни сон. Ему принадлежит то, что на небесах, и то, что на земле. Кто станет заступником пред Ним без Его дозволения? Он знает то, что было до них, и то, что будет после них...»\n\n"
        "2. **Три последние суры (по 3 раза):**\n"
        "Сура «Аль-Ихляс», сура «Аль-Фаляк», сура «Ан-Нас».\n\n"
        "3. **Формула начала утра:**\n"
        "«Асбахна ва асбах аль-мульку ли-Ллях, ва-ль-хамду ли-Ллях, ля иляха илля-ллаху вахдаху ля шарика ляh, ляhу-ль-мульку ва ляhу-ль-хамду ва хува ‘аля кулли шай-ин кадир...»\n\n"
        "4. **Сайид аль-истигфар:**\n"
        "«Аллахумма Анта Рабби, ля иляха илля Анта, сотворил меня, и я Твой раб, и я верен своему завету с Тобой...»"
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
    await callback.answer("Утренние азкары успешно зафиксированы! 🤍", show_alert=True)

@router.callback_query(F.data == "evening_adhkar_full")
async def evening_adhkar_full(callback: types.CallbackQuery):
    text = (
        "🌙 **Вечерние азкары (Полный текст)**\n\n"
        "1. **Аят аль-Курси (1 раз):**\n"
        "«Аллаху ля иляха илля хуваль хайюль кайюм...»\n\n"
        "2. **Три последние суры (по 3 раза):**\n"
        "Сура «Аль-Ихляс», сура «Аль-Фаляк», сура «Ан-Нас».\n\n"
        "3. **Формула начала вечера:**\n"
        "«Амсайна ва амса аль-мульку ли-Ллях, ва-ль-хамду ли-Ллях, ля иляха илля-ллаху вахдаху ля шарика ляh...»"
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
    await callback.answer("Вечерние азкары успешно зафиксированы! 🤍", show_alert=True)

@router.message(F.text == "📊 Мой путь")
async def cmd_my_path(message: types.Message):
    user_id = message.from_user.id
    today = get_today_str()
    ensure_daily_record(user_id)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT quran, books, steps, sport, tasbih, salawat, morning_adhkar, evening_adhkar 
        FROM daily_progress WHERE user_id = ? AND date = ?
    """, (user_id, today))
    row = cursor.fetchone()
    conn.close()
    
    quran, books, steps, sport, tasbih, salawat, m_adhkar, e_adhkar = row if row else ("", 0, 0, 0, 0, 0, 0, 0)
    
    summary_text = (
        f"📊 **Сводка дня ({today})**\n\n"
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
        SELECT quran, books, steps, sport, tasbih, salawat, morning_adhkar, evening_adhkar 
        FROM daily_progress WHERE user_id = ? AND date = ?
    """, (user_id, today))
    row = cursor.fetchone()
    conn.close()
    
    quran, books, steps, sport, tasbih, salawat, m_adhkar, e_adhkar = row if row else ("", 0, 0, 0, 0, 0, 0, 0)
    
    summary_text = (
        f"📊 **Сводка дня ({today})**\n\n"
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
    await state.set_state(Form.entering_quran)
    await callback.answer()

@router.message(Form.entering_quran)
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
    await state.set_state(Form.entering_books)
    await callback.answer()

@router.message(Form.entering_books)
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
    await state.set_state(Form.entering_steps)
    await callback.answer()

@router.message(Form.entering_steps)
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
    await state.set_state(Form.entering_sport)
    await callback.answer()

@router.message(Form.entering_sport)
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

@router.message(F.text == "⚙️ Актуальный режим")
async def cmd_current_mode(message: types.Message):
    user_id = message.from_user.id
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT city, mode, pause_reason FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    city = row[0] if row else "Нерюнгри"
    mode = row[1] if row else "active"
    reason = row[2] if row and len(row) > 2 else ""
    
    if mode == "pause":
        text = f"⏸ **Деликатная пауза активна ({reason})**\n\n"
        if reason == "Особенные дни":
            text += (
                "Дорогая сестра! В эти дни Всевышний сам освободил тебя от ряда обязанностей по Мудрости Своей, проявив к тебе особую милость и заботу. Это время не упущения, а особого состояния созерцания, душевного тепла и отдыха.\n\n"
                "💡 **Что можно делать:**\n"
                "• Искренние дуа и мольбы к Аллаху.\n"
                "• Обильное поминание (зикр), тасбих и салават Пророку ﷺ.\n"
                "• Слушание благородного Корана с трепетом в сердце.\n"
                "• Чтение полезных исламских книг и приобретение знаний.\n\n"
            )
        elif reason == "Заболела":
            text += (
                "Здоровье — это великий аманат от Аллаха. Когда тело просит отдыха и исцеления, забота о нем становится частью поклонения. Болезнь смывает тревоги и очищает душу.\n\n"
                "💡 **Поддержка:** Сосредоточьтесь на восстановлении сил. Не корите себя за паузу — ваше сердце помнит о Творце, а малейшее терпение возвышает вас пред Ним 🤍.\n\n"
            )
        elif reason == "Времени нет":
            text += (
                "Жизнь бывает насыщена заботами и делами. В периоды высокой занятости важно не выгорать, а сохранять внутренний баланс.\n\n"
                "💡 **Поддержка:** Даже в самый плотный день можно сохранить связь со Всевышним через короткий зикр в сердце и мысленную благодарность 🤍.\n\n"
            )
        else:
            text += (
                "Душе и разуму порой необходима тишина и пауза от ежедневной суеты, чтобы обрести свежие силы и вдохновение.\n\n"
                "💡 **Поддержка:** Позвольте себе этот короткий перерыв без чувства вины. Настоящее постоянство заключается в умении вовремя перевести дух 🤍.\n\n"
            )
        text += "Ваш прогресс и серия дней в абсолютной безопасности."
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏙 Изменить город", callback_data="change_city")],
            [InlineKeyboardButton(text="🔄 Сменить причину паузы", callback_data="pause_reasons")],
            [InlineKeyboardButton(text="▶️ Завершить паузу и вернуться в ритм", callback_data="end_pause")]
        ])
    else:
        text = (
            f"⚙️ **Актуальный режим**\n\n"
            f"🏙 Текущий город: **{city}**\n"
            f"✨ Статус: **Активный ритм**\n\n"
            "Вы находитесь в гармоничном потоке ежедневного поклонения и заботы о себе. Пусть каждый шаг на этом пути приносит свет вашему сердцу 🤍."
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏙 Изменить город", callback_data="change_city")],
            [InlineKeyboardButton(text="⏸ Включить деликатную паузу", callback_data="pause_reasons")]
        ])
        
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")

@router.callback_query(F.data == "change_city")
async def change_city_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите название вашего города (например, Нерюнгри, Москва, Казань):")
    await state.set_state(Form.entering_city)
    await callback.answer()

@router.message(Form.entering_city)
async def save_city(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    city_name = message.text.strip()
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET city = ? WHERE user_id = ?", (city_name, user_id))
    conn.commit()
    conn.close()
    
    await state.clear()
    await message.answer(f"Город успешно изменен на: **{city_name}** 🤍", parse_mode="Markdown", reply_markup=get_main_keyboard())

@router.callback_query(F.data == "pause_reasons")
async def pause_reasons(callback: types.CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌸 Особенные дни", callback_data="set_pause_Особенные дни")],
        [InlineKeyboardButton(text="🌿 Заболела", callback_data="set_pause_Заболела")],
        [InlineKeyboardButton(text="⏳ Времени нет", callback_data="set_pause_Времени нет")],
        [InlineKeyboardButton(text="☕ Просто отдых", callback_data="set_pause_Просто отдых")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])
    try:
        await callback.message.edit_text("Выберите причину для деликатной паузы:", reply_markup=markup)
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("set_pause_"))
async def set_pause(callback: types.CallbackQuery):
    reason = callback.data.split("_")[2]
    user_id = callback.from_user.id
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET mode = 'pause', pause_reason = ? WHERE user_id = ?", (reason, user_id))
    conn.commit()
    conn.close()
    
    text = f"⏸ **Деликатная пауза: {reason}**\n\n"
    if reason == "Особенные дни":
        text += (
            "Дорогая сестра! В эти дни Всевышний проявил к тебе особую заботу. Это время созерцания, душевного тепла и отдыха.\n\n"
            "💡 **Что поддержит вас:** дуа, зикр, тасбих, салават, слушание Корана и чтение книг.\n\n"
        )
    elif reason == "Заболела":
        text += (
            "Забота о здоровье — часть поклонения. Сосредоточьтесь на восстановлении сил, ваше сердце помнит о Творце 🤍.\n\n"
        )
    elif reason == "Времени нет":
        text += (
            "В периоды высокой занятости сохраняйте связь со Всевышним через короткий зикр в сердце и искреннее намерение 🤍.\n\n"
        )
    else:
        text += (
            "Позвольте себе этот короткий перерыв без чувства вины, чтобы продолжить путь с новыми силами 🤍.\n\n"
        )
    text += "Ваш прогресс надежно защищен."

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Сменить причину", callback_data="pause_reasons")],
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
    cursor.execute("UPDATE users SET mode = 'active', pause_reason = NULL WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    try:
        await callback.message.edit_text("✨ **С возвращением!**\nРежим паузы завершен, ваш активный путь продолжается с новыми силами 🤍.", parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.answer("Главное меню:", reply_markup=get_main_keyboard())
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await callback.answer()

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
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
