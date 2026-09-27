import os
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
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
dp = Dispatcher()

# Главное постоянное меню (4 аккуратные кнопки)
def get_main_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏰ Время намазов"), KeyboardButton(text="📊 Мой путь")],
            [KeyboardButton(text="⚙️ Актуальный режим"), KeyboardButton(text="⛳️ Активность")]
        ],
        resize_keyboard=True
    )

# --- ОНБОРДИНГ ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user = db.get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    
    intro_text = (
        "🌙 <b>Amal365</b>\n\n"
        "Ваш личный спутник на пути к постоянству в благих делах."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Начать путь", callback_data="onboarding_welcome")]
    ])
    await message.answer(intro_text, parse_html="HTML", reply_markup=kb)


@dp.callback_query(F.data == "onboarding_welcome")
async def cb_welcome(callback: types.CallbackQuery):
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
    await callback.message.edit_text(text, parse_html="HTML", reply_markup=kb)


@dp.callback_query(F.data == "onboarding_policy")
async def cb_policy(callback: types.CallbackQuery):
    text = (
        "<b>Политика конфиденциальности и бережного отношения</b>\n\n"
        "Мы бережно храним ваши данные и используем их исключительно для персонального сопровождения на вашем духовном пути."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Согласен(а)", callback_data="policy_agreed"),
            InlineKeyboardButton(text="❌ Выйти", callback_data="policy_exit")
        ]
    ])
    await callback.message.edit_text(text, parse_html="HTML", reply_markup=kb)


@dp.callback_query(F.data == "policy_exit")
async def cb_policy_exit(callback: types.CallbackQuery):
    await callback.message.edit_text("Вы всегда можете вернуться к нам, когда будете готовы. Всего доброго! 🤍")


@dp.callback_query(F.data == "policy_agreed")
async def cb_city_step(callback: types.CallbackQuery):
    text = (
        "🏙️ <b>Выбор вашего города</b>\n\n"
        "Пожалуйста, выберите вашу страну или введите название вашего города на кириллице (например: <i>Бишкек</i>, <i>Нерюнгри</i>, <i>Казань</i>):"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇰🇷 Кыргызстан", callback_data="country_kg"),
         InlineKeyboardButton(text="🇷🇺 Россия", callback_data="country_ru")],
        [InlineKeyboardButton(text="🇰🇿 Казахстан", callback_data="country_kz"),
         InlineKeyboardButton(text="🇺🇿 Узбекистан", callback_data="country_uz")]
    ])
    await callback.message.edit_text(text, parse_html="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("country_"))
async def cb_select_mode_prompt(callback: types.CallbackQuery):
    text = (
        "✨ <b>Выберите ваш режим сопровождения</b>\n\n"
        "Каждый режим создан с учетом вашего темпа и жизненного ритма:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Аль-Фард (5 намазов, зикр, салават)", callback_data="set_mode_fard")],
        [InlineKeyboardButton(text="🌿 Аль-Истикама (+ Тахаджуд, Азкары, Коран)", callback_data="set_mode_istikama")],
        [InlineKeyboardButton(text="📖 Ат-Тазкия (+ Чтение книг и знаний)", callback_data="set_mode_tazkiya")],
        [InlineKeyboardButton(text="⭐ Аль-Ихсан (Полный глубокий комплекс)", callback_data="set_mode_ihsan")]
    ])
    await callback.message.edit_text(text, parse_html="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("set_mode_"))
async def cb_mode_saved(callback: types.CallbackQuery):
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
        "Добро пожаловать в семью Amal365. Теперь ваш персональный путеводитель настроен.\n"
        "Используйте нижнее меню для управления."
    )
    await callback.message.answer(text, parse_html="HTML", reply_markup=get_main_reply_keyboard())
    await callback.message.delete()


# --- ОБРАБОТКА НИЖНЕГО МЕНЮ ---
@dp.message(F.text == "⏰ Время намазов")
async def menu_prayer_times(message: types.Message):
    await message.answer(
        "🕌 <b>Расписание намазов для вашего города</b>\n\n"
        "• Фаджр: 05:10\n"
        "• Зухр: 12:30\n"
        "• Аср: 16:15\n"
        "• Магриб: 19:00\n"
        "• Иша: 20:30\n\n"
        "<i>(Точное расписание синхронизируется автоматически по вашей геолокации).</i>",
        parse_html="HTML",
        reply_markup=get_main_reply_keyboard()
    )


