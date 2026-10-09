import os
import logging
import asyncio
from datetime import datetime
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

# ==================== FSM СОСТОЯНИЯ ====================
class OnboardingStates(StatesGroup):
    waiting_for_city = State()

class ActivityStates(StatesGroup):
    waiting_for_quran = State()
    waiting_for_book = State()
    waiting_for_steps = State()
    waiting_for_sport = State()

class SettingsStates(StatesGroup):
    waiting_for_new_city = State()


# ==================== КЛАВИАТУРЫ ====================

def get_main_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏰ Время намазов"), KeyboardButton(text="📿 Поминания и дуа")],
            [KeyboardButton(text="📊 Мой путь"), KeyboardButton(text="⛳️ Активность")],
            [KeyboardButton(text="⚙️ Актуальный режим")]
        ],
        resize_keyboard=True
    )


# ==================== РАСЧЕТ ВРЕМЕНИ НАМАЗОВ ====================
CITY_MAPPING = {
    "нерюнгри": "Neryungri",
    "бишкек": "Bishkek",
    "казань": "Kazan",
    "москва": "Moscow",
    "алматы": "Almaty",
    "ташкент": "Tashkent",
    "якутск": "Yakutsk",
    "санкт-петербург": "Saint Petersburg",
    "новосибирск": "Novosibirsk",
    "екатеринбург": "Ekaterinburg",
    "уфа": "Ufa",
    "грозный": "Grozny",
    "махачкала": "Makhachkala"
}

async def fetch_prayer_times(city: str):
    clean_city = city.lower().strip()
    api_city = CITY_MAPPING.get(clean_city, city)
    url = f"https://api.aladhan.com/v1/timingsByCity?city={api_city}&country=&method=3"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("code") == 200:
                        timings = data["data"]["timings"]
                        return {
                            "Фаджр": timings.get("Fajr", "04:40"),
                            "Восход": timings.get("Sunrise", "06:19"),
                            "Зухр": timings.get("Dhuhr", "12:35"),
                            "Аср": timings.get("Asr", "15:52"),
                            "Магриб": timings.get("Maghrib", "18:50"),
                            "Иша": timings.get("Isha", "20:31")
                        }
    except Exception as e:
        logging.error(f"Error fetching prayer times for {city}: {e}")
    
    return {
        "Фаджр": "04:40",
        "Восход": "06:19",
        "Зухр": "12:35",
        "Аср": "15:52",
        "Магриб": "18:50",
        "Иша": "20:31"
    }

def get_next_prayer(timings: dict):
    now = datetime.now().strftime("%H:%M")
    prayer_order = [
        ("Фаджр", timings.get("Фаджр")),
        ("Зухр", timings.get("Зухр")),
        ("Аср", timings.get("Аср")),
        ("Магриб", timings.get("Магриб")),
        ("Иша", timings.get("Иша"))
    ]
    for name, t_str in prayer_order:
        if t_str and now < t_str:
            return name
    return "Фаджр (завтра)"


# ==================== СТАРТ И ОНБОРДИНГ ====================

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    db.get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    text = (
        "Ассаляму алейкум ва рахматуллахи ва баракатух 🌙\n\n"
        "Добро пожаловать в <b>Amal365</b> — ваш бережный цифровой спутник на пути постоянства и поклонения.\n\n"
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
    text = "🌍 <b>Выбор страны</b>\n\nПожалуйста, выберите вашу страну:"
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
        "Напишите название вашего населенного пункта на кириллице (например: <i>Нерюнгри</i>, <i>Бишкек</i>, <i>Казань</i>):"
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
        "Пусть этот путь принесёт в ваше сердце свет, баракат и глубокую сакину.\n\n"
        "Панель внизу всегда рядом, чтобы тихо и деликатно сопровождать вас изо дня в день."
    )
    await callback.message.answer(text, parse_mode="HTML", reply_markup=get_main_reply_keyboard())
    await callback.message.delete()


