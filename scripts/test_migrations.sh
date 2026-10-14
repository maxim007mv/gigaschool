#!/usr/bin/env bash
# =====================================================================
# КАРКАС · scripts/test_migrations.sh
# Smoke-тест миграций 001→002→003→900 на живой PostgreSQL.
#
# Что делает:
#   1) создаёт свежую БД karkas_migr_test (DROP IF EXISTS + CREATE);
#   2) накатывает migrations/sql/001, 002, 003, 900 c ON_ERROR_STOP=1;
#   3) проверяет представления часов/покрытия по образцу 248 ч (Д2 §11–§12);
#   4) проверяет триггеры Human Gate, reopen и append-only.
#
# Любая не сходившаяся проверка → exit 1. Успех → последняя строка
# "MIGRATIONS TEST OK".
#
# Требуется: PostgreSQL 16+/17 с pgvector, pgcrypto, pg_trgm; psql в PATH
# (или /opt/homebrew/opt/postgresql@17/bin/psql) с доступом без пароля.
# =====================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SQL_DIR="$ROOT_DIR/migrations/sql"

TEST_DB="${TEST_DB:-karkas_migr_test}"
PGHOST_OPT="${PGHOST_OPT:-127.0.0.1}"
PGPORT_OPT="${PGPORT_OPT:-5432}"

# ---------- Поиск psql ---------------------------------------------------
PSQL_BIN=""
for cand in "$(command -v psql 2>/dev/null)" \
            /opt/homebrew/opt/postgresql@17/bin/psql \
            /opt/homebrew/opt/postgresql@16/bin/psql \
            /usr/local/opt/postgresql@17/bin/psql \
            /usr/local/opt/postgresql@16/bin/psql \
            /Applications/Postgres.app/Contents/Versions/latest/bin/psql; do
  if [ -n "$cand" ] && [ -x "$cand" ]; then
    PSQL_BIN="$cand"
    break
  fi
done
if [ -z "$PSQL_BIN" ]; then
  echo "FAIL: psql не найден (ни в PATH, ни в /opt/homebrew/opt/postgresql@17/bin)" >&2
  exit 1
fi

# ---------- Подключение: сначала TCP, затем локальный сокет --------------
CONN=(-h "$PGHOST_OPT" -p "$PGPORT_OPT")
if ! "$PSQL_BIN" -X -q -d postgres "${CONN[@]}" -c 'SELECT 1' >/dev/null 2>&1; then
  CONN=()
  if ! "$PSQL_BIN" -X -q -d postgres -c 'SELECT 1' >/dev/null 2>&1; then
    echo "FAIL: не удалось подключиться к PostgreSQL (ни $PGHOST_OPT, ни локальный сокет)" >&2
    exit 1
  fi
fi

PSQL_OPTS=(-X -q -v ON_ERROR_STOP=1 "${CONN[@]}")

fail() { echo "FAIL: $*" >&2; exit 1; }

db_query() {  # <sql> → вывод в -t -A (для утверждений)
  "$PSQL_BIN" "${PSQL_OPTS[@]}" -t -A -d "$TEST_DB" -c "$1"
}

db_exec() {   # <sql> → обычное выполнение
  "$PSQL_BIN" "${PSQL_OPTS[@]}" -d "$TEST_DB" -c "$1"
}

check() {  # <sql> <ожидаемое> <описание>
  local sql="$1" expected="$2" desc="$3" got
  got="$(db_query "$sql")" || fail "$desc: запрос завершился ошибкой"
  if [ "$got" != "$expected" ]; then
    fail "$desc: ожидалось <<$expected>>, получено <<$got>>"
  fi
  echo "  ok: $desc"
}

expect_error() {  # <regexp> <sql> <описание>
  local pattern="$1" sql="$2" desc="$3" out
  if out="$(db_exec "$sql" 2>&1)"; then
    fail "$desc: запрос выполнился, но должен был упасть"
  fi
  if ! printf '%s' "$out" | grep -Eq "$pattern"; then
    fail "$desc: в выводе нет <<$pattern>>. Вывод: $out"
  fi
  echo "  ok: $desc"
}

