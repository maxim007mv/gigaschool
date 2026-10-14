"""S22 · Актуализация старой программы (Д4 §5.10)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from pydantic import BaseModel, Field

from karkas.agent.skills._base import SkillContext, SkillSpec, complete_structured, to_json

DIR = "S22_actualize"
METADATA = SkillSpec(code="S22", name="Актуализация старой программы", dir=DIR, model_class="struct", depends_on=("S04",))


class OutdatedOut(BaseModel):
    element: str = ""
    current: str = ""
    reason: str = ""


class ProposalOut(BaseModel):
    was: str = ""
    proposed: str = ""
    rationale: str = ""


class ActualizeOut(BaseModel):
    outdated: list[OutdatedOut] = Field(default_factory=list)
    proposals: list[ProposalOut] = Field(default_factory=list)
    snapshot_date: str = ""
    notes: str = ""


def stale_tools(tools: list[Any], catalog: list[Any]) -> list[dict[str, str]]:
    """Детерминированно: инструменты каталога с lifecycle ≠ current — устарели."""
    by_name = {
        str(item.get("name") or "").strip().casefold(): item
        for item in catalog
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    outdated: list[dict[str, str]] = []
    for tool in tools:
        name = str((tool or {}).get("name") or "").strip() if isinstance(tool, dict) else str(tool).strip()
        if not name:
            continue
        service = by_name.get(name.casefold())
        if service is None:
            continue
        lifecycle = str(service.get("lifecycle") or "current")
        if lifecycle != "current":
            outdated.append(
                {
                    "element": name,
                    "current": str(service.get("latest_version") or ""),
                    "reason": f"жизненный цикл сервиса: {lifecycle} (снимок {service.get('snapshot', '')})".strip(),
                }
            )
    return outdated


def normalize(
    payload: ActualizeOut, snapshot_date: str, tools: list[Any], catalog: list[Any]
) -> dict[str, Any]:
    """Дедупликация, чистка, детерминированное дополнение по каталогу."""
    outdated: list[dict[str, str]] = []
    seen_elements: set[str] = set()
    for item in payload.outdated:
        element = item.element.strip()
        if not element or element.casefold() in seen_elements:
            continue
        seen_elements.add(element.casefold())
        outdated.append({"element": element, "current": item.current.strip(), "reason": item.reason.strip() or "требует проверки"})
    for item in stale_tools(tools, catalog):
        if item["element"].casefold() not in seen_elements:
            seen_elements.add(item["element"].casefold())
            outdated.append(item)
    proposals: list[dict[str, str]] = []
    seen_was: set[str] = set()
    for proposal in payload.proposals:
        was = proposal.was.strip()
        proposed = proposal.proposed.strip()
        if not was or not proposed or was.casefold() in seen_was or not proposal.rationale.strip():
            continue
        seen_was.add(was.casefold())
        proposals.append({"was": was, "proposed": proposed, "rationale": proposal.rationale.strip()})
    return {
        "outdated": outdated,
        "proposals": proposals,
        "snapshot_date": payload.snapshot_date.strip() or snapshot_date,
        "notes": payload.notes.strip(),
    }


async def run(inputs: dict[str, Any], ctx: SkillContext) -> dict[str, Any]:
    """Найти устаревшее в старой программе и предложить замены с обоснованием."""
    old_program = inputs.get("old_program") or (inputs.get("S04") if isinstance(inputs.get("S04"), dict) else {})
    tools = [item for item in (inputs.get("tools") or [])]
    catalog = [item for item in (inputs.get("service_catalog") or [])]
    snapshot_date = str(inputs.get("snapshot_date") or datetime.now(timezone.utc).date().isoformat())
    payload = cast(
        ActualizeOut,
        await complete_structured(
            ctx,
            METADATA,
            ActualizeOut,
            structure_json=to_json(old_program),
            tools_json=to_json(tools),
            service_catalog_json=to_json(catalog),
            snapshot_date=snapshot_date,
        ),
    )
    return normalize(payload, snapshot_date, tools, catalog)
