"""karkas.api.schemas — схемы запросов/ответов API v1 (Д4 §6)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from karkas.domain.kit import KitV1, ProgramConstraints, Report

ProgramStatus = Literal[
    "draft",
    "clarifying",
    "framework_generating",
    "framework_review",
    "framework_approved",
    "kit_generating",
    "kit_review",
    "kit_updating",
    "archived",
    "failed",
]

ArtifactFormat = Literal["docx", "pptx", "gift", "moodle_xml", "csv", "json", "report"]


class FileAttachIn(BaseModel):
    file_id: str
    role: Literal["template", "sample_program", "prof_standard", "reference", "old_program"] = "reference"


class ProgramCreateIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    brief: str = Field(min_length=1, max_length=20_000)
    file_ids: list[FileAttachIn] = Field(default_factory=list, max_length=10)
    options: dict[str, Any] = Field(default_factory=dict)


class ProgramCreateOut(BaseModel):
    program_id: str
    status: ProgramStatus
    job_id: str | None = None
    events: str


class ProgramPatchIn(BaseModel):
    """PATCH /programs/{id}: типизированные поля (Д4 §6.2, §10).

    Валидация значений на входе: объём 1..2000, ИА 0..100, ограничения — схемой
    ProgramConstraints (раньше принимался произвольный JSON и портил программу).
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    goal: str | None = Field(default=None, max_length=10_000)
    form: Literal["full_time", "part_time", "distance", "internship"] | None = None
    total_hours: int | None = Field(default=None, ge=1, le=2000)
    final_att_hours: int | None = Field(default=None, ge=0, le=100)
    final_att_form: str | None = Field(default=None, max_length=200)
    constraints: ProgramConstraints | None = None
    profile: dict[str, Any] | None = None


class ProgramListItem(BaseModel):
    id: str
    title: str
    kind: str | None
    total_hours: int | None
    status: ProgramStatus
    updated_at: str


class ProgramListOut(BaseModel):
    items: list[ProgramListItem]
    next_cursor: str | None = None


class QuestionOut(BaseModel):
    id: str
    slot: str
    ord: int
    text: str
    why: str = ""
    options: list[str] = Field(default_factory=list)
    allow_default: bool = True
    allow_free_text: bool = False


class QuestionsOut(BaseModel):
    status: ProgramStatus
    detected: dict[str, Any] = Field(default_factory=dict)
    questions: list[QuestionOut] = Field(default_factory=list)


class AnswerIn(BaseModel):
    id: str
    value: str | None = None
    use_default: bool = False


class AnswersIn(BaseModel):
    answers: list[AnswerIn] = Field(min_length=1, max_length=5)


class AnswersOut(BaseModel):
    status: ProgramStatus
    ready_for_framework: bool
    assumptions: list[str] = Field(default_factory=list)


class WorkloadCellIn(BaseModel):
    activity: Literal["lecture", "practice", "lab", "self_study", "current_control"]
    mode: Literal["in_person", "distance"] = "in_person"
    hours: int = Field(ge=0, le=500)


class FrameworkOp(BaseModel):
    """Операция правки каркаса (PATCH framework)."""

    model_config = ConfigDict(extra="ignore")

    op: Literal["set_hours", "rename", "move_topic", "link_outcome", "unlink_outcome", "set_goal", "set_final_att"]
    ref: str | None = None
    title: str | None = None
    topic_ref: str | None = None
    outcome_ref: str | None = None
    activity: str | None = None
    hours: int | None = Field(default=None, ge=0, le=500)
    lock: bool | None = None  # None — не трогать закрепление ячейки
    to_module: str | None = None
    position: int | None = None
    form: str | None = None


class FrameworkPatchIn(BaseModel):
    ops: list[FrameworkOp] = Field(min_length=1, max_length=200)


class FrameworkPatchOut(BaseModel):
    version: int
    checks: dict[str, Any]
    changed: list[dict[str, Any]] = Field(default_factory=list)


class RebalanceIn(BaseModel):
    scope: str | None = None  # module ref или None = вся программа
    keep_locked: bool = True


