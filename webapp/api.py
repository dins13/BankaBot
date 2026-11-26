"""FastAPI-бэкенд Mini App: REST API поверх существующей базы finance.db.

Запуск:
    uvicorn webapp.api:app --host 0.0.0.0 --port 8000

Авторизация: заголовок X-Telegram-Init-Data с подписанным initData из Telegram.
Для локальной разработки можно включить WEBAPP_DEV_MODE=1 и передавать
X-Dev-User (по умолчанию пользователь 1).
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Загружаем переменные окружения из .env (файл не коммитится).
load_dotenv(BASE_DIR / ".env")

from database import (  # noqa: E402
    add_operation,
    delete_operation,
    get_categories,
    get_category_totals,
    get_operation,
    get_operations,
    get_totals,
    init_db,
    upsert_user,
)
from services import CATEGORY_EMOJI  # noqa: E402
from webapp.auth import validate_init_data  # noqa: E402

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DEV_MODE = os.getenv("WEBAPP_DEV_MODE", "0").lower() in {"1", "true", "yes", "on"}
STATIC_DIR = Path(__file__).resolve().parent / "static"

DEFAULT_EXPENSE = [
    "еда", "продукты", "кафе", "транспорт", "такси", "жильё", "коммуналка",
    "связь", "развлечения", "здоровье", "одежда", "образование", "подарки",
    "путешествия", "животные", "прочее",
]
DEFAULT_INCOME = [
    "зарплата", "доход", "бонус", "подработка", "фриланс", "кэшбек", "прочее",
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Finance Mini App", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Авторизация
# ---------------------------------------------------------------------------

async def current_user(request: Request) -> dict:
    """Определяет пользователя по initData или dev-заголовку."""
    init_data = request.headers.get("X-Telegram-Init-Data") or request.query_params.get(
        "initData"
    )
    if init_data:
        user = validate_init_data(init_data, BOT_TOKEN)
        if not user:
            raise HTTPException(status_code=401, detail="Не удалось проверить данные Telegram")
        return user

    if DEV_MODE:
        raw = (
            request.headers.get("X-Dev-User")
            or request.query_params.get("dev_user")
            or "1"
        )
        try:
            user_id = int(raw)
        except ValueError:
            user_id = 1
        return {"id": user_id, "username": f"dev{user_id}", "first_name": "Dev"}

    raise HTTPException(status_code=401, detail="Требуется авторизация через Telegram")


# ---------------------------------------------------------------------------
# Модели и утилиты
# ---------------------------------------------------------------------------

class OperationIn(BaseModel):
    type: Literal["expense", "income"]
    amount: float = Field(gt=0, le=1_000_000_000_000)
    category: str = Field(min_length=1, max_length=64)
    comment: str | None = Field(default=None, max_length=300)
    date: str | None = Field(default=None, description="Дата операции, YYYY-MM-DD")


def _parse_day(value: str | None, field: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"Параметр {field} должен быть в формате YYYY-MM-DD"
        )


def _bounds(start: str | None, end: str | None) -> tuple[str | None, str | None]:
    """Преобразует даты YYYY-MM-DD в границы БД (конец не включается)."""
    start_dt = _parse_day(start, "start")
    end_dt = _parse_day(end, "end")
    start_s = start_dt.strftime("%Y-%m-%d 00:00:00") if start_dt else None
    end_s = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00") if end_dt else None
    if start_s and end_s and start_s >= end_s:
        raise HTTPException(status_code=400, detail="Начало периода должно быть раньше конца")
    return start_s, end_s


def _op_dict(row) -> dict:
    category = row["category"]
    return {
        "id": row["id"],
        "type": row["type"],
        "amount": round(float(row["amount"]), 2),
        "category": category,
        "comment": row["comment"],
        "created_at": row["created_at"],
        "emoji": CATEGORY_EMOJI.get(category, "📦"),
    }


def _cat_list(rows) -> list[dict]:
    return [
        {
            "name": row["category"],
            "emoji": CATEGORY_EMOJI.get(row["category"], "📦"),
            "count": int(row["cnt"]),
            "total": round(float(row["total"]), 2),
        }
        for row in rows
    ]


async def _summary(user_id: int, start: str | None, end: str | None) -> dict:
    rows = await get_totals(user_id, start=start, end=end)
    by_type = {row["type"]: row for row in rows}
    income = by_type.get("income")
    expense = by_type.get("expense")
    income_total = float(income["total"]) if income else 0.0
    expense_total = float(expense["total"]) if expense else 0.0
    return {
        "income": round(income_total, 2),
        "expense": round(expense_total, 2),
        "balance": round(income_total - expense_total, 2),
        "income_count": int(income["cnt"]) if income else 0,
        "expense_count": int(expense["cnt"]) if expense else 0,
    }


# ---------------------------------------------------------------------------
# Динамика по периодам
# ---------------------------------------------------------------------------

def _bucket_start(day: date, bucket: str) -> date:
    if bucket == "day":
        return day
    if bucket == "week":
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def _next_bucket(day: date, bucket: str) -> date:
    if bucket == "day":
        return day + timedelta(days=1)
    if bucket == "week":
        return day + timedelta(days=7)
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


def _build_trend(
    operations: list,
    start: str | None,
    end: str | None,
    bucket: str | None,
) -> list[dict]:
    if not operations:
        return []

    parsed = [
        (datetime.strptime(op["created_at"], "%Y-%m-%d %H:%M:%S"), op)
        for op in operations
    ]

    if bucket is None:
        first_day = min(dt.date() for dt, _ in parsed)
        last_day = max(dt.date() for dt, _ in parsed)
        span = (last_day - first_day).days
        bucket = "day" if span <= 31 else "week" if span <= 183 else "month"

    if start:
        first_day = datetime.strptime(start, "%Y-%m-%d %H:%M:%S").date()
    else:
        first_day = min(dt.date() for dt, _ in parsed)

    if end:
        last_day = (
            datetime.strptime(end, "%Y-%m-%d %H:%M:%S") - timedelta(days=1)
        ).date()
    else:
        last_day = max(dt.date() for dt, _ in parsed)

    aggregated: dict[date, dict[str, float]] = {}
    for dt, op in parsed:
        key = _bucket_start(dt.date(), bucket)
        record = aggregated.setdefault(key, {"expense": 0.0, "income": 0.0})
        record[op["type"]] += float(op["amount"])

    cursor = _bucket_start(first_day, bucket)
    last_bucket = _bucket_start(last_day, bucket)
    result: list[dict] = []
    while cursor <= last_bucket and len(result) < 500:
        record = aggregated.get(cursor, {"expense": 0.0, "income": 0.0})
        label = (
            cursor.strftime("%d.%m")
            if bucket in ("day", "week")
            else cursor.strftime("%m.%Y")
        )
        result.append(
            {
                "period": cursor.isoformat(),
                "label": label,
                "expense": round(record["expense"], 2),
                "income": round(record["income"], 2),
            }
        )
        cursor = _next_bucket(cursor, bucket)
    return result


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "dev_mode": DEV_MODE}


@app.get("/api/me")
async def me(user: dict = Depends(current_user)) -> dict:
    await upsert_user(user["id"], user.get("username"), user.get("first_name"))
    return {
        "user": {
            "id": user["id"],
            "username": user.get("username"),
            "first_name": user.get("first_name"),
        },
        "totals": await _summary(user["id"], None, None),
    }


@app.get("/api/categories")
async def categories(user: dict = Depends(current_user)) -> dict:
    """Существующие категории пользователя + категории по умолчанию."""
    rows = await get_categories(user["id"])
    result: dict[str, list[dict]] = {}
    for op_type, defaults in (("expense", DEFAULT_EXPENSE), ("income", DEFAULT_INCOME)):
        used = [row for row in rows if row["type"] == op_type]
        items = [
            {
                "name": row["category"],
                "emoji": CATEGORY_EMOJI.get(row["category"], "📦"),
                "count": int(row["cnt"]),
                "total": round(float(row["total"]), 2),
            }
            for row in used
        ]
        known = {item["name"] for item in items}
        for name in defaults:
            if name not in known:
                items.append(
                    {
                        "name": name,
                        "emoji": CATEGORY_EMOJI.get(name, "📦"),
                        "count": 0,
                        "total": 0.0,
                    }
                )
        result[op_type] = items
    return result


@app.get("/api/operations")
async def list_operations(
    user: dict = Depends(current_user),
    start: str | None = None,
    end: str | None = None,
    type: str | None = Query(default=None),
    category: str | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict:
    if type not in (None, "expense", "income"):
        raise HTTPException(status_code=400, detail="type должен быть expense или income")
    start_s, end_s = _bounds(start, end)
    rows = await get_operations(
        user["id"],
        start=start_s,
        end=end_s,
        op_type=type,
        category=category or None,
        limit=limit,
        offset=offset,
    )
    return {
        "items": [_op_dict(row) for row in rows],
        "totals": await _summary(user["id"], start_s, end_s),
    }


@app.post("/api/operations", status_code=201)
async def create_operation(
    payload: OperationIn, user: dict = Depends(current_user)
) -> dict:
    category = payload.category.strip().lower()
    if not category:
        raise HTTPException(status_code=400, detail="Категория не может быть пустой")

    created_at: datetime | None = None
    if payload.date:
        day = _parse_day(payload.date, "date")
        if day.date() > date.today():
            raise HTTPException(
                status_code=400, detail="Нельзя добавить операцию на будущую дату"
            )
        now = datetime.now()
        created_at = day.replace(hour=now.hour, minute=now.minute, second=now.second)

    await upsert_user(user["id"], user.get("username"), user.get("first_name"))
    op_id = await add_operation(
        user["id"],
        payload.type,
        round(payload.amount, 2),
        category,
        (payload.comment or "").strip() or None,
        created_at,
    )
    row = await get_operation(user["id"], op_id)
    return _op_dict(row)


@app.delete("/api/operations/{op_id}")
async def remove_operation(op_id: int, user: dict = Depends(current_user)) -> dict:
    deleted = await delete_operation(user["id"], op_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Операция не найдена")
    return {"ok": True, "id": op_id}


@app.get("/api/stats")
async def stats(
    user: dict = Depends(current_user),
    start: str | None = None,
    end: str | None = None,
    bucket: Literal["day", "week", "month"] | None = None,
) -> dict:
    start_s, end_s = _bounds(start, end)
    user_id = user["id"]

    totals = await _summary(user_id, start_s, end_s)
    expense_rows = await get_category_totals(
        user_id, start=start_s, end=end_s, op_type="expense"
    )
    income_rows = await get_category_totals(
        user_id, start=start_s, end=end_s, op_type="income"
    )
    operations = await get_operations(user_id, start=start_s, end=end_s)
    trend = _build_trend(operations, start_s, end_s, bucket)

    if start_s and end_s:
        days = max(
            (
                datetime.strptime(end_s, "%Y-%m-%d %H:%M:%S")
                - datetime.strptime(start_s, "%Y-%m-%d %H:%M:%S")
            ).days,
            1,
        )
    elif operations:
        dates = [
            datetime.strptime(op["created_at"], "%Y-%m-%d %H:%M:%S").date()
            for op in operations
        ]
        days = max((max(dates) - min(dates)).days + 1, 1)
    else:
        days = 1

    if bucket is None:
        bucket = _detect_bucket(trend) if trend else "day"

    return {
        "totals": totals,
        "categories": {
            "expense": _cat_list(expense_rows),
            "income": _cat_list(income_rows),
        },
        "trend": trend,
        "bucket": bucket,
        "days": days,
        "avg_expense_per_day": round(totals["expense"] / days, 2),
        "operations_count": totals["expense_count"] + totals["income_count"],
    }


def _detect_bucket(trend: list[dict]) -> str:
    """Определяет шаг агрегации по подписям (для ответа фронтенду)."""
    if len(trend) < 2:
        return "day"
    try:
        first = date.fromisoformat(trend[0]["period"])
        second = date.fromisoformat(trend[1]["period"])
    except ValueError:
        return "day"
    delta = (second - first).days
    if delta >= 28:
        return "month"
    if delta >= 7:
        return "week"
    return "day"


# ---------------------------------------------------------------------------
# Статика
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "webapp.api:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )
