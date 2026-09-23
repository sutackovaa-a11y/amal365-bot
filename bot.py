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

# Файл базы данных
DB_FILE = "bot_database.db"

# ----------------- РАБОТА С БАЗОЙ ДАННЫХ -----------------

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
            tasbih_dhikr TEXT DEFAULT 'Субханаллах (سُبْحَانَ ٱللَّهِ)'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seen_hadiths (
            user_id INTEGER,
            hadith_id TEXT,
            PRIMARY KEY (user_id, hadith_id)
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
    cursor.execute("SELECT user_id, city, mode, streak, last_completed_date, step_index, tasbih_count, tasbih_dhikr FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO users (user_id, city, mode, streak, last_completed_date, step_index, tasbih_count, tasbih_dhikr) VALUES (?, 'Нерюнгри', 'full', 0, NULL, 0, 0, 'Субханаллах (سُبْحَانَ ٱللَّهِ)')", (user_id,))
        conn.commit()
        row = (user_id, 'Нерюнгри', 'full', 0, None, 0, 0, 'Субханаллах (سُبْحَانَ ٱللَّهِ)')
    conn.close()
    return {
        "user_id": row[0],
        "city": row[1],
        "mode": row[2],
        "streak": row[3],
        "last_completed_date": row[4],
        "step_index": row[5],
        "tasbih_count": row[6],
        "tasbih_dhikr": row[7]
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
        ON CONFLICT(date) DO UPDATE SET completed_steps = ?, total_steps = ?
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

# ----------------- СПИСОК ШАГОВ И РЕЖИМЫ -----------------

ALL_STEPS = [
    {
        "id": "tahajjud",
        "title": "🌌 **Ночной намаз (Тахаджуд)**",
        "hadith": "📖 *Хадис:* «Лучший намаз после обязательных — это ночной намаз (Тахаджуд)». (Муслим)\n\n✨ *Духовность:* Время искреннего дуа, когда Аллах близок к молящимся.",
        "modes": ["basic", "spiritual", "full"]
    },
    {
        "id": "fajr",
        "title": "🌅 **Утренний намаз (Фаджр)**",
        "hadith": "📖 *Хадис:* «Тот, кто совершил утренний намаз, находится под защитой Аллаха». (Муслим)\n\n✨ *Напоминание:* 2 ракаата сунны Фаджра лучше, чем весь этот мир.",
        "modes": ["minimum", "basic", "spiritual", "full"]
    },
    {
        "id": "morning_azkar",
        "title": "☀️ **Утренние азкары (Тексты для чтения)**",
        "hadith": (
            "📜 *Основные утренние поминания:*\n\n"
            "1️⃣ **Аят аль-Курси** (Сура 2, аят 255)\n\n"
            "2️⃣ **3 Суры Защиты (по 3 раза):**\n"
            "• Сура «Аль-Ихляс»\n• Сура «Аль-Фаляк»\n• Сура «Ан-Нас»\n\n"
            "3️⃣ **Защита от вреда (3 раза):**\n"
            "«Бисми-Лляхи ллязи ля ядурру ма'асмихи шей'ун филь-арды ва ля фис-сама'и ва хувас-Сами'уль-'Алим»\n\n"
            "4️⃣ **Довольство верой (3 раза):**\n"
            "«Радыйту би-Лляхи Раббан, ва биль-Ислями динан, ва би-Мухаммадин салля-Ллаху 'аляйхи ва салляма набийян»\n\n"
            "5️⃣ **Главная молитва покаяния (Саййидуль-Истигфар):**\n"
            "«Аллахумма Анта Рабби ля иляха илля Анта, халяктани ва ана 'абдука...»\n\n"
            "6️⃣ **Прославление (100 раз):** «Субханаллахи ва бихамдихи»"
        ),
        "modes": ["spiritual", "full"]
    },
    {
        "id": "quran",
        "title": "📖 **Чтение Священного Корана**",
        "hadith": "📖 *Хадис:* «Читайте Коран, ибо в День воскрешения он придет заступником за тех, кто его читал». (Муслим)\n\n✨ *Мудрость:* Прочитайте хотя бы 1 страницу с размышлением (Тадаббур).",
        "modes": ["spiritual", "full"]
    },
    {
        "id": "salawat",
        "title": "📿 **Салават Пророку Мухаммаду ﷺ**",
        "hadith": "📖 *Хадис:* «Кто призовет на меня благословение один раз, того Аллах благословит за это десять раз». (Муслим)\n\n✨ *Практика:* Произнесите: *«Аллахумма салли 'аля Мухаммадин ва 'аля али Мухаммад»* (10 или 100 раз).",
        "modes": ["spiritual", "full"]
    },
    {
        "id": "sport",
        "title": "🏃‍♂️ **Спорт, здоровье и активность**",
        "hadith": "📖 *Хадис:* «Сильный верующий лучше и любимее Аллаху, чем слабый верующий, хотя в обоих есть благо». (Муслим)\n\n✨ *Тело и дух:* Разминка, 10 000 шагов или тренировка.",
        "modes": ["full"]
    },
    {
        "id": "dhuhr",
        "title": "🏙 **Полуденный намаз (Зухр)**",
        "hadith": "📖 *Хадис:* «Первое, за что будет спрошен раб в День суда — это его намаз». (Тирмизи)\n\n✨ *Напоминание:* Перерыв посреди дня для перезагрузки души.",
        "modes": ["minimum", "basic", "spiritual", "full"]
    },
    {
        "id": "books",
        "title": "📚 **Книги и саморазвитие**",
        "hadith": "📖 *Хадис:* «Стремление к знаниям — обязанность каждого мусульманина». (Ибн Маджа)\n\n✨ *Интеллект:* 15 минут чтения полезной книги для мышления.",
        "modes": ["full"]
    },
    {
        "id": "asr",
        "title": "🌇 **Послеполуденный намаз (Аср)**",
        "hadith": "📖 *Хадис:* «Кто упустит намаз Аср, тот словно лишился семьи и своего имущества». (Аль-Бухари)\n\n✨ *Напоминание:* Сохраняйте фокус во второй половине дня.",
        "modes": ["minimum", "basic", "spiritual", "full"]
    },
    {
        "id": "maghrib",
        "title": "🌆 **Вечерний намаз (Магриб)**",
        "hadith": "📖 *Хадис:* «Молитва — это опора религии». (Тирмизи)\n\n✨ *Благодарность:* Встречайте вечер с благодарностью Всевышнему.",
        "modes": ["minimum", "basic", "spiritual", "full"]
    },
    {
        "id": "isha",
        "title": "🌌 **Ночной намаз (Иша)**",
        "hadith": "📖 *Хадис:* «Кто совершит Иша в джамаате, словно молился половину ночи». (Муслим)\n\n✨ *Завершение:* Достойный финал обязательных поклонений дня.",
        "modes": ["minimum", "basic", "spiritual", "full"]
    },
    {
        "id": "evening_azkar",
        "title": "🌙 **Вечерние азкары (Тексты для чтения)**",
        "hadith": (
            "📜 *Основные вечерние поминания:*\n\n"
            "1️⃣ **Аят аль-Курси**\n\n"
            "2️⃣ **3 Суры Защиты (Ихляс, Фаляк, Нас — по 3 раза)**\n\n"
            "3️⃣ **Защита от зла творений (3 раза):**\n"
            "«А'узу би-калимати-Лляхит-таммати мин шарри ма халяк»\n\n"
            "4️⃣ **Приветствие вечера:**\n"
            "«Амсайна ва амсаль-мульку ли-Ллях, валь-хамду ли-Ллях...»\n\n"
            "5️⃣ **Вечернее вверение себя Аллаху:**\n"
            "«Аллахумма би-ка амсайна, ва би-ка асбахна, ва би-ка нахйа, ва би-ка намуту ва иляйкаль-масыр»\n\n"
            "6️⃣ **Прощение (100 раз):** «Астагфируллах ва атубу илейхи»"
        ),
        "modes": ["spiritual", "full"]
    },
    {
        "id": "reflection",
        "title": "🤍 **Самоанализ, Истигфар и Дуа перед сном**",
        "hadith": "📖 *Дуа:* «О Аллах, с именем Твоим я укладываюсь на бок и с именем Твоим встаю».\n\n✨ *Итог дня:* Простите всех, кто обидел вас, и спите с чистой душой.",
        "modes": ["minimum", "basic", "spiritual", "full"]
    }
]

# ----------------- РАСЧЕТ ВРЕМЕНИ И ТАЙМЗОНЫ -----------------

KNOWN_CITIES = {
    "нерюнгри": (56.6667, 124.7167),
    "neryungri": (56.6667, 124.7167),
    "бишкек": (42.8746, 74.5698),
    "якутск": (62.0355, 129.6755),
    "москва": (55.7558, 37.6173),
    "казань": (55.7887, 49.1221),
    "дубай": (25.2048, 55.2708),
    "стамбул": (41.0082, 28.9784)
}

async def get_prayer_data_with_tz(city_name: str):
    city_clean = city_name.strip().lower()
    lat, lng = None, None

    if city_clean in KNOWN_CITIES:
        lat, lng = KNOWN_CITIES[city_clean]

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

# ----------------- КЛАВИАТУРЫ И СТАРТ -----------------

class Form(StatesGroup):
    city = State()

def main_keyboard():
    kb = [
        [KeyboardButton(text="✨ Начать / Шаг дня")],
        [KeyboardButton(text="📿 Электронный Тасбих")],
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
        "minimum": "🟢 Минимум (Только 5 намазов)",
        "basic": "🌙 Базовый (5 намазов + Тахаджуд)",
        "spiritual": "🕊 Душевный рост (Коран + Азкары + Салават)",
        "full": "🚀 Полный рост (Намазы + Тахаджуд + Коран + Книги + Спорт)"
    }.get(profile['mode'], "Полный рост")

    text = (
        "🌟 **Добро пожаловать в «Амаль 365» — ваш уникальный духовный и интеллектуальный трекер!**\n\n"
        "Маленькие постоянные дела любимы Всевышним больше всего.\n\n"
        f"📍 **Город:** {profile['city']}\n"
        f"🎯 **Текущий режим:** {mode_name}\n"
        f"🔥 **Серия дней:** {profile['streak']} дн."
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=main_keyboard())

# ----------------- ЭЛЕКТРОННЫЙ ТАСБИХ -----------------

@dp.message(F.text == "📿 Электронный Тасбих")
async def show_tasbih(message: Message):
    profile = get_user_profile(message.from_user.id)
    count = profile['tasbih_count']
    dhikr = profile['tasbih_dhikr']

    text = (
        "📿 **Электронный Тасбих**\n\n"
        f"Текущее поминание:\n✨ **{dhikr}**\n\n"
        f"📊 Счёт: **{count} / 33**\n\n"
        "Нажимайте на кнопку ниже, чтобы вести счет:"
    )

    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Нажать для счета (+)", callback_data="tasbih_inc")],
        [
            InlineKeyboardButton(text="🔄 Сброс", callback_data="tasbih_reset"),
            InlineKeyboardButton(text="🎯 Цель", callback_data="tasbih_target")
        ],
        [InlineKeyboardButton(text="📖 Выбрать другое поминание", callback_data="tasbih_select")]
    ])

    await message.answer(text, parse_mode="Markdown", reply_markup=ikb)

