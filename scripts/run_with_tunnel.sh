#!/usr/bin/env bash
# Запуск бота вместе с публичным HTTPS-туннелем на порт Mini App.
#
# Зачем: Telegram открывает Mini App только по публичному HTTPS-адресу.
# Встроенный туннель VS Code (devtunnels.ms) для этого не подходит: он
# показывает браузеру (и Telegram WebView) страницу-предупреждение
# "You are about to connect to a developer tunnel... Continue", из-за чего
# мини-приложение выглядит как "no tunnel" / не открывается.
#
# Этот скрипт поднимает SSH-туннель через localhost.run (HTTPS без
# промежуточных страниц), получает публичный URL и запускает bot.py,
# подставляя его в WEBAPP_URL. Кнопка меню обновится автоматически.
#
# Использование:
#   ./scripts/run_with_tunnel.sh
#
# Переменные:
#   WEBAPP_PORT — локальный порт веб-сервера (по умолчанию 8000);
#   PYTHON      — интерпретатор Python (по умолчанию .venv/bin/python или python3).

set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${WEBAPP_PORT:-8000}"

if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

if ! command -v ssh >/dev/null 2>&1; then
  echo "Ошибка: не найден ssh — он нужен для туннеля localhost.run." >&2
  exit 1
fi

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Ошибка: порт $PORT уже занят. Остановите старый bot.py и повторите." >&2
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >&2 || true
  exit 1
fi

TUNNEL_LOG="$(mktemp -t localhost-run.XXXXXX)"
SSH_PID=""

cleanup() {
  if [[ -n "$SSH_PID" ]] && kill -0 "$SSH_PID" 2>/dev/null; then
    kill "$SSH_PID" 2>/dev/null || true
  fi
  rm -f "$TUNNEL_LOG"
}
trap cleanup EXIT INT TERM

echo "Поднимаю туннель localhost.run на порт $PORT…"
ssh -o StrictHostKeyChecking=accept-new \
    -o ServerAliveInterval=30 \
    -o ExitOnForwardFailure=yes \
    -R "80:localhost:${PORT}" \
    nokey@localhost.run >"$TUNNEL_LOG" 2>&1 &
SSH_PID=$!

PUBLIC_URL=""
for _ in $(seq 1 40); do
  PUBLIC_URL="$(grep -oE 'https://[a-zA-Z0-9.-]+\.(lhr\.life|localhost\.run)' "$TUNNEL_LOG" \
    | grep -v 'admin\.localhost\.run' | head -1 || true)"
  [[ -n "$PUBLIC_URL" ]] && break
  if ! kill -0 "$SSH_PID" 2>/dev/null; then
    echo "Туннель завершился с ошибкой:" >&2
    cat "$TUNNEL_LOG" >&2
    exit 1
  fi
  sleep 1
done

if [[ -z "$PUBLIC_URL" ]]; then
  echo "Не удалось получить публичный URL туннеля. Лог:" >&2
  cat "$TUNNEL_LOG" >&2
  exit 1
fi

echo "Публичный URL Mini App: $PUBLIC_URL"
echo "Запускаю бота с WEBAPP_URL=$PUBLIC_URL"
echo

# Без exec, чтобы trap остановил SSH-туннель после завершения бота.
WEBAPP_URL="$PUBLIC_URL" "$PY" bot.py
