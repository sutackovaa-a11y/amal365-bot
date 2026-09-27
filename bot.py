import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from dotenv import load_dotenv

from database import get_or_create_user, update_user_city

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("Не найден BOT_TOKEN в файле .env")

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

logging.basicConfig(level=logging.INFO)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    telegram_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name

    # Получаем или создаем пользователя в базе данных Supabase
    user = await get_or_create_user(telegram_id, username, first_name)

    welcome_text = (
        f"Ассаляму алейкум, {first_name} 🤍\n\n"
        "Добро пожаловать в **Amal365** — ваш мягкий и заботливий духовный компаньон.\n"
        "Здесь нет места чувству вины или гонке за цифрами. Только вы, ваши шаги и Всевышний.\n\n"
        "Чтобы мы могли точно рассчитывать время намазов, пожалуйста, отправьте название вашего города (например: *Москва*, *Казань*, *Бишкек*, *Нерюнгри*)."
    )

    await message.answer(welcome_text, parse_mode="Markdown")

@dp.message()
async def handle_text_messages(message: types.Message):
    """Временный обработчик текста (например, для сохранения города, если пользователь его прислал)."""
    text = message.strip() if message.text else ""
    telegram_id = message.from_user.id

    # Если сообщение похоже на название города (простая логика, которую позже расширим)
    if message.text and len(message.text.split()) <= 2:
        city_name = message.text.strip()
        await update_user_city(telegram_id, city_name)
        await message.answer(
            f"Город **{city_name}** сохранен 🤍 Теперь время намазов будет рассчитываться точно для вас.",
            parse_mode="Markdown"
        )
    else:
        await message.answer("Я вас услышала. Используйте меню или команды для навигации.")

async def main():
    print("Бот Amal365 запущен и готов к работе...")
    # Запуск поллинга
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