# ---------- Свежая БД ----------------------------------------------------
echo "== КАРКАС · тест миграций =="
echo "psql: $PSQL_BIN"
echo "БД:   $TEST_DB"

"$PSQL_BIN" "${PSQL_OPTS[@]}" -d postgres -c "DROP DATABASE IF EXISTS $TEST_DB WITH (FORCE);" >/dev/null \
  || fail "DROP DATABASE $TEST_DB"
"$PSQL_BIN" "${PSQL_OPTS[@]}" -d postgres -c "CREATE DATABASE $TEST_DB;" >/dev/null \
  || fail "CREATE DATABASE $TEST_DB"

# ---------- Накат миграций ----------------------------------------------
echo "-- накат миграций"
for f in 001_init.sql 002_indexes_views.sql 003_seed_registry.sql; do
  [ -f "$SQL_DIR/$f" ] || fail "нет файла $SQL_DIR/$f"
  "$PSQL_BIN" "${PSQL_OPTS[@]}" -1 -d "$TEST_DB" -f "$SQL_DIR/$f" >/dev/null \
    || fail "миграция $f"
  echo "  ok: $f"
done
[ -f "$SQL_DIR/900_demo_sample248.sql" ] || fail "нет файла $SQL_DIR/900_demo_sample248.sql"
"$PSQL_BIN" "${PSQL_OPTS[@]}" -d "$TEST_DB" -f "$SQL_DIR/900_demo_sample248.sql" >/dev/null \
  || fail "демо-данные 900_demo_sample248.sql"
echo "  ok: 900_demo_sample248.sql"

DEMO="00000000-0000-0000-0000-0000000000b1"
A1="00000000-0000-0000-0000-0000000000a1"
A2="00000000-0000-0000-0000-0000000000a2"

# ---------- (a) часы по образцу 248 ч ------------------------------------
echo "-- (a) представления часов по образцу 248 ч"
check "SELECT count(*) FROM v_program_hours WHERE program_id = '$DEMO';" \
      "1" "v_program_hours: одна строка на программу"
check "SELECT format('%s|%s|%s|%s|%s|%s|%s|%s', grand_total, requested, lecture, practice, lab, self_study, control, final_att_hours)
       FROM v_program_hours WHERE program_id = '$DEMO';" \
      "248|248|0|66|6|168|6|2" \
      "v_program_hours: grand_total=248, requested=248, ПР=66, ЛБ=6, СРС=168, ТК=6, ЛК=0, ИА=2"
check "SELECT count(*) FROM v_module_hours WHERE program_id = '$DEMO';" \
      "1" "v_module_hours: один модуль"
check "SELECT format('%s|%s|%s|%s|%s|%s|%s', m.number, mh.total, mh.lecture, mh.practice, mh.lab, mh.self_study, mh.control)
       FROM v_module_hours mh JOIN module m ON m.id = mh.module_id
       WHERE mh.program_id = '$DEMO' ORDER BY m.number;" \
      "1|246|0|66|6|168|6" \
      "Q1: строка учебного плана M1 = 246 ч (0/66/6/168/6)"

# ---------- (b) check_program_hours пуст ---------------------------------
echo "-- (b) проверка часов V-HRS"
check "SELECT count(*) FROM check_program_hours('$DEMO');" \
      "0" "check_program_hours: нарушений нет"

# (b2) положительный контроль: функция действительно ловит нарушения
P4="00000000-0000-0000-0000-0000000000c4"
M4="00000000-0000-0000-0000-0000000000c5"
T4="00000000-0000-0000-0000-0000000000c6"
db_exec "INSERT INTO program (id, org_id, owner_id, title, kind, form, total_hours, final_att_hours, status, constraints)
         VALUES ('$P4','$A1','$A2','Тестовая стажировка (V-HRS-04)','dpp_pk','internship',10,0,'draft','{\"self_study_only\": true}'::jsonb);" >/dev/null \
  || fail "создание программы для V-HRS-04"
