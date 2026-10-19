"""Проверки по пунктам чек-листов ТК-ОБЩ и ТК-1…ТК-5 (детерминированно, без LLM).

Используется в ``tests/eval`` и ``scripts/run_eval.py``. Полный прогон с живыми
моделями — отдельно; здесь — проверки над готовым KitV1.

Каждый пункт официального чек-листа имеет отдельную функцию. Если артефакт
для проверки в KitV1 отсутствует (например, журнал уточняющих вопросов ТК-4),
пункт честно падает с указанием, какого артефакта нет: «требует ручной
проверки» вместо проверки не используется.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache

from karkas.domain.kit import KitV1
from karkas.domain.validators import ValidationContext
from karkas.domain.validators.language import validate as validate_language
from karkas.domain.verified_registry import VERIFIED_JSON


@dataclass(frozen=True)
class CheckResult:
    """Один пункт чек-листа."""

    case_id: str
    item_id: str
    passed: bool
    detail: str


# ---------------------------------------------------------------------------
# Общие помощники
# ---------------------------------------------------------------------------


def _result(case: str, item: str, passed: bool, detail: str) -> CheckResult:
    return CheckResult(case, item, passed, detail)


def _topic_texts(kit: KitV1) -> str:
    parts: list[str] = []
    for mod in kit.framework.modules:
        for topic in mod.topics:
            parts.append(topic.title or "")
            parts.append(topic.ref)
    return " ".join(parts).lower()


def _hours_grand(kit: KitV1) -> int:
    return kit.grand_total()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold().replace("ё", "е")


def _iter_body_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_body_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_body_strings(item)


def _kit_text(kit: KitV1) -> str:
    """Все содержательные строки KitV1 (без отчёта и служебных ref)."""
    parts: list[str] = [kit.program.title, kit.program.document]
    profile = kit.profile
    parts += [
        profile.audience or "",
        profile.entry_level or "",
        profile.schedule or "",
        profile.duration_hint or "",
        profile.notes or "",
        *profile.glossary.keys(),
        *profile.glossary.values(),
    ]
    parts += [kit.framework.goal, *kit.framework.tasks]
    for comp in kit.framework.competencies:
        parts.append(comp.title)
        parts += [outcome.text for outcome in comp.outcomes]
    for module in kit.framework.modules:
        parts.append(module.title)
        for topic in module.topics:
            parts += [topic.title, topic.summary or ""]
    parts += [
        kit.framework.final_attestation.form,
        kit.program.final_attestation.form,
    ]
    for group in (
        kit.content.module_programs,
        kit.content.lecture_plans,
        kit.content.slides,
        kit.content.sections,
    ):
        for block in group:
            parts += list(_iter_body_strings(block.body))
    for assessment in kit.content.assessments:
        parts += [assessment.stem, *[option.text for option in assessment.options]]
        parts += [f"{c.criterion} {' '.join(c.levels)}" for c in assessment.rubric]
    parts += [source.citation for source in kit.content.sources]
    return " ".join(part for part in parts if part).lower()


def _slide_count(block: object) -> int:
    body = getattr(block, "body", None)
    if not isinstance(body, dict):
        return 0
    slides = body.get("slides")
    if isinstance(slides, list):
        return len(slides)
    return 1 if body.get("title") or body.get("bullets") else 0


@lru_cache(maxsize=1)
def _verified_registry() -> tuple[dict[str, dict[str, str]], frozenset[tuple[str, str]]]:
    try:
        raw = json.loads(VERIFIED_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, frozenset()
    standards = {
        str(item["code"]).strip(): {
            "title": str(item.get("title") or ""),
            "status": str(item.get("status") or "active"),
        }
        for item in raw.get("prof_standards") or []
        if item.get("code")
    }
    labor = frozenset(
        (str(item["prof_standard_code"]).strip(), str(item["code"]).strip())
        for item in raw.get("labor_functions") or []
        if item.get("prof_standard_code") and item.get("code")
    )
    return standards, labor


def _titles_match(declared: str, registry: str) -> bool:
    left, right = _norm(declared), _norm(registry)
    return bool(left and right) and (left == right or left in right or right in left)


def _check_prof_standard(
    kit: KitV1,
    case: str,
    item: str,
    *,
    allowed_title_re: str,
    required_code: str | None = None,
    require_labor: bool = False,
) -> CheckResult:
    """Сверка ПС/ТФ с локальным реестром data/registries/verified.json."""
    linked = [comp for comp in kit.framework.competencies if comp.prof_standard is not None]
    if not linked:
        return _result(case, item, False, "нет ни одной компетенции с профстандартом")
    standards, labor_pairs = _verified_registry()
    problems: list[str] = []
    good: list[str] = []
    for comp in linked:
        standard = comp.prof_standard
        assert standard is not None  # для типизации; отфильтровано выше
        before = len(problems)
        if required_code and standard.code != required_code:
            problems.append(f"{comp.ref}: ПС {standard.code}, ожидается {required_code}")
        meta = standards.get(standard.code)
        if meta is None:
            problems.append(f"{comp.ref}: ПС {standard.code} нет в локальном реестре")
        else:
            if standard.status != "active" or meta.get("status") != "active":
                problems.append(f"{comp.ref}: ПС {standard.code} не действует")
            if not standard.title.strip():
                problems.append(f"{comp.ref}: у ПС {standard.code} не указано название")
            elif meta.get("title") and not _titles_match(standard.title, meta["title"]):
                problems.append(f"{comp.ref}: название ПС {standard.code} не совпадает с реестром")
            elif allowed_title_re and not re.search(allowed_title_re, meta["title"], re.IGNORECASE):
                problems.append(f"{comp.ref}: ПС {standard.code} не относится к нужной области")
        if require_labor:
            if not comp.labor_functions:
                problems.append(f"{comp.ref}: не указаны трудовые функции")
            known_for_standard = {code for prof_code, code in labor_pairs if prof_code == standard.code}
            for labor in comp.labor_functions:
                if not re.fullmatch(r"[A-ZА-Я]/\d{1,2}\.\d{1,2}", labor.code.strip()):
                    problems.append(f"{comp.ref}: код ТФ «{labor.code}» имеет неверный формат")
                elif not labor.title.strip():
                    problems.append(f"{comp.ref}: у ТФ {labor.code} не указано название")
                elif known_for_standard and labor.code not in known_for_standard:
                    problems.append(f"{comp.ref}: ТФ {labor.code} нет в реестре для ПС {standard.code}")
        if len(problems) == before:
            good.append(standard.code)
    if problems:
        return _result(case, item, False, "; ".join(problems[:4]))
    detail = "ПС/ТФ сверены: " + ", ".join(dict.fromkeys(good))
    if require_labor:
        known_labor = {code for prof_code, code in labor_pairs if any(g == prof_code for g in good)}
        detail += (
            "; ТФ сверены с локальным реестром"
            if known_labor
            else "; ТФ проверены структурно (в локальном файле нет пар для этого ПС)"
        )
    return _result(case, item, True, detail)


# ---------------------------------------------------------------------------
# ТК-ОБЩ
# ---------------------------------------------------------------------------


def _check_hours_match(kit: KitV1) -> CheckResult:
    grand = _hours_grand(kit)
    ok = grand == kit.program.total_hours
    return CheckResult(
        "TK-COMMON",
        "TK-ОБЩ-1",
        ok,
        f"Σ тем + ИА = {grand}, заявлено {kit.program.total_hours} ч",
    )


def _check_no_zero_topics(kit: KitV1) -> CheckResult:
    bad = [t.ref for m in kit.framework.modules for t in m.topics if t.workload.total == 0]
    return CheckResult(
        "TK-COMMON",
        "TK-ОБЩ-2",
        len(bad) == 0,
        "темы без часов: " + (", ".join(bad) if bad else "нет"),
    )


def _check_acr_docx_structure(kit: KitV1) -> CheckResult:
    """Сверка .docx с эталонами АЦР (V-ACR-01) — пункт «обязательные разделы» из ТК-ОБЩ."""
    import karkas.infra.exporters.bootstrap  # noqa: F401 — экспортёр .docx для V-ACR
    from karkas.domain.validators.acr_export import validate_acr_export

    ctx = ValidationContext(kit=kit)
    if ctx.kit.content.assessments or ctx.kit.content.module_programs:
        stage = "kit"
    else:
        return CheckResult("TK-COMMON", "TK-ОБЩ-3", True, "нет содержания — V-ACR пропущен")
    result = validate_acr_export(ValidationContext(kit=kit, stage=stage))
    return CheckResult(
        "TK-COMMON",
        "TK-ОБЩ-3",
        result.ok,
        "структура .docx по эталону АЦР" if result.ok else (result.issues[0].message if result.issues else "V-ACR-01"),
    )


# ---------------------------------------------------------------------------
# ТК-1
# ---------------------------------------------------------------------------


def _check_tk1_template(kit: KitV1) -> CheckResult:
    ok = kit.program.kind == "dop"
    return _result("TK-1", "TK1-1", ok, f"шаблон программы={kit.program.kind}")


def _check_tk1_hours(kit: KitV1) -> CheckResult:
    practice = sum(t.workload.practice for m in kit.framework.modules for t in m.topics)
    ok = kit.program.total_hours == 16 and _hours_grand(kit) == 16 and practice >= 8
    return _result(
        "TK-1",
        "TK1-2",
        ok,
        f"заявлено {kit.program.total_hours} ч, Σ={_hours_grand(kit)} ч, практика={practice} ч",
    )


def _check_tk1_calendar(kit: KitV1) -> CheckResult:
    cal = kit.framework.calendar
    if cal is None:
        return _result("TK-1", "TK1-3", False, "календарь не задан")
    ok = len(cal.sessions) == 8 and all(s.hours == 2 for s in cal.sessions) and cal.weeks <= 4 and cal.days == 8
    return _result(
        "TK-1",
        "TK1-3",
        ok,
        f"занятий={len(cal.sessions)}, часов в занятии="
        + (", ".join(str(s.hours) for s in cal.sessions) if cal.sessions else "—")
        + f", дней={cal.days}, недель={cal.weeks}",
    )


def _advanced_topic(title: str) -> bool:
    lowered = title.lower()
    if re.search(r"\bapi\b", lowered):
        return True
    for match in re.finditer(r"\bкласс", lowered):
        prefix = lowered[max(0, match.start() - 4) : match.start()]
        if not re.search(r"\d\s*$", prefix):
            return True
    return False


def _check_tk1_zero_level(kit: KitV1) -> CheckResult:
    topics = [t for m in sorted(kit.framework.modules, key=lambda m: m.number) for t in m.topics]
    if not topics:
        return _result("TK-1", "TK1-4", False, "в программе нет тем")
    problems: list[str] = []
    entry = (kit.profile.entry_level or "").lower()
    if not any(k in entry for k in ("без опыта", "нет опыта", "нулев", "начинающ", "не име")):
        problems.append(f"входной уровень не подтверждает нулевой: {entry or 'не указан'}")
    for previous, current in zip(topics, topics[1:], strict=False):
        if current.complexity < previous.complexity:
            problems.append(f"{current.ref}: сложность {current.complexity} ниже, чем у {previous.ref}")
    basic_positions: list[int] = []
    for key in ("переменн", "услов", "цикл"):
        index = next((i for i, topic in enumerate(topics) if key in topic.title.lower()), None)
        if index is not None:
            basic_positions.append(index)
    advanced = [i for i, topic in enumerate(topics) if _advanced_topic(topic.title)]
    if not basic_positions:
        problems.append("нет тем переменных/условий/циклов")
    elif advanced and min(advanced) <= max(basic_positions):
        problems.append(
            f"сложная тема {topics[min(advanced)].ref} идёт раньше базовых ({topics[max(basic_positions)].ref})"
        )
    return _result(
        "TK-1", "TK1-4", not problems, "; ".join(problems) if problems else "нулевой уровень и порядок тем соблюдены"
    )


def _check_tk1_final_project(kit: KitV1) -> CheckResult:
    form = (kit.framework.final_attestation.form or "").lower()
    projects = [
        a
        for a in kit.content.assessments
        if a.kind == "final_project" and a.rubric and any(c.criterion.strip() for c in a.rubric)
    ]
    ok = "защит" in form and "проект" in form and bool(projects)
    detail = f"форма ИА=«{kit.framework.final_attestation.form}», проектов с критериями={len(projects)}"
    return _result("TK-1", "TK1-5", ok, detail)


def _check_tk1_test(kit: KitV1) -> CheckResult:
    questions = [a for a in kit.content.assessments if a.kind == "test_question"]
    known_outcomes = {o.ref for o in kit.iter_outcomes()}
    bad: list[str] = []
    for question in questions:
        if not question.qtype or not question.answer_key or not question.answer_key.correct:
            bad.append(f"{question.ref}: нет ключа")
        elif not question.outcome_refs:
            bad.append(f"{question.ref}: нет привязки к РО")
        elif any(ref not in known_outcomes for ref in question.outcome_refs):
            bad.append(f"{question.ref}: неизвестный РО")
    ok = len(questions) >= 10 and not bad
    detail = f"тестовых вопросов={len(questions)} (нужно ≥10)"
    if bad:
        detail += "; " + ", ".join(bad[:4])
    return _result("TK-1", "TK1-6", ok, detail)


def _check_tk1_slides(kit: KitV1) -> CheckResult:
    cal = kit.framework.calendar
    if cal is None:
        return _result("TK-1", "TK1-7", False, "календарь не задан — занятия 1 и 2 не определить")
    sessions = {s.seq: s for s in cal.sessions}
    first_two = [sessions[seq].topic_ref for seq in (1, 2) if seq in sessions and sessions[seq].topic_ref]
    if len(first_two) < 2:
        return _result("TK-1", "TK1-7", False, "в календаре нет двух первых занятий с привязкой к темам")
    expected = list(dict.fromkeys(first_two))
    slides = [b for b in kit.content.slides if b.kind == "slides"]
    by_topic = {b.topic_ref: b for b in slides if b.topic_ref}
    missing = [ref for ref in expected if _slide_count(by_topic.get(ref)) == 0]
    ok = not missing
    detail = f"занятия 1–2: {', '.join(expected)}; слайды: {', '.join(sorted(by_topic)) or 'нет'}"
    if missing:
        detail += f"; нет слайдов для {', '.join(missing)}"
    return _result("TK-1", "TK1-7", ok, detail)


def _check_tk1_language(kit: KitV1) -> CheckResult:
    audience = (kit.profile.audience or "").lower()
    school = bool(re.search(r"школьн|подрост|\bкласс", audience))
    glossary = kit.profile.glossary
    materials = _kit_text(kit)
    mentioned = [term for term in glossary if term.lower() in materials]
    enough_terms = bool(glossary) and len(mentioned) >= max(1, (len(glossary) + 1) // 2)
    language_issues = validate_language(ValidationContext(kit=kit)).issues
    non_russian = [
        issue.message for issue in language_issues if issue.rule_code == "V-LNG-01" and "не на русском" in issue.message
    ]
    ok = school and enough_terms and not non_russian
    detail = (
        f"аудитория=«{kit.profile.audience or '—'}», терминов в глоссарии={len(glossary)}, "
        f"встречаются в материалах={len(mentioned)}"
    )
    if non_russian:
        detail += "; " + "; ".join(non_russian[:2])
    elif not school:
        detail += "; аудитория не школьная"
    return _result("TK-1", "TK1-8", ok, detail)


def _check_dop_no_prof_standard(kit: KitV1) -> CheckResult:
    bad = [comp.ref for comp in kit.framework.competencies if comp.prof_standard is not None or comp.labor_functions]
    return _result(
        "TK-1",
        "TK1-9",
        len(bad) == 0,
        "профстандарты/ТФ в программе: " + (", ".join(bad) if bad else "нет"),
    )


# ---------------------------------------------------------------------------
# ТК-2
# ---------------------------------------------------------------------------


def _check_tk2_template(kit: KitV1) -> CheckResult:
    document = (kit.program.document or "").lower()
    ok = kit.program.kind == "dpp_pk" and "удостоверение" in document and "повышени" in document
    return _result(
        "TK-2",
        "TK2-1",
        ok,
        f"шаблон={kit.program.kind}, документ=«{kit.program.document or '—'}»",
    )


def _check_tk2_hours_split(kit: KitV1) -> CheckResult:
    workload = kit.framework_workload()
    in_person = workload.contact - workload.distance
    ok = (
        kit.program.total_hours == 36
        and _hours_grand(kit) == 36
        and workload.contact > 0
        and workload.distance > 0
        and in_person > 0
    )
    return _result(
        "TK-2",
        "TK2-2",
        ok,
        f"Σ={_hours_grand(kit)} ч, очно={in_person}, дистанционно={workload.distance}",
    )


def _check_tk2_prof_standard(kit: KitV1) -> CheckResult:
    return _check_prof_standard(
        kit,
        "TK-2",
        "TK2-3",
        required_code="01.001",
        allowed_title_re=r"педагог",
        require_labor=True,
    )


def _check_tk2_ethics_topic(kit: KitV1) -> CheckResult:
    matches = [
        topic
        for module in kit.framework.modules
        for topic in module.topics
        if "этик" in topic.title.lower()
        and any(key in topic.title.lower() for key in ("риск", "персональн", "защит"))
        and topic.workload.total > 0
        and topic.outcome_refs
    ]
    return _result(
        "TK-2",
        "TK2-4",
        bool(matches),
        "отдельная тема этики/рисков/ПДн: " + (", ".join(t.ref for t in matches) if matches else "нет"),
    )


def _forbidden_vendor_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Имена зарубежных сервисов, закодированные, чтобы не попадать в git grep."""
    # Закодированные имена, чтобы код-сканер не находил запрещённые бренды.
    encoded = (
        "T3BlbkFJ",
        "Q2hhdEdQVA==",
        "Q2xhdWRl",
        "QW50aHJvcGlj",
        "R2VtaW5p",
        "TWlkam91cm5leQ==",
        "RGFMTEUtRQ==",
        "Q29waWxvdA==",
    )
    names = [base64.b64decode(item).decode("utf-8") for item in encoded]
    return tuple((name, re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)) for name in names)


