#!/usr/bin/env python
"""Expert evaluation of `plan_pipeline`: briefs with reference plans, scored automatically.

WHY THIS EXISTS

Seven fix rounds were steered by one-off validators: a human-style grader read
108 plans, wrote verdicts in prose, and the next round patched per finding. The
round-7 validator measured 64/108 expert-correct and said that loop converges
too slowly — every round re-derives what "correct" means. This script freezes
it: `studio/eval/briefs.jsonl` holds each brief, the `spec` a competent caller
would write from the tool description, and an EXPERT REFERENCE (steps, models,
price band, notes, outcome). The plan is run in-process and every dimension is
scored mechanically, so a fix is measured against the whole set, not against
the finding that motivated it.

The rubric is in `studio/eval/README.md`. A brief is EXPERT-CORRECT when every
dimension its reference states passes; a dimension the reference leaves open
(no price band, no model constraint) is not scored.

A second, HOLDOUT file of the same format lives OUTSIDE the repository (pass it
with `--briefs PATH`); fixers never see it, so it measures generalisation and
not memorisation.

    python scripts/eval_plans.py                      # dev set, table + report
    python scripts/eval_plans.py --check              # vs studio/eval/baseline.json
    python scripts/eval_plans.py --write-baseline     # after a deliberate improvement
    python scripts/eval_plans.py --briefs /path/holdout.jsonl --report out.json
    python scripts/eval_plans.py --only w07_drone -v  # one brief, every dimension

No network and no paid call: plan_pipeline only reads the fact base. Side
journals are switched off with STUDIO_NO_JOURNAL=1 before the import.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EVAL_DIR = ROOT / "studio" / "eval"
BRIEFS = EVAL_DIR / "briefs.jsonl"
BASELINE = EVAL_DIR / "baseline.json"

#: Planner step name -> job code used by the references. The planner's own
#: names are Russian operation ids; the references speak job codes so that a
#: renamed operation is one edit here and not two hundred in the data.
STEP_JOB: dict[str, str] = {
    "озвучка": "tts",
    "дубляж": "dub",
    "оживление": "i2v",
    "генерация_видео": "t2v",
    "видео_со_звуком": "t2v_audio",
    "замена_персонажа": "char_replace",
    "звук_фон": "sfx",
    "липсинк": "lipsync",
    "генерация_изображения": "t2i",
    "редактирование_изображения": "image_edit",
    "музыка": "music",
    "апскейл": "upscale_video",
    "апскейл_изображения": "upscale_image",
    "реставрация": "restore",
    "раскраска": "colorize",
    "раскраска_изображения": "colorize",
    "интерполяция_кадров": "interpolate",
    "удаление_фона": "bg_remove_image",
    "удаление_фона_видео": "bg_remove_video",
    "расшифровка": "transcribe",
    "клонирование_голоса": "voice_clone",
    "оборот_360": "turntable",
    "модель_3d": "3d",
    "правка_видео": "v2v_edit",
    "видео_по_референсу": "r2v",
    "говорящий_аватар": "avatar",
}

#: Job codes a reference may name although no planner operation produces them
#: today (the reference says what an expert requires; the planner may lack it).
EXTRA_JOBS = frozenset(
    {"face_swap", "v2a", "captions", "relight", "inpaint_video", "sign_avatar", "3d"}
)
JOBS = frozenset(STEP_JOB.values()) | EXTRA_JOBS

OUTCOMES = frozenset(
    {"plan", "question", "refuse", "gap", "assembly_only", "over_budget", "plan_failed"}
)

DIMENSIONS = ("decomposition", "models", "price", "notes", "outcome")

#: Notes are searched in what the answer SAYS, not in its shape. Measured by a
#: negative control on the first draft (every note regex run over the answers
#: whose reference does not ask for it): searching the serialised JSON let key
#: names satisfy notes — `step_label` read as an AI-Act "label", `vram_gb` as a
#: VRAM remark, `licence_blocked_count` as a licence note, `hosting_jurisdiction:
#: null` as a hosting note — on 131-134 of 150 unrelated answers. So only string
#: VALUES are searched, and not under these keys:
#: * echoes of the caller's own words (a brief that says "RIFE" must not
#:   satisfy its own note);
#: * quoted evidence and per-candidate bookkeeping (a vendor quote about
#:   "30/60 fps figures in blogs" is not the plan talking about 60 fps).
ECHO_KEYS = frozenset({"brief", "understood_as", "full", "omitted", "stated_conditions"})
EVIDENCE_KEYS = frozenset(
    {
        "evidence",
        "failures_outside_brief",
        "price_note",
        "ban_note",
        "out_note",
        "life_note",
        "dur_note",
        "fit_note",
        "registry",
        "anchors",
        "requirement",
        "alternatives",
        "proven_rival",
        "why_not_next",
        "hard_excluded",
        "spec_needed",
    }
)


# --- reading ------------------------------------------------------------------------


def load_briefs(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or "id" not in row:
            raise ValueError(f"{path}:{n}: not a brief row")
        rows.append(row)
    return rows


def validate(rows: list[dict[str, Any]]) -> list[str]:
    """Shape errors in the reference set (the set is data; it is checked like code)."""
    errs: list[str] = []
    seen: set[str] = set()
    for r in rows:
        rid = str(r.get("id"))
        if rid in seen:
            errs.append(f"{rid}: duplicate id")
        seen.add(rid)
        for k in ("class", "brief", "spec", "ref"):
            if k not in r:
                errs.append(f"{rid}: missing {k}")
        ref = r.get("ref") or {}
        outs = ref.get("outcome")
        outs = outs if isinstance(outs, list) else [outs]
        for o in outs:
            if o not in OUTCOMES:
                errs.append(f"{rid}: unknown outcome {o!r}")
        for path in _paths(ref):
            for st in path:
                for j in _alts(st.get("job")):
                    if j not in JOBS:
                        errs.append(f"{rid}: unknown job {j!r}")
        for j in list(ref.get("forbidden") or []) + list(ref.get("optional") or []):
            if j not in JOBS:
                errs.append(f"{rid}: unknown job {j!r} in forbidden/optional")
        band = ref.get("price")
        if band is not None and not (
            isinstance(band, list) and len(band) == 2 and band[0] <= band[1]
        ):
            errs.append(f"{rid}: bad price band {band!r}")
        for note in ref.get("notes") or []:
            for rx in note.get("any") or []:
                try:
                    re.compile(rx)
                except re.error as e:
                    errs.append(f"{rid}: bad note regex {rx!r}: {e}")
    return errs


def _alts(job: object) -> list[str]:
    return [str(j) for j in job] if isinstance(job, list) else [str(job)]


def _paths(ref: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Reference step sequences: `steps` is one path, `paths` lists alternatives."""
    if ref.get("paths"):
        return [list(p) for p in ref["paths"]]
    if "steps" in ref:
        return [list(ref.get("steps") or [])]
    return []


