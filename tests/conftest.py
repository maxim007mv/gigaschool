"""Общие фикстуры pytest (проект КАРКАС).

Тяжёлые интеграционные фикстуры (PostgreSQL, S3) помечены маркером integration
и включаются только при наличии окружения.
"""

from __future__ import annotations

import os

import pytest

from karkas.domain.kit import (
    Competency,
    Content,
    FinalAttestation,
    Framework,
    KitV1,
    Module,
    Outcome,
    ProgramHeader,
    Topic,
    Workload,
)


def build_minimal_kit(total_hours: int = 16, final_att_hours: int = 2) -> KitV1:
    """Минимальный согласованный каркас: 1 компетенция, 1 модуль, 1 тема (14 + 2 = 16)."""
    topic = Topic(
        ref="T1.1",
        title="Введение",
        workload=Workload(lecture=5, practice=9),
        outcome_refs=["LO1.1"],
    )
    module = Module(ref="M1", number=1, title="Основы", topics=[topic])
    header = ProgramHeader(
        kind="dop",
        title="Тестовая программа",
        form="full_time",
        total_hours=total_hours,
        final_attestation=FinalAttestation(form="защита проекта", hours=final_att_hours),
    )
    framework = Framework(
        goal="Цель",
        competencies=[
            Competency(
                ref="C1",
                title="Компетенция",
                outcomes=[Outcome(ref="LO1.1", type="skill", text="Умеет применять основы")],
            )
        ],
        modules=[module],
        final_attestation=FinalAttestation(form="защита проекта", hours=final_att_hours),
    )
    return KitV1(program=header, framework=framework, content=Content())


@pytest.fixture()
def minimal_kit() -> KitV1:
    return build_minimal_kit()


def postgres_available() -> bool:
    return bool(os.environ.get("KARKAS_TEST_DATABASE_URL"))
