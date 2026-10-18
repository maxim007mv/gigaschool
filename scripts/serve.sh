#!/usr/bin/env bash
# Демо хакатона: lite-БД (без PostgreSQL), миграции, API + SPA на 0.0.0.0:8000.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -e ".[dev]"
fi

if [[ ! -d web/dist ]]; then
  echo "Сборка фронтенда (web/dist)…"
  (cd web && npm ci && VITE_USE_MOCKS=0 npm run build)
fi

if [[ -z "${DATABASE_URL:-}" ]] && [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  export KARKAS_LITE=1
  mkdir -p var
  export DATABASE_URL="sqlite+aiosqlite:///var/karkas.db"
  echo "PostgreSQL не задан — режим KARKAS_LITE (SQLite: ${DATABASE_URL})"
fi

export PUBLIC_API_BASE="${PUBLIC_API_BASE:-http://127.0.0.1:8000}"

echo "Миграции…"
.venv/bin/python -m migrations.runner --demo

echo "Запуск воркера очереди job…"
.venv/bin/python -m karkas.worker --concurrency 2 &
WORKER_PID=$!
trap 'kill "$WORKER_PID" 2>/dev/null || true' EXIT

echo "API + UI: http://0.0.0.0:8000 (PUBLIC_API_BASE=${PUBLIC_API_BASE})"
exec .venv/bin/uvicorn karkas.api.main:app --host 0.0.0.0 --port 8000