@dp.callback_query(F.data == "tasbih_inc")
async def tasbih_inc_cb(callback: CallbackQuery):
    profile = get_user_profile(callback.from_user.id)
    count = profile['tasbih_count'] + 1
    dhikr = profile['tasbih_dhikr']
    update_user_profile(callback.from_user.id, tasbih_count=count)

    text = (
        "📿 **Электронный Тасбих**\n\n"
        f"Текущее поминание:\n✨ **{dhikr}**\n\n"
        f"📊 Счёт: **{count} / 33**\n\n"
        "Нажимайте на кнопку ниже, чтобы вести счет:"
    )

    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Нажать для счета (+)", callback_data="tasbih_inc")],
        [
            InlineKeyboardButton(text="🔄 Сброс", callback_data="tasbih_reset"),
            InlineKeyboardButton(text="🎯 Цель", callback_data="tasbih_target")
        ],
        [InlineKeyboardButton(text="📖 Выбрать другое поминание", callback_data="tasbih_select")]
    ])

    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=ikb)
    except Exception:
        pass
    await callback.answer(f"+1 ({count})")

@dp.callback_query(F.data == "tasbih_reset")
async def tasbih_reset_cb(callback: CallbackQuery):
    profile = get_user_profile(callback.from_user.id)
    dhikr = profile['tasbih_dhikr']
    update_user_profile(callback.from_user.id, tasbih_count=0)

    text = (
        "📿 **Электронный Тасбих**\n\n"
        f"Текущее поминание:\n✨ **{dhikr}**\n\n"
        "📊 Счёт: **0 / 33**\n\n"
        "Нажимайте на кнопку ниже, чтобы вести счет:"
    )

    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Нажать для счета (+)", callback_data="tasbih_inc")],
        [
            InlineKeyboardButton(text="🔄 Сброс", callback_data="tasbih_reset"),
            InlineKeyboardButton(text="🎯 Цель", callback_data="tasbih_target")
        ],
        [InlineKeyboardButton(text="📖 Выбрать другое поминание", callback_data="tasbih_select")]
    ])

    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=ikb)
    except Exception:
        pass
    await callback.answer("Счетчик сброшен!")

