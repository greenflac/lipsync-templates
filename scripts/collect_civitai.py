#!/usr/bin/env python3
"""Collect prompt-and-result pairs from Civitai into the knowledge base.

    python scripts/collect_civitai.py --pages 5 --versions 100
    python scripts/collect_civitai.py --summary          # what is held already

The walk and every decision in it live in `studio/mcp/civitai.py`; this is the
handle. It exists so a collection run is a command with a record rather than a
snippet somebody pasted into a shell once.

RATE AND SCALE

Requests go out no faster than one per second by default and `--versions` is a
hard ceiling, so a mistyped page count cannot become a thousand calls against
somebody else's API. Raise them deliberately.

RIGHTS

`--rights` is stamped on every row and defaults to the basis recorded in
`studio/knowledge/PROVENANCE.md`. It is not decoration: it is what makes an
exact removal possible if it is ever asked for, and a row cannot be written
without it. If the basis changes, change it here and in PROVENANCE.md together.

The output file is in `.gitignore`. That is deliberate and explained there.
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

from studio.mcp import civitai  # noqa: E402

#: The basis these rows stand on, from PROVENANCE.md. Stamped per row.
DEFAULT_RIGHTS = "owner_authorisation_2026-08-27"


def exit_code(outcomes: list[str], written: int) -> int:
    """Три состояния в коде возврата, посчитанные ПО СВИДЕТЕЛЬСТВУ.

    Прежняя версия строила исход из одного числа `written`, поэтому получалось
    только два состояния: ветка `1` была недостижима, и жёсткий отказ API
    выходил с нулём, если хоть одно другое семейство что-то записало. Значение
    выводится из того, что исполнилось, а не из намерения (правило Е2).

    Вынесено из `main` (Т5): развилка внутри точки входа тестом недостижима.
    """
    if any(o == FAIL for o in outcomes):
        return 1
    if written:
        return 0
    return 2


def проверить_собранное(path: Path | None = None) -> dict[str, Any]:
    """Офлайн: годны ли УЖЕ СОБРАННЫЕ пары. Сети здесь нет.

    ФАЙЛА В РЕПОЗИТОРИИ НЕТ И НЕ БУДЕТ (`.gitignore`, и почему — в PROVENANCE.md):
    это чужие промпты. Поэтому на чистом клоне честный исход ровно один — «не
    смогли», и он НЕ сворачивается в «годно». Ноль проверенных строк при нуле
    нарушений — это отсутствие прибора, а не его успех (правило Р2); именно
    так канал и мог бы испортиться молча.

    Что считается нарушением (M), когда файл всё-таки лежит:
      * строка не разобралась как JSON;
      * нет любого поля из `civitai.REQUIRED_ROW_FIELDS` или оно пустое —
        строка без своего происхождения не подлежит точному удалению;
      * `provenance` не начинается с `civitai.PROVENANCE_PREFIX` — обращение
        по требованию об удалении ищет строки по этому префиксу;
      * `nsfw_level` выше потолка `civitai.MAX_NSFW_LEVEL` или не число;
      * слов в промпте меньше `civitai.MIN_PROMPT_WORDS`;
      * `image_url` повторяется — сбор дедуплицирует по нему, и повтор значит,
        что дедупликация перестала работать.

    Все пороги ИМПОРТИРУЮТСЯ из `studio/mcp/civitai.py` (правило Е1): вторая
    копия потолка NSFW разъехалась бы с той, по которой строки собирались, и
    проверка пропускала бы ровно то, что фильтр перестал ловить.
    """
    target = path or civitai.DEFAULT_OUTPUT_PATH
    if not target.is_file():
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"собранных пар нет: {target.name} не найден (файл не коммитится, "
                "см. .gitignore и studio/knowledge/PROVENANCE.md) — "
                "проверять нечего, и это НЕ «годно»"
            ),
        }
    нарушения: list[str] = []
    строк = 0
    видели: set[str] = set()
    for номер, строка in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        строка = строка.strip()
        if not строка or строка.startswith("//"):
            continue
        строк += 1
        try:
            запись = json.loads(строка)
        except ValueError:
            нарушения.append(f"строка {номер}: не JSON")
            continue
        if not isinstance(запись, dict):
            нарушения.append(f"строка {номер}: не объект")
            continue
        for поле in civitai.REQUIRED_ROW_FIELDS:
            if not str(запись.get(поле) or "").strip():
                нарушения.append(f"строка {номер}: нет обязательного поля {поле}")
        if not str(запись.get("provenance") or "").startswith(civitai.PROVENANCE_PREFIX):
            нарушения.append(f"строка {номер}: provenance без префикса {civitai.PROVENANCE_PREFIX}")
        уровень = запись.get("nsfw_level")
        if not isinstance(уровень, int) or isinstance(уровень, bool):
            нарушения.append(f"строка {номер}: nsfw_level не число")
        elif уровень > civitai.MAX_NSFW_LEVEL:
            нарушения.append(
                f"строка {номер}: nsfw_level {уровень} выше потолка {civitai.MAX_NSFW_LEVEL}"
            )
        слов = len(str(запись.get("prompt") or "").split())
        if слов < civitai.MIN_PROMPT_WORDS:
            нарушения.append(f"строка {номер}: слов в промпте {слов}")
        url = str(запись.get("image_url") or "")
        if url and url in видели:
            нарушения.append(f"строка {номер}: image_url повторяется")
        видели.add(url)
    if not строк:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"{target.name} есть, но в нём ни одной строки — проверять нечего",
        }
    заметка = f"собранных пар {строк}, разных изображений {len(видели)}"
    if нарушения:
        заметка += "\n  " + "\n  ".join(нарушения[:10])
        if len(нарушения) > 10:
            заметка += f"\n  ... и ещё {len(нарушения) - 10}"
    return {
        "outcome": FAIL if нарушения else PASS,
        "checked": строк,
        "violations": len(нарушения),
        "unmeasured": 0,
        "note": заметка,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="без сети: проверить форму уже собранных пар (нет файла — «не смогли»)",
    )
    parser.add_argument("--pages", type=int, default=1, help="model listing pages to walk")
    parser.add_argument("--per-page", type=int, default=20, help="models per listing page")
    parser.add_argument("--versions", type=int, default=25, help="hard ceiling on version requests")
    parser.add_argument("--sort", default="Most Downloaded")
    parser.add_argument(
        "--base-model",
        action="append",
        default=[],
        metavar="FAMILY",
        help=(
            "a Civitai base-model family to restrict the harvest to, e.g. 'Flux.1 D', "
            "'Flux.1 S', 'Wan Video 14B t2v', 'Qwen'. Repeatable; one API call per "
            "family, because the API honours only the first baseModels parameter. "
            "CASE-SENSITIVE, and an unrecognised name collects nothing without "
            "erroring. Omit it and the harvest is whatever the sort surfaces, which "
            "MEASURED is the Stable Diffusion checkpoint ecosystem and nothing this "
            "project targets."
        ),
    )
    parser.add_argument("--delay", type=float, default=civitai.DEFAULT_DELAY_SECONDS)
    parser.add_argument("--rights", default=DEFAULT_RIGHTS)
    parser.add_argument(
        "--safe-models-only",
        action="store_true",
        help=(
            "skip checkpoints that publish above PG-13 themselves, not just images "
            "that do. Every collected image is at PG or PG-13 either way; this is "
            "about whose checkpoint the wording came from. The count is printed "
            "whether or not this is set, so the decision can be made from a number."
        ),
    )
    parser.add_argument(
        "--summary", action="store_true", help="report what is held, collect nothing"
    )
    args = parser.parse_args(argv)

    if args.check:
        итог = проверить_собранное()
        print(итог["note"])
        print(
            f"\nпроверено {итог['checked']}\nнарушений {итог['violations']}\n"
            f"не смогли {итог['unmeasured']}"
        )
        return 0 if итог["outcome"] == PASS else (1 if итог["outcome"] == FAIL else 2)

    path = civitai.DEFAULT_OUTPUT_PATH
    if args.summary:
        rows = []
        if path.is_file():
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        held = civitai.summarise(rows)
        print(f"{held['outcome']}: {held['note']}")
        for provenance, count in sorted(held["by_provenance"].items(), key=lambda kv: -kv[1]):
            print(f"  {count:>5}  {provenance}")
        return 0 if held["outcome"] == PASS else 1

    families: list[str] = args.base_model or [""]
    outcomes = []
    for family in families:
        out = civitai.collect(
            harvested=date.today().isoformat(),
            rights=args.rights,
            pages=args.pages,
            per_page=args.per_page,
            sort=args.sort,
            base_model=family,
            safe_models_only=args.safe_models_only,
            max_versions=args.versions,
            delay_seconds=args.delay,
        )
        label = family or "(unfiltered)"
        print(f"{out['outcome']:<18} {label}: {out['note']}")
        outcomes.append(out)

    # One family collecting nothing does not make the run a success, and does
    # not make it a failure either. The counts go out beside the verdict so a
    # reader sees the denominator (house rule P2).
    got = sum(int(o["written"]) for o in outcomes)
    broke = [f for f, o in zip(families, outcomes) if o["outcome"] == FAIL]
    empty = [f for f, o in zip(families, outcomes) if o["outcome"] == UNMEASURED]
    print(
        f"\nсемейств {len(families)}\nзаписей {got}\n"
        f"сломалось {len(broke)}\nбез результата {len(empty)}"
    )
    for label, names in (("сломалось на", broke), ("ничего не дало", empty)):
        if names:
            print(f"  {label}: " + ", ".join(f or "(unfiltered)" for f in names))
    return exit_code([o["outcome"] for o in outcomes], got)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
