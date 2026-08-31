"""Measure the identity axis whose anchor is the client's raw photo and nothing else."""

from __future__ import annotations

import json
from pathlib import Path

from .identity_arcface import HARD_DRIFT_MAX, SAME_PERSON_MAX

#: CHOSEN: the instrument is a parameter, not a wired-in dependency. Swapping
#: it voids every number taken before it, so the swap has to be a visible
#: decision by the caller and not the side effect of editing an import.
DEFAULT_INSTRUMENT = "identity_arcface"

INSTRUMENT_LICENCE = {
    "identity_arcface": (
        "buffalo_l / InsightFace — non-commercial. "
        "Noted for shipping; does not block work. "
        "Replacement cost: recalibration of all thresholds."
    ),
}

#: CHOSEN: three outcomes instead of two, because "could not measure" folds
#: into neither of the other two. Words rather than flags — they are printed
#: into reports — and the whole package imports them from here, so the three
#: cannot drift into two spellings of the same verdict.
PASS, FAIL, UNMEASURED = "pass", "fail", "could not measure"

from .identity_arcface import MIN_COVERAGE  # noqa: E402

FOREIGN_FACE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "foreign_face.png"

#: CHOSEN 0.05 (by stream A, out of the instrument's own spread rather than a
#: paired run): the same person across a change of scale sat at 0.208..0.374 on
#: the live calibration set, so this bar is well inside the instrument's noise
#: and an order away from the distance to a stranger (0.6809, the negative
#: control row below). It decides the only branch of `upscale_drift_verdict`,
#: and the sign of the excess names two different illnesses: past -0.05 the
#: frames sit CLOSER to the reference than to the raw photo, meaning the
#: upscaler repainted the face and `d_ref` has stopped being a comparison with
#: the client at all; past +0.05 the upscaler spoiled the face. NOT MEASURED:
#: no paired before/after upscaler run exists in this tree.
UPSCALE_DRIFT_MAX = 0.05

#: CHOSEN 0.05 (by stream A, out of the same instrument-noise order as
#: `UPSCALE_DRIFT_MAX`; likewise not from a run of the restorer). It is not the
#: main sign that the axis is dead — that is a foreign frame landing inside
#: `SAME_PERSON_MAX`, and `restore_negative_control` tests for it first. This
#: bar catches the earlier, not yet fatal stage: the restorer mixing the
#: reference into a KNOWN STRANGER without carrying it over the bar, which
#: inflates every `d_raw` taken after the restore. Crossing it turns the
#: control's outcome into FAIL, and a failed control invalidates the run's
#: identity numbers instead of merely warning about them. NOT MEASURED: the
#: restorer has never been run on a foreign face, which needs a GPU.
RESTORE_PULL_MAX = 0.05

# Measuring devices, exercised by the tests and never by the paid path.
#
# `restore_negative_control` is the control the identity axis cannot do
# without: every generator in this pipeline is handed the client photo, so
# every one of them has a trivial way to make `d_raw` look perfect — paint the
# reference face over whatever it produced. A "before → after" pair on the
# CLIENT's own frames reads the same whether the generator did the work or
# copied the answer. Only an input where the generator must FAIL separates
# them: push a known stranger through it and demand the instrument still say
# "different person".
#
# `acceptance_report` is what refuses to call the axis accepted. Of the three
# calibration rows behind the bar this module ships, one reproduces; it totals
# them as "1 of 3" instead of an aggregate flag, and the main row — against the
# client's raw photo — has never been measured at all.

INSTRUMENTS = ("restore_negative_control", "acceptance_report")

