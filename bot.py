import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

from database import (
    create_user,
    get_user,
    update_user,
    get_stats,
    save_prayer,
    save_quran
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в переменных окружения (.env)")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура главного меню для интерактивной отметки дел."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🕌 Намазы", callback_data="menu_prayers"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="menu_stats")
        ]
    ])
    return keyboard

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Мягкий старт и онбординг пользователя в Amal365."""
    telegram_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    user = create_user(telegram_id, username, first_name)

    if not user or not user.get("city"):
        welcome_text = (
            f"Ассаляму алейкум, {first_name or 'дорогой гость'} 🤍\n\n"
            "Добро пожаловать в **Amal365** — ваш мягкий и заботливый духовный компаньон.\n"
            "Здесь нет места чувству вины или гонке за цифрами. Только вы, ваши шаги и Всевышний.\n\n"
            "Чтобы мы могли точно рассчитывать время намазов, пожалуйста, отправьте название вашего города (например: *Москва*, *Казань*, *Бишкек*, *Нерюнгри*)."
        )
        await message.answer(welcome_text, parse_mode="Markdown")
    else:
        welcome_text = (
            f"С возвращением, {first_name} 🤍\n\n"
            f"Ваш город: **{user.get('city')}**\n"
            "Выберите раздел ниже, чтобы продолжить:"
        )
        await message.answer(welcome_text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())

@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text_messages(message: types.Message):
    """Обработка текстовых сообщений (сохранение города при онбординге)."""
    telegram_id = message.from_user.id
    user = get_user(telegram_id)

    if not user:
        user = create_user(telegram_id, message.from_user.username, message.from_user.first_name)

    if user and not user.get("city"):
        city_name = message.text.strip()
        update_user(telegram_id, city=city_name, timezone="Europe/Moscow")
        
        await message.answer(
            f"Город **{city_name}** успешно сохранен 🤍\n\n"
            "Теперь ваш духовный трекер настроен.",
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard()
        )
    else:
        await message.answer("Я вас услышала. Ваша забота о духовном росте бесценна 🤍", reply_markup=get_main_menu_keyboard())

@dp.callback_query(F.data == "menu_stats")
async def cb_stats(callback: types.CallbackQuery):
    """Показ статистики через инлайн-кнопку."""
    telegram_id = callback.from_user.id
    data = get_stats(telegram_id)
    
    if not data or not data.get("user"):
        await callback.message.answer("Сначала отправьте /start для регистрации.")
        await callback.answer()
        return

    user = data["user"]
    prog = data["progress"]
    
    streak = user.get("streak_days", 0)
    city = user.get("city", "Не указан")

    stats_text = (
        f"📊 **Ваша статистика в Amal365**\n\n"
        f"🏙 Город: {city}\n"
        f"🔥 Серия дней (стрик): {streak} дн.\n\n"
        f"✨ **Прогресс за сегодня:**\n"
        f"• Фаджр: {'✅' if prog and prog.get('fajr') else '⭕️'}\n"
        f"• Зухр: {'✅' if prog and prog.get('dhuhr') else '⭕️'}\n"
        f"• Аср: {'✅' if prog and prog.get('asr') else '⭕️'}\n"
        f"• Магриб: {'✅' if prog.get('maghrib') else '⭕️'}\n"
        f"• Иша: {'✅' if prog.get('isha') else '⭕️'}\n"
        f"• Тахаджуд: {'✅' if prog.get('tahajjud') else '⭕️'}\n"
        f"• Чтение Корана: {prog.get('quran_pages', 0) if prog else 0} стр."
    )

    await callback.message.edit_text(stats_text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
    await callback.answer()

@dp.callback_query(F.data == "menu_prayers")
async def cb_prayers_menu(callback: types.CallbackQuery):
    """Меню выбора намазов для отметки."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Фаджр", callback_data="prayer_Фаджр"),
            InlineKeyboardButton(text="Зухр", callback_data="prayer_Зухр")
        ],
        [
            InlineKeyboardButton(text="Аср", callback_data="prayer_Аср"),
            InlineKeyboardButton(text="Магриб", callback_data="prayer_Магриб")
        ],
        [
            InlineKeyboardButton(text="Иша", callback_data="prayer_Иша"),
            InlineKeyboardButton(text="Тахаджуд", callback_data="prayer_Тахаджуд")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад в меню", callback_data="menu_main")
        ]
    ])
    await callback.message.edit_text("Выберите намаз, который хотите отметить:", reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith("prayer_"))
async def cb_save_prayer(callback: types.CallbackQuery):
    """Сохранение отметки намаза."""
    telegram_id = callback.from_user.id
    prayer_name = callback.data.split("_")[1]
    
    save_prayer(telegram_id, prayer_name)
    await callback.answer(f"Намаз «{prayer_name}» отмечен! 🤍")
    
    # Возвращаем в меню намазов с обновленным статусом
    await cb_prayers_menu(callback)

@dp.callback_query(F.data == "menu_main")
async def cb_main_menu(callback: types.CallbackQuery):
    """Возврат в главное меню."""
    await callback.message.edit_text("Главное меню Amal365 🤍", reply_markup=get_main_menu_keyboard())
    await callback.answer()

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """Команда /stats для просмотра статистики."""
    telegram_id = message.from_user.id
    data = get_stats(telegram_id)
    
    if not data or not data.get("user"):
        await message.answer("Сначала отправьте /start для регистрации.")
        return

    user = data["user"]
    prog = data["progress"]
    
    streak = user.get("streak_days", 0)
    city = user.get("city", "Не указан")

    stats_text = (
        f"📊 **Ваша статистика в Amal365**\n\n"
        f"🏙 Город: {city}\n"
        f"🔥 Серия дней (стрик): {streak} дн.\n\n"
        f"✨ **Прогресс за сегодня:**\n"
        f"• Фаджр: {'✅' if prog and prog.get('fajr') else '⭕️'}\n"
        f"• Зухр: {'✅' if prog and prog.get('dhuhr') else '⭕️'}\n"
        f"• Аср: {'✅' if prog and prog.get('asr') else '⭕️'}\n"
        f"• Магриб: {'✅' if prog and prog.get('maghrib') else '⭕️'}\n"
        f"• Иша: {'✅' if prog and prog.get('isha') else '⭕️'}\n"
        f"• Тахаджуд: {'✅' if prog and prog.get('tahajjud') else '⭕️'}\n"
        f"• Чтение Корана: {prog.get('quran_pages', 0) if prog else 0} стр."
    )

    await message.answer(stats_text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())

async def main():
    print("Бот Amal365 запущен и готов к работе...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
