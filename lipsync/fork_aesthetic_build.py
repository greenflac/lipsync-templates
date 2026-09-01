"""Build a draft aesthetic: an operator's prompt plus a driving become one draft.

The owner's contract of 2026-09-01 makes an aesthetic a unit of the product —
a prompt, a driving, a demo frame and a trial clip that were all proven
together — and this module is the command that assembles one. It produces a
DRAFT and nothing else: the step into the product base is a separate command,
because the owner looks at the demo frame with his own eyes first.

Seven stages, cheapest first, and the one paid call last. Every stage answers
with three outcomes and its numbers, and every route out of the process is a
parameter, so the whole command runs in tests without a network.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from .frame import FRAME
from .fork_identity import FAIL, PASS, UNMEASURED
from . import fork_aesthetic, fork_e2e, fork_intake, fork_plan, fork_video, pollinations

#: Where the demo identities and the aesthetics base sit, resolved from this
#: file rather than from the working directory: an operator runs the command
#: from wherever he happens to stand, and `assets/...` in the contract is a
#: repository path, not a relative one.
PACKAGE_ROOT = Path(__file__).resolve().parent.parent

BUILD_STAGES = (
    "1 driving intake",
    "2 prompt cleanup",
    "3 demo stylisation",
    "4 demo frame acceptance",
    "5 aesthetic card",
    "6 trial paid clip",
    "7 draft on disk",
)

#: The draft's file names, fixed so the publishing command can find them
#: without being told. Names, not paths: the draft directory is the operator's.
DRAFT_NAMES = {
    "aesthetic": "aesthetic.json",
    "demo": "demo.png",
    "driving": "driving.mp4",
    "trial": "trial.mp4",
    "report": "report.json",
}

#: CHOSEN 0.5 by this module, out of what the cut is FOR rather than out of a
#: distribution: the anthropometry cut removes the person and keeps the scene,
#: so a prompt that loses more than half its words to it was mostly a
#: description of a person and what is left cannot carry an environment, a
#: style and a composition. It is a judgement and may be moved; it is written
#: down as a judgement so the next reader does not mistake it for a measurement.
PROMPT_CUT_SHARE_MAX = 0.5

#: The kind every aesthetic built by this command carries. One value today, and
#: written once so the draft and the schema cannot disagree about it.
DRAFT_KIND = "transform"

#: Where the publishing command will put the two files this draft carries. The
#: draft records the paths it will occupy so `aesthetic.json` is already the
#: contract's element and nothing has to rewrite it later.
PUBLISHED_DRIVING_DIR = "assets/drivings"
PUBLISHED_TRIAL_DIR = "docs/trials"

# The stage folding lives in `fork_e2e` and is reached by name from here on
# purpose. A second copy of "count the checks and pick one of three outcomes"
# is a second place for that rule to drift, and an operator who reads both
# commands has to read one report format.
_result = fork_e2e._result


def _checks_of(reply) -> list:
    """Return a neighbour stage's checks as `(name, outcome, note)` triples."""
    out = []
    for check in (reply or {}).get("checks") or []:
        out.append((str(check.get("name")), str(check.get("outcome")), str(check.get("note"))))
    return out


def demo_path(gender: str) -> Path:
    """Return the absolute path of the demo identity for a declared gender.

    :param gender: `m` or `f`; an unknown value raises rather than defaulting.
    :returns: the file inside the repository.

    >>> demo_path("f").name
    'fork_plan_woman_fullbody.png'
    """
    return PACKAGE_ROOT / fork_aesthetic.demo_for(gender)


def other_demo_path(gender: str) -> Path:
    """Return the demo identity of the gender this build is NOT making.

    It is the reference the leak check measures against: with one demo in the
    frame and no client yet, "did somebody else get drawn" can only be asked
    about the other demo, and that is the swap the owner has actually seen.
    """
    key = str(gender).strip().lower()
    fork_aesthetic.demo_for(key)
    others = [g for g in fork_aesthetic.GENDERS if g != key]
    return PACKAGE_ROOT / fork_aesthetic.demo_for(others[0])


