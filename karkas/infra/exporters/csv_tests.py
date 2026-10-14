"""karkas.infra.exporters.csv_tests — выгрузка тестов в CSV (Д4 §5.12).

Формат: UTF-8, разделитель ``;``, кавычки — только при необходимости (``csv``).
Заголовок: ``ref;модуль;тема;РО;тип;вопрос;вариант_1..вариант_N;правильные;пояснение``
(число колонок вариантов — по самому широкому вопросу, минимум одна).
Значения:

- ``модуль`` — «М2 Название» (номер модуля обязателен для навигации методиста);
- ``тема`` — название темы; ``РО`` — коды результатов обучения через запятую;
- ``тип`` — машинный ``qtype`` KitV1 (``single``, ``multiple``, ``truefalse``, ``short``…);
- ``правильные`` — тексты верных вариантов через `` | `` (верные id, для которых нет
  варианта, остаются как есть — например, short-ответ);
- строки — только тестовые вопросы (``kind == "test_question"``), в порядке
  ``content.assessments``; при отсутствии вопросов возвращается только заголовок
  (функция не падает).
"""

from __future__ import annotations

import csv
import io

from karkas.domain.kit import Assessment, KitV1, Module, Topic

CSV_DELIMITER = ";"
BASE_COLUMNS = ("ref", "модуль", "тема", "РО", "тип", "вопрос")
OPTION_COLUMN_TEMPLATE = "вариант_{number}"
TAIL_COLUMNS = ("правильные", "пояснение")
CORRECT_SEPARATOR = " | "
OUTCOME_SEPARATOR = ", "
MIN_OPTION_COLUMNS = 1
LINE_TERMINATOR = "\r\n"


def _module_for_assessment(kit: KitV1, assessment: Assessment) -> Module | None:
    """Модуль вопроса: по ``module_ref``, иначе — модуль темы ``topic_ref``."""
    if assessment.module_ref:
        found = next((m for m in kit.framework.modules if m.ref == assessment.module_ref), None)
        if found is not None:
            return found
    if assessment.topic_ref:
        return next(
            (m for m in kit.framework.modules if any(t.ref == assessment.topic_ref for t in m.topics)),
            None,
        )
    return None


def _topic_for_assessment(kit: KitV1, assessment: Assessment) -> Topic | None:
    if not assessment.topic_ref:
        return None
    return next((t for t in kit.iter_topics() if t.ref == assessment.topic_ref), None)


def _module_label(module: Module | None) -> str:
    if module is None:
        return ""
    return f"М{module.number} {module.title}"


def _correct_texts(assessment: Assessment) -> list[str]:
    """Тексты верных ответов: из вариантов по id, иначе — сам ответ (short)."""
    option_texts = {option.id: option.text for option in assessment.options}
    correct = assessment.answer_key.correct if assessment.answer_key else []
    return [option_texts.get(answer, answer) for answer in correct]


def _explanation(assessment: Assessment) -> str:
    if assessment.answer_key and assessment.answer_key.explanation:
        return assessment.answer_key.explanation
    return ""


def _row(assessment: Assessment, kit: KitV1, option_columns: int) -> list[str]:
    module = _module_for_assessment(kit, assessment)
    topic = _topic_for_assessment(kit, assessment)
    row = [
        assessment.ref,
        _module_label(module),
        topic.title if topic else "",
        OUTCOME_SEPARATOR.join(assessment.outcome_refs),
        assessment.qtype or "",
        assessment.stem,
    ]
    row.extend(option.text for option in assessment.options)
    row.extend([""] * (option_columns - len(assessment.options)))
    row.append(CORRECT_SEPARATOR.join(_correct_texts(assessment)))
    row.append(_explanation(assessment))
    return row


def export_tests_csv(kit: KitV1) -> str:
    """Сериализовать тестовые вопросы комплекта в CSV (``;``, UTF-8, строки вопросов).

    Число колонок ``вариант_N`` определяется самым широким вопросом. Значения с ``;``,
    кавычками и переводами строк экранируются стандартным ``csv.writer``.
    """
    questions = [a for a in kit.content.assessments if a.kind == "test_question"]
    option_columns = max((len(a.options) for a in questions), default=0) or MIN_OPTION_COLUMNS
    header = (
        list(BASE_COLUMNS)
        + [OPTION_COLUMN_TEMPLATE.format(number=index + 1) for index in range(option_columns)]
        + list(TAIL_COLUMNS)
    )
    buffer = io.StringIO()
    writer = csv.writer(
        buffer,
        delimiter=CSV_DELIMITER,
        quoting=csv.QUOTE_MINIMAL,
        lineterminator=LINE_TERMINATOR,
    )
    writer.writerow(header)
    for assessment in questions:
        writer.writerow(_row(assessment, kit, option_columns))
    return buffer.getvalue()
