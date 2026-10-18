"""TK-3 / TK-5: детерминированный подбор ПС и прохождение V-TPL-01 на каркасе."""

from __future__ import annotations

from karkas.domain.kit import (
    Competency,
    Content,
    FinalAttestation,
    Framework,
    KitV1,
    LaborFunctionRef,
    Module,
    Outcome,
    ProfStandardRef,
    ProgramHeader,
    ProgramProfile,
    Topic,
    Workload,
)
from karkas.domain.prof_standard_pick import pick_prof_standard
from karkas.domain.validators import ValidationContext, run_validation
from karkas.eval.official_cases import OFFICIAL_CASES

_REGISTRY_CANDIDATES = [
    {
        "code": "06.026",
        "title": "Системный администратор информационно-коммуникационных систем",
        "status": "active",
        "labor_functions": [
            {"code": "B/01.5", "title": "Выполнение работ по выявлению и устранению инцидентов в информационно-коммуникационных системах", "otf_code": "B"},
            {"code": "C/03.6", "title": "Мониторинг событий, возникающих в процессе работы инфокоммуникационной системы", "otf_code": "C"},
        ],
    },
    {
        "code": "06.042",
        "title": "Специалист по большим данным",
        "status": "active",
        "labor_functions": [
            {"code": "A/03.6", "title": "Подготовка данных для проведения аналитических работ по исследованию больших данных", "otf_code": "A"},
        ],
    },
    {
        "code": "06.001",
        "title": "Программист",
        "status": "active",
        "labor_functions": [
            {"code": "A/02.3", "title": "Написание программного кода с использованием языков программирования, определения и манипулирования данными в базах данных", "otf_code": "A"},
        ],
    },
    {
        "code": "06.022",
        "title": "Системный аналитик",
        "status": "active",
        "labor_functions": [
            {"code": "A/01.4", "title": "Сбор исходных данных для проектирования Системы", "otf_code": "A"},
        ],
    },
]


def _mock_s05_s06(case_id: str) -> tuple[dict, list]:
    case = OFFICIAL_CASES[case_id]
    profile = {"audience": "слушатели", "entry_level": "базовый"}
    picked = pick_prof_standard(profile, _REGISTRY_CANDIDATES, brief=case.request_text)
    assert picked is not None, case_id
    assert picked["prof_standard"] and picked["prof_standard"]["code"]
    s05 = picked
    competencies = [
        {
            "ref": "C1",
            "title": "Профессиональная компетенция по тематике программы",
            "activity_kind": "профессиональная",
            "labor_function_codes": [lf["code"] for lf in s05["labor_functions"]],
            "outcomes": [
                {"ref": "LO1.1", "type": "knowledge", "text": "Знает основы предметной области"},
                {"ref": "LO1.2", "type": "skill", "text": "Применяет инструменты по темам программы"},
                {"ref": "LO1.3", "type": "experience", "text": "Выполняет практические задания в учебной среде"},
            ],
        }
    ]
    return s05, competencies


def _minimal_kit(case_id: str, s05: dict, competencies_raw: list) -> KitV1:
    ps = s05["prof_standard"]
    lf_refs = [
        LaborFunctionRef(code=lf["code"], title=lf.get("title", ""), otf_code=lf.get("otf_code"))
        for lf in s05["labor_functions"]
    ]
    comp = Competency(
        ref="C1",
        title=competencies_raw[0]["title"],
        prof_standard=ProfStandardRef(code=ps["code"], title=ps.get("title", "")),
        labor_functions=lf_refs,
        outcomes=[
            Outcome(ref="LO1.1", type="knowledge", text="Знает основы предметной области"),
            Outcome(ref="LO1.2", type="skill", text="Применяет инструменты по темам программы"),
            Outcome(ref="LO1.3", type="experience", text="Выполняет практические задания"),
        ],
    )
    return KitV1(
        program=ProgramHeader(
            kind="dpp_pk",
            title="Тест",
            form="part_time",
            total_hours=72,
            final_attestation=FinalAttestation(form="экзамен", hours=2),
            document="удостоверение о повышении квалификации",
        ),
        profile=ProgramProfile(audience="слушатели", entry_level="базовый"),
        framework=Framework(
            goal="Цель программы",
            tasks=["Сформировать компетенцию"],
            competencies=[comp],
            modules=[
                Module(
                    ref="M1",
                    number=1,
                    title="Модуль 1",
                    topics=[
                        Topic(
                            ref="T1.1",
                            title="Тема",
                            workload=Workload(lecture=4, practice=4, lab=0, self_study=8, current_control=0),
                            outcome_refs=["LO1.1"],
                        )
                    ],
                )
            ],
            final_attestation=FinalAttestation(form="экзамен", hours=2),
            gaps=[s05.get("gap") or s05.get("note") or ""],
        ),
        content=Content(),
    )


def test_tk3_pick_prof_standard_and_framework_tpl01() -> None:
    s05, _ = _mock_s05_s06("tk3")
    code = s05["prof_standard"]["code"]
    assert code in ("06.001", "06.042", "06.022")
    kit = _minimal_kit("tk3", s05, _)
    assert any(c.prof_standard for c in kit.framework.competencies)
    report = run_validation(ValidationContext(kit=kit, stage="framework"))
    tpl01 = [
        i
        for i in report.issues
        if i.rule_code == "V-TPL-01" and (i.entity_ref or "").startswith("1.5")
    ]
    assert not tpl01


def test_tk5_pick_prof_standard_and_framework_tpl01() -> None:
    s05, _ = _mock_s05_s06("tk5")
    assert s05["prof_standard"]["code"] == "06.026"
    kit = _minimal_kit("tk5", s05, _)
    assert kit.framework.competencies[0].prof_standard is not None
    report = run_validation(ValidationContext(kit=kit, stage="framework"))
    tpl01 = [
        i
        for i in report.issues
        if i.rule_code == "V-TPL-01" and (i.entity_ref or "").startswith("1.5")
    ]
    assert not tpl01
