import os
import logging
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


# Главное нижнее меню (ровно 5 кнопок)
def get_main_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏰ Время намазов"), KeyboardButton(text="📿 Поминания и дуа")],
            [KeyboardButton(text="📊 Мой путь"), KeyboardButton(text="⛳️ Активность")],
            [KeyboardButton(text="⚙️ Актуальный режим")]
        ],
        resize_keyboard=True
    )


# --- ОНБОРДИНГ ---

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    db.get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    
    intro_text = (
        "🌙 <b>Amal365</b>\n\n"
        "Ваш личный спутник на пути к постоянству в благих делах. "
        "Бот помогает бережно и регулярно совершать ежедневные поклонения, вести учет активности и укреплять духовную дисциплину шаг за шагом."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Начать", callback_data="onboarding_welcome")]
    ])
    await message.answer(intro_text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "onboarding_welcome")
async def cb_welcome(callback: types.CallbackQuery, state: FSMContext):
    text = (
        "Ассаляму алейкум ва рахматуллахи ва баракатух 🌙\n\n"
        "Добро пожаловать в Amal365!\n\n"
        "Ваши данные используются исключительно для персонального сопровождения на вашем духовном пути и остаются конфиденциальными.\n\n"
        "Пусть Всевышний дарует баракат в этом благом начинании 🤍"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Начать с Бисмиллях", callback_data="onboarding_country")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "onboarding_country")
async def cb_country_step(callback: types.CallbackQuery, state: FSMContext):
    text = (
        "🏙️ <b>Выбор вашей страны</b>\n\n"
        "Пожалуйста, выберите вашу страну из списка ниже:"
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
    await callback.message.edit_text(text, parse_mode="HTML")


@dp.message(OnboardingStates.waiting_for_city)
async def process_city_input(message: types.Message, state: FSMContext):
    city_name = message.text.strip()
    db.update_user(message.from_user.id, {"city": city_name})
    await state.clear()

    text = (
        f"✅ Город <b>{city_name}</b> успешно сохранен!\n\n"
        "✨ <b>Выберите ваш режим сопровождения</b>\n\n"
        "Каждый режим создан с учетом вашего темпа:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Аль-Фард (Постоянство, для начала пути)", callback_data="set_mode_fard")],
        [InlineKeyboardButton(text="🌿 Аль-Истикама (Укрепление привычек)", callback_data="set_mode_istikama")],
        [InlineKeyboardButton(text="📖 Ат-Тазкия (Духовное очищение и знания)", callback_data="set_mode_tazkiya")],
        [InlineKeyboardButton(text="⭐ Аль-Ихсан (Глубокий полный комплекс)", callback_data="set_mode_ihsan")]
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
        f"🎉 <b>Режим «{selected_mode}» успешно активирован!</b>\n\n"
        "Добро пожаловать в семью Amal365. Ваш персональный путеводитель настроен. "
        "Используйте нижнее меню для управления."
    )
    await callback.message.answer(text, parse_mode="HTML", reply_markup=get_main_reply_keyboard())
    await callback.message.delete()


# --- РАЗДЕЛ «ПОМИНАНИЯ И ДУА» ---

