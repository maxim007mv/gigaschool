"""Тесты правил группы «Источники» и «Ограничения» (V-SRC-01..04, V-SVC-01, V-ACT-01).

Для каждого правила — минимум один кейс «нарушение → issue» и «норма → нет issue».
Проверки кодов из реестров идут только при переданных registries; без них
правило обязано не падать, а попасть в summary["skipped"].
"""

from __future__ import annotations

from datetime import date
from typing import Any

from karkas.domain.kit import (
    Competency,
    Content,
    FinalAttestation,
    Framework,
    KitV1,
    LaborFunctionRef,
    LegalBasis,
    Outcome,
    ProfStandardRef,
    ProgramConstraints,
    ProgramHeader,
    ProgramProfile,
    Source,
    Workload,
    Module,
    Topic,
)
from karkas.domain.validators import (
    LaborFunction,
    NormativeAct,
    ProfStandard,
    RegistryBundle,
    ServiceRecord,
    ValidationContext,
    run_validation,
)

TODAY = date(2026, 10, 13)


def registries() -> RegistryBundle:
    return RegistryBundle(
        normative_acts=[
            NormativeAct(
                issuer="Российская Федерация",
                number="273-ФЗ",
                signed_on=date(2012, 12, 29),
                kind="federal_law",
                title="Об образовании в Российской Федерации",
            ),
            NormativeAct(issuer="Минобрнауки России", number="499", signed_on=date(2013, 7, 1),
                         valid_to=date(2025, 8, 31), replaced_by_number="266"),
            NormativeAct(issuer="Минобрнауки России", number="266", signed_on=date(2025, 3, 24),
                         valid_from=date(2025, 9, 1), valid_to=date(2031, 9, 1),
                         title="Порядок организации и осуществления образовательной деятельности по ДПП"),
            NormativeAct(issuer="Минпросвещения России", number="629", signed_on=date(2022, 7, 27)),
        ],
        prof_standards=[
            ProfStandard(code="06.015", title="Специалист по информационным системам", status="active"),
            ProfStandard(code="01.001", title="Устаревший стандарт", status="replaced"),
        ],
        labor_functions=[
            LaborFunction(prof_standard_code="06.015", code="C/14.6", title="Разработка архитектуры ИС"),
        ],
        services=[
            ServiceRecord(name="GitHub", available_ru=False, lifecycle="current"),
            ServiceRecord(name="pandas", available_ru=True, lifecycle="current", latest_version="2.2"),
            ServiceRecord(name="Moodle", available_ru=True, lifecycle="deprecated", latest_version="4.3"),
            ServiceRecord(name="СервисБезСтатуса", available_ru=None, lifecycle="current"),
        ],
    )


def build_kit(
    *,
    kind: str = "dpp_pk",
    sources: list[Source] | None = None,
    legal_basis: list[LegalBasis] | None = None,
    competencies: list[Competency] | None = None,
) -> KitV1:
    if competencies is None:
        competencies = [
            Competency(
                ref="C1",
                title="Разработка ИС",
                prof_standard=ProfStandardRef(code="06.015", title="Специалист по информационным системам"),
                labor_functions=[LaborFunctionRef(code="C/14.6", title="Разработка архитектуры ИС")],
                outcomes=[Outcome(ref="LO1.1", type="knowledge", text="Знает методы проектирования")],
            )
        ]
    header = ProgramHeader(
        kind=kind,
        title="Анализ данных на Python",
        form="part_time",
        total_hours=16,
        final_attestation=FinalAttestation(form="зачёт", hours=2),
        document="удостоверение о повышении квалификации" if kind == "dpp_pk" else "",
        legal_basis=legal_basis or [],
    )
    framework = Framework(
        goal="Освоить инструменты",
        competencies=competencies,
        modules=[
            Module(
                ref="M1",
                number=1,
                title="Основы",
                topics=[
                    Topic(
                        ref="T1.1",
                        title="Введение",
                        workload=Workload(lecture=5, practice=9),
                        outcome_refs=["LO1.1"],
                    )
                ],
            )
        ],
        final_attestation=FinalAttestation(form="зачёт", hours=2),
    )
    return KitV1(
        program=header,
        profile=ProgramProfile(entry_level="базовый", constraints=ProgramConstraints()),
        framework=framework,
        content=Content(sources=sources or []),
    )


