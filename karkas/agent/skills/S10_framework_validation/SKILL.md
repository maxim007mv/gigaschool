# S10 · Проверка каркаса

## Цель
Прогнать утверждаемый каркас через доменные валидаторы V-* и вернуть отчёт с
блокирующими ошибками. Шаг — обязательная часть Human Gate: пока есть `error`,
утверждение каркаса запрещено (framework:approve → 409).

## Вход
- `kit` (или `ctx.extra["kit"]`) — каркас KitV1 (модель или JSON);
- `registries` — реестры (НПА, профстандарты, ТФ, сервисы) для V-SRC/V-SVC;
- `reference_texts`, `declared_totals` — для V-PLG-01 и V-SMP-01;
- `today` — дата проверки (ISO), по умолчанию — текущая.

## Правила
1. Все проверки выполняет `karkas.domain.validators.run_validation` — логика правил
   не дублируется в навыке.
2. Реестры принимаются как `RegistryBundle` или словарём из JSON.
3. Отчёт не переписывается: навык только сериализует его (`Report.model_dump`).
4. Ошибки уровня `error` блокируют утверждение, `warning` — попадают в отчёт для методиста.

## Выход (schema.json)
`{report{passed, version, duration_ms, summary, issues[], gaps[], sample_findings[], assumptions[]}, passed, error_count}`

## Зависимости
- S09 (график), S04 (ошибки образца — V-SMP-01).

## Проверка после шага
- V-HRS-01…09, V-CAL-01, V-COV-01…04, V-SEQ-01, V-SRC-01…04, V-TPL-01…03, V-PLG-01, V-SVC-01, V-REQ-01;
- `passed = false`, если есть хотя бы одна `error` (правило Human Gate).

## Модель
Чистый код (`model_class=none`); смысловые LLM-проверки комплекта выполняются в S19.
