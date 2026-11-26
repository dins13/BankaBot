"""Точка входа: запуск Telegram-бота и веб-сервера Mini App.

Один процесс поднимает и бота (aiogram), и FastAPI/uvicorn со статикой Mini App.
Веб-сервер можно отключить переменной окружения WEBAPP_EMBED=0.
"""

import asyncio
import contextlib
import logging
import os
from pathlib import Path

import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.types import MenuButtonWebApp, WebAppInfo
from dotenv import load_dotenv

# Загружаем .env до импорта модулей, которые читают переменные окружения.
load_dotenv(Path(__file__).resolve().parent / ".env")

from database import init_db  # noqa: E402
from handlers import router  # noqa: E402
from webapp.api import app as webapp_app  # noqa: E402

# Токен от @BotFather задаётся ТОЛЬКО через переменную окружения BOT_TOKEN.
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError(
        "Не задан BOT_TOKEN. Укажите токен бота в переменной окружения BOT_TOKEN."
    )

# Публичный HTTPS-адрес Mini App для кнопки меню (необязательно).
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()

# Встроенный веб-сервер Mini App (включён по умолчанию).
WEBAPP_EMBED = os.getenv("WEBAPP_EMBED", "1").lower() in {"1", "true", "yes", "on"}
WEBAPP_HOST = os.getenv("WEBAPP_HOST") or os.getenv("HOST") or "0.0.0.0"
WEBAPP_PORT = int(os.getenv("WEBAPP_PORT") or os.getenv("PORT") or "8000")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.include_router(router)


class _BackgroundServer(uvicorn.Server):
    """uvicorn-сервер без перехвата сигналов — ими управляет aiogram."""

    @contextlib.contextmanager
    def capture_signals(self):  # type: ignore[override]
        yield


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


async def _serve_webapp(server: uvicorn.Server) -> None:
    """Запускает веб-сервер Mini App в фоне, не роняя бота при ошибке."""
    try:
        await server.serve()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logging.exception("Веб-сервер Mini App остановлен из-за ошибки")


async def _stop_webapp(server: uvicorn.Server, task: asyncio.Task) -> None:
    """Корректно останавливает встроенный веб-сервер."""
    server.should_exit = True
    with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
        await asyncio.wait_for(task, timeout=10)
    logging.info("Веб-сервер Mini App остановлен")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    init_db()
    logging.info("База данных инициализирована: finance.db")

    web_task: asyncio.Task | None = None
    server: uvicorn.Server | None = None
    if WEBAPP_EMBED:
        server = _BackgroundServer(
            uvicorn.Config(
                webapp_app,
                host=WEBAPP_HOST,
                port=WEBAPP_PORT,
                log_level="info",
            )
        )
        web_task = asyncio.create_task(_serve_webapp(server), name="webapp")
        logging.info(
            "Веб-сервер Mini App запущен на http://%s:%s", WEBAPP_HOST, WEBAPP_PORT
        )

    try:
        await _setup_menu_button()
        await dp.start_polling(bot)
    finally:
        if server is not None and web_task is not None:
            await _stop_webapp(server, web_task)


if __name__ == "__main__":
    asyncio.run(main())
