"""Парсинг сообщений, работа с периодами времени и форматирование отчётов."""

import re
from datetime import datetime, timedelta

from database import get_category_totals, get_operations, get_totals

# ---------------------------------------------------------------------------
# Парсинг сообщений
# ---------------------------------------------------------------------------

# Примеры: "100 еда", "-100 такси", "+5000 зарплата", "12,50 кофе"
AMOUNT_RE = re.compile(r"^([+-]?)(\d{1,12}(?:[.,]\d{1,2})?)\s+(.+)$", re.UNICODE)

# Необязательная дата в конце сообщения: "100 еда 05.10.2026"
DATE_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}$")

CATEGORY_EMOJI = {
    "еда": "🍔", "продукты": "🛒", "кафе": "☕", "ресторан": "🍽", "обед": "🥗",
    "транспорт": "🚌", "такси": "🚕", "метро": "🚇", "бензин": "⛽", "авто": "🚗",
    "жильё": "🏠", "аренда": "🏠", "квартира": "🏠", "коммуналка": "💡",
    "связь": "📱", "интернет": "🌐", "телефон": "📱", "мобильный": "📱",
    "развлечения": "🎮", "кино": "🎬", "игры": "🎮", "хобби": "🎨",
    "здоровье": "💊", "аптека": "💊", "спорт": "🏋", "врач": "🩺",
    "одежда": "👕", "обувь": "👟", "шоппинг": "🛍",
    "образование": "📚", "книги": "📚", "курсы": "🎓",
    "подарки": "🎁", "праздник": "🎉",
    "путешествия": "✈️", "отпуск": "🏖", "отель": "🏨",
    "животные": "🐾", "питомцы": "🐾",
    "зарплата": "💼", "зп": "💼", "доход": "💰", "бонус": "🎉",
    "подработка": "🛠", "фриланс": "💻", "кэшбек": "💳", "кэшбэк": "💳",
    "прочее": "📦", "другое": "📦", "разное": "📦",
}


def parse_operation(text: str) -> dict | None:
    """Разбирает сообщение вида '100 еда' или '+5000 зарплата'.

    В конце можно указать дату в формате ДД.ММ.ГГГГ, чтобы добавить
    операцию за прошедший день: '100 еда 05.10.2026'.

    Возвращает dict с ключами type/amount/category/comment/date или None,
    если сообщение не похоже на операцию.
    """
    match = AMOUNT_RE.match(text.strip())
    if not match:
        return None
    sign, amount_str, rest = match.groups()
    amount = round(float(amount_str.replace(",", ".")), 2)
    if amount <= 0:
        return None
    op_type = "income" if sign == "+" else "expense"
    parts = rest.split()

    # Необязательная дата в конце сообщения (ДД.ММ.ГГГГ).
    date = None
    if parts and DATE_RE.match(parts[-1]):
        try:
            date = datetime.strptime(parts[-1], "%d.%m.%Y")
        except ValueError:
            return None
        now = datetime.now()
        date = date.replace(hour=now.hour, minute=now.minute, second=now.second)
        parts = parts[:-1]

    if not parts:
        return None
    category = parts[0].lower()
    comment = " ".join(parts[1:]) or None
    return {
        "type": op_type,
        "amount": amount,
        "category": category,
        "comment": comment,
        "date": date,
    }


# ---------------------------------------------------------------------------
# Периоды времени
# ---------------------------------------------------------------------------

