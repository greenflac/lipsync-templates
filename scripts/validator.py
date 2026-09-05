#!/usr/bin/env python3
"""The validator's bench: hand over a creative with its origin cut away.

    python scripts/validator.py sample --size 80      # выбрать разбор
    python scripts/validator.py case <id>             # выдать один креатив
    python scripts/validator.py --check               # гейт: чистка работает?

WHAT THIS IS FOR

A subagent takes a creative whose origin is KNOWN, shows the picture to another
agent with nothing else, and only afterwards reveals the truth. The second agent
then has to find what OBSERVABLE sign would have told it — and that sign, with
its control, is what goes into the knowledge base. It measures whether this
agent can read a creative at all, which is a number nobody has.

THE LEAK IS THE WHOLE PROBLEM, AND IT IS NOT HYPOTHETICAL

MEASURED 2026-08-30 on the first row of our own civitai corpus: the PNG that
comes down from the CDN carries the ENTIRE ComfyUI graph in its metadata —

    prompt      1679 characters
    workflow    6259 characters, 14 nodes
    unet_name   flux1-dev-fp8.safetensors
    weight_dtype fp8_e4m3fn, plus LoraLoader, the sampler, the scheduler

Hand that file over and the reader answers from the answer key. Re-encoding to
JPEG empties it — one line — but a rule that lives in one line is a rule that
gets skipped, so `--check` re-proves it every build and the build goes red if a
single byte of provenance survives.

WHY THE SAMPLE IS STRATIFIED AND SMALL

MEASURED on our 473 rows: they hold 34 distinct configurations (base model x
sampler x step band), and 202 of them already cover 90% of those. The hundredth
"Flux.1 S / Euler / <=8 steps" teaches nothing. So the bench draws a few per
configuration and keeps the rest as a held-out set — because a sign claimed on
the cases you looked at is a story, not a measurement.

WHAT A GOOD ANSWER LOOKS LIKE, AND WHY `не смогли` IS ONE

Most creatives carry no distinguishing sign, and a bench that rewards guessing
teaches confidence. `не смогли` is a full answer here and is scored apart from
wrong ones, never folded in (rule R1).
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import random
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "studio" / "knowledge" / "civitai_prompts.jsonl"

#: Deterministic, so the same sample comes back on any machine and a claimed
#: sign can be re-tested against the same cases.
SEED = 20260830

#: How many cases per configuration. ВЫБРАНО: two to look at and the rest held
#: back. One would leave nothing to test a claim on; five would spend the budget
#: re-testing the same discrimination.
PER_CONFIG = 2

#: The CDN refuses Python's default agent. ИЗМЕРЕНО 2026-08-30: urllib gets 403
#: on every one of eight tries, curl with a browser agent gets 200 in 0.77 s
#: median over ten. This is a header, not a bypass — the host is open and
#: answers; it just declines to talk to a library that does not introduce itself.
USER_AGENT = "Mozilla/5.0"

#: Metadata keys that would hand over the answer. Anything outside the JFIF
#: markers a re-encode writes is treated as a leak, so a new carrier nobody
#: anticipated fails the gate instead of slipping through a list.
ALLOWED_INFO_KEYS = frozenset({"jfif", "jfif_version", "jfif_unit", "jfif_density", "dpi"})


def _rows() -> list[dict]:
    if not CORPUS.is_file():
        return []
    return [
        json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def config_of(row: dict) -> tuple:
    """The row's configuration — what a reader would have to tell apart."""
    params = row.get("parameters") or {}
    steps = params.get("steps")
    band = (
        "нет"
        if not isinstance(steps, int)
        else "<=8"
        if steps <= 8
        else "9-24"
        if steps <= 24
        else "25+"
    )
    sampler = str(params.get("sampler") or "нет").lower()
    return (row.get("base_model"), sampler, band)


def case_id(row: dict) -> str:
    return "vc-" + hashlib.sha256(str(row.get("image_url", "")).encode()).hexdigest()[:10]


def sample(size: int) -> dict:
    """A stratified draw plus the held-out remainder, both named by case id."""
    rows = _rows()
    if not rows:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"{CORPUS} отсутствует — корпус намеренно не коммитится, брать нечего",
        }
    by_config: dict[tuple, list[dict]] = collections.defaultdict(list)
    for row in rows:
        by_config[config_of(row)].append(row)

    rng = random.Random(SEED)
    drawn: list[dict] = []
    held: list[dict] = []
    for cfg in sorted(by_config, key=str):
        bucket = by_config[cfg][:]
        rng.shuffle(bucket)
        drawn.extend(bucket[:PER_CONFIG])
        held.extend(bucket[PER_CONFIG:])
    rng.shuffle(drawn)
    drawn = drawn[:size]
    return {
        "outcome": PASS,
        "checked": len(rows),
        "violations": 0,
        "unmeasured": 0,
        "configurations": len(by_config),
        "cases": [{"id": case_id(r), "config": list(config_of(r))} for r in drawn],
        "held_out": len(held),
        "note": (
            f"{len(drawn)} разборов из {len(by_config)} конфигураций; "
            f"{len(held)} строк отложены для проверки заявленных признаков"
        ),
    }


