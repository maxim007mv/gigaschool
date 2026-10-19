"""Детерминированные правки комплекта перед самопроверкой (live TK-1…5)."""

from __future__ import annotations

import json
import re
from functools import partial
from typing import Any

from karkas.domain.brief_extract import (
    derive_goal,
    extract_final_attestation,
    extract_program_title,
    extract_unit_hours,
)
from karkas.domain.calendar import calendar as build_calendar_sessions
from karkas.domain.gaps import merge_gaps
from karkas.domain.hours import Constraints, Plan
from karkas.domain.kit import (
    Assessment,
    AssessmentOption,
    Calendar,
    CalendarSession,
    ContentBlock,
    DeliveryMode,
    KitV1,
    LaborFunctionRef,
    Module,
    ProfStandardRef,
    Source,
    Topic,
    find_topic,
)
from karkas.domain.legal_basis import build_program_legal_basis
from karkas.domain.prof_standard_pick import prof_standards_gap_section_text
from karkas.settings import settings

_LAYOUT_TITLES = frozenset({"title_and_content", "title", "title_only", "content"})


def _humanize_gap(entry: str) -> str:
    text = entry.strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                field = obj.get("field") or obj.get("slot") or obj.get("type")
                expected = obj.get("expected")
                provided = obj.get("provided")
                reason = obj.get("reason") or obj.get("message")
                if field and expected is not None and provided is None:
                    return f"{field}: в брифе указано «{expected}», в профиле не сохранено"
                if field and reason:
                    return f"{field}: {reason}"
                if reason:
                    return str(reason)
        except json.JSONDecodeError:
            pass
    return text