def issues_of(kit: KitV1, code: str, regs: RegistryBundle | None = None, **ctx_kwargs: Any) -> list:
    bundle = regs if regs is not None else registries()
    ctx = ValidationContext(kit=kit, registries=bundle, today=TODAY, **ctx_kwargs)
    return [i for i in run_validation(ctx).issues if i.rule_code == code]


# ---------------------------------------------------------------------------
# V-SRC-01: НПА в реестре и действует на дату программы
# ---------------------------------------------------------------------------


def source_normative(citation: str) -> Source:
    return Source(ref="SRC-01", section="normative", citation=citation)


def test_src_01_valid_act_ok():
    kit = build_kit(sources=[source_normative("Приказ Минобрнауки России от 24.03.2025 № 266")])
    assert issues_of(kit, "V-SRC-01") == []


def test_src_01_repealed_act_is_error():
    kit = build_kit(sources=[source_normative("Приказ Минобрнауки России от 01.07.2013 № 499")])
    issues = issues_of(kit, "V-SRC-01")
    assert len(issues) == 1 and issues[0].severity == "error"
    assert "499" in issues[0].message and "266" in issues[0].message


def test_src_01_unknown_act_is_error():
    kit = build_kit(sources=[source_normative("Приказ Минобрнауки России от 01.01.2001 № 999")])
    issues = issues_of(kit, "V-SRC-01")
    assert len(issues) == 1 and "не найден" in issues[0].message


def test_src_01_legal_basis_repealed_is_error():
    kit = build_kit(
        legal_basis=[LegalBasis(ref="LB-01", act="Приказ Минобрнауки России от 01.07.2013 № 499")],
    )
    issues = issues_of(kit, "V-SRC-01")
    assert any(i.entity_ref == "LB-01" for i in issues)


def test_src_01_skipped_without_registry():
    kit = build_kit(sources=[source_normative("Приказ Минобрнауки России от 01.07.2013 № 499")])
    report = run_validation(ValidationContext(kit=kit, registries=None, today=TODAY))
    assert report.issues == [] or all(i.rule_code != "V-SRC-01" for i in report.issues)
    assert "V-SRC-01" in report.summary["skipped"]


# ---------------------------------------------------------------------------
# V-SRC-02/03: коды профстандартов и ТФ существуют в реестре и связаны
# ---------------------------------------------------------------------------


def test_src_02_unknown_prof_standard_is_error():
    competencies = [build_kit().framework.competencies[0]]
    competencies[0].prof_standard = ProfStandardRef(code="99.999")
    kit = build_kit(competencies=competencies)
    issues = issues_of(kit, "V-SRC-02")
    assert len(issues) == 1 and issues[0].severity == "error"
    assert "99.999" in issues[0].message


def test_src_02_replaced_prof_standard_is_error():
    competencies = [build_kit().framework.competencies[0]]
    competencies[0].prof_standard = ProfStandardRef(code="01.001")
    kit = build_kit(competencies=competencies)
    issues = issues_of(kit, "V-SRC-02")
    assert len(issues) == 1 and "replaced" in issues[0].message


def test_src_02_dpp_without_prof_standard_is_error():
    competency = Competency(
        ref="C1",
        title="Без ПС",
        outcomes=[Outcome(ref="LO1.1", type="skill", text="Умеет")],
    )
    kit = build_kit(competencies=[competency])
    issues = issues_of(kit, "V-SRC-02")
    assert len(issues) == 1 and "хотя бы один профстандарт" in issues[0].message


def test_src_02_ok_with_active_standard():
    assert issues_of(build_kit(), "V-SRC-02") == []


def test_src_02_skipped_without_registry():
    kit = build_kit()
    report = run_validation(ValidationContext(kit=kit, registries=None, today=TODAY))
    assert "V-SRC-02" in report.summary["skipped"]
    assert "V-SRC-03" in report.summary["skipped"]


def test_src_02_not_applied_to_dop():
    competency = Competency(
        ref="C1",
        title="ДОП",
        prof_standard=ProfStandardRef(code="06.015"),
        outcomes=[Outcome(ref="LO1.1", type="skill", text="Умеет")],
    )
    kit = build_kit(kind="dop", competencies=[competency])
    assert issues_of(kit, "V-SRC-02") == []


