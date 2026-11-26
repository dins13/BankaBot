"""Обработчики команд и сообщений бота."""

import os
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)

from database import add_operation, delete_operation, get_operation, upsert_user
from services import (
    build_balance_report,
    build_categories_report,
    build_period_report,
    build_stats_report,
    category_emoji,
    fmt_dt,
    fmt_money,
    parse_operation,
    start_of_day,
    start_of_month,
    start_of_week,
    start_of_year,
)

router = Router()

# Публичный HTTPS-адрес Mini App (например, https://xxxx.ngrok-free.app).
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip().rstrip("/")

HELP_TEXT = (
    "Я запоминаю твои доходы и расходы 💰\n\n"
    "Просто отправь сообщение:\n"
    "• `100 еда` — расход\n"
    "• `-100 такси` — расход\n"
    "• `+5000 зарплата` — доход\n"
    "• `100 еда 05.10.2026` — расход за прошедший день\n\n"
    "Команды:\n"
    "• /add 100 еда — добавить расход\n"
    "• /income 5000 зп — добавить доход\n"
    "• /today — траты за сегодня\n"
    "• /yesterday — траты за вчера\n"
    "• /week — траты за неделю\n"
    "• /month — траты за месяц\n"
    "• /year — траты за год\n"
    "• /stats — статистика за месяц\n"
    "• /categories — расходы по категориям за месяц\n"
    "• /period 2026-10-01 2026-10-12 — произвольный период\n"
    "• /balance — общий баланс\n"
    "• /del 5 — удалить операцию №5\n"
    "• /app — открыть мини-приложение"
)


def _args(message: Message) -> str:
    """Возвращает аргументы команды: для '/add 100 еда' -> '100 еда'."""
    parts = message.text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


async def _save_operation(message: Message, parsed: dict) -> None:
    user = message.from_user
    await upsert_user(user.id, user.username, user.first_name)
    op_id = await add_operation(
        user.id,
        parsed["type"],
        parsed["amount"],
        parsed["category"],
        parsed["comment"],
        parsed.get("date"),
    )
    emoji = "💸" if parsed["type"] == "expense" else "💰"
    label = "Расход" if parsed["type"] == "expense" else "Доход"
    text = (
        f"{emoji} {label} сохранён (№{op_id})\n"
        f"{category_emoji(parsed['category'])} {parsed['category']}: "
        f"{fmt_money(parsed['amount'])}"
    )
    if parsed.get("date"):
        text += f"\n📅 {parsed['date']:%d.%m.%Y}"
    if parsed["comment"]:
        text += f"\n📝 {parsed['comment']}"
    await message.answer(text)


async def _try_parse_and_save(
    message: Message, text: str, force_type: str | None = None
) -> bool:
    parsed = parse_operation(text)
    if not parsed:
        return False
    if force_type:
        parsed["type"] = force_type
    if parsed.get("date") and parsed["date"].date() > datetime.now().date():
        await message.answer("Нельзя добавить операцию на будущую дату.")
        return True
    await _save_operation(message, parsed)
    return True


# ---------------------------------------------------------------------------
# Старт и справка
# ---------------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message):
    name = message.from_user.first_name or "друг"
    await message.answer(
        f"Привет, {name}! Я твой финансовый бот 💰\n\n"
        "Отправь мне трату в формате `100 еда` или доход `+5000 зарплата`.\n\n"
        "Подробнее — /help",
        parse_mode="Markdown",
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, parse_mode="Markdown")


@router.message(Command("app"))
async def cmd_app(message: Message):
    """Отправляет кнопку запуска Mini App (нужен публичный HTTPS-адрес)."""
    if not WEBAPP_URL:
        await message.answer(
            "Мини-приложение не настроено.\n"
            "Укажите переменную окружения WEBAPP_URL с публичным HTTPS-адресом "
            "или запустите бота через ./scripts/run_with_tunnel.sh."
        )
        return
    if not WEBAPP_URL.startswith("https://"):
        await message.answer(
            "WEBAPP_URL должен начинаться с https:// — Telegram не открывает "
            "Mini App по HTTP-адресу."
        )
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открыть приложение 💰",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ]
    )
    await message.answer("Открыть финансовое мини-приложение:", reply_markup=keyboard)


# ---------------------------------------------------------------------------
# Добавление операций
# ---------------------------------------------------------------------------

@router.message(Command("add"))
async def cmd_add(message: Message):
    text = _args(message)
    if not text:
        await message.answer("Формат: `/add 100 еда`", parse_mode="Markdown")
        return
    if not await _try_parse_and_save(message, text, force_type="expense"):
        await message.answer("Не понял формат. Пример: `/add 100 еда`", parse_mode="Markdown")


