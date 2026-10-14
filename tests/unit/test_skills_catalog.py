"""Каталог навыков S01–S23: файлы, метаданные, схемы, дымовые прогоны шагов.

Тесты не зависят от реализаций параллельных субагентов: доменные модули
(solve/calendar/run_validation) и экспортёры подменяются заглушками.
"""

from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from karkas.agent.skills import SKILLS, SKILL_DIRS, load_skill
from karkas.agent.skills._base import SKILLS_DIR, InMemoryCheckpointStore, SkillContext, SkillSpec
from karkas.agent.skills._base import render_prompt
from karkas.domain.hours import Plan
from karkas.domain.kit import Report
from karkas.settings import Settings
from tests.conftest import build_minimal_kit

#: Ожидаемые зависимости (зафиксированы заданием конвейера).
EXPECTED_DEPS: dict[str, tuple[str, ...]] = {
    "S01": (),
    "S02": ("S01",),
    "S03": ("S01", "S02"),
    "S04": ("S01",),
    "S05": ("S01",),
    "S06": ("S05",),
    "S07": ("S06",),
    "S08": ("S07",),
    "S09": ("S08",),
    "S10": ("S09", "S04"),
    "S11": ("S10",),
    "S12": ("S11",),
    "S13": ("S12",),
    "S14": ("S11",),
    "S15": ("S11",),
    "S16": ("S10",),
    "S17": ("S11",),
    "S18": ("S17",),
    "S19": ("S18", "S16", "S15", "S14", "S13"),
    "S20": ("S19",),
    "S21": ("S20",),
    "S22": ("S04",),
    "S23": ("S08",),
}

#: Ожидаемый класс модели (struct/bulk/none).
EXPECTED_MODEL_CLASS: dict[str, str] = {
    "S01": "struct",
    "S02": "struct",
    "S03": "bulk",
    "S04": "struct",
    "S05": "struct",
    "S06": "struct",
    "S07": "struct",
    "S08": "none",
    "S09": "none",
    "S10": "none",
    "S11": "bulk",
    "S12": "bulk",
    "S13": "bulk",
    "S14": "bulk",
    "S15": "bulk",
    "S16": "bulk",
    "S17": "bulk",
    "S18": "none",
    "S19": "none",
    "S20": "none",
    "S21": "bulk",
    "S22": "struct",
    "S23": "bulk",
}

REQUIRED_FILES = ("SKILL.md", "schema.json", "prompt.jinja", "run.py")


def skill_module(code: str):
    return importlib.import_module(f"karkas.agent.skills.{SKILL_DIRS[code]}.run")


class StubGateway:
    """LLM-шлюз-заглушка: отвечает заранее заданным payload и пишет вызовы."""

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload or {}
        self.calls: list[dict[str, Any]] = []

    async def complete_json(
        self,
        skill: str,
        model_class: str,
        messages: list[dict],
        schema: type[BaseModel],
        temperature: float | None = None,
    ) -> BaseModel:
        self.calls.append({"skill": skill, "model_class": model_class, "messages": messages})
        return schema.model_validate(self.payload)


def make_ctx(gateway: Any | None = None, **extra: Any) -> SkillContext:
    return SkillContext(
        gateway=gateway,
        settings=Settings(environment="test"),
        checkpoint=InMemoryCheckpointStore(),
        extra=dict(extra),
    )


# ---------------------------------------------------------------------------
# Структура каталога
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", sorted(EXPECTED_DEPS))
def test_skill_directory_has_four_files(code: str) -> None:
    directory = SKILLS_DIR / SKILL_DIRS[code]
    assert directory.is_dir(), f"{code}: каталог {directory} не найден"
    for name in REQUIRED_FILES:
        assert (directory / name).is_file(), f"{code}: нет файла {name}"


