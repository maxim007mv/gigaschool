# КАРКАС — правила работы в репозитории

Проект: ИИ-агент проектирования образовательных программ «КАРКАС» (хакатон «Точка сборки», кейс №1, АЦР + GigaCowork).
Спецификации: `specs/01_Архитектура.md` … `specs/05_Полное_описание_и_трассировка.md`.

## Главное правило

**Всё, что написано — тестируется.** После кода: самопроверка (`docs/development/principal-review.md`), pytest, при необходимости — независимое ревью (`docs/development/review-pipeline.md`). Важные изменения — `changelog.md` (`docs/development/changelog-format.md`).

## Команды

- Тесты backend: `.venv/bin/pytest tests -q`
- SQL: `bash scripts/test_migrations.sh`
- Frontend: `cd web && npx tsc --noEmit && npx vitest run`
- Полная проверка: `make check`

## Архитектурные инварианты

- Часы — только в `topic_workload`; итоги — представления `v_*_hours`.
- Human Gate до генерации комплекта (API 409 + триггер БД).
- Солвер часов — `karkas/domain/hours.py`, не LLM.
- Тексты .docx/.pptx — только из комплекта (GigaChat); экспортёры рендерят KitV1.
- Реестры: коды ПС/ТФ/НПА только из подтверждённых источников.
- Деньги — `Decimal`; время — `datetime.now(timezone.utc)`.
- Pydantic v2; слои domain / agent / api / infra.

## Стек

Python 3.12+, PostgreSQL 16+/17 + pgvector, FastAPI, React 18 + Vite (`web/`), Cloud.ru Foundation Models.
