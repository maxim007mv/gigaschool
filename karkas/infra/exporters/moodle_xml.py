"""karkas.infra.exporters.moodle_xml — выгрузка тестов в Moodle XML (Д4 §5.12).

Соответствие типов:

======================  =========================  =====================================
``qtype`` KitV1         ``type`` Moodle XML         примечание
======================  =========================  =====================================
single                  multichoice                ``<single>true</single>``, fraction 100/0
multiple                multichoice                ``<single>false</single>``, несколько 100
truefalse               truefalse                  ответы ``true``/``false``
short                   shortanswer                принимаемые ответы из ``answer_key``
matching                matching                   пары из вариантов «элемент -> пара»
order, open             essay                      проверка вручную (в ядре Moodle нет
                                                   типа «упорядочивание»)
======================  =========================  =====================================

Дополнительно: ``<idnumber>`` = ref вопроса, ``<tags>`` — теги РО (``LO1.2``), рубрика
заданий с ручной проверкой попадает в ``<graderinfo>``. Если тестовых вопросов нет,
возвращается корректный пустой ``<quiz>`` (функция не падает). Экранирование
спецсимволов выполняет ``xml.etree``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree

from karkas.domain.kit import Assessment, KitV1

XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>'
INDENT = "  "

#: Символы, недопустимые в XML 1.0 (кроме \t \n \r): вычищаются из результата.
_INVALID_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
FRACTION_CORRECT = "100"
FRACTION_WRONG = "0"
SHUFFLE_ANSWERS = "1"
ANSWER_NUMBERING = "abc"
MATCHING_SEPARATORS = ("->", "→")
TRUE_LITERALS = frozenset({"true", "t", "1", "верно", "истина", "да", "yes"})
FALSE_LITERALS = frozenset({"false", "f", "0", "неверно", "ложь", "нет", "no"})

MULTICHOICE = "multichoice"
TRUEFALSE = "truefalse"
SHORTANSWER = "shortanswer"
MATCHING = "matching"
ESSAY = "essay"


def _correct_ids(assessment: Assessment) -> list[str]:
    """Идентификаторы верных вариантов (пусто, если ключа нет)."""
    return list(assessment.answer_key.correct) if assessment.answer_key else []


def _option_texts(assessment: Assessment) -> dict[str, str]:
    return {option.id: option.text for option in assessment.options}


def _answer_text(assessment: Assessment, answer: str) -> str:
    """Текст ответа: из варианта по id, иначе сам id (для short без вариантов)."""
    return _option_texts(assessment).get(answer, answer)


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


def _moodle_type(assessment: Assessment) -> str:
    """Тип вопроса Moodle XML по ``qtype`` с деградацией к ``essay``."""
    qtype = assessment.qtype or "open"
    if qtype == "short":
        return SHORTANSWER if _correct_ids(assessment) else ESSAY
    if qtype == "matching":
        return MATCHING if _matching_pairs(assessment) else ESSAY
    if qtype == "order" or qtype == "open":
        return ESSAY
    if qtype == "truefalse":
        return TRUEFALSE
    if qtype in ("single", "multiple"):
        return MULTICHOICE if assessment.options else ESSAY
    return ESSAY


def _add_answer(question: ElementTree.Element, text: str, fraction: str) -> None:
    """Добавить ответ с долей (100 — верный, 0 — неверный)."""
    answer = ElementTree.SubElement(question, "answer", {"fraction": fraction, "format": "html"})
    ElementTree.SubElement(answer, "text").text = text


def _add_name_and_text(question: ElementTree.Element, assessment: Assessment) -> None:
    """Имя вопроса, текст и ``<idnumber>`` (= ref) — xml.etree сам экранирует."""
    name = ElementTree.SubElement(question, "name")
    ElementTree.SubElement(name, "text").text = assessment.ref
    text_element = ElementTree.SubElement(question, "questiontext", {"format": "html"})
    ElementTree.SubElement(text_element, "text").text = assessment.stem
    ElementTree.SubElement(question, "idnumber").text = assessment.ref


def _add_tags(question: ElementTree.Element, assessment: Assessment) -> None:
    """Привязка вопроса к результатам обучения: ``<tags><tag><text>LO1.2</text>``."""
    tags = ElementTree.SubElement(question, "tags")
    for ref in assessment.outcome_refs:
        tag = ElementTree.SubElement(tags, "tag")
        ElementTree.SubElement(tag, "text").text = ref


def _add_graderinfo(question: ElementTree.Element, assessment: Assessment) -> None:
    """Рубрика задания с ручной проверкой — в ``<graderinfo>``."""
    if not assessment.rubric:
        return
    lines = [f"{criterion.criterion} — до {int(criterion.max_points)} баллов" for criterion in assessment.rubric]
    graderinfo = ElementTree.SubElement(question, "graderinfo", {"format": "html"})
    ElementTree.SubElement(graderinfo, "text").text = "\n".join(lines)


def _question_element(assessment: Assessment) -> ElementTree.Element:
    """Элемент ``<question>`` Moodle XML для одного оценочного средства."""
    question_type = _moodle_type(assessment)
    question = ElementTree.Element("question", {"type": question_type})
    _add_name_and_text(question, assessment)
    correct = set(_correct_ids(assessment))
    if question_type == MULTICHOICE:
        is_single = assessment.qtype == "single" and len(correct) == 1
        ElementTree.SubElement(question, "single").text = "true" if is_single else "false"
        ElementTree.SubElement(question, "shuffleanswers").text = SHUFFLE_ANSWERS
        ElementTree.SubElement(question, "answernumbering").text = ANSWER_NUMBERING
        for option in assessment.options:
            fraction = FRACTION_CORRECT if option.id in correct else FRACTION_WRONG
            _add_answer(question, option.text, fraction)
    elif question_type == TRUEFALSE:
        literal = _truefalse_literal(assessment)
        _add_answer(question, "true", FRACTION_CORRECT if literal == "TRUE" else FRACTION_WRONG)
        _add_answer(question, "false", FRACTION_CORRECT if literal == "FALSE" else FRACTION_WRONG)
    elif question_type == SHORTANSWER:
        ElementTree.SubElement(question, "usecase").text = "0"
        for answer in _correct_ids(assessment):
            _add_answer(question, _answer_text(assessment, answer), FRACTION_CORRECT)
    elif question_type == MATCHING:
        for left, right in _matching_pairs(assessment):
            subquestion = ElementTree.SubElement(question, "subquestion")
            ElementTree.SubElement(subquestion, "text").text = left
            answer = ElementTree.SubElement(subquestion, "answer")
            ElementTree.SubElement(answer, "text").text = right
    else:  # essay
        ElementTree.SubElement(question, "responseformat").text = "editor"
        _add_graderinfo(question, assessment)
    _add_tags(question, assessment)
    return question


def export_moodle_xml(kit: KitV1) -> str:
    """Сериализовать тестовые вопросы комплекта в Moodle XML.

    В выгрузку попадают только ``kind == "test_question"``; задания, проекты и
    вопросы собеседования в тест Moodle не переносятся. Если тестовых вопросов нет,
    возвращается валидный пустой ``<quiz>``.
    """
    quiz = ElementTree.Element("quiz")
    for assessment in kit.content.assessments:
        if assessment.kind == "test_question":
            quiz.append(_question_element(assessment))
    ElementTree.indent(quiz, space=INDENT)
    body = ElementTree.tostring(quiz, encoding="unicode")
    # Управляющие символы (например \x0b) недопустимы в XML 1.0 — LLM/пользовательский
    # текст может их содержать; удаляем, чтобы файл открывался в Moodle/парсерах.
    body = _INVALID_XML_CHARS.sub("", body)
    return f"{XML_DECLARATION}\n{body}\n"
