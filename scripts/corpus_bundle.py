#!/usr/bin/env python3
"""Собрать корпус в связку, которую можно положить в приватный репозиторий.

    python scripts/corpus_bundle.py --out work/bundle       # собрать
    python scripts/corpus_bundle.py --verify work/bundle    # сверить с манифестом

ЗАЧЕМ

Корпус и записи стенда лежат в `.gitignore` по решению владельца: репозиторий
публичный, а его LICENSE заявляет права на «промты, содержащиеся здесь», что
было бы заявкой на чужую работу. Следствие — при закрытии сессии всё собирается
заново. Нужен адрес, и адрес этот приватный.

ЧТО КЛАДЁТСЯ, А ЧТО НЕТ, И ПОЧЕМУ ИМЕННО ТАК

Кладётся ТЕКСТ И РЕЦЕПТ, не байты чужих медиафайлов. ИЗМЕРЕНО 2026-08-31:

    текстовые корпуса          ~7 МБ
    записи стенда (*.json)    620 КБ
    медиа банка               253 МБ   ← НЕ кладётся

Три причины, и первая не про размер. (1) Мы не перепубликуем чужие ролики и
картинки: собрать для замера и раздать — разные вещи. (2) Банк пересобирается
детерминированно: `TRUTH.json` несёт исходные URL, сид зафиксирован, номера
разборов выводятся из содержимого. (3) 253 МБ чужого видео в git — это не
хранилище, это свалка.

ЧЕСТНОЕ ОГРАНИЧЕНИЕ, а не мелкий шрифт: рецепт воспроизводится ровно до тех
пор, пока источники отвечают. Ролик, снятый загрузчиком с Civitai, исчезнет
вместе с его страницей, и тогда останется запись о том, что он был, и её
истина — но не он сам. Кому нужны байты, тот держит их у себя; здесь их нет
намеренно.

МАНИФЕСТ

У каждого файла sha256 и число строк. Это делает вопрос «корпус разъехался?»
отвечаемым, а не предметом веры: `--verify` печатает `проверено / расхождений /
не смогли`, и «файла нет» — третий исход, а не расхождение.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

#: Что едет в приватный репозиторий. Пути относительно корня, и каждый назван
#: явно: связка «всё, что в gitignore» однажды увезла бы туда чужой мусор.
CARRIED = (
    "studio/knowledge/civitai_prompts.jsonl",
    "studio/knowledge/gallery_prompts.jsonl",
    "work/casebank/TRUTH.json",
    "work/casebank/BLIND_MAP.json",
    "work/casebank/ANSWERS.json",
    "work/casebank/ANSWERS_cropped.json",
    "work/casebank/ANSWERS_merged.json",
    "work/casebank/SCORE.json",
)

#: Расширения, которые в связку не попадают НИКОГДА, даже если кто-то допишет
#: их в CARRIED. Список выше — намерение, этот — предохранитель.
NEVER = frozenset({".mp4", ".jpg", ".jpeg", ".png", ".webp", ".mov", ".parquet"})

MANIFEST = "MANIFEST.json"


def digest(path: Path) -> dict:
    """sha256 и число строк одного файла."""
    data = path.read_bytes()
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "lines": data.count(b"\n"),
    }


def plan(
    names: tuple[str, ...] = CARRIED, root: Path = REPO
) -> tuple[list[str], list[str], list[str]]:
    """(что кладём, чего нет на диске, что отвергнуто предохранителем).

    Вынесено из точки входа (Т5): решение о том, что поедет, обязано быть
    достижимо тестом без файлов на диске.
    """
    carried: list[str] = []
    missing: list[str] = []
    refused: list[str] = []
    for name in names:
        if Path(name).suffix.lower() in NEVER:
            refused.append(name)
        elif (root / name).is_file():
            carried.append(name)
        else:
            missing.append(name)
    return carried, missing, refused


def compare(manifest: dict, current: dict) -> tuple[list[str], list[str]]:
    """(расхождения, не смогли сверить). Второе — файл есть в манифесте, но не на диске."""
    differ: list[str] = []
    absent: list[str] = []
    for name, expected in manifest.items():
        got = current.get(name)
        if got is None:
            absent.append(name)
        elif got["sha256"] != expected["sha256"]:
            differ.append(f"{name}: {expected['lines']} строк → {got['lines']}")
    return sorted(differ), sorted(absent)


def build(out: Path) -> dict:
    carried, missing, refused = plan()
    out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict] = {}
    for name in carried:
        target = out / Path(name).name
        shutil.copyfile(REPO / name, target)
        manifest[Path(name).name] = dict(digest(target), source=name)
    (out / MANIFEST).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    return {"carried": carried, "missing": missing, "refused": refused, "manifest": manifest}


def verify(out: Path) -> dict:
    path = out / MANIFEST
    if not path.is_file():
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "differ": [],
            "absent": [],
            "note": f"нет {path}",
        }
    manifest = json.loads(path.read_text(encoding="utf-8"))
    current = {name: digest(out / name) for name in manifest if (out / name).is_file()}
    differ, absent = compare(manifest, current)
    outcome = FAIL if differ else (PASS if current else UNMEASURED)
    return {
        "outcome": outcome,
        "checked": len(current),
        "differ": differ,
        "absent": absent,
        "note": (
            f"{len(current)} файлов совпали с манифестом"
            if outcome is PASS
            else f"{len(differ)} файлов разъехались"
            if differ
            else "ни одного файла из манифеста нет на диске"
        ),
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="work/bundle")
    parser.add_argument("--verify", metavar="DIR", default="")
    args = parser.parse_args(argv)

    if args.verify:
        out = verify(Path(args.verify))
        for name in out["differ"]:
            print(f"  РАЗЪЕХАЛСЯ {name}")
        for name in out["absent"]:
            print(f"  НЕТ НА ДИСКЕ {name}")
        print(
            f"\nпроверено {out['checked']}\nрасхождений {len(out['differ'])}\nне смогли {len(out['absent'])}"
        )
        print(f"\n{out['outcome']}: {out['note']}")
        return {PASS: 0, FAIL: 1, UNMEASURED: 2}[out["outcome"]]

    made = build(Path(args.out))
    for name in made["carried"]:
        row = made["manifest"][Path(name).name]
        print(f"  {Path(name).name:26} {row['lines']:6} строк  {row['bytes'] / 1e6:6.2f} МБ")
    for name in made["missing"]:
        print(f"  НЕТ НА ДИСКЕ {name}")
    for name in made["refused"]:
        print(f"  ОТКАЗАНО (медиа не едет) {name}")
    total = sum(r["bytes"] for r in made["manifest"].values())
    print(
        f"\nпроверено {len(made['carried'])}\nнарушений {len(made['refused'])}\nне смогли {len(made['missing'])}"
    )
    print(f"\n{PASS if made['carried'] else UNMEASURED}: связка {total / 1e6:.1f} МБ в {args.out}")
    return 0 if made["carried"] else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