ACCEPTANCE_ROWS: dict[str, dict] = {
    "against the raw photo": {
        "target": {"median": 0.5067, "inside": 0, "judged": 21},
        "reproduced": None,
        "outcome": UNMEASURED,
        "why": (
            "the raw photo is NOT in the tree. The manifest of the "
            "calibration set says outright that the anchor "
            "`img/real_0000.png` is the MEDOID of the generated frames, and "
            "the uploaded photo was excluded by the template author "
            "deliberately. There is nothing to measure against; 0.5067 was "
            "recorded back when the photo existed. This is the MAIN "
            "acceptance row, and it is NOT CLOSED."
        ),
    },
    "against the medoid": {
        "target": {"median": 0.2579, "inside": 19, "judged": 21},
        "reproduced": {"median": 0.2579, "inside": 19, "judged": 21},
        "outcome": PASS,
        "why": (
            "reproduced exactly, to the fourth decimal, by the command "
            "`python3 -m unittest lipsync.tests.test_fork_identity`. "
            "It proves the INSTRUMENT is the same. It says nothing about "
            "the product: this is generated against generated."
        ),
    },
    "negative control": {
        "target": {"band": (0.96, 1.05), "inside": 0},
        "reproduced": {"median": 0.6809, "min": 0.5478, "max": 0.7454, "inside": 0, "judged": 21},
        "outcome": UNMEASURED,
        "why": (
            "the direction is right — 0 of 21 inside the bar, the median "
            "0.6809 is above HARD_DRIFT_MAX 0.6, the instrument says "
            '"a different person". But the 0.96–1.05 band was recorded '
            "against a photo that is not in the tree, and 0.6809 is the "
            "farthest the INSTRUMENT found among what exists (66 frames "
            "examined). Passing 0.68 off as 0.96–1.05 is not allowed."
        ),
    },
}


class DerivedAnchor(ValueError):
    """Signal that the anchor is a frame from the judged set — the medoid defect itself."""


