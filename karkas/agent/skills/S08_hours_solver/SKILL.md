# S08 · Солвер часов

## Цель
Распределить академические часы по темам и видам работ детерминированно
(метод наибольших остатков + ремонт ограничений) и доказать инварианты V-HRS.
LLM в этом шаге не участвует.

## Вход
- `modules` (из S07): `{ref, weight, topics[{ref, weight, practicality, has_lab}]}`;
- `constraints`: `total`/`total_hours`, `final_att`, `unit`, `self_study_only`,
  `min_practice_share(_pct)`, `self_study_share(_pct)`, `distance_share(_pct)`;
- `locked_cells` — закреплённые ячейки для `rebalance` (точечная правка часов).

## Правила
1. Часы распределяет ТОЛЬКО `karkas.domain.hours.solve/rebalance` — логика не дублируется.
2. Доли принимаются и как 0…1 (`min_practice_share`), и как 0…100 % (`*_pct`).
3. Если переданы `locked_cells` — вызывается `rebalance`, иначе `solve`.
4. Противоречивые ограничения не «проглатываются»: `HoursInfeasible` уходит наверх
   с объяснением для методиста.

## Выход (schema.json)
`{rows[{topic_ref: {lecture, practice, lab, self_study, current_control}}], distance{}, module_of{}, proof[{rule, ok, message}], constraints{...}}`

## Зависимости
- S07 (структура модулей и тем).

## Проверка после шага
- V-HRS-01 Σ строк + ИА = объём; V-HRS-06 Σ видов = итог строки; V-HRS-07 Σ тем = модуль;
- V-HRS-04 (стажировка: ЛК = ПР = ЛБ = 0) и V-HRS-05 (доля практики) — в `proof`;
- одинаковый вход даёт одинаковый выход (детерминизм солвера).

## Модель
Чистый код (`model_class=none`), LLM не вызывается: арифметика часов — ответственность домена.
