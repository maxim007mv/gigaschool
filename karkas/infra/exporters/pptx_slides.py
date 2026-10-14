"""karkas.infra.exporters.pptx_slides — выгрузка слайдов в .pptx (Д4 §5.12).

По каждому модулю формируется: титульный слайд темы, цели (РО тем модуля),
содержательные слайды из ``content.slides`` (не более ``MAX_CONTENT_SLIDES``),
практика (задания семинаров) и вопросы для самопроверки (тестовые вопросы и
вопросы собеседования). Заметки докладчика наполняются из ``content.lecture_plans``
модуля.

Выбор модулей: ``module_refs`` — явный список; по умолчанию — модули, для которых
есть slides-блоки. Если таких модулей нет (или данные о слайдах отсутствуют),
возвращается минимальный корректный .pptx с титульным слайдом программы —
функция не падает.
"""

from __future__ import annotations

import io
from typing import Any, Iterable, Sequence

from pptx import Presentation
from pptx.presentation import Presentation as PptxPresentation
from pptx.util import Inches

from karkas.domain.kit import Assessment, ContentBlock, KitV1, Module, Topic, find_outcome

LAYOUT_TITLE = 0
LAYOUT_TITLE_CONTENT = 1
BODY_PLACEHOLDER_IDX = 1
MAX_CONTENT_SLIDES = 12
TEXTBOX_POSITION = (Inches(1), Inches(2), Inches(8), Inches(4))
KIND_LABELS: dict[str, str] = {
    "dpp_pk": "Дополнительная профессиональная программа повышения квалификации",
    "dop": "Дополнительная общеразвивающая программа",
}
PRACTICE_KINDS = frozenset({"seminar_task"})
QUESTION_KINDS = frozenset({"test_question", "interview_question"})
GOALS_SLIDE_TITLE = "Цели и результаты обучения"
PRACTICE_SLIDE_TITLE = "Практика"
QUESTIONS_SLIDE_TITLE = "Вопросы для самопроверки"
BODY_LINE_KEYS = ("bullets", "lines", "items")
BODY_TEXT_KEYS = ("text", "markdown", "content")


def _selected_modules(kit: KitV1, module_refs: list[str] | None) -> list[Module]:
    """Модули для выгрузки: явный список или модули со slides-блоками."""
    if module_refs is None:
        refs = {block.module_ref for block in kit.content.slides if block.module_ref}
    else:
        refs = set(module_refs)
    return [module for module in kit.framework.modules if module.ref in refs]


def _lines(value: Any) -> list[str]:
    """Список строк из значения блока (list или многострочная строка)."""
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    return []


def _body_lines(body: dict[str, Any]) -> list[str]:
    """Содержимое блока: сначала списки, затем текстовые поля."""
    for key in BODY_LINE_KEYS:
        lines = _lines(body.get(key))
        if lines:
            return lines
    for key in BODY_TEXT_KEYS:
        lines = _lines(body.get(key))
        if lines:
            return lines
    return []


def _block_title(block: ContentBlock, topics: dict[str, Topic]) -> str:
    """Заголовок слайда: тема блока, затем title из body, затем ref."""
    topic = topics.get(block.topic_ref) if block.topic_ref else None
    body_title = block.body.get("title")
    if topic is not None:
        if isinstance(body_title, str) and body_title.strip():
            if topic.title in body_title:
                return body_title.strip()
            return f"{topic.title}. {body_title.strip()}"
        return topic.title
    if isinstance(body_title, str) and body_title.strip():
        return body_title.strip()
    return block.ref


def _slide_entries(
    blocks: Iterable[ContentBlock], topics: dict[str, Topic]
) -> list[tuple[str, list[str]]]:
    """Содержательные слайды из slides-блоков: (заголовок, строки)."""
    entries: list[tuple[str, list[str]]] = []
    for block in blocks:
        fallback_title = _block_title(block, topics)
        raw_slides = block.body.get("slides")
        if isinstance(raw_slides, list) and raw_slides:
            for item in raw_slides:
                if isinstance(item, dict):
                    title = str(item.get("title") or fallback_title)
                    bullets = (
                        _lines(item.get("bullets"))
                        or _lines(item.get("lines"))
                        or _lines(item.get("text"))
                    )
                else:
                    title, bullets = fallback_title, _lines(item)
                entries.append((title, bullets))
            continue
        bullets = _body_lines(block.body)
        entries.append((fallback_title, bullets))
    return entries


def _assessment_in_module(kit: KitV1, assessment: Assessment, module: Module) -> bool:
    if assessment.module_ref:
        return assessment.module_ref == module.ref
    if assessment.topic_ref:
        return any(topic.ref == assessment.topic_ref for topic in module.topics)
    return False


