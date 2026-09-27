import os
import logging
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

import database as db

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")
WEBHOOK_PATH = f"/bot/{BOT_TOKEN}"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"

if not BOT_TOKEN:
    logging.error("CRITICAL: BOT_TOKEN is missing!")

bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher(storage=MemoryStorage())

class OnboardingStates(StatesGroup):
    waiting_for_city = State()

class ActivityStates(StatesGroup):
    waiting_for_steps = State()
    waiting_for_sport = State()

class SettingsStates(StatesGroup):
    waiting_for_new_city = State()


# Главное нижнее меню (ровно 5 чистых кнопок)
def get_main_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏰ Время намазов"), KeyboardButton(text="📿 Поминания и дуа")],
            [KeyboardButton(text="📊 Мой путь"), KeyboardButton(text="⛳️ Активность")],
            [KeyboardButton(text="⚙️ Актуальный режим")]
        ],
        resize_keyboard=True
    )


# --- ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ ТОЧНОГО ВРЕМЕНИ НАМАЗОВ ПО ВСЕМУ МИРУ ---
async def fetch_prayer_times(city: str):
    url = f"https://api.aladhan.com/v1/timingsByCity?city={city}&country=&method=3"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("code") == 200:
                        timings = data["data"]["timings"]
                        return {
                            "Fajr": timings.get("Fajr", "05:10"),
                            "Dhuhr": timings.get("Dhuhr", "12:30"),
                            "Asr": timings.get("Asr", "16:15"),
                            "Maghrib": timings.get("Maghrib", "19:00"),
                            "Isha": timings.get("Isha", "20:30")
                        }
    except Exception as e:
        logging.error(f"Error fetching prayer times for {city}: {e}")
    
    return {
        "Fajr": "05:10",
        "Dhuhr": "12:30",
        "Asr": "16:15",
        "Maghrib": "19:00",
        "Isha": "20:30"
    }


# --- СТАРТ И ОНБОРДИНГ (Чистый и быстрый) ---

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    db.get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    
    text = (
        "Ассаляму алейкум ва рахматуллахи ва баракатух 🌙\n\n"
        "Добро пожаловать в <b>Amal365</b>.\n\n"
        "Мы бережно защищаем ваши данные и используем их исключительно для персонального сопровождения на пути к постоянству в благих делах.\n\n"
        "Пусть Аллах дарует пользу и баракат в этом пути 🤍"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Начать с Бисмиллях", callback_data="policy_agreed")],
        [InlineKeyboardButton(text="❌ Выйти", callback_data="policy_exit")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "policy_exit")
async def cb_policy_exit(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Вы всегда можете вернуться к нам, когда будете готовы. Всего доброго! 🤍", parse_mode="HTML")


@dp.callback_query(F.data == "policy_agreed")
async def cb_country_step(callback: types.CallbackQuery, state: FSMContext):
    text = (
        "🌍 <b>Выбор страны</b>\n\n"
        "Пожалуйста, выберите вашу страну:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇰🇬 Кыргызстан", callback_data="country_kg"),
         InlineKeyboardButton(text="🇷🇺 Россия", callback_data="country_ru")],
        [InlineKeyboardButton(text="🇰🇿 Казахстан", callback_data="country_kz"),
         InlineKeyboardButton(text="🇺🇿 Узбекистан", callback_data="country_uz")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("country_"))
async def cb_ask_city(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(OnboardingStates.waiting_for_city)
    text = (
        "🏙️ <b>Введите ваш город</b>\n\n"
        "Напишите название вашего населенного пункта на кириллице (например: <i>Нерюнгри</i>, <i>Бишкек</i>, <i>Казань</i>, <i>Алматы</i>):"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="policy_agreed")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.message(OnboardingStates.waiting_for_city)
async def process_city_input(message: types.Message, state: FSMContext):
    city_name = message.text.strip()
    db.update_user(message.from_user.id, {"city": city_name})
    await state.clear()

    text = (
        f"✅ Город <b>{city_name}</b> успешно сохранен!\n\n"
        "✨ <b>Выберите ваш режим сопровождения</b>\n\n"
        "Каждый ритм создан с заботой о вашем сердце:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Аль-Фард (5 намазов, салават, зикр)", callback_data="set_mode_fard")],
        [InlineKeyboardButton(text="🌿 Аль-Истикама (+ Тахаджуд, Коран)", callback_data="set_mode_istikama")],
        [InlineKeyboardButton(text="📖 Ат-Тазкия (+ Чтение книг)", callback_data="set_mode_tazkiya")],
        [InlineKeyboardButton(text="⭐ Аль-Ихсан (Полный глубокий комплекс)", callback_data="set_mode_ihsan")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("set_mode_"))
async def cb_mode_saved(callback: types.CallbackQuery, state: FSMContext):
    mode_map = {
        "set_mode_fard": "Аль-Фард",
        "set_mode_istikama": "Аль-Истикама",
        "set_mode_tazkiya": "Ат-Тазкия",
        "set_mode_ihsan": "Аль-Ихсан"
    }
    selected_mode = mode_map.get(callback.data, "Аль-Фард")
    db.update_user(callback.from_user.id, {"current_level": selected_mode})

    text = (
        f"🤍 <b>Альхамдулиллах, намерение оформлено. Ритм «{selected_mode}» бережно настроен.</b>\n\n"
        "Пусть этот путь принесёт в ваше сердце свет, баракат и глубокую сакину (умиротворение).\n\n"
        "Здесь нет места гонке и тревоге — только вы, ваши искренние стремления и милость Всевышнего.\n\n"
        "Панель внизу всегда рядом, чтобы тихо и деликатно сопровождать вас изо дня в день."
    )
    await callback.message.answer(text, parse_mode="HTML", reply_markup=get_main_reply_keyboard())
    await callback.message.delete()


# --- РАЗДЕЛ «ПОМИНАНИЯ И ДУА» ---

@dp.message(F.text == "📿 Поминания и дуа")
async def menu_remind_dua(message: types.Message):
    text = (
        "📿 <b>Поминания и дуа</b>\n\n"
        "«Поминайте Меня, и Я буду помнить вас...» (Коран, 2:152)\n\n"
        "Выберите нужное направление:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Зикр и салават (Тасбих)", callback_data="submenu_zikr")],
        [InlineKeyboardButton(text="📖 Утренние и вечерние азкары", callback_data="submenu_adhkar")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "submenu_zikr")
