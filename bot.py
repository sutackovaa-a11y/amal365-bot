import asyncio
import logging
import os
import sys
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv
from aiohttp import web
from database import save_or_update_user, get_user

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

class OnboardingState(StatesGroup):
    waiting_for_mode = State()
    waiting_for_city = State()
    changing_city = State()

dp = Dispatcher()
bot = Bot(token=TOKEN)

# --- КЛАВИАТУРЫ ПО КОНЦЕПЦИИ ---
def get_start_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤲 Начать", callback_data="start_onboarding")]
    ])

def get_bismillah_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Начнём путь с Бисмиллях", callback_data="choose_mode")]
    ])

def get_modes_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Аль-Фард (Обязательное)", callback_data="mode_alfard")],
        [InlineKeyboardButton(text="🌿 Аль-Истикама (Постоянство)", callback_data="mode_alistikama")],
        [InlineKeyboardButton(text="📖 Ат-Тазаккия (Духовный рост)", callback_data="mode_attazkiya")],
        [InlineKeyboardButton(text="⭐ Аль-Ихсан (Гармоничное развитие)", callback_data="mode_alihsan")]
    ])

def get_main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕌 Намаз и маршрут", callback_data="menu_prayers")],
        [InlineKeyboardButton(text="📊 Мой путь", callback_data="menu_path")],
        [InlineKeyboardButton(text="⚙️ Настройки и город", callback_data="menu_settings")],
        [InlineKeyboardButton(text="😊 Вечерняя рефлексия", callback_data="menu_reflection")]
    ])

# --- ХЕНДЛЕРЫ ОНБОРДИНГА ---

@dp.message(CommandStart())
async def cmd_start(message: Message):
    # Очищаем старую клавиатуру
    await message.answer("🌙 Подготовка пространства...", reply_markup=ReplyKeyboardRemove())
    
    save_or_update_user(message.from_user.id, message.from_user.full_name)
    
    text = (
        "🌙 <b>Amal365</b>\n\n"
        "Ваш личный спутник на пути к постоянству в благих делах.\n\n"
        "🕌 Намаз\n"
        "📖 Коран\n"
        "🤲 Азкары\n"
        "📿 Зикр и салават\n"
        "📚 Полезные знания\n"
        "🏃 Физическая активность"
    )
    await message.answer(text, reply_markup=get_start_keyboard(), parse_mode="HTML")

@dp.callback_query(F.data == "start_onboarding")
async def onboarding_step_2(callback: CallbackQuery):
    text = (
        "Ассаляму алейкум ва рахматуллахи ва баракатух 🌙\n\n"
        "Добро пожаловать в Amal365 — Ваш личный спутник на пути к постоянству в благих делах.\n\n"
        "Здесь Вы сможете отмечать намаз, чтение Корана, азкары и другие полезные дела, видеть свой путь и двигаться вперёд шаг за шагом.\n\n"
        "Ваши данные используются только для работы бота и остаются конфиденциальными.\n\n"
        "Пусть Аллах дарует пользу и баракат в этом пути 🤍"
    )
    await callback.message.edit_text(text, reply_markup=get_bismillah_keyboard(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "choose_mode")
async def onboarding_step_3(callback: CallbackQuery, state: FSMContext):
    text = (
        "Выберите этап пути, который ближе вашему сердцу сейчас:\n\n"
        "🌱 <b>Аль-Фард (Обязательное)</b>\n"
        "Основа ежедневной практики.\n\n"
        "🌿 <b>Аль-Истикама (Постоянство)</b>\n"
        "Путь устойчивости и регулярности.\n\n"
        "📖 <b>Ат-Тазаккия (Духовный рост)</b>\n"
        "Укрепление связи со Всевышним.\n\n"
        "⭐ <b>Аль-Ихсан (Гармоничное развитие)</b>\n"
        "Развитие души, знаний и тела."
    )
    await callback.message.edit_text(text, reply_markup=get_modes_keyboard(), parse_mode="HTML")
    await state.set_state(OnboardingState.waiting_for_mode)
    await callback.answer()

@dp.callback_query(OnboardingState.waiting_for_mode, F.data.startswith("mode_"))
async def process_mode_selection(callback: CallbackQuery, state: FSMContext):
    mode_map = {
        "mode_alfard": "alfard",
        "mode_alistikama": "alistikama",
        "mode_attazkiya": "attazkiya",
        "mode_alihsan": "alihsan"
    }
    selected_mode = mode_map.get(callback.data, "alfard")
    save_or_update_user(callback.from_user.id, callback.from_user.full_name, mode=selected_mode)
    await state.set_state(OnboardingState.waiting_for_city)
    
    text = (
        "📍 <b>Выбор города</b>\n\n"
        "Для точного времени намазов и уведомлений напишите название вашего города текстом (например: <i>Нерюнгри</i>, <i>Москва</i>, <i>Алматы</i>, <i>Бишкек</i>)."
    )
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()

@dp.message(OnboardingState.waiting_for_city)
async def process_city_input(message: Message, state: FSMContext):
    city_name = message.text.strip()
    save_or_update_user(message.from_user.id, message.from_user.full_name, city=city_name)
    await state.clear()
    
    text = (
        "Альхамдулиллях 🤍\n\n"
        "Настройка завершена.\n\n"
        "Сегодняшний путь готов."
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌙 Перейти к сегодняшнему дню", callback_data="go_to_main")]
    ])
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@dp.message(OnboardingState.changing_city)
async def process_change_city_input(message: Message, state: FSMContext):
    city_name = message.text.strip()
    save_or_update_user(message.from_user.id, message.from_user.full_name, city=city_name)
    await state.clear()
    
    text = f"Альхамдулиллях 🤍 Новый город <b>{city_name}</b> успешно сохранен!"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌙 В главное меню", callback_data="go_to_main")]
    ])
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

