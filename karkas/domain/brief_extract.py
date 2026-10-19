"""Извлечение слотов программы из текста брифа (без LLM)."""

from __future__ import annotations

import re

from karkas.domain.intake_slots import parse_total_hours

_QUOTED_TITLE = re.compile(r"[«\"']([^«»\"']{3,120})[»\"']")
_SESSION_HOURS = re.compile(
    r"(?:по|за)\s*(\d{1,2})\s*(?:акад(?:емических)?\s*)?ч(?:ас(?:а|ов)?)?",
    re.IGNORECASE,
)
_WEEKS_PER = re.compile(r"(\d{1,2})\s*раз(?:а)?\s*в\s*недел", re.IGNORECASE)
_PRACTICE_SHARE = re.compile(
    r"практик\w*\s+(?:должн\w*\s+)?(?:быть\s+)?(?:не\s+)?меньше\s+(\d{1,3})\s*%",
    re.IGNORECASE,
)


def extract_program_title(brief: str) -> str | None:
    """Название из кавычек («Первые шаги в Python») или None."""
    for match in _QUOTED_TITLE.finditer(brief):
        title = match.group(1).strip()
        if len(title) >= 3:
            return title[:120]
    return None


def extract_kind_label(brief: str) -> str | None:
    lowered = brief.lower().replace("ё", "е")
    if "общеразвива" in lowered or "дополнительная общеразвива" in lowered:
        return "Общеразвивающая (ДОП)"
    if any(x in lowered for x in ("повышение квалификации", "переподготовка", "дпп")):
        return "Повышение квалификации (ДПП ПК)"
    return None


def extract_unit_hours(brief: str) -> int | None:
    match = _SESSION_HOURS.search(brief)
    if match:
        value = int(match.group(1))
        if 1 <= value <= 8:
            return value
    return None


def extract_days_per_week(brief: str) -> int | None:
    match = _WEEKS_PER.search(brief)
    if match:
        return max(1, min(7, int(match.group(1))))
    return None


def extract_min_practice_share_pct(brief: str) -> float | None:
    match = _PRACTICE_SHARE.search(brief)
    if match:
        return float(match.group(1))
    return None


def extract_form_label(brief: str) -> str | None:
    lowered = brief.lower().replace("ё", "е")
    if "очно-заоч" in lowered or "смешан" in lowered:
        return "Очно-заочно"
    if "дистанц" in lowered or "дот" in lowered:
        return "Дистанционно"
    if "стажиров" in lowered:
        return "Стажировка"
    if "очн" in lowered:
        return "Очно"
    return None


def extract_module_current_control(brief: str) -> str | None:
    """Форма текущего контроля по разделам (модулям), если явно в брифе."""
    lowered = brief.lower().replace("ё", "е")
    if re.search(r"текущ\w*\s+контрол", lowered) and re.search(r"собесед", lowered):
        return "собеседование"
    if "стажиров" in lowered:
        return "собеседование"
    return None


def inject_brief_topic_keywords(brief: str, modules: list[dict], gaps: list[str]) -> None:
    """Добавить в названия тем ключевые термины из брифа (ТК-5: IaC, cloud, инфраструктура)."""
    lowered = brief.casefold()
    labels: list[str] = []
    if "инфраструктур" in lowered:
        labels.append("инфраструктура")
    if "iac" in lowered:
        labels.append("IaC")
    if "cloud" in lowered or "облач" in lowered:
        labels.append("cloud")
    if ("devops" in lowered or "ci/cd" in lowered or "стажиров" in lowered) and "iac" not in labels:
        labels.append("IaC")
    if ("devops" in lowered or "стажиров" in lowered) and "cloud" not in labels:
        labels.append("cloud")
    if not labels:
        return
    topics = [topic for module in modules for topic in module.get("topics") or []]
    if not topics:
        return
    joined = " ".join(str(t.get("title") or "") for t in topics).casefold()
    for label in labels:
        if label.casefold() in joined:
            continue
        target = topics[-1]
        title = str(target.get("title") or "").strip()
        target["title"] = f"{title}: {label}" if title else label
        gaps.append(f"{target.get('ref', '?')}: в название темы добавлен термин из брифа «{label}» (ТК-5)")