@dp.callback_query(F.data == "tasbih_target")
async def tasbih_target_cb(callback: CallbackQuery):
    await callback.answer("Цель установлена на 33 (Альхамдулиллах)", show_alert=True)

@dp.callback_query(F.data == "tasbih_select")
async def tasbih_select_cb(callback: CallbackQuery):
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Субханаллах", callback_data="set_dhikr_Subhanallah")],
        [InlineKeyboardButton(text="Альхамдулиллах", callback_data="set_dhikr_Alhamdulillah")],
        [InlineKeyboardButton(text="Аллаху Акбар", callback_data="set_dhikr_AllahuAkbar")],
        [InlineKeyboardButton(text="Астагфируллах", callback_data="set_dhikr_Astaghfirullah")]
    ])
    try:
        await callback.message.edit_text("Выберите поминание (зикр):", reply_markup=ikb)
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
    update_user_profile(callback.from_user.id, tasbih_dhikr=new_dhikr, tasbih_count=0)

    text = (
        "📿 **Электронный Тасбих**\n\n"
        f"Текущее поминание:\n✨ **{new_dhikr}**\n\n"
        "📊 Счёт: **0 / 33**\n\n"
        "Нажимайте на кнопку ниже, чтобы вести счет:"
    )
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Нажать для счета (+)", callback_data="tasbih_inc")],
        [
            InlineKeyboardButton(text="🔄 Сброс", callback_data="tasbih_reset"),
            InlineKeyboardButton(text="🎯 Цель", callback_data="tasbih_target")
        ],
        [InlineKeyboardButton(text="📖 Выбрать другое поминание", callback_data="tasbih_select")]
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
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ Изменить город", callback_data="change_city")]
        ])
        await message.answer(f"⚠️ Не удалось загрузить время для города **{city}**. Проверьте написание.", parse_mode="Markdown", reply_markup=ikb)
        return

    data = res["timings"]
    is_friday = datetime.datetime.now().weekday() == 4
    friday_text = ""
    if is_friday:
        friday_text = (
            "\n\n🕌 **СВЯЩЕННАЯ ПЯТНИЦА (ДЖУМА)!**\n"
            "• Прочитайте суру «Аль-Кахф» 📖\n"
            "• Произносите много салаватов Пророку ﷺ\n"
            "• Совершите коллективный Джума-намаз!"
        )

    text = (
        f"🕌 **Расписание намазов — {city}**\n\n"
        f"🌃 **Тахаджуд**: ~{data['Tahajjud']}\n"
        f"🌅 **Фаджр**: {data['Fajr']}\n"
        f"☀️ **Восход**: {data['Sunrise']}\n"
        f"🏙 **Зухр**: {data['Dhuhr']}\n"
        f"🌇 **Аср**: {data['Asr']}\n"
        f"🌆 **Магриб**: {data['Maghrib']}\n"
        f"🌌 **Иша**: {data['Isha']}"
        f"{friday_text}\n\n"
        f"🔔 *Напоминание:* Старайтесь готовиться к намазу за 5–10 минут до его начала!"
    )
    await message.answer(text, parse_mode="Markdown")

