"""Ответы live_run для ТК-4: слот важнее ключевых слов в тексте вопроса."""

from __future__ import annotations

from karkas.eval.live_run import _match_tk4_answers


def test_tk4_slot_kind_not_confused_with_program_word() -> None:
    questions = [
        {"slot": "kind", "text": "Какой тип программы повышения квалификации нужен?"},
        {"slot": "total_hours", "text": "Уточните объём в академических часах"},
        {"slot": "final_attestation", "text": "Форма итоговой аттестации"},
    ]
    answers = _match_tk4_answers(questions)
    assert answers["kind"] == "Повышение квалификации"
    assert "72" in (answers.get("total_hours") or "")
    assert "экзамен" in (answers.get("final_attestation") or "").lower()