async def cb_zikr_main(callback: types.CallbackQuery):
    text = (
        "📿 <b>Зикр и салават</b>\n\n"
        "Выберите желаемую цель для поминания:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="3️⃣3️⃣ Цель: 33 раза", callback_data="set_goal_33"),
         InlineKeyboardButton(text="9️⃣9️⃣ Цель: 99 раз", callback_data="set_goal_99")],
        [InlineKeyboardButton(text="♾️ Без фиксированной цели", callback_data="set_goal_unlimited")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_remind_dua")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("set_goal_"))
async def cb_set_tasbih_goal(callback: types.CallbackQuery):
    goal_map = {
        "set_goal_33": 33,
        "set_goal_99": 99,
        "set_goal_unlimited": 9999
    }
    goal = goal_map.get(callback.data, 33)
    db.update_user(callback.from_user.id, {"active_tasbih_goal": goal, "active_tasbih_count": 0, "active_tasbih_type": "subhanallah"})
    await cb_tasbih_counter(callback)


@dp.callback_query(F.data == "tasbih_counter_view")
async def cb_tasbih_counter(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    current_type = user.get("active_tasbih_type", "subhanallah")
    count = user.get("active_tasbih_count", 0)
    goal = user.get("active_tasbih_goal", 33)

    names = {
        "subhanallah": "Субханаллах (سبحان الله)",
        "alhamdulillah": "Альхамдулиллях (الحمد لله)",
        "allahuakbar": "Аллаху Акбар (الله أكبر)",
        "astaghfirullah": "Астагфируллах (أستغفر الله)",
        "salawat": "Салават на Пророка ﷺ"
    }

    goal_str = str(goal) if goal < 9999 else "∞"

    text = (
        f"📿 <b>Интерактивный Тасбих</b>\n\n"
        f"Этап: <b>{names.get(current_type, 'Зикр')}</b>\n"
        f"Счетчик: <b>{count} / {goal_str}</b>\n\n"
        "Нажимайте кнопку ниже с каждым произнесением:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Сделать поминание (+1)", callback_data="tasbih_inc")],
        [InlineKeyboardButton(text="🔄 Сбросить", callback_data="tasbih_reset")],
        [InlineKeyboardButton(text="⬅️ Назад к выбору цели", callback_data="submenu_zikr")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "tasbih_inc")
async def cb_tasbih_increment(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    count = user.get("active_tasbih_count", 0) + 1
    current_type = user.get("active_tasbih_type", "subhanallah")
    goal = user.get("active_tasbih_goal", 33)

    if count >= goal:
        stages = ["subhanallah", "alhamdulillah", "allahuakbar", "astaghfirullah", "salawat"]
        try:
            next_idx = stages.index(current_type) + 1
            if next_idx < len(stages):
                current_type = stages[next_idx]
                count = 0
                db.update_user(callback.from_user.id, {"active_tasbih_type": current_type, "active_tasbih_count": 0})
                await callback.answer("Альхамдулиллах! Переходим к следующему поминанию 🤍", show_alert=True)
            else:
                db.update_user(callback.from_user.id, {"active_tasbih_type": "subhanallah", "active_tasbih_count": 0, "active_tasbih_goal": 33})
                await callback.answer("Круг поминаний успешно завершен! Пусть Аллах примет его 🤍", show_alert=True)
                return await cb_zikr_main(callback)
        except ValueError:
            pass
    else:
        db.update_user(callback.from_user.id, {"active_tasbih_count": count})

    await cb_tasbih_counter(callback)


@dp.callback_query(F.data == "tasbih_reset")
async def cb_tasbih_reset(callback: types.CallbackQuery):
    db.update_user(callback.from_user.id, {"active_tasbih_count": 0, "active_tasbih_type": "subhanallah"})
    await callback.answer("Счетчик сброшен.", show_alert=True)
    await cb_tasbih_counter(callback)


@dp.callback_query(F.data == "submenu_adhkar")
async def cb_adhkar_menu(callback: types.CallbackQuery):
    text = (
        "📖 <b>Утренние и вечерние азкары</b>\n\n"
        "Выберите нужное время суток:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌅 Утренние азкары", callback_data="adhkar_morning")],
        [InlineKeyboardButton(text="🌙 Вечерние азкары", callback_data="adhkar_evening")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_remind_dua")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "adhkar_morning")
async def cb_morning_adhkar(callback: types.CallbackQuery):
    text = (
        "🌅 <b>Утренние азкары (Минимум защиты)</b>\n\n"
        "• <b>Аят аль-Курси</b> (Сура «Корова», 255) — 1 раз.\n"
        "• <b>Три последние суры</b> («Аль-Ихляс», «Аль-Фалак», «Ан-Нас») — по 3 раза.\n\n"
        "• <b>Формула начала утра:</b>\n"
        "<i>«Асбахна ва асбаха аль-мульку лилляхи рабби ль-’алямин. Аллахумма инни ас’алюка хайра хаза ль-явми фатхаху ва насраху ва нураху ва барактаху ва худаху...»</i>\n\n"
        "• <b>Сейид аль-истигфар:</b>\n"
        "<i>«Аллахумма Анта Рабби, ля иляха илля Анта, халяктани ва ана ’абдука...»</i>\n\n"
        "• <b>Короткая формула:</b> Чтение «Субханаллаһ ва бихамдиһ» по 100 раз."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить как прочитанные", callback_data="mark_morning_done")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="submenu_adhkar")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "mark_morning_done")
async def cb_mark_morning(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(callback.from_user.id, date_str, {"morning_adhkar_done": True})
    await callback.answer("Утренние азкары отмечены выполненными! 🤍", show_alert=True)
    await cb_adhkar_menu(callback)


@dp.callback_query(F.data == "adhkar_evening")
async def cb_evening_adhkar(callback: types.CallbackQuery):
    text = (
        "🌙 <b>Вечерние азкары (Минимум защиты)</b>\n\n"
        "• <b>Аят аль-Курси</b> — 1 раз.\n"
        "• <b>Три последние суры</b> («Аль-Ихляс», «Аль-Фалак», «Ан-Нас») — по 3 раза.\n\n"
        "• <b>Формула начала вечера:</b>\n"
        "<i>«Амсайна ва амса аль-мульку лилляхи рабби ль-’алямин. Аллахумма инни ас’алюка хайра ма фи хазихи ль-лейляти...»</i>\n\n"
        "• <b>Сейид аль-истигфар:</b> Молитва о прощении (1 раз).\n\n"
        "• <b>Короткая формула:</b> Чтение зикров по 100 раз."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить как прочитанные", callback_data="mark_evening_done")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="submenu_adhkar")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "mark_evening_done")
async def cb_mark_evening(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(callback.from_user.id, date_str, {"evening_adhkar_done": True})
    await callback.answer("Вечерние азкары отмечены выполненными! 🤍", show_alert=True)
    await cb_adhkar_menu(callback)


@dp.callback_query(F.data == "back_to_remind_dua")
async def cb_back_to_remind_dua(callback: types.CallbackQuery):
    text = (
        "📿 <b>Поминания и дуа</b>\n\n"
        "Выберите нужное направление:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Зикр и салават (Тасбих)", callback_data="submenu_zikr")],
        [InlineKeyboardButton(text="📖 Утренние и вечерние азкары", callback_data="submenu_adhkar")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


# --- ОСТАЛЬНЫЕ КНОПКИ НИЖНЕГО МЕНЮ ---

@dp.message(F.text == "⏰ Время намазов")
async def menu_prayer_times(message: types.Message):
    user = db.get_or_create_user(message.from_user.id)
    city = user.get("city", "Нерюнгри")
    times = await fetch_prayer_times(city)
    await message.answer(
        f"🕌 <b>Время намазов для г. {city}</b>\n\n"
        f"• Фаджр: {times['Fajr']}\n"
        f"• Зухр: {times['Dhuhr']}\n"
        f"• Аср: {times['Asr']}\n"
        f"• Магриб: {times['Maghrib']}\n"
        f"• Иша: {times['Isha']}\n\n"
        f"<i>«Воистину, намаз предписан верующим в определенное время».</i>",
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard()
    )


@dp.message(F.text == "📊 Мой путь")
async def menu_my_path(message: types.Message):
    text = (
        "📊 <b>Мой путь</b>\n\n"
        "Выберите интересующий вас раздел:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌙 Сводка дня", callback_data="path_daily_summary")],
        [InlineKeyboardButton(text="📈 Общий прогресс (Стрик)", callback_data="path_general_streak")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "path_daily_summary")
async def cb_path_summary(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    date_str = db.get_user_local_date(user)
    prog = db.get_today_progress(user["id"], date_str)
    
    text = (
        "🌙 <b>Сводка дня</b>\n\n"
        f"• Дата: {date_str}\n"
        f"• Намазы: {'✅ Выполнены' if prog.get('fajr_done') else '⏳ В процессе'}\n"
        f"• Азкары (утр/веч): {prog.get('morning_adhkar_done', False)} / {prog.get('evening_adhkar_done', False)}\n"
        f"• Шаги сегодня: {prog.get('activity_steps', 0)}\n\n"
        "Пусть Аллах примет ваши труды 🤍"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="path_back_main")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "path_general_streak")
async def cb_path_streak(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    streak = user.get("streak_days", 0)
    level = user.get("current_level", "Аль-Фард")
    
    text = (
        "📈 <b>Общий прогресс</b>\n\n"
        f"🔥 Непрерывная серия дней (стрик): <b>{streak} дн.</b>\n"
        f"✨ Активный режим: <b>{level}</b>\n\n"
        "Самые любимые дела перед Аллахом — те, которые совершаются регулярно 🤍"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="path_back_main")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "path_back_main")
async def cb_path_back(callback: types.CallbackQuery):
    text = (
        "📊 <b>Мой путь</b>\n\n"
        "Выберите интересующий вас раздел:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌙 Сводка дня", callback_data="path_daily_summary")],
        [InlineKeyboardButton(text="📈 Общий прогресс (Стрик)", callback_data="path_general_streak")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


# --- АКТУАЛЬНЫЙ РЕЖИМ И ДЕЛИКАТНАЯ ПАУЗА ---

@dp.message(F.text == "⚙️ Актуальный режим")
async def menu_settings(message: types.Message):
    user = db.get_or_create_user(message.from_user.id)
    level = user.get("current_level", "Аль-Фард")
    city = user.get("city", "Не указан")
    is_paused = user.get("pause_mode", False)
    pause_reason = user.get("pause_reason", "Пауза")

    if is_paused:
        if pause_reason == "Особенные дни":
            pause_desc = (
                f"🌸 <b>Деликатная пауза активна: {pause_reason}</b>\n\n"
                "В эти дни ваше тело и сердце нуждаются в особой заботе и бережном отношении. Серия дней и прогресс в абсолютной безопасности.\n\n"
                "Вы можете продолжать мягкое поминание Всевышнего (зикр), делать прекрасный Салават на Пророка ﷺ и слушать благородный Коран со спокойной душой 🤍\n\n"
                "Когда будете готовы, вы можете восстановить режим или изменить причину ниже:"
            )
        else:
            pause_desc = (
                f"🌸 <b>Деликатная пауза активна: {pause_reason}</b>\n\n"
                "Ваш прогресс и серия дней в абсолютной безопасности.\n\n"
                "Отдыхайте со спокойной душой. Когда будете готовы, вы можете восстановить режим или изменить причину ниже:"
            )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✨ Восстановить режим / Завершить паузу", callback_data="pause_restore")],
            [InlineKeyboardButton(text="🌸 Сменить причину паузы", callback_data="settings_pause")]
        ])
        await message.answer(pause_desc, parse_mode="HTML", reply_markup=kb)
        return

    text = (
        f"⚙️ <b>Настройки и актуальный режим</b>\n\n"
        f"• Текущий ритм: <b>{level}</b>\n"
        f"• Ваш город: <b>{city}</b>\n\n"
        "Выберите параметр для настройки:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏙️ Сменить город", callback_data="settings_change_city")],
        [InlineKeyboardButton(text="✨ Перенастроить режим", callback_data="settings_change_mode")],
        [InlineKeyboardButton(text="🌸 Деликатная пауза", callback_data="settings_pause")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "settings_change_city")
async def cb_settings_change_city(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SettingsStates.waiting_for_new_city)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_back_main")]
    ])
    await callback.message.edit_text(
        "🏙️ Введите название нового города на кириллице:",
        parse_mode="HTML",
        reply_markup=kb
    )


