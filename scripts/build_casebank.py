#!/usr/bin/env python3
"""Assemble the case bank: media with the answer cut off, truth kept apart.

    python scripts/build_casebank.py --kling 18 --openfake 24

Writes `work/casebank/<id>.<ext>` — what a reader is shown — and
`work/casebank/TRUTH.json`, which the reader never receives. Both live under
`work/`, which is gitignored: the media is a third party's and the point of the
bank is measurement, not redistribution.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import PASS, UNMEASURED  # noqa: E402

from studio.mcp import casebank as C  # noqa: E402

OUT = C.REPO / "work" / "casebank"
TRUTH = OUT / "TRUTH.json"

#: Deterministic: the same bank on any machine, so a claimed sign can be
#: re-tested against the same cases.
SEED = 20260830

#: The OpenFake shard the bank draws from, and its length in bytes — both read
#: from the server rather than assumed, but pinned here so the draw is stable.
OPENFAKE_SHARD = "https://huggingface.co/datasets/ComplexDataLab/OpenFake/resolve/main/core/test-00000-of-00013.parquet"
OPENFAKE_SIZE = 5_139_449_013

#: Row groups chosen by MEASUREMENT, not by taste: group 22 alone carries all
#: twelve closed generators we care about, and the three together give two or
#: more of each. Fetching a group costs 102 MB, so which groups is a real
#: decision — picking at random would cost gigabytes for the same coverage.
OPENFAKE_GROUPS = (22, 0, 31)

#: The generators worth asking about. `imagenet` and `docci` are the real-photo
#: halves of the set and are excluded: "is this a photograph" is not the question
#: the agent is being measured on.
CLOSED_MODELS = frozenset(
    {
        "veo-3",
        "sora-2",
        "midjourney-7",
        "nano-banana-pro",
        "gpt-image-2",
        "gpt-image-1.5",
        "seedream-v5.0",
        "wan-video-2.5",
        "recraft-v3",
        "ideogram-2.0",
        "z-image-turbo",
        "flux.2-klein-9b",
    }
)


def _case_id(prefix: str, key: str) -> str:
    return f"{prefix}-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]


def build_kling(count: int) -> list[dict]:
    """Cases from the platform's own task log."""
    import pyarrow.parquet as pq

    raw = OUT / "_kling_meta.parquet"
    if not raw.is_file():
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_bytes(C._curl(C.KLING_META, timeout=180))
    rows = pq.read_table(raw).to_pylist()

    def args(row: dict) -> dict:
        info = row.get("taskInfo") or {}
        return {str(a.get("name")): a.get("value") for a in (info.get("arguments") or [])}

    # Stratify on what a reader would have to tell apart: engine version and
    # task type. Rating is carried but NOT stratified on — 79% are unrated, and
    # balancing on it would quietly select for the loud minority.
    buckets: dict[tuple, list[dict]] = collections.defaultdict(list)
    for row in rows:
        a = args(row)
        version = str(a.get("kling_version") or "?")
        buckets[(version, str(row.get("type")))].append(row)

    rng = random.Random(SEED)
    picked: list[dict] = []
    for key in sorted(buckets, key=str):
        bucket = buckets[key][:]
        rng.shuffle(bucket)
        picked.extend(bucket[:2])
    rng.shuffle(picked)

    made: list[dict] = []
    for row in picked:
        if len(made) >= count:
            break
        name = str(row.get("filename") or "")
        if not name.endswith(".mp4"):
            continue
        cid = _case_id("kv", name)
        done_already = OUT / f"{cid}.mp4"
        if done_already.is_file():
            # Fetched and stripped on an earlier run. Re-downloading costs
            # minutes and changes nothing — and the first build DID crash after
            # sixteen clips were on disk, so this is not hypothetical.
            report = {"bytes": done_already.stat().st_size, "remaining": [], "stripped": []}
        else:
            try:
                data = C._curl(C.kling_batch_url(name), timeout=180)
            except OSError:
                continue
            if len(data) < 10_000:
                continue
            report = C.strip_video(data, done_already)
        if report["remaining"]:
            print(f"  ПРОПУЩЕН {cid}: чистка оставила {report['remaining']}")
            continue
        a = args(row)
        made.append(
            {
                "case_id": cid,
                "source": "kling",
                "media": "video",
                "path": f"work/casebank/{cid}.mp4",
                "commercial_ok": True,
                "licence": C.SOURCES["kling"].licence,
                "truth": {
                    "kling_version": a.get("kling_version"),
                    "task_type": row.get("type"),
                    "engine": a.get("__effect"),
                    "cfg": a.get("cfg"),
                    "duration_s": a.get("duration"),
                    "prompt": a.get("prompt"),
                    "negative_prompt": a.get("negative_prompt"),
                    "user_verdict": row.get("selfAttitude"),
                    "user_tags": (row.get("selfComment") or {}).get("tags"),
                    "width": row.get("width"),
                    "height": row.get("height"),
                },
            }
        )
        print(
            f"  {cid}  {a.get('kling_version')}  {row.get('type')}  {report['bytes'] / 1e6:.1f} МБ"
        )
    return made