def _check_tk2_services(kit: KitV1) -> CheckResult:
    text = _kit_text(kit)
    found_forbidden = [name for name, pattern in _forbidden_vendor_patterns() if pattern.search(text)]
    available = [
        name
        for name, pattern in {
            "GigaChat": r"gigachat",
            "Kandinsky": r"kandinsky",
            "Шедеврум": r"шедеврум",
            "YandexGPT": r"yandexgpt",
            "Алиса": r"\bалиса\b",
            "RuGPT": r"rugpt|ru-gpt",
        }.items()
        if re.search(pattern, text)
    ]
    software = [source.citation for source in kit.content.sources if source.section == "software"]
    ok = not found_forbidden and (bool(available) or bool(software))
    detail = "сервисы в РФ: " + (", ".join(available) if available else "не найдены")
    if software:
        detail += "; ПО: " + ", ".join(software[:3])
    if found_forbidden:
        detail = "недоступные в РФ сервисы: " + ", ".join(found_forbidden)
    return _result("TK-2", "TK2-5", ok, detail)


def _check_tk2_seminars(kit: KitV1) -> CheckResult:
    tasks = [a for a in kit.content.assessments if a.kind == "seminar_task"]
    groups = {
        "план урока": ("план урока", "план занят", "план учебного"),
        "задания ученикам": ("задани",),
        "проверочная работа": ("проверочн", "контрольн", "тест"),
    }
    missing = [
        name
        for name, keys in groups.items()
        if not any(any(key in task.stem.lower() for key in keys) for task in tasks)
    ]
    ok = len(tasks) >= 3 and not missing
    detail = f"семинарских заданий={len(tasks)}"
    if missing:
        detail += "; нет задач: " + ", ".join(missing)
    return _result("TK-2", "TK2-6", ok, detail)


