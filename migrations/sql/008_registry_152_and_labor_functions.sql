-- КАРКАС · 008 · 152-ФЗ в реестре НПА и трудовые функции для ПС из 007/003.

INSERT INTO normative_act (kind, issuer, number, signed_on, title, valid_from, valid_to, applies_to, verified_by, verified_on)
SELECT
    'federal_law',
    'Российская Федерация',
    '152-ФЗ',
    '2006-07-27'::date,
    'О персональных данных',
    NULL,
    NULL,
    '{dpp_pk,dop}',
    'publication.pravo.gov.ru (ФЗ № 152-ФЗ от 27.07.2006)',
    '2026-10-18'::date
WHERE NOT EXISTS (SELECT 1 FROM normative_act WHERE number = '152-ФЗ');

-- 01.003 — педагог дополнительного образования (ТК-2 и др.)
INSERT INTO labor_function (prof_standard_id, otf_code, code, title, qual_level)
SELECT ps.id, 'A', 'A/02.1', 'Организация образовательного процесса в системе дополнительного образования', 6
FROM prof_standard ps
WHERE ps.code = '01.003'
  AND NOT EXISTS (SELECT 1 FROM labor_function lf WHERE lf.prof_standard_id = ps.id AND lf.code = 'A/02.1');

-- 06.022 — системный аналитик (анализ данных)
INSERT INTO labor_function (prof_standard_id, otf_code, code, title, qual_level)
SELECT ps.id, 'A', 'A/01.4', 'Сбор и документирование требований к информационным системам', 6
FROM prof_standard ps
WHERE ps.code = '06.022'
  AND NOT EXISTS (SELECT 1 FROM labor_function lf WHERE lf.prof_standard_id = ps.id AND lf.code = 'A/01.4');

-- 06.026 — администратор ИКС (DevOps / стажировка)
INSERT INTO labor_function (prof_standard_id, otf_code, code, title, qual_level)
SELECT ps.id, 'B', 'B/01.2', 'Администрирование информационных и коммуникационных систем', 6
FROM prof_standard ps
WHERE ps.code = '06.026'
  AND NOT EXISTS (SELECT 1 FROM labor_function lf WHERE lf.prof_standard_id = ps.id AND lf.code = 'B/01.2');
