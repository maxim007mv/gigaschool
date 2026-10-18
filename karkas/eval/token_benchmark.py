"""Бенчмарк токенов по шагам S01–S19 (фикстурный запрос, без живого LLM)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from jinja2 import meta

from karkas.agent.skills import SKILLS, SKILL_DIRS
from karkas.agent.skills._base import (
    SKILLS_DIR,
    _jinja_env,
    make_messages,
    render_prompt,
    to_json,
)
from karkas.domain.framework_skeleton import SkeletonSpec, build_skeleton_modules
from karkas.eval.defense_metrics import estimate_gigachat3_pro_cost
from karkas.eval.token_estimate import estimate_messages_tokens, estimate_tokens

PIPELINE_SKILLS: tuple[str, ...] = tuple(f"S{i:02d}" for i in range(1, 20))

FAKE_BRIEF = (
    "Программа «Основы анализа данных на Python» для слушателей с базовым IT-бэкграундом. "
    "Форма: очная. Нужны практические занятия и итоговая аттестация."
)

# Типичные размеры ответа модели (JSON) для оценки completion-токенов.
_COMPLETION_STUB: dict[str, str] = {
    "S01": '{"profile":{"audience":"ИТ-специалисты","entry_level":"базовый"},"goal":"…","missing_slots":[]}',
    "S02": '{"kind":"dop","confidence":0.9,"rationale":"…"}',
    "S03": '{"questions":[],"assumptions":[]}',
    "S04": '{"sections":[],"sample_errors":[],"topic_candidates":[],"findings":[],"notes":""}',
    "S05": '{"prof_standard":null,"labor_functions":[],"confidence":1.0,"note":""}',
    "S06": '{"competencies":[{"ref":"C1","title":"…","outcomes":[{"ref":"LO1.1","type":"skill","text":"…"}]}],"gaps":[]}',
    "S07": '{"modules":[{"ref":"M1","number":1,"title":"…","topics":[{"ref":"T1.1","title":"…","outcome_refs":["LO1.1"]}]}],"gaps":[]}',
    "S11": '{"module_programs":[{"body":{"annotation":"…","topics":[{"topic_ref":"T1.1","summary":"…"}]}}],"notes":""}',
    "S12": '{"lecture_plans":[{"ref":"LP-T1.1","body":{"goals":["…"],"stages":[{"stage":"…","minutes":10}]}}]}',
    "S13": '{"slides":[{"title":"…","bullets":["…"],"notes":"…","layout":"title_and_content"}],"notes":""}',
    "S14": '{"questions":[{"ref":"Q-1","stem":"…","options":[{"id":"a","text":"…"}],"answer_key":{"correct":["a"]}}]}',
    "S15": '{"tasks":[{"ref":"P-1","stem":"…","outcome_refs":["LO1.1"]}]}',
    "S16": '{"items":[{"ref":"FA-1","kind":"final_project","stem":"…","rubric":[{"criterion":"…","max_points":10}]}],"requirements":[],"notes":""}',
    "S17": '{"sources":[{"section":"main","citation":"Учебник …"}],"notes":""}',
}


@dataclass(frozen=True, slots=True)
class ProgramScale:
    """Масштаб синтетической программы для бенчмарка."""

    total_hours: int
    module_count: int
    topic_count: int
    modules: list[dict[str, Any]]
    topics: list[dict[str, Any]]
    outcomes: list[dict[str, Any]]


@dataclass
class SkillTokenRow:
    code: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    llm: bool

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class PipelineTokenReport:
    total_hours: int
    rows: list[SkillTokenRow] = field(default_factory=list)
    prompt_compact: bool = True

    @property
    def prompt_tokens(self) -> int:
        return sum(row.prompt_tokens for row in self.rows)

    @property
    def completion_tokens(self) -> int:
        return sum(row.completion_tokens for row in self.rows)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost_rub(self):
        return estimate_gigachat3_pro_cost(self.prompt_tokens, self.completion_tokens).cost_rub


def build_program_scale(total_hours: int, *, kind: str = "dop") -> ProgramScale:
    """Синтетический каркас по объёму (как eval skeleton, без солвера)."""
    spec = SkeletonSpec(total=total_hours, kind=kind)  # type: ignore[arg-type]
    modules_in = build_skeleton_modules(spec)
    modules: list[dict[str, Any]] = []
    topics: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    for mi, mod in enumerate(modules_in, start=1):
        topic_dicts = []
        for ti, topic in enumerate(mod.topics, start=1):
            ref = f"T{mi}.{ti}"
            topic_dicts.append(
                {
                    "ref": ref,
                    "title": f"Тема {ref}",
                    "outcome_refs": [f"LO{mi}.{ti}"],
                    "complexity": 2,
                    "practicality": 0.6,
                    "weight": 1.0,
                    "has_lab": topic.has_lab,
                }
            )
            topics.append(topic_dicts[-1])
            outcomes.append({"ref": f"LO{mi}.{ti}", "type": "skill", "text": f"Умеет по теме {ref}"})
        modules.append(
            {
                "ref": mod.ref,
                "number": mi,
                "title": f"Модуль {mi}",
                "weight": mod.weight,
                "att_form": "зачёт",
                "topics": topic_dicts,
            }
        )
    return ProgramScale(
        total_hours=total_hours,
        module_count=len(modules),
        topic_count=len(topics),
        modules=modules,
        topics=topics,
        outcomes=outcomes,
    )


def _prompt_variables(skill_dir: str) -> set[str]:
    env = _jinja_env()
    source, _, _ = env.loader.get_source(env, f"{skill_dir}/prompt.jinja")
    ast = env.parse(source)
    return meta.find_undeclared_variables(ast)


def _variable_bundle(scale: ProgramScale) -> dict[str, Any]:
    profile = {"audience": "ИТ-специалисты", "entry_level": "базовый", "constraints": {}}
    module = scale.modules[0] if scale.modules else {}
    topic = scale.topics[0] if scale.topics else {}
    return {
        "brief": FAKE_BRIEF,
        "files_text": "",
        "answers_json": to_json({}),
        "profile_json": to_json(profile),
        "profile": profile,
        "kind": "dop",
        "total_hours": scale.total_hours,
        "rule_signals": to_json(["аудитория взрослые"]),
        "missing_slots_json": to_json([]),
        "max_questions": 5,
        "references_text": "Раздел 1. Аннотация. Раздел 2. Учебный план.",
        "labor_functions_json": to_json([]),
        "knowledge": "",
        "competencies_json": to_json(
            [{"ref": "C1", "title": "Компетенция", "outcomes": scale.outcomes[:3]}]
        ),
        "candidates_json": to_json([]),
        "references_json": to_json([]),
        "instruction": "",
        "missing_outcomes": "",
        "previous_json": "",
        "module_json": to_json(module),
        "outcomes_json": to_json(scale.outcomes),
        "topic_json": to_json(topic),
        "topics_json": to_json(scale.topics[:3]),
        "lecture_plan_json": to_json({"body": {"stages": [{"stage": "Введение", "minutes": 10}]}}),
        "module_program_json": to_json({"body": {"topics": [{"topic_ref": topic.get("ref"), "summary": "…"}]}}),
        "count": 3,
        "form": "защита проекта",
        "allowed_normative_json": to_json([]),
        "affected_json": to_json([]),
    }


def _render_skill_prompt(code: str, scale: ProgramScale, *, compact: bool) -> str | None:
    spec = SKILLS.get(code)
    if spec is None or not spec.is_llm:
        return None
    skill_dir = SKILL_DIRS[code]
    variables = _variable_bundle(scale)
    needed = _prompt_variables(skill_dir)
    render_vars = {key: variables[key] for key in needed if key in variables}
    missing = needed - render_vars.keys()
    if missing:
        raise KeyError(f"{code}: нет фикстур для переменных промпта {sorted(missing)}")
    if not compact:
        for key, value in list(render_vars.items()):
            if key.endswith("_json") and isinstance(value, str):
                try:
                    render_vars[key] = to_json(json.loads(value), indent=2)
                except json.JSONDecodeError:
                    pass
    return render_prompt(skill_dir, **render_vars)


def _call_counts(code: str, scale: ProgramScale, *, all_slides: bool) -> int:
    if code in ("S01", "S02", "S03", "S04", "S05", "S06", "S07"):
        return 1 if code != "S04" else 0
    if code == "S11":
        return scale.module_count
    if code in ("S12", "S14", "S15"):
        return scale.topic_count
    if code == "S13":
        return scale.topic_count if all_slides else min(1, scale.topic_count)
    if code in ("S16", "S17"):
        return 1
    return 0


def measure_pipeline_tokens(
    total_hours: int,
    *,
    compact: bool = True,
    all_slides: bool = True,
) -> PipelineTokenReport:
    """Оценить prompt/completion токены по шагам для фикстурного запроса."""
    scale = build_program_scale(total_hours)
    report = PipelineTokenReport(total_hours=total_hours, prompt_compact=compact)
    for code in PIPELINE_SKILLS:
        spec = SKILLS[code]
        calls = _call_counts(code, scale, all_slides=all_slides)
        if not spec.is_llm or calls == 0:
            report.rows.append(SkillTokenRow(code, calls, 0, 0, llm=spec.is_llm))
            continue
        prompt_text = _render_skill_prompt(code, scale, compact=compact)
        if not prompt_text:
            report.rows.append(SkillTokenRow(code, calls, 0, 0, llm=True))
            continue
        prompt_per_call = estimate_messages_tokens(make_messages(prompt_text))
        completion_per_call = estimate_tokens(_COMPLETION_STUB.get(code, "{}"))
        report.rows.append(
            SkillTokenRow(
                code,
                calls,
                prompt_per_call * calls,
                completion_per_call * calls,
                llm=True,
            )
        )
    return report


def compare_compact_savings(total_hours: int) -> dict[str, Any]:
    """Сравнение compact vs pretty JSON в промптах (до/после политики compact)."""
    after = measure_pipeline_tokens(total_hours, compact=True)
    before = measure_pipeline_tokens(total_hours, compact=False)
    return {
        "total_hours": total_hours,
        "before": {
            "prompt_tokens": before.prompt_tokens,
            "completion_tokens": before.completion_tokens,
            "total_tokens": before.total_tokens,
            "cost_rub": str(before.cost_rub),
        },
        "after": {
            "prompt_tokens": after.prompt_tokens,
            "completion_tokens": after.completion_tokens,
            "total_tokens": after.total_tokens,
            "cost_rub": str(after.cost_rub),
        },
        "prompt_tokens_saved": before.prompt_tokens - after.prompt_tokens,
    }


def markdown_table(reports: list[PipelineTokenReport]) -> str:
    """Таблица для README / отчёта защиты."""
    lines = [
        "| Объём | Prompt | Completion | Всего | ₽ (GigaChat-3-Pro) |",
        "|------:|-------:|-----------:|------:|-------------------:|",
    ]
    for report in reports:
        lines.append(
            f"| {report.total_hours} ч | {report.prompt_tokens:,} | "
            f"{report.completion_tokens:,} | {report.total_tokens:,} | {report.cost_rub} |"
        )
    return "\n".join(lines)


def per_skill_table(report: PipelineTokenReport) -> str:
    lines = [
        f"### Детализация S01–S19 ({report.total_hours} ч)",
        "",
        "| Шаг | Вызовов | Prompt | Completion | Всего |",
        "|-----|--------:|-------:|-----------:|------:|",
    ]
    for row in report.rows:
        if not row.llm and row.calls == 0:
            continue
        lines.append(
            f"| {row.code} | {row.calls} | {row.prompt_tokens:,} | "
            f"{row.completion_tokens:,} | {row.total_tokens:,} |"
        )
    return "\n".join(lines)
