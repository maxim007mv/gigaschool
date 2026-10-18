"""ТК-4: не более 5 вопросов; каркас не стартует при открытых уточнениях."""

from __future__ import annotations

from karkas.agent.skills.S03_clarifying_questions.run import QuestionOut, QuestionsOut, normalize


def test_s03_caps_at_five_questions() -> None:
    payload = QuestionsOut(questions=[QuestionOut(slot=f"slot{i}", question=f"Q{i}?") for i in range(8)])
    out = normalize(payload, [f"slot{i}" for i in range(8)], max_questions=5)
    assert len(out["questions"]) == 5
    assert len(out["assumptions"]) >= 1