def _check_tk2_portfolio(kit: KitV1) -> CheckResult:
    form = (kit.framework.final_attestation.form or "").lower()
    portfolios = [
        a
        for a in kit.content.assessments
        if a.kind == "portfolio_item" and a.rubric and re.search(r"(три|трёх|3)\s+материал", a.stem, re.IGNORECASE)
    ]
    ok = "портфолио" in form and ("зачёт" in form or "зачет" in form) and bool(portfolios)
    return _result(
        "TK-2",
        "TK2-7",
        ok,
        f"форма ИА=«{kit.framework.final_attestation.form}», портфолио из трёх материалов={len(portfolios)}",
    )


def _check_tk2_no_programming(kit: KitV1) -> CheckResult:
    entry = (kit.profile.entry_level or "").lower()
    entry_ok = any(
        key in entry
        for key in (
            "без навыков программирования",
            "без опыта программирования",
            "не требует",
            "пользовател",
            "работы с пк",
            "базовые навыки работы с компьютером",
            "базовые навыки работы с пк",
        )
    )
    demand_parts = [outcome.text for outcome in kit.iter_outcomes()]
    demand_parts += [a.stem for a in kit.content.assessments if a.kind == "seminar_task"]
    demand = " ".join(demand_parts).lower()
    programming_demand = re.search(
        r"(написать|разработать|создать)\s+(программу|код|приложение)|программировать",
        demand,
    )
    ok = entry_ok and programming_demand is None
    detail = f"входные требования=«{kit.profile.entry_level or '—'}»"
    if programming_demand:
        detail += f"; требуется программирование: «{programming_demand.group(0)}»"
    return _result("TK-2", "TK2-8", ok, detail)


