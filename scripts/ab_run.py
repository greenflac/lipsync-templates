#!/usr/bin/env python3
"""An A/B run: does an assembled prompt beat the raw request?

    python scripts/ab_run.py                 # DRY RUN. Prints the plan, spends nothing.
    python scripts/ab_run.py --spend         # actually calls the API

Dry run is the default and spending needs a flag, because the guard that
matters is the one in the code. On 2026-08-26 a single generation was made on
an inference that it was free; it was not. A paragraph saying "be careful" does
not survive the next session.

THE QUESTION, and it must be able to answer "no":

    Does a prompt assembled by studio.selfrag produce a better image than the
    same request sent to the model unchanged?

If the two arms are indistinguishable, the prompt-engineering layer is
decoration, and that is worth knowing at a cost of six images.

DESIGN

    arm A   the prompt studio.selfrag assembles (vendor skeleton + retrieved
            precedents + rule table)
    arm B   the request text, sent raw

Everything else is held: same model, same seed, same size, same aspect. One
variable.

    pair 1   flux, text to image
    pair 2   kontext, an EDIT of pair 1's arm-A image, so both arms edit the
             SAME picture. This is where the strongest cross-vendor rule we
             found gets tested directly: arm A drops what the reference already
             shows, arm B re-describes it.
    control- a prompt that deliberately breaks what we know: on-screen text
             (a tokenizer limit), chained actions (physics), contradictory
             light. If it scores like the rest, the JUDGING is broken and every
             other score in the run is void.
    control+ a prompt from the corpus, unchanged.

Six calls. Files land in work/ab/, and every generation is recorded in the
examples table so the ratings become training rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from studio.selfrag.corpus import load_corpus  # noqa: E402
from studio.selfrag.pipeline import PromptEngineer, PromptRequest  # noqa: E402

OUT = REPO / "work" / "ab"

# Held constant across every call, so the only difference between arms is the
# prompt. A drifting seed would make the comparison meaningless.
SEED = 7
WIDTH, HEIGHT = 832, 1216
MODEL_T2I = "flux"
MODEL_EDIT = "kontext"

REQUEST_1 = (
    "an amber glass serum bottle standing on porous volcanic stone, "
    "warm directional light, soft shadow, product photography"
)
REQUEST_2 = "make the background wet dark slate and the light cooler, leave the bottle untouched"

# Breaks three things this project has sourced: on-screen lettering is a
# character-blind encoder, not a resolution problem; chained causal actions
# fall off fast; two contradictory light sources have no single answer.
CONTROL_NEGATIVE = (
    "a serum bottle with the word LUMIERE written across the glass in gold script, "
    "it first sits on stone then rolls off and then lands in water, "
    "harsh midday sun and candlelight at the same time"
)


def corpus_control() -> str:
    """A prompt from the corpus, unchanged: the positive control.

    Chosen deterministically (first product-photography row in id order) so the
    run repeats. Its wording is not printed to a committed file.
    """
    out = load_corpus()
    for record in out.get("records") or []:
        if "продуктовая съёмка 2" in [t.lower() for t in record.tags]:
            return record.prompt
    return ""


def build() -> list[dict]:
    """Assemble every prompt. Costs nothing and touches no network."""
    engineer = PromptEngineer(state_path=str(REPO / "work" / "ab" / "state.sqlite3"))
    plan: list[dict] = []

    a1 = engineer.write(
        PromptRequest(
            text=REQUEST_1,
            model="flux",
            mode="t2i",
            subject="an amber glass serum bottle",
            camera="standing on porous volcanic stone, soft shadow",
        )
    )
    plan.append(
        {
            "id": "p1_A",
            "kind": "pair",
            "arm": "A",
            "api": "image",
            "model": MODEL_T2I,
            "prompt": a1["prompt"],
            "run_id": a1["run_id"],
            "outcome": a1["outcome"],
            "precedents": len(a1["examples"]),
        }
    )
    plan.append(
        {
            "id": "p1_B",
            "kind": "pair",
            "arm": "B",
            "api": "image",
            "model": MODEL_T2I,
            "prompt": REQUEST_1,
            "run_id": "",
            "outcome": "baseline",
        }
    )

    a2 = engineer.write(
        PromptRequest(
            text=REQUEST_2,
            model="flux",
            mode="edit",
            subject="an amber glass serum bottle",
            action="the background becomes wet dark slate, the light turns cooler",
        )
    )
    plan.append(
        {
            "id": "p2_A",
            "kind": "pair",
            "arm": "A",
            "api": "edit",
            "model": MODEL_EDIT,
            "prompt": a2["prompt"],
            "run_id": a2["run_id"],
            "outcome": a2["outcome"],
            "precedents": len(a2["examples"]),
            "reference": "p1_A",
        }
    )
    plan.append(
        {
            "id": "p2_B",
            "kind": "pair",
            "arm": "B",
            "api": "edit",
            "model": MODEL_EDIT,
            "prompt": REQUEST_2,
            "run_id": "",
            "outcome": "baseline",
            "reference": "p1_A",
        }
    )

    plan.append(
        {
            "id": "c_neg",
            "kind": "control",
            "arm": "negative",
            "api": "image",
            "model": MODEL_T2I,
            "prompt": CONTROL_NEGATIVE,
            "run_id": "",
            "outcome": "control",
        }
    )
    positive = corpus_control()
    plan.append(
        {
            "id": "c_pos",
            "kind": "control",
            "arm": "positive",
            "api": "image",
            "model": MODEL_T2I,
            "prompt": positive,
            "run_id": "",
            "outcome": "control" if positive else "MISSING: no corpus row matched",
        }
    )
    engineer.close()
    return plan


METER_KEYS = (
    "x-usage-completion-video-seconds",
    "x-usage-completion-audio-seconds",
    "x-usage-completion-image-count",
    "x-usage-total-cost",
    "x-usage",
    "x-cost",
    "x-model-used",
    "x-cache",
    "x-request-id",
)


def _capture_headers(sink: list[dict]):
    """Record the metering headers of every response, without reimplementing
    the client.

    `lipsync.pollinations.image` returns bytes and drops the response, so cost
    is invisible through it — and `lipsync/**` is frozen by CONTRACTS.md, so it
    cannot be changed here. Wrapping requests records what the server said
    about the price without a second copy of the call logic.
    """
    import requests

    real_get, real_post = requests.get, requests.post

    def note(r):
        sink.append(
            {k: v for k, v in ((k, r.headers.get(k)) for k in METER_KEYS) if v}
            | {"status": r.status_code, "bytes": len(r.content or b"")}
        )
        return r

    requests.get = lambda *a, **k: note(real_get(*a, **k))  # type: ignore[assignment]
    requests.post = lambda *a, **k: note(real_post(*a, **k))  # type: ignore[assignment]
    def вернуть_как_было() -> None:
        """Восстановить настоящие вызовы. Раньше стоял `lambda`, собиравший
        КОРТЕЖ ИЗ ДВУХ `setattr`, каждый из которых возвращает `None`, —
        значение выбрасывалось, и читать это как «функция что-то вернула»
        было нечего."""
        requests.get = real_get  # type: ignore[assignment]
        requests.post = real_post  # type: ignore[assignment]

    return вернуть_как_было


def run(plan: list[dict]) -> list[dict]:
    """Make the calls. Only reached with --spend."""
    from lipsync.pollinations import image, images_edit

    OUT.mkdir(parents=True, exist_ok=True)
    done: list[dict] = []
    for step in plan:
        meter: list[dict] = []
        restore = _capture_headers(meter)
        target = OUT / f"{step['id']}.jpg"
        if not step["prompt"]:
            step["error"] = "empty prompt: not called"
            done.append(step)
            continue
        try:
            if step["api"] == "image":
                image(
                    step["prompt"],
                    target,
                    model=step["model"],
                    seed=SEED,
                    width=WIDTH,
                    height=HEIGHT,
                )
            else:
                reference = OUT / f"{step['reference']}.jpg"
                if not reference.is_file():
                    step["error"] = f"reference {reference.name} was never produced"
                    done.append(step)
                    continue
                images_edit(
                    step["prompt"],
                    reference,
                    target,
                    model=step["model"],
                    width=WIDTH,
                    height=HEIGHT,
                )
            step["file"] = str(target)
            step["bytes"] = target.stat().st_size
        except Exception as exc:  # noqa: BLE001 - a failed call is a result too
            step["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            restore()
        step["metering"] = meter
        done.append(step)
    return done


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spend", action="store_true", help="actually call the paid API")
    args = parser.parse_args()

    plan = build()
    for step in plan:
        head = f"[{step['id']}] {step['api']}/{step['model']} arm={step['arm']}"
        extra = f" precedents={step.get('precedents')}" if "precedents" in step else ""
        print(f"{head}{extra}")
        text = step["prompt"] or ""
        print(f"    {text[:300] if text else '(EMPTY — ' + str(step.get('outcome')) + ')'}")
    print(f"\n{len(plan)} calls planned.")

    if not args.spend:
        print("DRY RUN: nothing was called and nothing was spent. Re-run with --spend.")
        (REPO / "work" / "ab").mkdir(parents=True, exist_ok=True)
        (REPO / "work" / "ab" / "plan.json").write_text(
            json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return 0

    done = run(plan)
    (OUT / "result.json").write_text(
        json.dumps(done, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    failed = [s for s in done if s.get("error")]
    print(f"\nproduced {len(done) - len(failed)} of {len(done)}; {len(failed)} failed")
    for s in failed:
        print(f"  {s['id']}: {s['error']}")
    # The same three-outcome hole that was OBSERVED in `scripts/ingest_harvest.py`
    # and fixed there on 2026-08-28: `1 if failed else 0` reads an empty run as a
    # clean one. Here it is worse than a green light on nothing — this is the
    # script that spends money, so "produced 0 of 0; 0 failed" exiting 0 would
    # report a successful A/B that never called anything.
    if not done:
        print(
            "\nCOULD NOT MEASURE: the plan ran zero calls, so nothing was produced "
            "and nothing failed. That is not a successful run."
        )
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
