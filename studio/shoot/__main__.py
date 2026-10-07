"""python -m studio.shoot validate|compile|qa

    validate PRODUCTION.json                проверить все планы до рендера
    compile  PRODUCTION.json OUT_DIR [ID…]  промпт и граф ComfyUI на каждый план
    qa       VIDEO.mp4 RIG                  замер готового плана

Код выхода: 0 — «годно», 1 — «не годно», 2 — «не смогли».
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from studio.shoot import qa, validate
from studio.shoot.compile import compile_shot
from studio.shoot.h3graph import build
from studio.shoot.spec import load

EXIT = {"годно": 0, "не годно": 1, "не смогли": 2}


def _validate(path: str) -> int:
    prod = load(path)
    found = validate.check(prod)
    for f in found:
        print(f"{f.severity:9} {f.shot:12} {f.rule:10} {f.message}")
    verdict = validate.outcome(found)
    print(f"{verdict}: {len(prod.shots)} планов, {len(found)} замечаний")
    return EXIT[verdict]


def _compile(path: str, out: str, ids: list[str]) -> int:
    prod = load(path)
    found = validate.check(prod)
    if validate.outcome(found) != "годно":
        print("не годно: сначала validate", file=sys.stderr)
        return 1
    base = Path(path).resolve().parent
    dst = Path(out)
    dst.mkdir(parents=True, exist_ok=True)
    for shot in prod.shots:
        if ids and shot.id not in ids:
            continue
        c = compile_shot(prod, shot)
        refs = [str((base / r).resolve()) for r in c.refs]
        (dst / f"{shot.id}.prompt.txt").write_text(c.prompt + "\n", encoding="utf-8")
        job = {
            "name": shot.id,
            "rig": shot.rig,
            "refs": refs,
            "seconds": c.seconds,
            "seed": c.seed,
            "graph": build(c, f"shoot/{shot.id}"),
        }
        (dst / f"{shot.id}.job.json").write_text(
            json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"{shot.id}: {len(refs)} рефов, {c.seconds} с, {shot.rig}")
    return 0


def _qa(video: str, rig: str) -> int:
    rep = qa.measure(video, rig)
    print(json.dumps(asdict(rep), ensure_ascii=False, indent=1))
    return EXIT[rep.outcome]


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "validate":
        return _validate(argv[1])
    if len(argv) >= 3 and argv[0] == "compile":
        return _compile(argv[1], argv[2], argv[3:])
    if len(argv) == 3 and argv[0] == "qa":
        return _qa(argv[1], argv[2])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