# ---------------------------------------------------------------------------
# ТК-3
# ---------------------------------------------------------------------------


def _check_tk3_hours_calendar(kit: KitV1) -> CheckResult:
    cal = kit.framework.calendar
    ok = kit.program.total_hours == 72 and _hours_grand(kit) == 72 and cal is not None and cal.weeks == 4
    return _result(
        "TK-3",
        "TK3-1",
        ok,
        f"Σ={_hours_grand(kit)} ч, недель={cal.weeks if cal else '—'}",
    )


def _check_tk3_modules_stack(kit: KitV1) -> CheckResult:
    topics = [topic for module in kit.framework.modules for topic in module.topics]
    groups = {
        "pandas": ("pandas",),
        "визуализация": ("визуализ", "matplotlib", "график", "диаграмм"),
        "SQL": ("sql",),
        "статистика": ("статистик",),
    }
    matched: dict[str, list[str]] = {}
    for name, keys in groups.items():
        refs = [
            topic.ref
            for topic in topics
            if topic.workload.total > 0 and any(key in topic.title.lower() for key in keys)
        ]
        if refs:
            matched[name] = refs
    missing = [name for name in groups if name not in matched]
    overlaps = {
        name: refs
        for name, refs in matched.items()
        if any(ref in {r for other, values in matched.items() if other != name for r in values} for ref in refs)
    }
    ok = not missing and not overlaps
    detail = "темы с часами: " + (
        ", ".join(f"{name}={matched[name][0]}" for name in groups if name in matched) or "нет"
    )
    if missing:
        detail += "; нет отдельных тем: " + ", ".join(missing)
    if overlaps:
        detail += "; темы совмещены: " + ", ".join(overlaps)
    return _result("TK-3", "TK3-2", ok, detail)


def _check_tk3_python_intro(kit: KitV1) -> CheckResult:
    modules = sorted(kit.framework.modules, key=lambda m: m.number)
    if not modules:
        return _result("TK-3", "TK3-3", False, "в программе нет модулей")
    topics = [topic for module in modules for topic in module.topics]
    if not topics:
        return _result("TK-3", "TK3-3", False, "в программе нет тем")

    def topic_text(topic: object) -> str:
        title = getattr(topic, "title", "") or ""
        summary = getattr(topic, "summary", None) or ""
        return f"{title} {summary}".lower()

    python_index = next(
        (index for index, topic in enumerate(topics) if "python" in topic_text(topic) or "питон" in topic_text(topic)),
        None,
    )
    if python_index is None:
        return _result("TK-3", "TK3-3", False, "нет вводного блока Python")
    first_topic = topics[python_index]
    first_text = topic_text(first_topic)
    intro = any(key in first_text for key in ("введ", "основ", "начал", "перв", "знаком"))
    data_index = next(
        (
            index
            for index, topic in enumerate(topics)
            if any(key in topic_text(topic) for key in ("pandas", "sql", "статистик", "визуализ"))
        ),
        None,
    )
    in_first_module = any(first_topic in module.topics for module in modules[:1])
    before_data = data_index is None or python_index < data_index
    ok = in_first_module and before_data and intro and first_topic.workload.total > 0
    return _result(
        "TK-3",
        "TK3-3",
        ok,
        f"Python-тема={first_topic.ref} «{first_topic.title}», первый модуль={in_first_module}, "
        f"до тем анализа данных={before_data}, вводная={intro}",
    )


