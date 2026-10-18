"""Официальные открытые запросы ТК-1…ТК-5 (хаб «Точка сборки», кейс №1).

Полные тексты — data/eval/test_cases_official.txt; чек-листы — karkas.eval.checklists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

OFFICIAL_TXT = Path(__file__).resolve().parents[2] / "data" / "eval" / "test_cases_official.txt"


@dataclass(frozen=True)
class ChecklistItem:
    item_id: str
    text: str


@dataclass(frozen=True)
class OfficialCase:
    case_id: str
    title: str
    request_text: str
    checklist: tuple[ChecklistItem, ...]


def _load_request_texts() -> dict[str, str]:
    if not OFFICIAL_TXT.is_file():
        return {}
    raw = OFFICIAL_TXT.read_text(encoding="utf-8")
    out: dict[str, str] = {}
    chunks = re.split(r"(?m)^Запрос\s+(\d+)\.\s+", raw)
    for index in range(1, len(chunks), 2):
        num = chunks[index]
        block = chunks[index + 1]
        match = re.search(
            r"Текст запроса\s*\n(.*?)(?=\n(?:Приложения|Ответы методиста|Эталонный чек-лист)|\Z)",
            block,
            flags=re.DOTALL,
        )
        if not match:
            continue
        body = " ".join(line.strip() for line in match.group(1).strip().splitlines() if line.strip())
        out[f"tk{num}"] = body
    return out


_REQUESTS = _load_request_texts()

TK1 = OfficialCase(
    case_id="tk1",
    title="«Первые шаги в Python» для школьников",
    request_text=_REQUESTS.get(
        "tk1",
        "Нужна дополнительная общеразвивающая программа «Первые шаги в Python» для школьников "
        "8 и 9 классов без опыта программирования. Объем 16 часов, занятия очно по 2 часа "
        "два раза в неделю. Практики должно быть не меньше половины всех часов. "
        "В конце каждый ученик защищает небольшой проект, например простую игру или чат-бота. "
        "Нужны итоговый тест на 10 вопросов и слайды для первых двух занятий.",
    ),
    checklist=(
        ChecklistItem("TK1-1", "Выбран шаблон общеразвивающей программы, а не программы повышения квалификации."),
        ChecklistItem("TK1-2", "Общий объем равен ровно 16 часам, из них практических занятий не меньше 8 часов."),
        ChecklistItem("TK1-3", "Календарный график состоит из 8 занятий по 2 часа и укладывается в 4 недели."),
        ChecklistItem("TK1-9", "В программе нет привязки к профстандартам и трудовым функциям."),
    ),
)

TK2 = OfficialCase(
    case_id="tk2",
    title="«Искусственный интеллект в работе учителя»",
    request_text=_REQUESTS.get(
        "tk2",
        "Программа повышения квалификации «Искусственный интеллект в работе учителя» для учителей "
        "школ Ингушетии, 36 часов, очно-заочно с применением дистанционных технологий.",
    ),
    checklist=(
        ChecklistItem("TK2-1", "Шаблон программы повышения квалификации, удостоверение о ПК."),
        ChecklistItem("TK2-2", "36 часов; очная и дистанционная работа разделены явно."),
        ChecklistItem("TK2-3", "Компетенции связаны с трудовыми функциями профстандарта «Педагог»."),
        ChecklistItem("TK2-4", "Отдельная тема о рисках, этике и защите персональных данных учеников."),
    ),
)

TK3 = OfficialCase(
    case_id="tk3",
    title="«Анализ данных на Python» для сотрудников банков",
    request_text=_REQUESTS.get(
        "tk3",
        "Нужна программа повышения квалификации на 72 часа «Анализ данных на Python» для сотрудников "
        "региональных отделений банков, которые сейчас работают в Excel. Формат очно-заочный, срок 4 недели. "
        "Основные темы это pandas, визуализация, SQL для выгрузки данных и основы статистики. "
        "Итоговая аттестация в виде защиты проекта на обезличенных банковских данных. "
        "Прикладываю нашу прошлую программу, структуру можно взять оттуда, но содержание нужно новое. "
        "Слайды нужны для модуля про pandas.",
    ),
    checklist=(
        ChecklistItem("TK3-1", "72 часа; календарный график на 4 недели."),
        ChecklistItem("TK3-2", "Темы pandas, визуализация, SQL, основы статистики с часами."),
        ChecklistItem("TK3-3", "Вводный блок по основам Python."),
        ChecklistItem("TK3-8", "Задания на банковских ситуациях."),
    ),
)

TK4 = OfficialCase(
    case_id="tk4",
    title="Курс по кибербезопасности для колледжа",
    request_text=_REQUESTS.get(
        "tk4",
        "Сделайте курс по кибербезопасности для студентов колледжа, примерно на месяц, "
        "чтобы после него ребята могли пойти работать в эту сферу.",
    ),
    checklist=(ChecklistItem("TK4-5", "После уточнений — шаблон ПК и программа ровно на 72 часа."),),
)

TK5 = OfficialCase(
    case_id="tk5",
    title="Стажировка «DevOps-инженер от Linux до CI/CD»",
    request_text=_REQUESTS.get(
        "tk5",
        "Нужна программа повышения квалификации в форме стажировки «DevOps-инженер от Linux до CI/CD» "
        "на 256 часов. Слушатели проходят стажировку в ИТ-компаниях региона, вся работа самостоятельная "
        "под руководством наставника от компании, аудиторных занятий нет. Итоговая аттестация занимает 2 часа "
        "и проходит в форме защиты отчёта о стажировке. Срок около двух месяцев, не больше 4 часов в день. "
        "Возьмите за образец структуры нашу стажировку по бизнес-анализу.",
    ),
    checklist=(
        ChecklistItem("TK5-1", "Общий объем 256 ч: 254 СРС + 2 ч итоговой аттестации."),
        ChecklistItem("TK5-2", "Лекции, практики и лабораторные равны нулю."),
        ChecklistItem("TK5-3", "Ошибка итоговой строки образца не перенесена."),
        ChecklistItem("TK5-4", "Календарь ~2 месяца, не более 4 ч в день."),
        ChecklistItem("TK5-5", "Темы Linux, сети, контейнеризация, CI/CD, мониторинг, IaC."),
        ChecklistItem("TK5-6", "Текущий контроль — собеседование с вопросами по разделам."),
    ),
)

OFFICIAL_CASES: dict[str, OfficialCase] = {c.case_id: c for c in (TK1, TK2, TK3, TK4, TK5)}
