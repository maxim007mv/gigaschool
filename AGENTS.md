# КАРКАС — правила работы в репозитории (AGENTS.md)

Проект: ИИ-агент проектирования образовательных программ «КАРКАС» (хакатон «Точка сборки», кейс №1, АЦР + GigaCowork).
Спецификации: `specs/01_Архитектура.md`, `specs/02_База_данных.md`, `specs/03_Веб-интерфейс.md`, `specs/04_Backend_и_API.md`, `specs/05_Полное_описание_и_трассировка.md`.

## Главное правило

**Всё, что написано — тестируется.** После любого кода: самопроверка `principal-review` (авто-режим, см. `.cursor/skills/principal-review/SKILL.md`), прогон тестов, затем НЕЗАВИСИМАЯ проверка отдельным субагентом с чистым контекстом (он сам читает код и сам запускает тесты, без подсказок). Важные изменения — запись в `changelog.md` (см. `.cursor/rules/changelog.mdc`). Полный пайплайн — `.cursor/rules/review-pipeline.mdc`.

## Команды

- Тесты backend: `.venv/bin/pytest tests -q` → 0 failed (unit + contract + integration на живом PostgreSQL).
- Тесты SQL: `bash scripts/test_migrations.sh` (PostgreSQL 17 + pgvector, миграции, триггеры Human Gate, демо 248 ч).
- Frontend: `cd web && npx tsc --noEmit && npx vitest run`; сборка — `npm run build`.

## Архитектурные инварианты (нарушение = дефект)

- Часы хранятся ТОЛЬКО в `topic_workload` (листовой уровень); итоги — представления `v_topic_hours` / `v_module_hours` / `v_program_hours`.
- Human Gate: генерация комплекта до утверждения каркаса запрещена (API 409 GATE_NOT_PASSED + триггер БД `program_gate`).
- Часы распределяет детерминированный солвер (`karkas/domain/hours.py`), не LLM. LLM предлагает только веса, «практичность», формулировки.
- **Тексты .docx / .pptx** — только из комплекта (GigaChat, S11–S17): программа, слайды, заметки, макет слайда. `infra/exporters/*` — рендер (python-docx/python-pptx) и проверки, **без** подстановки педагогических шаблонов. Экономия токенов — компактные промпты и узкий контекст, не отказ от ИИ в выгрузках.
- Справочники-реестры: коды профстандартов/ТФ/НПА попадают в документ только из реестра; неподтверждённое помечается.
- Деньги — `Decimal`/копейки; `datetime.utcnow()` запрещён (только `datetime.now(timezone.utc)`).
- Все ответы навыков — Pydantic v2 модели; `model_config`, не `class Config`.
- Слои: `domain` — чистые функции без БД/HTTP/LLM; `agent` вызывает domain+infra; `api` — тонкий слой.

## Стек

Python 3.13 (`karkas/`), PostgreSQL 16+/17 + pgvector, FastAPI + Pydantic v2, SQLAlchemy Core + asyncpg, React 18 + TS + Vite (`web/`). LLM — только Cloud.ru Foundation Models (OpenAI-совместимый API).