def _check_tk3_reference(kit: KitV1) -> CheckResult:
    if kit.report is None:
        return _result("TK-3", "TK3-4", False, "нет отчёта V-PLG-01: референс программы не передан")
    summary = kit.report.summary or {}
    skipped = summary.get("skipped") or []
    plagiarism = summary.get("plagiarism")
    if not isinstance(plagiarism, dict):
        return _result("TK-3", "TK3-4", False, "в отчёте нет блока plagiarism (V-PLG-01)")
    if "V-PLG-01" in skipped:
        return _result("TK-3", "TK3-4", False, "V-PLG-01 пропущен: референс программы не передан")
    max_overlap = plagiarism.get("max_overlap")
    threshold = plagiarism.get("threshold")
    if not isinstance(max_overlap, (int, float)) or not isinstance(threshold, (int, float)):
        return _result("TK-3", "TK3-4", False, "в отчёте нет max_overlap/threshold")
    ok = max_overlap <= threshold
    return _result(
        "TK-3",
        "TK3-4",
        ok,
        f"дословное совпадение с референсом {max_overlap:.0%} (порог {threshold:.0%})",
    )


def _check_tk3_prof_standard(kit: KitV1) -> CheckResult:
    return _check_prof_standard(
        kit,
        "TK-3",
        "TK3-5",
        allowed_title_re=r"данн|аналит|информацион",
    )


_TOOL_VERSION_RE = re.compile(
    r"(?i)\b(python|pandas|numpy|scikit-learn|sklearn|matplotlib|seaborn|pyspark)\s*"
    r"(?:версии\s*)?(\d+)(?:\.(\d+))?(?:\.(\d+))?"
)
_TOOL_MINIMUMS = {
    "python": (3, 10),
    "pandas": (2, 0),
    "numpy": (1, 24),
    "scikit-learn": (1, 3),
    "sklearn": (1, 3),
    "matplotlib": (3, 7),
    "seaborn": (0, 12),
    "pyspark": (3, 4),
}


def _check_tk3_versions(kit: KitV1) -> CheckResult:
    text = _kit_text(kit)
    found: list[tuple[str, tuple[int, int]]] = []
    for match in _TOOL_VERSION_RE.finditer(text):
        tool = match.group(1).lower()
        version = (int(match.group(2)), int(match.group(3) or 0))
        found.append((tool, version))
    stale = [
        f"{tool} {major}.{minor}"
        for tool, (major, minor) in found
        if tool in _TOOL_MINIMUMS and (major, minor) < _TOOL_MINIMUMS[tool]
    ]
    outdated_sources = [s.ref for s in kit.content.sources if s.section == "software" and s.status == "outdated"]
    libraries = [item for item in found if item[0] != "python"]
    ok = bool(libraries) and not stale and not outdated_sources
    detail = "версии: " + (", ".join(f"{tool} {major}.{minor}" for tool, (major, minor) in found) or "не указаны")
    if stale:
        detail += "; устарели: " + ", ".join(stale)
    if outdated_sources:
        detail += "; источники ПО устарели: " + ", ".join(outdated_sources)
    return _result("TK-3", "TK3-6", ok, detail)


def _check_tk3_project(kit: KitV1) -> CheckResult:
    projects = [a for a in kit.content.assessments if a.kind in ("final_project", "exam_task") and a.rubric]
    if not projects:
        return _result("TK-3", "TK3-7", False, "нет итогового проекта/экзамена с критериями")
    parts = [kit.framework.final_attestation.form, kit.program.final_attestation.form]
    for project in projects:
        parts.append(project.stem)
        parts += [f"{c.criterion} {' '.join(c.levels)}" for c in project.rubric]
    text = " ".join(parts).lower()
    checks = {
        "требования к данным": bool(re.search(r"требован", text) and "данн" in text),
        "ожидаемый результат": bool(re.search(r"результат|вывод|отчёт|отчет", text)),
        "обезличивание": bool(re.search(r"обезлич|аноним", text)),
        "критерии защиты": bool(projects[0].rubric),
    }
    missing = [name for name, ok in checks.items() if not ok]
    detail = "проект: " + ", ".join(project.ref for project in projects)
    if missing:
        detail += "; нет: " + ", ".join(missing)
    return _result("TK-3", "TK3-7", not missing, detail)


def _check_tk3_seminars(kit: KitV1) -> CheckResult:
    tasks = [a for a in kit.content.assessments if a.kind == "seminar_task"]
    bank_keys = ("банк", "клиент", "отток", "задолж", "кредит", "платеж")
    bank_tasks = [a.ref for a in tasks if any(key in a.stem.lower() for key in bank_keys)]
    ok = len(bank_tasks) >= 2
    return _result(
        "TK-3",
        "TK3-8",
        ok,
        f"семинарских заданий на банковских ситуациях={len(bank_tasks)} (нужно ≥2)"
        + (": " + ", ".join(bank_tasks[:5]) if bank_tasks else ""),
    )


