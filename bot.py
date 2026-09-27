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


# --- ОНБОРДИНГ ---

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    db.get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    
    intro_text = (
        "🌙 <b>Amal365</b>\n\n"
        "Ваш личный спутник на пути к постоянству в благих делах.\n"
        "Бот помогает бережно и регулярно совершать ежедневные поклонения, вести учёт активности и укреплять духовную дисциплину шаг за шагом."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Начать", callback_data="onboarding_welcome")]
    ])
    await message.answer(intro_text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "onboarding_welcome")
async def cb_welcome(callback: types.CallbackQuery, state: FSMContext):
    text = (
        "Ассаляму алейкум ва рахматуллахи ва баракатух 🌙\n\n"
        "Добро пожаловать в <b>Amal365</b>.\n\n"
        "Amal365 помогает сохранять постоянство в благих делах и двигаться вперёд шаг за шагом.\n\n"
        "Ваши данные используются только для работы бота и остаются конфиденциальными.\n\n"
        "Пусть Аллах дарует пользу и баракат в этом пути 🤍"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Начнём путь с Бисмиллях", callback_data="onboarding_policy")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "onboarding_policy")
async def cb_policy(callback: types.CallbackQuery, state: FSMContext):
    text = (
        "📜 <b>Политика конфиденциальности и бережного отношения</b>\n\n"
        "Мы надежно защищаем ваши данные и используем их исключительно для персонального сопровождения."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Согласен(а)", callback_data="policy_agreed"),
            InlineKeyboardButton(text="❌ Выйти", callback_data="policy_exit")
        ]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


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
    await callback.message.edit_text(text, parse_mode="HTML")


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
        f"🤍 <b>Режим «{selected_mode}» успешно активирован!</b>\n\n"
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
        "Выберите форму поминания или начните круговой тасбих:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Начать тасбих (Субханаллах и др.)", callback_data="tasbih_start")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_remind_dua")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "tasbih_start")
async def cb_tasbih_counter(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    current_type = user.get("active_tasbih_type", "subhanallah")
    count = user.get("active_tasbih_count", 0)

    names = {
        "subhanallah": "Субханаллах (سبحان الله)",
        "alhamdulillah": "Альхамдулиллях (الحمد لله)",
        "allahuakbar": "Аллаху Акбар (الله أكبر)",
        "astaghfirullah": "Астагфируллах (أستغفر الله)",
        "salawat": "Салават на Пророка ﷺ"
    }

    text = (
        f"📿 <b>Интерактивный Тасбих</b>\n\n"
        f"Текущий этап: <b>{names.get(current_type, 'Зикр')}</b>\n"
        f"Счетчик: <b>{count} / 33</b>\n\n"
        "Нажимайте на кнопку ниже с каждым произнесением:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Сделать поминание (+1)", callback_data="tasbih_inc")],
        [InlineKeyboardButton(text="🔄 Сбросить / Начать заново", callback_data="tasbih_reset")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="submenu_zikr")]
    ])
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)


@dp.callback_query(F.data == "tasbih_inc")
async def cb_tasbih_increment(callback: types.CallbackQuery):
    user = db.get_or_create_user(callback.from_user.id)
    count = user.get("active_tasbih_count", 0) + 1
    current_type = user.get("active_tasbih_type", "subhanallah")

    # Автоматическое переключение этапов по достижении 33
    if count >= 33:
        stages = ["subhanallah", "alhamdulillah", "allahuakbar", "astaghfirullah", "salawat"]
        try:
            next_idx = stages.index(current_type) + 1
            if next_idx < len(stages):
                current_type = stages[next_idx]
                count = 0
                db.update_user(callback.from_user.id, {"active_tasbih_type": current_type, "active_tasbih_count": 0})
                await callback.answer("Альхамдулиллах! Переходим к следующему поминанию 🤍", show_alert=True)
            else:
                db.update_user(callback.from_user.id, {"active_tasbih_type": "subhanallah", "active_tasbih_count": 0})
                await callback.answer("Круг поминаний успешно завершен! Пусть Аллах примет его 🤍", show_alert=True)
                return cb_zikr_main(callback)
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
        "🌅 <b>Утренние азкары</b>\n\n"
        "<i>«Аллаху ля иляха илля хувал хайюль кайюм...»</i>\n\n"
        "Прочтите защитные слова для наполнения дня светом."
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
        "🌙 <b>Вечерние азкары</b>\n\n"
        "<i>«Амсарна ва амсаль мульку лилляхи раббиль 'алямин...»</i>\n\n"
        "Обретите умиротворение в вечернем поминании."
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
    city = user.get("city", "Ваш город")
    await message.answer(
        f"🕌 <b>Время намазов для г. {city}</b>\n\n"
        "• Фаджр: 05:10\n"
        "• Зухр: 12:30\n"
        "• Аср: 16:15\n"
        "• Магриб: 19:00\n"
        "• Иша: 20:30\n\n"
        "<i>«Воистину, намаз предписан верующим в определенное время».</i>",
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard()
    )


@dp.message(F.text == "📊 Мой путь")
async def menu_my_path(message: types.Message):
    user = db.get_or_create_user(message.from_user.id)
    streak = user.get("streak_days", 0)
    level = user.get("current_level", "Аль-Фард")
    
    text = (
        f"📊 <b>Ваш духовный путь</b>\n\n"
        f"🔥 Непрерывная серия дней (стрик): <b>{streak} дн.</b>\n"
        f"✨ Активный режим: <b>{level}</b>\n\n"
        "Самые любимые дела перед Аллахом — те, которые совершаются регулярно 🤍"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_main_reply_keyboard())


@dp.message(F.text == "⚙️ Актуальный режим")
async def menu_settings(message: types.Message):
    user = db.get_or_create_user(message.from_user.id)
    level = user.get("current_level", "Аль-Фард")
    city = user.get("city", "Не указан")
    
    text = (
        f"⚙️ <b>Настройки и актуальный режим</b>\n\n"
        f"• Текущий ритм: <b>{level}</b>\n"
        f"• Ваш город: <b>{city}</b>\n\n"
        "Вы можете изменить параметры ниже:"
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
        "Выберите причину паузы. Ваш прогресс и серия дней в абсолютной безопасности:"
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
        "Отдыхайте со спокойной душой. Когда будете готовы, возвращайтесь — все достижения на месте.",
        parse_mode="HTML"
    )


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
    await callback.message.edit_text(
        "🚶‍♂️ Отправьте в ответ число ваших шагов цифрами (например: <i>5000</i>):",
        parse_mode="HTML"
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
    await callback.message.edit_text(
        "🏃‍♀️ Напишите время тренировки (например: <i>15 минут</i> или <i>1 час</i>):",
        parse_mode="HTML"
    )


@dp.message(ActivityStates.waiting_for_sport)
async def process_sport_input(message: types.Message, state: FSMContext):
    user = db.get_or_create_user(message.from_user.id)
    date_str = db.get_user_local_date(user)
    db.update_daily_progress(message.from_user.id, date_str, {"sport_minutes": 30}) # условно фиксируем
    await state.clear()

    await message.answer(
        f"💪 Альхамдулиллах! Тренировка успешно сохранена. Пусть Аллах дарует вам крепкое здоровье и силы для благих дел! 🤍",
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
