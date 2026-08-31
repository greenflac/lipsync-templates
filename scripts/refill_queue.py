"""Одна очередь дочитывания: что именно сейчас стоит идти читать.

ЗАЧЕМ ОДНА, А НЕ ТРИ

Работа, которая делает базу полнее, приходит из трёх мест, и до сих пор ни
одно не порождало работу — каждое только отвечало на вопрос:

  * `misses.jsonl` — о модели СПРОСИЛИ, а база промолчала. Спрос доказан.
  * `stale_model_facts` — факт старше 90 дней. Мы прямо сейчас отвечаем им.
  * `discover_models.py` — в индексе появилось то, чего у нас нет.

Три списка в трёх местах читаются как три необязательных отчёта. Один
упорядоченный список читается как очередь, и это разница между «знаем о
пробеле» и «пробел закрывается».

ПОЧЕМУ ПОРЯДОК ИМЕННО ТАКОЙ

Протухший ВЕНДОРСКИЙ факт стоит выше промаха нарочно: промах — это честное
«не знаем», а протухший факт — это ответ, который мы продолжаем выдавать за
верный. Неверный ответ дороже отсутствующего. Всё остальное — будущий спрос,
и оно ниже доказанного.

Порядок — константа-решение, и он сторожится тестом (правило Т1): если его
переставить, тест обязан покраснеть, иначе очередь не очередь, а список.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.mcp import misses  # noqa: E402
from studio.selfrag import facts as facts_mod  # noqa: E402
from studio.selfrag.facts import STALE_AFTER_DAYS, TIER_VENDOR  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "studio" / "knowledge" / "model_facts.jsonl"

#: Причина — ОДНА строка в одном месте, и производители берут её отсюда же.
#: Пока производители печатали свои литералы, а `PRIORITY` держал их копии,
#: опечатка на стороне производителя уводила все протухшие вендорские факты в
#: хвост очереди, и ни один тест этого не видел: тесты порядка подавали в
#: `order()` литералы, набранные в самом тесте, то есть проверяли копию
#: (найдено независимой проверкой 2026-08-31, правило Е1).
STALE_VENDOR = "протухший вендорский факт"
ASKED_UNKNOWN = "спросили — не знаем"
NEW_FAMILY = "новое семейство"
NEW_VERSION = "новая версия известного семейства"
STALE_OTHER = "протухший факт прочих тиров"

#: ВЫБРАНО 2026-08-31. Меньшее число — раньше в очереди. Обоснование каждой
#: ступени — в докстроке модуля; переставить их молча нельзя, тест держит.
PRIORITY: dict[str, int] = {
    STALE_VENDOR: 1,
    ASKED_UNKNOWN: 2,
    NEW_FAMILY: 3,
    NEW_VERSION: 4,
    STALE_OTHER: 5,
}


def stale_work(today: date | None = None, path: Path | None = None) -> list[dict[str, Any]]:
    """Факты старше порога — тем, чем мы отвечаем, и что пора перечитать."""
    rows = facts_mod.load_facts(FACTS if path is None else path)
    when = today or date.today()
    found: list[dict[str, Any]] = []
    for fact in rows:
        if not fact.stated_on:
            continue
        try:
            age = (when - date.fromisoformat(fact.stated_on)).days
        except ValueError:
            continue
        if age <= STALE_AFTER_DAYS:
            continue
        vendor = fact.tier == TIER_VENDOR
        found.append(
            {
                "reason": STALE_VENDOR if vendor else STALE_OTHER,
                "model": fact.model,
                "detail": f"{fact.attribute}, источнику {age} дней",
                "where": fact.source_url,
            }
        )
    return found


def missed_work(path: Path | None = None) -> list[dict[str, Any]]:
    """Модели, о которых спрашивали не раз и база молчала."""
    return [
        {
            "reason": ASKED_UNKNOWN,
            "model": row["model"],
            "detail": f"спрашивали {row['misses']} раз(а), последний {row['last_asked']}",
            "where": ", ".join(row["attributes"]) or "всё",
        }
        for row in misses.queue(misses.load(path))
    ]


def discovered_work(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Находки опроса индексов, если прогон сохранён. Нет прогона — нет строк."""
    if not payload:
        return []
    found: list[dict[str, Any]] = []
    for row in payload.get("new_families", []):
        found.append(
            {
                "reason": NEW_FAMILY,
                "model": row.get("family", ""),
                "detail": f"загрузчиков {len(row.get('uploaders', []))}, задача {row.get('task', '')}",
                "where": ", ".join(row.get("examples", [])[:2]),
            }
        )
    for row in payload.get("new_versions", []):
        found.append(
            {
                "reason": NEW_VERSION,
                "model": row.get("stem", ""),
                "detail": f"семейство {row.get('family', '')}, перезаливок {row.get('count', 0)}",
                "where": ", ".join(row.get("examples", [])[:2]),
            }
        )
    return found


