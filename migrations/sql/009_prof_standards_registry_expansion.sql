-- КАРКАС · 009 · расширение реестра ПС и ТФ (сверено с текстами приказов Минтруда).
-- 06.026: приказ № 680н от 29.09.2020 (КонсультантПлюс LAW_366254, mintrud.gov.ru/docs/mintrud/orders/1648)
-- 06.042: приказ № 405н от 06.07.2020 (КонсультантПлюс LAW_359468)
-- 06.001: приказ № 424н от 20.07.2022 (КонсультантПлюс LAW_425094, mintrud.gov.ru/docs/mintrud/orders/2403)
-- 06.022: приказ № 367н от 27.04.2023 (mintrud.gov.ru/docs/mintrud/orders/2638)

UPDATE prof_standard SET
    title = 'Системный администратор информационно-коммуникационных систем',
    order_number = '680н',
    order_date = '2020-09-29'::date,
    source = 'Приказ Минтруда России от 29.09.2020 № 680н; profstandart.rosmintrud.ru (06.026)'
WHERE code = '06.026';

UPDATE prof_standard SET
    title = 'Системный аналитик',
    order_number = '367н',
    order_date = '2023-04-27'::date,
    source = 'Приказ Минтруда России от 27.04.2023 № 367н; profstandart.rosmintrud.ru (06.022)'
WHERE code = '06.022';

INSERT INTO prof_standard (code, title, order_number, order_date, source) VALUES
('06.042', 'Специалист по большим данным', '405н', '2020-07-06',
 'Приказ Минтруда России от 06.07.2020 № 405н; profstandart.rosmintrud.ru (06.042)'),
('06.001', 'Программист', '424н', '2022-07-20',
 'Приказ Минтруда России от 20.07.2022 № 424н; profstandart.rosmintrud.ru (06.001)')
ON CONFLICT (code) DO UPDATE SET
    title = EXCLUDED.title,
    order_number = EXCLUDED.order_number,
    order_date = EXCLUDED.order_date,
    source = EXCLUDED.source;

-- Удалить ошибочную ТФ B/01.2 (не из приказа 680н для 06.026).
DELETE FROM labor_function lf
USING prof_standard ps
WHERE lf.prof_standard_id = ps.id AND ps.code = '06.026' AND lf.code = 'B/01.2';

-- 06.026 — трудовые функции (приказ 680н).
INSERT INTO labor_function (prof_standard_id, otf_code, code, title, qual_level)
SELECT ps.id, v.otf, v.code, v.title, v.qual
FROM prof_standard ps
CROSS JOIN (VALUES
    ('A', 'A/01.4', 'Выполнение работ по выявлению и устранению типичных инцидентов информационно-коммуникационных систем', 4),
    ('A', 'A/02.4', 'Выполнение работ по управлению стандартными изменениями в технических и программных средствах информационно-коммуникационных систем по инструкции', 4),
    ('B', 'B/01.5', 'Выполнение работ по выявлению и устранению инцидентов в информационно-коммуникационных системах', 5),
    ('B', 'B/02.5', 'Обеспечение работы технических и программных средств информационно-коммуникационных систем', 5),
    ('C', 'C/03.6', 'Мониторинг событий, возникающих в процессе работы инфокоммуникационной системы', 6),
    ('C', 'C/04.6', 'Восстановление работоспособности программно-аппаратных средств инфокоммуникационной системы и/или ее составляющих после сбоев', 6)
) AS v(otf, code, title, qual)
WHERE ps.code = '06.026'
  AND NOT EXISTS (SELECT 1 FROM labor_function lf WHERE lf.prof_standard_id = ps.id AND lf.code = v.code);

-- 06.042 — специалист по большим данным (приказ 405н).
INSERT INTO labor_function (prof_standard_id, otf_code, code, title, qual_level)
SELECT ps.id, v.otf, v.code, v.title, v.qual
FROM prof_standard ps
CROSS JOIN (VALUES
    ('A', 'A/01.6', 'Выявление, формирование и согласование требований к результатам аналитических работ с применением технологий больших данных', 6),
    ('A', 'A/02.6', 'Планирование и организация аналитических работ с использованием технологий больших данных', 6),
    ('A', 'A/03.6', 'Подготовка данных для проведения аналитических работ по исследованию больших данных', 6),
    ('A', 'A/04.6', 'Проведение аналитических работ по исследованию больших данных', 6)
) AS v(otf, code, title, qual)
WHERE ps.code = '06.042'
  AND NOT EXISTS (SELECT 1 FROM labor_function lf WHERE lf.prof_standard_id = ps.id AND lf.code = v.code);

-- 06.001 — программист (приказ 424н).
INSERT INTO labor_function (prof_standard_id, otf_code, code, title, qual_level)
SELECT ps.id, v.otf, v.code, v.title, v.qual
FROM prof_standard ps
CROSS JOIN (VALUES
    ('A', 'A/01.3', 'Формализация и алгоритмизация поставленных задач для разработки программного кода', 3),
    ('A', 'A/02.3', 'Написание программного кода с использованием языков программирования, определения и манипулирования данными в базах данных', 3),
    ('A', 'A/05.3', 'Проверка и отладка программного кода', 3),
    ('B', 'B/03.4', 'Проверка работоспособности компьютерного программного обеспечения', 4)
) AS v(otf, code, title, qual)
WHERE ps.code = '06.001'
  AND NOT EXISTS (SELECT 1 FROM labor_function lf WHERE lf.prof_standard_id = ps.id AND lf.code = v.code);

-- 06.022 — системный аналитик (приказ 367н), дополнение к 008.
INSERT INTO labor_function (prof_standard_id, otf_code, code, title, qual_level)
SELECT ps.id, v.otf, v.code, v.title, v.qual
FROM prof_standard ps
CROSS JOIN (VALUES
    ('A', 'A/01.4', 'Сбор исходных данных для проектирования Системы из установленных при обследовании предметной области, объекта автоматизации, ИТ-инфраструктуры и ИТ-ландшафта источников информации', 4),
    ('A', 'A/02.4', 'Изучение и описание деятельности, подлежащей автоматизации, и работы пользователей в аналогичных, заменяемых, развиваемых или интегрируемых системах и продуктах', 4),
    ('B', 'B/01.5', 'Выделение и систематизация установленных фактов, требований и проектных решений, открытых вопросов и противоречий', 5)
) AS v(otf, code, title, qual)
WHERE ps.code = '06.022'
  AND NOT EXISTS (SELECT 1 FROM labor_function lf WHERE lf.prof_standard_id = ps.id AND lf.code = v.code);

UPDATE labor_function lf SET
    title = 'Сбор исходных данных для проектирования Системы из установленных при обследовании предметной области, объекта автоматизации, ИТ-инфраструктуры и ИТ-ландшафта источников информации',
    otf_code = 'A',
    qual_level = 4
FROM prof_standard ps
WHERE lf.prof_standard_id = ps.id AND ps.code = '06.022' AND lf.code = 'A/01.4';
