# Пайплайн после изменения кода

1. **Самопроверка** — `docs/development/principal-review.md` (авто-режим) по `git diff`.
2. **Тесты** — `.venv/bin/pytest tests --ignore=tests/payments_audit`; при изменении `web/` — `cd web && npx tsc --noEmit && npx vitest run`.
3. **Независимое ревью** — по желанию: второй разработчик или отдельный прогон чек-листа по diff.
4. **Changelog** — важные фиксы: `docs/development/changelog-format.md` → `changelog.md`.
5. **Отчёт** — что сделано, тесты, открытые риски.

Коммит и push в `main` — только по согласованию; повседневная работа в ветке `dev`.