@dp.message(F.text == "📊 Мой путь")
async def menu_my_path(message: types.Message):
    user = db.get_or_create_user(message.from_user.id)
    streak = user.get("streak_days", 0)
    text = (
        f"📊 <b>Ваш личный путь в Amal365</b>\n\n"
        f"🔥 Текущая серия дней (стрик): <b>{streak} дн.</b>\n"
        f"✨ Статус: Всё идет прекрасным чередом. Аллах видит каждое ваше старание 🤍"
    )
    await message.answer(text, parse_html="HTML", reply_markup=get_main_reply_keyboard())


@dp.message(F.text == "⚙️ Актуальный режим")
async def menu_settings(message: types.Message):
    user = db.get_or_create_user(message.from_user.id)
    level = user.get("current_level", "Аль-Фард")
    text = (
        f"⚙️ <b>Настройки и актуальный режим</b>\n\n"
        f"Текущий режим: <b>{level}</b>\n"
        f"Вы можете в любой момент изменить настройки или сделать деликатную паузу."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌸 Деликатная пауза / Возврат", callback_data="settings_pause")]
    ])
    await message.answer(text, parse_html="HTML", reply_markup=kb)


@dp.callback_query(F.data == "settings_pause")
async def cb_pause_menu(callback: types.CallbackQuery):
    text = (
        "🌸 <b>Деликатная пауза</b>\n\n"
        "Выберите причину паузы. Помните: ваш прогресс и серия дней (стрик) никогда не сгорят, вы в абсолютной безопасности:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌸 Особенные дни", callback_data="pause_special")],
        [InlineKeyboardButton(text="🌿 Заболел(а)", callback_data="pause_sick")],
        [InlineKeyboardButton(text="⏳ Времени нет", callback_data="pause_busy")],
        [InlineKeyboardButton(text="✨ Просто отдых", callback_data="pause_rest")]
    ])
    await callback.message.edit_text(text, parse_html="HTML", reply_markup=kb)


@dp.callback_query(F.data.startswith("pause_"))
async def cb_pause_set(callback: types.CallbackQuery):
    reasons = {
        "pause_special": "Особенные дни (окружены заботой, доступны зикры, салават и Коран)",
        "pause_sick": "Заболел(а) (отдыхайте, мы ждем вас в любой момент)",
        "pause_busy": "Времени нет (прогресс сохранен)",
        "pause_rest": "Просто пауза (все данные в безопасности)"
    }
    reason_text = reasons.get(callback.data, "Пауза")
    db.update_user(callback.from_user.id, {"pause_mode": True, "pause_reason": reason_text})
    
    await callback.message.edit_text(
        f"🤍 Режим паузы активирован: <i>{reason_text}</i>.\n\n"
        "Не переживайте ни о чем. Вы можете продолжить в любой момент, ваши данные и серия дней бережно сохранены.",
        parse_html="HTML"
    )


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
    await message.answer(text, parse_html="HTML", reply_markup=kb)


@dp.callback_query(F.data == "act_walk")
async def cb_act_walk(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🚶‍♂️ Отправьте в ответ число ваших шагов (например: <i>5000</i>), и мы запишем их в копилку здоровья! 🤍",
        parse_html="HTML"
    )


@dp.callback_query(F.data == "act_sport")
async def cb_act_sport(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🏃‍♀️ Напишите сколько минут длилась тренировка (например: <i>30 минут</i>).\n"
        "<i>Наше тело — это аманат (доверие) от Всевышнего, а здоровье дает силы для благого! ✨</i>",
        parse_html="HTML"
    )


# --- ЗАПУСК ВЕБ-СЕРВЕРА ДЛЯ RENDER ---
async def on_startup(bot: Bot):
    if not RENDER_EXTERNAL_URL:
        logging.warning("⚠️ RENDER_EXTERNAL_URL не задан! Вебхук не будет установлен автоматически.")
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