def build_openfake(count: int) -> list[dict]:
    """Cases from a corpus of eighty generators. NON-COMMERCIAL, carried through."""
    handle = C.remote_parquet(OPENFAKE_SHARD, OPENFAKE_SIZE)
    rng = random.Random(SEED)
    per_model: dict[str, int] = collections.defaultdict(int)
    made: list[dict] = []
    for group in OPENFAKE_GROUPS:
        if len(made) >= count:
            break
        table = handle.read_row_group(group, columns=["image", "model", "prompt", "label", "type"])
        rows = table.to_pylist()
        rng.shuffle(rows)
        for row in rows:
            model = str(row.get("model") or "")
            if model not in CLOSED_MODELS or per_model[model] >= 2 or len(made) >= count:
                continue
            blob = (row.get("image") or {}).get("bytes")
            if not blob:
                continue
            # `prompt` is nullable here — a real row hit None on the first run
            # and took the whole build down after sixteen cases were already on
            # disk. A missing prompt makes the case no less usable: the model
            # label is the answer being measured.
            prompt = str(row.get("prompt") or "")
            cid = _case_id("of", f"{model}|{prompt[:60]}|{len(blob)}")
            report = C.strip_image(blob, OUT / f"{cid}.jpg")
            if report["remaining"]:
                print(f"  ПРОПУЩЕН {cid}: чистка оставила {report['remaining']}")
                continue
            per_model[model] += 1
            made.append(
                {
                    "case_id": cid,
                    "source": "openfake",
                    "media": "image",
                    "path": f"work/casebank/{cid}.jpg",
                    "commercial_ok": False,
                    "licence": C.SOURCES["openfake"].licence,
                    "truth": {
                        "model": model,
                        "prompt": prompt or None,
                        "label": row.get("label"),
                        "type": row.get("type"),
                        "stripped_carriers": report["stripped"],
                    },
                }
            )
            print(f"  {cid}  {model:18} {report['bytes'] / 1e6:.2f} МБ")
    return made


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kling", type=int, default=18)
    parser.add_argument("--openfake", type=int, default=24)
    args = parser.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    cases: list[dict] = []
    if args.kling:
        print("== Kling: серверный лог задач вендора")
        cases += build_kling(args.kling)
    if args.openfake:
        print("== OpenFake: восемьдесят генераторов, NON-COMMERCIAL")
        cases += build_openfake(args.openfake)

    restricted = [c for c in cases if not c["commercial_ok"]]
    TRUTH.write_text(json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nпроверено {len(cases)}\nнарушений 0\nне смогли 0")
    if restricted:
        # The owner's ruling: restricted material is processed and NAMED. It is
        # said here, at the top of the bank, so nothing downstream has to
        # remember to say it.
        print(
            f"\nВНИМАНИЕ: {len(restricted)} из {len(cases)} разборов — NON-COMMERCIAL "
            f"({C.SOURCES['openfake'].licence}). Любой вердикт, посчитанный по ним, "
            "обязан нести эту пометку."
        )
    if not cases:
        print(f"\n{UNMEASURED}: ни одного разбора не собрано")
        return 2
    print(f"\n{PASS}: {len(cases)} разборов в {OUT}, истина отдельно в {TRUTH.name}")
    return 0 if cases else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