def stage_driving(*, driving, frames=None, product_seconds=None, intake=None) -> dict:
    """Stage 1: the driving is on disk and the six-axis intake accepted it."""
    checks = [fork_e2e.file_fact(driving, "driving")]
    paths = [str(f) for f in (frames or [])]
    numbers: dict = {"frames_given": len(paths)}
    if checks[0][1] != PASS:
        return _result(
            BUILD_STAGES[0], checks, numbers=numbers, note="no driving on disk: nothing to accept"
        )
    intake = fork_intake.driving_intake if intake is None else intake
    try:
        reply = intake(str(driving), paths, product_seconds=product_seconds)
    except Exception as exc:  # noqa: BLE001 - a crashed instrument is "not measured"
        checks.append(("driving intake", UNMEASURED, f"{type(exc).__name__}: {exc}"))
        return _result(BUILD_STAGES[0], checks, numbers=numbers)
    outcome, note = fork_e2e.outcome_of(reply, what="driving_intake")
    if isinstance(reply, dict):
        numbers["fps"] = reply.get("fps")
        numbers["seconds"] = reply.get("seconds")
        numbers["axes"] = {k: v.get("outcome") for k, v in (reply.get("axes") or {}).items()}
    checks.append(("driving intake", outcome, fork_e2e._numbers_of(reply) + note))
    return _result(BUILD_STAGES[0], checks, numbers=numbers)


def stage_prompt(*, prompt, aesthetic_id: str, composer=None) -> dict:
    """Stage 2: cut the anthropometry, then add the identity clause and the lettering ban."""
    text = prompt if isinstance(prompt, str) else ""
    checks: list = [
        (
            "operator prompt",
            PASS if text.strip() else FAIL,
            f"{len(text.split())} words given" if text.strip() else "the prompt is empty",
        )
    ]
    numbers: dict = {"words_in": len(text.split())}
    if not text.strip():
        return _result(BUILD_STAGES[1], checks, numbers=numbers)

    composer = fork_aesthetic.compose if composer is None else composer
    reply = composer({"id": aesthetic_id, "kind": DRAFT_KIND, "prompt": text})
    outcome, note = fork_e2e.outcome_of(reply, what="fork_aesthetic.compose")
    checks.append(("anthropometry cut", outcome, note))
    built = (reply or {}).get("prompt") if isinstance(reply, dict) else None
    if not built:
        return _result(BUILD_STAGES[1], checks, numbers=numbers)
    numbers["words_out"] = len(str(built).split())

    cut = (reply.get("cut") or {}) if isinstance(reply, dict) else {}
    share = cut.get("cut_share")
    numbers["cut_share"] = share
    if share is None:
        checks.append(
            (
                "prompt survived the cut",
                UNMEASURED,
                "the cut reported no share: how much was removed is not known",
            )
        )
    else:
        checks.append(
            (
                "prompt survived the cut",
                PASS if float(share) <= PROMPT_CUT_SHARE_MAX else FAIL,
                f"the cut removed {share} of the words against the ceiling "
                f"{PROMPT_CUT_SHARE_MAX}: past it the prompt was a person, not a scene",
            )
        )

    ban = fork_aesthetic.no_brands_clause()
    checks.append(
        (
            "lettering ban",
            PASS if ban in str(built) else FAIL,
            "the ban is in the assembled prompt"
            if ban in str(built)
            else "the assembled prompt carries no lettering ban",
        )
    )
    clause = fork_aesthetic.IDENTITY_CLAUSE
    checks.append(
        (
            "identity clause",
            PASS if clause in str(built) else FAIL,
            "the identity clause is in the assembled prompt"
            if clause in str(built)
            else "the assembled prompt carries no identity clause",
        )
    )
    return _result(BUILD_STAGES[1], checks, numbers=numbers, prompt=str(built))


