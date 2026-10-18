"""Сквозной прогон ТК через POST /api/v1/agent/run (живой LLM + API)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from karkas.domain.kit import KitV1
from karkas.eval.checklists import format_report, run_checklist
from karkas.eval.defense_metrics import MANUAL_BASELINE_HOURS_DEFAULT, estimate_gigachat3_pro_cost
from karkas.eval.official_cases import OFFICIAL_CASES, OfficialCase


@dataclass
class LiveRunReport:
    case_id: str
    started_at: str
    finished_at: str
    status: str
    program_id: str | None = None
    run_id: str | None = None
    timings_s: dict[str, float] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    cost_rub: str | None = None
    checklist_passed: int = 0
    checklist_total: int = 0
    checklist_failed: list[str] = field(default_factory=list)
    detail: str | None = None
    kit_path: str | None = None

    def to_markdown(self) -> str:
        lines = [
            f"# Live eval — {self.case_id}",
            "",
            f"- **Статус:** {self.status}",
            f"- **Начало:** {self.started_at}",
            f"- **Конец:** {self.finished_at}",
        ]
        if self.program_id:
            lines.append(f"- **program_id:** `{self.program_id}`")
        if self.timings_s:
            lines.append(f"- **Время (с):** {json.dumps(self.timings_s, ensure_ascii=False)}")
        if self.usage:
            lines.append(f"- **Токены / usage:** {json.dumps(self.usage, ensure_ascii=False)}")
        if self.cost_rub:
            lines.append(f"- **Оценка ₽ (GigaChat-3-Pro):** {self.cost_rub}")
        lines.append(f"- **Чек-лист:** {self.checklist_passed}/{self.checklist_total}")
        if self.checklist_failed:
            lines.append("- **Провалы:** " + ", ".join(self.checklist_failed))
        if self.detail:
            lines.append(f"- **Детали:** {self.detail}")
        if self.kit_path:
            lines.append(f"- **Kit JSON:** `{self.kit_path}`")
        return "\n".join(lines) + "\n"


def _api_key() -> str:
    key = os.environ.get("KARKAS_EVAL_API_KEY") or os.environ.get("AGENT_RUN_API_KEY") or ""
    if not key:
        raise RuntimeError(
            "Задайте KARKAS_EVAL_API_KEY (X-Api-Key с ролью service) для --live прогона"
        )
    return key


def _match_tk4_answers(questions: list[dict[str, Any]]) -> dict[str, str | None]:
    """Ответы методиста из открытого ТК-4 (таблица уточнений)."""
    table = {
        "тип": "Повышение квалификации",
        "программ": "Повышение квалификации",
        "объём": "72 часа",
        "объем": "72 часа",
        "слушател": "Студенты 3 курса специальности «Информационные системы и программирование»",
        "форм": "Очная, занятия на базе колледжа",
        "аттестац": "Экзамен с практическим заданием на стенде",
    }
    answers: dict[str, str | None] = {}
    for index, q in enumerate(questions, start=1):
        text = (q.get("text") or q.get("question") or "").lower()
        value = None
        for key, ans in table.items():
            if key in text:
                value = ans
                break
        slot = str(q.get("slot") or "").strip()
        if slot:
            answers[slot] = value or "на ваше усмотрение"
        else:
            answers[f"q{index}"] = value or "на ваше усмотрение"
    return answers


def run_live_case(
    case_id: str,
    *,
    base_url: str = "http://127.0.0.1:8000",
    timeout_s: float = 1200.0,
    out_dir: Path | None = None,
) -> LiveRunReport:
    case = OFFICIAL_CASES.get(case_id.lower())
    if case is None:
        raise ValueError(f"Неизвестный кейс {case_id}")

    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    headers = {"X-Api-Key": _api_key(), "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "request": case.request_text,
        "mode": "full",
        "wait": True,
        "auto_approve": True,
        "formats": ["docx", "json"],
    }

    with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout_s) as client:
        resp = client.post("/api/v1/agent/run", headers=headers, json=payload)
        if resp.status_code >= 400:
            finished = datetime.now(timezone.utc)
            return LiveRunReport(
                case_id=case.case_id,
                started_at=started.isoformat(),
                finished_at=finished.isoformat(),
                status="http_error",
                detail=f"{resp.status_code}: {resp.text[:500]}",
            )
        data = resp.json()
        run_id = data.get("run_id")
        status = data.get("status", "unknown")

        rounds = 0
        while status == "needs_input" and run_id and rounds < 6:
            rounds += 1
            questions = data.get("questions") or []
            if case.case_id == "tk4":
                answers = _match_tk4_answers(questions)
            else:
                answers = {f"q{i + 1}": "на ваше усмотрение" for i in range(len(questions))}
            cont = {
                "run_id": run_id,
                "answers": answers,
                "wait": True,
                "auto_approve": True,
            }
            resp = client.post("/api/v1/agent/run", headers=headers, json=cont)
            if resp.status_code >= 400:
                break
            data = resp.json()
            status = data.get("status", "unknown")

    finished = datetime.now(timezone.utc)
    timings = {k: float(v) for k, v in (data.get("timings") or {}).items()}
    timings.setdefault("wall_s", round(time.monotonic() - t0, 1))
    usage = data.get("usage") or {}
    tokens = int(usage.get("tokens") or 0)
    cost_rub = usage.get("cost_rub")
    if cost_rub is None and tokens:
        # грубая оценка 50/50 in/out если провайдер не вернул разбивку
        half = tokens // 2
        est = estimate_gigachat3_pro_cost(half, tokens - half)
        cost_rub = str(est.cost_rub)

    report = LiveRunReport(
        case_id=case.case_id,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        status=status,
        program_id=data.get("program_id"),
        run_id=run_id,
        timings_s=timings,
        usage=usage,
        cost_rub=str(cost_rub) if cost_rub is not None else None,
        detail=data.get("detail"),
    )

    kit_raw = data.get("kit")
    if kit_raw and status == "completed":
        kit = KitV1.model_validate(kit_raw)
        results = run_checklist(kit, case.case_id)
        report.checklist_total = len(results)
        report.checklist_passed = sum(1 for r in results if r.passed)
        report.checklist_failed = [f"{r.item_id}: {r.detail}" for r in results if not r.passed]
        if out_dir:
            out_dir.mkdir(parents=True, exist_ok=True)
            kit_path = out_dir / f"{case.case_id}_live_kit.json"
            kit_path.write_text(json.dumps(kit.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            report.kit_path = str(kit_path)
            md_path = out_dir / f"{case.case_id}_live_report.md"
            md_body = report.to_markdown() + "\n```\n" + format_report(results) + "\n```\n"
            md_path.write_text(md_body, encoding="utf-8")
            json_path = out_dir / f"{case.case_id}_live_report.json"
            json_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return report
