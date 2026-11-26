# BankaBot + Mini App

Telegram-бот для учёта финансов и Telegram Mini App с тем же функционалом.
Оба используют одну базу `finance.db`.

## Возможности

- Добавление расходов и доходов (сумма, категория, комментарий, дата).
- Удаление операций.
- Распределение по существующим категориям (из истории + категории по умолчанию).
- История операций с фильтрами по периоду, типу и категории.
- Аналитика:
  - доходы, расходы, баланс;
  - средний расход в день;
  - распределение по категориям (кольцевая диаграмма и легенда);
  - динамика по времени (дни / недели / месяцы);
  - топ категорий расходов.

## Структура

```
bot.py                 запуск Telegram-бота (aiogram)
handlers.py            команды бота, /app и кнопка Mini App
services.py            парсинг, периоды, отчёты
database.py            SQLite-слой (общий для бота и Mini App)
webapp/
  api.py               FastAPI: REST API + раздача статики
  auth.py              проверка подписи Telegram initData
  static/
    index.html
    styles.css
    app.js
finance.db             база данных (создаётся автоматически)
```

## Установка

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Локальный запуск Mini App

```bash
WEBAPP_DEV_MODE=1 uvicorn webapp.api:app --host 0.0.0.0 --port 8000
```

Откройте http://localhost:8000 — в dev-режиме запросы авторизуются под
пользователем `1` (или `?dev_user=123`, `X-Dev-User: 123`).
Можно посмотреть и изменить те же операции, что и в боте.

В dev-режиме удобно наполнить базу через API:

```bash
curl -X POST http://localhost:8000/api/operations \
  -H 'Content-Type: application/json' \
  -d '{"type":"expense","amount":450,"category":"еда","comment":"обед"}'
```

## Подключение к Telegram

Telegram открывает Mini App только по HTTPS. Для локальной разработки
подойдёт туннель, например ngrok или cloudflared:

```bash
ngrok http 8000
# или
cloudflared tunnel --url http://localhost:8000
```

Затем запустите API и бота с одним и тем же публичным адресом:

```bash
export WEBAPP_URL="https://<ваш-адрес>"
export BOT_TOKEN="<токен-бота>"

uvicorn webapp.api:app --host 0.0.0.0 --port 8000
python bot.py
```

- Бот при старте установит кнопку меню «Финансы».
- Команда `/app` пришлёт кнопку запуска Mini App.
- Авторизация в API выполняется по подписи `initData`, токен бота должен
  совпадать у бота и Mini App (`BOT_TOKEN`).

## Переменные окружения

| Переменная        | Назначение                                             |
|-------------------|--------------------------------------------------------|
| `BOT_TOKEN`       | Токен Telegram-бота (бот и проверка initData)          |
| `WEBAPP_URL`      | Публичный HTTPS-адрес Mini App для кнопок в боте       |
| `WEBAPP_DEV_MODE` | `1` — разрешить доступ без Telegram (только локально)  |
| `HOST`, `PORT`    | Адрес и порт при запуске `python -m webapp.api`        |

## API

| Метод  | Путь                    | Описание                                  |
|--------|-------------------------|-------------------------------------------|
| GET    | `/api/me`               | Пользователь и общий баланс               |
| GET    | `/api/categories`       | Существующие категории по типам           |
| GET    | `/api/operations`       | История с фильтрами и итогами             |
| POST   | `/api/operations`       | Добавить операцию                         |
| DELETE | `/api/operations/{id}`  | Удалить операцию                          |
| GET    | `/api/stats`            | Сводка, категории, динамика по периодам   |

Параметры периода: `start` и `end` в формате `YYYY-MM-DD` (включительно).
Для динамики — `bucket=day|week|month` (по умолчанию подбирается автоматически).

## Команды бота

`/add`, `/income`, `/today`, `/yesterday`, `/week`, `/month`, `/year`,
`/stats`, `/categories`, `/period`, `/balance`, `/del`, `/app`, `/help`.
