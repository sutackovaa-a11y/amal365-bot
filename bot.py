import asyncio
import os
import logging
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import CommandStart
from dotenv import load_dotenv
from database import save_or_update_user

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    full_name = message.from_user.full_name or "Гость"
    
    # Сохраняем пользователя в базу Supabase
    try:
        save_or_update_user(telegram_id=user_id, full_name=full_name)
    except Exception as e:
        logging.error(f"Ошибка сохранения пользователя: {e}")

    await message.answer(
        f"Ассаляму алейкум, {full_name}! 🤍 Я — **Amal 365**, ваш тихий и бережный цифровой духовный спутник.\n\n"
        "Я здесь, чтобы идти с вами рука об руку от Фаджра до Иша, помогая сохранять внутренний свет и баланс без спешки и гонки."
    )

async def main():
    logging.info("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