db_exec "INSERT INTO module (id, program_id, ref, number, title) VALUES ('$M4','$P4','M1',1,'Модуль теста V-HRS-04');" >/dev/null \
  || fail "модуль теста V-HRS-04"
db_exec "INSERT INTO topic (id, program_id, module_id, ref, number, title) VALUES ('$T4','$P4','$M4','T1.1',1,'Тема теста V-HRS-04');" >/dev/null \
  || fail "тема теста V-HRS-04"
db_exec "INSERT INTO topic_workload (topic_id, activity, mode, hours)
         VALUES ('$T4','lecture','in_person',4), ('$T4','self_study','distance',6);" >/dev/null \
  || fail "часы теста V-HRS-04"
check "SELECT string_agg(rule_code, ',' ORDER BY rule_code) FROM check_program_hours('$P4');" \
      "V-HRS-04" "V-HRS-04: у стажировки (self_study_only) найдены ЛК/ПР/ЛБ"

P5="00000000-0000-0000-0000-0000000000c7"
M5="00000000-0000-0000-0000-0000000000c8"
T5="00000000-0000-0000-0000-0000000000c9"
db_exec "INSERT INTO program (id, org_id, owner_id, title, kind, form, total_hours, final_att_hours, status, constraints)
         VALUES ('$P5','$A1','$A2','Тестовая программа (V-HRS-05)','dpp_pk','distance',10,0,'draft','{\"min_practice_share_pct\": 50}'::jsonb);" >/dev/null \
  || fail "создание программы для V-HRS-05"
db_exec "INSERT INTO module (id, program_id, ref, number, title) VALUES ('$M5','$P5','M1',1,'Модуль теста V-HRS-05');" >/dev/null \
  || fail "модуль теста V-HRS-05"
db_exec "INSERT INTO topic (id, program_id, module_id, ref, number, title) VALUES ('$T5','$P5','$M5','T1.1',1,'Тема теста V-HRS-05');" >/dev/null \
  || fail "тема теста V-HRS-05"
db_exec "INSERT INTO topic_workload (topic_id, activity, mode, hours)
         VALUES ('$T5','practice','in_person',2), ('$T5','self_study','distance',8);" >/dev/null \
  || fail "часы теста V-HRS-05"
check "SELECT string_agg(rule_code, ',' ORDER BY rule_code) FROM check_program_hours('$P5');" \
      "V-HRS-05" "V-HRS-05: практика 2 ч < 50% от 10 ч"

# ---------- (c) Q2: разрывы покрытия ------------------------------------
echo "-- (c) Q2: разрывы покрытия РО"
Q2_SQL="SELECT string_agg(ref || '|' || type::text || '|' || topics::text || '|' || assessments::text || '|' || problem, chr(10) ORDER BY ref)
        FROM (
          SELECT ref, type, topics, assessments,
                 CASE WHEN topics = 0 THEN 'нет темы' WHEN assessments < 2 THEN 'мало оценочных средств' END AS problem
          FROM v_outcome_coverage
          WHERE program_id = '$DEMO' AND (topics = 0 OR assessments < 2)
        ) q;"
EXPECTED_Q2=$'LO1.2|skill|1|1|мало оценочных средств\nLO1.3|experience|1|0|мало оценочных средств'
check "$Q2_SQL" "$EXPECTED_Q2" "Q2: ровно 2 строки — LO1.2 (topics=1, assessments=1) и LO1.3 (topics=1, assessments=0)"

# ---------- (d) Q4: граф влияния темы T1.3 -------------------------------
echo "-- (d) Q4: граф влияния T1.3 (UNION ALL из Д2 §11)"
Q4_SQL="SELECT format('%s|%s', count(*), string_agg(entity || ':' || ref, ',' ORDER BY entity, ref))
        FROM (
          SELECT 'assessment_item' AS entity, ai.ref FROM assessment_item ai JOIN topic t ON t.id = ai.topic_id
          WHERE t.program_id = '$DEMO' AND t.ref = 'T1.3'
          UNION ALL
          SELECT 'learning_outcome', lo.ref FROM topic_outcome tl JOIN topic t ON t.id = tl.topic_id
          JOIN learning_outcome lo ON lo.id = tl.outcome_id
          WHERE t.program_id = '$DEMO' AND t.ref = 'T1.3'
        ) q;"