# ==================== РАЗДЕЛ «ПОМИНАНИЯ И ДУА» (3 КНОПКИ) ====================

@dp.message(F.text == "📿 Поминания и дуа")
async def menu_remind_dua(message: types.Message):
    text = (
        "📿 <b>Поминания и дуа</b>\n\n"
        "«Поминайте Меня, и Я буду помнить вас...» (Коран, 2:152)\n\n"
        "Выберите нужное направление:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Тасбих", callback_data="rem_tasbih")],
        [InlineKeyboardButton(text="✨ Салават", callback_data="rem_salawat")],
        [InlineKeyboardButton(text="🌅 Утренние азкары", callback_data="rem_azkar_morning"),
         InlineKeyboardButton(text="🌆 Вечерние азкары", callback_data="rem_azkar_evening")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "back_to_remind_dua")
async def cb_back_to_remind_dua(callback: types.CallbackQuery):
    text = (
        "📿 <b>Поминания и дуа</b>\n\n"
        "Выберите нужное направление:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Тасбих", callback_data="rem_tasbih")],
        [InlineKeyboardButton(text="✨ Салават", callback_data="rem_salawat")],
        [InlineKeyboardButton(text="🌅 Утренние азкары", callback_data="rem_azkar_morning"),
         InlineKeyboardButton(text="🌆 Вечерние азкары", callback_data="rem_azkar_evening")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

# 1. ТАСБИХ (Цели: 7, 33, 99, без цели + автопереход + мгновенная фиксация)
@dp.callback_query(F.data == "rem_tasbih")
async def rem_tasbih(callback: types.CallbackQuery):
    text = "📿 <b>Тасбих</b>\n\nВыберите желаемую цель для повторения:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="7 раз", callback_data="tasbih_target_7"),
         InlineKeyboardButton(text="33 раза", callback_data="tasbih_target_33"),
         InlineKeyboardButton(text="99 раз", callback_data="tasbih_target_99")],
        [InlineKeyboardButton(text="♾️ Без цели (свободный счет)", callback_data="tasbih_target_none")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_remind_dua")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith("tasbih_target_"))
async def cb_set_tasbih_target(callback: types.CallbackQuery):
    target_raw = callback.data.split("_")[2]
    goal = 999999 if target_raw == "none" else int(target_raw)
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
        "astaghfirullah": "Астагфируллах (أستغفر الله)"
    }
    goal_str = str(goal) if goal < 999990 else "∞"

    text = (
        f"📿 <b>Тасбих</b>\n\n"
        f"Зикр: <b>{names.get(current_type, 'Субханаллах')}</b>\n"
        f"Счетчик: <b>{count} / {goal_str}</b>\n\n"
        "Каждый клик мгновенно сохраняется в вашей сводке дня 🤍"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Нажать (+1)", callback_data="tasbih_inc")],
        [InlineKeyboardButton(text="🔄 Сбросить", callback_data="tasbih_reset")],
        [InlineKeyboardButton(text="⬅️ К выбору целей", callback_data="rem_tasbih")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "tasbih_inc")
async def cb_tasbih_increment(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    count = user.get("active_tasbih_count", 0) + 1
    current_type = user.get("active_tasbih_type", "subhanallah")
    goal = user.get("active_tasbih_goal", 33)

    date_str = db.get_user_local_date(user)
    prog = db.get_today_progress(user["id"], date_str)
    current_total_tasbih = prog.get("tasbih_count", 0) + 1
    db.update_daily_progress(user["id"], date_str, {"tasbih_count": current_total_tasbih})

    if count >= goal and goal < 999990:
        stages = ["subhanallah", "alhamdulillah", "allahuakbar", "astaghfirullah"]
        try:
            next_idx = stages.index(current_type) + 1
            if next_idx < len(stages):
                current_type = stages[next_idx]
                count = 0
                db.update_user(callback.from_user.id, {"active_tasbih_type": current_type, "active_tasbih_count": 0})
                await callback.answer("Цель достигнута! Плавный автопереход к следующему зикру 🤍", show_alert=True)
            else:
                db.update_user(callback.from_user.id, {"active_tasbih_type": "subhanallah", "active_tasbih_count": 0})
                await callback.answer("Круг поминаний успешно завершен! Пусть Аллах примет его 🤍", show_alert=True)
                return await cb_tasbih_counter(callback)
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

# 2. САЛАВАТ (Цели: 33, 100, без цели + пятничный акцент + мгновенная фиксация)
@dp.callback_query(F.data == "rem_salawat")
async def rem_salawat(callback: types.CallbackQuery):
    text = (
        "✨ <b>Салават на Пророка ﷺ</b>\n\n"
        "«Кто призовет на меня благословение один раз, тому Аллах ниспошлет благословение десять раз» (Муслим).\n"
        "Особенно благословенно чтение в пятницу (Джума).\n\n"
        "Выберите цель:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="33 раза", callback_data="salawat_target_33"),
         InlineKeyboardButton(text="100 раз", callback_data="salawat_target_100")],
        [InlineKeyboardButton(text="♾️ Без цели (свободный счет)", callback_data="salawat_target_none")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_remind_dua")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith("salawat_target_"))
async def cb_set_salawat_target(callback: types.CallbackQuery):
    target_raw = callback.data.split("_")[2]
    goal = 999999 if target_raw == "none" else int(target_raw)
    db.update_user(callback.from_user.id, {"active_salawat_goal": goal, "active_salawat_count": 0})
    await cb_salawat_counter(callback)

@dp.callback_query(F.data == "salawat_counter_view")
async def cb_salawat_counter(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    count = user.get("active_salawat_count", 0)
    goal = user.get("active_salawat_goal", 33)
    goal_str = str(goal) if goal < 999990 else "∞"

    text = (
        "✨ <b>Салават на Пророка ﷺ</b>\n\n"
        f"Счетчик: <b>{count} / {goal_str}</b>\n\n"
        "Каждое нажатие мгновенно сохраняется в базе данных 🤍"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Нажать Салават (+1)", callback_data="salawat_inc")],
        [InlineKeyboardButton(text="🔄 Сбросить", callback_data="salawat_reset")],
        [InlineKeyboardButton(text="⬅️ К выбору целей", callback_data="rem_salawat")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "salawat_inc")
async def cb_salawat_increment(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    count = user.get("active_salawat_count", 0) + 1
    db.update_user(callback.from_user.id, {"active_salawat_count": count})

    date_str = db.get_user_local_date(user)
    prog = db.get_today_progress(user["id"], date_str)
    current_total_salawat = prog.get("salawat_count", 0) + 1
    db.update_daily_progress(user["id"], date_str, {"salawat_count": current_total_salawat})

    await cb_salawat_counter(callback)

@dp.callback_query(F.data == "salawat_reset")
async def cb_salawat_reset(callback: types.CallbackQuery):
    db.update_user(callback.from_user.id, {"active_salawat_count": 0})
    await callback.answer("Счетчик салаватов сброшен.", show_alert=True)
    await cb_salawat_counter(callback)

# 3. АЗКАРЫ (Раздельные: Утренние и Вечерние)
@dp.callback_query(F.data == "rem_azkar_morning")
async def cb_morning_adhkar(callback: types.CallbackQuery):
    text = (
        "🌅 <b>Утренние азкары</b> (после Фаджра)\n\n"
        "• Аят аль-Курси — 1 раз.\n"
        "• Три последние суры — по 3 раза.\n"
        "• Формула начала утра и Сейид аль-истигфар."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить как выполненные", callback_data="mark_morning_done")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_remind_dua")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "mark_morning_done")
async def cb_mark_morning(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(callback.from_user.id, date_str, {"morning_adhkar_done": True})
    await callback.answer("Утренние азкары успешно зафиксированы! 🤍", show_alert=True)
    await cb_back_to_remind_dua(callback)

@dp.callback_query(F.data == "rem_azkar_evening")
async def cb_evening_adhkar(callback: types.CallbackQuery):
    text = (
        "🌆 <b>Вечерние азкары</b> (после Магриба)\n\n"
        "• Аят аль-Курси — 1 раз.\n"
        "• Три последние суры — по 3 раза.\n"
        "• Формула начала вечера и Сейид аль-истигфар."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить как выполненные", callback_data="mark_evening_done")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_remind_dua")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "mark_evening_done")
async def cb_mark_evening(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(callback.from_user.id, date_str, {"evening_adhkar_done": True})
    await callback.answer("Вечерние азкары успешно зафиксированы! 🤍", show_alert=True)
    await cb_back_to_remind_dua(callback)


# ==================== ВРЕМЯ НАМАЗОВ ====================

@dp.message(F.text == "⏰ Время намазов")
async def menu_prayer_times(message: types.Message):
    user = db.get_or_create_user(message.from_user.id)
    city = user.get("city", "Нерюнгри")
    times = await fetch_prayer_times(city)
    next_p = get_next_prayer(times)
    
    text = (
        f"🕌 <b>Время намазов для г. {city}</b>\n\n"
        f"⏳ Ближайший намаз: <b>{next_p}</b>\n\n"
        f"• Фаджр: {times['Фаджр']}\n"
        f"• Восход солнца: {times['Восход']}\n"
        f"• Зухр: {times['Зухр']}\n"
        f"• Аср: {times['Аср']}\n"
        f"• Магриб: {times['Магриб']}\n"
        f"• Иша: {times['Иша']}\n\n"
        f"<i>«Воистину, намаз предписан верующим в определенное время».</i>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_reply_keyboard())


# ==================== РАЗДЕЛ «МОЙ ПУТЬ» (МУДАЛЯМА) ====================

@dp.message(F.text == "📊 Мой путь")
async def menu_my_path(message: types.Message):
    text = "📊 <b>Мой путь (Мудаляма)</b>\n\nВыберите интересующий вас раздел:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌙 Сводка дня", callback_data="path_daily_summary")],
        [InlineKeyboardButton(text="📈 История поклонения", callback_data="path_history")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "path_daily_summary")
async def cb_path_summary(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    date_str = db.get_user_local_date(user)
    prog = db.get_today_progress(user["id"], date_str)
    
    morning_str = "✅ Прочитаны" if prog.get('morning_adhkar_done', False) else "⏳ В процессе"
    evening_str = "✅ Прочитаны" if prog.get('evening_adhkar_done', False) else "⏳ В процессе"
    
    text = (
        "🌙 <b>Сводка дня (Сегодня)</b>:\n\n"
        f"• Дата: {date_str}\n"
        f"• Намазы: {'✅ Выполнены' if prog.get('fajr_done') else '⏳ В процессе'}\n"
        f"• Тасбих: {prog.get('tasbih_count', 0)} раз\n"
        f"• Салават: {prog.get('salawat_count', 0)} раз\n"
        f"• Утренние азкары: {morning_str}\n"
        f"• Вечерние азкары: {evening_str}\n"
        f"• Коран: {prog.get('quran_progress', 'Не записано')}\n"
        f"• Книги: {prog.get('books_pages', 0)} стр.\n"
        f"• Шаги: {prog.get('activity_steps', 0)}\n"
        f"• Спорт: {prog.get('sport_minutes', 0)} мин.\n\n"
        "Пусть Аллах примет ваши труды 🤍"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="path_back_main")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "path_history")
async def cb_path_history(callback: types.CallbackQuery):
    text = (
        "📈 <b>История поклонения</b>\n\n"
        "Здесь хранится ваш бессрочный архив достижений за недели, месяцы и годы. "
        "База устроена так, что ни одно усилие, ни один зикр или шаг не стираются со временем 🤍"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="path_back_main")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "path_back_main")
async def cb_path_back(callback: types.CallbackQuery):
    text = "📊 <b>Мой путь (Мудаляма)</b>\n\nВыберите интересующий вас раздел:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌙 Сводка дня", callback_data="path_daily_summary")],
        [InlineKeyboardButton(text="📈 История поклонения", callback_data="path_history")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


# ==================== ЗАБОТА О ТЕЛЕ И ДУХЕ (4 НАПРАВЛЕНИЯ) ====================

@dp.message(F.text == "⛳️ Активность")
async def menu_activity(message: types.Message):
    text = (
        "⛳️ <b>Забота о теле и духе</b>\n\n"
        "«Наше тело — это аманат (доверие) от Всевышнего, а здоровье дает силы для благого». Что запишем в дневник сегодня?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Коран", callback_data="act_quran"),
         InlineKeyboardButton(text="📚 Книга", callback_data="act_book")],
        [InlineKeyboardButton(text="🚶‍♂️ Шаги", callback_data="act_walk"),
         InlineKeyboardButton(text="🏃‍♀️ Спорт", callback_data="act_sport")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "act_quran")
async def cb_act_quran(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ActivityStates.waiting_for_quran)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="act_back_main")]])
    await callback.message.edit_text("📖 Напишите, какую суру или аяты вы прочитали сегодня:", parse_mode="HTML", reply_markup=kb)

