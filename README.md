# КАРКАС

ИИ-агент проектирования образовательных программ с верифицируемым каркасом и Human-in-the-Loop
(хакатон «Точка сборки», кейс №1, АЦР + GigaCowork).

**Главная идея:** LLM пишет тексты, а структура, арифметика и проверки — детерминированный код.
Каркас ≤ 3 минут, комплект 72 ч ≤ 20 минут, генерация содержания только после утверждения
каркаса человеком (Human Gate), коды профстандартов/НПА — только из реестров.

## Структура

```
karkas/
├─ api/            FastAPI: роутеры, схемы, problem+json, SSE
├─ agent/          llm_gateway (Cloud.ru FM), skill_runner (DAG), skills/ S01–S23
├─ domain/         чистые функции: hours (солвер), calendar, validators (V-*),
│                  dependency_graph, framework_ops, kit (KitV1), templates/*.yaml
├─ infra/          db, repos, jobs (очередь), storage (S3), ingest, exporters, metrics
└─ worker.py       цикл воркера очереди
migrations/        SQL-миграции 001–003 + раннер (python -m migrations.runner)
web/               SPA методиста (React 18 + TS + Vite)
tests/             unit / integration / eval / contract
specs/             спецификации Д1–Д5 (извлечены из .docx)
deploy/            Docker Compose, Caddy, Dockerfile (профиль A)
```

## Быстрый старт (локально)

```bash
python3.13 -m venv .venv && .venv/bin/pip install -e ".[dev]"
# PostgreSQL 16+/17 + pgvector; затем:
cp .env.example .env               # заполнить FM_API_KEY и модели
.venv/bin/python -m migrations.runner --demo
.venv/bin/uvicorn karkas.api.main:app --reload
.venv/bin/python -m karkas.worker --concurrency 4
cd web && npm install && npm run dev
```

## Тесты (обязательный пайплайн проекта — AGENTS.md)

```bash
.venv/bin/pytest tests/unit -q                     # юниты домена и инфраструктуры
.venv/bin/pytest tests/integration -q              # живой PostgreSQL (миграции, репозитории)
bash scripts/test_migrations.sh                    # DDL + триггеры Human Gate
cd web && npx tsc --noEmit && npx vitest run       # фронтенд
```

## Ключевые инварианты

- Часы — только в `topic_workload`; итоги вычисляются представлениями (`v_*_hours`).
- Утверждение каркаса с несходящимися часами блокируется API (409 `HOURS_MISMATCH`) и триггером БД.
- Генерация комплекта до утверждения — 409 `GATE_NOT_PASSED` (+ триггер `program_gate`).
- Солвер часов детерминирован (`karkas/domain/hours.py`), LLM даёт только веса и «практичность».
- Секреты — только в окружении; тексты промптов в логи не пишутся (только хэш и размер).

## Документы

- `specs/01_Архитектура.md` … `specs/05_Полное_описание_и_трассировка.md` — полный текст Д1–Д5.
- `AGENTS.md`, `.cursor/rules/*.mdc`, `.cursor/skills/principal-review/SKILL.md` — правила работы
  (всё тестируется; после кода — самопроверка, тесты, независимая проверка субагентом).
- `changelog.md` — история важных изменений.
