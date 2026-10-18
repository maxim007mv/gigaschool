"""Тесты выгрузок Moodle XML, CSV и KitV1 JSON (karkas.infra.exporters).

Фикстура комплекта — ``build_export_kit()`` из test_exporters_gift.py.
"""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ElementTree

import pytest

from karkas.domain.kit import (
    AnswerKey,
    Assessment,
    AssessmentOption,
    Criterion,
    KitV1,
)
from karkas.infra.exporters import (
    ARTIFACT_KINDS,
    export_gift,
    export_kit_json,
    export_moodle_xml,
    export_tests_csv,
)
from karkas.infra.exporters.kit_json import kit_json_schema
from tests.unit.test_exporters_gift import build_export_kit

EXPECTED_TEST_REFS = {"Q-001", "Q-002", "Q-003", "Q-004"}


@pytest.fixture()
def kit() -> KitV1:
    return build_export_kit()


# ---------------------------------------------------------------------------
# Moodle XML
# ---------------------------------------------------------------------------


def _parse_quiz(text: str) -> ElementTree.Element:
    root = ElementTree.fromstring(text)
    assert root.tag == "quiz"
    return root


def _question_by_ref(root: ElementTree.Element, ref: str) -> ElementTree.Element:
    for question in root.findall("question"):
        if question.findtext("idnumber") == ref:
            return question
    raise AssertionError(f"вопрос {ref} не найден в XML")


def _fractions(question: ElementTree.Element) -> list[str]:
    return [answer.get("fraction") or "" for answer in question.findall("answer")]


def test_moodle_xml_parses_with_declaration(kit: KitV1) -> None:
    text = export_moodle_xml(kit)
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    root = _parse_quiz(text)
    assert len(root.findall("question")) == len(EXPECTED_TEST_REFS)


def test_moodle_xml_escapes_special_characters(kit: KitV1) -> None:
    """Спецсимволы не ломают XML, а восстанавливаются парсером как есть."""
    root = _parse_quiz(export_moodle_xml(kit))
    question = _question_by_ref(root, "Q-001")
    assert question.findtext("questiontext/text") == "Что выведет код, если x = 2 ~ 3 # важно: {5}?"


def test_moodle_multichoice_single_flag_and_fractions(kit: KitV1) -> None:
    root = _parse_quiz(export_moodle_xml(kit))
    single = _question_by_ref(root, "Q-001")
    assert single.get("type") == "multichoice"
    assert single.findtext("single") == "true"
    assert _fractions(single) == ["100", "0", "0", "0"]
    answers = [answer.findtext("text") for answer in single.findall("answer")]
    assert answers[0] == "print(x=2)"


def test_moodle_multichoice_multiple_has_two_correct(kit: KitV1) -> None:
    root = _parse_quiz(export_moodle_xml(kit))
    multiple = _question_by_ref(root, "Q-002")
    assert multiple.findtext("single") == "false"
    assert _fractions(multiple) == ["100", "100", "0"]


def test_moodle_truefalse_and_shortanswer(kit: KitV1) -> None:
    root = _parse_quiz(export_moodle_xml(kit))
    truefalse = _question_by_ref(root, "Q-003")
    assert truefalse.get("type") == "truefalse"
    assert [answer.findtext("text") for answer in truefalse.findall("answer")] == ["true", "false"]
    assert _fractions(truefalse) == ["100", "0"]
    short = _question_by_ref(root, "Q-004")
    assert short.get("type") == "shortanswer"
    assert [answer.findtext("text") for answer in short.findall("answer")] == ["dict"]
    assert _fractions(short) == ["100"]


def test_moodle_tags_bind_questions_to_outcomes(kit: KitV1) -> None:
    """<tags><tag><text>LO1.2</text> — привязка к результатам обучения."""
    root = _parse_quiz(export_moodle_xml(kit))
    expected = {
        assessment.ref: assessment.outcome_refs
        for assessment in kit.content.assessments
        if assessment.kind == "test_question"
    }
    for ref, outcome_refs in expected.items():
        question = _question_by_ref(root, ref)
        tags = [tag.findtext("text") for tag in question.findall("tags/tag")]
        assert tags == outcome_refs
    assert "ST-T1.1-1" not in {question.findtext("idnumber") for question in root.findall("question")}


