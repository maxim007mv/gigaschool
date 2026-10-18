-- =====================================================================
-- КАРКАС · 901_demo_password · Argon2id-хэш пароля демо-пользователя (B-02)
-- Демо-креды (НЕ прод): methodist@acr-demo.example; пароль — константа
-- DEMO_PASSWORD в web/src/pages/LoginPage.tsx (префилл формы входа).
-- НЕ входит в production-цепочку: применяется только с migrations.runner --demo.
-- =====================================================================
BEGIN;
UPDATE app_user SET password_hash = '$argon2id$v=19$m=65536,t=3,p=4$FyTuCfCQKn48mgnbzAN+mw$i1JGNc7D3BC7PdhSecBh8efCQ5M9QUstvtt4Ly3T1BA' WHERE email = 'methodist@acr-demo.example';
COMMIT;
