#!/usr/bin/env python3
"""Чего база не знает о СВОЁМ ЖЕ предмете: липсинк, который продаётся на fal.ai.

ЗАЧЕМ ЭТОТ КАНАЛ

Опрос машинных индексов (`discover_models.py`) ходит в OpenRouter и DeepInfra
— каталоги языковых и мультимодальных API. Липсинк-моделей там нет вовсе, и
это не поломка: их там не продают. Продают их на портале, и портал мы не
опрашивали ни разу.

ИЗМЕРЕНО 2026-09-02: по слову `lipsync` fal.ai отдаёт 22 модели, и 18 из них
база не знает НИ ОДНОЙ строкой — среди них Heygen v3, sync-3, VEED, Kling
LipSync. Нашлось это не гейтом: я спросил инструмент про его собственный
главный вопрос («какой липсинк взять»), увидел в ответе `sync-lipsync` с нулём
строк и пошёл смотреть, что ещё продаётся рядом.

ЧТО ЭТОТ СКРИПТ ДЕЛАЕТ И ЧЕГО НЕ ДЕЛАЕТ

Он НЕ записывает факты. Портал знает имя, заголовок и цену — это `portal`-тир
и капабилити в лучшем случае, а набирать строки ради строк уже разбиралось
дважды за сегодня и оба раза кончалось метаданными вместо применимости.

Он производит ОЧЕРЕДЬ: имена, которых в базе нет, в той же форме, что и опрос
индексов (`new_families`), чтобы `refill_queue.py` показывал их рядом с
остальной работой. Что читать первым — решает человек, глядя на очередь.

ТРИ ИСХОДА (Р1)

    годно        портал ответил, разница посчитана
    не годно     ответ портала не разобрался (схема поменялась)
    не смогли    портал не ответил или закрыт политикой (Ц3: не обходим)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402
from studio.mcp import fetch  # noqa: E402
from studio.selfrag import modelnames  # noqa: E402
from studio.selfrag.facts import load_facts  # noqa: E402

#: Портал и его открытый каталог. `fal.ai` объявлен открытым хабом в
#: `studio/mcp/routes.py` и отвечает без ключа — проверено 2026-09-02.
ПОРТАЛ = "fal.ai"
КАТАЛОГ = "https://fal.ai/api/models?keywords={слово}&page={страница}"

#: Слова, по которым спрашиваем. ВЫБРАНО по предмету репозитория, а не по
#: широте: это студия липсинка, и канал заводится ради него. Широкий запрос
#: («video») вернул бы сотни имён, из которых база не знает почти ни одного, и
#: очередь превратилась бы в каталог портала — то есть в шум.
СЛОВА: tuple[str, ...] = ("lipsync", "avatar", "talking")

#: Сколько страниц брать на слово. ВЫБРАНО 3: у `lipsync` их одна (22 модели),
#: запас на рост. Портал сам называет `pages`, и цикл кончается по нему.
СТРАНИЦ = 3

ОЧЕРЕДЬ = Path(__file__).resolve().parents[1] / "studio" / "knowledge" / "portal_poll.json"


#: Имя модели из идентификатора портала. Е1: живёт в `modelnames`, потому что
#: тот же портал читает и канал записи цен (`scripts/ingest_portal.py`), а
#: разница между базой и порталом считается ПО ИМЕНИ — разъехавшись, два
#: написания одного превратились бы в выдуманную работу.
имя_модели = modelnames.from_portal_id


def спросить(слово: str, страница: int) -> tuple[str, dict[str, Any] | None]:
    """Одна страница каталога. Три исхода, и «не разобралось» отличимо от «не ответил»."""
    ответ = fetch.fetch(КАТАЛОГ.format(слово=слово, страница=страница))
    if ответ.get("outcome") != PASS:
        return (UNMEASURED, None)
    try:
        разобрано = json.loads(ответ.get("text") or "")
    except ValueError:
        return (FAIL, None)
    if not isinstance(разобрано, dict) or "items" not in разобрано:
        return (FAIL, None)
    return (PASS, разобрано)


def опросить(слова: tuple[str, ...] = СЛОВА) -> dict[str, Any]:
    """Все слова, все страницы. Возвращает найденное и счётчики (Р2)."""
    найдено: dict[str, dict[str, Any]] = {}
    ответило = 0
    не_разобралось = 0
    не_ответило = 0
    for слово in слова:
        отвечало = False
        for страница in range(1, СТРАНИЦ + 1):
            исход, тело = спросить(слово, страница)
            if исход == UNMEASURED:
                не_ответило += 1
                break
            if исход == FAIL or тело is None:
                не_разобралось += 1
                break
            отвечало = True
            for запись in тело.get("items") or []:
                имя = имя_модели(str(запись.get("id") or ""))
                if имя:
                    найдено.setdefault(
                        имя,
                        {
                            "name": имя,
                            "title": str(запись.get("title") or "")[:80],
                            "url": f"https://fal.ai/models/{str(запись.get('id') or '').strip('/')}",
                            "keyword": слово,
                        },
                    )
            if страница >= int(тело.get("pages") or 1):
                break
        ответило += 1 if отвечало else 0
    return {
        "found": найдено,
        "answered": ответило,
        "asked": len(слова),
        "unparsed": не_разобралось,
        "silent": не_ответило,
    }


def разница(найдено: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Имена портала, которых база не знает НИ ОДНОЙ строкой.

    Сравнение идёт по свёрнутому имени (`modelnames.fold`), а не по строке:
    `sync-lipsync-v2` и `sync_lipsync_v2` — одно и то же, и считать их разными
    значит выдумать работу.
    """
    свои = {modelnames.fold(факт.model) for факт in load_facts()}
    return [запись for имя, запись in sorted(найдено.items()) if modelnames.fold(имя) not in свои]