# --- the answer ---------------------------------------------------------------------


#: An outcome VALUE as a machine code. Since round 8 an English answer says
#: `pass`/`fail` where a Russian one says `годно`/`не годно` (`l10n.OUTCOME_EN`);
#: the scorer must not depend on the language of the answer.
OUTCOME_CODE: dict[str, str] = {
    "pass": "pass",
    "годно": "pass",
    "fail": "fail",
    "не годно": "fail",
    "could not measure": "unmeasured",
    "не смогли": "unmeasured",
}


def outcome_code(v: object) -> str:
    """`pass` / `fail` / `unmeasured` for an outcome value in either language."""
    return OUTCOME_CODE.get(str(v or "").strip().lower(), str(v or ""))


def observed_outcome(d: dict[str, Any]) -> str:
    reason = str(d.get("reason") or "")
    pp = d.get("people_policy") or {}
    decision = pp.get("decision") if isinstance(pp, dict) else None
    budget = d.get("budget") or {}
    steps = d.get("steps") or []
    if reason == "запрещённая_тема" or decision == "refuse":
        return "refuse"
    if reason == "работа_не_поддерживается":
        return "gap"
    if reason in ("нужен_ответ_заказчика", "нужна_спецификация") or decision == "question":
        return "question"
    if reason == "дороже_потолка" or (
        isinstance(budget, dict) and outcome_code(budget.get("outcome")) == "fail"
    ):
        return "over_budget"
    if reason == "только_монтаж":
        return "assembly_only"
    if steps and outcome_code(d.get("outcome")) == "fail":
        return "plan_failed"
    if steps:
        return "plan"
    return f"other:{reason or d.get('outcome')}"