def test_moodle_empty_quiz_without_questions() -> None:
    kit = build_export_kit()
    kit.content.assessments = []
    root = _parse_quiz(export_moodle_xml(kit))
    assert root.findall("question") == []


def _single_question(kit: KitV1, **kwargs) -> ElementTree.Element:
    """Оставить в комплекте один вопрос и вернуть его XML-элемент."""
    base = dict(kind="test_question", module_ref="M1", outcome_refs=["LO1.1"])
    base.update(kwargs)
    kit.content.assessments = [Assessment(**base)]
    root = _parse_quiz(export_moodle_xml(kit))
    questions = root.findall("question")
    assert len(questions) == 1
    return questions[0]


def test_moodle_matching_pairs_become_subquestions(kit: KitV1) -> None:
    question = _single_question(
        kit,
        ref="Q-200",
        stem="Сопоставьте типы данных.",
        qtype="matching",
        options=[
            AssessmentOption(id="1", text="list -> список"),
            AssessmentOption(id="2", text="dict -> словарь"),
        ],
        answer_key=AnswerKey(correct=[]),
    )
    assert question.get("type") == "matching"
    subquestions = question.findall("subquestion")
    assert [sub.findtext("text") for sub in subquestions] == ["list", "dict"]
    assert [sub.findtext("answer/text") for sub in subquestions] == ["список", "словарь"]


def test_moodle_degraded_types_become_essay(kit: KitV1) -> None:
    """order/open/matching без пар/short без ответов/выбор без вариантов → essay."""
    cases = [
        dict(
            ref="Q-201",
            stem="Упорядочьте.",
            qtype="order",
            options=[AssessmentOption(id="1", text="раз")],
            answer_key=AnswerKey(correct=["1"]),
        ),
        dict(ref="Q-202", stem="Опишите.", qtype="open", options=[], answer_key=AnswerKey(correct=[])),
        dict(
            ref="Q-203",
            stem="Соотнесите.",
            qtype="matching",
            options=[AssessmentOption(id="1", text="без пары")],
            answer_key=AnswerKey(correct=[]),
        ),
        dict(ref="Q-204", stem="Ответьте.", qtype="short", options=[], answer_key=AnswerKey(correct=[])),
        dict(
            ref="Q-205",
            stem="Выберите.",
            qtype="single",
            options=[],
            answer_key=AnswerKey(correct=["a"]),
        ),
    ]
    for case in cases:
        question = _single_question(kit, **case)
        assert question.get("type") == "essay", case["ref"]


def test_moodle_essay_keeps_rubric_in_graderinfo(kit: KitV1) -> None:
    question = _single_question(
        kit,
        ref="Q-206",
        stem="Опишите подход.",
        qtype="open",
        options=[],
        answer_key=AnswerKey(correct=[]),
        rubric=[Criterion(criterion="Полнота", max_points=6, levels=["полный", "частичный"])],
    )
    assert question.get("type") == "essay"
    graderinfo = question.findtext("graderinfo/text")
    assert graderinfo is not None and "Полнота — до 6 баллов" in graderinfo


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def _csv_rows(text: str) -> list[list[str]]:
    return list(csv.reader(text.splitlines(), delimiter=";"))


def test_csv_header_and_row_count(kit: KitV1) -> None:
    rows = _csv_rows(export_tests_csv(kit))
    header = rows[0]
    assert header[:6] == ["ref", "модуль", "тема", "РО", "тип", "вопрос"]
    assert header[6:10] == ["вариант_1", "вариант_2", "вариант_3", "вариант_4"]
    assert header[10:] == ["правильные", "пояснение"]
    assert len(rows) == 5  # заголовок + 4 тестовых вопроса
    assert {row[0] for row in rows[1:]} == EXPECTED_TEST_REFS