class RebalanceOut(BaseModel):
    version: int
    changed: list[dict[str, Any]]
    checks: dict[str, Any]


class ApproveIn(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class ApproveOut(BaseModel):
    status: ProgramStatus
    version: int
    approved_by: str | None
    approved_at: str | None


class ValidateOut(BaseModel):
    version: int
    checks: dict[str, Any]


class KitGenerateIn(BaseModel):
    slides: dict[str, Any] = Field(default_factory=dict)  # {"modules": ["M2"]}
    tests: dict[str, Any] = Field(default_factory=dict)  # {"final_questions": 10}
    lms_formats: list[str] = Field(default_factory=lambda: ["gift", "moodle_xml"])


class KitGenerateOut(BaseModel):
    job_id: str
    estimate_minutes: int = 12


class KitItemOut(BaseModel):
    ref: str
    kind: str
    payload: dict[str, Any]
    links: dict[str, Any] = Field(default_factory=dict)


class EditIn(BaseModel):
    target_ref: str = Field(min_length=1, max_length=100)
    instruction: str = Field(min_length=3, max_length=2000)
    dry_run: bool = False


class EditOut(BaseModel):
    edit_id: str
    status: str
    affected: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)
    job_id: str | None = None


KitRegeneratePart = Literal["module_program", "lecture_plan", "slides", "tests", "tasks"]


class KitRegenerateIn(BaseModel):
    target_ref: str = Field(min_length=1, max_length=100)
    parts: list[KitRegeneratePart] = Field(min_length=1, max_length=5)


class KitRegenerateOut(BaseModel):
    job_id: str


class ExportIn(BaseModel):
    formats: list[ArtifactFormat] = Field(min_length=1)


class ActualizeIn(BaseModel):
    """Тело POST /programs/{id}:actualize — ранее загруженные файлы старой программы."""

    file_ids: list[str] = Field(default_factory=list, max_length=10)


class ExportFileOut(BaseModel):
    kind: str
    name: str
    url: str
    expires_in: int = 900


class ExportOut(BaseModel):
    export_id: str | None = None
    status: str
    version: int | None = None
    files: list[ExportFileOut] = Field(default_factory=list)


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    progress: dict[str, Any]
    attempts: int
    error: dict[str, Any] | None = None


class VersionItemOut(BaseModel):
    version: int
    reason: str
    created_at: str
    created_by: str | None = None


class ProgramOut(BaseModel):
    id: str
    title: str
    kind: str | None
    total_hours: int | None
    status: ProgramStatus
    profile: dict[str, Any]
    constraints: dict[str, Any]
    lock_version: int


class FrameworkOut(BaseModel):
    version: int
    status: ProgramStatus
    kit: KitV1


class ReportOut(Report):
    """Отчёт автопроверки (см. karkas.domain.kit.Report)."""


class UsageOut(BaseModel):
    program_id: str
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_rub: Decimal = Decimal("0")
    cache_hit_pct: float = 0.0
    p95_latency_ms: float | None = None
    savings_hours: float | None = None
    tokens: int = 0
    methodologist_active_hours: float | None = None
    manual_baseline_hours: float | None = None
    first_time_framework_approval: bool | None = None


class AgentRunIn(BaseModel):
    """Единый эндпоинт автопрогонов (Д4 §6.6)."""

    model_config = ConfigDict(extra="ignore")

    request: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    mode: Literal["framework", "full"] = "full"
    answers: dict[str, str | None] | None = None
    run_id: str | None = None
    auto_approve: bool = False  # для автопрогонов сервисной платформы (только service-ключи)
    wait: bool = True
    formats: list[ArtifactFormat] = Field(default_factory=lambda: ["docx", "json"])


class AgentRunOut(BaseModel):
    run_id: str
    status: Literal["needs_input", "completed", "running", "failed"]
    program_id: str | None = None
    questions: list[dict[str, Any]] = Field(default_factory=list)
    version: int | None = None
    kit: KitV1 | None = None
    report: dict[str, Any] | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)
    timings: dict[str, float] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    detail: str | None = None
