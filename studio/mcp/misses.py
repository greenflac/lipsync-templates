"""Вопросы, заданные агенту о моделях, и что база смогла на них ответить.

ЗАЧЕМ ЭТОТ ФАЙЛ, И ЧЕГО БЕЗ НЕГО НЕ БЫЛО

Покрытие спрашивали числом: «сколько моделей мы знаем». База отвечала
«245 моделей, 988 фактов» — и это ответ не на тот вопрос. Моделей в мире
выходит десятки в неделю, и почти о всех никто никогда не спросит. Значение
имеет одно: на РЕАЛЬНО заданный вопрос база ответила или промолчала.

`advise()` третий исход уже отдавал честно (`не смогли`, а не `не годно`), но
нигде не записывал, что вопрос БЫЛ. Из-за этого не существовало знаменателя:
доля закрытых вопросов не считалась, список «что дочитать» собирался по памяти,
а «покрытие выросло» нечем было отличить от «спрашивать стали о другом».

Правило П1 ровно про это: счётчик раньше ручки. Ручки (опрос индексов, очередь
дочитывания) без этого журнала нечем принимать — они будут выглядеть полезными
в любом случае.

ЧТО ПИШЕТСЯ

КАЖДЫЙ вопрос, а не только промах. Журнал одних промахов растёт и при
улучшении базы, и при ухудшении: без попаданий рядом он неотличим от счётчика
активности. Строка — append-only, потому что журнал, а не таблица.

ЧЕГО ЗДЕСЬ НЕТ НАРОЧНО

Ответа. Что именно база сказала — есть в `model_facts.jsonl` и выводится
заново; дублировать это здесь значит завести второй способ узнать известное
(правило Е1), который разъедется с первым.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

STORE = Path(__file__).resolve().parents[1] / "knowledge" / "misses.jsonl"

#: Исход одного вопроса, теми же тремя значениями, что и везде (правило Р1).
#: Это исход КОНСУЛЬТАЦИИ, как его назвал `advise`. Промах считается не по
#: нему, а по полю `known` ниже: см. Е2 и пойманное расхождение.
OUTCOMES = (PASS, FAIL, UNMEASURED)

#: Без этих полей строка не кладётся: вопрос без даты не отличить от вопроса
#: прошлого года, а вопрос без исхода не считается ни в один знаменатель.
REQUIRED = ("model", "asked_on", "outcome")

#: Сколько атрибутов о модели у базы НА САМОМ ДЕЛЕ нашлось. Промах считается
#: по этому числу, а не по исходу консультации, — правило Е2, «при расхождении
#: флага и свидетельства верь свидетельству».
#:
#: Расхождение не гипотетическое, оно поймано первым же живым прогоном
#: 2026-08-31: `advise("wan-2.2")` вернул `не смогли`, потому что модели нет в
#: РЕЕСТРЕ ДОСТУПНОСТИ, — и одновременно `checked 3`, то есть три атрибута о
#: ней записаны. Считать это промахом значит мерить полноту реестра и называть
#: результат покрытием базы.
KNOWN_FIELD = "known"

#: ВЫБРАНО 2026-08-31: столько промахов подряд об ОДНОЙ модели считается
#: сигналом, что её пора дочитывать, а не случайным вопросом. Меньше — и в
#: очередь попадёт каждая опечатка в имени; больше — и настоящий пробел
#: простоит неделю. Порог сторожится тестом в обе стороны (правило Т1).
REPEAT_BEFORE_QUEUE = 2


def covered(row: dict[str, Any]) -> bool:
    """Нашлось ли у базы хоть что-нибудь по этому вопросу.

    Вынесено функцией (правило Т5), потому что от неё зависит и знаменатель
    покрытия, и попадание модели в очередь дочитывания — а развилка, повторённая
    в двух местах, разъедется.
    """
    return int(row.get(KNOWN_FIELD, 0) or 0) > 0


@dataclass(frozen=True)
class Coverage:
    """Сколько вопросов задали и сколько из них база закрыла."""

    asked: int
    answered: int
    contested: int
    missed: int
    outcome: str
    rate: float | None
    note: str


def problems(row: dict[str, Any]) -> list[str]:
    """Что не так с одной строкой журнала. Пусто — значит ничего.

    Вынесено из точки входа (правило Т5), чтобы решение гейта было достижимо
    из теста без файла на диске.
    """
    found: list[str] = []
    for field in REQUIRED:
        if not str(row.get(field) or "").strip():
            found.append(f"{field}: обязательное поле пустое или отсутствует")
    outcome = str(row.get("outcome") or "")
    if outcome and outcome not in OUTCOMES:
        found.append(f"outcome: {outcome!r} не из {OUTCOMES}")
    return found


def note_question(
    model: str,
    attribute: str,
    outcome: str,
    *,
    known: int = 0,
    asked_on: str = "",
    note: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    """Записать один заданный вопрос и его исход. Возвращает записанную строку.

    Молчит при любой ошибке записи НАРОЧНО: журнал наблюдает за консультацией,
    а не участвует в ней. Упавший диск не должен превращать ответ о модели в
    ошибку — иначе счётчик становится причиной отказа, ради наблюдения за
    которым он и заведён.
    """
    row = {
        "model": str(model or "").strip(),
        "attribute": str(attribute or "").strip(),
        "outcome": str(outcome or "").strip(),
        KNOWN_FIELD: int(known),
        "asked_on": asked_on or date.today().isoformat(),
        "note": note,
    }
    if problems(row):
        return row
    target = STORE if path is None else path
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return row


def load(path: Path | None = None) -> list[dict[str, Any]]:
    """Строки журнала. Отсутствующий файл — пустой журнал, а не ошибка."""
    target = STORE if path is None else path
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def coverage(rows: Iterable[dict[str, Any]]) -> Coverage:
    """Доля заданных вопросов, которые база закрыла.

    Ноль вопросов — это `не смогли`, а не стопроцентное покрытие. Пустой
    знаменатель, свёрнутый в успех, — ровно та ошибка, из-за которой правило
    Р2 существует: «нарушений 0» при нуле проверок читается как работа.
    """
    seen = [r for r in rows if not problems(r)]
    asked = len(seen)
    known = [r for r in seen if covered(r)]
    answered = sum(1 for r in known if r.get("outcome") != FAIL)
    contested = sum(1 for r in known if r.get("outcome") == FAIL)
    missed = asked - len(known)
    if asked == 0:
        return Coverage(0, 0, 0, 0, UNMEASURED, None, "вопросов не задавали — мерить нечего")
    rate = (answered + contested) / asked
    return Coverage(
        asked=asked,
        answered=answered,
        contested=contested,
        missed=missed,
        outcome=PASS if missed == 0 else FAIL,
        rate=rate,
        note=f"спрошено {asked}, из базы {answered + contested}, мимо {missed}",
    )


def queue(
    rows: Iterable[dict[str, Any]], *, repeat: int = REPEAT_BEFORE_QUEUE
) -> list[dict[str, Any]]:
    """Что дочитывать: модели, о которых промахнулись не меньше `repeat` раз.

    Отсортировано по числу промахов, потому что очередь без порядка — это
    список, и его читают с начала независимо от того, что там важнее.
    """
    counts: dict[str, int] = {}
    attributes: dict[str, set[str]] = {}
    last: dict[str, str] = {}
    for row in rows:
        if problems(row) or covered(row):
            continue
        name = str(row["model"]).lower()
        counts[name] = counts.get(name, 0) + 1
        if row.get("attribute"):
            attributes.setdefault(name, set()).add(str(row["attribute"]))
        asked_on = str(row.get("asked_on") or "")
        if asked_on > last.get(name, ""):
            last[name] = asked_on
    ready: list[dict[str, Any]] = [
        {
            "model": name,
            "misses": count,
            "attributes": sorted(attributes.get(name, ())),
            "last_asked": last.get(name, ""),
        }
        for name, count in counts.items()
        if count >= repeat
    ]
    ready.sort(key=lambda row: (-counts[str(row["model"])], str(row["model"])))
    return ready
