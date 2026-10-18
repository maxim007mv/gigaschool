"""Round-trip: export GIFT → parse → сверка структуры."""

from __future__ import annotations

from karkas.infra.exporters.gift import export_gift
from karkas.infra.exporters.gift_parse import parse_gift
from tests.unit.test_exporters_gift import build_export_kit


def test_gift_parse_roundtrip_counts() -> None:
    kit = build_export_kit()
    text = export_gift(kit)
    parsed = parse_gift(text)
    assert len(parsed.categories) == 2
    refs = {q.ref for q in parsed.questions}
    assert refs == {"Q-001", "Q-002", "Q-003", "Q-004"}
    single = next(q for q in parsed.questions if q.ref == "Q-001")
    assert single.correct_count == 1
    assert single.distractor_count == 3