def свести(путь: Path = ОЧЕРЕДЬ) -> dict[str, Any]:
    """Прочитать сохранённую очередь и пересчитать её по НЫНЕШНЕЙ базе.

    Пересчёт обязателен: очередь, снятая вчера, называет работой то, что сегодня
    уже записано, а очередь, которая просит сделанного, читается по диагонали —
    это разбиралось сегодня дважды на других очередях.
    """
    if not путь.is_file():
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"опроса портала нет: {путь.name} не найден",
            "still_unknown": [],
        }
    try:
        снято = json.loads(путь.read_text(encoding="utf-8"))
    except ValueError:
        return {
            "outcome": FAIL,
            "checked": 0,
            "violations": 1,
            "unmeasured": 0,
            "note": f"{путь.name} не разобрался как JSON",
            "still_unknown": [],
        }
    семьи = снято.get("new_families") or []
    if снято.get("partial"):
        return {
            "outcome": UNMEASURED,
            "checked": len(семьи),
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"опрос {ПОРТАЛ} от {снято.get('polled_on', 'без даты')} НЕПОЛНЫЙ: "
                f"ответило {снято.get('channels_answered', '?')} слов из "
                f"{снято.get('channels_asked', '?')}. В очереди {len(семьи)} имён, "
                "но пробел в ней неотличим от отсутствия модели"
            ),
            "still_unknown": семьи,
        }
    свои = {modelnames.fold(факт.model) for факт in load_facts()}
    ещё_нет = [с for с in семьи if modelnames.fold(str(с.get("family") or "")) not in свои]
    записанных = len(семьи) - len(ещё_нет)
    return {
        "outcome": PASS,
        "checked": len(семьи),
        "violations": 0,
        "unmeasured": 0,
        "note": (
            f"опрос {ПОРТАЛ} от {снято.get('polled_on', 'без даты')}: "
            f"в очереди было {len(семьи)}, записано с тех пор {записанных}, "
            f"остаётся неизвестными {len(ещё_нет)}"
        ),
        "still_unknown": ещё_нет,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="без сети: пересчитать сохранённое")
    parser.add_argument("--write", action="store_true", help="сохранить очередь в знание")
    args = parser.parse_args(argv)

    if args.check:
        итог = свести()
        print(итог["note"])
        print(
            f"\nпроверено {итог['checked']}\nнарушений {итог['violations']}\nне смогли {итог['unmeasured']}"
        )
        return 0 if итог["outcome"] == PASS else (1 if итог["outcome"] == FAIL else 2)

    опрос = опросить()
    новые = разница(опрос["found"])
    print(
        f"портал {ПОРТАЛ}: слов спрошено {опрос['asked']}, ответило {опрос['answered']}, "
        f"не разобралось {опрос['unparsed']}, не ответило {опрос['silent']}"
    )
    print(f"моделей на портале {len(опрос['found'])}, база не знает {len(новые)}")
    for запись in новые[:20]:
        print(f"  {запись['name'][:44]:46} {запись['title'][:34]}")
    if args.write:
        ОЧЕРЕДЬ.write_text(
            json.dumps(
                {
                    "polled_on": date.today().isoformat(),
                    "portal": ПОРТАЛ,
                    "keywords": list(СЛОВА),
                    "checked": len(опрос["found"]),
                    "channels_asked": опрос["asked"],
                    "channels_answered": опрос["answered"],
                    # НЕПОЛНЫЙ ОПРОС ПОМЕЧАЕТСЯ В САМОМ ФАЙЛЕ. Наблюдено на
                    # первом же живом прогоне: одно слово из трёх не ответило
                    # (портал икнул, повторный запрос прошёл), а очередь при
                    # этом записалась и выглядела полной. Очередь, снятая
                    # наполовину, читается как «вот всё, чего мы не знаем», и
                    # разница между «этого нет на портале» и «мы не спросили»
                    # исчезает ровно там, где она дороже всего.
                    "partial": опрос["answered"] < опрос["asked"],
                    "new_families": [
                        {
                            "family": з["name"],
                            "task": з["title"],
                            "uploaders": [ПОРТАЛ],
                            "examples": [з["url"]],
                        }
                        for з in новые
                    ],
                    "new_versions": [],
                },
                ensure_ascii=False,
                indent=1,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"очередь записана: {ОЧЕРЕДЬ}")
    if not опрос["answered"]:
        print("не смогли: портал не ответил ни на одно слово")
        return 2
    if опрос["answered"] < опрос["asked"]:
        print(
            f"не смогли целиком: ответило {опрос['answered']} слов из {опрос['asked']}. "
            "Очередь ниже — НЕПОЛНАЯ: то, чего мы не спросили, в ней не отличается "
            "от того, чего на портале нет."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
