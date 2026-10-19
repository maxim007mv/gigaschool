"""karkas.infra.exporters.docx_program — выгрузка программы в .docx (Д4 §5.12).

Два режима:

1. ``template_path`` задан и файл существует — рендер через ``docxtpl`` (шаблон АЦР
   с Jinja-метками). Контекст содержит плоские метки (``title``, ``kind_label``,
   ``total_hours``, ``order_number``, ``order_date``, ``city``, ``year``, ``goal`` …)
   и списки для таблиц (``modules``, ``curriculum``, ``thematic_plan``, ``calendar``,
   ``sources``, ``competencies``, ``assumptions``). Неизвестная метка шаблона —
   ошибка Jinja: методист должен видеть, что шаблон и контекст разошлись.
2. Иначе — программная сборка python-docx по структуре шаблона ДПП ПК (Д4 §5.12,
   таблица 4.9): титул, раздел 1 (аннотация, цель, результаты З/У/Н, основание,
   компетенции, требования, форма, объём, документ), раздел 2 (учебный план,
   учебно-тематический план, календарный график, рабочие программы, оценочные
   материалы), раздел 3 (условия и литература по разделам), приложения 1–2.

Инварианты:

- строки модулей и итоги вычисляются из тем: Σ тем + ИА = ``program.total_hours``;
- реквизиты приказа, ФИО и подписи — только пропуски-подчёркивания (V-TPL-03);
- источники и НПА со статусом ≠ verified помечаются «[не подтверждено — проверьте]»;
- при отсутствии данных раздел не пропадает: выводится явная пометка (функция
  не падает ни на пустом комплекте, ни без слайдов/тестов).

Педагогический текст (аннотации, разделы 3.x, методичка, формулировки заданий)
берётся **только** из комплекта KitV1 (выход навыков S11–S17 / GigaChat).
Экспортёр не подставляет шаблонные абзацы вместо ИИ — только рендер и
организационные пропуски (V-TPL-03).
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt
from docx.table import Table
from docxtpl import DocxTemplate
from jinja2.sandbox import SandboxedEnvironment

from karkas.domain.acr_reference import DOP_ACR_HEADINGS
from karkas.domain.kit import (
    Assessment,
    ContentBlock,
    KitV1,
    Module,
    Source,
    Topic,
)

KIND_LABELS: dict[str, str] = {
    "dpp_pk": "Дополнительная профессиональная программа повышения квалификации",
    "dop": "Дополнительная общеразвивающая программа",
}
FORM_LABELS: dict[str, str] = {
    "full_time": "очная",
    "part_time": "очно-заочная",
    "distance": "заочная с применением дистанционных образовательных технологий",
    "internship": "стажировка",
}
OUTCOME_TYPE_LABELS: dict[str, str] = {
    "knowledge": "Знать",
    "skill": "Уметь",
    "experience": "Владеть (практический опыт)",
}
OUTCOME_TYPE_ORDER = ("knowledge", "skill", "experience")
SOURCE_SECTION_LABELS: dict[str, str] = {
    "normative": "Нормативные правовые акты",
    "main": "Основная литература",
    "additional": "Дополнительная литература",
    "internet": "Интернет-ресурсы",
    "software": "Программное обеспечение и информационные сервисы",
}
SOURCE_SECTION_ORDER = ("normative", "main", "additional", "internet", "software")
ACTIVITY_LABELS: dict[str, str] = {
    "lecture": "лекция",
    "practice": "практическое занятие",
    "lab": "лабораторная работа",
    "self_study": "самостоятельная работа",
    "current_control": "текущий контроль",
    "final_attestation": "итоговая аттестация",
}
DELIVERY_MODE_LABELS: dict[str, str] = {"in_person": "очно", "distance": "дистанционно"}
ASSESSMENT_KIND_LABELS: dict[str, str] = {
    "test_question": "Тестовые вопросы",
    "seminar_task": "Задания семинаров (практикумов)",
    "interview_question": "Вопросы собеседования",
    "final_project": "Итоговый проект",
    "exam_task": "Экзаменационные задания",
    "portfolio_item": "Материалы портфолио",
}
TEST_KINDS = frozenset({"test_question"})
FINAL_ATTESTATION_KINDS = frozenset({"interview_question", "final_project", "exam_task", "portfolio_item"})

PRACTICE_KINDS = frozenset({"seminar_task"}) | TEST_KINDS | FINAL_ATTESTATION_KINDS

NO_COLUMN = "№"
NAME_COLUMN = "Наименование разделов и тем"
TOTAL_COLUMN = "Всего, ч"
LECTURE_COLUMN = "ЛК"
PRACTICE_COLUMN = "ПР"
LAB_COLUMN = "ЛБ"
SELF_STUDY_COLUMN = "СРС"
CONTROL_COLUMN = "Контроль"
DISTANCE_COLUMN = "ДОТ"
ATT_FORM_COLUMN = "Форма аттестации"
FINAL_ROW_LABEL = "Итоговая аттестация"
TOTAL_ROW_LABEL = "ИТОГО"

ORDER_PLACEHOLDER = "___"
ORDER_DATE_PLACEHOLDER = "«__» ________ 20__ г."
SIGNATURE_PLACEHOLDER = "______________________"
UNVERIFIED_MARK = "[не подтверждено — проверьте]"
PARTIAL_VERIFY_MARK = "[частично проверено — ISBN]"
NORMAL_FONT_SIZE_PT = 12
AI_SECTION_MISSING = (
    "[раздел не сформирован моделью — требуется генерация комплекта (GigaChat), не подстановка шаблона]"
)
ANNOTATION_MISSING_TEXT = "Аннотация в комплекте не сформирована."
LEGAL_BASIS_MISSING_TEXT = "Основание разработки программы в комплекте не указано."
COMPETENCIES_MISSING_TEXT = "Компетенции в комплекте не сформированы."
CALENDAR_MISSING_TEXT = "Календарный учебный график формируется по мере комплектования групп."
MODULE_PROGRAMS_MISSING_TEXT = "Рабочие программы модулей в комплекте не сформированы."

DOP_TITLE_LINES = (
    "ДОПОЛНИТЕЛЬНАЯ ОБЩЕОБРАЗОВАТЕЛЬНАЯ",
    "ОБЩЕРАЗВИВАЮЩАЯ ПРОГРАММА",
)
DOP_EXPLANATORY_NOTE_HEADING = "Пояснительная записка"
# Заголовки разделов эталона АЦР (24 ч) — единый источник: karkas.domain.acr_reference.
DOP_ACR_SECTION_HEADINGS: tuple[str, ...] = DOP_ACR_HEADINGS


# ---------------------------------------------------------------------------
# Расчётные значения и контекст шаблона
# ---------------------------------------------------------------------------


def _program_hours(kit: KitV1) -> dict[str, int]:
    """Часы программы: контактная работа, СРС, контроль, ДОТ, ИА, итог (из тем)."""
    workload = kit.framework_workload()
    return {
        "lecture": workload.lecture,
        "practice": workload.practice,
        "lab": workload.lab,
        "self_study": workload.self_study,
        "current_control": workload.current_control,
        "contact": workload.contact,
        "distance": workload.distance,
        "content": workload.total,
        "final_attestation": kit.framework.final_attestation.hours,
        "grand_total": kit.grand_total(),
    }


def _topic_number(topic: Topic) -> str:
    """Номер темы для таблиц: T2.3 → 2.3."""
    return topic.ref[1:] if topic.ref.startswith("T") else topic.ref


def _module_item(module: Module) -> dict[str, Any]:
    """Строка модуля учебного плана (часы считаются из тем)."""
    workload = module.workload
    return {
        "no": str(module.number),
        "name": f"М{module.number} {module.title}",
        "total": workload.total,
        "lecture": workload.lecture,
        "practice": workload.practice,
        "lab": workload.lab,
        "self_study": workload.self_study,
        "current_control": workload.current_control,
        "distance": workload.distance,
        "att_form": module.att_form or "",
        "bold": True,
    }


def _topic_item(topic: Topic) -> dict[str, Any]:
    """Строка темы учебно-тематического плана."""
    workload = topic.workload
    return {
        "no": _topic_number(topic),
        "name": topic.title,
        "total": workload.total,
        "lecture": workload.lecture,
        "practice": workload.practice,
        "lab": workload.lab,
        "self_study": workload.self_study,
        "current_control": workload.current_control,
        "distance": workload.distance,
        "att_form": topic.control_form or "",
        "bold": False,
    }


def _study_plan_items(kit: KitV1) -> list[dict[str, Any]]:
    """Строки учебного плана (2.1): модули + ИА + ИТОГО (Σ тем + ИА = объём)."""
    modules = [_module_item(module) for module in kit.framework.modules]
    hours = _program_hours(kit)
    final = kit.framework.final_attestation
    final_row = {
        "no": "",
        "name": FINAL_ROW_LABEL,
        "total": final.hours,
        "lecture": 0,
        "practice": 0,
        "lab": 0,
        "self_study": 0,
        "current_control": 0,
        "distance": 0,
        "att_form": final.form,
        "bold": False,
    }
    total_row = {
        "no": "",
        "name": TOTAL_ROW_LABEL,
        "total": hours["grand_total"],
        "lecture": hours["lecture"],
        "practice": hours["practice"],
        "lab": hours["lab"],
        "self_study": hours["self_study"],
        "current_control": hours["current_control"],
        "distance": hours["distance"],
        "att_form": "",
        "bold": True,
    }
    return [*modules, final_row, total_row]


def _thematic_plan_items(kit: KitV1) -> list[dict[str, Any]]:
    """Строки учебно-тематического плана (2.2): модули, темы, ИА, итог."""
    items: list[dict[str, Any]] = []
    for module in kit.framework.modules:
        items.append(_module_item(module))
        items.extend(_topic_item(topic) for topic in module.topics)
    plan = _study_plan_items(kit)
    items.extend(plan[-2:])  # ИА + ИТОГО
    return items


def _module_payload(module: Module) -> dict[str, Any]:
    """Модуль для контекста docxtpl: часы + темы."""
    payload = _module_item(module)
    payload["ref"] = module.ref
    payload["title"] = module.title
    payload["topics"] = [
        {**_topic_item(topic), "ref": topic.ref, "outcome_refs": list(topic.outcome_refs)} for topic in module.topics
    ]
    return payload


def _source_payload(source: Source, number: int, *, marked: bool = True) -> dict[str, Any]:
    """Источник для контекста docxtpl с пометкой неподтверждённых."""
    citation = source.citation
    if marked and source.status == "partially_verified":
        citation = f"{citation} {PARTIAL_VERIFY_MARK}"
    elif marked and source.status != "verified":
        citation = f"{citation} {UNVERIFIED_MARK}"
    return {
        "ref": source.ref,
        "number": number,
        "citation": citation,
        "url": source.url or "",
        "isbn": source.isbn or "",
        "status": source.status,
        "section": source.section,
        "section_label": SOURCE_SECTION_LABELS.get(source.section, source.section),
    }


def _template_context(kit: KitV1) -> dict[str, Any]:
    """Контекст docxtpl: плоские метки и списки строк для таблиц шаблона АЦР."""
    header = kit.program
    hours = _program_hours(kit)
    final = kit.framework.final_attestation
    sources = [_source_payload(source, index + 1) for index, source in enumerate(kit.content.sources)]
    calendar = kit.framework.calendar
    return {
        "kit": kit,
        "program": kit.program.model_dump(mode="json"),
        "title": header.title,
        "kind": header.kind,
        "kind_label": KIND_LABELS.get(header.kind, header.kind),
        "organization": header.organization or ORDER_PLACEHOLDER,
        "city": header.city or ORDER_PLACEHOLDER,
        "year": header.year or datetime.now(UTC).year,
        "form": header.form,
        "form_label": FORM_LABELS.get(header.form, header.form),
        "total_hours": header.total_hours,
        "document": header.document,
        "order_number": ORDER_PLACEHOLDER,
        "order_date": ORDER_DATE_PLACEHOLDER,
        "goal": kit.framework.goal,
        "tasks": list(kit.framework.tasks),
        "final_attestation": {
            "form": final.form,
            "hours": final.hours,
        },
        "hours": hours,
        "competencies": [c.model_dump(mode="json") for c in kit.framework.competencies],
        "modules": [_module_payload(module) for module in kit.framework.modules],
        "curriculum": _study_plan_items(kit),
        "thematic_plan": _thematic_plan_items(kit),
        "calendar": (
            {
                "weeks": calendar.weeks,
                "days": calendar.days,
                "days_per_week": calendar.days_per_week,
                "max_hours_per_day": calendar.max_hours_per_day,
                "sessions": [
                    {
                        "seq": session.seq,
                        "week": session.week,
                        "day": session.day,
                        "topic_ref": session.topic_ref or "",
                        "activity": session.activity,
                        "mode": session.mode,
                        "hours": session.hours,
                    }
                    for session in calendar.sessions
                ],
            }
            if calendar
            else None
        ),
        "assessments": [a.model_dump(mode="json") for a in kit.content.assessments],
        "sources": sources,
        "assumptions": [assumption.text for assumption in kit.assumptions],
        "placeholders": kit.placeholders.model_dump(mode="json"),
        "unverified_mark": UNVERIFIED_MARK,
    }


# ---------------------------------------------------------------------------
# Программная сборка документа (python-docx)
# ---------------------------------------------------------------------------


def _prepare_styles(document: DocxDocument) -> None:
    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(NORMAL_FONT_SIZE_PT)


def _para(document: DocxDocument, text: str = "", *, bold: bool = False, italic: bool = False) -> None:
    if not text:
        return
    paragraph = document.add_paragraph()
    run = paragraph.add_run(text)
    run.bold = bold
    run.italic = italic


def _bullets(document: DocxDocument, items: Sequence[str]) -> None:
    for item in items:
        document.add_paragraph(item, style="List Bullet")


def _set_cell(cell: Any, value: str, *, bold: bool = False) -> None:
    cell.text = str(value)
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.bold = bold


def _curriculum_header(use_distance: bool) -> list[str]:
    """Заголовок таблиц учебного плана; колонка ДОТ — только если есть ДОТ."""
    header = [
        NO_COLUMN,
        NAME_COLUMN,
        TOTAL_COLUMN,
        LECTURE_COLUMN,
        PRACTICE_COLUMN,
        LAB_COLUMN,
        SELF_STUDY_COLUMN,
        CONTROL_COLUMN,
    ]
    if use_distance:
        header.append(DISTANCE_COLUMN)
    header.append(ATT_FORM_COLUMN)
    return header


def _item_cells(item: dict[str, Any], use_distance: bool) -> list[str]:
    cells = [
        str(item["no"]),
        str(item["name"]),
        str(item["total"]),
        str(item["lecture"]),
        str(item["practice"]),
        str(item["lab"]),
        str(item["self_study"]),
        str(item["current_control"]),
    ]
    if use_distance:
        cells.append(str(item["distance"]))
    cells.append(str(item["att_form"]))
    return cells


def _add_items_table(
    document: DocxDocument,
    header: Sequence[str],
    items: Sequence[dict[str, Any]],
    use_distance: bool,
) -> Table:
    table = document.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"
    for index, title in enumerate(header):
        _set_cell(table.rows[0].cells[index], title, bold=True)
    for item in items:
        cells = table.add_row().cells
        for index, value in enumerate(_item_cells(item, use_distance)):
            _set_cell(cells[index], value, bold=bool(item["bold"]))
    return table


def _uses_distance(kit: KitV1) -> bool:
    """Колонка ДОТ появляется, если дистанционные часы есть хотя бы у одной темы."""
    return any(module.workload.distance > 0 for module in kit.framework.modules)


def _find_block(kit: KitV1, kind: str) -> ContentBlock | None:
    return next((block for block in kit.content.sections if block.kind == kind), None)


def _annotation_for_export(kit: KitV1) -> str:
    block = _find_block(kit, "annotation")
    text = _block_text(block) if block else ""
    if text:
        return text
    audience = kit.profile.audience or "слушателей"
    goal = (kit.framework.goal or "").strip()
    base = (
        f"Программа «{kit.program.title}» направлена на {audience} "
        f"и рассчитана на {kit.program.total_hours} академических часов."
    )
    return f"{base} {goal}".strip() if goal else base


def _block_text(block: ContentBlock) -> str:
    for key in ("text", "markdown", "content", "summary"):
        value = block.body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _topic_of(kit: KitV1, ref: str | None) -> Topic | None:
    if not ref:
        return None
    return next((topic for topic in kit.iter_topics() if topic.ref == ref), None)


def _assessment_topic_line(kit: KitV1, assessment: Assessment) -> str:
    topic = _topic_of(kit, assessment.topic_ref)
    parts = ["РО: " + ", ".join(assessment.outcome_refs)]
    if topic is not None:
        parts.append(f"тема {topic.ref}")
    return f"({'; '.join(parts)})"


def _add_rubric(document: DocxDocument, assessment: Assessment) -> None:
    if not assessment.rubric:
        return
    _para(document, "Критерии оценки:", bold=True)
    for criterion in assessment.rubric:
        line = f"{criterion.criterion} — до {criterion.max_points:g} баллов"
        if criterion.levels:
            line += f" (уровни: {', '.join(criterion.levels)})"
        document.add_paragraph(line, style="List Bullet")


def _add_assessment_full(document: DocxDocument, kit: KitV1, assessment: Assessment) -> None:
    """Оценочное средство целиком: формулировка, варианты, ключ, критерии."""
    _para(document, f"{assessment.ref}. {assessment.stem}", bold=True)
    _para(document, _assessment_topic_line(kit, assessment), italic=True)
    correct = set(assessment.answer_key.correct) if assessment.answer_key else set()
    for option in assessment.options:
        marker = " — верный ответ" if option.id in correct else ""
        document.add_paragraph(f"— {option.text}{marker}", style="List Bullet")
    if assessment.qtype == "short" and assessment.answer_key and assessment.answer_key.correct:
        answers = ", ".join(assessment.answer_key.correct)
        document.add_paragraph(f"— принимаемые ответы: {answers}", style="List Bullet")
    if assessment.answer_key and assessment.answer_key.explanation:
        _para(document, f"Пояснение: {assessment.answer_key.explanation}")
    _add_rubric(document, assessment)


def _add_assessment_overview(document: DocxDocument, kit: KitV1, assessment: Assessment) -> None:
    """Краткая строка для раздела 2.5."""
    _para(document, f"{assessment.ref}. {assessment.stem}")
    _para(document, _assessment_topic_line(kit, assessment), italic=True)


def _add_title_page(document: DocxDocument, kit: KitV1) -> None:
    header = kit.program
    organization = document.add_paragraph()
    organization.alignment = WD_ALIGN_PARAGRAPH.CENTER
    organization.add_run(header.organization or ORDER_PLACEHOLDER)
    approved = document.add_paragraph()
    approved.alignment = WD_ALIGN_PARAGRAPH.CENTER
    approved.add_run("УТВЕРЖДЕНО").bold = True
    order = document.add_paragraph()
    order.alignment = WD_ALIGN_PARAGRAPH.CENTER
    order.add_run(f"Приказом № {ORDER_PLACEHOLDER} от {ORDER_DATE_PLACEHOLDER}")
    document.add_paragraph()
    kind = document.add_paragraph()
    kind.alignment = WD_ALIGN_PARAGRAPH.CENTER
    kind.add_run(KIND_LABELS.get(header.kind, header.kind))
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run(header.title).bold = True
    document.add_paragraph()
    footer = document.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run(f"{header.city or ORDER_PLACEHOLDER} — {header.year or datetime.now(UTC).year}")
    document.add_page_break()


def _add_section_1(document: DocxDocument, kit: KitV1) -> None:
    header = kit.program
    hours = _program_hours(kit)
    document.add_heading("1. Общая характеристика программы", level=1)

    document.add_heading("1.1 Аннотация", level=2)
    _para(document, _annotation_for_export(kit))

    document.add_heading("1.2 Цель и задачи программы", level=2)
    _para(document, kit.framework.goal or "Цель в комплекте не сформулирована.")
    if kit.framework.tasks:
        _para(document, "Задачи:", bold=True)
        _bullets(document, kit.framework.tasks)

    document.add_heading("1.3 Планируемые результаты обучения", level=2)
    if not kit.framework.competencies:
        _para(document, COMPETENCIES_MISSING_TEXT)
    for competency in kit.framework.competencies:
        document.add_heading(f"{competency.ref}. {competency.title}", level=3)
        grouped: dict[str, list[str]] = {key: [] for key in OUTCOME_TYPE_ORDER}
        for outcome in competency.outcomes:
            grouped.setdefault(outcome.type, []).append(f"{outcome.ref}. {outcome.text}")
        for outcome_type in OUTCOME_TYPE_ORDER:
            items = grouped.get(outcome_type) or []
            if not items:
                continue
            _para(document, f"{OUTCOME_TYPE_LABELS.get(outcome_type, outcome_type)}:", bold=True)
            _bullets(document, items)

    document.add_heading("1.4 Программа разработана на основе", level=2)
    basis_lines: list[str] = []
    for competency in kit.framework.competencies:
        standard = competency.prof_standard
        if standard is None:
            continue
        line = f"Профессиональный стандарт {standard.code}"
        if standard.title:
            line += f" «{standard.title}»"
        if standard.status != "active":
            line += f" {UNVERIFIED_MARK}"
        basis_lines.append(line)
    for legal in header.legal_basis:
        line = legal.act
        if legal.status != "verified":
            line += f" {UNVERIFIED_MARK}"
        basis_lines.append(line)
    if basis_lines:
        _bullets(document, basis_lines)
    else:
        _para(document, LEGAL_BASIS_MISSING_TEXT)

    document.add_heading("1.5 Перечень компетенций и трудовых функций", level=2)
    if not kit.framework.competencies:
        _para(document, COMPETENCIES_MISSING_TEXT)
    for competency in kit.framework.competencies:
        line = f"{competency.ref}. {competency.title}"
        codes = [function.code for function in competency.labor_functions]
        if codes:
            line += f" (трудовые функции: {', '.join(codes)})"
        _bullets(document, [line])

    document.add_heading("1.6 Требования к слушателям", level=2)
    profile = kit.profile
    _para(document, f"Категория слушателей: {profile.audience or AI_SECTION_MISSING}.")
    _para(document, f"Входной уровень: {profile.entry_level or AI_SECTION_MISSING}.")

    document.add_heading("1.7 Форма обучения", level=2)
    form_line = FORM_LABELS.get(header.form, header.form)
    if hours["distance"]:
        form_line += (
            f"; из них {hours['distance']} ч контактной работы — с применением дистанционных образовательных технологий"
        )
    _para(document, f"Форма обучения: {form_line}.")

    document.add_heading("1.8 Объём программы", level=2)
    parts = [
        f"Общая трудоёмкость — {hours['grand_total']} акад. ч",
        f"контактная работа — {hours['contact']} ч",
    ]
    if hours["current_control"]:
        parts.append(f"текущий контроль — {hours['current_control']} ч")
    parts.append(f"самостоятельная работа — {hours['self_study']} ч")
    parts.append(f"итоговая аттестация — {hours['final_attestation']} ч ({kit.framework.final_attestation.form})")
    if hours["distance"]:
        parts.append(f"из них с применением ДОТ — {hours['distance']} ч")
    _para(document, "; ".join(parts) + ".")
    calendar = kit.framework.calendar
    if calendar is not None:
        _para(document, f"Срок освоения — {calendar.weeks} нед. ({calendar.days} учебных дней).")
    elif profile.schedule:
        _para(document, f"Срок освоения — {profile.schedule}.")
    else:
        _para(document, "Срок освоения формируется по мере комплектования групп.")

    document.add_heading("1.9 Выдаваемый документ", level=2)
    document_text = header.document or "документ определяется образовательной организацией"
    _para(document, f"По итогам обучения выдаётся: {document_text}.")


def _add_section_2(document: DocxDocument, kit: KitV1) -> None:
    use_distance = _uses_distance(kit)
    header = _curriculum_header(use_distance)
    document.add_heading("2. Содержание программы", level=1)

    document.add_heading("2.1 Учебный план", level=2)
    _add_items_table(document, header, _study_plan_items(kit), use_distance)

    document.add_heading("2.2 Учебно-тематический план", level=2)
    _add_items_table(document, header, _thematic_plan_items(kit), use_distance)

    document.add_heading("2.3 Календарный учебный график", level=2)
    calendar = kit.framework.calendar
    if calendar is None or not calendar.sessions:
        _para(document, CALENDAR_MISSING_TEXT)
    else:
        calendar_header = ["№", "Неделя", "День", "Тема / этап", "Вид работы", "Часы", "Режим"]
        table = document.add_table(rows=1, cols=len(calendar_header))
        table.style = "Table Grid"
        for index, title in enumerate(calendar_header):
            _set_cell(table.rows[0].cells[index], title, bold=True)
        for session in calendar.sessions:
            topic = _topic_of(kit, session.topic_ref)
            name = topic.title if topic is not None else FINAL_ROW_LABEL
            values = [
                str(session.seq),
                str(session.week),
                str(session.day),
                name,
                ACTIVITY_LABELS.get(session.activity, session.activity),
                str(session.hours),
                DELIVERY_MODE_LABELS.get(session.mode, session.mode),
            ]
            cells = table.add_row().cells
            for index, value in enumerate(values):
                _set_cell(cells[index], value)

    document.add_heading("2.4 Рабочие программы модулей", level=2)
    if not kit.content.module_programs:
        _para(document, MODULE_PROGRAMS_MISSING_TEXT)
    for block in kit.content.module_programs:
        module = next((m for m in kit.framework.modules if m.ref == block.module_ref), None)
        title = block.body.get("title") if isinstance(block.body.get("title"), str) else None
        heading = title or (f"М{module.number} {module.title}" if module else block.ref)
        document.add_heading(heading, level=3)
        text = _block_text(block)
        if text:
            for line in text.splitlines():
                if line.strip():
                    _para(document, line.strip())

    document.add_heading("2.5 Оценочные материалы", level=2)
    if not kit.content.assessments:
        _para(document, "Оценочные материалы в комплекте не сформированы.")
    for kind, label in ASSESSMENT_KIND_LABELS.items():
        group = [a for a in kit.content.assessments if a.kind == kind]
        if not group:
            continue
        document.add_heading(label, level=3)
        for assessment in group:
            _add_assessment_overview(document, kit, assessment)


def _add_section_3(document: DocxDocument, kit: KitV1) -> None:
    document.add_heading("3. Условия реализации программы", level=1)
    index = 1
    template_sections = [block for block in kit.content.sections if block.kind == "template_section"]
    if template_sections:
        for block in template_sections:
            title = block.body.get("title") if isinstance(block.body.get("title"), str) else None
            document.add_heading(f"3.{index} {title or block.ref}", level=2)
            text = _block_text(block)
            if text:
                for line in text.splitlines():
                    if line.strip():
                        _para(document, line.strip())
            index += 1
    else:
        document.add_heading(f"3.{index} Материально-техническое и организационное обеспечение", level=2)
        _para(document, AI_SECTION_MISSING)
        index += 1

    document.add_heading(f"3.{index} Учебно-методическое обеспечение и литература", level=2)
    if not kit.content.sources:
        _para(document, "Источники в комплекте не сформированы.")
    number = 0
    for section in SOURCE_SECTION_ORDER:
        sources = [source for source in kit.content.sources if source.section == section]
        if not sources:
            continue
        _para(document, SOURCE_SECTION_LABELS.get(section, section), bold=True)
        for source in sources:
            number += 1
            line = f"{number}. {source.citation}"
            if source.isbn:
                line += f" — ISBN {source.isbn}"
            if source.url:
                line += f" — {source.url}"
            if source.status != "verified":
                line += f" {UNVERIFIED_MARK}"
            document.add_paragraph(line, style="List Bullet")
    index += 1

    document.add_heading(f"3.{index} Кадровое обеспечение", level=2)
    _para(document, f"Преподаватель(и): {SIGNATURE_PLACEHOLDER} / {SIGNATURE_PLACEHOLDER} /")


def _add_appendix_1(document: DocxDocument, kit: KitV1) -> None:
    document.add_page_break()
    document.add_heading("Приложение 1. Оценочные материалы текущего контроля", level=1)
    current = [a for a in kit.content.assessments if a.kind == "test_question" or a.kind == "seminar_task"]
    if not current:
        _para(document, "Оценочные материалы текущего контроля в комплекте не сформированы.")
    for assessment in current:
        _add_assessment_full(document, kit, assessment)


def _add_appendix_2(document: DocxDocument, kit: KitV1) -> None:
    document.add_page_break()
    document.add_heading("Приложение 2. Оценочные материалы итоговой аттестации", level=1)
    final = kit.framework.final_attestation
    _para(document, f"Форма итоговой аттестации: {final.form} ({final.hours} ч).", bold=True)
    group = [a for a in kit.content.assessments if a.kind in FINAL_ATTESTATION_KINDS]
    if not group:
        _para(document, "Оценочные материалы итоговой аттестации в комплекте не сформированы.")
    for assessment in group:
        _add_assessment_full(document, kit, assessment)


def _add_signatures(document: DocxDocument, kit: KitV1) -> None:
    """Подписи и ФИО — только пустые пропуски (V-TPL-03)."""
    document.add_paragraph()
    _para(document, f"Разработчик(и): {SIGNATURE_PLACEHOLDER} / {SIGNATURE_PLACEHOLDER} /")
    _para(document, "Согласовано: ______________________ / ______________________ /")


def _outcomes_grouped(kit: KitV1) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {key: [] for key in OUTCOME_TYPE_ORDER}
    for competency in kit.framework.competencies:
        for outcome in competency.outcomes:
            grouped.setdefault(outcome.type, []).append(outcome.text)
    return grouped


def _template_section_text(kit: KitV1, *title_parts: str) -> str:
    """Текст блока template_section, если заголовок содержит одну из подстрок."""
    lowered = [part.lower() for part in title_parts]
    for block in kit.content.sections:
        if block.kind != "template_section":
            continue
        title = str(block.body.get("title") or "")
        if any(part in title.lower() for part in lowered):
            text = _block_text(block)
            if text:
                return text
    return ""


def _add_dop_title_page(document: DocxDocument, kit: KitV1) -> None:
    header = kit.program
    organization = document.add_paragraph()
    organization.alignment = WD_ALIGN_PARAGRAPH.CENTER
    organization.add_run(header.organization or ORDER_PLACEHOLDER)
    approved = document.add_paragraph()
    approved.alignment = WD_ALIGN_PARAGRAPH.CENTER
    approved.add_run("УТВЕРЖДЕНО").bold = True
    order = document.add_paragraph()
    order.alignment = WD_ALIGN_PARAGRAPH.CENTER
    order.add_run(f"Приказом № {ORDER_PLACEHOLDER} от {ORDER_DATE_PLACEHOLDER}")
    document.add_paragraph()
    for line in DOP_TITLE_LINES:
        kind_line = document.add_paragraph()
        kind_line.alignment = WD_ALIGN_PARAGRAPH.CENTER
        kind_line.add_run(line).bold = True
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run(f"«{header.title}»").bold = True
    document.add_paragraph()
    footer = document.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run(f"{header.city or ORDER_PLACEHOLDER} {header.year or datetime.now(UTC).year}")
    document.add_page_break()


def _add_dop_explanatory_note(document: DocxDocument, kit: KitV1) -> None:
    document.add_heading(DOP_EXPLANATORY_NOTE_HEADING, level=1)
    _para(document, _annotation_for_export(kit))


def _add_dop_part_1(document: DocxDocument, kit: KitV1) -> None:
    header = kit.program
    profile = kit.profile
    hours = _program_hours(kit)
    calendar = kit.framework.calendar

    document.add_heading("1.1. Актуальность Программы", level=2)
    _para(
        document,
        _template_section_text(kit, "актуальность") or _annotation_for_export(kit) or ANNOTATION_MISSING_TEXT,
    )

    document.add_heading("1.2. Категории обучающихся", level=2)
    _para(
        document,
        profile.audience or _template_section_text(kit, "категор", "слушател") or AI_SECTION_MISSING,
    )
    if profile.entry_level:
        _para(document, f"Входной уровень: {profile.entry_level}.")

    document.add_heading("1.3. Цель и задачи программы", level=2)
    _para(document, kit.framework.goal or "Цель в комплекте не сформулирована.")
    if kit.framework.tasks:
        _para(document, "Задачи Программы", bold=True)
        _bullets(document, kit.framework.tasks)

    document.add_heading("1.4. Сроки реализации", level=2)
    _para(document, f"Трудоёмкость: {hours['grand_total']} часов.")
    if calendar is not None:
        _para(document, f"Срок реализации: {calendar.days} дней ({calendar.weeks} учебных недель).")
    elif profile.schedule:
        _para(document, f"Срок реализации: {profile.schedule}.")
    else:
        _para(document, "Конкретные даты устанавливаются приказом о зачислении по мере комплектования групп.")

    document.add_heading("1.5. Планируемые результаты обучения", level=2)
    grouped = _outcomes_grouped(kit)
    for outcome_type, label in (
        ("knowledge", "Знания"),
        ("skill", "Умения"),
        ("experience", "Навыки"),
    ):
        items = grouped.get(outcome_type) or []
        if not items:
            continue
        _para(document, f"{label}:", bold=True)
        _bullets(document, items)
    if not any(grouped.values()):
        _para(document, COMPETENCIES_MISSING_TEXT)

    document.add_heading("1.6. Календарный учебный график", level=2)
    if calendar is None:
        _para(document, CALENDAR_MISSING_TEXT)
    else:
        _para(
            document,
            f"Количество учебных недель — {calendar.weeks}; учебных дней — {calendar.days}; "
            f"режим занятий: не более {calendar.max_hours_per_day} ч в день.",
        )
        if calendar.sessions:
            calendar_header = ["№", "Неделя", "День", "Тема / этап", "Вид работы", "Часы"]
            table = document.add_table(rows=1, cols=len(calendar_header))
            table.style = "Table Grid"
            for index, title in enumerate(calendar_header):
                _set_cell(table.rows[0].cells[index], title, bold=True)
            for session in calendar.sessions:
                topic = _topic_of(kit, session.topic_ref)
                name = topic.title if topic is not None else FINAL_ROW_LABEL
                values = [
                    str(session.seq),
                    str(session.week),
                    str(session.day),
                    name,
                    ACTIVITY_LABELS.get(session.activity, session.activity),
                    str(session.hours),
                ]
                cells = table.add_row().cells
                for index, value in enumerate(values):
                    _set_cell(cells[index], value)

    if header.document:
        _para(document, f"Документ, выдаваемый по итогам обучения: {header.document}.")


def _add_dop_part_2(document: DocxDocument, kit: KitV1) -> None:
    use_distance = _uses_distance(kit)
    header = _curriculum_header(use_distance)
    document.add_heading("2. Содержание программы", level=1)

    document.add_heading("2.1. Учебный план", level=2)
    _add_items_table(document, header, _study_plan_items(kit), use_distance)

    document.add_heading("2.2. Учебно-тематический план", level=2)
    _add_items_table(document, header, _thematic_plan_items(kit), use_distance)

    document.add_heading("2.3. Оценочные материалы", level=2)
    final = kit.framework.final_attestation
    _para(document, f"Итоговая аттестация — {final.form} ({final.hours} ч).")
    if not kit.content.assessments:
        _para(document, "Оценочные материалы в комплекте не сформированы.")
    for assessment in kit.content.assessments:
        _add_assessment_full(document, kit, assessment)

    document.add_heading("2.4. Методические материалы", level=2)
    methodical = _template_section_text(kit, "методическ")
    _para(document, methodical or AI_SECTION_MISSING)


def _add_dop_part_3(document: DocxDocument, kit: KitV1) -> None:
    document.add_heading("3. Организационно-педагогические условия реализации программы", level=1)

    document.add_heading("3.1. Материально-технические условия реализации программы", level=2)
    mto = _template_section_text(kit, "материально", "техническ")
    _para(document, mto or AI_SECTION_MISSING)

    document.add_heading("3.2. Учебно-методическое и информационное обеспечение программы", level=2)
    umi = _template_section_text(kit, "учебно-методическ", "информацион")
    _para(document, umi or AI_SECTION_MISSING)

    document.add_heading("3.3. Литература", level=2)
    for section, subheading in (
        ("main", "3.3.1. Основная литература"),
        ("additional", "3.3.2. Дополнительная литература"),
        ("internet", "3.3.3. Интернет-ресурсы"),
    ):
        sources = [source for source in kit.content.sources if source.section == section]
        document.add_heading(subheading, level=3)
        if not sources:
            _para(document, "—")
            continue
        for index, source in enumerate(sources, start=1):
            line = f"{index}. {source.citation}"
            if source.url:
                line += f" {source.url}"
            if source.status != "verified":
                line += f" {UNVERIFIED_MARK}"
            document.add_paragraph(line, style="List Bullet")

    document.add_heading("3.4. Кадровое обеспечение программы", level=2)
    _para(document, f"Преподаватель(и): {SIGNATURE_PLACEHOLDER} / {SIGNATURE_PLACEHOLDER} /")


def _add_internship_title_page(document: DocxDocument, kit: KitV1) -> None:
    header = kit.program
    organization = document.add_paragraph()
    organization.alignment = WD_ALIGN_PARAGRAPH.CENTER
    organization.add_run(header.organization or ORDER_PLACEHOLDER)
    approved = document.add_paragraph()
    approved.alignment = WD_ALIGN_PARAGRAPH.CENTER
    approved.add_run("УТВЕРЖДЕНО").bold = True
    order = document.add_paragraph()
    order.alignment = WD_ALIGN_PARAGRAPH.CENTER
    order.add_run(f"Приказом № {ORDER_PLACEHOLDER} от {ORDER_DATE_PLACEHOLDER}")
    document.add_paragraph()
    for line in (
        "ДОПОЛНИТЕЛЬНАЯ ПРОФЕССИОНАЛЬНАЯ ПРОГРАММА",
        "ПОВЫШЕНИЯ КВАЛИФИКАЦИИ В ФОРМЕ СТАЖИРОВКИ",
    ):
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.add_run(line)
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run(f"«{header.title}»").bold = True
    document.add_paragraph()
    footer = document.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run(f"{header.city or ORDER_PLACEHOLDER} — {header.year or datetime.now(UTC).year}")
    document.add_page_break()


def _add_internship_section_1(document: DocxDocument, kit: KitV1) -> None:
    """Раздел 1 стажировки — заголовки как в data/templates/acr_dpp_pk_staj_bsa_248h.txt."""
    header = kit.program
    hours = _program_hours(kit)
    document.add_heading(
        "1. ОБЩАЯ ХАРАКТЕРИСТИКА ДОПОЛНИТЕЛЬНОЙ ПРОФЕССИОНАЛЬНОЙ ПРОГРАММЫ",
        level=1,
    )

    document.add_heading("1.1. Аннотация программы", level=2)
    _para(document, _annotation_for_export(kit))

    document.add_heading("1.2. Цель реализации программы", level=2)
    _para(document, kit.framework.goal or "Цель в комплекте не сформулирована.")

    document.add_heading("1.3. Планируемые результаты обучения", level=2)
    if not kit.framework.competencies:
        _para(document, COMPETENCIES_MISSING_TEXT)
    for competency in kit.framework.competencies:
        document.add_heading(f"{competency.ref}. {competency.title}", level=3)
        for outcome in competency.outcomes:
            _para(
                document,
                f"{outcome.ref}. ({OUTCOME_TYPE_LABELS.get(outcome.type, outcome.type)}) {outcome.text}",
            )

    document.add_heading("1.4. Программа разработана на основе", level=2)
    basis_lines: list[str] = []
    for competency in kit.framework.competencies:
        standard = competency.prof_standard
        if standard is None:
            continue
        line = f"Профессиональный стандарт {standard.code}"
        if standard.title:
            line += f" «{standard.title}»"
        if standard.status != "active":
            line += f" {UNVERIFIED_MARK}"
        basis_lines.append(line)
    for legal in header.legal_basis:
        line = legal.act
        if legal.status != "verified":
            line += f" {UNVERIFIED_MARK}"
        basis_lines.append(line)
    _para(document, "; ".join(basis_lines) if basis_lines else LEGAL_BASIS_MISSING_TEXT)

    document.add_heading("1.5. Перечень профессиональных компетенций", level=2)
    for competency in kit.framework.competencies:
        _bullets(document, [f"{competency.ref}. {competency.title}"])

    document.add_heading("1.6. Требования к слушателям", level=2)
    profile = kit.profile
    _para(document, profile.audience or AI_SECTION_MISSING)

    document.add_heading("1.7. Форма обучения", level=2)
    _para(document, FORM_LABELS.get(header.form, header.form))

    document.add_heading("1.8. Объём программы", level=2)
    _para(
        document,
        f"{hours['grand_total']} академических часов; контактная работа — {hours['contact']} ч; "
        f"самостоятельная работа — {hours['self_study']} ч; итоговая аттестация — {hours['final_attestation']} ч.",
    )
    calendar = kit.framework.calendar
    if calendar is not None:
        _para(document, f"Срок обучения: {calendar.days} дней (до {calendar.max_hours_per_day} ч в день).")

    document.add_heading("1.9. Выдаваемый документ", level=2)
    _para(document, header.document or "Удостоверение о повышении квалификации установленного образца.")


def _add_internship_section_2(document: DocxDocument, kit: KitV1) -> None:
    use_distance = _uses_distance(kit)
    header = _curriculum_header(use_distance)
    document.add_heading("2. СОДЕРЖАНИЕ ПРОГРАММЫ", level=1)

    document.add_heading("2.1. Учебный план", level=2)
    _add_items_table(document, header, _study_plan_items(kit), use_distance)

    document.add_heading("2.2. Учебно-тематический план", level=2)
    _add_items_table(document, header, _thematic_plan_items(kit), use_distance)

    document.add_heading("2.3. Календарный учебный график", level=2)
    calendar = kit.framework.calendar
    if calendar is None:
        _para(document, CALENDAR_MISSING_TEXT)
    else:
        _para(
            document,
            f"Срок обучения: {calendar.days} дней. Режим занятий: до {calendar.max_hours_per_day} часов в день.",
        )

    document.add_heading("2.4. Рабочая программа учебных дисциплин", level=2)
    if not kit.content.module_programs:
        _para(document, MODULE_PROGRAMS_MISSING_TEXT)
    for block in kit.content.module_programs:
        module = next((m for m in kit.framework.modules if m.ref == block.module_ref), None)
        heading = f"Раздел {module.number}. {module.title}" if module else block.ref
        document.add_heading(heading, level=3)
        text = _block_text(block)
        _para(document, text or AI_SECTION_MISSING)

    document.add_heading("2.5. Оценка качества освоения программы", level=2)
    for kind, label in ASSESSMENT_KIND_LABELS.items():
        group = [a for a in kit.content.assessments if a.kind == kind]
        if not group:
            continue
        document.add_heading(label, level=3)
        for assessment in group:
            _add_assessment_overview(document, kit, assessment)


def _build_dpp_internship_document(kit: KitV1) -> bytes:
    """Стажировка ПК — структура как acr_dpp_pk_staj_bsa_248h (без копирования ошибки итогов)."""
    document = Document()
    _prepare_styles(document)
    _add_internship_title_page(document, kit)
    _add_internship_section_1(document, kit)
    _add_internship_section_2(document, kit)
    _add_signatures(document, kit)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _build_dop_document(kit: KitV1) -> bytes:
    """Собрать .docx ДОП по структуре эталона АЦР (приказ № 629, пример 24 ч)."""
    document = Document()
    _prepare_styles(document)
    _add_dop_title_page(document, kit)
    _add_dop_explanatory_note(document, kit)
    _add_dop_part_1(document, kit)
    _add_dop_part_2(document, kit)
    _add_dop_part_3(document, kit)
    _add_signatures(document, kit)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _build_generated_document(kit: KitV1) -> bytes:
    """Собрать .docx программно (python-docx) по структуре шаблона ДПП ПК."""
    document = Document()
    _prepare_styles(document)
    _add_title_page(document, kit)
    _add_section_1(document, kit)
    _add_section_2(document, kit)
    _add_section_3(document, kit)
    _add_appendix_1(document, kit)
    _add_appendix_2(document, kit)
    _add_signatures(document, kit)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def export_docx_program(kit: KitV1, template_path: Path | None = None) -> bytes:
    """Экспортировать программу в .docx.

    ``template_path`` задан и существует — рендер docxtpl с контекстом
    :func:`_template_context` в песочнице ``jinja2.SandboxedEnvironment`` (шаблон
    не может дотянуться до приватных атрибутов и методов). Неизвестная метка
    шаблона приводит к ошибке Jinja — это сигнал, что шаблон и контекст разошлись.
    Иначе документ собирается программно по структуре шаблона ДПП ПК; итоги часов
    вычисляются из тем и совпадают с ``kit.grand_total()``, реквизиты приказа и
    подписи — пропуски.
    """
    if template_path is not None and template_path.exists():
        template = DocxTemplate(str(template_path))
        template.render(_template_context(kit), jinja_env=SandboxedEnvironment())
        buffer = io.BytesIO()
        template.save(buffer)
        return buffer.getvalue()
    if kit.program.kind == "dop":
        return _build_dop_document(kit)
    if kit.program.form == "internship":
        return _build_dpp_internship_document(kit)
    return _build_generated_document(kit)
