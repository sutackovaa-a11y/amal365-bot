import asyncio
import os
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import CommandStart
from dotenv import load_dotenv
from database import save_or_update_user

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    full_name = message.from_user.full_name or "Гость"
    
    try:
        save_or_update_user(telegram_id=user_id, full_name=full_name)
    except Exception as e:
        logging.error(f"Ошибка сохранения пользователя: {e}")

    await message.answer(
        f"Ассаляму алейкум, {full_name}! 🤍 Я — **Amal 365**, ваш тихий и бережный цифровой духовный спутник.\n\n"
        "Я здесь, чтобы идти с вами рука об руку от Фаджра до Иша, помогая сохранять внутренний свет и баланс без спешки и гонки."
    )

# Веб-сервер для Render, чтобы он видел активность и не выключал бота
async def handle(request):
    return web.Response(text="Amal365 Bot is active and running!")

async def web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"Веб-сервер запущен на порту {PORT}")

async def main():
    # Запускаем веб-сервер для Render и саму логику бота
    await web_server()
    logging.info("Бот запущен...")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