@dp.message(SettingsStates.waiting_for_new_city)
async def process_new_city(message: types.Message, state: FSMContext):
    new_city = message.text.strip()
    db.update_user(message.from_user.id, {"city": new_city})
    await state.clear()
    await message.answer(
        f"✅ Город успешно изменен на <b>{new_city}</b>!",
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard()
    )


@dp.callback_query(F.data == "settings_change_mode")
async def cb_settings_change_mode(callback: types.CallbackQuery):
    text = "✨ <b>Выберите новый режим сопровождения:</b>"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Аль-Фард", callback_data="set_mode_fard")],
        [InlineKeyboardButton(text="🌿 Аль-Истикама", callback_data="set_mode_istikama")],
        [InlineKeyboardButton(text="📖 Ат-Тазкия", callback_data="set_mode_tazkiya")],
        [InlineKeyboardButton(text="⭐ Аль-Ихсан", callback_data="set_mode_ihsan")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_back_main")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "settings_pause")
async def cb_pause_menu(callback: types.CallbackQuery):
    text = (
        "🌸 <b>Деликатная пауза</b>\n\n"
        "Выберите причину паузы. Ваш прогресс и серия дней в абсолютной безопасности:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌸 Особенные дни", callback_data="pause_special")],
        [InlineKeyboardButton(text="🌿 Заболел(а)", callback_data="pause_sick")],
        [InlineKeyboardButton(text="⏳ Времени нет", callback_data="pause_busy")],
        [InlineKeyboardButton(text="✨ Просто отдых", callback_data="pause_rest")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_back_main")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("pause_"))
async def cb_pause_set(callback: types.CallbackQuery):
    if callback.data == "pause_restore":
        db.update_user(callback.from_user.id, {"pause_mode": False, "pause_reason": None})
        await callback.message.edit_text(
            "🤍 С возвращением! Режим паузы завершен, ваш активный путь продолжается с новыми силами.",
            parse_mode="HTML"
        )
        return

    reasons = {
        "pause_special": "Особенные дни",
        "pause_sick": "Заболел(а)",
        "pause_busy": "Времени нет",
        "pause_rest": "Просто отдых"
    }
    reason_text = reasons.get(callback.data, "Пауза")
    db.update_user(callback.from_user.id, {"pause_mode": True, "pause_reason": reason_text})
    
    if reason_text == "Особенные дни":
        msg_text = (
            f"🌸 <b>Деликатная пауза активирована: {reason_text}</b>\n\n"
            "В эти дни ваше тело и сердце нуждаются в особой заботе и бережном отношении. Серия дней и прогресс в абсолютной безопасности.\n\n"
            "Вы можете продолжать мягкое поминание Всевышнего (зикр), делать прекрасный Салават на Пророка ﷺ и слушать благородный Коран со спокойной душой 🤍\n\n"
            "Когда будете готовы, вы можете восстановить режим или изменить причину ниже:"
        )
    else:
        msg_text = (
            f"🌸 <b>Деликатная пауза активирована: {reason_text}</b>\n\n"
            "Ваш прогресс и серия дней в абсолютной безопасности.\n\n"
            "Отдыхайте со спокойной душой. Когда будете готовы, вы можете восстановить режим или изменить причину ниже:"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Восстановить режим / Завершить паузу", callback_data="pause_restore")],
        [InlineKeyboardButton(text="🌸 Сменять причину паузы", callback_data="settings_pause")]
    ])
    await callback.message.edit_text(msg_text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "settings_back_main")