# ----------------- ШАГ ДНЯ И СОХРАНЕНИЕ ИСТОРИИ -----------------

@dp.message(F.text == "✨ Начать / Шаг дня")
async def show_step_of_day(message: Message):
    profile = get_user_profile(message.from_user.id)
    user_mode = profile['mode']
    active_steps = [s for s in ALL_STEPS if user_mode in s['modes']]
    idx = profile['step_index']

    if idx >= len(active_steps):
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Начать новый день", callback_data="reset_steps")]
        ])
        await message.answer(
            "🎉 **МашаАллах! Вы выполнили абсолютно все шаги на сегодня!**\n\n"
            "Пусть Аллах примет ваше поклонение, спорт, чтение и стремления к росту!",
            parse_mode="Markdown",
            reply_markup=ikb
        )
        return

    step = active_steps[idx]
    is_friday = datetime.datetime.now().weekday() == 4
    friday_note = "\n\n🕌 *Пятничный бонус:* Прочитайте суру «Аль-Кахф» и отправьте салават!" if is_friday else ""

    text = (
        f"📌 **Шаг {idx + 1} из {len(active_steps)}**\n\n"
        f"{step['title']}\n\n"
        f"{step['hadith']}"
        f"{friday_note}"
    )

    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить выполненным", callback_data="complete_step")],
        [InlineKeyboardButton(text="⚙️ Настройки и Режимы", callback_data="open_settings")]
    ])

    await message.answer(text, parse_mode="Markdown", reply_markup=ikb)