@dp.message(ActivityStates.waiting_for_quran)
async def process_quran_input(message: types.Message, state: FSMContext):
    quran_info = message.text.strip()
    user = db.get_or_create_user(message.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(message.from_user.id, date_str, {"quran_progress": quran_info})
    await state.clear()
    await message.answer(f"✅ Машаллаh! Записано чтение Корана: <b>{quran_info}</b> 🤍", parse_mode="HTML", reply_markup=get_main_reply_keyboard())

@dp.callback_query(F.data == "act_book")
async def cb_act_book(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ActivityStates.waiting_for_book)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="act_back_main")]])
    await callback.message.edit_text("📚 Сколько страниц книги вы прочитали сегодня? (введите число):", parse_mode="HTML", reply_markup=kb)

@dp.message(ActivityStates.waiting_for_book)
async def process_book_input(message: types.Message, state: FSMContext):
    try:
        pages = int(message.text.strip())
    except ValueError:
        await message.answer("Пожалуйста, введите количество страниц числом:")
        return
    user = db.get_or_create_user(message.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(message.from_user.id, date_str, {"books_pages": pages})
    await state.clear()
    await message.answer(f"✅ Альхамдулиллах! Записано страниц книги: <b>{pages}</b> 🤍", parse_mode="HTML", reply_markup=get_main_reply_keyboard())

@dp.callback_query(F.data == "act_walk")
async def cb_act_walk(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ActivityStates.waiting_for_steps)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="act_back_main")]])
    await callback.message.edit_text("🚶‍♂️ Отправьте количество ваших шагов за сегодня цифрами:", parse_mode="HTML", reply_markup=kb)

