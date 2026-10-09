import asyncio
import logging
import sqlite3
from datetime import datetime
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

def get_today_str():
    return datetime.now().strftime("%Y-%m-%d")

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

router = Router()

def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏰ Время намазов"), KeyboardButton(text="📿 Поминания и дуа")],
            [KeyboardButton(text="📊 Мой путь"), KeyboardButton(text="⛳ Активность")],
            [KeyboardButton(text="⚙️ Актуальный режим")]
        ],
        resize_keyboard=True
    )

def get_next_prayer():
    current_time_str = datetime.now().strftime("%H:%M")
    prayers = [
        ("Фаджр", "04:40"),
        ("Восход солнца", "06:19"),
        ("Зухр", "12:35"),
        ("Аср", "15:52"),
        ("Магриб", "18:50"),
        ("Иша", "20:31")
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
        f"• Фаджр: 04:40\n"
        f"• Восход солнца: 06:19\n"
        f"• Зухр: 12:35\n"
        f"• Аср: 15:52\n"
        f"• Магриб: 18:50\n"
        f"• Иша: 20:31\n\n"
        f"«Воистину, намаз предписан верующим в определенное время»."
    )
    await message.answer(text, parse_mode="Markdown")

@router.message(F.text == "📿 Поминания и дуа")
async def cmd_duas(message: types.Message):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Тасбих (Счетчик)", callback_data="tasbih_inc")],
        [InlineKeyboardButton(text="🌹 Салават", callback_data="salawat_inc")],
        [InlineKeyboardButton(text="☀️ Утренние азкары", callback_data="morning_adhkar_full")],
        [InlineKeyboardButton(text="🌙 Вечерние азкары", callback_data="evening_adhkar_full")]
    ])
    await message.answer("📿 **Поминания и дуа**\n\nВыберите нужный раздел:", reply_markup=markup, parse_mode="Markdown")

@router.callback_query(F.data == "back_to_duas")
async def back_to_duas(callback: types.CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Тасбих (Счетчик)", callback_data="tasbih_inc")],
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
    
    text = f"📿 **Счетчик Тасбиха**\n\nПовторяйте зикр с искренностью в сердце.\n\nТекущий счет: **{count}**"
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
        "«Аллаху ля иляха илля хуваль хайюль кайюм, не берет Его ни дремота, ни сон...»\n\n"
        "2. **Три последние суры (по 3 раза):**\n"
        "Сура «Аль-Ихляс», «Аль-Фаляк», «Ан-Нас».\n\n"
        "3. **Формула начала утра:**\n"
        "«Асбахна ва асбах аль-мульку ли-Ллях, ва-ль-хамду ли-Ллях...»\n\n"
        "4. **Сайид аль-истигфар:**\n"
        "«Аллахумма Анта Рабби, ля иляха илля Анта, сотворил меня, и я Твой раб...»"
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
        "Сура «Аль-Ихляс», «Аль-Фаляк», «Ан-Нас».\n\n"
        "3. **Формула начала вечера:**\n"
        "«Амсайна ва амса аль-мульку ли-Ллях, ва-ль-хамду ли-Ллях...»"
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

@router.message(F.text == "⛳ Активность")
@router.callback_query(F.data == "add_activity_menu")
async def add_activity_menu(event: types.Message | types.CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Коран", callback_data="act_quran"), InlineKeyboardButton(text="📚 Книги", callback_data="act_books")],
        [InlineKeyboardButton(text="👣 Шаги", callback_data="act_steps"), InlineKeyboardButton(text="⚽ Спорт", callback_data="act_sport")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_main")]
    ])
    if isinstance(event, types.CallbackQuery):
        try:
            await event.message.edit_text("⛳ **Выберите категорию для записи активности:**", reply_markup=markup, parse_mode="Markdown")
        except TelegramBadRequest:
            pass
        await event.answer()
    else:
        await event.answer("⛳ **Выберите категорию для записи активности:**", reply_markup=markup, parse_mode="Markdown")

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery):
    await callback.message.answer("Главное меню:", reply_markup=get_main_keyboard())
    try:
        await callback.message.delete()
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
    cursor.execute("SELECT mode, pause_reason FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    mode = row[0] if row else "active"
    reason = row[1] if row and len(row) > 1 else ""
    
    if mode == "pause":
        text = (
            f"⏸ **Деликатная пауза активна ({reason})**\n\n"
            "Уведомления временно приостановлены для вашего комфорта. При этом ведение учета (Коран, книги, шаги, спорт, тасбих, салават) полностью доступно. Ваш прогресс и серия дней в абсолютной безопасности 🤍."
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Сменить причину", callback_data="pause_reasons")],
            [InlineKeyboardButton(text="▶️ Восстановить режим и завершить паузу", callback_data="end_pause")]
        ])
    else:
        text = (
            "🤍 **Альхамдулиллах, намерение оформлено. Ритм «Аль-Фард» бережно настроен.**\n\n"
            "Пусть этот путь принесет в ваше сердце свет, баракат и глубокую сакину.\n\n"
            "Панель внизу всегда рядом, чтобы тихо и деликатно сопровождать вас изо дня в день."
        )
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏸ Включить деликатную паузу", callback_data="pause_reasons")]
        ])
        
    await message.answer(text, reply_markup=markup, parse_mode="Markdown")

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
    cursor.execute("INSERT OR REPLACE INTO users (user_id, mode, pause_reason) VALUES (?, 'pause', ?)", (user_id, reason))
    conn.commit()
    conn.close()
    
    text = (
        f"⏸ **Деликатная пауза: {reason}**\n\n"
        "Иногда душа нуждается в паузе от мирской суеты, чтобы собраться с силами. Но помните: истинный покой и исцеление сердца обретаются лишь в поминании Всевышнего («Воистину, поминанием Аллаха успокаиваются сердца», сура Ар-Рад, 28).\n\n"
        "Ваш прогресс и путь постоянства под надежной защитой 🤍."
    )
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
    cursor.execute("INSERT OR REPLACE INTO users (user_id, mode, pause_reason) VALUES (?, 'active', NULL)", (user_id,))
    conn.commit()
    conn.close()
    
    try:
        await callback.message.edit_text("✨ **С возвращением!**\nРежим паузы завершен, ваш активный путь продолжается с новыми силами 🤍.", parse_mode="Markdown")
    except TelegramBadRequest:
        pass
    await callback.answer()

import os

async def main():
    init_db()
    logging.basicConfig(level=logging.INFO)
    
    # Получаем токен из переменной окружения Render
    token = os.getenv("BOT_TOKEN")
    if not token:
        logging.error("Не найден токен бота! Проверьте вкладку Environment на Render.")
        return
        
    bot = Bot(token=token)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
