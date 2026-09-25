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

class OnboardingStates(StatesGroup):
    waiting_for_mode = State()
    waiting_for_city = State()
    changing_city = State()
    changing_mode = State()

dp = Dispatcher()
bot = Bot(token=TOKEN)

# --- КЛАВИАТУРЫ ПО КОНЦЕПЦИИ ---

def kb_start():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤲 Начать", callback_data="onboard_2")]
    ])

def kb_bismillah():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✨ Начнём путь с Бисмиллях", callback_data="onboard_modes")]
    ])

def kb_modes():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌱 Аль-Фард (Обязательное)", callback_data="mode_alfard")],
        [InlineKeyboardButton(text="🌿 Аль-Истикама (Постоянство)", callback_data="mode_alistikama")],
        [InlineKeyboardButton(text="📖 Ат-Тазаккия (Духовный рост)", callback_data="mode_attazkiya")],
        [InlineKeyboardButton(text="⭐ Аль-Ихсан (Гармоничное развитие)", callback_data="mode_alihsan")]
    ])

def kb_main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕌 Намаз и маршрут", callback_data="menu_prayers")],
        [InlineKeyboardButton(text="📊 Мой путь", callback_data="menu_path")],
        [InlineKeyboardButton(text="⚙️ Настройки и город", callback_data="menu_settings")],
        [InlineKeyboardButton(text="😊 Вечерняя рефлексия", callback_data="menu_reflection")]
    ])

# --- ОНБОРДИНГ ---

@dp.message(CommandStart())
async def cmd_start(message: Message):
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
    await message.answer(text, reply_markup=kb_start(), parse_mode="HTML")