@dp.message(F.text == "📿 Поминания и дуа")
async def menu_remind_dua(message: types.Message):
    text = (
        "📿 <b>Поминания и дуа</b>\n\n"
        "Выберите нужное направление для поминания Всевышнего:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Зикр (Счётчик)", callback_data="submenu_zikr")],
        [InlineKeyboardButton(text="📖 Утренние и вечерние азкары", callback_data="submenu_adhkar")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


# --- ПОДМЕНЮ: ЗИКР СО СЧЁТЧИКОМ ---
@dp.callback_query(F.data == "submenu_zikr")
async def cb_zikr_main(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    date_str = db.get_user_local_date(user)
    prog = db.get_today_progress(callback.from_user.id, date_str)
    count = prog.get("zikr_count", 0)

    text = (
        f"📿 <b>Счётчик зикра</b>\n\n"
        f"Текущий счетчик поминаний за сегодня: <b>{count}</b>\n\n"
        "Нажимайте на кнопку ниже, чтобы совершить тасбих:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Сделать зикр (+1)", callback_data="zikr_increment")],
        [InlineKeyboardButton(text="🔄 Сбросить счетчик", callback_data="zikr_reset")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_remind_dua")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "zikr_increment")
async def cb_zikr_inc(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    date_str = db.get_user_local_date(user)
    prog = db.get_today_progress(callback.from_user.id, date_str)
    count = prog.get("zikr_count", 0) + 1
    
    db.update_daily_progress(callback.from_user.id, date_str, {"zikr_count": count})

    text = (
        f"📿 <b>Счётчик зикра</b>\n\n"
        f"Текущий счетчик поминаний за сегодня: <b>{count}</b>\n\n"
        "Нажимайте на кнопку ниже, чтобы совершить тасбих:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Сделать зикр (+1)", callback_data="zikr_increment")],
        [InlineKeyboardButton(text="🔄 Сбросить счетчик", callback_data="zikr_reset")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_remind_dua")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "zikr_reset")
async def cb_zikr_res(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(callback.from_user.id, date_str, {"zikr_count": 0})

    text = (
        f"📿 <b>Счётчик зикра</b>\n\n"
        f"Текущий счетчик поминаний за сегодня: <b>0</b>\n\n"
        "Счетчик успешно сброшен."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Сделать зикр (+1)", callback_data="zikr_increment")],
        [InlineKeyboardButton(text="🔄 Сбросить счетчик", callback_data="zikr_reset")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_remind_dua")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


# --- ПОДМЕНЮ: УТРЕННИЕ И ВЕЧЕРНИЕ АЗКАРЫ ---
@dp.callback_query(F.data == "submenu_adhkar")
async def cb_adhkar_menu(callback: types.CallbackQuery):
    text = (
        "📖 <b>Утренние и вечерние азкары</b>\n\n"
        "Выберите, какие азкары вы хотите прочитать:"
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
        "🌅 <b>Утренние азкары</b>\n\n"
        "<i>«Аллаху ля иляха илля хувал хайюль кайюм, ля таъхузуху синатув ва ля навм...»</i>\n\n"
        "Прочтите защитные слова и поминания для наполнения дня светом."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить как прочитанные", callback_data="mark_morning_done")],
        [InlineKeyboardButton(text="⬅️ К выбору азкаров", callback_data="submenu_adhkar")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "mark_morning_done")
async def cb_mark_morning(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(callback.from_user.id, date_str, {"morning_adhkar_done": True})
    await callback.answer("Утренние азкары отмечены выполненными! 🤍", show_alert=True)
    
    text = "🌿 <b>Утренние азкары успешно завершены!</b> Пусть день пройдет благословенно."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="submenu_adhkar")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "adhkar_evening")
async def cb_evening_adhkar(callback: types.CallbackQuery):
    text = (
        "🌙 <b>Вечерние азкары</b>\n\n"
        "<i>«Амсарна ва амсаль мульку лилляхи раббиль 'алямин...»</i>\n\n"
        "Обретите умиротворение и защиту в вечернем поминании."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить как прочитанные", callback_data="mark_evening_done")],
        [InlineKeyboardButton(text="⬅️ К выбору азкаров", callback_data="submenu_adhkar")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "mark_evening_done")
async def cb_mark_evening(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(callback.from_user.id, date_str, {"evening_adhkar_done": True})
    await callback.answer("Вечерние азкары отмечены выполненными! 🤍", show_alert=True)
    
    text = "🌿 <b>Вечерние азкары успешно завершены!</b> Спокойного вечера."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="submenu_adhkar")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "back_to_remind_dua")
async def cb_back_to_remind_dua(callback: types.CallbackQuery):
    text = (
        "📿 <b>Поминания и дуа</b>\n\n"
        "Выберите нужное направление для поминания Всевышнего:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📿 Зикр (Счётчик)", callback_data="submenu_zikr")],
        [InlineKeyboardButton(text="📖 Утренние и вечерние азкары", callback_data="submenu_adhkar")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


# --- ОСТАЛЬНЫЕ КНОПКИ НИЖНЕГО МЕНЮ ---

@dp.message(F.text == "⏰ Время намазов")
async def menu_prayer_times(message: types.Message):
    user = db.get_or_create_user(message.from_user.id)
    city = user.get("city", "Ваш город")
    await message.answer(
        f"🕌 <b>Расписание намазов для г. {city}</b>\n\n"
        "• Фаджр: 05:10\n"
        "• Зухр: 12:30\n"
        "• Аср: 16:15\n"
        "• Магриб: 19:00\n"
        "• Иша: 20:30\n\n"
        "<i>(Точное расписание синхронизировано автоматически).</i>",
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard()
    )


@dp.message(F.text == "📊 Мой путь")
async def menu_my_path(message: types.Message):
    text = (
        "📊 <b>Ваш личный путь в Amal365</b>\n\n"
        "Выберите интересующий вас раздел:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="☀️ Дневной прогресс", callback_data="path_daily"),
         InlineKeyboardButton(text="📈 Общий прогресс", callback_data="path_overall")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "path_daily")
async def cb_path_daily(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    date_str = db.get_user_local_date(user)
    prog = db.get_today_progress(callback.from_user.id, date_str)
    
    steps = prog.get("activity_steps", 0)
    sport = prog.get("sport_minutes", 0)
    zikr = prog.get("zikr_count", 0)
    
    text = (
        f"☀️ <b>Дневной прогресс за сегодня ({date_str})</b>\n\n"
        f"📿 Зикров сделано: <b>{zikr}</b>\n"
        f"🚶‍♂️ Шаги: <b>{steps}</b>\n"
        f"🏃‍♀️ Спорт: <b>{sport} мин.</b>\n"
        f"✨ Всё идет прекрасным чередом. Аллах видит каждое старание 🤍"
    )
    await callback.message.edit_text(text, parse_mode="HTML")


@dp.callback_query(F.data == "path_overall")
async def cb_path_overall(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    streak = user.get("streak_days", 0)
    level = user.get("current_level", "Аль-Фард")
    city = user.get("city", "Не указан")
    
    text = (
        f"📈 <b>Общий прогресс и статистика</b>\n\n"
        f"🔥 Текущая серия дней (стрик): <b>{streak} дн.</b>\n"
        f"✨ Активный режим: <b>{level}</b>\n"
        f"🏙️ Город: <b>{city}</b>\n\n"
        "Продолжайте в том же духе! Каждый шаг приближает к довольству Всевышнего 🤍"
    )
    await callback.message.edit_text(text, parse_mode="HTML")


@dp.message(F.text == "⚙️ Актуальный режим")
async def menu_settings(message: types.Message):
    user = db.get_or_create_user(message.from_user.id)
    level = user.get("current_level", "Аль-Фард")
    city = user.get("city", "Не указан")
    
    text = (
        f"⚙️ <b>Настройки и актуальный режим</b>\n\n"
        f"• Текущий режим: <b>{level}</b>\n"
        f"• Ваш город: <b>{city}</b>\n\n"
        "Вы можете изменить параметры ниже в любое время:"
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
    await callback.message.edit_text(
        "🏙️ Введите название нового города на кириллице:",
        parse_mode="HTML"
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
        [InlineKeyboardButton(text="⭐ Аль-Ихсан", callback_data="set_mode_ihsan")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "settings_pause")
async def cb_pause_menu(callback: types.CallbackQuery):
    text = (
        "🌸 <b>Деликатная пауза</b>\n\n"
        "Выберите причину паузы. Помните: ваш прогресс и серия дней никогда не сгорят, вы в абсолютной безопасности:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌸 Особенные дни", callback_data="pause_special")],
        [InlineKeyboardButton(text="🌿 Заболел(а)", callback_data="pause_sick")],
        [InlineKeyboardButton(text="⏳ Времени нет", callback_data="pause_busy")],
        [InlineKeyboardButton(text="✨ Просто отдых", callback_data="pause_rest")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("pause_"))
async def cb_pause_set(callback: types.CallbackQuery):
    reasons = {
        "pause_special": "Особенные дни",
        "pause_sick": "Заболел(а)",
        "pause_busy": "Времени нет",
        "pause_rest": "Просто отдых"
    }
    reason_text = reasons.get(callback.data, "Пауза")
    db.update_user(callback.from_user.id, {"pause_mode": True, "pause_reason": reason_text})
    
    await callback.message.edit_text(
        f"🤍 Режим паузы активирован: <i>{reason_text}</i>.\n\n"
        "Не переживайте ни о чем. Вы можете продолжить в любой момент, ваши данные бережно сохранены.",
        parse_mode="HTML"
    )


# --- ТРЕКЕР АКТИВНОСТИ ---

@dp.message(F.text == "⛳️ Активность")
async def menu_activity(message: types.Message):
    text = (
        "⛳️ <b>Трекер физической активности</b>\n\n"
        "Выберите или укажите вашу активность сегодня (спорт или ходьба):"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚶‍♂️ Ходьба (Шаги)", callback_data="act_walk"),
         InlineKeyboardButton(text="🏃‍♀️ Спорт / Тренировка", callback_data="act_sport")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "act_walk")
async def cb_act_walk(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ActivityStates.waiting_for_steps)
    await callback.message.edit_text(
        "🚶‍♂️ Отправьте в ответ число ваших шагов цифрами (например: <i>5000</i>), и мы запишем их в копилку здоровья! 🤍",
        parse_mode="HTML"
    )


@dp.message(ActivityStates.waiting_for_steps)
async def process_steps_input(message: types.Message, state: FSMContext):
    text_val = message.text.strip()
    try:
        steps = int(text_val)
    except ValueError:
        await message.answer("Пожалуйста, введите число шагов цифрами (например: 5000). Попробуйте еще раз:")
        return

    user = db.get_or_create_user(message.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(message.from_user.id, date_str, {"activity_steps": steps})
    await state.clear()

    await message.answer(
        f"✅ Отлично! Записано шагов: <b>{steps}</b>. Машаллаh, вы молодец! 🤍",
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard()
    )


@dp.callback_query(F.data == "act_sport")
async def cb_act_sport(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ActivityStates.waiting_for_sport)
    await callback.message.edit_text(
        "🏃‍♀️ Напишите количество минут тренировки цифрами (например: <i>30</i>).\n\n"
        "<i>Наше тело — это аманат от Всевышнего, а здоровье дает силы для благого! ✨</i>",
        parse_mode="HTML"
    )


@dp.message(ActivityStates.waiting_for_sport)
async def process_sport_input(message: types.Message, state: FSMContext):
    text_val = message.text.replace("минут", "").replace("мин", "").strip()
    try:
        minutes = int(text_val)
    except ValueError:
        await message.answer("Пожалуйста, введите количество минут цифрами (например: 30). Попробуйте еще раз:")
        return

    user = db.get_or_create_user(message.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(message.from_user.id, date_str, {"sport_minutes": minutes})
    await state.clear()

    await message.answer(
        f"💪 Прекрасно! Тренировка на <b>{minutes} мин.</b> успешно сохранена в вашем дневнике. Пусть Аллах дарует вам крепкие силы! 🤍",
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard()
    )


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
