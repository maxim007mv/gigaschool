-- КАРКАС · миграция 005 · каталог ПО/сервисов (V-SVC-01, S18).
INSERT INTO service_catalog (name, category, available_ru, lifecycle, latest_version, checked_on, note) VALUES
('Python', 'tool', true, 'current', '3.13', CURRENT_DATE, 'Язык программирования'),
('PostgreSQL', 'platform', true, 'current', '17', CURRENT_DATE, 'СУБД'),
('Docker', 'platform', true, 'current', '27', CURRENT_DATE, 'Контейнеризация'),
('Git', 'tool', true, 'current', '2.47', CURRENT_DATE, 'Система контроля версий'),
('Visual Studio Code', 'tool', true, 'current', '1.95', CURRENT_DATE, 'Редактор кода'),
('VSCodium', 'tool', true, 'current', '1.95', CURRENT_DATE, 'Сборка VS Code без телеметрии'),
('Jupyter Notebook', 'tool', true, 'current', '7.2', CURRENT_DATE, 'Интерактивные блокноты'),
('Linux', 'platform', true, 'current', '6.x', CURRENT_DATE, 'ОС для серверов и разработки'),
('Ubuntu', 'platform', true, 'current', '24.04', CURRENT_DATE, 'Дистрибутив Linux'),
('Astra Linux', 'platform', true, 'current', '1.8', CURRENT_DATE, 'Отечественный дистрибутив'),
('РЕД ОС', 'platform', true, 'current', '8', CURRENT_DATE, 'Отечественный дистрибутив'),
('GigaChat', 'ai_service', true, 'current', '3', CURRENT_DATE, 'Cloud.ru Foundation Models'),
('Yandex Cloud', 'platform', true, 'current', '2025', CURRENT_DATE, 'Облачная платформа'),
('GitLab CE', 'platform', true, 'current', '17', CURRENT_DATE, 'Git-платформа'),
('Gitea', 'platform', true, 'current', '1.22', CURRENT_DATE, 'Лёгкий Git-сервер'),
('ChatGPT', 'ai_service', false, 'current', '2025', CURRENT_DATE, 'Недоступен для официального контура РФ'),
('GitHub Copilot', 'ai_service', false, 'current', '2025', CURRENT_DATE, 'Недоступен для официального контура РФ')
ON CONFLICT (name) DO NOTHING;

-- Дополнительные профстандарты (коды Минтруда; реквизиты приказов — сверять с реестром).
INSERT INTO prof_standard (code, title, order_number, order_date, source) VALUES
('06.022', 'Системный аналитик', NULL, NULL, 'требует проверки: номер приказа Минтруда'),
('06.026', 'Администратор информационных и коммуникационных систем', NULL, NULL, 'требует проверки'),
('01.003', 'Педагог дополнительного образования', NULL, NULL, 'требует проверки'),
('01.001', 'Педагог', NULL, NULL, 'требует проверки')
ON CONFLICT (code) DO NOTHING;
