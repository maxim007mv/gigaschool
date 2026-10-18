"""Замеры времени конвейера на FakeGateway (без сети и БД)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from karkas.agent.skill_runner import SkillRunner
from karkas.agent.skills import SKILLS
from karkas.agent.skills._base import InMemoryCheckpointStore, SkillContext
from karkas.domain.framework_skeleton import SkeletonSpec, build_skeleton_modules, skeleton_constraints
from karkas.domain.hours import solve
from karkas.eval.fake_llm import FakeGateway
from karkas.eval.token_benchmark import build_program_scale


@dataclass(frozen=True, slots=True)
class TimingRow:
    label: str
    seconds: float


@dataclass
class TimingReport:
    rows: list[TimingRow]

    def as_dict(self) -> dict[str, float]:
        return {row.label: round(row.seconds, 3) for row in self.rows}


def _s07_from_scale(scale) -> dict[str, Any]:
    return {"modules": scale.modules, "gaps": []}


async def _run_framework_fake(scale, gateway: FakeGateway) -> float:
    runner = SkillRunner(skills=SKILLS.values(), concurrency=2)
    ctx = SkillContext(gateway=gateway, checkpoint=InMemoryCheckpointStore(), extra={"checkpoint_prefix": "bench:fw:"})
    inputs: dict[str, Any] = {
        "brief": "Бенчмарк каркаса",
        "files_text": "",
        "answers_json": "{}",
        "profile": {"audience": "ИТ", "entry_level": "базовый"},
        "constraints": {"total": scale.total_hours, "final_att": 2, "unit": 1},
        "kind": "dop",
        "total_hours": scale.total_hours,
        "candidates": [],
    }
    gateway.responses["S07"] = _s07_from_scale(scale)
    started = time.perf_counter()
    await runner.run("S09", inputs, ctx)
    return time.perf_counter() - started


async def _seed_skill(ctx: SkillContext, code: str, payload: dict[str, Any]) -> None:
    prefix = str(ctx.extra.get("checkpoint_prefix") or "")
    await ctx.checkpoint.save(f"{prefix}{code}", payload)


async def _run_kit_fake(scale, gateway: FakeGateway) -> float:
    runner = SkillRunner(skills=SKILLS.values(), concurrency=2)
    prefix = "bench:kit:"
    ctx = SkillContext(gateway=gateway, checkpoint=InMemoryCheckpointStore(), extra={"checkpoint_prefix": prefix})
    await _seed_skill(ctx, "S10", {"passed": True, "report": {}})
    profile = {"audience": "ИТ", "entry_level": "базовый"}
    outcomes = scale.outcomes
    gateway.responses.setdefault(
        "S11",
        {
            "module_programs": [
                {
                    "body": {
                        "annotation": "Модуль",
                        "topics": [{"topic_ref": "T1.1", "summary": "Тема", "work_forms": [], "materials": []}],
                    }
                }
            ],
            "notes": "",
        },
    )
    gateway.responses.setdefault(
        "S16",
        {
            "items": [
                {
                    "ref": "FA-1",
                    "kind": "final_project",
                    "stem": "Проект",
                    "rubric": [{"criterion": "OK", "max_points": 10, "levels": ["зачтено"]}],
                    "outcome_refs": ["LO1.1"],
                }
            ],
            "requirements": [],
            "notes": "",
            "dropped": [],
        },
    )
    gateway.responses.setdefault(
        "S17",
        {"sources": [{"section": "main", "citation": "Учебник"}], "notes": ""},
    )
    started = time.perf_counter()
    for module in scale.modules:
        ctx.extra["checkpoint_prefix"] = f"{prefix}{module['ref']}:"
        await _seed_skill(ctx, "S10", {"passed": True, "report": {}})
        gateway.responses["S11"] = {
            "module_programs": [
                {
                    "body": {
                        "annotation": f"Модуль {module['ref']}",
                        "att_form": "зачёт",
                        "topics": [
                            {
                                "topic_ref": str(topic.get("ref")),
                                "summary": f"Содержание {topic.get('ref')}",
                                "work_forms": ["практика"],
                                "materials": ["слайды"],
                            }
                            for topic in module.get("topics") or []
                            if isinstance(topic, dict)
                        ],
                    }
                }
            ],
            "notes": "",
        }
        s11 = (
            await runner.run(
                "S11",
                {"module": module, "outcomes": outcomes, "profile": profile},
                ctx,
            )
        ).output
        for topic in module.get("topics") or []:
            common = {
                "topic": topic,
                "topics": [topic],
                "outcomes": outcomes,
                "profile": profile,
                "module_ref": module["ref"],
            }
            await runner.run("S12", {**common, "module_program_json": s11.get("module_programs", [{}])[0]}, ctx)
            await runner.run("S13", common, ctx)
            await runner.run("S14", {**common, "count": 3}, ctx)
            await runner.run("S15", common, ctx)
    await runner.run(
        "S16",
        {"outcomes": outcomes, "profile": profile, "form": "защита", "kind": "dop"},
        ctx,
    )
    s17 = (await runner.run("S17", {"topics": scale.topics, "allowed_normative": []}, ctx)).output
    await runner.run("S18", {"S17": s17, "sources": s17.get("sources") or []}, ctx)
    return time.perf_counter() - started


def time_hours_solver(total_hours: int) -> float:
    spec = SkeletonSpec(total=total_hours, kind="dop")
    modules = build_skeleton_modules(spec)
    constraints = skeleton_constraints(spec)
    started = time.perf_counter()
    for _ in range(50):
        solve(modules, constraints)
    elapsed = time.perf_counter() - started
    return elapsed / 50.0


async def measure_timings(total_hours: int) -> TimingReport:
    scale = build_program_scale(total_hours)
    gateway = FakeGateway()
    kit_gateway = FakeGateway()
    fw_s = await _run_framework_fake(scale, gateway)
    kit_s = await _run_kit_fake(scale, kit_gateway)
    return TimingReport(
        rows=[
            TimingRow(f"solver_{total_hours}h_avg", time_hours_solver(total_hours)),
            TimingRow(f"framework_fake_{total_hours}h", fw_s),
            TimingRow(f"kit_fake_{total_hours}h", kit_s),
            TimingRow(f"llm_calls_framework_{total_hours}h", float(len(gateway.calls))),
            TimingRow(f"llm_calls_kit_{total_hours}h", float(len(kit_gateway.calls))),
        ]
    )


async def measure_both() -> dict[str, Any]:
    reports = {}
    for hours in (16, 72):
        report = await measure_timings(hours)
        reports[str(hours)] = report.as_dict()
    return reports