def _samples(manifest_path: str | Path) -> list:
    """Return the paths of every frame in the set, relative to the manifest directory."""
    p = Path(manifest_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    root = p.parent
    return [(root / s["path"]).resolve() for s in data.get("samples", [])]


def refuse_derived_anchor(
    anchor: str | Path, frames, *, manifest: str | Path | None = None
) -> None:
    """Fail the run if the anchor comes from what is being judged. The medoid is that case."""
    a = Path(anchor).resolve()
    if a in {Path(f).resolve() for f in frames}:
        raise DerivedAnchor(
            f"the anchor is a frame from the judged set: {a.name}. This compares "
            f"generated with generated — exactly the defect that once made "
            f"0.2579 read as a success while the true anchor gave 0.5067."
        )
    if manifest is None:
        return
    if a in _samples(manifest):
        raise DerivedAnchor(
            f"the anchor {a.name} is listed in the set {Path(manifest).name} among "
            f"samples: by provenance it is derived, even if it did not make "
            f"the judged list. Only the UPLOADED photo can be the "
            f"anchor."
        )
    text = Path(manifest).read_text(encoding="utf-8")
    if "MEDOID" in text and a.name in text:
        raise DerivedAnchor(f"the manifest {Path(manifest).name} itself calls {a.name} a medoid.")


def _instrument(name: str):
    """Return the instrument by name. Known ones only — a typo must not yield a stub."""
    if name != DEFAULT_INSTRUMENT:
        raise ValueError(
            f"unknown identity instrument: {name!r}. Known: "
            f"{DEFAULT_INSTRUMENT!r}. Changing the instrument voids every recorded "
            f"number and is done as a decision, not as a typo."
        )
    from . import identity_arcface

    return identity_arcface


def distances(
    frames,
    anchor: str | Path,
    *,
    instrument: str = DEFAULT_INSTRUMENT,
    min_face_px: int | None = None,
) -> dict:
    """Return the distance from every frame to the anchor. Three outcomes per frame, not two."""
    mod = _instrument(instrument)
    a = mod.face_detail(anchor)
    empty: dict = {
        "per_frame": {},
        "face_px": {},
        "no_face": [],
        "too_small": [],
        "median": None,
        "min": None,
        "max": None,
        "inside": 0,
        "judged": 0,
        "total": 0,
        "coverage": 0.0,
        "outcome": UNMEASURED,
        "bar": SAME_PERSON_MAX,
        "min_face_px": min_face_px,
    }
    if a is None:
        return {
            **empty,
            "note": f"no face on the anchor {Path(anchor).name}: nothing to measure from",
        }

    per_frame, face_px, no_face, too_small = {}, {}, [], []
    total = 0
    for p in frames:
        total += 1
        name = Path(p).name
        d = mod.face_detail(p)
        if d is None:
            no_face.append(name)
            continue
        face_px[name] = d["face_px"]
        if min_face_px is not None and d["face_px"] < min_face_px:
            too_small.append(name)
            continue
        per_frame[name] = mod.cosine_distance(a["embedding"], d["embedding"])

    if not per_frame:
        return {
            **empty,
            "total": total,
            "face_px": face_px,
            "no_face": no_face,
            "too_small": too_small,
            "note": (
                f"nothing to judge: of {total} frames, {len(no_face)} have no "
                f"face and {len(too_small)} have a face smaller than "
                f'{min_face_px}px. This is NOT "a different person".'
            ),
        }

    vals = sorted(per_frame.values())
    inside = sum(1 for v in vals if v <= SAME_PERSON_MAX)
    coverage = round(len(vals) / total, 3)
    return {
        "per_frame": per_frame,
        "face_px": face_px,
        "no_face": no_face,
        "too_small": too_small,
        "median": round(mod._quantile(vals, 0.5), 4),
        "min": round(vals[0], 4),
        "max": round(vals[-1], 4),
        "inside": inside,
        "judged": len(vals),
        "total": total,
        "coverage": coverage,
        "bar": SAME_PERSON_MAX,
        "min_face_px": min_face_px,
        "outcome": UNMEASURED
        if coverage < MIN_COVERAGE
        else (PASS if inside * 2 > len(vals) else FAIL),
        "note": (
            f"{instrument}: median "
            f"{round(mod._quantile(vals, 0.5), 4)}, "
            f"inside the bar {SAME_PERSON_MAX}: {inside} of {len(vals)} judged "
            f"(total {total}; face-size filter: "
            f"{'off' if min_face_px is None else str(min_face_px) + 'px'})"
        ),
    }


def axis(
    frames,
    *,
    raw_photo: str | Path,
    upscaled_reference: str | Path | None = None,
    foreign: str | Path | None = None,
    driving_actor: str | Path | None = None,
    manifest: str | Path | None = None,
    instrument: str = DEFAULT_INSTRUMENT,
    min_face_px: int | None = None,
) -> dict:
    """Return four numbers at once, with the verdict against the RAW PHOTO and nothing else."""
    refuse_derived_anchor(raw_photo, frames, manifest=manifest)
    if upscaled_reference is not None:
        refuse_derived_anchor(upscaled_reference, frames, manifest=manifest)

    out: dict = {
        "instrument": instrument,
        "licence": INSTRUMENT_LICENCE.get(instrument, "licence not checked"),
        "bar": SAME_PERSON_MAX,
        "hard_bar": HARD_DRIFT_MAX,
        "d_raw": distances(frames, raw_photo, instrument=instrument, min_face_px=min_face_px),
        "d_ref": None,
        "d_neg": None,
        "d_drv": None,
        "control": "NOT RUN",
        "leak_to_actor": "NOT CHECKED",
        "upscale": "NOT CHECKED",
    }
    if upscaled_reference is not None:
        out["d_ref"] = distances(
            frames, upscaled_reference, instrument=instrument, min_face_px=min_face_px
        )
        out["upscale"] = upscale_drift_verdict(out["d_raw"], out["d_ref"])
    if foreign is not None:
        out["d_neg"] = distances(frames, foreign, instrument=instrument, min_face_px=min_face_px)
        out["control"] = control_verdict(out["d_neg"])
    if driving_actor is not None:
        out["d_drv"] = distances(
            frames, driving_actor, instrument=instrument, min_face_px=min_face_px
        )
        out["leak_to_actor"] = actor_leak_verdict(out["d_raw"], out["d_drv"])

    out["verdict"] = out["d_raw"]["outcome"]
    out["note"] = _note(out)
    return out


def control_verdict(d_neg: dict) -> str:
    """Say whether the negative control fired. Three outcomes here too."""
    if d_neg.get("median") is None:
        return f"{UNMEASURED}: the control yielded no judgeable frame"
    if d_neg["inside"] > 0:
        return (
            f"{FAIL}: the instrument took a stranger for the subject on "
            f"{d_neg['inside']} frame(s) — the run's numbers are invalid"
        )
    if d_neg["median"] < HARD_DRIFT_MAX:
        return (
            f"{UNMEASURED}: the stranger sits at {d_neg['median']}, below "
            f"{HARD_DRIFT_MAX} — the control is weak and does not show the "
            f'"definitely a stranger" band'
        )
    return f"{PASS}: the stranger is at {d_neg['median']}, not a single frame inside the bar"


def upscale_drift_verdict(d_raw: dict, d_ref: dict, *, drift_max: float = UPSCALE_DRIFT_MAX) -> str:
    """Say what the face upscale did. Not an identity verdict and never will be."""
    a, b = d_raw.get("median"), d_ref.get("median")
    if a is None or b is None:
        return (
            f"{UNMEASURED}: one of the two medians is missing (to the raw photo {a}, "
            f'to the reference {b}). This is NOT "the upscale is harmless".'
        )
    drift = round(b - a, 4)
    if drift < -drift_max:
        return (
            f"{FAIL}: to the reference {b} against {a} to the raw photo — "
            f"the frames are closer to the reference by {abs(drift)} against the "
            f"threshold {drift_max}. The upscaler repainted the face: the reference "
            f"is no longer the client, and d_ref is no longer a comparison with them."
        )
    if drift > drift_max:
        return (
            f"{FAIL}: to the reference {b} against {a} to the raw photo — "
            f"the reference is farther by {drift} against the threshold {drift_max}. "
            f"The upscaler spoiled the face."
        )
    return (
        f"{PASS}: to the raw photo {a}, to the reference after the upscale {b}, "
        f"the divergence {drift} is within {drift_max} — the upscale did not "
        f"move identity"
    )


def actor_leak_verdict(d_raw: dict, d_drv: dict) -> str:
    """Say whether the output drifted toward the DRIVING ACTOR instead of the client."""
    if d_raw.get("median") is None or d_drv.get("median") is None:
        return (
            f"{UNMEASURED}: one of the two distances is missing "
            f"(to the client {d_raw.get('median')}, "
            f"to the actor {d_drv.get('median')})"
        )
    if d_drv["median"] < d_raw["median"]:
        return (
            f"{FAIL}: the distance to the driving actor {d_drv['median']} is CLOSER "
            f"than to the client {d_raw['median']} — the face leaked from the driving"
        )
    return (
        f"{PASS}: to the client {d_raw['median']}, to the actor "
        f"{d_drv['median']} — the actor is farther, no leak visible"
    )


def restore_negative_control(
    restored_foreign_frames=None,
    *,
    raw_photo: str | Path,
    foreign_frames_before=None,
    instrument: str = DEFAULT_INSTRUMENT,
    min_face_px: int | None = None,
    pull_max: float = RESTORE_PULL_MAX,
) -> dict:
    """Run the negative control: push a known stranger through the generator, expect a refusal."""
    common: dict = {"instrument": instrument, "min_face_px": min_face_px}
    out: dict = {
        "bar": SAME_PERSON_MAX,
        "pull_max": pull_max,
        "before": None,
        "after": None,
        "pull": None,
    }
    if restored_foreign_frames is None:
        return {
            **out,
            "outcome": UNMEASURED,
            "note": (
                "UNVERIFIED: the restorer has not been run on a foreign face "
                "(a GPU is needed). Until that run exists, d_raw AFTER the "
                "restore is not separated from the restorer's quality — this is "
                '"could not measure", NOT "the restorer is honest".'
            ),
        }

    after = distances(restored_foreign_frames, raw_photo, **common)
    out["after"] = after
    if after["median"] is None:
        return {
            **out,
            "outcome": UNMEASURED,
            "note": (
                f"the restore control yielded no judgeable frame: "
                f'{after["note"]}. This is NOT "the restorer is honest".'
            ),
        }

    if after["inside"] > 0:
        return {
            **out,
            "outcome": FAIL,
            "note": (
                f"THE RESTORER PRINTS THE REFERENCE: the foreign face after the "
                f"restore landed inside the bar {SAME_PERSON_MAX} to the client on "
                f"{after['inside']} frame(s) of {after['judged']}, "
                f"median {after['median']}. So d_raw after the "
                f"restore measures the restorer, not the generator under test, and all "
                f"axis numbers after the restore are INVALID."
            ),
        }

    if foreign_frames_before is None:
        return {
            **out,
            "outcome": PASS,
            "note": (
                f"the foreign face after the restore sits at "
                f"{after['median']}, not a single frame inside the bar "
                f"{SAME_PERSON_MAX} — the restorer does not print the reference. "
                f"THE PULL WAS NOT MEASURED: no before-restore frames were supplied, "
                f"so an early stage of the same illness would stay invisible."
            ),
        }

    before = distances(foreign_frames_before, raw_photo, **common)
    out["before"] = before
    if before["median"] is None:
        return {
            **out,
            "outcome": UNMEASURED,
            "note": (
                f"the foreign face BEFORE the restore cannot be judged "
                f"({before['note']}), and without that number the pull cannot "
                f"be computed: {after['median']} has nothing to compare with."
            ),
        }

    pull = round(before["median"] - after["median"], 4)
    out["pull"] = pull
    if pull > pull_max:
        return {
            **out,
            "outcome": FAIL,
            "note": (
                f"the restorer PULLED the foreign face toward the client by {pull} "
                f"({before['median']} → {after['median']}) against the threshold "
                f"{pull_max}. The stranger did not land inside the bar {SAME_PERSON_MAX}, "
                f"but the direction is the same: the restorer mixes in the "
                f"reference, and d_raw after it is inflated."
            ),
        }
    return {
        **out,
        "outcome": PASS,
        "note": (
            f"the foreign face {before['median']} → {after['median']}, "
            f"the pull {pull} does not exceed {pull_max}, zero frames of "
            f"{after['judged']} inside the bar {SAME_PERSON_MAX} — "
            f"the restorer does not print the reference, and d_raw after the "
            f"restore measures the generator under test"
        ),
    }


def acceptance_report() -> dict:
    """Report how many calibration rows are ACTUALLY reproduced. In numbers, not a flag."""
    rows = ACCEPTANCE_ROWS
    done = [n for n, r in rows.items() if r["outcome"] == PASS]
    unmeasured = [n for n, r in rows.items() if r["outcome"] == UNMEASURED]
    failed = [n for n, r in rows.items() if r["outcome"] == FAIL]
    outcome = PASS if len(done) == len(rows) else (FAIL if failed else UNMEASURED)
    return {
        "outcome": outcome,
        "reproduced": len(done),
        "of": len(rows),
        "unmeasured": unmeasured,
        "failed": failed,
        "rows": rows,
        "note": (
            f"identity acceptance: reproduced {len(done)} row(s) of "
            f"{len(rows)}, unmeasured {len(unmeasured)}, failed "
            f"{len(failed)}. Reproduced: {', '.join(done) or '—'}. "
            f"UNMEASURED: {', '.join(unmeasured) or '—'}. "
            + (
                "All three rows are required, and all three are reproduced: the identity acceptance is CLOSED."
                if outcome == PASS
                else f"All three rows are required, so the identity acceptance is NOT "
                f'CLOSED — and "{len(done)} of {len(rows)}" here is not "almost" '
                f'but "the main row was never measured".'
            )
        ),
    }


def _note(out: dict) -> str:
    """Build the report in numbers: checked N, inside the bar M, unmeasured K."""
    raw = out["d_raw"]
    head = (
        f"VERDICT AGAINST THE RAW PHOTO: {raw['outcome']}. "
        f"median {raw['median']}, inside the bar {raw['inside']} of "
        f"{raw['judged']} judged, unmeasured "
        f"{len(raw['no_face']) + len(raw['too_small'])} of {raw['total']}."
    )
    if out["d_ref"] is not None:
        ref = out["d_ref"]
        head += (
            f" FOR REFERENCE, NOT THE VERDICT — to the reference (the raw photo "
            f"AFTER THE FACE UPSCALE, no generated link in between): median "
            f"{ref['median']}, inside the bar {ref['inside']} of {ref['judged']}."
            f" WHAT THE UPSCALE DID: {out['upscale']}."
        )
    if out.get("d_drv") is not None:
        head += f" LEAK TO THE DRIVING ACTOR: {out['leak_to_actor']}."
    head += f" CONTROL: {out['control']}."
    head += f" INSTRUMENT LICENCE: {out['licence']}"
    return head