def stylize_demo(*, prompt: str, demo, out_path, model=None, size=FRAME) -> str:
    """Redraw the demo identity from ONE reference. The owner's decision 2: not `compose`.

    :param prompt: the assembled prompt from stage 2.
    :param demo: the demo identity picture.
    :param out_path: where the styled demo is written.
    :returns: the written path.
    """
    width, height = size
    return pollinations.images_edit(
        prompt,
        str(demo),
        str(out_path),
        model=fork_e2e.STYLE_MODEL if model is None else model,
        width=int(width),
        height=int(height),
    )


def stage_stylize(*, prompt, gender, out_path, stylize=None, sizer=None) -> dict:
    """Stage 3: one image through img2img, at the delivery frame and no other size."""
    checks: list = []
    numbers: dict = {"asked": list(FRAME), "model": fork_e2e.STYLE_MODEL}
    try:
        source = demo_path(gender)
    except KeyError as exc:
        checks.append(("declared gender", FAIL, str(exc)))
        return _result(BUILD_STAGES[2], checks, numbers=numbers)
    checks.append(("declared gender", PASS, f"gender {gender}, demo {source.name}"))
    checks.append(fork_e2e.file_fact(source, "demo identity"))
    if checks[-1][1] != PASS:
        return _result(BUILD_STAGES[2], checks, numbers=numbers)

    stylize = stylize_demo if stylize is None else stylize
    t0 = time.perf_counter()
    try:
        made = stylize(prompt=str(prompt), demo=str(source), out_path=str(out_path))
    except Exception as exc:  # noqa: BLE001 - a route that refused is "not measured"
        checks.append(("img2img call", UNMEASURED, f"{type(exc).__name__}: {exc}"))
        return _result(BUILD_STAGES[2], checks, numbers=numbers)
    made = str(made or out_path)
    numbers["seconds"] = round(time.perf_counter() - t0, 3)
    checks.append(("img2img call", PASS, f"{numbers['seconds']} s, one reference image"))
    checks.append(fork_e2e.file_fact(made, "styled demo"))
    if checks[-1][1] != PASS:
        return _result(BUILD_STAGES[2], checks, numbers=numbers)

    got, note = fork_e2e.frame_size(made, sizer=sizer)
    numbers["got"] = list(got) if got else None
    kept = fork_e2e.styliser_kept_the_plan(asked=FRAME, got=got)
    checks.append(("the route kept the ordered size", kept["outcome"], f"{note}; {kept['note']}"))
    return _result(BUILD_STAGES[2], checks, numbers=numbers, styled=made)


def stage_demo_acceptance(*, made, gender, distances=None, sizer=None) -> dict:
    """Stage 4: the demo identity survived, the other demo did not leak, the canvas is 9:16."""
    checks: list = []
    numbers: dict = {}
    try:
        mine, other = demo_path(gender), other_demo_path(gender)
    except KeyError as exc:
        checks.append(("declared gender", FAIL, str(exc)))
        return _result(BUILD_STAGES[3], checks, numbers=numbers)

    kept = fork_aesthetic.accept(made=made, demo=mine, distances=distances)
    numbers["identity_median"] = kept.get("median")
    checks.append(("demo identity survived", kept["outcome"], str(kept.get("note"))))

    leak = fork_aesthetic.leak_verdict(made=made, client=mine, demo=other, distances=distances)
    numbers["leak_gap"] = leak.get("gap")
    checks.append(
        (
            "the other demo did not leak",
            leak["outcome"],
            f"measured against {other.name}; {leak.get('note')}",
        )
    )

    got, note = fork_e2e.frame_size(made, sizer=sizer)
    numbers["size"] = list(got) if got else None
    axis = fork_plan.ratio_axis(*(got or (None, None)))
    checks.append(("9:16 canvas", axis["outcome"], f"{note}; {axis['note']}"))
    return _result(BUILD_STAGES[3], checks, numbers=numbers)


