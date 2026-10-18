# Трассировка: требование → код → тест

Подробности хаба — `docs/hub/hub_notes.md`. Открытые ТК — `data/eval/test_cases_official.txt`. Продуктовый бриф — `data/templates/product_brief_karkas.md`.

## Кейс / хаб (технический чекпоинт)

| Требование | Реализация | Проверка |
|------------|------------|----------|
| Два шаблона АЦР (ДОП + ДПП ПК/стажировка), экспорт .docx | `docx_program.py`, `acr_reference.py`, `data/templates/acr_*` | `test_exporters_docx_pptx.py`, **V-ACR-01** |
| Часы только в темах, Σ сходится | `hours.py`, `KitV1.grand_total()` | **V-HRS-***, `test_validators_hours.py` |
| Human Gate до комплекта | API 409 + триггер БД | integration, `test_migrations.sh` |
| Открытые ТК-1…ТК-5 | `data/eval/tk*.json`, `checklists.py` | `test_data_kits.py`, `scripts/run_eval.py` |
| Произвольный kit JSON | `scripts/run_eval.py --kit … --case tkN` | `tests/eval/test_run_eval_kit_mode.py` |
| Live LLM + метрики защиты | `karkas/eval/live_run.py`, `defense_metrics.py` | `run_eval.py --live --case tk1` (нужен API + ключ) |
| Cloud.ru лимиты (2 concurrent, 4096 tokens, 120s) | `settings.py`, `llm_gateway.py` | unit gateway, `.env.example` |
| Одна команда демо | `scripts/serve.sh` | README |

## Продуктовый бриф (`product_brief_karkas.md`) — покрытие и пробелы

| Обещание брифа | Статус | Где в продукте | Пробел / заметка |
|----------------|--------|----------------|------------------|
| **5 экранов SPA** (бриф → уточнения → каркас часы → матрица → комплект) | ✅ | `IntakePage`, `ClarifyPage`, `FrameworkPage` (вкладки план/связи), `KitPage` | Матрица — вкладка «Связи» на том же маршруте `/framework`, не отдельный URL (достаточно для брифа) |
| Ползунок 16–500 ч, файлы, «что агент понял» | ✅ | `IntakePage.tsx` | — |
| До 5 уточняющих вопросов + «на усмотрение агента» | ✅ | `ClarifyPage`, `max_questions` в settings | — |
| Human Gate, светофор часов, утверждение | ✅ | `FrameworkPage`, `HoursGrid`, API 409 | — |
| Детерминированный солвер часов | ✅ | `domain/hours.py` | — |
| Оба шаблона АЦР + сверка структуры .docx | ✅ | экспорт + **V-ACR-01** в отчёте | Показ в UI: `ReportPanel` → строка «Шаблон АЦР» |
| Выгрузка .docx / .pptx / LMS / JSON | ✅ | `ExportMenu`, exporters | — |
| `POST /api/v1/agent/run` | ✅ | `api/routers/agent.py` | — |
| Метрики: время методиста, токены/₽, FTAR | ✅ (измеряемые) | `usage.py`, `EffectPanel` | **Нет** фиксированных «35%» / «85%» из маркетингового текста брифа — только факты из `audit_log` / `llm_call` |
| Метрики: V-HRS 100%, ТК1–5 | ✅ | `run_eval.py`, валидаторы | Live-качество зависит от LLM (`--live`) |
| Скорость каркаса ≤3 мин / комплект 72ч ≤20 мин | ⚠️ | `framework_slo_s`, `kit_timeout_min`, метрики в pipeline | **Нет** отдельного дашборда SLO в UI; есть `timings` в `agent/run` и live-отчёте |
| Точечная правка без пересборки всего | ✅ | `EditDrawer`, skills S21+ | — |
| Актуализация / адаптация программы | ⚠️ | `ActualizePage`, `AdaptPage` | Вне основного 5-шагового сценария демо; зрелость ниже каркас→комплект |
| Роль эксперт-преподаватель | ⚠️ | роль `expert` в API | **Нет** отдельного упрощённого UI для эксперта |
| Роль руководитель / методсовет | ⚠️ | отчёт самопроверки, выгрузка | **Нет** отдельного экрана «только отчёт» |
| Прогресс по этапам в UI | ✅ (этот раунд) | `ProgramStatusBar`, SSE на комплекте | Скриншоты в README — текстовый walkthrough |

## Команды

```bash
bash scripts/serve.sh
.venv/bin/python scripts/run_eval.py
.venv/bin/python scripts/run_eval.py --kit path/to/kit.json --case tk1
KARKAS_EVAL_API_KEY=… .venv/bin/python scripts/run_eval.py --live --case tk1 --api http://127.0.0.1:8000
.venv/bin/pytest tests/eval tests/unit/test_exporters_docx_pptx.py -q
```
