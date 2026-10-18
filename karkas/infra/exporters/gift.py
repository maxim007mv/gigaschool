"""karkas.infra.exporters.gift — выгрузка тестов в формате Moodle GIFT (Д4 §5.12).

Правила сериализации:
- категория = модуль: ``$CATEGORY: $course$/М2 Название модуля`` (иерархия по номерам
  модулей; вопросы без модуля уходят в категорию ``$course$/Без модуля``);
- заголовок вопроса: ``::Q-014 [LO2.2]::текст вопроса{...}`` — ref и теги РО;
- ``single`` — один ``=``, ``multiple`` — несколько ``=``, неверные — ``~``;
- ``truefalse`` — ``{TRUE#…}`` или ``{FALSE#…}``;
- ``short`` — ``{=ответ}`` (несколько принимаемых ответов — через пробел),
  ``open`` — ``{}`` (проверка вручную);
- ``matching`` — блок ``=элемент -> соответствие``, если варианты заданы парами,
  иначе открытый вопрос с комментарием; ``order`` — открытый вопрос с
  комментарием «верный порядок» (в GIFT нет типа упорядочивания);
- пояснение из ``answer_key.explanation`` добавляется после ``#``;
- спецсимволы ``\\ ~ = # { } :`` экранируются обратным слэшем;
- задания (``seminar_task``, ``interview_question``, ``final_project``, ``exam_task``,
  ``portfolio_item``) в GIFT не выгружаются;
- если тестовых вопросов нет, возвращается корректный файл с комментарием
  ``// Тестовых вопросов в комплекте нет`` (функция не падает).
"""

from __future__ import annotations

from karkas.domain.kit import Assessment, KitV1, Module

GIFT_SPECIAL_CHARS = "\\~=#{}:"
"""Спецсимволы GIFT, экранируемые обратным слэшем (Д4 §5.12)."""

TRUE_LITERALS = frozenset({"true", "t", "1", "верно", "истина", "да", "yes"})
FALSE_LITERALS = frozenset({"false", "f", "0", "неверно", "ложь", "нет", "no"})
MATCHING_SEPARATORS = ("->", "→")
NO_QUESTIONS_COMMENT = "// Тестовых вопросов в комплекте нет"
UNASSIGNED_CATEGORY = "$course$/Без модуля"


def escape_gift(text: str) -> str:
    """Экранировать спецсимволы GIFT (``\\ ~ = # { } :``) обратным слэшем."""
    escaped: list[str] = []
    for char in text:
        if char in GIFT_SPECIAL_CHARS:
            escaped.append("\\")
        escaped.append(char)
    return "".join(escaped)


def _single_line(text: str) -> str:
    """Схлопнуть переводы строк и повторные пробелы: заголовок GIFT — одна строка."""
    return " ".join(text.split())


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


def _category(module: Module | None) -> str:
    """Категория GIFT: модуль с номером; вопросы без модуля — отдельная категория."""
    if module is None:
        return UNASSIGNED_CATEGORY
    return f"$course$/М{module.number} {_single_line(module.title)}"


def _correct_ids(assessment: Assessment) -> list[str]:
    """Идентификаторы верных вариантов (пусто, если ключа нет)."""
    return list(assessment.answer_key.correct) if assessment.answer_key else []


def _option_texts(assessment: Assessment) -> dict[str, str]:
    return {option.id: option.text for option in assessment.options}


def _answer_text(assessment: Assessment, answer: str) -> str:
    """Текст ответа: из варианта по id, иначе сам id (для short без вариантов)."""
    return _option_texts(assessment).get(answer, answer)


def _feedback(assessment: Assessment) -> str:
    """Фидбек ``#пояснение`` из ``answer_key.explanation`` (пусто, если пояснения нет)."""
    explanation = assessment.answer_key.explanation if assessment.answer_key else None
    if not explanation:
        return ""
    return f"#{escape_gift(_single_line(explanation))}"


def _explanation_comment(assessment: Assessment) -> str | None:
    """Пояснение отдельной строкой-комментарием (когда ``#`` привязать некуда)."""
    explanation = assessment.answer_key.explanation if assessment.answer_key else None
    if not explanation:
        return None
    return f"// Пояснение: {_single_line(explanation)}"


def _truefalse_literal(assessment: Assessment) -> str:
    """Литерал ``TRUE``/``FALSE``: по тексту верного варианта, затем по его позиции."""
    option_texts = _option_texts(assessment)
    correct = _correct_ids(assessment)
    for answer in correct:
        word = option_texts.get(answer, answer).strip().lower()
        if word in TRUE_LITERALS:
            return "TRUE"
        if word in FALSE_LITERALS:
            return "FALSE"
    option_ids = [option.id for option in assessment.options]
    if correct and option_ids:
        return "TRUE" if correct[0] == option_ids[0] else "FALSE"
    return "TRUE"