@dp.callback_query(F.data == "complete_step")
async def complete_step_callback(callback: CallbackQuery):
    profile = get_user_profile(callback.from_user.id)
    user_mode = profile['mode']
    active_steps = [s for s in ALL_STEPS if user_mode in s['modes']]

    idx = profile['step_index']

    if idx < len(active_steps):
        completed_step = active_steps[idx]
        try:
            await callback.message.edit_text(
                f"✅ **ВЫПОЛНЕНО**\n\n"
                f"{completed_step['title']}\n\n"
                f"{completed_step['hadith']}",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    new_index = idx + 1
    update_user_profile(callback.from_user.id, step_index=new_index)

    if new_index >= len(active_steps):
        new_streak = profile['streak'] + 1
        today_str = str(datetime.date.today())
        update_user_profile(callback.from_user.id, streak=new_streak, last_completed_date=today_str)
        save_daily_history(callback.from_user.id, len(active_steps), len(active_steps))

        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Начать новый день", callback_data="reset_steps")]
        ])
        await callback.message.answer(
            "🎉 **Альхамдулиллах! Все шаги дня успешно выполнены!**\n\n"
            f"🔥 Ваша текущая серия (Стрик): **{new_streak} дн.**\n"
            f"🏆 Вы стали еще сильнее духовно и интеллектуально!",
            parse_mode="Markdown",
            reply_markup=ikb
        )
    else:
        next_step = active_steps[new_index]
        is_friday = datetime.datetime.now().weekday() == 4
        friday_note = "\n\n🕌 *Пятничный бонус:* Прочитайте суру «Аль-Кахф» и отправьте салават!" if is_friday else ""

        text = (
            f"📌 **Шаг {new_index + 1} из {len(active_steps)}**\n\n"
            f"{next_step['title']}\n\n"
            f"{next_step['hadith']}"
            f"{friday_note}"
        )

        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Отметить выполненным", callback_data="complete_step")],
            [InlineKeyboardButton(text="⚙️ Настройки и Режимы", callback_data="open_settings")]
        ])

        await callback.message.answer(text, parse_mode="Markdown", reply_markup=ikb)
    
    await callback.answer()

@dp.callback_query(F.data == "reset_steps")
async def reset_steps_callback(callback: CallbackQuery):
    update_user_profile(callback.from_user.id, step_index=0)
    await callback.answer("Новый день начат!")
    await show_step_of_day(callback.message)

# ----------------- ПРОГРЕСС 7 / 90 / 365 ДНЕЙ -----------------

@dp.message(F.text == "📊 Мой прогресс (7/90/365)")
async def show_progress(message: Message):
    profile = get_user_profile(message.from_user.id)
    total_completed_days = get_user_stats(message.from_user.id)
    streak = profile['streak']

    p7 = min(100, int((streak / 7) * 100))
    p90 = min(100, int((streak / 90) * 100))
    p365 = min(100, int((streak / 365) * 100))

    text = (
        "📊 **Ваш личный прогресс роста и поклонения**\n\n"
        f"🔥 **Текущая серия дней подряд:** {streak} дн.\n"
        f"📅 **Всего успешных дней в базе:** {total_completed_days} дн.\n\n"
        f"🎯 **Цели и марафоны:**\n"
        f"• **7 дней (Неделя):** {p7}% {'✅' if p7 >= 100 else '⏳'}\n"
        f"• **90 дней (Трансформация):** {p90}% {'✅' if p90 >= 100 else '⏳'}\n"
        f"• **365 дней (Амаль 365):** {p365}% {'✅' if p365 >= 100 else '⏳'}\n\n"
        "🤍 Никакой конкуренции с другими — только ваша победа над собой вчерашним!"
    )
    await message.answer(text, parse_mode="Markdown")

