"""V-LNG-01 не применяется к идентификаторам и литералам кода (TK1-8)."""

import pytest

from karkas.domain.validators.language import _looks_like_code_snippet


@pytest.mark.parametrize("text", ["My-Var", "if-else", "(1, 'a', True)", "my_var", "print()", "person.age"])
def test_code_tokens_are_skipped(text: str) -> None:
    assert _looks_like_code_snippet(text)


@pytest.mark.parametrize("text", ["Students learn the basics of programming", "Знает синтаксис Python"])
def test_plain_text_is_not_code(text: str) -> None:
    assert not _looks_like_code_snippet(text)