def test_src_03_unknown_labor_function_is_error():
    competencies = [build_kit().framework.competencies[0]]
    competencies[0].labor_functions = [LaborFunctionRef(code="C/99.9")]
    kit = build_kit(competencies=competencies)
    issues = issues_of(kit, "V-SRC-03")
    assert len(issues) == 1 and "C/99.9" in issues[0].message


def test_src_03_ok():
    assert issues_of(build_kit(), "V-SRC-03") == []


# ---------------------------------------------------------------------------
# V-SRC-04: литература подтверждена или явно помечена
# ---------------------------------------------------------------------------


def literature(status: str, evidence: dict | None = None) -> Source:
    return Source(
        ref="SRC-02",
        section="main",
        citation="Иванов И.И. Основы программирования. — М.: Наука, 2024",
        isbn="978-5-00000-000-0",
        status=status,
        evidence=evidence or {},
    )


def test_src_04_verified_with_evidence_ok():
    kit = build_kit(sources=[literature("verified", {"isbn_checked": True})])
    assert issues_of(kit, "V-SRC-04") == []


def test_src_04_verified_without_evidence_is_error():
    kit = build_kit(sources=[literature("verified")])
    issues = issues_of(kit, "V-SRC-04")
    assert len(issues) == 1 and issues[0].severity == "error"


def test_src_04_unverified_is_warning():
    kit = build_kit(sources=[literature("unverified")])
    issues = issues_of(kit, "V-SRC-04")
    assert len(issues) == 1 and issues[0].severity == "warning"
    assert "не подтверждено" in issues[0].message


def test_src_04_not_found_is_error():
    kit = build_kit(sources=[literature("not_found")])
    issues = issues_of(kit, "V-SRC-04")
    assert len(issues) == 1 and issues[0].severity == "error"


def test_src_04_outdated_is_warning():
    kit = build_kit(sources=[literature("outdated")])
    issues = issues_of(kit, "V-SRC-04")
    assert len(issues) == 1 and issues[0].severity == "warning"


def test_src_04_skipped_without_sources():
    report = run_validation(ValidationContext(kit=build_kit(), registries=registries(), today=TODAY))
    assert "V-SRC-04" in report.summary["skipped"]


# ---------------------------------------------------------------------------
# V-SVC-01 и V-ACT-01: сервисы каталога
# ---------------------------------------------------------------------------


def software(citation: str) -> Source:
    return Source(ref="SRC-03", section="software", citation=citation)


def test_svc_01_unavailable_service_is_error():
    kit = build_kit(sources=[software("GitHub Actions для CI/CD")])
    issues = issues_of(kit, "V-SVC-01")
    assert len(issues) == 1 and issues[0].severity == "error"
    assert "GitHub" in issues[0].message


def test_svc_01_available_service_ok():
    kit = build_kit(sources=[software("pandas 2.2 для таблиц")])
    assert issues_of(kit, "V-SVC-01") == []


def test_svc_01_unknown_mention_is_warning():
    kit = build_kit(sources=[software("НекийСервис для рисования")])
    issues = issues_of(kit, "V-SVC-01")
    assert len(issues) == 1 and issues[0].severity == "warning"


def test_svc_01_unknown_availability_is_info():
    kit = build_kit(sources=[software("СервисБезСтатуса для опросов")])
    issues = issues_of(kit, "V-SVC-01")
    assert len(issues) == 1 and issues[0].severity == "info"


def test_svc_01_skipped_without_registry():
    kit = build_kit(sources=[software("GitHub Actions")])
    report = run_validation(ValidationContext(kit=kit, registries=None, today=TODAY))
    assert "V-SVC-01" in report.summary["skipped"]


def test_act_01_deprecated_service_is_warning():
    kit = build_kit(sources=[software("Moodle 4.3 для тестов")])
    issues = issues_of(kit, "V-ACT-01")
    assert len(issues) == 1 and issues[0].severity == "warning"
    assert "deprecated" in issues[0].message


def test_act_01_current_service_ok():
    kit = build_kit(sources=[software("pandas 2.2")])
    assert issues_of(kit, "V-ACT-01") == []


def test_act_01_skipped_without_registry():
    kit = build_kit(sources=[software("Moodle 4.3")])
    report = run_validation(ValidationContext(kit=kit, registries=None, today=TODAY))
    assert "V-ACT-01" in report.summary["skipped"]
