#!/usr/bin/env bash
# Запуск API (+ SPA из web/dist) на 0.0.0.0:8000 для приёмки хакатона.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -e ".[dev]"
fi

if [[ ! -d web/dist ]]; then
  echo "Сборка фронтенда (web/dist)…"
  (cd web && npm ci && npm run build)
fi

if [[ -z "${DATABASE_URL:-}" ]] && [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export PUBLIC_API_BASE="${PUBLIC_API_BASE:-http://127.0.0.1:8000}"
echo "API + UI: http://0.0.0.0:8000 (PUBLIC_API_BASE=${PUBLIC_API_BASE})"
exec .venv/bin/uvicorn karkas.api.main:app --host 0.0.0.0 --port 8000