def plan_steps(d: dict[str, Any]) -> list[tuple[str, str]]:
    out = []
    for st in d.get("steps") or []:
        name = str(st.get("step") or "")
        model = str((st.get("chosen") or {}).get("model") or "")
        out.append((STEP_JOB.get(name, "?" + name), model))
    return out


def step_shots(d: dict[str, Any]) -> list[int]:
    """Generations per plan step (`shots`; absent = 1), aligned with `plan_steps`."""
    out = []
    for st in d.get("steps") or []:
        n = st.get("shots")
        out.append(int(n) if isinstance(n, (int, float)) and n else 1)
    return out


def clip_price(d: dict[str, Any]) -> float | None:
    pp = d.get("pipeline_price")
    if not isinstance(pp, dict):
        return None
    for key in ("за_ролик", "смета"):
        v = pp.get(key)
        if isinstance(v, dict) and isinstance(v.get("usd"), (int, float)):
            return float(v["usd"])
    return None


def answer_text(d: dict[str, Any]) -> str:
    """The prose of the answer: string values outside echo and evidence keys, lower-cased."""
    out: list[str] = []

    def walk(v: object) -> None:
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            for k, x in v.items():
                if k not in ECHO_KEYS and k not in EVIDENCE_KEYS:
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(d)
    return "\n".join(out).lower()


# --- model constraints (read off the fact base through the registry) ----------------

_REGISTRY: Any = None
_FACTS: Any = None


def _registry() -> Any:
    global _REGISTRY, _FACTS
    if _REGISTRY is None:
        from studio import endpoints as ep
        from studio.selfrag import facts as F

        _FACTS = F.load_facts()
        _REGISTRY = ep.build(_FACTS)
    return _REGISTRY


_RES = re.compile(r"(\d{3,4})\s*p\b|(\d)\s*k\b|\d{3,5}\s*[x:]\s*(\d{3,5})", re.I)


def native_height(model: str) -> int:
    """Largest output height the fact base records for the model (0 = none recorded)."""
    e = _registry().get(model)
    if e is None:
        return 0
    best = 0
    for text in e.resolutions:
        # Prose such as "1080p max, no 4K" must not read as 4K.
        clean = re.sub(
            r"no\s+\d\s*k|not available[^,;]*|4k not available", "", str(text), flags=re.I
        )
        for m in _RES.finditer(clean):
            if m.group(1):
                best = max(best, int(m.group(1)))
            elif m.group(2):
                best = max(best, {2: 1440, 4: 2160, 8: 4320}.get(int(m.group(2)), 0))
            elif m.group(3):
                best = max(best, min(int(m.group(3)), 4320))
    return best


def open_weights(model: str) -> bool:
    e = _registry().get(model)
    return bool(e is not None and (e.self_hostable or "открыт" in str(e.open_weights)))


def recorded_failure(model: str, term: str) -> bool:
    _registry()
    t = term.lower()
    for f in _FACTS or []:
        if f.model.lower() == model.lower() and f.attribute in (
            "failure_mode",
            "degrades_when",
            "limitation",
        ):
            if t in f"{f.value} {f.note}".lower():
                return True
    return False


def model_ok(model: str, rule: dict[str, Any] | None) -> tuple[bool, str]:
    """Does the chosen model satisfy the reference's acceptable set for this step?"""
    if not rule:
        return True, ""
    m = model.lower()
    if not m:
        return False, "no model chosen"
    for rx in rule.get("none") or []:
        if re.fullmatch(rx, m):
            return False, f"{model} is excluded ({rx})"
    if rule.get("any") and not any(re.fullmatch(rx, m) for rx in rule["any"]):
        if not rule.get("or_require"):
            return False, f"{model} not in the acceptable set"
        ok, why = _constraints(model, rule["or_require"])
        if not ok:
            return False, f"{model} not in the acceptable set and {why}"
    if rule.get("require"):
        ok, why = _constraints(model, rule["require"])
        if not ok:
            return False, why
    return True, ""


def _constraints(model: str, req: dict[str, Any]) -> tuple[bool, str]:
    if "native_res_min" in req and native_height(model) < int(req["native_res_min"]):
        return False, f"{model}: native height {native_height(model)} < {req['native_res_min']}"
    if req.get("open_weights") and not open_weights(model):
        return False, f"{model}: open weights not recorded"
    for term in req.get("no_failure_on") or []:
        if recorded_failure(model, term):
            return False, f"{model}: recorded failure on '{term}'"
    return True, ""


