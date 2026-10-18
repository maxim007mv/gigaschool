-- КАРКАС · миграция 007 · профстандарты для ТК-2…ТК-5 (коды из реестра Минтруда).
-- Перед релизом сверить с profstandart.rosmintrud.ru; дубли ON CONFLICT пропускаются.

INSERT INTO prof_standard (code, title, order_number, order_date, source) VALUES
('01.001', 'Педагог', '608н', '2013-10-18', 'profstandart.rosmintrud.ru, реестр ПС (ТК-2)'),
('01.003', 'Педагог дополнительного образования', '608н', '2013-10-18', 'profstandart.rosmintrud.ru, реестр ПС'),
('06.022', 'Системный аналитик', NULL, NULL, 'profstandart.rosmintrud.ru, реестр ПС (ТК-3 анализ данных)'),
('06.026', 'Администратор информационных и коммуникационных систем', NULL, NULL,
 'profstandart.rosmintrud.ru, реестр ПС (ТК-5 DevOps/администрирование)')
ON CONFLICT (code) DO NOTHING;

-- Трудовые функции «Педагог» (ТК-2): одна обобщённая ТФ для привязки S05/S06.
INSERT INTO labor_function (prof_standard_id, otf_code, code, title, qual_level)
SELECT ps.id, 'A', 'A/01.1', 'Организация и проведение занятий с обучающимися', 6
FROM prof_standard ps
WHERE ps.code = '01.001'
  AND NOT EXISTS (
    SELECT 1 FROM labor_function lf
    WHERE lf.prof_standard_id = ps.id AND lf.code = 'A/01.1'
  );
