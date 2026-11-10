"""Слой работы с базой данных SQLite.

Используется стандартный модуль sqlite3 (без внешних зависимостей).
Все запросы выполняются в отдельном потоке через asyncio.to_thread,
чтобы не блокировать event loop бота.
"""

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

DB_PATH = Path(__file__).resolve().parent / "finance.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    first_name TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    type       TEXT NOT NULL CHECK (type IN ('expense', 'income')),
    amount     REAL NOT NULL,
    category   TEXT NOT NULL,
    comment    TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_operations_user_time
    ON operations (user_id, created_at);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Создаёт таблицы, если их ещё нет. Вызывается один раз при старте бота."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)


def now_iso() -> str:
    """Текущее локальное время в формате БД (ГГГГ-ММ-ДД ЧЧ:ММ:СС)."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def fetchall(query: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    def _execute() -> list[sqlite3.Row]:
        with _connect() as conn:
            return conn.execute(query, params).fetchall()
    return await asyncio.to_thread(_execute)


async def fetchone(query: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
    def _execute() -> sqlite3.Row | None:
        with _connect() as conn:
            return conn.execute(query, params).fetchone()
    return await asyncio.to_thread(_execute)


async def execute(query: str, params: Sequence[Any] = ()) -> int:
    """Выполняет запрос на изменение данных, возвращает lastrowid."""
    def _execute() -> int:
        with _connect() as conn:
            cur = conn.execute(query, params)
            conn.commit()
            return cur.lastrowid
    return await asyncio.to_thread(_execute)


# ---------------------------------------------------------------------------
# Репозиторий: пользователи и операции
# ---------------------------------------------------------------------------

async def upsert_user(user_id: int, username: str | None, first_name: str | None) -> None:
    """Добавляет пользователя или обновляет его имя/ник при повторном обращении."""
    await execute(
        """
        INSERT INTO users (user_id, username, first_name, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username   = excluded.username,
            first_name = excluded.first_name
        """,
        (user_id, username, first_name, now_iso()),
    )


async def add_operation(
    user_id: int,
    op_type: str,
    amount: float,
    category: str,
    comment: str | None = None,
    created_at: datetime | None = None,
) -> int:
    """Сохраняет операцию (expense/income), возвращает её id.

    Если created_at не задан, используется текущее время. Позволяет
    добавлять операции за прошедшие дни.
    """
    ts = created_at.strftime("%Y-%m-%d %H:%M:%S") if created_at else now_iso()
    return await execute(
        """
        INSERT INTO operations (user_id, type, amount, category, comment, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, op_type, amount, category, comment, ts),
    )


async def get_operation(user_id: int, op_id: int) -> sqlite3.Row | None:
    return await fetchone(
        "SELECT * FROM operations WHERE id = ? AND user_id = ?",
        (op_id, user_id),
    )


async def delete_operation(user_id: int, op_id: int) -> bool:
    """Удаляет операцию, если она принадлежит пользователю. Возвращает успех."""
    def _delete() -> bool:
        with _connect() as conn:
            cur = conn.execute(
                "DELETE FROM operations WHERE id = ? AND user_id = ?",
                (op_id, user_id),
            )
            conn.commit()
            return cur.rowcount > 0
    return await asyncio.to_thread(_delete)


async def get_operations(
    user_id: int,
    start: str | None = None,
    end: str | None = None,
    op_type: str | None = None,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    """Операции пользователя за период (start <= created_at < end), новые сверху."""
    query = "SELECT * FROM operations WHERE user_id = ?"
    params: list[Any] = [user_id]
    if start is not None:
        query += " AND created_at >= ?"
        params.append(start)
    if end is not None:
        query += " AND created_at < ?"
        params.append(end)
    if op_type is not None:
        query += " AND type = ?"
        params.append(op_type)
    query += " ORDER BY created_at DESC, id DESC"
    if limit is not None:
        query += f" LIMIT {int(limit)}"
    return await fetchall(query, params)


async def get_totals(
    user_id: int,
    start: str | None = None,
    end: str | None = None,
) -> list[sqlite3.Row]:
    """Суммы и количество операций по типам (expense/income) за период."""
    query = """
        SELECT type, SUM(amount) AS total, COUNT(*) AS cnt
        FROM operations
        WHERE user_id = ?
    """
    params: list[Any] = [user_id]
    if start is not None:
        query += " AND created_at >= ?"
        params.append(start)
    if end is not None:
        query += " AND created_at < ?"
        params.append(end)
    query += " GROUP BY type"
    return await fetchall(query, params)


async def get_category_totals(
    user_id: int,
    start: str | None = None,
    end: str | None = None,
    op_type: str = "expense",
) -> list[sqlite3.Row]:
    """Суммы по категориям за период, отсортированы по убыванию суммы."""
    query = """
        SELECT category, SUM(amount) AS total, COUNT(*) AS cnt
        FROM operations
        WHERE user_id = ? AND type = ?
    """
    params: list[Any] = [user_id, op_type]
    if start is not None:
        query += " AND created_at >= ?"
        params.append(start)
    if end is not None:
        query += " AND created_at < ?"
        params.append(end)
    query += " GROUP BY category ORDER BY total DESC"
    return await fetchall(query, params)