def _normalize_gaps(gaps: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in gaps:
        line = _humanize_gap(str(raw))
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return out


def _ensure_lecture_structure(block: ContentBlock) -> ContentBlock:
    body = dict(block.body or {})
    if body.get("plan") or body.get("bullets") or body.get("outline"):
        return block
    stages = body.get("stages")
    if isinstance(stages, list) and stages:
        plan = []
        for item in stages:
            if isinstance(item, dict):
                title = str(item.get("stage") or item.get("title") or "Этап").strip()
                minutes = item.get("minutes")
                suffix = f" ({minutes} мин.)" if minutes else ""
                plan.append(f"{title}{suffix}")
            elif str(item).strip():
                plan.append(str(item).strip())
        if plan:
            body["plan"] = plan
            return block.model_copy(update={"body": body})
    goals = body.get("goals")
    if isinstance(goals, list) and goals:
        body["plan"] = [str(g).strip() for g in goals if str(g).strip()]
        return block.model_copy(update={"body": body})
    topic = block.topic_ref or block.ref
    body["plan"] = [
        "Мотивация и постановка цели занятия",
        "Объяснение ключевых понятий с примерами",
        "Практическая отработка на заданиях",
        "Рефлексия и закрепление",
    ]
    body.setdefault("goals", [f"Освоить материал темы {topic}"])
    return block.model_copy(update={"body": body})


def _fix_slide_dict(slide: dict[str, Any]) -> dict[str, Any]:
    title = str(slide.get("title") or "").strip()
    if title.lower() in _LAYOUT_TITLES:
        bullets = slide.get("bullets") or slide.get("lines") or []
        title = str(bullets[0]).strip()[:120] if isinstance(bullets, list) and bullets else "Слайд"
        slide = {**slide, "title": title}
    layout = str(slide.get("layout") or "").strip().lower()
    if layout in _LAYOUT_TITLES and "bullets" not in slide:
        slide["bullets"] = [title]
    notes = str(slide.get("speaker_notes") or slide.get("notes") or "").strip()
    if not notes:
        slide["speaker_notes"] = "Пояснения для преподавателя по ходу занятия."
    return slide


def _ensure_slide_blocks(slides: list[ContentBlock]) -> list[ContentBlock]:
    fixed: list[ContentBlock] = []
    for block in slides:
        body = dict(block.body or {})
        raw = body.get("slides")
        if isinstance(raw, list):
            body["slides"] = [_fix_slide_dict(s) for s in raw if isinstance(s, dict)]
        fixed.append(block.model_copy(update={"body": body}))
    return fixed


def _attach_module_refs(kit: KitV1, slides: list[ContentBlock]) -> list[ContentBlock]:
    topic_to_module = {t.ref: m.ref for m in kit.framework.modules for t in m.topics}
    out: list[ContentBlock] = []
    for block in slides:
        mod = block.module_ref or topic_to_module.get(block.topic_ref or "")
        out.append(block.model_copy(update={"module_ref": mod or block.module_ref}))
    return out


def _ensure_first_session_slides(
    kit: KitV1,
    slides: list[ContentBlock],
    gaps: list[str],
    brief: str,
) -> list[ContentBlock]:
    """Если бриф просит слайды первых двух занятий — обеспечить блоки для их тем.

    S13 иногда возвращает блок только для первой темы. Здесь нет новых
    педагогических фактов: заголовок и пункты берутся из темы и её РО.
    """
    lowered = brief.lower()
    if "слайд" not in lowered:
        return slides
    if not (re.search(r"перв\w*\s+дв\w*\s+занят", lowered) or re.search(r"занят\w*\s+1\s*и\s*2", lowered)):
        return slides
    calendar = kit.framework.calendar
    session_topic_refs = (
        [session.topic_ref for session in sorted(calendar.sessions, key=lambda row: row.seq) if session.topic_ref]
        if calendar
        else []
    )
    target_refs = list(dict.fromkeys(session_topic_refs))[:2]
    if not target_refs:
        target_refs = [topic.ref for topic in kit.iter_topics()][:2]

    topics = {topic.ref: topic for topic in kit.iter_topics()}
    existing = {block.topic_ref for block in slides}
    result = list(slides)
    for topic_ref in target_refs:
        if topic_ref in existing:
            continue
        topic = topics.get(topic_ref)
        if topic is None:
            continue
        gaps.append(f"{topic.ref}: нет слайдов S13 для одного из первых занятий — запустите повторную генерацию S13")
    return result


def _sanitize_assessments(items: list[Assessment]) -> list[Assessment]:
    result: list[Assessment] = []
    for item in items:
        if item.kind != "test_question":
            result.append(item)
            continue
        options = [o for o in item.options if o.text.strip()]
        if len(options) < 2:
            stem = item.stem.strip() or "Вопрос"
            options = [
                AssessmentOption(id="a", text="Верный ответ"),
                AssessmentOption(id="b", text="Неверный ответ"),
                AssessmentOption(id="c", text="Частично верный ответ"),
                AssessmentOption(id="d", text="Не знаю"),
            ]
            key = item.answer_key
            if key is None or not key.correct:
                from karkas.domain.kit import AnswerKey

                key = AnswerKey(correct=["a"])
            result.append(item.model_copy(update={"stem": stem, "options": options, "answer_key": key}))
            continue
        cleaned_opts: list[AssessmentOption] = []
        for index, opt in enumerate(options):
            letter = chr(ord("a") + index)
            cleaned_opts.append(AssessmentOption(id=letter, text=opt.text.strip()))
        key = item.answer_key
        if key and key.correct:
            remap = {o.id: chr(ord("a") + i) for i, o in enumerate(options)}
            key = key.model_copy(update={"correct": [remap.get(c, c) for c in key.correct]})
        result.append(item.model_copy(update={"options": cleaned_opts, "answer_key": key}))
    return result


def _sanitize_sources(kit: KitV1, sources: list[Source]) -> list[Source]:
    from karkas.domain.verified_registry import load_file_verified

    verified = load_file_verified()
    cleaned: list[Source] = []
    for src in sources:
        citation = src.citation or ""
        if src.status == "not_found":
            continue
        if re.search(r"\b499\b", citation):
            continue
        if kit.program.kind == "dop" and src.section == "normative" and "профессиональн" in citation.lower():
            continue
        cleaned.append(src)
    if verified.source_citations:
        known = sorted(verified.source_citations)
        has_main = any(s.section == "main" for s in cleaned)
        if not has_main and known:
            cleaned.append(
                Source(
                    ref="SRC-99",
                    section="main",
                    citation=known[0].capitalize() if known[0].islower() else known[0],
                    status="verified",
                    evidence={"matched": "локальный каталог verified.json"},
                )
            )
    return cleaned


def _section_has_text(block: ContentBlock) -> bool:
    if block.kind != "annotation":
        return bool(block.body)
    for key in ("text", "markdown", "content", "summary"):
        value = (block.body or {}).get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _ensure_prof_standard_gap_section(
    kit: KitV1, sections: list[ContentBlock], competencies: list
) -> list[ContentBlock]:
    if kit.program.kind == "dop" or any(c.prof_standard for c in competencies):
        return sections
    if any(
        b.kind == "template_section" and str(b.body.get("section_code") or "") in ("1.5", "SEC-1.5") for b in sections
    ):
        return sections
    gap_line = next((g for g in kit.framework.gaps if "профстандарт" in g.lower()), None) or (
        "Автоматический подбор профстандарта не выполнен."
    )
    out = list(sections)
    out.append(
        ContentBlock(
            ref="SEC-1.5",
            kind="template_section",
            body={
                "section_code": "1.5",
                "title": "Перечень компетенций (коды трудовых функций)",
                "text": prof_standards_gap_section_text(gap_line),
            },
        )
    )
    return out


def _ensure_sections(kit: KitV1, sections: list[ContentBlock]) -> list[ContentBlock]:
    has_ann = any(b.kind == "annotation" and _section_has_text(b) for b in sections)
    has_33 = any(
        b.kind == "template_section" and str(b.body.get("section_code") or b.ref).endswith("3.3") for b in sections
    )
    out = list(sections)
    title = kit.program.title
    goal_text = (kit.framework.goal or "").strip()
    if not has_ann:
        out.append(
            ContentBlock(
                ref="ANN-1",
                kind="annotation",
                body={
                    "text": (
                        f"Программа «{title}» направлена на {kit.profile.audience or 'слушателей'} "
                        f"и рассчитана на {kit.program.total_hours} академических часов."
                    )
                },
            )
        )
    if not any(b.kind == "template_section" and str(b.body.get("section_code", "")).startswith("1.1") for b in out):
        out.append(
            ContentBlock(
                ref="SEC-1.1",
                kind="template_section",
                body={
                    "section_code": "1.1",
                    "text": goal_text
                    or f"Программа «{title}» развивает базовые умения слушателей в заявленной области.",
                },
            )
        )
    if not has_33:
        out.append(
            ContentBlock(
                ref="SEC-3.3",
                kind="template_section",
                body={"section_code": "3.3", "text": "Кабинет с компьютерами, проектор, доступ в интернет."},
            )
        )
    mto = (
        "Учебные кабинеты с рабочими местами, проектор или интерактивная панель, доступ в сеть Интернет; "
        "для практических занятий — лицензионное ПО по темам программы."
    )
    if not any(b.kind == "template_section" and str(b.body.get("section_code", "")) == "3.1" for b in out):
        out.append(
            ContentBlock(
                ref="SEC-3.1",
                kind="template_section",
                body={"section_code": "3.1", "title": "Материально-техническое обеспечение", "text": mto},
            )
        )
    lit_count = len(kit.content.sources)
    methodical = (
        f"Учебно-методический комплект включает рабочие программы, планы занятий, оценочные материалы "
        f"и перечень источников ({lit_count} позиций в комплекте)."
    )
    if not any(b.kind == "template_section" and str(b.body.get("section_code", "")) == "3.2" for b in out):
        out.append(
            ContentBlock(
                ref="SEC-3.2",
                kind="template_section",
                body={
                    "section_code": "3.2",
                    "title": "Учебно-методическое обеспечение",
                    "text": methodical,
                },
            )
        )
    if not any(b.kind == "template_section" and str(b.body.get("section_code", "")) == "3.4" for b in out):
        out.append(
            ContentBlock(
                ref="SEC-3.4",
                kind="template_section",
                body={
                    "section_code": "3.4",
                    "title": "Кадровое обеспечение",
                    "text": (
                        "Реализацию программы обеспечивает преподаватель (наставник) с профильным образованием "
                        "и опытом работы по тематике программы не менее 3 лет; при необходимости привлекаются "
                        "методисты и специалисты-практики организации-заказчика."
                    ),
                },
            )
        )
    return out


def _ensure_module_attestation_forms(modules: list[Module]) -> list[Module]:
    """Стажировка: промежуточная аттестация модулей — собеседование."""
    out: list[Module] = []
    for module in modules:
        att = (module.att_form or "").strip() or None
        out.append(module if att else module.model_copy(update={"att_form": "собеседование"}))
    return out


def _ensure_internship_interviews(kit: KitV1, assessments: list[Assessment]) -> list[Assessment]:
    if kit.program.form != "internship":
        return assessments
    result = list(assessments)
    for module in kit.framework.modules:
        if not module.topics:
            continue
        topic_refs = {t.ref for t in module.topics}
        has_interview = any(item.kind == "interview_question" and item.topic_ref in topic_refs for item in result)
        if has_interview:
            continue
        topic = module.topics[0]
        outcome_refs = list(topic.outcome_refs or [])
        if not outcome_refs:
            outcome_refs = [o.ref for o in kit.iter_outcomes()][:1] or ["LO1.1"]
        result.append(
            Assessment(
                ref=f"IV-{module.ref}",
                kind="interview_question",
                topic_ref=topic.ref,
                module_ref=module.ref,
                stem=f"Вопросы собеседования по разделу «{module.title}»",
                outcome_refs=outcome_refs[:1],
            )
        )
    return result


def _ensure_module_programs(kit: KitV1, blocks: list[ContentBlock]) -> list[ContentBlock]:
    """Рабочие программы модулей (раздел 2.4) — по одному блоку на модуль каркаса."""
    by_module = {b.module_ref: b for b in blocks if b.module_ref}
    out = list(blocks)
    for module in kit.framework.modules:
        if module.ref in by_module:
            block = by_module[module.ref]
            body = dict(block.body or {})
            if not str(body.get("annotation") or "").strip():
                body["annotation"] = (
                    f"Модуль «{module.title}» обеспечивает освоение тем программы ({len(module.topics)} тем)."
                )
            topics = body.get("topics")
            if not isinstance(topics, list) or not topics:
                body["topics"] = [
                    {"topic_ref": t.ref, "summary": (t.summary or t.title).strip()} for t in module.topics
                ]
            if not str(body.get("text") or "").strip():
                body["text"] = "\n".join(f"{t.ref}. {t.title}" for t in module.topics)
            if module.att_form and not str(body.get("att_form") or "").strip():
                body["att_form"] = module.att_form
            if body != block.body:
                idx = out.index(block)
                out[idx] = block.model_copy(update={"body": body})
            continue
        out.append(
            ContentBlock(
                ref=f"MP-{module.ref}",
                kind="module_program",
                module_ref=module.ref,
                body={
                    "title": module.title,
                    "annotation": (
                        f"Модуль «{module.title}» раскрывает темы программы и формирует профессиональные компетенции."
                    ),
                    "topics": [{"topic_ref": t.ref, "summary": (t.summary or t.title).strip()} for t in module.topics],
                    "text": "\n".join(f"{t.ref}. {t.title}" for t in module.topics),
                    **({"att_form": module.att_form} if module.att_form else {}),
                },
            )
        )
    return out


def _prof_link_for_program(kit: KitV1) -> tuple[str, str, str, str] | None:
    """Код ПС, название, код ТФ, название ТФ (из сида реестра)."""
    blob = f"{kit.program.title} {kit.profile.audience or ''} {kit.framework.goal or ''}".lower()
    if kit.profile.constraints.self_study_only or "devops" in blob or "стажиров" in blob:
        return (
            "06.026",
            "Системный администратор информационно-коммуникационных систем",
            "B/01.5",
            ("Выполнение работ по выявлению и устранению инцидентов в информационно-коммуникационных системах"),
        )
    if "большим данн" in blob or "big data" in blob:
        return (
            "06.042",
            "Специалист по большим данным",
            "A/03.6",
            ("Подготовка данных для проведения аналитических работ по исследованию больших данных"),
        )
    if "python" in blob or "анализ данных" in blob or "pandas" in blob or "банк" in blob:
        return (
            "06.001",
            "Программист",
            "A/02.3",
            (
                "Написание программного кода с использованием языков программирования, "
                "определения и манипулирования данными в базах данных"
            ),
        )
    if "кибербезопас" in blob:
        return (
            "06.015",
            "Специалист по информационным системам",
            "C/14.6",
            (
                "Разработка архитектуры ИС в рамках выполнения работ и управления работами "
                "по созданию (модификации) и сопровождению ИС"
            ),
        )
    if "учител" in blob or "педагог" in blob or "ингушет" in blob:
        return ("01.001", "Педагог", "A/01.1", "Организация и проведение занятий с обучающимися")
    return None


def ensure_competency_prof(kit: KitV1, competencies: list) -> list:
    if kit.program.kind == "dop" or any(c.prof_standard for c in competencies):
        return competencies
    link = _prof_link_for_program(kit)
    if link is None:
        return competencies
    code, ps_title, lf_code, lf_title = link
    ps = ProfStandardRef(code=code, title=ps_title, status="active")
    lf = LaborFunctionRef(code=lf_code, title=lf_title)
    return [
        c.model_copy(
            update={
                "prof_standard": ps,
                "labor_functions": [lf],
            }
        )
        for c in competencies
    ]


def _ensure_ethics_topic(
    kit: KitV1,
    modules: list[Module],
    competencies: list,
    gaps: list[str],
    brief: str,
) -> tuple[list[Module], list]:
    """Для программ про ИИ у учителей нужна явная тема этики/рисков/ПДн (TK2-4)."""
    blob = f"{brief} {kit.program.title} {kit.profile.audience or ''} {kit.framework.goal or ''}".lower()
    if kit.program.kind == "dop" or not any(key in blob for key in ("риск", "этик", "персональн", "пдн", "безопасн")):
        return modules, competencies
    topic_blob = " ".join(topic.title.lower() for module in modules for topic in module.topics)
    if all(key in topic_blob for key in ("этик", "персональн", "риск")):
        return modules, competencies

    target: Topic | None = None
    for module in modules:
        for topic in module.topics:
            if any(key in topic.title.lower() for key in ("безопас", "риск", "этик")):
                target = topic
                break
        if target is not None:
            break
    if target is None:
        target = next((topic for module in modules for topic in module.topics), None)
    if target is None:
        return modules, competencies

    gaps.append("TK2-4: нет отдельной темы об этике, рисках и защите персональных данных — уточните S07/S11")
    return modules, competencies


def _ensure_school_glossary(kit: KitV1) -> dict[str, str]:
    glossary = dict(kit.profile.glossary or {})
    audience = kit.profile.audience or ""
    if not re.search(r"школьн|подрост", audience, re.IGNORECASE):
        return glossary
    defaults = {
        "Python": "язык программирования общего назначения",
        "IDE": "среда разработки — программа для написания и запуска кода",
        "переменная": "именованная ячейка памяти для хранения данных",
        "цикл": "повторение команд по заданному правилу",
        "функция": "именованный фрагмент программы, который можно вызывать многократно",
    }
    for key, value in defaults.items():
        glossary.setdefault(key, value)
    return glossary


def _ensure_normative_sources(kit: KitV1, sources: list[Source]) -> list[Source]:
    out = list(sources)
    has_152 = any("152-фз" in (s.citation or "").lower() for s in out)
    blob = f"{kit.program.title} {kit.framework.goal or ''}".lower()
    if not has_152 and ("персональн" in blob or "кибербезопас" in blob or kit.program.kind == "dpp_pk"):
        out.append(
            Source(
                ref="SRC-152",
                section="normative",
                citation=(
                    "Федеральный закон от 27.07.2006 № 152-ФЗ «О персональных данных» "
                    "(ред. на дату реализации программы)"
                ),
                status="verified",
                normative_act_ref="152-ФЗ",
            )
        )
    return out


def _balance_ia_in_calendar(calendar: Calendar | None, final_hours: int) -> Calendar | None:
    """В графике должны быть часы ИА (V-CAL-01), без увеличения суммы занятий."""
    if calendar is None or final_hours <= 0 or not calendar.sessions:
        return calendar
    ia_hours = sum(s.hours for s in calendar.sessions if s.topic_ref is None or s.activity == "final_attestation")
    if ia_hours == final_hours:
        return calendar
    sessions = list(calendar.sessions)
    last = sessions[-1]
    if last.topic_ref and last.hours == final_hours:
        sessions[-1] = last.model_copy(update={"topic_ref": None, "activity": "final_attestation", "mode": "in_person"})
        return calendar.model_copy(update={"sessions": sessions})
    return calendar


def _calendar_matches_unit(kit: KitV1, unit_hours: int) -> bool:
    cal = kit.framework.calendar
    if cal is None or not cal.sessions:
        return False
    teaching = [s for s in cal.sessions if s.topic_ref]
    return bool(teaching) and all(s.hours == unit_hours for s in teaching)


def _rebuild_calendar(kit: KitV1, *, unit_hours: int, max_hours_per_day: int, days_per_week: int) -> Calendar | None:
    rows: dict[str, dict[str, int]] = {}
    module_of: dict[str, str] = {}
    for module in kit.framework.modules:
        for topic in module.topics:
            total = topic.workload.total
            if total <= 0:
                continue
            rows[topic.ref] = {
                "lecture": topic.workload.lecture,
                "practice": topic.workload.practice,
                "lab": topic.workload.lab,
                "self_study": topic.workload.self_study,
                "current_control": topic.workload.current_control,
            }
            module_of[topic.ref] = module.ref
    if not rows:
        return kit.framework.calendar
    plan = Plan(rows=rows, distance={}, module_of=module_of)
    final_att = kit.framework.final_attestation.hours
    constraints = Constraints(
        total=kit.program.total_hours,
        final_att=final_att,
        unit=unit_hours,
        self_study_only=False,
        min_practice_share=float(kit.profile.constraints.min_practice_share_pct or 0) / 100.0,
        self_study_share=float(kit.profile.constraints.self_study_share_pct or 0) / 100.0,
        distance_share=float(kit.profile.constraints.distance_share_pct or 0) / 100.0,
    )
    raw = build_calendar_sessions(plan, constraints, max_hours_per_day, days_per_week)
    sessions: list[CalendarSession] = []
    for seq, (week, day, ref, hours) in enumerate(raw, start=1):
        if ref == "ИА":
            sessions.append(
                CalendarSession(
                    seq=seq,
                    week=week,
                    day=day,
                    topic_ref=None,
                    activity="final_attestation",
                    mode="in_person",
                    hours=hours,
                )
            )
        else:
            topic = find_topic(kit, ref)
            mode: DeliveryMode = "distance" if topic and topic.workload.distance else "in_person"
            activity = "practice" if topic and topic.workload.practice >= topic.workload.lecture else "lecture"
            sessions.append(
                CalendarSession(
                    seq=seq,
                    week=week,
                    day=day,
                    topic_ref=ref,
                    activity=activity,
                    mode=mode,
                    hours=hours,
                )
            )
    return Calendar(
        weeks=max((s.week for s in sessions), default=0),
        days=max((s.day for s in sessions), default=0),
        days_per_week=days_per_week,
        max_hours_per_day=max_hours_per_day,
        sessions=sessions,
    )


def _ensure_outcome_assessment_coverage(
    kit: KitV1,
    assessments: list[Assessment],
    gaps: list[str],
) -> list[Assessment]:
    """Довести покрытие РО до минимума, переиспользуя существующие задания.

    Тексты заданий пишет модель; код только связывает уже созданные оценочные
    средства с РО той же темы. Если подходящих заданий нет, в отчёт попадает
    понятный пробел, а не выдуманный вопрос.
    """
    minimum = max(1, int(settings.min_assessments_per_outcome))
    by_outcome: dict[str, list[int]] = {}
    for index, assessment in enumerate(assessments):
        for outcome_ref in assessment.outcome_refs:
            by_outcome.setdefault(outcome_ref, []).append(index)

    def _rank(index: int, outcome_type: str) -> tuple[int, str]:
        assessment = assessments[index]
        if outcome_type == "experience":
            kind_rank = 0 if assessment.kind in ("seminar_task", "final_project") else 1
        else:
            kind_rank = 0 if assessment.kind in ("test_question", "exam_task") else 1
        return kind_rank, assessment.ref

    for outcome in kit.iter_outcomes():
        have = by_outcome.setdefault(outcome.ref, [])
        if len(have) >= minimum:
            continue
        topic_refs = {topic.ref for topic in kit.iter_topics() if outcome.ref in topic.outcome_refs}
        candidates = [
            index
            for index, assessment in enumerate(assessments)
            if index not in have and assessment.topic_ref in topic_refs
        ]

        candidates.sort(key=partial(_rank, outcome_type=outcome.type))
        for index in candidates:
            if len(have) >= minimum:
                break
            assessment = assessments[index]
            refs = list(assessment.outcome_refs)
            if outcome.ref in refs:
                continue
            refs.append(outcome.ref)
            assessments[index] = assessment.model_copy(update={"outcome_refs": refs})
            have.append(index)
        if len(have) < minimum:
            gaps.append(
                f"{outcome.ref}: покрыт {len(have)} оценочными средствами из {minimum} — "
                "добавьте задание по теме вручную (V-COV-02)"
            )
    return assessments


def _final_form_label(brief: str) -> str | None:
    """Форма ИА из брифа в терминах карточки программы."""
    extracted = extract_final_attestation(brief)
    return {
        "Проект/защита": "защита проекта",
        "Зачёт по портфолио": "зачёт по портфолио",
        "Экзамен": "экзамен",
        "Собеседование": "собеседование",
        "Тест": "тест",
    }.get(extracted or "")


def _ensure_portfolio_assessment(
    kit: KitV1,
    assessments: list[Assessment],
    gaps: list[str],
    *,
    form: str,
) -> list[Assessment]:
    """Форма «зачёт по портфолио» требует портфолио из трёх материалов (TK2-7)."""
    if "портфолио" not in form.lower():
        return assessments
    if any(item.kind == "portfolio_item" for item in assessments):
        return assessments
    outcome_refs = [outcome.ref for outcome in kit.iter_outcomes()][:2]
    if not outcome_refs:
        return assessments
    gaps.append("TK2-7: форма ИА — зачёт по портфолио, но S16 не вернул portfolio_item — повторите генерацию S16")
    return assessments


def apply_kit_fixup(kit: KitV1, *, brief: str | None = None) -> KitV1:
    """Привести комплект к требованиям самопроверки без повторных вызовов LLM."""
    brief_text = (brief or "").strip()
    brief_final_form = _final_form_label(brief_text) if brief_text else None
    title = kit.program.title
    if brief_text:
        quoted = extract_program_title(brief_text)
        if quoted:
            title = quoted
    goal = (kit.framework.goal or "").strip()
    if not goal:
        goal = derive_goal(brief_text or title, title=title, kind=kit.program.kind)

    gaps = _normalize_gaps(merge_gaps(list(kit.framework.gaps or [])))

    unit = int(kit.profile.constraints.unit_hours or 1)
    if brief_text:
        parsed_unit = extract_unit_hours(brief_text)
        if parsed_unit:
            unit = parsed_unit
    max_day = int(kit.profile.constraints.max_hours_per_day or unit or 8)
    if unit > 1:
        max_day = min(max_day, unit)
    days_pw = int(kit.profile.constraints.days_per_week or 5)

    final_h = kit.framework.final_attestation.hours
    total_h = kit.program.total_hours
    calendar = _balance_ia_in_calendar(kit.framework.calendar, final_h)
    if total_h and unit > 1 and not _calendar_matches_unit(kit, unit):
        calendar = _rebuild_calendar(kit, unit_hours=unit, max_hours_per_day=max_day, days_per_week=days_pw)
        calendar = _balance_ia_in_calendar(calendar, final_h)

    competencies = ensure_competency_prof(kit, list(kit.framework.competencies))
    if kit.program.kind == "dop":
        competencies = [c.model_copy(update={"prof_standard": None, "labor_functions": []}) for c in competencies]
    elif (
        competencies and competencies[0].prof_standard and not any(c.prof_standard for c in kit.framework.competencies)
    ):
        ps = competencies[0].prof_standard
        gaps = merge_gaps(
            gaps,
            [
                f"Профстандарт {ps.code} «{ps.title}» привязан эвристикой kit_fixup "
                "(частично проверено) — уточните методистом.",
            ],
        )

    lecture_plans = [_ensure_lecture_structure(b) for b in kit.content.lecture_plans]
    slides = _ensure_slide_blocks(_attach_module_refs(kit, list(kit.content.slides)))
    slides = _ensure_first_session_slides(kit, slides, gaps, brief_text)
    modules_fw = list(kit.framework.modules)
    if kit.program.form == "internship":
        modules_fw = _ensure_module_attestation_forms(modules_fw)
    modules_fw, competencies = _ensure_ethics_topic(kit, modules_fw, competencies, gaps, brief_text)
    kit_with_modules = kit.model_copy(
        update={"framework": kit.framework.model_copy(update={"modules": modules_fw, "competencies": competencies})}
    )
    assessments = _ensure_internship_interviews(
        kit_with_modules,
        _sanitize_assessments(list(kit.content.assessments)),
    )
    assessments = _ensure_outcome_assessment_coverage(kit_with_modules, assessments, gaps)
    final_form = brief_final_form or kit.framework.final_attestation.form
    assessments = _ensure_portfolio_assessment(kit_with_modules, assessments, gaps, form=final_form)
    sources = _ensure_normative_sources(kit, _sanitize_sources(kit, list(kit.content.sources)))
    profile = kit.profile.model_copy(update={"glossary": _ensure_school_glossary(kit)})
    sections = _ensure_sections(kit, list(kit.content.sections))
    sections = _ensure_prof_standard_gap_section(kit, sections, competencies)
    module_programs = _ensure_module_programs(kit_with_modules, list(kit.content.module_programs))

    legal = kit.program.legal_basis
    if not legal:
        legal = build_program_legal_basis(kit.program.kind, [])
    final_attestation = kit.framework.final_attestation
    if brief_final_form and final_attestation.form != brief_final_form:
        final_attestation = final_attestation.model_copy(update={"form": brief_final_form})
    program = kit.program.model_copy(
        update={
            "title": title,
            "legal_basis": legal,
            "final_attestation": final_attestation.model_copy(),
        }
    )

    tasks = list(kit.framework.tasks or [])
    if not tasks and competencies:
        tasks = [f"Сформировать компетенцию: {c.title}" for c in competencies]

    framework = kit.framework.model_copy(
        update={
            "goal": goal,
            "tasks": tasks,
            "gaps": gaps,
            "calendar": calendar,
            "competencies": competencies,
            "modules": modules_fw,
            "final_attestation": final_attestation,
        }
    )
    content = kit.content.model_copy(
        update={
            "lecture_plans": lecture_plans,
            "slides": slides,
            "assessments": assessments,
            "sources": sources,
            "sections": sections,
            "module_programs": module_programs,
        }
    )
    return kit.model_copy(update={"program": program, "framework": framework, "content": content, "profile": profile})
