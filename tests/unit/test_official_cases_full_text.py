"""Официальные ТК грузят полный текст из data/eval/test_cases_official.txt."""

from __future__ import annotations

from karkas.eval.official_cases import OFFICIAL_CASES, OFFICIAL_TXT


def test_tk5_includes_devops_from_file() -> None:
    assert OFFICIAL_TXT.is_file()
    tk5 = OFFICIAL_CASES["tk5"].request_text.lower()
    assert "devops" in tk5
    assert "256" in tk5
    assert len(tk5) > 200