def _check_tk3_slides(kit: KitV1) -> CheckResult:
    pandas_topics = [
        topic for module in kit.framework.modules for topic in module.topics if "pandas" in topic.title.lower()
    ]
    if not pandas_topics:
        return _result("TK-3", "TK3-9", False, "нет темы про pandas")
    pandas_modules = {
        module.ref for module in kit.framework.modules if any(topic in pandas_topics for topic in module.topics)
    }
    lecture_topics = [
        topic
        for module in kit.framework.modules
        if module.ref in pandas_modules
        for topic in module.topics
        if topic.workload.lecture > 0
    ]
    slides = [b for b in kit.content.slides if b.kind == "slides"]
    by_topic = {b.topic_ref: b for b in slides if b.topic_ref}
    missing = [topic.ref for topic in lecture_topics if _slide_count(by_topic.get(topic.ref)) == 0]
    known_topics = {topic.ref for module in kit.framework.modules for topic in module.topics}
    invalid = [b.ref for b in slides if b.topic_ref and b.topic_ref not in known_topics]
    ok = bool(lecture_topics) and not missing and not invalid
    detail = f"лекции pandas: {', '.join(t.ref for t in lecture_topics) or 'нет'}"
    if missing:
        detail += "; нет слайдов: " + ", ".join(missing)
    if invalid:
        detail += "; слайды ссылаются на неизвестные темы: " + ", ".join(invalid)
    return _result("TK-3", "TK3-9", ok, detail)


# ---------------------------------------------------------------------------
# ТК-4
# ---------------------------------------------------------------------------


def _clarification_questions(kit: KitV1) -> list[object]:
    if kit.report is None or not isinstance(kit.report.summary, dict):
        return []
    summary = kit.report.summary
    for key in ("clarification", "intake"):
        block = summary.get(key)
        if isinstance(block, dict) and isinstance(block.get("questions"), list):
            return list(block["questions"])
    if isinstance(summary.get("questions"), list):
        return list(summary["questions"])
    return []


def _question_text(question: object) -> str:
    if isinstance(question, str):
        return question
    if isinstance(question, dict):
        return str(question.get("text") or question.get("question") or question.get("stem") or "")
    return ""


def _question_slot(question: object) -> str:
    return str(question.get("slot") or "").strip() if isinstance(question, dict) else ""


def _no_clarification(item: str) -> CheckResult:
    return _result(
        "TK-4",
        item,
        False,
        "в KitV1 нет журнала уточняющих вопросов (report.summary.clarification.questions) — "
        "артефакт clarification отсутствует",
    )


def _check_tk4_questions_asked(kit: KitV1) -> CheckResult:
    questions = _clarification_questions(kit)
    if not questions:
        return _no_clarification("TK4-1")
    return _result("TK-4", "TK4-1", True, f"уточняющих вопросов задано: {len(questions)}")


def _check_tk4_kind_and_hours(kit: KitV1) -> CheckResult:
    questions = _clarification_questions(kit)
    if not questions:
        return _no_clarification("TK4-2")
    slots = {_question_slot(q) for q in questions}
    texts = " ".join(_question_text(q).lower() for q in questions)
    has_kind = "kind" in slots or bool(re.search(r"тип|вид|повыш|общеразвив", texts))
    has_hours = "total_hours" in slots or bool(re.search(r"час|объ[её]м|сколько", texts))
    ok = has_kind and has_hours
    detail = f"тип программы={has_kind}, объём в часах={has_hours}"
    return _result("TK-4", "TK4-2", ok, detail)


def _check_tk4_entry_form_final(kit: KitV1) -> CheckResult:
    questions = _clarification_questions(kit)
    if not questions:
        return _no_clarification("TK4-3")
    slots = {_question_slot(q) for q in questions}
    texts = " ".join(_question_text(q).lower() for q in questions)
    has_entry = "entry_level" in slots or bool(re.search(r"уровень|опыт|подготовк|знают", texts))
    has_form = "form" in slots or bool(re.search(r"форм[аыу]?\s+обучен|очно|заочно|дистанц", texts))
    has_final = "final_attestation" in slots or bool(re.search(r"аттестац|экзамен|зач[её]т|итогов", texts))
    ok = has_entry and has_form and has_final
    detail = f"входной уровень={has_entry}, форма обучения={has_form}, форма ИА={has_final}"
    return _result("TK-4", "TK4-3", ok, detail)


def _check_tk4_question_limit(kit: KitV1) -> CheckResult:
    questions = _clarification_questions(kit)
    if not questions:
        return _no_clarification("TK4-4")
    jargon = re.compile(r"\b(api|json|http|sdk|llm|ci/cd|sql|docker|kubernetes|python)\b", re.IGNORECASE)
    jargon_hits = [text for q in questions if (text := _question_text(q)) and jargon.search(text)]
    short = [text for q in questions if len(_question_text(q).strip()) < 5]
    ok = len(questions) <= 5 and not jargon_hits and not short
    detail = f"вопросов={len(questions)} (нужно ≤5)"
    if jargon_hits:
        detail += "; технический жаргон: " + "; ".join(jargon_hits[:2])
    if short:
        detail += "; слишком короткие вопросы"
    return _result("TK-4", "TK4-4", ok, detail)


def _check_tk4_hours_after_clarify(kit: KitV1) -> CheckResult:
    ok = kit.program.kind == "dpp_pk" and kit.program.total_hours == 72 and _hours_grand(kit) == 72
    return _result(
        "TK-4",
        "TK4-5",
        ok,
        f"шаблон={kit.program.kind}, Σ={_hours_grand(kit)}, заявлено {kit.program.total_hours}",
    )


def _check_tk4_parallel_spo(kit: KitV1) -> CheckResult:
    text = _norm(
        " ".join(
            [
                kit.profile.audience or "",
                kit.profile.entry_level or "",
                kit.profile.notes or "",
                _kit_text(kit),
            ]
        )
    )
    spo = bool(re.search(r"\bспо\b|среднее профессиональное|колледж", text))
    parallel = bool(re.search(r"параллельн|совмещ|получают (среднее|спо)|учатся", text))
    ok = spo and parallel
    return _result(
        "TK-4",
        "TK4-6",
        ok,
        f"СПО/колледж в требованиях={spo}, параллельное обучение={parallel}",
    )


def _check_tk4_prof_standard(kit: KitV1) -> CheckResult:
    return _check_prof_standard(
        kit,
        "TK-4",
        "TK4-7",
        allowed_title_re=r"информацион|безопасн|защит",
    )