# ----------------- ХАДИСЫ И ПЯТНИЦА -----------------

@dp.message(F.text == "📖 Хадисы и Пятница")
async def show_hadiths_and_friday(message: Message):
    text = (
        "📖 **Мудрые хадисы про поклонение, спорт и знания:**\n\n"
        "1️⃣ «Первое, за что спросят человека в День Суда — это намаз» (Тирмизи).\n"
        "2️⃣ «Сильный верующий лучше и любимее Аллаху, чем слабый» (Муслим).\n"
        "3️⃣ «Стремление к знаниям — обязанность каждого мусульманина» (Ибн Маджа).\n\n"
        "🕌 **Пятничные Сунны (Джума):**\n"
        "• Совершить полное омовение (гусль)\n"
        "• Надеть чистую одежду\n"
        "• Прочитать суру «Аль-Кахф» 📖\n"
        "• Произносить много салаватов Пророку Мухаммаду ﷺ\n"
        "• Сделать дуа в час принятия (между Асром и Магрибом)"
    )
    await message.answer(text, parse_mode="Markdown")

# ----------------- НАСТРОЙКИ И ВЫБОР РЕЖИМА -----------------

@dp.message(F.text == "⚙️ Настройки и Режимы")
async def show_settings(message: Message):
    profile = get_user_profile(message.from_user.id)
    
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Минимум (Только 5 намазов)", callback_data="set_mode_minimum")],
        [InlineKeyboardButton(text="🌙 Базовый (5 намазов + Тахаджуд)", callback_data="set_mode_basic")],
        [InlineKeyboardButton(text="🕊 Душевный рост (Коран + Азкары)", callback_data="set_mode_spiritual")],
        [InlineKeyboardButton(text="🚀 Полный рост (+Спорт +Книги)", callback_data="set_mode_full")],
        [InlineKeyboardButton(text="🌆 Изменить город (Любой город мира)", callback_data="change_city")]
    ])
    
    mode_descr = {
        "minimum": "🟢 Минимум (Только 5 намазов)",
        "basic": "🌙 Базовый (5 намазов + Тахаджуд)",
        "spiritual": "🕊 Душевный рост (Намазы + Тахаджуд + Коран + Азкары + Салават)",
        "full": "🚀 Полный рост (Намазы + Тахаджуд + Коран + Спорт + Книги + Азкары + Салават)"
    }.get(profile['mode'], "Полный рост")

    await message.answer(
        f"⚙️ **Настройки профиля**\n\n"
        f"📍 **Текущий город:** {profile['city']}\n"
        f"🎯 **Выбранный режим:** {mode_descr}\n\n"
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
        "✍️ **Напишите название любого города мира** (например: `Нерюнгри`, `Бишкек`, `Москва`, `Дубай`):",
        parse_mode="Markdown"
    )
    await callback.answer()

@dp.message(Form.city)
async def process_city_input(message: Message, state: FSMContext):
    new_city = message.text.strip().replace("*", "")
    update_user_profile(message.from_user.id, city=new_city)
    await state.clear()

    await message.answer(
        f"✅ Город успешно изменен на **{new_city}**!\nБот автоматически настроил время намазов.",
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
                                    msg = f"🔔 До наступления намаза **{p_name}** осталось 5 минут!\nВремя совершить омовение и идти навстречу к Аллаху."
                                    await bot.send_message(u_id, msg, parse_mode="Markdown")
                                except Exception as err:
                                    logging.error(f"Failed to send PUSH to {u_id}: {err}")
                            else:
                                conn.close()
        except Exception as e:
            logging.error(f"Error in notification loop: {e}")

        await asyncio.sleep(40)

# ----------------- WEB SERVER ДЛЯ RENDER -----------------

async def handle_ping(request):
    return web.Response(text="Amal365 Ultimate Bot is Active!", status=200)

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