async def cb_settings_back(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    level = user.get("current_level", "Аль-Фард")
    city = user.get("city", "Не указан")
    
    text = (
        f"⚙️ <b>Настройки и актуальный режим</b>\n\n"
        f"• Текущий ритм: <b>{level}</b>\n"
        f"• Ваш город: <b>{city}</b>\n\n"
        "Выберите параметр для настройки:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏙️ Сменить город", callback_data="settings_change_city")],
        [InlineKeyboardButton(text="✨ Перенастроить режим", callback_data="settings_change_mode")],
        [InlineKeyboardButton(text="🌸 Деликатная пауза", callback_data="settings_pause")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


# --- ТРЕКЕР АКТИВНОСТИ ---

@dp.message(F.text == "⛳️ Активность")
async def menu_activity(message: types.Message):
    text = (
        "⛳️ <b>Забота о теле</b>\n\n"
        "«Наше тело — это аманат (доверие) от Всевышнего, а здоровье дает силы для благого». Что добавим в дневник сегодня?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚶‍♂️ Ходьба (Шаги)", callback_data="act_walk"),
         InlineKeyboardButton(text="🏃‍♀️ Спорт / Тренировка", callback_data="act_sport")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "act_walk")
async def cb_act_walk(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ActivityStates.waiting_for_steps)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="act_back_main")]
    ])
    await callback.message.edit_text(
        "🚶‍♂️ Отправьте в ответ число ваших шагов цифрами (например: <i>5000</i>):",
        parse_mode="HTML",
        reply_markup=kb
    )


