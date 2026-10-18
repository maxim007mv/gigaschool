# Code review — КАРКАС (2026-10-18)

Ревью уровня production: безопасность, корректность, поддерживаемость. Актуально для ветки `dev` / релизов в `main`.

## Исправлено в этом проходе

| Severity | Находка | Фикс |
|----------|---------|------|
| **High** | `kit_core` не вызывал **S17** перед **S18** → пустые источники / расхождение с тестами | Добавлен шаг S17, в S18 передаются `sources` |
| **Medium** | Загрузка файлов: имя с `..` / путём | `PurePath.name`, отклонение `..` в `files.py` |
| **Low** | Нет структурного лога токенов с шлюза | `logger.info("llm.usage", skill=…, prompt_tokens=…)` в `llm_gateway` |
| **Low** | Промпты раздувались pretty JSON | `to_json()` компактный по умолчанию; бенчмарк `compare_compact_savings` |

## Открыто (обоснованно)

| Severity | Находка | Рекомендация |
|----------|---------|--------------|
| **Medium** | `mypy --strict` на всём `karkas/domain` — десятки `type-arg` в validators | Поэтапно типизировать `list`/`dict` в validators; CI: `mypy karkas/domain` с `disable_error_code` |
| **Medium** | Live HTTP-проверка URL источников (S18) отключена | Осознанная заглушка хакатона; включать только с egress allowlist |
| **Low** | `kit_core` по умолчанию слайды только 1-го модуля | Опция `slides.modules` в API; для полного комплекта — явный список |
| **Low** | Дублирование `FakeGateway` (тесты vs `karkas/eval/fake_llm.py`) | Постепенно перевести интеграционные тесты на `karkas.eval.fake_llm` |
| **Info** | Секреты только в env — ок; промпты не в логах (хэш в gateway) | Периодический аудит `grep API_KEY` в репо |

## Безопасность (чек-лист)

- **Auth:** программы/файлы — JWT + org scope (`require_roles`, `get_file` с org_id).
- **Upload:** лимит размера, MIME/ingest, имя файла без path traversal (исправлено).
- **Local storage download:** `relative_to(store.root)` — ок.
- **LLM:** allowlist моделей, concurrency 2, без утечки ключей в репозиторий.

## Качество кода / границы модулей

- **domain/** — чистая логика (часы, валидаторы, kit).
- **agent/** — навыки, gateway, pipeline.
- **infra/** — БД, экспорт, storage.
- **api/** — тонкие роутеры.
- Единая проверка: `make check` / `scripts/check.sh` (ruff, mypy domain, pytest).

## Метрики

- Токены по шагам: `scripts/benchmark_pipeline.py`
- Время (FakeGateway): тот же скрипт, секция `timings_fake_gateway_sec`
- Live: `llm.usage` в логах + таблица `llm_call`