def card_for_draft(card) -> dict | None:
    """Return the contract's `card` element, or None when the card was never measured.

    The tolerances travel with the medians because a band without its width is
    not a band; `fork_plan` names them `tol_*` and the schema nests them, and
    this is the one place the two shapes meet.
    """
    if not isinstance(card, dict) or card.get("outcome") != PASS:
        return None
    axes = fork_plan.PERSON_AXES
    if any(card.get(a) is None for a in axes):
        return None
    out = {a: card[a] for a in axes}
    out["tolerances"] = {a: card.get(f"tol_{a}") for a in axes}
    return out


def stage_card(*, made, pose=None) -> dict:
    """Stage 5: read the composition card off the finished demo frame."""
    card = fork_e2e.driving_card([str(made)], pose=pose)
    checks = [("aesthetic card", card["outcome"], str(card.get("note")))]
    element = card_for_draft(card)
    numbers = {"card": element, "frames": card.get("frames"), "of": card.get("of")}
    if card["outcome"] == PASS and element is None:
        checks.append(
            (
                "card carries all four axes",
                UNMEASURED,
                "the card read but an axis is missing: an incomplete card is "
                "not a card, and the user frame would be judged against a hole",
            )
        )
    return _result(BUILD_STAGES[4], checks, numbers=numbers, card=element)


