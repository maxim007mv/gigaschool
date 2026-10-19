#!/usr/bin/env bash
# Единая проверка перед PR: линт, типы (domain), тесты, фронт typecheck.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -x .venv/bin/ruff ]]; then
  .venv/bin/ruff check karkas tests scripts
  .venv/bin/ruff format --check karkas tests scripts
else
  echo "ruff не установлен — pip install -e '.[dev]'"
  exit 1
fi

if [[ -x .venv/bin/mypy ]]; then
  .venv/bin/mypy karkas/domain
else
  echo "mypy не установлен — пропуск"
fi

.venv/bin/pytest tests --ignore=tests/payments_audit -q

if [[ -f examples/tk1/kit_tk1.json && -f examples/tk2/kit_tk2.json ]]; then
  .venv/bin/python scripts/run_eval.py --kit examples/tk1/kit_tk1.json --case tk1 --validate
  .venv/bin/python scripts/run_eval.py --kit examples/tk2/kit_tk2.json --case tk2 --validate
fi

if [[ -d web/node_modules ]]; then
  (cd web && npm run typecheck)
else
  echo "web/node_modules нет — пропуск tsc (запустите npm install в web/)"
fi

echo "check: OK"