# --- ГЛАВНОЕ МЕНЮ И РАЗДЕЛЫ ---

@dp.callback_query(F.data == "go_to_main")
async def main_menu_handler(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    streak = user.get("streak", 1) if user else 1
    
    text = (
        f"Сегодня Вы стали лучше, чем вчера 🌱\n\n"
        f"🔥 Серия: <b>{streak} дней</b>\n\n"
        "Выберите нужный раздел:"
    )
    await callback.message.edit_text(text, reply_markup=get_main_menu_keyboard(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "menu_prayers")
async def menu_prayers_handler(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    city = user.get("city", "Ваш город") if user else "Ваш город"
    current_time_str = datetime.now().strftime("%H:%M")
    
    text = (
        f"🕌 <b>Намаз и ежедневный маршрут</b>\n"
        f"📍 Город: <b>{city}</b> | ⏰ <code>{current_time_str}</code>\n\n"
        "⏳ <b>До следующего намаза (Зухр):</b> <code>2 ч 15 мин</code>\n\n"
        "🌅 Фаджр — Совершено ✓\n"
        "☀️ Зухр — Ожидает\n"
        " عصر Аср — Ожидает\n"
        "🌇 Магриб — Ожидает\n"
        "🌙 Иша — Ожидает\n\n"
        "📿 Салаваты: 24 / 100\n"
        "🤲 Утренние азкары: Выполнено ✓"
    )
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить Зухр", callback_data="mark_zuhr")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "mark_zuhr")
async def mark_zuhr_handler(callback: CallbackQuery):
    await callback.answer("Зухр отмечен. Пусть Аллах примет Ваш намаз 🤍", show_alert=True)

@dp.callback_query(F.data == "menu_path")
async def menu_path_handler(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    streak = user.get("streak", 1) if user else 1
    city = user.get("city", "Не указан") if user else "Не указан"
    mode = user.get("spiritual_mode", "alfard") if user else "alfard"
    
    text = (
        "📊 <b>Мой путь</b>\n\n"
        f"🔥 Серия: <b>{streak} дней</b>\n"
        f"📍 Город: <b>{city}</b>\n"
        f"🌱 Этап: <b>{mode.upper()}</b>\n\n"
        "🕌 Намазы: 94%\n"
        "📖 Коран: 31 день\n"
        "🤲 Азкары: 27 дней\n"
        "📿 Салаваты: 22 дня\n\n"
        "<i>«Каждый путь состоит не только из шагов вперёд, но и из остановок.»</i> 🤍"
    )
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "menu_settings")
async def menu_settings_handler(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    city = user.get("city", "Не указан") if user else "Не указан"
    text = (
        "⚙️ <b>Настройки и город</b>\n\n"
        f"📍 Текущий город: <b>{city}</b>\n\n"
        "Хотите изменить город для расчета времени намазов?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📍 Изменить город", callback_data="change_city_btn")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "change_city_btn")
async def change_city_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(OnboardingState.changing_city)
    text = "📍 Напишите название нового города текстом:"
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "menu_reflection")
async def menu_reflection_handler(callback: CallbackQuery):
    text = (
        "😊 <b>Вечерняя рефлексия</b>\n\n"
        "Как прошёл сегодняшний день?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😊 Хорошо", callback_data="ref_good"),
         InlineKeyboardButton(text="😐 Обычно", callback_data="ref_normal")],
        [InlineKeyboardButton(text="😔 Тяжело", callback_data="ref_hard")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("ref_"))
async def reflection_result_handler(callback: CallbackQuery):
    choice = callback.data.split("_")[1]
    if choice == "hard":
        resp = "Даже один искренний намаз сегодня имеет огромную ценность перед Аллахом 🤍"
    elif choice == "good":
        resp = "Альхамдулиллях! Пусть Аллах примет ваши благие дела и увеличит баракат 🤍"
    else:
        resp = "Каждый день — это шаг на пути к довольству Всевышнего. Продолжайте в том же духе 🤍"
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌙 В главное меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(f"🌙 <b>Рефлексия сохранена</b>\n\n{resp}", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle(request):
    return web.Response(text="Amal365 Concept Bot is active!")

async def run_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"Веб-сервер запущен на порту {PORT}")

async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    print("Бот Amal365 запущен по финальной концепции...")
    await asyncio.gather(
        run_web_server(),
        dp.start_polling(bot, drop_pending_updates=True)
    )

if __name__ == "__main__":
    asyncio.run(main())
