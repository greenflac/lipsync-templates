"""python -m studio.shoot validate|compile|qa

    validate PRODUCTION.json                проверить все планы до рендера
    compile  PRODUCTION.json OUT_DIR [ID…]  промпт и граф ComfyUI на каждый план
    qa       VIDEO.mp4 RIG                  замер готового плана
    render   PRODUCTION.json OUT_DIR ID…    рендер + QA, обе попытки — в журнал
             (env COMFY_URL — адрес ComfyUI, GPU_RATE_USD_H — цена часа пода,
              H3_UNET/H3_CLIP — другие веса; пакет сверх budget_usd не стартует)
    journal  PRODUCTION.json                проверка журнала и сводка для постмортема
    log      PRODUCTION.json KIND STAGE BY "итог" [ключ=значение | ключ:=json …]
             ручная строка: решение, отзыв, инцидент
    edit     PRODUCTION.json EDIT.json RENDERS_DIR OUT.mp4
             монтаж; плана без рендера в RENDERS_DIR — слейт той же длины

Код выхода: 0 — «годно», 1 — «не годно», 2 — «не смогли».
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from studio.shoot import journal, qa, validate
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


def _render(path: str, out: str, ids: list[str]) -> int:
    from studio.shoot.render import render_shot

    url, rate = os.environ.get("COMFY_URL", ""), os.environ.get("GPU_RATE_USD_H", "")
    if not url or not rate:
        print("не смогли: нужны COMFY_URL и GPU_RATE_USD_H", file=sys.stderr)
        return 2
    prod = load(path)
    if validate.outcome(validate.check(prod)) != "годно":
        print("не годно: сначала validate", file=sys.stderr)
        return 1
    from studio.shoot.render import budget_problem

    rows = journal.load(Path(path).parent / "journal.jsonl")
    over = budget_problem(prod.budget_usd, prod, ids, rows, float(rate))
    if over:
        print(f"не годно: {over}", file=sys.stderr)
        return 1
    from studio.shoot.h3graph import CLIP, UNET

    unet = os.environ.get("H3_UNET") or UNET
    clip = os.environ.get("H3_CLIP") or CLIP
    worst = 0
    for sid in ids:
        rev, qev = render_shot(
            prod, Path(path).parent, sid, Path(out), url, float(rate), unet=unet, clip=clip
        )
        print(rev["summary"], "|", (qev or {}).get("notes", ""))
        worst = max(worst, EXIT[rev["outcome"]])
    return worst


def _journal(path: str) -> int:
    rows = journal.load(Path(path).parent / "journal.jsonl")
    bad = journal.check(rows)
    for b in bad:
        print("не годно:", b)
    print(journal.render_summary(journal.summarize(rows)))
    return 1 if bad else 0


def _log(path: str, kind: str, stage: str, by: str, summary: str, extra: list[str]) -> int:
    ev: dict[str, object] = {"kind": kind, "stage": stage, "by": by, "summary": summary}
    for kv in extra:
        if ":=" in kv:
            k, v = kv.split(":=", 1)
            ev[k] = json.loads(v)
        else:
            k, v = kv.split("=", 1)
            ev[k] = v
    try:
        row = journal.append(Path(path).parent / "journal.jsonl", ev)
    except ValueError as e:
        print("не годно:", e, file=sys.stderr)
        return 1
    print(row["id"])
    return 0


def _edit(path: str, edit_path: str, renders_dir: str, out: str) -> int:
    from studio.shoot import edit

    prod = load(path)
    e = edit.load(edit_path)
    base = Path(edit_path).resolve().parent
    bad = edit.problems(e, base, {s.id for s in prod.shots})
    for b in bad:
        print("не годно:", b)
    if bad:
        return 1
    renders: dict[str, Path] = {}
    for shot in prod.shots:  # самый свежий файл плана; принятый дубль кладётся последним
        found = sorted(Path(renders_dir).glob(f"{shot.id}*.mp4"), key=lambda p: p.stat().st_mtime)
        if found:
            renders[shot.id] = found[-1]
    slates = edit.assemble(e, base, renders, {s.id: s.purpose for s in prod.shots}, Path(out))
    print(f"{out}: {e.length:.1f} с; рендеров {len(renders)}, слейтов {len(slates)}")
    for sid, p in sorted(renders.items()):
        print(f"  {sid:20} ← {p.name}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "validate":
        return _validate(argv[1])
    if len(argv) >= 3 and argv[0] == "compile":
        return _compile(argv[1], argv[2], argv[3:])
    if len(argv) == 3 and argv[0] == "qa":
        return _qa(argv[1], argv[2])
    if len(argv) >= 4 and argv[0] == "render":
        return _render(argv[1], argv[2], argv[3:])
    if len(argv) == 2 and argv[0] == "journal":
        return _journal(argv[1])
    if len(argv) == 5 and argv[0] == "edit":
        return _edit(argv[1], argv[2], argv[3], argv[4])
    if len(argv) >= 6 and argv[0] == "log":
        return _log(argv[1], argv[2], argv[3], argv[4], argv[5], argv[6:])
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