@dp.message(ActivityStates.waiting_for_steps)
async def process_steps_input(message: types.Message, state: FSMContext):
    try:
        steps = int(message.text.strip())
    except ValueError:
        await message.answer("Пожалуйста, введите число шагов цифрами:")
        return
    user = db.get_or_create_user(message.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(message.from_user.id, date_str, {"activity_steps": steps})
    await state.clear()
    await message.answer(f"✅ Машаллаh! Записано шагов: <b>{steps}</b> 🤍", parse_mode="HTML", reply_markup=get_main_reply_keyboard())

@dp.callback_query(F.data == "act_sport")
async def cb_act_sport(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ActivityStates.waiting_for_sport)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="act_back_main")]])
    await callback.message.edit_text("🏃‍♀️ Напишите время тренировки в минутах (например: <i>30</i>):", parse_mode="HTML", reply_markup=kb)

@dp.message(ActivityStates.waiting_for_sport)
async def process_sport_input(message: types.Message, state: FSMContext):
    try:
        minutes = int(message.text.strip())
    except ValueError:
        await message.answer("Пожалуйста, введите минуты числом:")
        return
    user = db.get_or_create_user(message.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(message.from_user.id, date_str, {"sport_minutes": minutes})
    await state.clear()
    await message.answer(f"💪 Альхамдулиллах! Тренировка сохранена: <b>{minutes} мин.</b> 🤍", parse_mode="HTML", reply_markup=get_main_reply_keyboard())

@dp.callback_query(F.data == "act_back_main")
async def cb_act_back(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "⛳️ <b>Забота о теле и духе</b>\n\n"
        "«Наше тело — это аманат (доверие) от Всевышнего, а здоровье дает силы для благого». Что запишем в дневник сегодня?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Коран", callback_data="act_quran"),
         InlineKeyboardButton(text="📚 Книга", callback_data="act_book")],
        [InlineKeyboardButton(text="🚶‍♂️ Шаги", callback_data="act_walk"),
         InlineKeyboardButton(text="🏃‍♀️ Спорт", callback_data="act_sport")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


# ==================== АКТУАЛЬНЫЙ РЕЖИМ И ДЕЛИКАТНАЯ ПАУЗА ====================

@dp.message(F.text == "⚙️ Актуальный режим")
async def menu_settings(message: types.Message):
    user = db.get_or_create_user(message.from_user.id)
    level = user.get("current_level", "Аль-Фард")
    city = user.get("city", "Не указан")
    is_paused = user.get("pause_mode", False)
    pause_reason = user.get("pause_reason", "Пауза")

    if is_paused:
        if pause_reason == "Особенные дни":
            desc_pause = (
                f"🌸 <b>Деликатная пауза активна: {pause_reason}</b>\n\n"
                "Уведомления временно приостановлены для вашего комфорта. При этом ведение учета (Коран, книги, шаги, спорт, тасбих, салават) полностью доступно 🤍\n\n"
                "Ваш прогресс и серия дней в абсолютной безопасности."
            )
        elif pause_reason == "Заболел(а)":
            desc_pause = (
                f"🌸 <b>Деликатная пауза активна: {pause_reason}</b>\n\n"
                "Желаем скорейшего выздоровления и крепкого здоровья! Пусть эта болезнь станет очищением. Отдыхайте, набирайтесь сил, а когда будете готовы — в любое время сможете восстановить режим и продолжить путь 🤍\n\n"
                "Ваш прогресс и серия дней в абсолютной безопасности."
            )
        elif pause_reason == "Времени нет":
            desc_pause = (
                f"🌸 <b>Деликатная пауза активна: {pause_reason}</b>\n\n"
                "Мы понимаем, что мирские хлопоты и дела занимают много времени, но помните: эта мирская жизнь — лишь временное пристанище. В ахирате нас спасет именно намаз и наши благие деяния. Берегите связь со Всевышним 🤍\n\n"
                "Ваш прогресс и серия дней в безопасности. Восстановить режим можно в любой момент."
            )
        elif pause_reason == "Просто отдых":
            desc_pause = (
                f"🌸 <b>Деликатная пауза активна: {pause_reason}</b>\n\n"
                "Иногда душе нужна пауза от мирской суеты, чтобы собраться с силами. Но помните: истинный покой и исцеление сердца обретаются лишь в поминании Всевышнего («Воистину, поминанием Аллаха успокаиваются сердца», сура Ар-Рад, 28).\n\n"
                "Отдыхайте бережно, но пусть ваше сердце не уходит в беспечность. Ваш прогресс и путь постоянства под надежной защитой 🤍"
            )
        else:
            desc_pause = f"🌸 <b>Деликатная пауза активна</b>\n\nСтатус: <b>{pause_reason}</b>"

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✨ Восстановить режим / Завершить паузу", callback_data="pause_restore")],
            [InlineKeyboardButton(text="🌸 Сменить причину паузы", callback_data="settings_pause")]
        ])
        sent_msg = await message.answer(desc_pause, parse_mode="HTML", reply_markup=kb)
        
        # Автоматическое закрепление вверху чата
        try:
            await message.bot.pin_chat_message(chat_id=message.chat.id, message_id=sent_msg.message_id)
        except Exception as e:
            logging.error(f"Не удалось закрепить сообщение паузы: {e}")
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
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="settings_back_main")]])
    await callback.message.edit_text("🏙️ Введите название нового города на кириллице:", parse_mode="HTML", reply_markup=kb)