def _assessment_lines(kit: KitV1, module: Module, kinds: frozenset[str]) -> list[str]:
    """Формулировки оценочных средств модуля заданных видов."""
    return [
        assessment.stem
        for assessment in kit.content.assessments
        if assessment.kind in kinds and _assessment_in_module(kit, assessment, module)
    ]


def _outcome_lines(kit: KitV1, module: Module) -> list[str]:
    """Строки целей: РО тем модуля; если РО нет — названия тем."""
    lines: list[str] = []
    seen: set[str] = set()
    for topic in module.topics:
        for ref in topic.outcome_refs:
            if ref in seen:
                continue
            seen.add(ref)
            outcome = find_outcome(kit, ref)
            lines.append(f"{ref} — {outcome.text}" if outcome is not None else ref)
    if not lines:
        lines = [topic.title for topic in module.topics]
    return lines


def _lecture_notes(kit: KitV1, module: Module) -> str:
    """Заметки докладчика из планов лекций модуля."""
    lines: list[str] = []
    for block in kit.content.lecture_plans:
        if block.module_ref == module.ref:
            lines.extend(_body_lines(block.body))
    return "\n".join(lines)


def _add_title_slide(
    presentation: PptxPresentation, title: str, subtitle: str, notes: str | None = None
) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[LAYOUT_TITLE])
    if slide.shapes.title is not None:
        slide.shapes.title.text = title
    if len(slide.placeholders) > 1 and subtitle:
        slide.placeholders[1].text = subtitle
    if notes:
        slide.notes_slide.notes_text_frame.text = notes


def _add_content_slide(
    presentation: PptxPresentation,
    title: str,
    bullets: Sequence[str],
    notes: str | None = None,
) -> None:
    slide = presentation.slides.add_slide(presentation.slide_layouts[LAYOUT_TITLE_CONTENT])
    if slide.shapes.title is not None:
        slide.shapes.title.text = title
    body = next(
        (shape for shape in slide.placeholders if shape.placeholder_format.idx == BODY_PLACEHOLDER_IDX),
        None,
    )
    if body is not None:
        frame = body.text_frame
        for index, bullet in enumerate(bullets):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.text = bullet
    elif bullets:
        textbox = slide.shapes.add_textbox(*TEXTBOX_POSITION)
        frame = textbox.text_frame
        for index, bullet in enumerate(bullets):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.text = bullet
    if notes:
        slide.notes_slide.notes_text_frame.text = notes


def _add_minimal_slide(presentation: PptxPresentation, kit: KitV1) -> None:
    """Минимальный титульный слайд программы (когда слайдов модулей нет)."""
    kind = KIND_LABELS.get(kit.program.kind, kit.program.kind)
    subtitle = f"{kind}. {kit.program.total_hours} акад. ч"
    if kit.framework.goal:
        subtitle += f"\nЦель: {kit.framework.goal}"
    _add_title_slide(presentation, kit.program.title, subtitle)


def export_pptx_slides(kit: KitV1, module_refs: list[str] | None = None) -> bytes:
    """Экспортировать слайды в .pptx (python-pptx, стандартный мастер).

    ``module_refs`` — выгружать только указанные модули (ref вида ``M2``).
    По умолчанию берутся модули, у которых есть slides-блоки; если таких нет —
    минимальный титульный слайд программы. Заметки докладчика — из ``lecture_plans``.
    """
    presentation = Presentation()
    modules = _selected_modules(kit, module_refs)
    topics = {topic.ref: topic for topic in kit.iter_topics()}
    if not modules:
        _add_minimal_slide(presentation, kit)
    for module in modules:
        notes = _lecture_notes(kit, module)
        subtitle = f"{kit.program.title}\n{module.workload.total} акад. ч"
        _add_title_slide(presentation, f"М{module.number} {module.title}", subtitle, notes)
        goals = _outcome_lines(kit, module)
        if goals:
            _add_content_slide(presentation, GOALS_SLIDE_TITLE, goals)
        blocks = [block for block in kit.content.slides if block.module_ref == module.ref]
        entries = _slide_entries(blocks, topics)[:MAX_CONTENT_SLIDES]
        for title, bullets in entries:
            _add_content_slide(presentation, title, bullets)
        practice = _assessment_lines(kit, module, PRACTICE_KINDS)
        if practice:
            _add_content_slide(presentation, PRACTICE_SLIDE_TITLE, practice)
        questions = _assessment_lines(kit, module, QUESTION_KINDS)
        if questions:
            _add_content_slide(presentation, QUESTIONS_SLIDE_TITLE, questions)
    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()