@pytest.mark.parametrize("code", sorted(EXPECTED_DEPS))
def test_skill_md_is_instruction(code: str) -> None:
    text = (SKILLS_DIR / SKILL_DIRS[code] / "SKILL.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert 15 <= len(lines) <= 40, f"{code}: SKILL.md {len(lines)} строк (нужно 15–40)"
    for heading in ("## Цель", "## Вход", "## Выход", "## Зависимости", "## Проверка после шага"):
        assert heading in text, f"{code}: в SKILL.md нет раздела «{heading}»"
    assert code in text


@pytest.mark.parametrize("code", sorted(EXPECTED_DEPS))
def test_schema_json_is_valid(code: str) -> None:
    raw = (SKILLS_DIR / SKILL_DIRS[code] / "schema.json").read_text(encoding="utf-8")
    document = json.loads(raw)
    assert isinstance(document, dict)
    assert "input" in document and "output" in document, f"{code}: schema.json без input/output"


@pytest.mark.parametrize("code", sorted(EXPECTED_DEPS))
def test_prompt_template_has_variables(code: str) -> None:
    text = (SKILLS_DIR / SKILL_DIRS[code] / "prompt.jinja").read_text(encoding="utf-8")
    assert "{{" in text, f"{code}: prompt.jinja без переменных"


@pytest.mark.parametrize("code", sorted(EXPECTED_DEPS))
def test_run_module_metadata(code: str) -> None:
    module = skill_module(code)
    spec = module.METADATA
    assert isinstance(spec, SkillSpec)
    assert spec.code == code
    assert spec.dir == SKILL_DIRS[code]
    assert spec.depends_on == EXPECTED_DEPS[code], f"{code}: неверные зависимости"
    assert spec.model_class == EXPECTED_MODEL_CLASS[code], f"{code}: неверный класс модели"
    assert callable(module.run)
    assert inspect.iscoroutinefunction(module.run), f"{code}: run() должен быть async"


@pytest.mark.parametrize("code", sorted(EXPECTED_DEPS))
def test_prompt_renders(code: str) -> None:
    # Рендер не должен падать на пустых переменных (шаблон остаётся валидным Jinja).
    assert isinstance(render_prompt(SKILL_DIRS[code]), str)


def test_llm_skill_prompt_variables_are_passed() -> None:
    """Статическая сверка: все переменные prompt.jinja LLM-навыка передаются из run()."""
    import ast

    from jinja2 import Environment, FileSystemLoader, meta

    env = Environment(loader=FileSystemLoader(str(SKILLS_DIR)))
    for code, spec in SKILLS.items():
        if not spec.is_llm:
            continue
        module = skill_module(code)
        tree = ast.parse(inspect.getsource(module))
        passed: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "complete_structured":
                passed.update(keyword.arg for keyword in node.keywords if keyword.arg)
        template_source = (SKILLS_DIR / spec.dir / "prompt.jinja").read_text(encoding="utf-8")
        required = meta.find_undeclared_variables(env.parse(template_source))
        missing = required - passed
        assert not missing, f"{code}: prompt.jinja ждёт {sorted(missing)}, run() передаёт {sorted(passed)}"


def test_catalog_contains_all_skills() -> None:
    assert set(SKILLS) == set(EXPECTED_DEPS)
    assert tuple(SKILLS) == tuple(sorted(EXPECTED_DEPS))
    for code, spec in SKILLS.items():
        assert spec.code == code
        assert spec.name.strip()


def test_load_skill() -> None:
    spec = load_skill("S08")
    assert spec.code == "S08" and spec.depends_on == ("S07",)
    with pytest.raises(KeyError) as excinfo:
        load_skill("S99")
    assert "S99" in str(excinfo.value)


def test_dependencies_exist_and_acyclic() -> None:
    assert all(dep in SKILLS for spec in SKILLS.values() for dep in spec.depends_on)
    visited: dict[str, int] = {}

    def visit(code: str) -> None:
        mark = visited.get(code, 0)
        assert mark != 1, f"цикл через {code}"
        if mark == 2:
            return
        visited[code] = 1
        for dep in SKILLS[code].depends_on:
            visit(dep)
        visited[code] = 2

    for code in SKILLS:
        visit(code)


# ---------------------------------------------------------------------------
# S02 — детерминированные правила и LLM-арбитр
# ---------------------------------------------------------------------------


async def test_s02_rules_decide_without_llm() -> None:
    module = skill_module("S02")
    gateway = StubGateway()
    result = await module.run(
        {"brief": "Курс повышения квалификации для учителей информатики"},
        make_ctx(gateway),
    )
    assert result["kind"] == "dpp_pk"
    assert result["source"] == "rules"
    assert result["confidence"] >= 0.8
    assert gateway.calls == []


async def test_s02_school_intensive_is_dop_by_rules() -> None:
    module = skill_module("S02")
    gateway = StubGateway()
    result = await module.run({"brief": "Интенсив для школьников 12–15 лет, кружок"}, make_ctx(gateway))
    assert result["kind"] == "dop"
    assert result["source"] == "rules"
    assert gateway.calls == []


async def test_s02_conflict_uses_llm_arbiter() -> None:
    module = skill_module("S02")
    gateway = StubGateway({"kind": "dop", "confidence": 0.7, "rationale": "аудитория — школьники"})
    result = await module.run(
        {"brief": "Повышение квалификации для школьников летнего лагеря"},
        make_ctx(gateway),
    )
    assert result["source"] == "llm"
    assert result["kind"] == "dop"
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["model_class"] == "struct"


async def test_s02_attached_template_wins() -> None:
    module = skill_module("S02")
    gateway = StubGateway()
    result = await module.run(
        {"brief": "Непонятный запрос", "attached_templates": ["templates/dop.yaml"]},
        make_ctx(gateway),
    )
    assert result["kind"] == "dop"
    assert result["source"] == "rules"
    assert result["confidence"] >= 0.95
    assert gateway.calls == []


async def test_s02_singular_teacher_sign_is_dpp() -> None:
    module = skill_module("S02")
    result = await module.run({"brief": "Курс для учитель информатики"}, make_ctx(StubGateway()))
    assert result["kind"] == "dpp_pk"
    assert result["source"] == "rules"


async def test_s02_no_signs_returns_question() -> None:
    module = skill_module("S02")
    gateway = StubGateway()
    result = await module.run({"brief": "Хотим что-нибудь про данные"}, make_ctx(gateway))
    assert result["source"] == "question"
    assert result["kind"] is None
    assert result["question"]
    assert gateway.calls == []


# ---------------------------------------------------------------------------
# S06 — постпроверка З/У/Н и кодов ТФ
# ---------------------------------------------------------------------------


async def test_s06_filters_incomplete_competencies_and_foreign_lf() -> None:
    module = skill_module("S06")
    gateway = StubGateway(
        {
            "competencies": [
                {
                    "ref": "C1",
                    "title": "Полная компетенция",
                    "labor_function_codes": ["A/01.1", "ЧУЖОЙ/99"],
                    "outcomes": [
                        {"ref": "LO1.1", "type": "knowledge", "text": "Знает основы"},
                        {"ref": "LO1.2", "type": "skill", "text": "Умеет применять"},
                        {"ref": "LO1.3", "type": "experience", "text": "Владеет инструментом"},
                    ],
                },
                {
                    "ref": "C2",
                    "title": "Неполная компетенция",
                    "outcomes": [{"ref": "LO2.1", "type": "skill", "text": "Умеет"}],
                },
            ],
            "gaps": [],
        }
    )
    result = await module.run(
        {"S05": {"labor_functions": [{"code": "A/01.1"}]}, "kind": "dpp_pk"},
        make_ctx(gateway),
    )
    assert [item["ref"] for item in result["competencies"]] == ["C1"]
    assert result["competencies"][0]["labor_function_codes"] == ["A/01.1"]
    assert any("V-COV-03" in gap for gap in result["gaps"])
    assert any("V-SRC-03" in gap for gap in result["gaps"])


async def test_s06_dop_has_no_labor_functions() -> None:
    module = skill_module("S06")
    gateway = StubGateway(
        {
            "competencies": [
                {
                    "ref": "C1",
                    "title": "Компетенция ДОП",
                    "labor_function_codes": ["A/01.1"],
                    "outcomes": [
                        {"ref": "LO1.1", "type": "knowledge", "text": "Знает"},
                        {"ref": "LO1.2", "type": "skill", "text": "Умеет"},
                        {"ref": "LO1.3", "type": "experience", "text": "Владеет"},
                    ],
                }
            ]
        }
    )
    result = await module.run({"kind": "dop"}, make_ctx(gateway))
    assert result["competencies"][0]["labor_function_codes"] == []


# ---------------------------------------------------------------------------
# S14 — постпроверка вопросов (ключ и РО обязательны)
# ---------------------------------------------------------------------------


async def test_s14_drops_questions_without_key_or_outcomes() -> None:
    module = skill_module("S14")
    gateway = StubGateway(
        {
            "questions": [
                {
                    "ref": "Q-001",
                    "stem": "Верный вопрос?",
                    "qtype": "single",
                    "options": [{"id": "a", "text": "Да"}, {"id": "b", "text": "Нет"}],
                    "answer_key": {"correct": ["a"], "explanation": "так верно"},
                    "outcome_refs": ["LO1.1"],
                },
                {
                    "ref": "Q-002",
                    "stem": "Без ключа",
                    "qtype": "single",
                    "options": [{"id": "a", "text": "Да"}, {"id": "b", "text": "Нет"}],
                    "outcome_refs": ["LO1.1"],
                },
                {
                    "ref": "Q-003",
                    "stem": "Без привязки к РО",
                    "qtype": "truefalse",
                    "options": [{"id": "a", "text": "Верно"}, {"id": "b", "text": "Неверно"}],
                    "answer_key": {"correct": ["a"]},
                    "outcome_refs": [],
                },
            ]
        }
    )
    result = await module.run(
        {"outcomes": [{"ref": "LO1.1"}], "topics": [{"ref": "T1.1"}]},
        make_ctx(gateway),
    )
    assert [item["ref"] for item in result["questions"]] == ["Q-001"]
    assert len(result["dropped"]) == 2


# ---------------------------------------------------------------------------
# S08 — smoke-прогон солвера (домен подменён заглушкой)
# ---------------------------------------------------------------------------


async def test_s08_hours_solver_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    module = skill_module("S08")
    fake_plan = Plan(
        rows={"T1.1": {"lecture": 5, "practice": 9}},
        distance={},
        module_of={"T1.1": "M1"},
        proof=[("V-HRS-01 Σ строк + ИА = объём", True, "14 + 2 = 16")],
    )
    captured: dict[str, Any] = {}

    def fake_solve(modules, constraints):
        captured["modules"] = modules
        captured["constraints"] = constraints
        return fake_plan

    monkeypatch.setattr(module, "solve", fake_solve)
    inputs = {
        "modules": [
            {"ref": "M1", "weight": 1.0, "topics": [{"ref": "T1.1", "weight": 1.0, "practicality": 0.8, "has_lab": False}]}
        ],
        "constraints": {"total": 16, "final_att": 2, "unit": 1},
    }
    result = await module.run(inputs, make_ctx())

    assert result["rows"] == {"T1.1": {"lecture": 5, "practice": 9}}
    assert result["module_of"] == {"T1.1": "M1"}
    assert result["proof"] == [{"rule": "V-HRS-01 Σ строк + ИА = объём", "ok": True, "message": "14 + 2 = 16"}]
    assert result["distance"] == {}
    assert result["constraints"]["total"] == 16
    assert captured["constraints"].total == 16
    assert captured["modules"][0].ref == "M1"
    assert captured["modules"][0].topics[0].practicality == pytest.approx(0.8)


async def test_s08_uses_rebalance_with_locked_cells(monkeypatch: pytest.MonkeyPatch) -> None:
    module = skill_module("S08")
    calls: list[str] = []

    def fake_solve(modules, constraints):
        calls.append("solve")
        return Plan(rows={"T1.1": {"lecture": 2}}, module_of={"T1.1": "M1"})

    def fake_rebalance(modules, constraints, locked_cells):
        calls.append("rebalance")
        assert locked_cells == {"T1.1": {"practice": 4}}
        return Plan(rows={"T1.1": {"practice": 4}}, module_of={"T1.1": "M1"})

    monkeypatch.setattr(module, "solve", fake_solve)
    monkeypatch.setattr(module, "rebalance", fake_rebalance)
    result = await module.run(
        {
            "modules": [{"ref": "M1", "weight": 1.0, "topics": [{"ref": "T1.1", "weight": 1.0}]}],
            "constraints": {"total": 16},
            "locked_cells": {"T1.1": {"practice": 4}},
        },
        make_ctx(),
    )
    assert calls == ["rebalance"]
    assert result["rows"] == {"T1.1": {"practice": 4}}


# ---------------------------------------------------------------------------
# S09 — smoke-прогон календаря (домен подменён заглушкой)
# ---------------------------------------------------------------------------


async def test_s09_calendar_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    module = skill_module("S09")

    def fake_calendar(plan, constraints, max_per_day, days_per_week):
        assert max_per_day == 4
        assert days_per_week == 5
        return [(1, 1, "T1.1", 2), (1, 2, "T1.1", 2), (1, 3, "ИА", 2)]

    monkeypatch.setattr(module, "calendar", fake_calendar)
    result = await module.run(
        {
            "rows": {"T1.1": {"lecture": 2, "practice": 2}},
            "module_of": {"T1.1": "M1"},
            "distance": {"T1.1": 2},
            "constraints": {"total": 6, "final_att": 2},
            "max_hours_per_day": 4,
            "days_per_week": 5,
        },
        make_ctx(),
    )
    assert result["weeks"] == 1
    assert result["days"] == 3
    assert result["sessions"][0]["topic_ref"] == "T1.1"
    assert result["sessions"][0]["mode"] == "distance"
    assert result["sessions"][0]["activity"] == "lecture"
    assert result["sessions"][-1]["topic_ref"] is None
    assert result["sessions"][-1]["activity"] == "final_attestation"
    assert sum(session["hours"] for session in result["sessions"]) == 6


# ---------------------------------------------------------------------------
# S10 — smoke-прогон валидаторов (домен подменён заглушкой)
# ---------------------------------------------------------------------------


async def test_s10_framework_validation_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    module = skill_module("S10")

    def fake_validation(context):
        assert context.kit.program.total_hours == 16
        return Report(passed=True, duration_ms=7, summary={"hours": {"ok": True, "checked": 3}})

    monkeypatch.setattr(module, "run_validation", fake_validation)
    result = await module.run(
        {"kit": build_minimal_kit().model_dump(mode="json"), "today": "2026-10-13"},
        make_ctx(),
    )
    assert result["passed"] is True
    assert result["error_count"] == 0
    assert result["report"]["summary"]["hours"]["ok"] is True


# ---------------------------------------------------------------------------
# S18 — ISBN и статусы источников
# ---------------------------------------------------------------------------


async def test_s18_isbn_check_digits() -> None:
    module = skill_module("S18")
    assert module.isbn13_valid("978-5-4461-1234-0")
    assert module.isbn_valid("9785446112340")
    assert not module.isbn_valid("978-5-4461-1234-1")
    assert module.isbn10_valid("0306406152")
    assert not module.isbn10_valid("0306406153")
    assert not module.isbn_valid("abc")


async def test_s18_verifies_sources_and_summary() -> None:
    module = skill_module("S18")
    sources = [
        {"ref": "SRC-01", "section": "normative", "citation": "Приказ № 499", "normative_act_ref": "Минобрнауки 499"},
        {"ref": "SRC-02", "section": "normative", "citation": "Старый приказ", "normative_act_ref": "Минобрнауки 100"},
        {"ref": "SRC-03", "section": "main", "citation": "Книга", "isbn": "978-5-4461-1234-0"},
        {"ref": "SRC-04", "section": "main", "citation": "Книга с опечаткой", "isbn": "978-5-4461-1234-1"},
        {"ref": "SRC-05", "section": "internet", "citation": "Документация", "url": "https://example.org"},
        {"ref": "SRC-06", "section": "software", "citation": "Python 3.13", "url": None},
        {"ref": "SRC-07", "section": "additional", "citation": "Книга без ISBN", "isbn": None},
    ]
    registries = {
        "normative_acts": [
            {"issuer": "Минобрнауки", "number": "499", "valid_from": "2013-09-01"},
            {"issuer": "Минобрнауки", "number": "100", "valid_to": "2020-01-01", "replaced_by_number": "499"},
        ],
        "services": [{"name": "Python", "available_ru": True, "lifecycle": "current"}],
    }
    result = await module.run(
        {"S17": {"sources": sources}, "registries": registries, "today": "2026-10-13"},
        make_ctx(),
    )
    statuses = {source["ref"]: source["status"] for source in result["sources"]}
    assert statuses["SRC-01"] == "verified"
    assert statuses["SRC-02"] == "outdated"
    assert statuses["SRC-03"] == "unverified"
    assert statuses["SRC-04"] == "not_found"
    assert statuses["SRC-05"] == "unverified"
    assert statuses["SRC-06"] == "verified"
    assert statuses["SRC-07"] == "unverified"
    assert result["summary"] == {"verified": 2, "unverified": 3, "not_found": 1, "outdated": 1}
    assert set(result["unconfirmed"]) == {"SRC-02", "SRC-03", "SRC-04", "SRC-05", "SRC-07"}
    assert result["sources"][4]["evidence"]["http_checked"] is False


# ---------------------------------------------------------------------------
# S20 — smoke-прогон экспорта (экспортёры подменены заглушками)
# ---------------------------------------------------------------------------


async def test_s20_export_returns_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    module = skill_module("S20")
    from karkas.infra import exporters

    def fake_docx(kit):
        return b"docx-bytes"

    def fake_gift(kit):
        return "$CATEGORY: $course$/M1"

    def fake_json(kit):
        return '{"schema_version": "kit.v1"}'

    def fake_pptx(kit, module_refs=None):
        return f"pptx:{module_refs}".encode()

    monkeypatch.setattr(
        exporters,
        "ARTIFACT_KINDS",
        {"docx": fake_docx, "pptx": fake_pptx, "gift": fake_gift, "json": fake_json},
    )
    result = await module.run(
        {
            "kit": build_minimal_kit().model_dump(mode="json"),
            "formats": ["docx", "pptx", "gift", "json"],
            "module_refs": ["M1"],
        },
        make_ctx(),
    )
    assert result["docx"] == b"docx-bytes"
    assert result["gift"].startswith("$CATEGORY")
    assert json.loads(result["json"])["schema_version"] == "kit.v1"
    assert result["pptx"] == b"pptx:['M1']"


async def test_s20_fallback_to_export_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если ARTIFACT_KINDS недоступен, используются замороженные имена export_*."""
    module = skill_module("S20")
    from karkas.infra import exporters

    monkeypatch.setattr(exporters, "ARTIFACT_KINDS", None, raising=False)
    monkeypatch.setattr(module, "export_gift", lambda kit: "fallback-gift")
    result = await module.run(
        {"kit": build_minimal_kit().model_dump(mode="json"), "formats": ["gift"]},
        make_ctx(),
    )
    assert result == {"gift": "fallback-gift"}


async def test_s20_rejects_unknown_format() -> None:
    module = skill_module("S20")
    with pytest.raises(ValueError):
        await module.run(
            {"kit": build_minimal_kit().model_dump(mode="json"), "formats": ["pdf"]},
            make_ctx(),
        )


async def test_s20_uses_artifact_kinds_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    module = skill_module("S20")
    from karkas.infra import exporters

    monkeypatch.setattr(exporters, "ARTIFACT_KINDS", {"gift": lambda kit: "gift-from-registry"}, raising=False)
    result = await module.run(
        {"kit": build_minimal_kit().model_dump(mode="json"), "formats": ["gift"]},
        make_ctx(),
    )
    assert result == {"gift": "gift-from-registry"}


# ---------------------------------------------------------------------------
# Сквозной прогон: каталог + раннер + заглушки домена (S01 → S10)
# ---------------------------------------------------------------------------

FRAMEWORK_STUB_PAYLOADS: dict[str, dict[str, Any]] = {
    "S01": {
        "profile": {"audience": "учителя", "notes": "повышение квалификации"},
        "template_signs": ["повышение квалификации"],
        "missing_slots": [],
    },
    "S04": {
        "sections": [{"title": "1.1 Аннотация", "order": 1}],
        "sample_errors": [],
        "findings": ["образец на 24 ч"],
    },
    "S05": {
        "prof_standard": {"code": "01.001", "title": "Педагог"},
        "labor_functions": [{"code": "A/01.1", "title": "Обучение"}],
        "confidence": 0.9,
    },
    "S06": {
        "competencies": [
            {
                "ref": "C1",
                "title": "Преподавание",
                "labor_function_codes": ["A/01.1"],
                "outcomes": [
                    {"ref": "LO1.1", "type": "knowledge", "text": "Знает"},
                    {"ref": "LO1.2", "type": "skill", "text": "Умеет"},
                    {"ref": "LO1.3", "type": "experience", "text": "Владеет"},
                ],
            }
        ]
    },
    "S07": {
        "modules": [
            {
                "ref": "M1",
                "title": "Основы",
                "weight": 1.0,
                "att_form": "зачёт",
                "topics": [
                    {
                        "ref": "T1.1",
                        "title": "Введение",
                        "outcome_refs": ["LO1.1"],
                        "complexity": 1,
                        "practicality": 0.6,
                        "weight": 1.0,
                        "has_lab": False,
                    }
                ],
            }
        ]
    },
}


class ScriptedGateway:
    """Шлюз-заглушка сквозного прогона: отвечает по коду навыка и пишет порядок вызовов."""

    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self.payloads = payloads
        self.calls: list[str] = []

    async def complete_json(
        self,
        skill: str,
        model_class: str,
        messages: list[dict],
        schema: type[BaseModel],
        temperature: float | None = None,
    ) -> BaseModel:
        self.calls.append(skill)
        assert messages and messages[-1]["content"].strip(), f"{skill}: пустой промпт"
        return schema.model_validate(self.payloads[skill])


async def test_framework_chain_end_to_end_with_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сквозной прогон S01→S10: каталог, раннер, зависимости, прогресс, ключи входа."""
    from karkas.agent.skill_runner import SkillRunner
    from karkas.agent.skills import SKILLS

    stub_s08 = skill_module("S08")
    stub_s09 = skill_module("S09")
    stub_s10 = skill_module("S10")
    monkeypatch.setattr(
        stub_s08,
        "solve",
        lambda modules, constraints: Plan(
            rows={"T1.1": {"lecture": 6, "practice": 8}},
            module_of={"T1.1": "M1"},
            proof=[("V-HRS-01", True, "ok")],
        ),
    )
    monkeypatch.setattr(
        stub_s09,
        "calendar",
        lambda plan, constraints, max_per_day, days_per_week=5: [
            (1, 1, "T1.1", 4),
            (1, 2, "T1.1", 4),
            (1, 3, "ИА", 2),
        ],
    )
    monkeypatch.setattr(
        stub_s10,
        "run_validation",
        lambda context: Report(passed=True, duration_ms=1, summary={"hours": {"ok": True}}),
    )

    gateway = ScriptedGateway(FRAMEWORK_STUB_PAYLOADS)
    events: list[tuple[str, int, int]] = []
    settings = Settings(environment="test")
    runner = SkillRunner(SKILLS.values(), settings=settings)
    ctx = SkillContext(
        gateway=gateway,
        settings=settings,
        checkpoint=InMemoryCheckpointStore(),
        extra={"kit": build_minimal_kit()},
    )
    result = await runner.run(
        "S10",
        {
            "brief": "Повышение квалификации учителей, 16 часов",
            "kind": "dpp_pk",
            "candidates": [
                {
                    "code": "01.001",
                    "title": "Педагог",
                    "status": "active",
                    "labor_functions": [{"code": "A/01.1", "title": "Обучение"}],
                }
            ],
            "references": [{"name": "sample.docx", "text": "1.1 Аннотация ..."}],
            "constraints": {"total": 16, "final_att": 2},
        },
        ctx,
        on_progress=lambda code, done, total, label: events.append((code, done, total)),
    )

    assert result.output["passed"] is True
    assert result.output["report"]["summary"]["hours"]["ok"] is True
    assert gateway.calls == ["S01", "S04", "S05", "S06", "S07"]
    assert events[-1] == ("S10", 8, 8)  # S01,S04,S05,S06,S07,S08,S09,S10
    assert [code for code, _, _ in events if code == "S10"] == ["S10", "S10"]


# ---------------------------------------------------------------------------
# Прочее: путь до SKILL-файлов каталога
# ---------------------------------------------------------------------------


def test_skills_dir_points_to_catalog() -> None:
    assert SKILLS_DIR.name == "skills"
    assert (SKILLS_DIR / SKILL_DIRS["S01"] / "SKILL.md").is_file()
    assert Path(SKILLS_DIR, "S23_adapt", "run.py").is_file()