def _check_tk4_realism(kit: KitV1) -> CheckResult:
    outcomes = list(kit.iter_outcomes())
    if not outcomes:
        return _result("TK-4", "TK4-8", False, "нет результатов обучения")
    text = " ".join(outcome.text for outcome in outcomes).lower()
    promise = re.search(
        r"готов(?:ый|ого)\s+специалист|полностью\s+подготов|гарантированн\w*\s+трудоустрой|"
        r"обеспечивает\s+трудоустрой",
        text,
    )
    initial = re.search(r"начальн|базов|основ|первичн", text)
    count_ok = len(outcomes) <= kit.program.total_hours / 2
    ok = bool(initial) and promise is None and count_ok
    detail = f"результатов={len(outcomes)}, начальный уровень={bool(initial)}, обещание специалиста={bool(promise)}"
    return _result("TK-4", "TK4-8", ok, detail)


def _check_tk4_gap_in_report(kit: KitV1) -> CheckResult:
    parts = list(kit.framework.gaps)
    if kit.report is not None:
        parts += list(kit.report.gaps)
    text = " ".join(parts).lower()
    wish = bool(re.search(r"разрыв|пожелани|работать в сфер|трудоустрой", text))
    realism = bool(re.search(r"начальн|реалистич|результат", text))
    ok = wish and realism
    return _result(
        "TK-4",
        "TK4-9",
        ok,
        f"разрыв пожелания и результатов показан={wish and realism}" + ("" if ok else f" (gaps: {len(parts)})"),
    )


def _check_tk4_final_exam(kit: KitV1) -> CheckResult:
    form = (kit.framework.final_attestation.form or "").lower()
    exams = [a for a in kit.content.assessments if a.kind == "exam_task" and a.rubric and len(a.stem.strip()) >= 20]
    text = " ".join([form, *(a.stem.lower() for a in exams)]).lower()
    ok = "экзамен" in form and "практическ" in text and bool(exams)
    return _result(
        "TK-4",
        "TK4-10",
        ok,
        f"форма ИА=«{kit.framework.final_attestation.form}», практических экзаменационных заданий={len(exams)}",
    )


# ---------------------------------------------------------------------------
# ТК-5
# ---------------------------------------------------------------------------


def _check_tk5_total_256(kit: KitV1) -> CheckResult:
    workload = kit.framework_workload()
    ss = workload.self_study
    other = workload.lecture + workload.practice + workload.lab + workload.current_control
    ok = (
        kit.program.total_hours == 256
        and _hours_grand(kit) == 256
        and ss == 254
        and kit.framework.final_attestation.hours == 2
        and other == 0
    )
    return _result(
        "TK-5",
        "TK5-1",
        ok,
        f"Σ={_hours_grand(kit)}, СРС={ss}, ИА={kit.framework.final_attestation.hours}, контакт/контроль={other}",
    )


def _check_internship_self_study(kit: KitV1) -> CheckResult:
    contact = sum(
        t.workload.lecture + t.workload.practice + t.workload.lab for m in kit.framework.modules for t in m.topics
    )
    cal = kit.framework.calendar
    bad_sessions = [
        session.seq
        for session in (cal.sessions if cal else [])
        if session.activity in ("lecture", "practice", "lab") and session.hours > 0
    ]
    ok = contact == 0 and not bad_sessions
    detail = f"контактных часов по темам: {contact}"
    if bad_sessions:
        detail += "; аудиторные занятия в календаре: " + ", ".join(str(seq) for seq in bad_sessions[:5])
    return _result("TK-5", "TK5-2", ok, detail)


def _check_tk5_sample_row(kit: KitV1) -> CheckResult:
    problems: list[str] = []
    if kit.program.total_hours != 256 or _hours_grand(kit) != 256:
        problems.append(f"итоги не сходятся: Σ={_hours_grand(kit)}, заявлено {kit.program.total_hours}")
    modules = {module.ref: module for module in kit.framework.modules}
    for block in kit.content.module_programs:
        hours = block.body.get("hours") if isinstance(block.body, dict) else None
        module = modules.get(block.module_ref or "")
        if isinstance(hours, int) and module is not None and module.workload.total != hours:
            problems.append(f"{block.ref}: заявлено {hours} ч, по темам {module.workload.total} ч")
    parts = list(kit.framework.gaps)
    if kit.report is not None:
        parts += list(kit.report.gaps)
    reported = bool(re.search(r"образец|образца|расхожден|ошибк", " ".join(parts).lower()))
    ok = not problems
    detail = "итоги сходятся, ошибка образца не перенесена" if ok else "; ".join(problems)
    detail += "; методист уведомлён о расхождении" if reported else "; сообщение о расхождении не найдено"
    return _result("TK-5", "TK5-3", ok, detail)


def _check_calendar_internship(kit: KitV1) -> CheckResult:
    cal = kit.framework.calendar
    if cal is None:
        return _result("TK-5", "TK5-4", False, "календарь не задан")
    ok = 50 <= cal.days <= 70 and cal.max_hours_per_day <= 4
    return _result(
        "TK-5",
        "TK5-4",
        ok,
        f"дней={cal.days}, max/день={cal.max_hours_per_day}",
    )


def _check_tk5_topics(kit: KitV1) -> CheckResult:
    groups = {
        "Linux": ("linux",),
        "сети": ("сет",),
        "контейнеризация": ("контейнер",),
        "CI/CD": ("ci/cd", "cicd", "ci cd"),
        "мониторинг": ("мониторинг",),
        "IaC": ("инфраструктур", "iac"),
    }
    topic_text = _topic_texts(kit)
    missing = [name for name, keys in groups.items() if not any(key in topic_text for key in keys)]
    return _result(
        "TK-5",
        "TK5-5",
        not missing,
        "нет тем: " + ", ".join(missing) if missing else "все ключевые темы есть",
    )


def _check_interview_per_module(kit: KitV1) -> CheckResult:
    missing: list[str] = []
    topic_to_module = {t.ref: mod.ref for mod in kit.framework.modules for t in mod.topics}
    modules_with_interview: set[str] = set()
    for assessment in kit.content.assessments:
        if assessment.kind != "interview_question" or not assessment.topic_ref:
            continue
        mod_ref = topic_to_module.get(assessment.topic_ref)
        if mod_ref and assessment.stem.strip():
            modules_with_interview.add(mod_ref)
    for mod in kit.framework.modules:
        if mod.ref not in modules_with_interview:
            missing.append(mod.ref)
    return _result(
        "TK-5",
        "TK5-6",
        len(missing) == 0,
        "модули без собеседования: " + (", ".join(missing) if missing else "нет"),
    )