def _choice_lines(assessment: Assessment) -> list[str]:
    """Строки вариантов: ``=верный``/``~неверный`` с пояснением у верных."""
    correct = set(_correct_ids(assessment))
    feedback = _feedback(assessment)
    lines: list[str] = []
    for option in assessment.options:
        marker = "=" if option.id in correct else "~"
        line = f"{marker}{escape_gift(_single_line(option.text))}"
        if option.id in correct and feedback:
            line += feedback
        lines.append(line)
    return lines


def _matching_pairs(assessment: Assessment) -> list[tuple[str, str]]:
    """Пары «элемент -> соответствие» из текстов вариантов; иначе — пустой список."""
    pairs: list[tuple[str, str]] = []
    for option in assessment.options:
        for separator in MATCHING_SEPARATORS:
            if separator in option.text:
                left, _, right = option.text.partition(separator)
                pairs.append((left.strip(), right.strip()))
                break
        else:
            return []
    return pairs


def _short_lines(assessment: Assessment) -> list[str]:
    """Строки верных ответов short-вопроса: ``=ответ`` (пояснение — у первого)."""
    feedback = _feedback(assessment)
    lines: list[str] = []
    for index, answer in enumerate(_correct_ids(assessment)):
        line = f"={escape_gift(_single_line(_answer_text(assessment, answer)))}"
        if index == 0 and feedback:
            line += feedback
        lines.append(line)
    return lines


def _question_block(assessment: Assessment) -> str:
    """Блок GIFT: заголовок ``::ref [LO…]::`` и тело по типу вопроса."""
    tags = ", ".join(assessment.outcome_refs)
    header = f"::{assessment.ref} [{tags}]::{escape_gift(_single_line(assessment.stem))}"
    qtype = assessment.qtype or "open"
    comments: list[str] = []
    if qtype in ("single", "multiple"):
        lines = _choice_lines(assessment)
        if lines:
            body = "{\n" + "\n".join(lines) + "\n}"
        else:
            body = "{}"
            comments.append("// варианты ответа не заданы — вопрос проверяется вручную")
    elif qtype == "truefalse":
        body = "{" + _truefalse_literal(assessment) + _feedback(assessment) + "}"
    elif qtype == "short":
        lines = _short_lines(assessment)
        body = "{" + " ".join(lines) + "}" if lines else "{}"
        if not lines:
            comment = _explanation_comment(assessment)
            if comment:
                comments.append(comment)
    elif qtype == "matching":
        pairs = _matching_pairs(assessment)
        if pairs:
            body = (
                "{\n"
                + "\n".join(
                    f"={escape_gift(_single_line(left))} -> {escape_gift(_single_line(right))}" for left, right in pairs
                )
                + "\n}"
            )
        else:
            body = "{}"
            comments.append("// соответствие проверяется вручную: пары не заданы как «элемент -> соответствие»")
            comment = _explanation_comment(assessment)
            if comment:
                comments.append(comment)
    elif qtype == "order":
        body = "{}"
        order = " -> ".join(_single_line(_answer_text(assessment, answer)) for answer in _correct_ids(assessment))
        comments.append(f"// верный порядок: {order}" if order else "// упорядочивание проверяется вручную")
    else:  # open
        body = "{}"
        comment = _explanation_comment(assessment)
        if comment:
            comments.append(comment)
    block = header + body
    if comments:
        block += "\n" + "\n".join(comments)
    return block


def export_gift(kit: KitV1) -> str:
    """Сериализовать тестовые вопросы комплекта в Moodle GIFT.

    Категории — по модулям в порядке каркаса; вопросы — в порядке ``content.assessments``.
    Нетестовые оценочные средства (задания, проекты) не выгружаются. Если тестовых
    вопросов нет, возвращается файл с комментарием ``// Тестовых вопросов в комплекте нет``.
    """
    questions = [a for a in kit.content.assessments if a.kind == "test_question"]
    if not questions:
        return NO_QUESTIONS_COMMENT + "\n"

    by_module: dict[str, list[Assessment]] = {}
    unassigned: list[Assessment] = []
    for assessment in questions:
        module = _module_for_assessment(kit, assessment)
        if module is None:
            unassigned.append(assessment)
        else:
            by_module.setdefault(module.ref, []).append(assessment)

    chunks: list[str] = []
    for module in kit.framework.modules:
        group = by_module.get(module.ref)
        if not group:
            continue
        chunks.append(f"$CATEGORY: {_category(module)}")
        chunks.extend(_question_block(assessment) for assessment in group)
    if unassigned:
        chunks.append(f"$CATEGORY: {_category(None)}")
        chunks.extend(_question_block(assessment) for assessment in unassigned)
    return "\n\n".join(chunks) + "\n"
