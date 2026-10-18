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

## Быстрый старт (ВМ хакатона, порт 8000)

Приложение для приёмки слушает **`0.0.0.0:8000`**: REST API, OpenAPI и (после сборки) SPA методиста с того же порта.

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env   # при необходимости; на ВМ часто уже заданы OPENAI_BASE_URL и OPENAI_API_KEY
```

Переменные LLM (не коммитить ключи):

| Переменная | Назначение |
|------------|------------|
| `OPENAI_BASE_URL` / `FM_BASE_URL` | OpenAI-совместимый шлюз Cloud.ru |
| `OPENAI_API_KEY` / `FM_API_KEY` | Ключ доступа |
| `MODEL_STRUCT` | Каркас, компетенции (напр. `GigaChat/GigaChat-3-Pro`) |
| `MODEL_BULK` | Массовая генерация содержания |
| `MODEL_EMBED` | Эмбеддинги (`ai-sage/Giga-Embeddings-instruct-3B`) |

Для reasoning-моделей с длинным «скрытым» выводом задайте `LLM_MAX_OUTPUT_TOKENS>=1000` (см. вебинар по моделям).

PostgreSQL 16+/17 + pgvector:

```bash
.venv/bin/python -m migrations.runner --demo   # демо-программа 248 ч
.venv/bin/python -m karkas.worker --concurrency 4 &
bash scripts/serve.sh                          # API + UI на :8000
```

Для кликабельных ссылок на выгрузки в local storage задайте `PUBLIC_API_BASE=http://<хост>:8000` (по умолчанию `http://127.0.0.1:8000`).

Разработка фронтенда отдельно (hot reload, прокси на API):

```bash
.venv/bin/uvicorn karkas.api.main:app --host 0.0.0.0 --port 8000 --reload
cd web && npm install && npm run dev           # http://localhost:5173 → /api на :8000
```

Материалы кейса — в каталог [`data/`](data/README.md) (шаблоны, открытые запросы, JSON для eval).

## Eval и чек-листы

Детерминированные проверки по пунктам ТК-ОБЩ / ТК-1…ТК-5 над экспортом `KitV1`:

```bash
.venv/bin/pytest tests/eval -q
.venv/bin/python scripts/run_eval.py           # все data/eval/tk*.json
```

## Тесты (обязательный пайплайн проекта — AGENTS.md)

```bash
.venv/bin/pytest tests/unit -q                     # юниты домена и инфраструктуры
.venv/bin/pytest tests/eval -q                     # чек-листы (без живых моделей)
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
