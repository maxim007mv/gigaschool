"""Тесты операций правки каркаса (PATCH framework) — чистые функции."""

from __future__ import annotations

import pytest

from karkas.domain.framework_ops import OpError, apply_ops
from tests.conftest import build_minimal_kit


def _kit():
    return build_minimal_kit()


def test_set_hours_updates_only_cell() -> None:
    kit = _kit()
    new_kit, changes = apply_ops(kit, [{"op": "set_hours", "ref": "T1.1", "activity": "practice", "hours": 7}])
    topic = new_kit.framework.modules[0].topics[0]
    assert topic.workload.practice == 7
    assert topic.workload.lecture == 5  # не тронуто
    assert changes[0]["ref"] == "T1.1" and changes[0]["from"] == 9 and changes[0]["to"] == 7
    # исходный kit не мутирован
    assert kit.framework.modules[0].topics[0].workload.practice == 9


def test_set_hours_with_lock_adds_tag() -> None:
    new_kit, _ = apply_ops(
        _kit(),
        [{"op": "set_hours", "ref": "T1.1", "activity": "lecture", "hours": 5, "lock": True}],
    )
    assert "lecture:in_person" in new_kit.framework.modules[0].topics[0].locked


def test_set_hours_invalid_activity() -> None:
    with pytest.raises(OpError):
        apply_ops(_kit(), [{"op": "set_hours", "ref": "T1.1", "activity": "homework", "hours": 1}])


def test_set_hours_bounds() -> None:
    with pytest.raises(OpError):
        apply_ops(_kit(), [{"op": "set_hours", "ref": "T1.1", "activity": "lecture", "hours": 501}])


def test_rename_topic_and_module() -> None:
    new_kit, changes = apply_ops(
        _kit(),
        [
            {"op": "rename", "ref": "T1.1", "title": "Новое имя темы"},
            {"op": "rename", "ref": "M1", "title": "Новый модуль"},
        ],
    )
    assert new_kit.framework.modules[0].topics[0].title == "Новое имя темы"
    assert new_kit.framework.modules[0].title == "Новый модуль"
    assert len(changes) == 2


def test_move_topic() -> None:
    kit = _kit()
    # добавим второй модуль с темой
    from karkas.domain.kit import Module, Topic, Workload

    kit.framework.modules.append(
        Module(ref="M2", number=2, title="Второй", topics=[Topic(ref="T2.1", title="Тема 2", workload=Workload(lecture=1))])
    )
    new_kit, changes = apply_ops(kit, [{"op": "move_topic", "topic_ref": "T2.1", "to_module": "M1", "position": 1}])
    assert [t.ref for t in new_kit.framework.modules[0].topics] == ["T2.1", "T1.1"]
    assert new_kit.framework.modules[1].topics == []
    assert changes[0]["from"] == "M2" and changes[0]["to"] == "M1"


def test_link_and_unlink_outcome() -> None:
    kit = _kit()
    from karkas.domain.kit import Outcome

    kit.framework.competencies[0].outcomes.append(Outcome(ref="LO1.2", type="knowledge", text="Знает"))
    new_kit, _ = apply_ops(kit, [{"op": "link_outcome", "topic_ref": "T1.1", "outcome_ref": "LO1.2"}])
    assert "LO1.2" in new_kit.framework.modules[0].topics[0].outcome_refs
    again, _ = apply_ops(new_kit, [{"op": "unlink_outcome", "topic_ref": "T1.1", "outcome_ref": "LO1.2"}])
    assert "LO1.2" not in again.framework.modules[0].topics[0].outcome_refs


def test_link_unknown_outcome_raises() -> None:
    with pytest.raises(OpError):
        apply_ops(_kit(), [{"op": "link_outcome", "topic_ref": "T1.1", "outcome_ref": "LO9.9"}])


def test_set_goal_and_final_att() -> None:
    new_kit, _ = apply_ops(
        _kit(),
        [
            {"op": "set_goal", "title": "Новая цель"},
            {"op": "set_final_att", "form": "экзамен", "hours": 4},
        ],
    )
    assert new_kit.framework.goal == "Новая цель"
    assert new_kit.framework.final_attestation.form == "экзамен"
    assert new_kit.framework.final_attestation.hours == 4
    assert new_kit.program.final_attestation.hours == 4


def test_unknown_op_raises() -> None:
    with pytest.raises(OpError):
        apply_ops(_kit(), [{"op": "explode"}])
