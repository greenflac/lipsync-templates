"""Балл по замороженному набору вопросов. Правило счёта берётся ИЗ ФАЙЛА.

ЗАЧЕМ ИМЕННО ТАК

Первая редакция набора правила счёта не имела, и независимая приёмка показала
на ней 4 из 16 против 6 из 16 по двум одинаково защитимым правилам. Разброс в
50% создавала формулировка, которую выбирает тот, кто отчитывается, — уже
увидев результат. Поэтому здесь нет ни одного порога и ни одной трактовки:
скрипт исполняет `scored`, записанное у вопроса, и печатает результат по видам.

ЧТО НЕ СЧИТАЕТСЯ ОТВЕТОМ, И ЭТО ЗАПИСАНО В САМОМ НАБОРЕ

Находки класса и общие правила. ИЗМЕРЕНО: те же 12 из 171 возвращаются
побайтово одинаково выдуманному имени, `veo-3.1` и запросу про бухучёт. Канал,
отвечающий одинаково на любой вход, несёт ноль бит о входе.

ВИДЫ ВОПРОСОВ СЧИТАЮТСЯ ПОРОЗНЬ, И ЭТО НЕ УКРАШЕНИЕ

`naming` двигается картой псевдонимов без единого нового факта; `model` растёт
только чтением источников. Сложить их в один балл значит разрешить отчитаться
знанием за работу по именам.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.factindex import FactIndex, verdict  # noqa: E402
from studio.terms import bridge, bridged_words  # noqa: E402
from studio.mcp import advice  # noqa: E402

ЗАМОРОЖЕННЫЕ = (
    Path(__file__).resolve().parents[1] / "studio" / "knowledge" / "frozen_questions.jsonl"
)

#: Тир, ниже которого источник не закрывает вопрос. ВЫБРАНО и записано в шапке
#: самого набора: без этой строки одиннадцать записей блогового тира по именам
#: из журнала промахов поднимают балл вчетверо, не добавив ни одного знания.
FLOOR_TIER = "blog"


def load(path: Path | None = None) -> list[dict[str, Any]]:
    текст = (path or ЗАМОРОЖЕННЫЕ).read_text(encoding="utf-8")
    строки = [s for s in текст.splitlines() if s.strip() and not s.startswith("//")]
    return [json.loads(s) for s in строки]


def _above_floor(claim: dict[str, Any]) -> bool:
    """Есть ли у утверждения источник выше блогового."""
    for вариант in claim.get("claims", []):
        if вариант.get("best_tier") and вариант["best_tier"] != FLOOR_TIER:
            return True
    return False


def ask_advise(q: dict[str, Any]) -> dict[str, Any]:
    """Спросить консультанта. Возвращает исход и то, чем он обоснован."""
    ответ = advice.advise(q["ask"], q.get("attribute", ""))
    атрибут = q.get("attribute", "")
    claim = (ответ.get("claims") or {}).get(атрибут, {}) if атрибут else {}
    return {
        "outcome": ответ.get("outcome"),
        "claims": ответ.get("claims") or {},
        "claim": claim,
        "failure_modes": ответ.get("failure_modes") or [],
        "note": str(ответ.get("note") or ""),
        # находки класса намеренно НЕ переносятся: набор объявляет их не ответом
    }


def ask_factindex(q: dict[str, Any], index: FactIndex) -> dict[str, Any]:
    """Спросить индекс, проведя вопрос через мост терминов.

    Мост добавляет английские соответствия доменных слов и НЕ трогает
    остальное: негативные контроли обязаны остаться пустыми, и на это есть
    отдельный тест. Что именно мост узнал — печатается, иначе его работу нечем
    проверить.
    """
    спрошено = bridge(q["ask"])
    hits = index.search(спрошено)
    v = verdict(hits, спрошено)
    return {
        "outcome": v["outcome"],
        "hits": v["hits"],
        "models": [h["model"] for h in v["hits"]],
        "bridged": bridged_words(q["ask"]),
    }


def score(q: dict[str, Any], got: dict[str, Any]) -> str:
    """Годно / не годно / не смогли — по правилу, записанному у вопроса.

    Третий исход здесь не украшение: вопрос, чей канал не отработал, обязан
    отличаться от вопроса, на который база честно не ответила.
    """
    вид = q["kind"]
    if got.get("outcome") is None:
        return "не смогли"

    if вид == "control":
        пусто = not got.get("models") and not got.get("claims")
        нет_соседей = "The base does hold" not in got.get("note", "")
        если_атрибут = got.get("claim", {}).get("checked", 0) == 0 if q.get("attribute") else True
        return (
            "годно"
            if (пусто or не_пусто_но_контроль(q, got)) and нет_соседей and если_атрибут
            else "не годно"
        )

    if вид == "naming":
        return "годно" if "The base does hold" in got.get("note", "") else "не годно"

    if вид == "brief":
        # Исполняется ТО, что записано в `scored`, а не общее правило «выдача
        # непуста». Первая редакция скорера проверяла непустоту и дала 4 из 4
        # там, где русский бриф заведомо поднимает шум: измерено, английская
        # форма даёт wan-animate-replace со счётом 4.122, русская — нет.
        # Слабое правило в скорере — тот же дефект, что отсутствие правила в
        # наборе, только спрятанный на этаж ниже.
        нужен = требуемое_имя(q.get("scored", ""))
        if нужен:
            return "годно" if нужен in [m.lower() for m in got.get("models", [])] else "не годно"
        return "годно" if got.get("models") else "не годно"

    if q.get("attribute") == "failure_mode":
        return "годно" if got.get("failure_modes") else "не годно"

    if q.get("attribute"):
        claim = got.get("claim") or {}
        if not claim:
            return "не годно"
        return "годно" if claim.get("outcome") == "pass" and _above_floor(claim) else "не годно"

    return "годно" if got.get("claims") else "не годно"


def требуемое_имя(scored: str) -> str:
    """Имя модели, которое `scored` требует увидеть в выдаче. Пусто — не требует.

    Разбирается ровно форма «в выдаче есть <имя>», записанная в наборе. Всё
    прочее возвращает пусто, и тогда действует общее правило — но молча
    подменять требование общим правилом нельзя.
    """
    маркер = "в выдаче есть "
    if маркер not in scored:
        return ""
    хвост = scored.split(маркер, 1)[1].strip()
    первое = хвост.split()[0] if хвост.split() else ""
    return первое.lower() if "-" in первое or "_" in первое else ""


def не_пусто_но_контроль(q: dict[str, Any], got: dict[str, Any]) -> bool:
    """Контроль на ЗНАКОМОЙ модели: пустым ответ быть не обязан.

    q22 спрашивает несуществующий атрибут у известной модели. Правильный ответ
    — «об этом атрибуте не записано ничего», а не «модели нет». Известность
    модели не должна закрывать вопрос о её несуществующем свойстве.
    """
    return bool(q.get("attribute")) and got.get("claim", {}).get("checked", 0) == 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    вопросы = load()
    index = FactIndex()
    строки = []
    for q in вопросы:
        канал = q["channel"]
        got = ask_advise(q) if канал == "advise" else ask_factindex(q, index)
        строки.append({**q, "исход": score(q, got)})

    по_видам: dict[str, Counter] = {}
    for r in строки:
        по_видам.setdefault(r["tests"], Counter())[r["исход"]] += 1

    if args.json:
        print(json.dumps(строки, ensure_ascii=False, indent=2))
        return 0

    print("БАЛЛ ПО ЗАМОРОЖЕННОМУ НАБОРУ")
    print(f"вопросов {len(строки)}, правило счёта взято из файла, не отсюда\n")
    for что, счёт in sorted(по_видам.items()):
        всего = sum(счёт.values())
        print(
            f"  {что:20} годно {счёт['годно']:2} из {всего:2}"
            f"   не годно {счёт['не годно']:2}   не смогли {счёт['не смогли']:2}"
        )
    итог = Counter(r["исход"] for r in строки)
    print(
        f"\nпроверено {len(строки)}, годно {итог['годно']},"
        f" не годно {итог['не годно']}, не смогли {итог['не смогли']}"
    )
    print("\nчто НЕ отвечено:")
    for r in строки:
        if r["исход"] != "годно":
            print(f"  [{r['исход']:9}] {r['id']} {r['kind']:8} {r['ask'][:56]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
