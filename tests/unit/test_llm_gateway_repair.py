"""Ремонт structured output и мягкая нормализация JSON."""

from __future__ import annotations

from pydantic import BaseModel, Field

from karkas.agent.llm_gateway import _lenient_coerce


class _SampleOut(BaseModel):
    title: str = ""
    tags: list[str] = Field(default_factory=list)


def test_lenient_coerce_string_to_list() -> None:
    raw = {"title": "t", "tags": "one"}
    coerced = _lenient_coerce(raw, _SampleOut)
    obj = _SampleOut.model_validate(coerced)
    assert obj.tags == ["one"]


def test_lenient_coerce_null_optional_dropped() -> None:
    raw = {"title": "t", "tags": None}
    coerced = _lenient_coerce(raw, _SampleOut)
    obj = _SampleOut.model_validate(coerced)
    assert obj.tags == []
