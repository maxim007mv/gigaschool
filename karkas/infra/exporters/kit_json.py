"""karkas.infra.exporters.kit_json — выгрузка комплекта в KitV1 JSON (Д4 §3, §5.12).

Каноническая сериализация: ``json.dumps(kit.model_dump(mode="json"), ensure_ascii=False)``.
Та же схема публикуется в ``/api/v1/schemas/kit-v1.json`` (``kit_json_schema()``) и
используется для снимков версий и типов фронтенда.
"""

from __future__ import annotations

import json
from typing import Any

from karkas.domain.kit import KitV1


def export_kit_json(kit: KitV1) -> str:
    """Сериализовать комплект как KitV1 JSON (UTF-8, без ASCII-экранирования)."""
    return json.dumps(kit.model_dump(mode="json"), ensure_ascii=False)


def kit_json_schema() -> dict[str, Any]:
    """JSON Schema канонической модели KitV1 (``kit.v1``)."""
    return KitV1.model_json_schema()
