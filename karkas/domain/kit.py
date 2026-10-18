"""karkas.domain.kit — каноническая модель комплекта KitV1 (Д4 §3, Д2 §13).

KitV1 — единственная сериализация комплекта. Из неё строятся все выгрузки
(.docx, .pptx, GIFT, Moodle XML, CSV, JSON). JSON Schema публикуется в
`/api/v1/schemas/kit-v1.json`.

Правила:
- ссылки (ref) стабильны: C1, LO1.2, M2, T2.3, Q-017, ST-T2.3-1, SRC-04;
- итоги часов НЕ хранятся: `Module.workload` и `grand_total()` вычисляются;
- поля-заполнители (приказ, ФИО, подписи) обязаны быть пустыми (V-TPL-03).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

# ---------------------------------------------------------------------------
# Аннотированные типы (стабильные ref-шаблоны, Д2 §5.1)
# ---------------------------------------------------------------------------

NonNegInt = Annotated[int, Field(ge=0)]
HoursCell = Annotated[int, Field(ge=0, le=500)]

RefCompetency = Annotated[str, StringConstraints(pattern=r"^C\d{1,2}$")]
RefOutcome = Annotated[str, StringConstraints(pattern=r"^LO\d{1,2}\.\d{1,2}$")]
RefModule = Annotated[str, StringConstraints(pattern=r"^M\d{1,2}$")]
RefTopic = Annotated[str, StringConstraints(pattern=r"^T\d{1,2}\.\d{1,2}$")]
RefSource = Annotated[str, StringConstraints(pattern=r"^SRC-\d{1,3}$")]
RefAny = Annotated[str, StringConstraints(pattern=r"^[A-Za-zА-Яа-я0-9][\w\-.]*$")]

OutcomeType = Literal["knowledge", "skill", "experience"]
ProgramKind = Literal["dpp_pk", "dop"]
ProgramForm = Literal["full_time", "part_time", "distance", "internship"]
DeliveryMode = Literal["in_person", "distance"]
VerifyStatus = Literal["verified", "partially_verified", "unverified", "not_found", "outdated"]
IssueSeverity = Literal["error", "warning", "info"]
AssessmentKind = Literal[
    "test_question",
    "seminar_task",
    "interview_question",
    "final_project",
    "exam_task",
    "portfolio_item",
]
QuestionType = Literal["single", "multiple", "truefalse", "short", "matching", "order", "open"]
SourceSection = Literal["normative", "main", "additional", "internet", "software"]
ContentBlockKind = Literal["module_program", "lecture_plan", "slides", "template_section", "annotation"]

ACTIVITIES: tuple[str, ...] = ("lecture", "practice", "lab", "self_study", "current_control")
CONTACT_ACTIVITIES: tuple[str, ...] = ("lecture", "practice", "lab")


# ---------------------------------------------------------------------------
# Часы
# ---------------------------------------------------------------------------


class Workload(BaseModel):
    """Часы по видам работ. `total` — вычисляемый, хранить его нельзя."""

    model_config = ConfigDict(extra="ignore")

    lecture: HoursCell = 0
    practice: HoursCell = 0
    lab: HoursCell = 0
    self_study: HoursCell = 0
    current_control: HoursCell = 0
    distance: HoursCell = 0  # «из них дистанционно» (подмножество контактных часов)

    @property
    def total(self) -> int:
        return self.lecture + self.practice + self.lab + self.self_study + self.current_control

    @property
    def contact(self) -> int:
        return self.lecture + self.practice + self.lab

    def by_activity(self, activity: str) -> int:
        return int(getattr(self, activity, 0))

    def is_zero(self) -> bool:
        return self.total == 0


def sum_workloads(items: Iterable[Workload]) -> Workload:
    """Поэлементная сумма часов (модуль = Σ тем; программа = Σ модулей)."""
    acc = Workload()
    for w in items:
        acc = Workload(
            lecture=acc.lecture + w.lecture,
            practice=acc.practice + w.practice,
            lab=acc.lab + w.lab,
            self_study=acc.self_study + w.self_study,
            current_control=acc.current_control + w.current_control,
            distance=acc.distance + w.distance,
        )
    return acc


# ---------------------------------------------------------------------------
# Каркас
# ---------------------------------------------------------------------------


class Outcome(BaseModel):
    """Результат обучения (З/У/Н) — LO1.2."""

    model_config = ConfigDict(extra="ignore")

    ref: RefOutcome
    type: OutcomeType
    text: str = Field(min_length=1)
    bloom_level: Annotated[int | None, Field(ge=1, le=6)] = None


class ProfStandardRef(BaseModel):
    """Ссылка на профстандарт — только код из реестра (V-SRC-02)."""

    model_config = ConfigDict(extra="ignore")

    code: str = Field(pattern=r"^\d{2}\.\d{3}$")
    title: str = ""
    status: Literal["active", "replaced", "cancelled"] = "active"
    order_number: str | None = None


class LaborFunctionRef(BaseModel):
    """Ссылка на трудовую функцию — только код из реестра (V-SRC-03)."""

    model_config = ConfigDict(extra="ignore")

    code: str  # C/14.6
    title: str = ""
    otf_code: str | None = None


class Competency(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref: RefCompetency
    title: str = Field(min_length=1)
    activity_kind: str | None = None
    prof_standard: ProfStandardRef | None = None  # обязателен для dpp_pk, запрещён для dop
    labor_functions: list[LaborFunctionRef] = Field(default_factory=list)
    outcomes: list[Outcome] = Field(default_factory=list)


class Topic(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref: RefTopic
    title: str = Field(min_length=1)
    summary: str | None = None
    workload: Workload = Field(default_factory=Workload)
    outcome_refs: list[str] = Field(default_factory=list)
    control_form: str | None = None
    complexity: Annotated[int, Field(ge=1, le=5)] = 1
    practicality: Annotated[float, Field(ge=0, le=1)] = 0.5  # 0 — теория, 1 — практика
    weight: Annotated[float, Field(gt=0)] = 1.0
    locked: list[str] = Field(default_factory=list)  # закреплённые ячейки: "practice:in_person"


class Module(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref: RefModule
    number: Annotated[int, Field(gt=0)]
    title: str = Field(min_length=1)
    weight: Annotated[float, Field(gt=0)] = 1.0
    att_form: str | None = None
    topics: list[Topic] = Field(default_factory=list)

    @property
    def workload(self) -> Workload:
        """Часы модуля — сумма тем (вычисляется, не хранится: AD-3)."""
        return sum_workloads(t.workload for t in self.topics)


class CalendarSession(BaseModel):
    model_config = ConfigDict(extra="ignore")

    seq: int = Field(gt=0)
    week: Annotated[int, Field(gt=0)]
    day: Annotated[int, Field(gt=0)]
    topic_ref: str | None = None  # None = итоговая аттестация
    activity: str = "lecture"
    mode: DeliveryMode = "in_person"
    hours: Annotated[int, Field(ge=1, le=12)]


class Calendar(BaseModel):
    model_config = ConfigDict(extra="ignore")

    weeks: Annotated[int, Field(gt=0)]
    days: Annotated[int, Field(gt=0)]
    days_per_week: Annotated[int, Field(gt=0, le=7)] = 5
    max_hours_per_day: Annotated[int, Field(gt=0, le=12)] = 8
    sessions: list[CalendarSession] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sequence_is_monotonic(self) -> Calendar:
        seqs = [s.seq for s in self.sessions]
        if seqs != sorted(seqs):
            raise ValueError("calendar.sessions: seq должен быть неубывающим")
        return self


class FinalAttestation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    form: str = Field(min_length=1)
    hours: Annotated[int, Field(ge=0, le=100)] = 2


class LegalBasis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref: str
    act: str
    status: VerifyStatus = "verified"


class Framework(BaseModel):
    model_config = ConfigDict(extra="ignore")

    goal: str = ""
    tasks: list[str] = Field(default_factory=list)
    competencies: list[Competency] = Field(default_factory=list)
    modules: list[Module] = Field(default_factory=list)
    final_attestation: FinalAttestation
    calendar: Calendar | None = None
    gaps: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Содержание
# ---------------------------------------------------------------------------


class AssessmentOption(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    text: str


class AnswerKey(BaseModel):
    model_config = ConfigDict(extra="ignore")

    correct: list[str] = Field(default_factory=list)
    explanation: str | None = None


class Criterion(BaseModel):
    """Критерий рубрики: баллы + уровни («зачтено» при ≥ 70 %)."""

    model_config = ConfigDict(extra="ignore")

    criterion: str
    max_points: Annotated[float, Field(ge=0)] = 0.0
    levels: list[str] = Field(default_factory=list)


class Assessment(BaseModel):
    """Оценочное средство: вопрос теста, задание семинара, ИА и т. п."""

    model_config = ConfigDict(extra="ignore")

    ref: RefAny
    kind: AssessmentKind
    topic_ref: str | None = None
    module_ref: str | None = None
    stem: str = Field(min_length=1)
    qtype: QuestionType | None = None
    options: list[AssessmentOption] = Field(default_factory=list)
    answer_key: AnswerKey | None = None
    rubric: list[Criterion] = Field(default_factory=list)
    outcome_refs: Annotated[list[str], Field(min_length=1)]
    difficulty: Annotated[int | None, Field(ge=1, le=5)] = None

    @model_validator(mode="after")
    def _kind_requires_payload(self) -> Assessment:
        if self.kind == "test_question" and (self.qtype is None or self.answer_key is None):
            raise ValueError(f"{self.ref}: тестовый вопрос требует qtype и answer_key (V-COV-04)")
        if self.kind in ("seminar_task", "final_project", "exam_task", "portfolio_item") and not self.rubric:
            raise ValueError(f"{self.ref}: задание/проект требуют критериев оценки (rubric)")
        return self


class ContentBlock(BaseModel):
    """Структурированное содержание: рабочая программа, лекция, слайды, раздел."""

    model_config = ConfigDict(extra="ignore")

    ref: RefAny
    kind: ContentBlockKind
    module_ref: str | None = None
    topic_ref: str | None = None
    body: dict[str, Any] = Field(default_factory=dict)
    generated_by: str | None = None
    stale: bool = False


class Source(BaseModel):
    """Источник: НПА / литература / интернет / ПО."""

    model_config = ConfigDict(extra="ignore")

    ref: RefSource
    section: SourceSection
    citation: str = Field(min_length=1)
    url: str | None = None
    isbn: str | None = None
    normative_act_ref: str | None = None
    topic_refs: list[str] = Field(default_factory=list)  # использование в темах (source_usage)
    status: VerifyStatus = "unverified"
    evidence: dict[str, Any] = Field(default_factory=dict)


class Content(BaseModel):
    model_config = ConfigDict(extra="ignore")

    module_programs: list[ContentBlock] = Field(default_factory=list)
    lecture_plans: list[ContentBlock] = Field(default_factory=list)
    slides: list[ContentBlock] = Field(default_factory=list)
    sections: list[ContentBlock] = Field(default_factory=list)
    assessments: list[Assessment] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Программа, профиль, плейсхолдеры, отчёт, эффект
# ---------------------------------------------------------------------------


class ProgramHeader(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: ProgramKind
    title: str = Field(min_length=1)
    form: ProgramForm
    total_hours: Annotated[int, Field(ge=1, le=2000)]
    final_attestation: FinalAttestation
    document: str = ""  # выдаваемый документ
    legal_basis: list[LegalBasis] = Field(default_factory=list)
    organization: str | None = None
    city: str | None = None
    year: int | None = None


class ProgramConstraints(BaseModel):
    """Ограничения часов (program.constraints в БД)."""

    model_config = ConfigDict(extra="ignore")

    min_practice_share_pct: float = Field(default=0.0, ge=0, le=100)
    self_study_only: bool = False
    unit_hours: Annotated[int, Field(ge=1, le=8)] = 1
    max_hours_per_day: Annotated[int, Field(ge=1, le=12)] = 8
    days_per_week: Annotated[int, Field(ge=1, le=7)] = 5
    distance_share_pct: float = Field(default=0.0, ge=0, le=100)
    self_study_share_pct: float = Field(default=0.0, ge=0, le=100)


class ProgramProfile(BaseModel):
    """JSON-профиль брифа (выход S01)."""

    model_config = ConfigDict(extra="ignore")

    audience: str | None = None
    entry_level: str | None = None
    schedule: str | None = None
    duration_hint: str | None = None
    notes: str | None = None
    glossary: dict[str, str] = Field(default_factory=dict)
    constraints: ProgramConstraints = Field(default_factory=ProgramConstraints)


class _EmptyStrModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @field_validator("*", mode="after")
    @classmethod
    def _must_stay_empty(cls, v: Any) -> Any:
        if isinstance(v, str) and v:
            raise ValueError("поле-заполнитель должно оставаться пустым (V-TPL-03)")
        return v


class TeacherPlaceholder(_EmptyStrModel):
    name: str = ""
    position: str = ""
    degree: str = ""


class SignaturePlaceholder(_EmptyStrModel):
    name: str = ""
    position: str = ""


class Placeholders(BaseModel):
    """Поля для ручного заполнения — всегда пустые (ЗАД-17, V-TPL-03)."""

    model_config = ConfigDict(extra="ignore")

    order_number: str = ""
    order_date: str = ""
    teachers: list[TeacherPlaceholder] = Field(default_factory=list)
    signatures: list[SignaturePlaceholder] = Field(default_factory=list)

    @field_validator("order_number", "order_date")
    @classmethod
    def _must_be_empty(cls, v: str) -> str:
        if v:
            raise ValueError("реквизиты приказа заполняются человеком вне системы (V-TPL-03)")
        return v


class ReportIssue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rule_code: str
    severity: IssueSeverity
    entity_ref: str | None = None
    message: str
    fix_hint: dict[str, Any] | None = None


class Report(BaseModel):
    """Отчёт автопроверки (S10/S19)."""

    model_config = ConfigDict(extra="ignore")

    passed: bool
    version: int | None = None
    duration_ms: int = 0
    summary: dict[str, Any] = Field(default_factory=dict)
    issues: list[ReportIssue] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    sample_findings: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)

    @property
    def errors(self) -> list[ReportIssue]:
        return [i for i in self.issues if i.severity == "error"]


class Assumption(BaseModel):
    """Допущение (ответ «на ваше усмотрение» или значение по умолчанию)."""

    model_config = ConfigDict(extra="ignore")

    text: str
    slot: str | None = None
    accepted_value: str | None = None
    source: Literal["default", "user", "agent"] = "default"


class Usage(BaseModel):
    """Фактический расход токенов и стоимость (из llm_call)."""

    model_config = ConfigDict(extra="ignore")

    calls: NonNegInt = 0
    prompt_tokens: NonNegInt = 0
    completion_tokens: NonNegInt = 0
    tokens: NonNegInt = 0
    cost_rub: Decimal = Decimal("0")
    duration_s: float = 0.0
    cache_hit_pct: float = 0.0


class KitV1(BaseModel):
    """Каноническая модель комплекта."""

    model_config = ConfigDict(extra="ignore")

    schema_version: Literal["kit.v1"] = "kit.v1"
    program: ProgramHeader
    profile: ProgramProfile = Field(default_factory=ProgramProfile)
    placeholders: Placeholders = Field(default_factory=Placeholders)
    framework: Framework
    content: Content = Field(default_factory=Content)
    assumptions: list[Assumption] = Field(default_factory=list)
    report: Report | None = None
    usage: Usage | None = None

    # --- Вычисляемые итоги (единственный источник — темы) -----------------

    def framework_workload(self) -> Workload:
        """Σ часов всех тем программы."""
        return sum_workloads(t.workload for m in self.framework.modules for t in m.topics)

    def grand_total(self) -> int:
        """Σ тем + итоговая аттестация (должно равняться program.total_hours)."""
        return self.framework_workload().total + self.framework.final_attestation.hours

    def iter_topics(self) -> Iterator[Topic]:
        for m in self.framework.modules:
            yield from m.topics

    def iter_outcomes(self) -> Iterator[Outcome]:
        for c in self.framework.competencies:
            yield from c.outcomes


# ---------------------------------------------------------------------------
# Утилиты поиска по ref (используются валидаторами, графом зависимостей, API)
# ---------------------------------------------------------------------------


def find_topic(kit: KitV1, ref: str) -> Topic | None:
    return next((t for t in kit.iter_topics() if t.ref == ref), None)


def find_module(kit: KitV1, ref: str) -> Module | None:
    return next((m for m in kit.framework.modules if m.ref == ref), None)


def find_outcome(kit: KitV1, ref: str) -> Outcome | None:
    return next((o for o in kit.iter_outcomes() if o.ref == ref), None)


def find_competency(kit: KitV1, ref: str) -> Competency | None:
    return next((c for c in kit.framework.competencies if c.ref == ref), None)


def find_assessment(kit: KitV1, ref: str) -> Assessment | None:
    return next((a for a in kit.content.assessments if a.ref == ref), None)


def find_content_block(kit: KitV1, ref: str) -> ContentBlock | None:
    for group in (
        kit.content.module_programs,
        kit.content.lecture_plans,
        kit.content.slides,
        kit.content.sections,
    ):
        for b in group:
            if b.ref == ref:
                return b
    return None


def find_source(kit: KitV1, ref: str) -> Source | None:
    return next((s for s in kit.content.sources if s.ref == ref), None)
