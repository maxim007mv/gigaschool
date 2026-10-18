# КАРКАС

ИИ-агент проектирования образовательных программ с верифицируемым каркасом и Human-in-the-Loop
(хакатон «Точка сборки», кейс №1, АЦР + GigaCowork).

Продуктовый бриф: [`data/templates/product_brief_karkas.md`](data/templates/product_brief_karkas.md).
Правила хаба и лимиты LLM: [`docs/hub/hub_notes.md`](docs/hub/hub_notes.md).
Трассировка «требование → модуль → тест»: [`docs/REQUIREMENTS_TRACEABILITY.md`](docs/REQUIREMENTS_TRACEABILITY.md).

## Запуск одной командой (демо для проверяющего)

```bash
git clone <repo> && cd gigaschool && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && bash scripts/serve.sh
```

Откройте `http://<хост>:8000` — SPA методиста и API. Без PostgreSQL используется lite-режим (SQLite, см. `KARKAS_LITE` в `scripts/serve.sh`).

**Главная идея:** LLM пишет тексты, а структура, арифметика и проверки — детерминированный код.
Каркас ≤ 3 минут, комплект 72 ч ≤ 20 минут, генерация содержания только после утверждения
каркаса человеком (Human Gate), коды профстандартов/НПА — только из реестров.

## Пять экранов SPA (как в брифе)

| # | Экран | Маршрут | Что делает |
|---|--------|---------|------------|
| 1 | Новый запрос | `/programs/new` | Бриф, файлы (.docx/.pdf/.txt), ползунок 16–500 ч, «Что агент уже понял» |
| 2 | Уточнения | `/programs/{id}/clarify` | До 5 вопросов, «на усмотрение агента» |
| 3 | Каркас: часы (Human Gate) | `/programs/{id}/framework` | Таблица часов, светофор ошибок, утверждение |
| 4 | Матрица связей | `/programs/{id}/framework` (вкладка «Связи») | РО ↔ темы ↔ оценочные средства |
| 5 | Комплект УМК | `/programs/{id}/kit` | Дерево материалов, самопроверка, выгрузка .docx/.pptx/LMS/JSON |

## Demo walkthrough (5 шагов для жюри)

После `bash scripts/serve.sh` откройте `http://<хост>:8000` (вход — демо-учётка на экране логина).

1. **Новый запрос** — введите бриф (например, открытый ТК-1 из `data/eval/test_cases_official.txt`), при необходимости приложите `.docx`, задайте объём 16–500 ч. После отправки увидите блок «Что агент уже понял».
2. **Уточнения** — ответьте на карточки вопросов или выберите «На усмотрение агента»; сверху — полоса этапов и статус программы.
3. **Каркас: часы** — вкладка «Учебный план»: таблица часов со светофором; исправьте ячейки или нажмите «Пересчитать»; **Утвердить каркас** доступно только при нуле ошибок.
4. **Матрица связей** — вкладка «Связи» на том же экране: компетенции ↔ темы ↔ оценочные средства.
5. **Комплект УМК** — дерево материалов слева, предпросмотр по центру, **отчёт самопроверки** справа (часы, покрытие, **шаблон АЦР**, замечания V-*). Панель «Эффект» показывает измеренные токены и ₽. Выгрузите `.docx` / `.pptx` / LMS / JSON.

Сквозной автопрогон для метрик защиты (нужен поднятый API и сервисный ключ):

```bash
export KARKAS_EVAL_API_KEY="<X-Api-Key>"
.venv/bin/python scripts/run_eval.py --live --case tk1 --api http://127.0.0.1:8000
```

Отчёт сохраняется в `data/eval/reports/` (время по этапам, токены, чек-лист).

## Метрики (только измеренные в продукте)

### Бенчмарк защиты (фикстурный запрос, оценка токенов)

Скрипт: `.venv/bin/python scripts/benchmark_pipeline.py --markdown` (детализация по S01–S19, compact JSON до/после).

| Объём | Prompt (оценка) | Completion (оценка) | Всего | ₽ GigaChat-3-Pro |
|------:|----------------:|--------------------:|------:|-----------------:|
| 16 ч  | 7 304           | 686                 | 7 990 | 0.65             |
| 72 ч  | 17 155          | 1 265               | 18 420| 1.48             |

Экономия **compact JSON** в промптах (pretty `indent=2` → компакт): **~1.5k / ~4.4k** prompt-токенов на 16 / 72 ч соответственно.  
Живые токены: лог `llm.usage` (skill, prompt_tokens, completion_tokens) и сумма в `llm_call` / UI «Эффект».

На экране **«Комплект УМК»** и в `GET /api/v1/programs/{id}/usage` (не фиксированные «рыночные» проценты):

- **Активное время методиста** и **экономия к базовой линии** (40 ч на программу в API) — из `audit_log`
- **Токены и ₽** — сумма `llm_call` × тариф Cloud.ru FM в настройках
- **FTAR каркаса** — доля программ с `framework.approve` без последующего `framework.reopen` (по аудиту)
- **Сходимость часов** — солвер + **V-HRS**; открытые ТК — `scripts/run_eval.py`

## Отличие от зарубежных аналогов

См. [`docs/competitors_registry.md`](docs/competitors_registry.md). Кратко: Mindsmith / Coursebox и др. не закрывают **российский регуляторный контур** (273-ФЗ, приказы № 499/629, шаблоны АЦР), **детерминированную сходимость часов**, **сквозную связку ЗУН ↔ темы ↔ оценочные средства** и жёсткий **Human Gate** до генерации УМК.

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
.venv/bin/python scripts/run_eval.py           # все data/eval/tk*.json (официальные чек-листы хаба)
.venv/bin/python scripts/export_eval_cases.py  # пересобрать tk*.json из reference_kits
```

LLM для хакатона: только модели Cloud.ru Foundation Models (`OPENAI_BASE_URL`), `max_tokens ≤ 4096`, не более 2 параллельных запросов (см. `docs/hub/hub_notes.md`).

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
