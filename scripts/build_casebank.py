#!/usr/bin/env python3
"""Assemble the case bank: media with the answer cut off, truth kept apart.

    python scripts/build_casebank.py --kling 18 --openfake 24 --civitai 16

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


CIVITAI_MODELS = (
    "https://civitai.com/api/v1/models?limit=40&page={page}&sort=Most%20Downloaded&period=Month"
)
CIVITAI_VERSION = "https://civitai.com/api/v1/model-versions/{version_id}"

#: How deep to walk the model listing before giving up. ВЫБРАНО 6: the probe run
#: (scripts/probe_civitai_video.py) got 60 versions with video from three pages,
#: but only a third of those sat on a VIDEO base — six pages leaves room for the
#: filter to reject two thirds and still fill a bank. One request per page.
CIVITAI_PAGES = 6

#: At most this many clips from one model version. The reason is the same one
#: `MAX_PER_PROVENANCE` exists for in the retriever: one uploader's showcase
#: page is one author's taste, and sixteen clips from it would measure that
#: author rather than the model.
CIVITAI_PER_VERSION = 2


def _civitai_base_family(base: str) -> str | None:
    """The video engine a page claims, or None if the page is not about video."""
    text = str(base or "").lower()
    for known in C.CIVITAI_VIDEO_BASES:
        if known in text:
            return known
    return None


def build_civitai(count: int) -> list[dict]:
    """Cases whose truth is the UPLOADER'S WORD, taken deliberately.

    Accepted by the owner 2026-08-31 to break the bank's missing negative
    control: every video in it was Kling, so "guessed the family" was correct by
    construction and measured nothing. Any non-Kling video breaks that, and a
    noisy label breaks it just as well as a clean one — what the noise costs is
    the precision of the number, not the existence of the measurement.

    The label is trusted no further than that. `truth_grade: uploader_claim`
    travels on every case, the scorer reports the grade apart, and a verdict
    computed over these carries the warning at the top.
    """

    def api(url: str) -> dict:
        try:
            return json.loads(C._curl(url, timeout=60) or b"{}")
        except (OSError, json.JSONDecodeError):
            return {}

    # Walk the listing first: it says which versions have video, so the
    # expensive per-version request is only spent where it can pay off.
    wanted: list[tuple[str, int, str]] = []  # (family, version_id, model_name)
    seen_versions: set[int] = set()
    for page in range(1, CIVITAI_PAGES + 1):
        listing = api(CIVITAI_MODELS.format(page=page))
        for model in listing.get("items", []):
            for version in model.get("modelVersions", []):
                family = _civitai_base_family(version.get("baseModel"))
                vid = version.get("id")
                if not family or vid in seen_versions:
                    continue
                if not any(i.get("type") == "video" for i in version.get("images", [])):
                    continue
                seen_versions.add(vid)
                wanted.append((family, int(vid), str(model.get("name") or "")))
        if not listing.get("items"):
            break

    by_family: dict[str, list[tuple[str, int, str]]] = collections.defaultdict(list)
    for entry in wanted:
        by_family[entry[0]].append(entry)
    print(
        f"  версий с видео на видео-базе: {len(wanted)} по семействам "
        f"{ {k: len(v) for k, v in sorted(by_family.items())} }"
    )

    # Round-robin across families so one popular base cannot fill the bank —
    # which is the very defect this source is being added to fix.
    rng = random.Random(SEED)
    order: list[tuple[str, int, str]] = []
    pools = {k: (rng.sample(v, len(v))) for k, v in by_family.items()}
    while any(pools.values()):
        for family in sorted(pools):
            if pools[family]:
                order.append(pools[family].pop())

    made: list[dict] = []
    per_family: dict[str, int] = collections.defaultdict(int)
    for family, version_id, model_name in order:
        if len(made) >= count:
            break
        detail = api(CIVITAI_VERSION.format(version_id=version_id))
        base = str(detail.get("baseModel") or family)
        taken = 0
        for item in detail.get("images", []):
            if len(made) >= count or taken >= CIVITAI_PER_VERSION:
                break
            if item.get("type") != "video":
                continue
            if int(item.get("nsfwLevel") or 0) > C.CIVITAI_MAX_NSFW:
                continue
            url = str(item.get("url") or "")
            if not url:
                continue
            cid = _case_id("cv", f"{version_id}|{url}")
            out = OUT / f"{cid}.mp4"
            if out.is_file():
                report = {"bytes": out.stat().st_size, "remaining": [], "stripped": []}
            else:
                try:
                    data = C._curl(url, timeout=180)
                except OSError:
                    continue
                if len(data) < 10_000:
                    continue
                report = C.strip_video(data, out)
            if report["remaining"]:
                print(f"  ПРОПУЩЕН {cid}: чистка оставила {report['remaining']}")
                continue
            meta = item.get("meta") or {}
            made.append(
                {
                    "case_id": cid,
                    "source": "civitai",
                    "media": "video",
                    "path": f"work/casebank/{cid}.mp4",
                    "commercial_ok": False,
                    "licence": C.SOURCES["civitai"].licence,
                    "truth_grade": "uploader_claim",
                    "truth": {
                        "model": base,
                        "family_hint": family,
                        "model_page": model_name,
                        "version_id": version_id,
                        "prompt": meta.get("prompt"),
                        "meta_keys": sorted(str(k) for k in meta),
                        "label_written_by": "uploader",
                        "source_url": CIVITAI_VERSION.format(version_id=version_id),
                        "rights": "owner_authorisation_2026-08-27",
                    },
                }
            )
            per_family[family] += 1
            taken += 1
            print(f"  {cid}  {base:26} {report['bytes'] / 1e6:.1f} МБ")
    print(f"  собрано по семействам: {dict(sorted(per_family.items()))}")
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
    parser.add_argument("--civitai", type=int, default=16)
    args = parser.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    cases: list[dict] = []
    if args.kling:
        print("== Kling: серверный лог задач вендора")
        cases += build_kling(args.kling)
    if args.civitai:
        print("== Civitai: видео не-Kling, истина = СЛОВО ЗАГРУЗЧИКА, NON-COMMERCIAL")
        cases += build_civitai(args.civitai)
    if args.openfake:
        print("== OpenFake: восемьдесят генераторов, NON-COMMERCIAL")
        cases += build_openfake(args.openfake)

    restricted = [c for c in cases if not c["commercial_ok"]]
    unverified = [c for c in cases if c.get("truth_grade") == C.UNVERIFIED_GRADE]
    TRUTH.write_text(json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nпроверено {len(cases)}\nнарушений 0\nне смогли 0")
    if restricted:
        # The owner's ruling: restricted material is processed and NAMED. It is
        # said here, at the top of the bank, so nothing downstream has to
        # remember to say it.
        # The licences are read off the CASES, not named from a constant. The
        # first version hardcoded OpenFake's and duly printed it over sixteen
        # Civitai clips — a message that contradicts its own evidence (rule E2).
        licences = sorted({c["licence"] for c in restricted})
        print(
            f"\nВНИМАНИЕ: {len(restricted)} из {len(cases)} разборов — NON-COMMERCIAL. "
            "Любой вердикт, посчитанный по ним, обязан нести эту пометку. Лицензии:"
        )
        for licence in licences:
            print(f"  — {licence}")
    if unverified:
        print(
            f"\nВНИМАНИЕ: у {len(unverified)} из {len(cases)} разборов истину написал "
            "ЗАГРУЗЧИК, а не машина. Принято владельцем 2026-08-31 ради негативного "
            "контроля; считается отдельной строкой и пометку несёт дальше."
        )
    if not cases:
        print(f"\n{UNMEASURED}: ни одного разбора не собрано")
        return 2
    print(f"\n{PASS}: {len(cases)} разборов в {OUT}, истина отдельно в {TRUTH.name}")
    return 0 if cases else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