def stage_trial(
    *,
    styled,
    driving,
    first: int,
    last: int,
    work_dir,
    upload=None,
    kling=None,
    probe=None,
    cutter=None,
    decode=None,
    distances=None,
    cuts=None,
) -> dict:
    """Stage 6: cut the window, place the one paid order, accept what came back.

    The owner's decision 5: an aesthetic without a trial clip is not fit, so
    this stage is the one that spends money — and it is reached only after the
    five cheap stages have passed, never before.
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    checks: list = []
    numbers: dict = {"window": [first, last]}

    cut = fork_e2e.stage_window(
        driving=driving,
        first=first,
        last=last,
        out_path=work / DRAFT_NAMES["driving"],
        probe=probe,
        cutter=cutter,
    )
    checks += _checks_of(cut)
    numbers["cut"] = cut.get("numbers")
    if cut["outcome"] != PASS:
        return _result(
            BUILD_STAGES[5],
            checks,
            numbers=numbers,
            note="the window did not come out: no order was made, no money spent",
        )

    ordered = fork_e2e.stage_kling(
        styled=styled,
        window=cut["window"],
        out_path=work / DRAFT_NAMES["trial"],
        upload=upload,
        kling=kling,
        probe=probe,
    )
    checks += _checks_of(ordered)
    numbers["kling"] = ordered.get("numbers")
    if ordered["outcome"] != PASS:
        return _result(BUILD_STAGES[5], checks, numbers=numbers, window=cut["window"])

    accepted = fork_e2e.stage_output_acceptance(
        produced=ordered["produced"],
        client_photo=styled,
        frames_dir=work / "trial_frames",
        probe=probe,
        decode=decode,
        distances=distances,
        cuts=cuts,
    )
    checks += _checks_of(accepted)
    numbers["output"] = accepted.get("numbers")
    return _result(
        BUILD_STAGES[5],
        checks,
        numbers=numbers,
        window=cut["window"],
        trial=ordered["produced"],
    )


def draft_element(
    *,
    aesthetic_id: str,
    name: str,
    prompt: str,
    gender: str,
    demo_why: str,
    window,
    card,
    trial,
) -> dict:
    """Build the aesthetics-base element the contract describes, with published paths.

    The `driving` and `trial` fields name where the publishing command will put
    the two files, not where they sit in the draft: the draft already holds the
    element the base will receive, so nothing has to rewrite it later.
    """
    stem = f"{aesthetic_id}_{gender}"
    return {
        "id": aesthetic_id,
        "name": name,
        "kind": DRAFT_KIND,
        "prompt": prompt,
        "demo": gender,
        "demo_why": demo_why,
        "driving": f"{PUBLISHED_DRIVING_DIR}/{stem}.mp4",
        "window": [int(window[0]), int(window[1])],
        "card": card,
        "trial": None if trial is None else f"{PUBLISHED_TRIAL_DIR}/{stem}.mp4",
    }


def stage_draft(*, out_dir, element: dict, styled, driving, trial, report: dict) -> dict:
    """Stage 7: put the draft on disk — element, demo frame, driving copy, trial, report."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    checks: list = []
    numbers: dict = {"dir": str(out)}

    copies = [("demo", styled), ("driving", driving), ("trial", trial)]
    for key, src in copies:
        target = out / DRAFT_NAMES[key]
        if src is None:
            checks.append(
                (
                    f"{key} in the draft",
                    FAIL if key == "trial" else UNMEASURED,
                    f"nothing to copy into {target.name}"
                    + (
                        ": the owner's decision 5 makes an aesthetic without a trial clip unfit"
                        if key == "trial"
                        else ""
                    ),
                )
            )
            continue
        # Two of the three are written straight into the draft by the stages
        # that made them, so "copy" would be a file onto itself. The stage
        # still CHECKS all three: a file that is already in place is in place,
        # and skipping the check for it would leave the draft's own products
        # unverified while the borrowed driving was verified.
        already = Path(src).resolve() == target.resolve()
        if not already:
            try:
                shutil.copyfile(str(src), target)
            except Exception as exc:  # noqa: BLE001 - a copy that did not happen is not a pass
                checks.append((f"{key} in the draft", UNMEASURED, f"{type(exc).__name__}: {exc}"))
                continue
        checks.append(fork_e2e.file_fact(target, f"{key} in the draft"))

    (out / DRAFT_NAMES["aesthetic"]).write_text(
        json.dumps(element, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    checks.append(fork_e2e.file_fact(out / DRAFT_NAMES["aesthetic"], "aesthetic element"))
    (out / DRAFT_NAMES["report"]).write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    checks.append(fork_e2e.file_fact(out / DRAFT_NAMES["report"], "run report"))
    return _result(BUILD_STAGES[6], checks, numbers=numbers, draft=str(out))


def totals(stages: list) -> dict:
    """Fold the stages into one verdict with its three numbers.

    >>> totals([{"checked": 2, "violations": 0, "unmeasured": 0}])["outcome"]
    'pass'
    """
    checked = sum(int(s.get("checked", 0)) for s in stages)
    violations = sum(int(s.get("violations", 0)) for s in stages)
    unmeasured = sum(int(s.get("unmeasured", 0)) for s in stages)
    return {
        "outcome": fork_e2e.verdict(checked, violations, unmeasured),
        "checked": checked,
        "violations": violations,
        "unmeasured": unmeasured,
    }


def not_reached(stage: str, why: str) -> dict:
    """Return a stage that never ran. Not reached is "could not measure", never a pass."""
    return _result(stage, [(stage, UNMEASURED, why)], note=why)


def run(
    *,
    prompt,
    driving,
    window,
    gender: str,
    aesthetic_id: str,
    name: str,
    out_dir,
    demo_why: str = "",
    frames=None,
    intake=None,
    composer=None,
    stylize=None,
    sizer=None,
    distances=None,
    pose=None,
    upload=None,
    kling=None,
    probe=None,
    cutter=None,
    decode=None,
    cuts=None,
    log=None,
) -> dict:
    """Run the seven stages in order and stop before the paid one if any cheap stage failed."""
    first, last = int(window[0]), int(window[1])
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stages: list = []

    def add(stage: dict) -> dict:
        stages.append(stage)
        fork_e2e.say(fork_e2e.line(stage), log=log)
        return stage

    add(stage_driving(driving=driving, frames=frames, intake=intake))
    add(stage_prompt(prompt=prompt, aesthetic_id=aesthetic_id, composer=composer))
    built = stages[-1].get("prompt")

    styled = None
    if stages[-1]["outcome"] == PASS and built:
        add(
            stage_stylize(
                prompt=built,
                gender=gender,
                out_path=out / DRAFT_NAMES["demo"],
                stylize=stylize,
                sizer=sizer,
            )
        )
        styled = stages[-1].get("styled")
    else:
        add(not_reached(BUILD_STAGES[2], "the prompt did not assemble: nothing to stylise with"))

    if styled:
        add(stage_demo_acceptance(made=styled, gender=gender, distances=distances, sizer=sizer))
        add(stage_card(made=styled, pose=pose))
    else:
        add(not_reached(BUILD_STAGES[3], "no styled demo: nothing to accept"))
        add(not_reached(BUILD_STAGES[4], "no styled demo: nothing to read a card off"))
    card = stages[-1].get("card")

    cheap = totals(stages)
    trial = None
    if cheap["outcome"] == PASS:
        add(
            stage_trial(
                styled=styled,
                driving=driving,
                first=first,
                last=last,
                work_dir=out,
                upload=upload,
                kling=kling,
                probe=probe,
                cutter=cutter,
                decode=decode,
                distances=distances,
                cuts=cuts,
            )
        )
        trial = stages[-1].get("trial")
    else:
        add(
            not_reached(
                BUILD_STAGES[5],
                f"stages 1-5 ended {cheap['outcome']} with checked "
                f"{cheap['checked']}, violations {cheap['violations']}, "
                f"unmeasured {cheap['unmeasured']}: the paid order was NOT placed",
            )
        )

    element = draft_element(
        aesthetic_id=aesthetic_id,
        name=name,
        prompt=built or "",
        gender=str(gender).strip().lower(),
        demo_why=demo_why,
        window=(first, last),
        card=card,
        trial=trial,
    )
    report = {"stages": stages, "element": element, "cheap": cheap}
    add(
        stage_draft(
            out_dir=out,
            element=element,
            styled=styled,
            driving=driving,
            trial=trial,
            report=report,
        )
    )
    whole = totals(stages)
    fork_e2e.say(
        f"[{whole['outcome']:<18}] draft {aesthetic_id}_{gender} "
        f"checked {whole['checked']}, violations {whole['violations']}, "
        f"unmeasured {whole['unmeasured']}",
        log=log,
    )
    return {**whole, "stages": stages, "element": element, "draft": str(out)}


def main(argv=None) -> int:
    """Command line entry point: build one draft aesthetic."""
    parser = argparse.ArgumentParser(description="Build a draft aesthetic")
    parser.add_argument("--prompt", required=True, help="file holding the operator's prompt")
    parser.add_argument("--driving", required=True)
    parser.add_argument("--window", required=True, help="first:last, in driving frames")
    parser.add_argument("--gender", required=True, choices=list(fork_aesthetic.GENDERS))
    parser.add_argument("--id", required=True, dest="aesthetic_id")
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", required=True, dest="out_dir")
    parser.add_argument("--demo-why", default="", dest="demo_why")
    parser.add_argument("--frames", default=None, help="directory of unpacked driving frames")
    args = parser.parse_args(argv)

    frames = fork_e2e.frame_paths(args.frames) if args.frames else None
    got = run(
        prompt=Path(args.prompt).read_text(encoding="utf-8"),
        driving=args.driving,
        window=fork_e2e.parse_window(args.window),
        gender=args.gender,
        aesthetic_id=args.aesthetic_id,
        name=args.name,
        out_dir=args.out_dir,
        demo_why=args.demo_why,
        frames=frames,
    )
    return fork_video.EXIT_BY_OUTCOME[got["outcome"]]


if __name__ == "__main__":
    sys.exit(main())
