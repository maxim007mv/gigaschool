"""karkas.domain.framework_ops — применение операций правки каркаса (Д4 §6.4).

PATCH framework: набор операций над KitV1 (set_hours, rename, move_topic,
link_outcome, unlink_outcome, set_goal, set_final_att) → новый KitV1 + список изменений.
Часы меняются только в Topic.workload (листовой уровень).
"""

from __future__ import annotations

from typing import Any

from karkas.domain.kit import FinalAttestation, KitV1, Module, Topic, find_module, find_outcome, find_topic


class OpError(ValueError):
    """Операция неприменима (неверный ref, выход за границы и т. п.)."""


def _parse_lock(activity: str, mode: str) -> str:
    return f"{activity}:{mode}"


def apply_ops(kit: KitV1, ops: list[dict[str, Any]]) -> tuple[KitV1, list[dict[str, Any]]]:
    """Применить операции к копии KitV1. Возвращает (новый kit, список изменений)."""
    new_kit = kit.model_copy(deep=True)
    changes: list[dict[str, Any]] = []

    for op in ops:
        kind = op.get("op")
        ref = op.get("ref")
        if kind == "set_goal":
            old = new_kit.framework.goal
            new_kit.framework.goal = op.get("title") or op.get("goal") or old
            changes.append({"ref": "goal", "field": "goal", "from": old, "to": new_kit.framework.goal})
            continue

        if kind == "set_final_att":
            form = op.get("form") or new_kit.framework.final_attestation.form
            hours = op.get("hours", new_kit.framework.final_attestation.hours)
            try:
                validated = FinalAttestation(form=form, hours=int(hours))
            except Exception as exc:
                raise OpError("Часы итоговой аттестации должны быть целым числом от 0 до 100") from exc
            old = new_kit.framework.final_attestation.model_dump()
            new_kit.framework.final_attestation = validated
            new_kit.program.final_attestation = validated.model_copy()
            changes.append({"ref": "final_attestation", "field": "hours", "from": old, "to": validated.model_dump()})
            continue

        if kind == "rename":
            title = op.get("title")
            if not title:
                raise OpError("Для rename нужен title")
            topic = find_topic(new_kit, ref or "")
            if topic is not None:
                changes.append({"ref": topic.ref, "field": "title", "from": topic.title, "to": title})
                topic.title = title
                continue
            module = find_module(new_kit, ref or "")
            if module is not None:
                changes.append({"ref": module.ref, "field": "title", "from": module.title, "to": title})
                module.title = title
                continue
            raise OpError(f"Элемент {ref} не найден")

        if kind == "set_hours":
            topic = find_topic(new_kit, ref or "")
            if topic is None:
                raise OpError(f"Тема {ref} не найдена")
            activity = op.get("activity")
            if activity not in ("lecture", "practice", "lab", "self_study", "current_control"):
                raise OpError(f"Неизвестный вид работы: {activity}")
            hours = op.get("hours")
            if hours is None or hours < 0 or hours > 500:
                raise OpError("Часы должны быть в диапазоне 0…500")
            old = topic.workload.by_activity(activity)
            setattr(topic.workload, activity, int(hours))
            mode = op.get("mode", "in_person")
            # Трёхзначная семантика замка: lock=true — закрепить, lock=false — снять,
            # lock отсутствует — не трогать существующее закрепление (иначе
            # обычная правка часов молча снимала «замок» солвера).
            lock_value = op.get("lock")
            if lock_value is True:
                lock_tag = _parse_lock(activity, mode)
                if lock_tag not in topic.locked:
                    topic.locked.append(lock_tag)
            elif lock_value is False:
                lock_tag = _parse_lock(activity, mode)
                topic.locked = [t for t in topic.locked if t != lock_tag]
            changes.append({"ref": topic.ref, "field": activity, "from": old, "to": int(hours)})
            continue

        if kind == "move_topic":
            topic_ref = op.get("topic_ref") or op.get("ref")
            to_module = op.get("to_module")
            position = op.get("position")
            if not topic_ref or not to_module or not position or int(position) < 1:
                raise OpError("Для move_topic нужны topic_ref, to_module и position ≥ 1")
            source_module = None
            topic: Topic | None = None
            for m in new_kit.framework.modules:
                for t in m.topics:
                    if t.ref == topic_ref:
                        source_module, topic = m, t
                        break
                if topic:
                    break
            target = find_module(new_kit, to_module)
            if source_module is None or topic is None or target is None:
                raise OpError("Тема или модуль назначения не найдены")
            source_module.topics.remove(topic)
            target.topics.insert(min(int(position) - 1, len(target.topics)), topic)
            changes.append({"ref": topic.ref, "field": "module", "from": source_module.ref, "to": target.ref})
            continue

        if kind in ("link_outcome", "unlink_outcome"):
            topic = find_topic(new_kit, op.get("topic_ref") or "")
            outcome = find_outcome(new_kit, op.get("outcome_ref") or "")
            if topic is None or outcome is None:
                raise OpError("Тема или результат обучения не найдены")
            if kind == "link_outcome":
                if outcome.ref not in topic.outcome_refs:
                    topic.outcome_refs.append(outcome.ref)
                    topic.outcome_refs.sort()
                    changes.append({"ref": topic.ref, "field": "outcome_refs", "from": None, "to": outcome.ref})
            else:
                if outcome.ref in topic.outcome_refs:
                    topic.outcome_refs.remove(outcome.ref)
                    changes.append({"ref": topic.ref, "field": "outcome_refs", "from": outcome.ref, "to": None})
            continue

        raise OpError(f"Неизвестная операция: {kind}")

    return new_kit, changes