@dp.message(SettingsStates.waiting_for_new_city)
async def process_new_city(message: types.Message, state: FSMContext):
    new_city = message.text.strip()
    db.update_user(message.from_user.id, {"city": new_city})
    await state.clear()
    await message.answer(f"✅ Город успешно изменен на <b>{new_city}</b>!", parse_mode="HTML", reply_markup=get_main_reply_keyboard())

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
    text = "🌸 <b>Деликатная пауза</b>\n\nВыберите причину паузы. Ваш прогресс и серия дней в абсолютной безопасности:"
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
        try:
            await callback.bot.unpin_chat_message(chat_id=callback.message.chat.id)
        except Exception:
            pass
        await callback.message.edit_text("🤍 С возвращением! Режим паузы завершен, ваш активный путь продолжается с новыми силами.", parse_mode="HTML")
        return

    reasons = {
        "pause_special": "Особенные дни",
        "pause_sick": "Заболел(а)",
        "pause_busy": "Времени нет",
        "pause_rest": "Просто отдых"
    }
    reason_text = reasons.get(callback.data, "Пауза")
    db.update_user(callback.from_user.id, {"pause_mode": True, "pause_reason": reason_text})
    
    if callback.data == "pause_special":
        desc = (
            f"🌸 <b>Деликатная пауза: {reason_text}</b>\n\n"
            "Уведомления временно приостановлены для вашего комфорта. При этом ведение учета (Коран, книги, шаги, спорт, тасбих, салават) полностью доступно 🤍\n\n"
            "Ваш прогресс и серия дней в абсолютной безопасности."
        )
    elif callback.data == "pause_sick":
        desc = (
            f"🌸 <b>Деликатная пауза: {reason_text}</b>\n\n"
            "Желаем скорейшего выздоровления и крепкого здоровья! Пусть эта болезнь станет очищением. Отдыхайте, набирайтесь сил 🤍"
        )
    elif callback.data == "pause_busy":
        desc = (
            f"🌸 <b>Деликатная пауза: {reason_text}</b>\n\n"
            "Мы понимаем, что мирские хлопоты занимают много времени, но помните: эта жизнь — лишь временное пристанище. В ахирате нас спасет намаз и благие деяния 🤍"
        )
    elif callback.data == "pause_rest":
        desc = (
            f"🌸 <b>Деликатная пауза: {reason_text}</b>\n\n"
            "Иногда душе нужна пауза от мирской суеты. Но помните: истинный покой сердца обретается лишь в поминании Всевышнего («Воистину, поминанием Аллаха успокаиваются сердца», сура Ар-Рад, 28). Отдыхайте бережно 🤍"
        )
    else:
        desc = f"🌸 <b>Деликатная пауза: {reason_text}</b>"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Восстановить режим / Завершить паузу", callback_data="pause_restore")],
        [InlineKeyboardButton(text="🌸 Сменить причину паузы", callback_data="settings_pause")]
    ])
    await callback.message.edit_text(desc, parse_mode="HTML", reply_markup=kb)
    
    # Автоматическое закрепление вверху чата
    try:
        await callback.bot.pin_chat_message(chat_id=callback.message.chat.id, message_id=callback.message.message_id)
    except Exception as e:
        logging.error(f"Не удалось закрепить сообщение паузы: {e}")

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


# ==================== ЗАПУСК ВЕБ-СЕРВЕРА ДЛЯ RENDER ====================
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
        webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
        webhook_requests_handler.register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
        dp.startup.register(on_startup)

    logging.info(f"Starting web server on port {PORT}...")
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