@router.message(Command("income"))
async def cmd_income(message: Message):
    text = _args(message)
    if not text:
        await message.answer("Формат: `/income 5000 зарплата`", parse_mode="Markdown")
        return
    if not await _try_parse_and_save(message, text, force_type="income"):
        await message.answer(
            "Не понял формат. Пример: `/income 5000 зарплата`", parse_mode="Markdown"
        )


# ---------------------------------------------------------------------------
# Отчёты по периодам
# ---------------------------------------------------------------------------

@router.message(Command("today"))
async def cmd_today(message: Message):
    now = datetime.now()
    report = await build_period_report(
        message.from_user.id, start_of_day(now), now, f"сегодня {now:%d.%m.%Y}"
    )
    await message.answer(report)


@router.message(Command("yesterday"))
async def cmd_yesterday(message: Message):
    now = datetime.now()
    yesterday = now - timedelta(days=1)
    report = await build_period_report(
        message.from_user.id,
        start_of_day(yesterday),
        start_of_day(now),
        f"вчера {yesterday:%d.%m.%Y}",
    )
    await message.answer(report)


@router.message(Command("week"))
async def cmd_week(message: Message):
    now = datetime.now()
    week_start = start_of_week(now)
    report = await build_period_report(
        message.from_user.id, week_start, now, f"эта неделя (с {week_start:%d.%m})"
    )
    await message.answer(report)


@router.message(Command("month"))
async def cmd_month(message: Message):
    now = datetime.now()
    report = await build_period_report(
        message.from_user.id, start_of_month(now), now, f"месяц {now:%m.%Y}"
    )
    await message.answer(report)


@router.message(Command("year"))
async def cmd_year(message: Message):
    now = datetime.now()
    report = await build_period_report(
        message.from_user.id, start_of_year(now), now, f"год {now:%Y}"
    )
    await message.answer(report)


@router.message(Command("period"))
async def cmd_period(message: Message):
    parts = _args(message).split()
    if len(parts) != 2:
        await message.answer(
            "Формат: `/period 2026-10-01 2026-10-12`", parse_mode="Markdown"
        )
        return
    try:
        start = datetime.strptime(parts[0], "%Y-%m-%d")
        end = datetime.strptime(parts[1], "%Y-%m-%d") + timedelta(days=1)
    except ValueError:
        await message.answer(
            "Даты должны быть в формате ГГГГ-ММ-ДД, "
            "например `/period 2026-10-01 2026-10-12`",
            parse_mode="Markdown",
        )
        return
    if start >= end:
        await message.answer("Дата начала должна быть раньше даты конца.")
        return
    report = await build_period_report(
        message.from_user.id,
        start,
        end,
        f"с {start:%d.%m.%Y} по {(end - timedelta(days=1)):%d.%m.%Y}",
    )
    await message.answer(report)


# ---------------------------------------------------------------------------
# Аналитика
# ---------------------------------------------------------------------------

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    now = datetime.now()
    report = await build_stats_report(
        message.from_user.id, start_of_month(now), now, f"месяц {now:%m.%Y}"
    )
    await message.answer(report)


@router.message(Command("categories"))
async def cmd_categories(message: Message):
    now = datetime.now()
    report = await build_categories_report(
        message.from_user.id, start_of_month(now), now, f"месяц {now:%m.%Y}"
    )
    await message.answer(report)


@router.message(Command("balance"))
async def cmd_balance(message: Message):
    report = await build_balance_report(message.from_user.id)
    await message.answer(report)


# ---------------------------------------------------------------------------
# Удаление операций
# ---------------------------------------------------------------------------

@router.message(Command("del"))
async def cmd_del(message: Message):
    text = _args(message)
    if not text.isdigit():
        await message.answer("Формат: `/del 5` — удалить операцию №5", parse_mode="Markdown")
        return
    op_id = int(text)
    op = await get_operation(message.from_user.id, op_id)
    if not op:
        await message.answer(f"Операция №{op_id} не найдена.")
        return
    await delete_operation(message.from_user.id, op_id)
    sign = "-" if op["type"] == "expense" else "+"
    await message.answer(
        f"🗑 Удалена операция №{op_id}: {sign}{fmt_money(op['amount'])} "
        f"({category_emoji(op['category'])} {op['category']}, {fmt_dt(op['created_at'])})"
    )


# ---------------------------------------------------------------------------
# Обработка обычных сообщений (регистрируется последней)
# ---------------------------------------------------------------------------

@router.message(F.text)
async def handle_text(message: Message):
    if await _try_parse_and_save(message, message.text):
        return
    await message.answer(
        "Не понял. Отправь расход в формате `100 еда` или доход `+5000 зарплата`.\n"
        "Подробнее — /help",
        parse_mode="Markdown",
    )