def test_csv_single_question_row(kit: KitV1) -> None:
    rows = {row[0]: row for row in _csv_rows(export_tests_csv(kit))[1:]}
    row = rows["Q-001"]
    assert row[1] == "М1 Основы Python"
    assert row[2] == "Введение в Python"
    assert row[3] == "LO1.2"
    assert row[4] == "single"
    assert row[5] == "Что выведет код, если x = 2 ~ 3 # важно: {5}?"
    assert row[6:10] == ["print(x=2)", "print(x~2)", "print(x#2)", "print(x:2)"]
    assert row[10] == "print(x=2)"
    assert row[11] == "Верно: арифметика"


def test_csv_multiple_question_quotes_delimiter(kit: KitV1) -> None:
    """Значение с ';' экранируется и разбирается csv.reader как одна ячейка."""
    text = export_tests_csv(kit)
    rows = {row[0]: row for row in _csv_rows(text)[1:]}
    expected_stem = "Какие методы дают обзор таблицы? Выберите все верные; верных может быть несколько."
    assert rows["Q-002"][5] == expected_stem
    assert rows["Q-002"][10] == "df.head() | df.describe()"


def test_csv_short_question_has_answer_and_empty_options(kit: KitV1) -> None:
    rows = {row[0]: row for row in _csv_rows(export_tests_csv(kit))[1:]}
    row = rows["Q-004"]
    assert row[4] == "short"
    assert row[6:10] == ["", "", "", ""]
    assert row[10] == "dict"
    assert row[11] == "Словарь — dict."


def test_csv_without_questions_returns_header_only() -> None:
    kit = build_export_kit()
    kit.content.assessments = []
    rows = _csv_rows(export_tests_csv(kit))
    assert len(rows) == 1
    assert rows[0][0] == "ref"


# ---------------------------------------------------------------------------
# KitV1 JSON и реестр форматов
# ---------------------------------------------------------------------------


def test_kit_json_roundtrip(kit: KitV1) -> None:
    """json.loads → KitV1.model_validate возвращает эквивалентный комплект."""
    text = export_kit_json(kit)
    restored = KitV1.model_validate(json.loads(text))
    assert restored.program.title == kit.program.title
    assert restored.grand_total() == kit.grand_total()
    assert restored.content.assessments[0].answer_key.correct == ["a"]


def test_kit_json_is_utf8_not_ascii_escaped(kit: KitV1) -> None:
    text = export_kit_json(kit)
    assert kit.program.title in text
    assert "\\u04" not in text


def test_kit_json_schema_has_top_level_sections() -> None:
    schema = kit_json_schema()
    assert schema.get("title") == "KitV1"
    properties = schema["properties"]
    for section in ("program", "framework", "content"):
        assert section in properties


def test_artifact_kinds_registry() -> None:
    assert set(ARTIFACT_KINDS) == {"docx", "pptx", "gift", "moodle_xml", "csv", "json", "report"}
    for function in ARTIFACT_KINDS.values():
        assert callable(function)


def test_artifact_functions_produce_content(kit: KitV1) -> None:
    """Все функции реестра работоспособны на общей фикстуре."""
    results = {kind: function(kit) for kind, function in ARTIFACT_KINDS.items()}
    assert results["gift"].startswith("$CATEGORY") or results["gift"].startswith("//")
    for kind, value in results.items():
        assert value, f"{kind}: пустой результат"
        if isinstance(value, bytes):
            assert value[:2] == b"PK", f"{kind}: не zip-контейнер"


def test_import_of_stroutputs_are_str(kit: KitV1) -> None:
    assert isinstance(export_gift(kit), str)
    assert isinstance(export_moodle_xml(kit), str)
    assert isinstance(export_tests_csv(kit), str)
    assert isinstance(export_kit_json(kit), str)