# --- scoring ------------------------------------------------------------------------


def _match_path(
    path: list[dict[str, Any]], got: list[tuple[str, str]], ref: dict[str, Any], shots: list[int]
) -> dict[str, Any]:
    """Match one reference path against the plan. Returns per-dimension verdicts."""
    optional = set(ref.get("optional") or [])
    forbidden = set(ref.get("forbidden") or [])
    ordered = ref.get("ordered", True)
    used: set[int] = set()
    pos = 0
    misses: list[str] = []
    overshot: list[str] = []
    model_fails: list[str] = []
    for st in path:
        want = set(_alts(st["job"]))
        hit = None
        rng = range(pos, len(got)) if ordered else range(len(got))
        for i in rng:
            if i not in used and got[i][0] in want:
                hit = i
                break
        if hit is None:
            misses.append("/".join(sorted(want)))
            continue
        used.add(hit)
        if st.get("shots_max") and shots[hit] > int(st["shots_max"]):
            overshot.append(f"{got[hit][0]} x{shots[hit]} (at most {st['shots_max']})")
        if ordered:
            pos = hit + 1
        ok, why = model_ok(got[hit][1], st.get("models"))
        if not ok:
            model_fails.append(f"{got[hit][0]}: {why}")
    extra = [got[i][0] for i in range(len(got)) if i not in used and got[i][0] not in optional]
    bad = [j for j, _ in got if j in forbidden]
    deco_ok = not misses and not overshot and not extra and not bad
    reasons: list[str] = []
    if misses:
        reasons.append("missing " + ", ".join(misses))
    if overshot:
        reasons.append("too many generations: " + ", ".join(overshot))
    if extra:
        reasons.append("extra " + ", ".join(extra))
    if bad:
        reasons.append("forbidden " + ", ".join(bad))
    return {
        "decomposition": (deco_ok, "; ".join(reasons)),
        "models": (
            not model_fails and not misses,
            "; ".join(model_fails) or ("step missing" if misses else ""),
        ),
    }


def score(row: dict[str, Any], d: dict[str, Any]) -> dict[str, Any]:
    ref = row["ref"]
    got = plan_steps(d)
    res: dict[str, tuple[bool, str] | None] = dict.fromkeys(DIMENSIONS)

    want_out = ref["outcome"] if isinstance(ref["outcome"], list) else [ref["outcome"]]
    obs = observed_outcome(d)
    res["outcome"] = (obs in want_out, f"got {obs}, want {'|'.join(want_out)}")

    paths = _paths(ref)
    if paths:
        best: dict[str, Any] | None = None
        for p in paths:
            m = _match_path(p, got, ref, step_shots(d))
            rank = (m["decomposition"][0] + m["models"][0], m["decomposition"][0])
            if best is None or rank > best["_rank"]:
                best = {**m, "_rank": rank}
        assert best is not None
        res["decomposition"] = best["decomposition"]
        if any(st.get("models") for p in paths for st in p):
            res["models"] = best["models"]

    band = ref.get("price")
    if band is not None:
        usd = clip_price(d)
        if usd is None:
            res["price"] = (False, f"no clip price, want [{band[0]}, {band[1]}]")
        else:
            res["price"] = (band[0] <= usd <= band[1], f"{usd} usd, want [{band[0]}, {band[1]}]")

    notes = ref.get("notes") or []
    if notes:
        text = answer_text(d)
        missing = [n["id"] for n in notes if not any(re.search(rx, text, re.I) for rx in n["any"])]
        res["notes"] = (not missing, "missing note " + ", ".join(missing) if missing else "")

    scored = {k: v for k, v in res.items() if v is not None}
    return {
        "id": row["id"],
        "class": row["class"],
        "correct": all(v[0] for v in scored.values()),
        "dims": {k: {"ok": v[0], "why": v[1]} for k, v in scored.items()},
        "observed": {"outcome": obs, "reason": d.get("reason"), "steps": got, "usd": clip_price(d)},
    }


