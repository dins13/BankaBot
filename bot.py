"""Точка входа: запуск Telegram-бота для учёта финансов."""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.types import MenuButtonWebApp, WebAppInfo

from database import init_db
from handlers import router

# Токен от @BotFather. Можно задать через переменную окружения BOT_TOKEN.
BOT_TOKEN = os.getenv("BOT_TOKEN", "***REMOVED***")

# Публичный HTTPS-адрес Mini App для кнопки меню (необязательно).
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.include_router(router)


async def _setup_menu_button() -> None:
    """Добавляет кнопку Mini App в меню бота, если задан WEBAPP_URL."""
    if not WEBAPP_URL:
        return
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Финансы",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        )
        logging.info("Кнопка Mini App установлена: %s", WEBAPP_URL)
    except Exception as exc:  # noqa: BLE001
        logging.warning("Не удалось установить кнопку Mini App: %s", exc)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    logging.info("База данных инициализирована: finance.db")
    await _setup_menu_button()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())