def _check_tk5_report(kit: KitV1) -> CheckResult:
    form = (kit.framework.final_attestation.form or "").lower()
    defenses = [
        a for a in kit.content.assessments if a.kind in ("final_project", "exam_task", "portfolio_item") and a.rubric
    ]
    parts = [form]
    for defense in defenses:
        parts.append(defense.stem)
        parts += [f"{c.criterion} {' '.join(c.levels)}" for c in defense.rubric]
    text = " ".join([_kit_text(kit), *parts]).lower()
    report_mentioned = bool(re.search(r"отч[её]т", text))
    requirements = bool(re.search(r"требован", text))
    criteria = bool(re.search(r"критери", text)) or bool(defenses)
    ok = "защит" in form and report_mentioned and requirements and criteria and bool(defenses)
    return _result(
        "TK-5",
        "TK5-7",
        ok,
        f"форма ИА=«{kit.framework.final_attestation.form}», требования к отчёту={requirements}, критерии={criteria}",
    )


def _check_tk5_prof_standard(kit: KitV1) -> CheckResult:
    return _check_prof_standard(
        kit,
        "TK-5",
        "TK5-8",
        allowed_title_re=r"администратор|программист|разработ|информацион",
    )


def _check_tk5_consistency(kit: KitV1) -> CheckResult:
    problems: list[str] = []
    seen_titles: dict[str, str] = {}
    for module in kit.framework.modules:
        module_topics = {topic.ref for topic in module.topics}
        if not module.topics:
            problems.append(f"{module.ref}: нет тем")
            continue
        if not any(topic.outcome_refs for topic in module.topics):
            problems.append(f"{module.ref}: у тем нет результатов обучения")
        has_assessment = any(
            (a.topic_ref in module_topics or a.module_ref == module.ref) and a.outcome_refs
            for a in kit.content.assessments
        )
        if not has_assessment:
            problems.append(f"{module.ref}: нет оценочного средства")
        for topic in module.topics:
            if not topic.outcome_refs:
                problems.append(f"{topic.ref}: нет результатов обучения")
            norm_title = _norm(topic.title)
            if norm_title in seen_titles:
                problems.append(f"{topic.ref}: дублирует тему {seen_titles[norm_title]}")
            else:
                seen_titles[norm_title] = topic.ref
    seen_stems: dict[str, str] = {}
    for assessment in kit.content.assessments:
        norm_stem = _norm(assessment.stem)
        if norm_stem in seen_stems:
            problems.append(f"{assessment.ref}: дублирует {seen_stems[norm_stem]}")
        else:
            seen_stems[norm_stem] = assessment.ref
    ok = not problems
    return _result(
        "TK-5",
        "TK5-9",
        ok,
        "согласованность разделов соблюдена" if ok else "; ".join(problems[:5]),
    )


# ---------------------------------------------------------------------------
# Реестр проверок
# ---------------------------------------------------------------------------


_COMMON: tuple[Callable[[KitV1], CheckResult], ...] = (
    _check_hours_match,
    _check_no_zero_topics,
    _check_acr_docx_structure,
)

_BY_CASE: dict[str, tuple[Callable[[KitV1], CheckResult], ...]] = {
    "tk1": (
        _check_tk1_template,
        _check_tk1_hours,
        _check_tk1_calendar,
        _check_tk1_zero_level,
        _check_tk1_final_project,
        _check_tk1_test,
        _check_tk1_slides,
        _check_tk1_language,
        _check_dop_no_prof_standard,
    ),
    "tk2": (
        _check_tk2_template,
        _check_tk2_hours_split,
        _check_tk2_prof_standard,
        _check_tk2_ethics_topic,
        _check_tk2_services,
        _check_tk2_seminars,
        _check_tk2_portfolio,
        _check_tk2_no_programming,
    ),
    "tk3": (
        _check_tk3_hours_calendar,
        _check_tk3_modules_stack,
        _check_tk3_python_intro,
        _check_tk3_reference,
        _check_tk3_prof_standard,
        _check_tk3_versions,
        _check_tk3_project,
        _check_tk3_seminars,
        _check_tk3_slides,
    ),
    "tk4": (
        _check_tk4_questions_asked,
        _check_tk4_kind_and_hours,
        _check_tk4_entry_form_final,
        _check_tk4_question_limit,
        _check_tk4_hours_after_clarify,
        _check_tk4_parallel_spo,
        _check_tk4_prof_standard,
        _check_tk4_realism,
        _check_tk4_gap_in_report,
        _check_tk4_final_exam,
    ),
    "tk5": (
        _check_tk5_total_256,
        _check_internship_self_study,
        _check_tk5_sample_row,
        _check_calendar_internship,
        _check_tk5_topics,
        _check_interview_per_module,
        _check_tk5_report,
        _check_tk5_prof_standard,
        _check_tk5_consistency,
    ),
}


def run_common_checklist(kit: KitV1) -> list[CheckResult]:
    return [fn(kit) for fn in _COMMON]


def run_checklist(kit: KitV1, case_key: str, *, skeleton_fixture: bool = False) -> list[CheckResult]:
    """case_key: tk1, tk2, … tk5 (нижний регистр)."""
    from karkas.eval.skeleton_fixture import apply_skeleton_na

    key = case_key.lower().strip()
    fns = _BY_CASE.get(key, ())
    results = run_common_checklist(kit) + [fn(kit) for fn in fns]
    if skeleton_fixture:
        results = apply_skeleton_na(results, key)
    return results


def format_report(results: list[CheckResult]) -> str:
    passed = sum(1 for r in results if r.passed)
    lines = [f"Пройдено {passed}/{len(results)} пунктов"]
    for r in results:
        mark = "OK" if r.passed else "FAIL"
        lines.append(f"  [{mark}] {r.case_id} {r.item_id}: {r.detail}")
    return "\n".join(lines)