@dp.message(ActivityStates.waiting_for_steps)
async def process_steps_input(message: types.Message, state: FSMContext):
    try:
        steps = int(message.text.strip())
    except ValueError:
        await message.answer("Пожалуйста, введите число шагов цифрами (например: 5000):")
        return

    user = db.get_or_create_user(message.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(message.from_user.id, date_str, {"activity_steps": steps})
    await state.clear()

    await message.answer(
        f"✅ Машаллаh! Записано шагов: <b>{steps}</b>. Вы отлично потрудились сегодня 🤍",
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard()
    )


@dp.callback_query(F.data == "act_sport")
async def cb_act_sport(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ActivityStates.waiting_for_sport)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="act_back_main")]
    ])
    await callback.message.edit_text(
        "🏃‍♀️ Напишите время тренировки (например: <i>15 минут</i> или <i>1 час</i>):",
        parse_mode="HTML",
        reply_markup=kb
    )


@dp.message(ActivityStates.waiting_for_sport)
async def process_sport_input(message: types.Message, state: FSMContext):
    user = db.get_or_create_user(message.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(message.from_user.id, date_str, {"sport_minutes": 30})
    await state.clear()

    await message.answer(
        f"💪 Альхамдулиллах! Тренировка успешно сохранена. Пусть Аллах дарует вам крепкое здоровье и силы для благих дел! 🤍",
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard()
    )


@dp.callback_query(F.data == "act_back_main")
async def cb_act_back(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "⛳️ <b>Забота о теле</b>\n\n"
        "«Наше тело — это аманат (доверие) от Всевышнего, а здоровье дает силы для благого». Что добавим в дневник сегодня?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚶‍♂️ Ходьба (Шаги)", callback_data="act_walk"),
         InlineKeyboardButton(text="🏃‍♀️ Спорт / Тренировка", callback_data="act_sport")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


# --- ЗАПУСК ВЕБ-СЕРВЕРА ДЛЯ RENDER ---
async def on_startup(bot: Bot):
    if not RENDER_EXTERNAL_URL:
        logging.warning("⚠️ RENDER_EXTERNAL_URL не задан!")
        return
    try:
        await bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True)
        logging.info(f"=== WEBHOOK SUCCESSFULLY SET TO: {WEBHOOK_URL} ===")
    except Exception as e:
        logging.error(f"=== ERROR SETTING WEBHOOK: {e} ===")


def main():
    app = web.Application()
    
    async def index(request):
        return web.Response(text="Amal365 Bot Web Service is running 🤍")
    
    app.router.add_get("/", index)

    if bot:
        webhook_requests_handler = SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
        )
        webhook_requests_handler.register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
        dp.startup.register(on_startup)

    logging.info(f"Starting web server on port {PORT}...")
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