def order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Очередь: по приоритету причины, внутри причины — по имени модели.

    Неизвестная причина уезжает в конец, а не роняет прогон: очередь, которая
    падает от новой строки, перестаёт быть очередью ровно тогда, когда её
    расширяют.
    """
    ranked = sorted(rows, key=lambda r: (PRIORITY.get(str(r["reason"]), 99), str(r["model"])))
    return ranked


def report(rows: list[dict[str, Any]], sources: dict[str, bool], limit: int) -> int:
    """Напечатать очередь числами и вернуть исход из трёх."""
    silent = [name for name, answered in sources.items() if not answered]
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["reason"])] = counts.get(str(row["reason"]), 0) + 1

    print("ОЧЕРЕДЬ ДОЧИТЫВАНИЯ")
    print(
        f"источников работы {len(sources)}, ответили {len(sources) - len(silent)}, "
        f"не смогли {len(silent)}"
    )
    if silent:
        print("  молчат: " + ", ".join(silent))
    print(f"строк в очереди {len(rows)}")
    for reason in sorted(counts, key=lambda r: PRIORITY.get(r, 99)):
        print(f"  {reason}: {counts[reason]}")

    print(f"\n--- ПЕРВЫЕ {min(limit, len(rows))}")
    for row in order(rows)[:limit]:
        print(f"  [{row['reason']}] {row['model']}")
        print(f"       {row['detail']}  |  {row['where']}")

    if len(silent) == len(sources):
        print("\nисход: не смогли — ни один источник работы не ответил")
        return 2
    if silent:
        print(f"\nисход: не смогли полностью — молчат {len(silent)} из {len(sources)}")
        return 2
    print(f"\nисход: годно — работы на {len(rows)} строк")
    return 0


def check_journal(path: Path | None = None) -> int:
    """Гейт: журнал читается, строки целы, знаменатель покрытия существует.

    Сети здесь нет нарочно — гейт обязан быть честным в CI (правило Т4). Три
    исхода: битая строка красит сборку, пустой журнал красит её отдельным
    сообщением (файл лежит в репозитории заполненным, и пустым он может стать
    только если строки вычистили), целый журнал печатает числа и молчит.
    """
    rows, torn = misses.read(path)
    broken = [(i, misses.problems(row)) for i, row in enumerate(rows, 1) if misses.problems(row)]
    cover = misses.coverage(rows)
    print(
        f"журнал вопросов: разобрано {len(rows)}, не разобралось {len(torn)}, "
        f"битых по схеме {len(broken)}"
    )
    if torn:
        print("  строки, не разобравшиеся как JSON: " + ", ".join(str(n) for n in torn[:10]))
    print(f"покрытие: {cover.note}, исход {cover.outcome}")
    for number, found in broken[:10]:
        print(f"  строка {number}: " + "; ".join(found))
    if broken or torn:
        print("ПРОВАЛ: битые строки в журнале — знаменатель покрытия им врёт")
        return 1
    if not rows:
        print("НЕ СМОГЛИ: журнал пуст, мерить покрытие нечем")
        return 2
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--discovered",
        type=Path,
        help="сохранённый прогон discover_models.py --json; без него канал молчит",
    )
    parser.add_argument("--limit", type=int, default=20, help="сколько строк печатать")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="гейт: схема журнала вопросов и знаменатель покрытия, без сети",
    )
    args = parser.parse_args(argv)

    if args.check:
        return check_journal()

    payload: dict[str, Any] | None = None
    if args.discovered and args.discovered.exists():
        payload = json.loads(args.discovered.read_text(encoding="utf-8"))

    asked = missed_work()
    stale = stale_work()
    fresh = discovered_work(payload)
    rows = order(asked + stale + fresh)
    sources = {
        "журнал вопросов": bool(misses.load()),
        "факты с датами": bool(stale) or bool(facts_mod.load_facts(FACTS)),
        "опрос индексов": payload is not None,
    }
    if args.json:
        print(json.dumps({"queue": rows, "sources": sources}, ensure_ascii=False, indent=2))
        return 0 if any(sources.values()) else 2
    return report(rows, sources, args.limit)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
