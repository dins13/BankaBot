"""Проверка подписи Telegram WebApp initData.

Алгоритм описан в документации Telegram:
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

# Данные считаются устаревшими, если им больше суток.
MAX_AGE_SECONDS = 24 * 60 * 60


def validate_init_data(
    init_data: str,
    bot_token: str,
    max_age: int | None = MAX_AGE_SECONDS,
) -> dict | None:
    """Проверяет initData и возвращает данные пользователя или None.

    Возвращает словарь с ключами id/username/first_name.
    """
    if not init_data:
        return None

    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    except ValueError:
        return None

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    if max_age is not None:
        try:
            auth_date = int(pairs.get("auth_date", "0"))
        except ValueError:
            return None
        if auth_date <= 0 or time.time() - auth_date > max_age:
            return None

    user_raw = pairs.get("user")
    if not user_raw:
        return None

    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError:
        return None

    user_id = user.get("id")
    if not isinstance(user_id, int):
        return None

    return {
        "id": user_id,
        "username": user.get("username"),
        "first_name": user.get("first_name"),
    }