check "$Q4_SQL" \
      "5|assessment_item:Q-001,assessment_item:Q-002,assessment_item:Q-003,learning_outcome:LO1.1,learning_outcome:LO1.2" \
      "Q4: ровно 5 строк — Q-001…Q-003, LO1.1, LO1.2"

# ---------- (e) триггеры -------------------------------------------------
echo "-- (e) триггеры: Human Gate, reopen, append-only"

# Тестовая программа c1: 72 ч, но часы намеренно не сходятся (30 + 2 ≠ 72)
C1="00000000-0000-0000-0000-0000000000c1"
C2="00000000-0000-0000-0000-0000000000c2"
C3="00000000-0000-0000-0000-0000000000c3"

db_exec "INSERT INTO program (id, org_id, owner_id, title, kind, form, total_hours, final_att_hours, status, constraints)
         VALUES ('$C1','$A1','$A2','Тестовая программа (проверка триггеров)','dpp_pk','distance',72,2,'draft','{}'::jsonb);" >/dev/null \
  || fail "создание тестовой программы"
db_exec "INSERT INTO module (id, program_id, ref, number, title)
         VALUES ('$C2','$C1','M1',1,'Модуль тестовой программы');" >/dev/null \
  || fail "создание модуля тестовой программы"
db_exec "INSERT INTO topic (id, program_id, module_id, ref, number, title)
         VALUES ('$C3','$C1','$C2','T1.1',1,'Тема тестовой программы');" >/dev/null \
  || fail "создание темы тестовой программы"
db_exec "INSERT INTO topic_workload (topic_id, activity, mode, hours)
         VALUES ('$C3','practice','in_person',30);" >/dev/null \
  || fail "часы тестовой программы (30 + 2 ≠ 72)"

expect_error "GATE_NOT_PASSED" \
  "UPDATE program SET status = 'kit_generating', approved_at = now() WHERE id = '$C1';" \
  "kit_generating до утверждения каркаса запрещён"

expect_error "HOURS_MISMATCH" \
  "UPDATE program SET status = 'framework_approved', approved_by = '$A2', approved_at = now() WHERE id = '$C1';" \
  "утверждение с несходящимися часами запрещено"

# Исправляем часы тестовой программы: 40 ПР + 30 СРС = 70; 70 + ИА 2 = 72
db_exec "UPDATE topic_workload SET hours = 40 WHERE topic_id = '$C3' AND activity = 'practice' AND mode = 'in_person';
         INSERT INTO topic_workload (topic_id, activity, mode, hours) VALUES ('$C3','self_study','distance',30);" >/dev/null \
  || fail "исправление часов тестовой программы"
check "SELECT count(*) FROM check_program_hours('$C1');" "0" "часы тестовой программы сходятся (72)"
check "SELECT format('%s|%s', grand_total, requested) FROM v_program_hours WHERE program_id = '$C1';" \
      "72|72" "v_program_hours тестовой программы: 72 = 72"

expect_error "APPROVER_REQUIRED" \
  "UPDATE program SET status = 'framework_approved', approved_at = now() WHERE id = '$C1';" \
  "framework_approved без approved_by запрещён"

db_exec "UPDATE program SET status = 'framework_approved', approved_by = '$A2', approved_at = now() WHERE id = '$C1';" >/dev/null \
  || fail "корректное утверждение тестовой программы"
check "SELECT status::text || '|' || (approved_at IS NOT NULL)::text || '|' || (approved_by IS NOT NULL)::text
       FROM program WHERE id = '$C1';" \
      "framework_approved|true|true" "корректное утверждение прошло"

