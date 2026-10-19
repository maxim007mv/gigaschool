# Runbook: деплой и демо «КАРКАС» на VM хакатона

Цель: поднять демо «КАРКАС» (кейс №1, «Точка сборки») с API на порту **8000** (требование площадки), SPA и PostgreSQL + pgvector.

Файлы: `deploy/docker-compose.yml`, `deploy/Dockerfile`, `deploy/Dockerfile.web`, `deploy/Caddyfile`, `scripts/serve.sh`.

## 1. Требования к VM

- Docker Engine 24+ с `docker compose` v2 **или** Python 3.12+ для `scripts/serve.sh`.
- RAM ≥ 4 ГБ (compose: `postgres` с `shared_buffers=2GB`).
- Порты: **8000** (API для приёмки), при Docker+Caddy также **80/443**.
- Egress на Cloud.ru Foundation Models (`FM_BASE_URL`, см. `docs/hub/hub_notes.md`).

## 2. Клонирование и ветка

```bash
git clone https://github.com/maxim007mv/gigaschool.git && cd gigaschool
git checkout dev
cp .env.example .env
```

## 3. Переменные `.env` (имена без значений)

`.env.example` по умолчанию включает lite-режим: `KARKAS_LITE=1`, `DATABASE_URL`
закомментирован, модели `MODEL_STRUCT`/`MODEL_BULK`/`MODEL_EMBED` уже заполнены.
Этот режим подходит для локального демо на SQLite.

Обязательные для генерации и `/readyz`:

- `JWT_SECRET` — в prod не менее 32 символов, без placeholder (в `.env.example`
  строка закомментирована, её нужно задать)
- `FM_API_KEY`, `FM_BASE_URL`
- `MODEL_STRUCT`, `MODEL_BULK`, `MODEL_EMBED` (например `ai-sage/Giga-Embeddings-instruct-3B`), при необходимости `MODEL_RERANK`
- `DATABASE_URL` — только для PostgreSQL; в compose это
  `postgresql+asyncpg://karkas:karkas@postgres:5432/karkas`, при этом задайте
  `KARKAS_LITE=0` и раскомментируйте строку `DATABASE_URL`.

Опционально: `S3_*`, `TARIFFS_JSON`, `MODEL_ALLOWLIST`, `DAILY_BUDGET_RUB` (по умолчанию
100 ₽/сутки; в `.env.example` не выведен). Полный список — `.env.example` и
`karkas/settings.py`.

## 4. Вариант A — быстрый демо на :8000 (хакатон)

Без Docker, один процесс API + один воркер (`--concurrency 1`); семафор шлюза —
не более 2 LLM-запросов на команду:

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
# PostgreSQL снаружи или KARKAS_LITE=1 (SQLite) — см. scripts/serve.sh
bash scripts/serve.sh
```

Проверка: `curl -s http://127.0.0.1:8000/healthz` и `curl -s http://127.0.0.1:8000/api/v1/healthz` → `{"status":"ok",...}`.

Миграции при PostgreSQL: `.venv/bin/python -m migrations.runner` и `--demo` для
сидов `900_*`, `901_demo_password.sql` (без фиктивных usage-рядов). В lite-режиме
тот же раннер применяет `migrations/sqlite/001–004`.

## 5. Вариант B — Docker Compose

Перед запуском compose в `.env` задайте `KARKAS_LITE=0` и раскомментируйте
`DATABASE_URL` — иначе api/worker/migrate унаследуют lite-режим из `.env.example`
и будут работать каждый со своей SQLite-базой внутри контейнера.

```bash
docker compose -f deploy/docker-compose.yml build
```

Собирается образ `karkas` (`deploy/Dockerfile`). SPA отдельно:

```bash
docker build -f deploy/Dockerfile.web -t karkas-web:local .
docker volume create gigaschool_web_dist 2>/dev/null || true
docker run --rm -v gigaschool_web_dist:/out karkas-web:local
```

Миграции:

```bash
docker compose -f deploy/docker-compose.yml up migrate
docker compose -f deploy/docker-compose.yml run --rm migrate python -m migrations.runner --demo
```

`--demo` подключает `migrations/sql/900_demo_sample248.sql` и `901_demo_password.sql` (Argon2id для `methodist@acr-demo.example`). Сиды `902_*` с фиктивными `llm_call` **не используются**.

Запуск:

```bash
docker compose -f deploy/docker-compose.yml up -d
```

Порядок: `postgres` → `migrate` → `api` + `worker` → `caddy`. API слушает **8000 внутри сети**; с хоста без проброса порта — через Caddy (`deploy/Caddyfile`) или добавьте в `api` секцию `ports: ["8000:8000"]` для прямого доступа.

## 6. Демо-вход (B-02)

После `--demo` и миграции `901_demo_password.sql`:

- E-mail: `methodist@acr-demo.example`
- Пароль: значение `DEMO_PASSWORD` в `web/src/pages/LoginPage.tsx` (префилл формы; не коммитить в runbook)

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"methodist@acr-demo.example","password":"<DEMO_PASSWORD>"}'
```

## 7. Smoke-check

```bash
BASE=http://127.0.0.1:8000
curl -s $BASE/healthz
curl -s $BASE/api/v1/readyz   # 200 при БД + FM_API_KEY + моделях
PID=00000000-0000-0000-0000-0000000000b1
curl -s -H "Authorization: Bearer <token>" $BASE/api/v1/programs/$PID/usage
```

## 8. Caddy (OPS)

В `deploy/Caddyfile` заменить `admin@example.com` и `karkas.example.com` на реальные значения перед прод-TLS.

## 9. Откат

1. `docker compose -f deploy/docker-compose.yml down`
2. `git checkout <предыдущий коммит>` на `dev`
3. Пересобрать образы, повторить миграции и `up -d`
4. Дамп БД: `docker compose exec -T postgres pg_dump -U karkas karkas > backup.sql`
