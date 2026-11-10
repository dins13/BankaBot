"""Точка входа: запуск Telegram-бота для учёта финансов."""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher

from database import init_db
from handlers import router

# Токен от @BotFather. Можно задать через переменную окружения BOT_TOKEN.
BOT_TOKEN = os.getenv("BOT_TOKEN", "***REMOVED***")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.include_router(router)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    logging.info("База данных инициализирована: finance.db")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())