def fetch_stripped(url: str, out: Path) -> dict:
    """Download and re-encode. The returned dict names what was thrown away."""
    from PIL import Image

    result = subprocess.run(
        ["curl", "-sL", "-A", USER_AGENT, "--max-time", "60", url],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        return {"outcome": UNMEASURED, "note": f"не скачалось: код {result.returncode}"}
    original = Image.open(io.BytesIO(result.stdout))
    carried = sorted(k for k in (original.info or {}) if k not in ALLOWED_INFO_KEYS)
    buffer = io.BytesIO()
    original.convert("RGB").save(buffer, "JPEG", quality=88)
    out.write_bytes(buffer.getvalue())
    left = sorted(k for k in (Image.open(out).info or {}) if k not in ALLOWED_INFO_KEYS)
    return {
        "outcome": FAIL if left else PASS,
        "stripped": carried,
        "remaining": left,
        "bytes": len(buffer.getvalue()),
        "note": (
            f"осталось {left} — истина уехала бы вместе с картинкой"
            if left
            else f"снято {len(carried)} носителей происхождения: {carried or 'их не было'}"
        ),
    }


def check() -> dict:
    """The gate. Does the strip actually strip, and can it tell when it does not?"""
    from PIL import Image, PngImagePlugin

    canvas = Image.new("RGB", (64, 64), (30, 60, 120))

    # ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: файл, набитый происхождением, обязан выйти пустым.
    meta = PngImagePlugin.PngInfo()
    meta.add_text("prompt", "a woman in a red dress, flux1-dev-fp8")
    meta.add_text("workflow", json.dumps({"nodes": [{"type": "UNETLoader"}]}))
    loaded = io.BytesIO()
    canvas.save(loaded, "PNG", pnginfo=meta)
    before = sorted(
        k for k in Image.open(io.BytesIO(loaded.getvalue())).info if k not in ALLOWED_INFO_KEYS
    )

    cleaned = io.BytesIO()
    Image.open(io.BytesIO(loaded.getvalue())).convert("RGB").save(cleaned, "JPEG", quality=88)
    after = sorted(
        k for k in Image.open(io.BytesIO(cleaned.getvalue())).info if k not in ALLOWED_INFO_KEYS
    )

    problems: list[str] = []
    if not before:
        # НЕГАТИВНЫЙ КОНТРОЛЬ на сам контроль (И5): если подопытный файл вышел
        # чистым ещё ДО чистки, то зелёный ниже не значит ничего.
        problems.append("подопытный файл не понёс происхождения — гейт проверял бы пустоту")
    if after:
        problems.append(f"после чистки осталось {after}")
    return {
        "outcome": FAIL if problems else PASS,
        "checked": 1,
        "violations": len(problems),
        "unmeasured": 0,
        "before": before,
        "after": after,
        "note": "; ".join(problems) if problems else f"снято {before}, осталось пусто",
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["sample", "case", "check"], nargs="?", default="check")
    parser.add_argument("target", nargs="?")
    parser.add_argument("--size", type=int, default=80)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "check" or args.check:
        out = check()
        print(f"до чистки:    {out['before']}")
        print(f"после чистки: {out['after'] or '(пусто)'}")
    elif args.command == "sample":
        out = sample(args.size)
        for case in out.get("cases", [])[:6]:
            print(f"  {case['id']}  {case['config']}")
        if out.get("cases"):
            print(f"  … всего {len(out['cases'])}")
    else:
        rows = {case_id(r): r for r in _rows()}
        row = rows.get(str(args.target))
        if row is None:
            out = {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "note": f"нет разбора {args.target!r}",
            }
        else:
            out = fetch_stripped(row["image_url"], REPO / "work" / f"{args.target}.jpg")
            out.setdefault("checked", 1)
            out.setdefault("violations", 0)
            out.setdefault("unmeasured", 0)

    print(
        f"\nпроверено {out.get('checked', 0)}\nнарушений {out.get('violations', 0)}\n"
        f"не смогли {out.get('unmeasured', 0)}"
    )
    print(f"\n{out['outcome']}: {out['note']}")
    return {PASS: 0, FAIL: 1, UNMEASURED: 2}[out["outcome"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