db_exec "UPDATE program SET status = 'kit_generating' WHERE id = '$C1';" >/dev/null \
  || fail "kit_generating после утверждения"
check "SELECT status::text FROM program WHERE id = '$C1';" \
      "kit_generating" "kit_generating после утверждения разрешён"

db_exec "UPDATE program SET status = 'framework_approved' WHERE id = '$C1';" >/dev/null \
  || fail "возврат в framework_approved"
db_exec "UPDATE topic_workload SET hours = 41 WHERE topic_id = '$C3' AND activity = 'practice' AND mode = 'in_person';" >/dev/null \
  || fail "UPDATE topic_workload утверждённой программы (без флага солвера)"
check "SELECT status::text || '|' || (approved_at IS NULL)::text || '|' || (approved_by IS NULL)::text
       FROM program WHERE id = '$C1';" \
      "framework_review|true|true" "изменение часов вернуло программу в framework_review, approved_at=NULL"

# Флаг солвера (karkas.solver='on') отключает возврат на проверку
db_exec "UPDATE topic_workload SET hours = 40 WHERE topic_id = '$C3' AND activity = 'practice' AND mode = 'in_person';" >/dev/null \
  || fail "возврат часов к 40"
db_exec "UPDATE program SET status = 'framework_approved', approved_by = '$A2', approved_at = now() WHERE id = '$C1';" >/dev/null \
  || fail "повторное утверждение тестовой программы"
db_exec "SET karkas.solver = 'on';
         UPDATE topic_workload SET hours = 41 WHERE topic_id = '$C3' AND activity = 'practice' AND mode = 'in_person';" >/dev/null \
  || fail "UPDATE topic_workload в сессии солвера"
check "SELECT status::text FROM program WHERE id = '$C1';" \
      "framework_approved" "сессия солвера (karkas.solver=on) не будит reopen-триггер"

# Снимки версий append-only
db_exec "INSERT INTO program_version (program_id, version, reason, snapshot, snapshot_hash)
         VALUES ('$C1',1,'framework_approved','{}'::jsonb, digest('c1-v1','sha256'));" >/dev/null \
  || fail "INSERT в program_version"
expect_error "append-only" \
  "UPDATE program_version SET reason = 'edit' WHERE program_id = '$C1' AND version = 1;" \
  "program_version: UPDATE запрещён (append-only)"
expect_error "append-only" \
  "DELETE FROM program_version WHERE program_id = '$C1';" \
  "program_version: DELETE запрещён (append-only)"

# ---------- Секции llm_call и v_program_usage ---------------------------
echo "-- (f) секции llm_call и v_program_usage"
db_exec "INSERT INTO llm_call (created_at, org_id, program_id, skill, model, prompt_tokens, completion_tokens, latency_ms, cost_rub, cache_hit, ok)
         VALUES ('2026-10-05T10:00:00+00','$A1','$DEMO','S06','qwen3',1000,500,1200,1.2345,true,true),
                ('2027-01-15T10:00:00+00','$A1','$DEMO','S06','qwen3',200,100,900,0.5,false,true);" >/dev/null \
  || fail "INSERT в llm_call"
check "SELECT tableoid::regclass::text FROM llm_call WHERE created_at = '2026-10-05T10:00:00+00';" \
      "llm_call_2026_10" "llm_call: октябрь 2026 → секция llm_call_2026_10"
check "SELECT tableoid::regclass::text FROM llm_call WHERE created_at = '2027-01-15T10:00:00+00';" \
      "llm_call_default" "llm_call: вне объявленных месяцев → DEFAULT-секция"
check "SELECT format('%s|%s|%s|%s|%s', calls, prompt_tokens, completion_tokens, cost_rub, cache_hit_pct)
       FROM v_program_usage WHERE program_id = '$DEMO';" \
      "2|1200|600|1.7345|50.0" "v_program_usage: calls=2, токены 1200/600, стоимость 1.7345 ₽, кэш 50.0%"

# ---------- Итог ---------------------------------------------------------
echo "MIGRATIONS TEST OK"
exit 0