def dt_to_db(dt: datetime) -> str:
    """Формат времени для хранения и сравнения в БД."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def start_of_week(dt: datetime) -> datetime:
    """Начало текущей недели (понедельник, 00:00)."""
    return (dt - timedelta(days=dt.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def start_of_month(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def start_of_year(dt: datetime) -> datetime:
    return dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Форматирование
# ---------------------------------------------------------------------------

def fmt_money(amount: float) -> str:
    return f"{amount:,.2f}".replace(",", " ") + " ₽"


def fmt_signed(amount: float) -> str:
    sign = "+" if amount >= 0 else "-"
    return f"{sign}{fmt_money(abs(amount))}"


def fmt_dt(iso_str: str) -> str:
    return datetime.strptime(iso_str, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")


def fmt_dt_short(iso_str: str) -> str:
    return datetime.strptime(iso_str, "%Y-%m-%d %H:%M:%S").strftime("%d.%m %H:%M")


def category_emoji(category: str) -> str:
    return CATEGORY_EMOJI.get(category, "📦")


# ---------------------------------------------------------------------------
# Отчёты
# ---------------------------------------------------------------------------

async def build_period_report(
    user_id: int, start: datetime, end: datetime, title: str
) -> str:
    """Список операций за период с итогами."""
    ops = await get_operations(user_id, start=dt_to_db(start), end=dt_to_db(end))
    if not ops:
        return f"📭 За период «{title}» операций нет."

    expenses = [o for o in ops if o["type"] == "expense"]
    incomes = [o for o in ops if o["type"] == "income"]

    lines = [f"📅 {title}"]
    if expenses:
        lines.append("\n💸 Расходы:")
        for o in expenses:
            lines.append(
                f"{category_emoji(o['category'])} {o['category']} — "
                f"{fmt_money(o['amount'])} ({fmt_dt_short(o['created_at'])})"
            )
    if incomes:
        lines.append("\n💰 Доходы:")
        for o in incomes:
            lines.append(
                f"{category_emoji(o['category'])} {o['category']} — "
                f"{fmt_money(o['amount'])} ({fmt_dt_short(o['created_at'])})"
            )

    total_exp = sum(o["amount"] for o in expenses)
    total_inc = sum(o["amount"] for o in incomes)
    lines.append(f"\nИтого: расходы {fmt_money(total_exp)}, доходы {fmt_money(total_inc)}")
    return "\n".join(lines)


async def build_stats_report(
    user_id: int, start: datetime, end: datetime, title: str
) -> str:
    """Сводка: доходы/расходы/баланс, топ категорий, средний расход в день."""
    totals = {
        row["type"]: row
        for row in await get_totals(user_id, start=dt_to_db(start), end=dt_to_db(end))
    }
    income = totals.get("income")
    expense = totals.get("expense")
    inc_total = income["total"] if income else 0.0
    exp_total = expense["total"] if expense else 0.0
    balance = inc_total - exp_total

    lines = [f"📊 Статистика: {title}"]
    lines.append(
        f"💰 Доходы: {fmt_money(inc_total)}"
        + (f" ({income['cnt']} опер.)" if income else "")
    )
    lines.append(
        f"💸 Расходы: {fmt_money(exp_total)}"
        + (f" ({expense['cnt']} опер.)" if expense else "")
    )
    lines.append(f"📉 Баланс: {fmt_signed(balance)}")

    cats = await get_category_totals(
        user_id, start=dt_to_db(start), end=dt_to_db(end), op_type="expense"
    )
    if cats:
        lines.append("\n🏆 Топ категорий расходов:")
        for i, row in enumerate(cats[:10], 1):
            pct = row["total"] / exp_total * 100 if exp_total else 0
            lines.append(
                f"{i}. {category_emoji(row['category'])} {row['category']} — "
                f"{fmt_money(row['total'])} ({pct:.0f}%)"
            )
        days = max((end - start).days, 1)
        lines.append(f"\nСредний расход в день: {fmt_money(exp_total / days)}")
    return "\n".join(lines)


async def build_categories_report(
    user_id: int, start: datetime, end: datetime, title: str
) -> str:
    """Расходы, сгруппированные по категориям, с долями."""
    cats = await get_category_totals(
        user_id, start=dt_to_db(start), end=dt_to_db(end), op_type="expense"
    )
    if not cats:
        return f"🗂 За период «{title}» расходов нет."
    total = sum(row["total"] for row in cats)
    lines = [f"🗂 Расходы по категориям: {title}"]
    for i, row in enumerate(cats, 1):
        pct = row["total"] / total * 100
        lines.append(
            f"{i}. {category_emoji(row['category'])} {row['category']} — "
            f"{fmt_money(row['total'])} ({pct:.0f}%, {row['cnt']} опер.)"
        )
    lines.append(f"\nИтого: {fmt_money(total)}")
    return "\n".join(lines)


async def build_balance_report(user_id: int) -> str:
    """Общий баланс за всё время."""
    totals = {row["type"]: row for row in await get_totals(user_id)}
    income = totals.get("income")
    expense = totals.get("expense")
    inc_total = income["total"] if income else 0.0
    exp_total = expense["total"] if expense else 0.0
    balance = inc_total - exp_total
    lines = [f"💰 Общий баланс: {fmt_signed(balance)}"]
    lines.append(f"Доходы всего: {fmt_money(inc_total)}")
    lines.append(f"Расходы всего: {fmt_money(exp_total)}")
    return "\n".join(lines)