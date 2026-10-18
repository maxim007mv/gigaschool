# Трассировка: требование кейса → код → тест

Для автоматического LLM-ревью репозитория (технический чекпоинт хаба). Подробности — `docs/hub/hub_notes.md`, открытые ТК — `data/eval/test_cases_official.txt`.

| Требование | Реализация | Проверка |
|------------|------------|----------|
| Два шаблона АЦР (ДОП + ДПП ПК/стажировка), экспорт .docx | `karkas/infra/exporters/docx_program.py`, `karkas/domain/acr_reference.py`, `data/templates/acr_*` | `tests/unit/test_exporters_docx_pptx.py`, **V-ACR-01** `karkas/domain/validators/acr_export.py` |
| Часы только в темах, Σ сходится | `karkas/domain/hours.py`, `KitV1.grand_total()` | **V-HRS-***, `tests/unit/test_validators_hours.py` |
| Human Gate до комплекта | API 409 + триггер БД | `tests/integration/`, `scripts/test_migrations.sh` |
| Уточнения без «месяца» вместо часов | `karkas/domain/intake_slots.py` | `tests/unit/test_intake_slots.py` (если есть) / clarify pipeline |
| Профстандарты/НПА только из реестра, иначе пометка | `karkas/domain/validators/sources.py` | `tests/unit/test_validators_sources.py` |
| Ошибка итоговой строки образца 248 ч не копируется | **V-SMP-01** `validators/sample.py` + солвер часов | `tests/unit/test_validation_suite.py` (V-SMP-01) |
| Открытые ТК-1…ТК-5 | `data/eval/tk*.json`, `karkas/eval/checklists.py` | `tests/eval/test_data_kits.py`, `scripts/run_eval.py` |
| Cloud.ru GigaChat, лимиты токенов | `karkas/agent/llm_gateway.py`, `.env.example` | конфиг + ручной прогон eval с ключом |
| Одна команда демо | `scripts/serve.sh` (SQLite lite) | README «Быстрый старт» |
| Самопроверка в UI | отчёт `run_validation` → kit.report | `web/` KitPage, `tests/unit/test_exporters_docx_pptx.py` (report docx) |

## Команды для проверяющего

```bash
bash scripts/serve.sh                    # API+UI :8000 (lite)
.venv/bin/python scripts/run_eval.py     # чек-листы ТК-1…ТК-5
.venv/bin/pytest tests/eval tests/unit/test_exporters_docx_pptx.py -q
```