def extract_final_attestation(brief: str) -> str | None:
    lowered = brief.lower()
    if re.search(r"\bэкзамен\w*\b", lowered):
        return "Экзамен"
    if re.search(r"портфолио", lowered):
        return "Зачёт по портфолио"
    if re.search(r"итогов\w*\s+аттестац", lowered) and re.search(r"защит", lowered):
        return "Проект/защита"
    if (
        re.search(r"защит\w*[^.]{0,40}проект", lowered)
        or re.search(r"защищ\w*[^.]{0,40}проект", lowered)
        or re.search(r"проект\w*\s+на\s+защит", lowered)
    ):
        return "Проект/защита"
    if re.search(r"\bсобеседован", lowered):
        return "Собеседование"
    if re.search(r"итогов\w*\s+тест|тест\s+на\s+\d+\s+вопрос", lowered):
        return "Тест"
    return None


def extract_distance_share_pct(brief: str, form_label: str | None = None) -> float | None:
    """Доля ДОТ только если в брифе явно указаны дистанционные технологии / ДОТ."""
    lowered = brief.lower().replace("ё", "е")
    explicit = any(
        token in lowered
        for token in (
            "дистанцион",
            " дот",
            "дот ",
            "электронн",
            "дистанционных технолог",
        )
    )
    if not explicit:
        return None
    form = (form_label or extract_form_label(brief) or "").lower()
    if "очно-заоч" in form or "очно-заоч" in lowered:
        return 30.0
    if "дистанц" in form or ("дистанц" in lowered and "очн" not in lowered):
        return 100.0
    return 30.0


def kit_options_from_brief(brief: str) -> dict[str, object]:
    """Опции комплекта из явных пожеланий брифа (слайды, число вопросов теста)."""
    options: dict[str, object] = {}
    lowered = brief.lower()
    if "слайд" in lowered:
        if re.search(r"перв\w+\s+дв\w+\s+занят", lowered) or re.search(r"занят\w+\s+1\s+и\s+2", lowered):
            options["slides"] = {"first_topics": 2}
        elif re.search(r"модул\w+\s+про\s+pandas|pandas", lowered):
            options["slides"] = {"module_title_contains": "pandas"}
    test_match = re.search(r"тест\s+на\s+(\d+)\s+вопрос", lowered)
    if test_match:
        options["tests"] = {"final_questions": int(test_match.group(1))}
    return options


def slots_from_brief(brief: str) -> dict[str, str]:
    """Слоты, однозначно читаемые из брифа (для pre-fill уточнений)."""
    out: dict[str, str] = {}
    kind = extract_kind_label(brief)
    if kind:
        out["kind"] = kind
    hours = parse_total_hours(brief)
    if hours:
        out["total_hours"] = str(hours)
    form = extract_form_label(brief)
    if form:
        out["form"] = form
    final_att = extract_final_attestation(brief)
    if final_att:
        out["final_attestation"] = final_att
    lowered = brief.lower().replace("ё", "е")
    if "школьник" in lowered:
        out["audience"] = "Школьники"
        out["entry_level"] = "Без опыта программирования"
    elif "учител" in lowered:
        out["audience"] = "Учителя общеобразовательных организаций"
        out["entry_level"] = "Педагогический стаж, базовые навыки работы с ПК"
    elif "банк" in lowered or "excel" in lowered:
        out["audience"] = "Сотрудники региональных отделений банков"
        out["entry_level"] = "Опыт работы с электронными таблицами"
    elif "колледж" in lowered or "студент" in lowered:
        out["audience"] = "Студенты колледжа"
        out["entry_level"] = "Базовая ИТ-подготовка"
    elif "стажиров" in lowered or "devops" in lowered:
        out["audience"] = "Слушатели на стажировке в ИТ-компаниях"
        out["entry_level"] = "Опыт администрирования Linux на уровне пользователя"
    return out


def derive_goal(brief: str, *, title: str | None = None, kind: str | None = None) -> str:
    """Краткая цель программы, если S01 не заполнил поле goal."""
    name = title or extract_program_title(brief) or "программа"
    audience = "слушателей"
    if "школьник" in brief.lower():
        audience = "школьников"
    if kind == "dop" or "общеразвива" in brief.lower():
        return f"Развить у {audience} интерес и базовые умения по теме «{name}»."
    return f"Сформировать у {audience} профессиональные компетенции по теме «{name}»."