def run(rows: list[dict[str, Any]], verbose: bool = False) -> list[dict[str, Any]]:
    from studio.mcp import server as s

    out = []
    for row in rows:
        t = time.time()
        try:
            d = json.loads(s.plan_pipeline(row["brief"], spec=row["spec"]))
        except Exception as e:  # a crash is a wrong answer, not a broken scorer
            d = {"outcome": "crash", "reason": repr(e)[:200]}
        r = score(row, d)
        r["seconds"] = round(time.time() - t, 2)
        out.append(r)
        if verbose:
            mark = "OK " if r["correct"] else "BAD"
            print(f"{mark} {row['id']:28} {r['observed']['outcome']:13} {r['observed']['steps']}")
            for k, v in r["dims"].items():
                if not v["ok"]:
                    print(f"      {k}: {v['why']}")
    return out


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    per: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "correct": 0})
    dims: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "ok": 0})
    for r in results:
        per[r["class"]]["n"] += 1
        per[r["class"]]["correct"] += int(r["correct"])
        for k, v in r["dims"].items():
            dims[k]["n"] += 1
            dims[k]["ok"] += int(v["ok"])
    n = len(results)
    c = sum(int(r["correct"]) for r in results)
    return {
        "total": {"n": n, "correct": c, "pct": round(100.0 * c / n, 1) if n else 0.0},
        "classes": {
            k: {**v, "pct": round(100.0 * v["correct"] / v["n"], 1)} for k, v in sorted(per.items())
        },
        "dimensions": {
            k: {**v, "pct": round(100.0 * v["ok"] / v["n"], 1)} for k, v in sorted(dims.items())
        },
    }


def print_table(summary: dict[str, Any], title: str) -> None:
    print(f"\n{title}")
    print(f"{'class':22} {'n':>4} {'correct':>8} {'%':>6}")
    for k, v in summary["classes"].items():
        print(f"{k:22} {v['n']:>4} {v['correct']:>8} {v['pct']:>6}")
    t = summary["total"]
    print(f"{'TOTAL':22} {t['n']:>4} {t['correct']:>8} {t['pct']:>6}")
    print(
        "dimension pass rate: "
        + ", ".join(f"{k} {v['pct']}%" for k, v in summary["dimensions"].items())
    )


def check(summary: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Regressions against the committed baseline: any class down, or the total down."""
    bad = []
    for k, b in baseline.get("classes", {}).items():
        now = summary["classes"].get(k)
        if now is None:
            bad.append(f"class {k} vanished from the set")
        elif now["correct"] < b["correct"]:
            bad.append(f"class {k}: {now['correct']}/{now['n']} < baseline {b['correct']}/{b['n']}")
    if summary["total"]["correct"] < baseline["total"]["correct"]:
        bad.append(f"total {summary['total']['correct']} < baseline {baseline['total']['correct']}")
    return bad


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--briefs", type=Path, default=BRIEFS)
    ap.add_argument(
        "--report", type=Path, default=Path(tempfile.gettempdir()) / "eval_plans_report.json"
    )
    ap.add_argument(
        "--check", action="store_true", help="fail on a regression against the baseline"
    )
    ap.add_argument("--baseline", type=Path, default=BASELINE)
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    rows = load_briefs(a.briefs)
    errs = validate(rows)
    if errs:
        print("FAIL: the reference set is malformed:\n  " + "\n  ".join(errs[:40]))
        return 1
    if a.only:
        rows = [r for r in rows if r["id"] in a.only]
    t = time.time()
    results = run(rows, verbose=a.verbose)
    summary = summarise(results)
    print_table(summary, f"{a.briefs.name}: {len(rows)} briefs, {time.time() - t:.0f} s")
    report = {"briefs": str(a.briefs), "summary": summary, "results": results}
    a.report.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"report: {a.report}")

    if a.write_baseline:
        base = {"briefs": a.briefs.name, "total": summary["total"], "classes": summary["classes"]}
        a.baseline.write_text(
            json.dumps(base, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(f"baseline written: {a.baseline}")
    if a.check:
        if not a.baseline.is_file():
            print(f"FAIL: no baseline at {a.baseline}")
            return 1
        bad = check(summary, json.loads(a.baseline.read_text(encoding="utf-8")))
        if bad:
            print("FAIL: expert-correct regressed:\n  " + "\n  ".join(bad))
            return 1
        print("ok: no class regressed, total not below baseline")
    return 0


if __name__ == "__main__":
    sys.exit(main())
