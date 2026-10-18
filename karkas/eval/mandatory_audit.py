"""Сверка с таблицей приоритетов кейса (раздел 5): пункты «Обязательно».

Не заменяет прогон агента на ТК-1…ТК-5 — фиксирует наличие подсистем в коде.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class MandatoryItem:
    id: str
    title: str
    evidence: str  # путь или модуль


MANDATORY: tuple[MandatoryItem, ...] = (
    MandatoryItem(
        "M-01",
        "Оба шаблона АЦР, объём 16–500 ч",
        "karkas/domain/templates/dpp_pk.yaml;karkas/domain/templates/dop.yaml;karkas/domain/hours.py",
    ),
    MandatoryItem(
        "M-02",
        "Запрос и референсы .docx/.pdf/текст, уточняющие вопросы",
        "karkas/api/routers/files.py;karkas/api/routers/clarify.py;karkas/agent/skills/S03_clarifying_questions",
    ),
    MandatoryItem(
        "M-03",
        "Карта компетенций ↔ ЗУН, темы, вопросы, задания",
        "web/src/features/coverage/CoverageMatrix.tsx;karkas/domain/validators/coverage.py",
    ),
    MandatoryItem(
        "M-04",
        "УП/УТП и автопроверка сумм часов",
        "karkas/domain/hours.py;karkas/domain/validators/hours.py;web/src/features/hours",
    ),
    MandatoryItem(
        "M-05",
        "Тесты с ключами и привязкой к РО",
        "karkas/agent/skills/S14_test_questions;karkas/domain/kit.py",
    ),
    MandatoryItem(
        "M-06",
        "Задания семинаров с критериями",
        "karkas/agent/skills/S15_seminar_tasks",
    ),
    MandatoryItem(
        "M-07",
        "Планы лекций и слайды .pptx",
        "karkas/agent/skills/S12_lecture_plans;karkas/agent/skills/S13_slides;karkas/infra/exporters/pptx_slides.py",
    ),
    MandatoryItem(
        "M-08",
        "Выгрузка .docx по шаблону АЦР",
        "karkas/infra/exporters/docx_program.py",
    ),
    MandatoryItem(
        "M-09",
        "Единый API для автопрогонов, только Cloud.ru FM",
        "karkas/api/routers/agent.py;karkas/agent/llm_gateway.py",
    ),
    MandatoryItem(
        "M-10",
        "Метрика защиты: экономия часов методиста и стоимость в токенах",
        "karkas/api/routers/usage.py;web/src/pages/KitPage.tsx",
    ),
)


def audit_mandatory(root: Path = ROOT) -> list[tuple[MandatoryItem, bool, str]]:
    rows: list[tuple[MandatoryItem, bool, str]] = []
    for item in MANDATORY:
        paths = [root / p.strip() for p in item.evidence.split(";")]
        missing = [str(p.relative_to(root)) for p in paths if not p.exists()]
        ok = not missing
        detail = "ok" if ok else "нет: " + ", ".join(missing)
        rows.append((item, ok, detail))
    return rows


def format_mandatory_report(rows: list[tuple[MandatoryItem, bool, str]]) -> str:
    passed = sum(1 for _, ok, _ in rows if ok)
    lines = [f"Обязательные пункты кейса: {passed}/{len(rows)}"]
    for item, ok, detail in rows:
        mark = "OK" if ok else "GAP"
        lines.append(f"  [{mark}] {item.id} {item.title} — {detail}")
    return "\n".join(lines)