@dp.callback_query(F.data == "onboard_2")
async def onboard_step_2(callback: CallbackQuery):
    text = (
        "Ассаляму алейкум ва рахматуллахи ва баракатух 🌙\n\n"
        "Добро пожаловать в Amal365 — Ваш личный спутник на пути к постоянству в благих делах.\n\n"
        "Здесь Вы сможете отмечать намаз, чтение Корана, азкары и другие полезные дела, видеть свой путь и двигаться вперёд шаг за шагом.\n\n"
        "Ваши данные используются только для работы бота и остаются конфиденциальными.\n\n"
        "Пусть Аллах дарует пользу и баракат в этом пути 🤍"
    )
    await callback.message.edit_text(text, reply_markup=kb_bismillah(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "onboard_modes")
async def onboard_step_3(callback: CallbackQuery, state: FSMContext):
    text = (
        "<b>Выберите этап пути:</b>\n\n"
        "🌱 <b>Аль-Фард (Обязательное)</b>\nОснова ежедневной практики.\n\n"
        "🌿 <b>Аль-Истикама (Постоянство)</b>\nПуть устойчивости и регулярности.\n\n"
        "📖 <b>Ат-Тазаккия (Духовный рост)</b>\nУкрепление связи со Всевышним.\n\n"
        "⭐ <b>Аль-Ихсан (Гармоничное развитие)</b>\nРазвитие души, знаний и тела."
    )
    await callback.message.edit_text(text, reply_markup=kb_modes(), parse_mode="HTML")
    await state.set_state(OnboardingStates.waiting_for_mode)
    await callback.answer()

@dp.callback_query(OnboardingStates.waiting_for_mode, F.data.startswith("mode_"))
async def process_mode(callback: CallbackQuery, state: FSMContext):
    mode_map = {
        "mode_alfard": "alfard",
        "mode_alistikama": "alistikama",
        "mode_attazkiya": "attazkiya",
        "mode_alihsan": "alihsan"
    }
    selected = mode_map.get(callback.data, "alfard")
    save_or_update_user(callback.from_user.id, callback.from_user.full_name, mode=selected)
    await state.set_state(OnboardingStates.waiting_for_city)
    
    text = (
        "📍 <b>Выбор города</b>\n\n"
        "Для точного времени намазов и уведомлений напишите название вашего города текстом (например: <i>Москва, Алматы, Бишкек, Казань, Нерюнгри</i>)."
    )
    await callback.message.edit_text(text, parse_mode="HTML")
    await callback.answer()

@dp.message(OnboardingStates.waiting_for_city)
async def process_city(message: Message, state: FSMContext):
    city = message.text.strip()
    save_or_update_user(message.from_user.id, message.from_user.full_name, city=city)
    await state.clear()
    
    text = (
        "Альхамдулиллях 🤍\n\n"
        "Настройка завершена.\n\n"
        "Сегодняшний путь готов."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌙 Перейти к сегодняшнему дню", callback_data="go_to_main")]
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

# --- ГЛАВНОЕ МЕНЮ И МАРШРУТ ---

@dp.callback_query(F.data == "go_to_main")
async def main_menu(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    streak = user.get("streak", 1) if user else 1
    text = (
        f"Сегодня Вы стали лучше, чем вчера 🌱\n\n"
        f"🔥 Серия: <b>{streak} дней</b>\n\n"
        "Выберите нужный раздел:"
    )
    await callback.message.edit_text(text, reply_markup=kb_main_menu(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "menu_prayers")
async def menu_prayers(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    city = user.get("city", "Не указан") if user else "Не указан"
    current_time = datetime.now().strftime("%H:%M")
    
    text = (
        f"🕌 <b>Намаз и ежедневный маршрут</b>\n"
        f"📍 Город: <b>{city}</b> | ⏰ <code>{current_time}</code>\n\n"
        "⏳ <b>До следующего намаза (Зухр):</b> <code>2 ч 15 мин</code>\n\n"
        "🌅 Фаджр — Совершено ✓\n"
        "☀️ Зухр — Ожидает\n"
        "عصر Аср — Ожидает\n"
        "🌇 Магриб — Ожидает\n"
        "🌙 Иша — Ожидает\n\n"
        "📿 Салаваты: 24 / 100\n"
        "🤲 Утренние азкары: Выполнено ✓"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Отметить Зухр", callback_data="mark_zuhr")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "mark_zuhr")
async def mark_zuhr(callback: CallbackQuery):
    text = (
        "☀️ <b>Зухр отмечен.</b>\n\n"
        "Пусть Аллах примет Ваш намаз 🤍\n\n"
        "📖 <i>«Поистине, намаз предписан верующим в определенное время.»</i> (Сура Ан-Ниса, 103)\n\n"
        "⏳ До Асра осталось 3 часа 10 минут."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer("Зухр отмечен. Пусть Аллах примет Ваш намаз 🤍", show_alert=True)

@dp.callback_query(F.data == "menu_path")
async def menu_path(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    streak = user.get("streak", 1) if user else 1
    city = user.get("city", "Не указан") if user else "Не указан"
    mode = user.get("spiritual_mode", "alfard").upper() if user else "ALFARD"
    
    text = (
        "📊 <b>Мой путь</b>\n\n"
        f"🔥 Серия: <b>{streak} дней</b>\n"
        f"📍 Город: <b>{city}</b>\n"
        f"🌱 Этап: <b>{mode}</b>\n\n"
        "🕌 Намазы: 94%\n"
        "📖 Коран: 31 день\n"
        "🤲 Азкары: 27 дней\n"
        "📿 Салаваты: 22 дня\n\n"
        "<i>«Каждый путь состоит не только из шагов вперёд, но и из остановок.»</i> 🤍"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "menu_settings")
async def menu_settings(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    city = user.get("city", "Не указан") if user else "Не указан"
    mode = user.get("spiritual_mode", "alfard").upper() if user else "ALFARD"
    
    text = (
        "⚙️ <b>Настройки и город</b>\n\n"
        f"📍 Город: <b>{city}</b>\n"
        f"🌱 Этап: <b>{mode}</b>\n\n"
        "Что вы хотите изменить?"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📍 Изменить город", callback_data="set_change_city")],
        [InlineKeyboardButton(text="🌱 Изменить этап", callback_data="set_change_mode")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="go_to_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "set_change_city")
async def set_change_city(callback: CallbackQuery, state: FSMContext):
    await state.set_state(OnboardingStates.changing_city)
    await callback.message.edit_text("📍 Напишите название нового города текстом:", parse_mode="HTML")
    await callback.answer()

@dp.message(OnboardingStates.changing_city)
async def process_change_city(message: Message, state: FSMContext):
    city = message.text.strip()
    save_or_update_user(message.from_user.id, message.from_user.full_name, city=city)
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌙 В главное меню", callback_data="go_to_main")]])
    await message.answer(f"Альхамдулиллях 🤍 Новый город <b>{city}</b> сохранен!", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "set_change_mode")
async def set_change_mode(callback: CallbackQuery, state: FSMContext):
    await state.set_state(OnboardingStates.changing_mode)
    await callback.message.edit_text("Выберите этап пути:", reply_markup=kb_modes(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(OnboardingStates.changing_mode, F.data.startswith("mode_"))
async def process_change_mode(callback: CallbackQuery, state: FSMContext):
    mode_map = {
        "mode_alfard": "alfard",
        "mode_alistikama": "alistikama",
        "mode_attazkiya": "attazkiya",
        "mode_alihsan": "alihsan"
    }
    selected = mode_map.get(callback.data, "alfard")
    save_or_update_user(callback.from_user.id, callback.from_user.full_name, mode=selected)
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌙 В главное меню", callback_data="go_to_main")]])
    await message.answer(f"Альхамдулиллях 🤍 Этап обновлен на <b>{selected.upper()}</b>!", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data == "menu_reflection")
async def menu_reflection(callback: CallbackQuery):
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
async def reflection_result(callback: CallbackQuery):
    choice = callback.data.split("_")[1]
    if choice == "hard":
        resp = "Даже один искренний намаз сегодня имеет огромную ценность перед Аллахом 🤍"
    elif choice == "good":
        resp = "Альхамдулиллях! Пусть Аллах примет ваши благие дела и увеличит баракат 🤍"
    else:
        resp = "Каждый день — это шаг на пути к довольству Всевышнего. Продолжайте в том же духе 🤍"
        
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌙 В главное меню", callback_data="go_to_main")]])
    await callback.message.edit_text(f"🌙 <b>Рефлексия сохранена</b>\n\n{resp}", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle(request):
    return web.Response(text="Amal365 Bot is running successfully!")

async def run_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    print("Запуск бота Amal365...")
    await asyncio.gather(
        run_web_server(),
        dp.start_polling(bot, drop_pending_updates=True)
    )

if __name__ == "__main__":
    asyncio.run(main())
