"""Self-reflection over a retrieved set and over a drafted prompt.

WHAT THIS IS NOT. It is not Self-RAG as published (Asai et al., ICLR 2024,
arXiv:2310.11511). That method extends the *generator's vocabulary* with
reflection tokens (`Retrieve`, `ISREL`, `ISSUP`, `ISUSE`), trains the generator
on data annotated by a separate critic model, and runs segment-level beam
search that interpolates critique-token probabilities at inference. It needs a
fine-tuned generator. There is no version of that which runs on this machine,
and pretending otherwise would put a paper's reported numbers behind a system
that cannot produce them. (Source, second-hand: the paper was unreachable
through this session's egress proxy on 2026-08-26.)

WHAT THIS IS. The same three questions, asked by code that can actually answer
them, plus an optional second model for the one question code cannot:

    ISREL  is the retrieved set relevant?     -> `grade_context`, deterministic
    ISSUP  is the draft supported and legal?  -> `grade_draft`, deterministic
    ISUSE  is the draft any good?             -> `judge`, optional, injected

Two rules the design obeys and the paper's framing makes easy to violate:

* The verdict does not come from the doer. `grade_draft` is rules, not the
  writer. If a model judges, it is a DIFFERENT callable from the one that
  wrote — passing the same callable is refused, because a judge scoring its
  own output is an instrument with no negative control.
* Every grade has three outcomes. "Could not measure" is never folded into
  either "good" or "bad": a rule that could not run is counted in
  `unmeasured`, and a draft that only passed because six rules were skipped is
  not a draft that passed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.registry import ModelCard, card_for
from studio.selfrag.retrieval import Hit, confidence as retrieval_confidence
from studio.selfrag.spec import GenSpec, MODE_I2V, assemble
from studio.style import PALETTE_WORDS

__all__ = [
    "CONTEXT_MIN_CONFIDENCE",
    "MAX_ROUNDS",
    "RULES",
    "SEVERITY_CAVEAT",
    "SEVERITY_RISK",
    "SEVERITY_UNMEASURED",
    "SEVERITY_VIOLATION",
    "Finding",
    "grade_context",
    "grade_draft",
    "reflect",
]

SEVERITY_VIOLATION = "violation"  # the draft is wrong; do not ship it
SEVERITY_RISK = "risk"  # a documented failure mode is invited; warn
SEVERITY_UNMEASURED = "unmeasured"  # this rule could not run on THIS draft
SEVERITY_CAVEAT = "caveat"  # a standing limitation of the instrument itself

# The difference between the last two is worth stating, because collapsing them
# is a mistake this file made first and had to be fixed (OBSERVED 2026-08-26:
# every run in an end-to-end smoke test came back "could not measure", because
# "the model cards are second-hand" is true on every run forever). An
# UNMEASURED finding means a check that should have run on this prompt did not,
# and it changes the verdict. A CAVEAT means a constant, already-known
# limitation; it is printed on every report and changes no verdict, because a
# signal that fires every single time carries no information about any run.

# Below this retrieval confidence the context is treated as no context at all
# and the pipeline abstains rather than conditioning on it. CHOSEN, and chosen
# for a measured reason from the literature rather than taste: top-ranked but
# irrelevant context is reported to hurt answers more than no context does, so
# the failure this floor prevents is worse than the miss it causes.
# Mutate it in both directions and watch `test_reflect` change verdict.
CONTEXT_MIN_CONFIDENCE = 0.25

# Rounds of critique-and-revise. CHOSEN: each round is a full re-assembly and,
# when a reviser is supplied, a model call. Three rounds that have not fixed a
# rule violation are three rounds that will not.
MAX_ROUNDS = 3

# Words that make on-screen lettering likely. Text garbling in diffusion models
# is a tokenizer problem — character-blind text encoders cannot predict a
# word's glyph sequence — so this is a risk no amount of prompt polish removes.
_TEXT_WORDS = re.compile(
    r"\b(text|lettering|caption|subtitle|sign|signage|logo|watermark|title card|writing)\b",
    re.I,
)

# Phrases that ask an object to leave the frame and come back. Object
# permanence is a documented failure of current video models: nothing holds a
# persistent state for the hidden object.
_OCCLUSION = re.compile(
    r"\b(walks behind|disappears|out of frame|off screen|off-screen|hidden behind|reappears)\b",
    re.I,
)

# A degree or rate word. Some vendor guides put amplitude and rate in the
# motion slot explicitly ("swaying violently", "moving slowly"); a bare verb
# leaves the model to pick, and it picks badly under fast motion.
_RATE_WORDS = re.compile(
    r"\b(slow|slowly|fast|quickly|rapid|gentle|gently|violent|violently|steady|steadily"
    r"|abrupt|abruptly|gradual|gradually|slight|slightly|barely|sharply)\b",
    re.I,
)

# A constraint phrased as an instruction rather than as a thing. At least one
# vendor's guidance is to write negatives as nouns ("urban background"), not
# as commands ("no buildings"), because the encoder has no operator for "no".
_NEGATIVE_INSTRUCTION = re.compile(r"^\s*(no|not|without|avoid|don'?t|never)\b", re.I)

# Rough count of independent actions asked of one clip. Joint caption-and-
# physics satisfaction is low for current models, and it falls further the more
# causal steps a single clip must carry.
_ACTION_SPLIT = re.compile(r"\b(then|after that|and then|before|while|as soon as)\b", re.I)
MAX_ACTIONS = 2


@dataclass(frozen=True)
class Finding:
    """One thing a rule noticed, and what to do about it."""

    rule: str
    severity: str
    message: str
    fix: str = ""


# ------------------------------------------------------------------- rules
#
# Each rule takes (spec, draft, card) and returns findings. Held as a table so
# a test can drop one rule and watch a known-bad draft start passing; a rule
# nothing can turn off is a rule nothing proves is working.


def _rule_word_band(spec: GenSpec, draft: dict, card: ModelCard) -> list[Finding]:
    if not card.word_band:
        return [
            Finding(
                "word_band",
                SEVERITY_UNMEASURED,
                f"no published prompt-length band for {card.model_id}",
            )
        ]
    low, high = card.word_band
    words = int(draft.get("words") or 0)
    if words < low:
        return [
            Finding(
                "word_band",
                SEVERITY_RISK,
                f"{words} words is under {card.model_id}'s {low}-{high} band",
                f"add detail to the empty slots of {draft.get('skeleton')}",
            )
        ]
    if words > high:
        return [
            Finding(
                "word_band",
                SEVERITY_RISK,
                f"{words} words is over {card.model_id}'s {low}-{high} band",
                "cut the least load-bearing clause",
            )
        ]
    return []


def _rule_i2v_appearance(spec: GenSpec, draft: dict, card: ModelCard) -> list[Finding]:
    if spec.mode != MODE_I2V:
        return []
    prompt = (draft.get("prompt") or "").lower()
    colours = sorted({w for w in PALETTE_WORDS if re.search(rf"\b{re.escape(w)}\b", prompt)})
    if not colours:
        return []
    return [
        Finding(
            "i2v_appearance",
            SEVERITY_RISK,
            f"an image-to-video prompt re-describes appearance ({', '.join(colours)}); "
            "the reference image already carries it and the two signals fight",
            "drop the colour words; spend the prompt on motion",
        )
    ]


def _rule_negative_placement(spec: GenSpec, draft: dict, card: ModelCard) -> list[Finding]:
    if not spec.constraints:
        return []
    out: list[Finding] = []
    if card.negative_prompt == "yes" and not draft.get("negative_prompt"):
        out.append(
            Finding(
                "negative_placement",
                SEVERITY_VIOLATION,
                f"{card.model_id} has a negative_prompt field and it came back empty "
                "while constraints were requested",
                "route the constraints to the field, not the prose",
            )
        )
    if card.negative_prompt == "unknown":
        out.append(
            Finding(
                "negative_placement",
                SEVERITY_CAVEAT,
                f"whether {card.model_id} accepts a negative prompt was never verified",
            )
        )
    for constraint in spec.constraints:
        if _NEGATIVE_INSTRUCTION.match(constraint):
            out.append(
                Finding(
                    "negative_instruction",
                    SEVERITY_RISK,
                    f"constraint {constraint!r} is phrased as an instruction; these "
                    "encoders have no operator for 'no'",
                    "name the thing you want instead, as a noun",
                )
            )
    return out


def _rule_parameter_beats_prose(spec: GenSpec, draft: dict, card: ModelCard) -> list[Finding]:
    """A knob that controls the same thing as a phrase makes the phrase dead."""
    out: list[Finding] = []
    if "camera_fixed" in card.parameters and spec.camera:
        out.append(
            Finding(
                "parameter_beats_prose",
                SEVERITY_VIOLATION,
                f"{card.model_id} exposes camera_fixed, which overrides camera language; "
                f"the prompt still carries {spec.camera!r}",
                "set the camera_fixed parameter and delete the camera clause",
            )
        )
    if "character_orientation" in card.parameters and spec.mode == MODE_I2V:
        out.append(
            Finding(
                "parameter_beats_prose",
                SEVERITY_RISK,
                f"{card.model_id} drifts on face likeness under motion control; "
                "character_orientation=image is the documented remedy and is not set",
                "set character_orientation=image",
            )
        )
    return out


def _rule_on_screen_text(spec: GenSpec, draft: dict, card: ModelCard) -> list[Finding]:
    hit = _TEXT_WORDS.search(draft.get("prompt") or "")
    if not hit:
        return []
    return [
        Finding(
            "on_screen_text",
            SEVERITY_RISK,
            f"the prompt asks for on-screen lettering ({hit.group(0)!r}); glyph "
            "sequences are a text-encoder limitation, not a resolution one",
            "composite the text in post, or accept garbled glyphs",
        )
    ]


def _rule_occlusion(spec: GenSpec, draft: dict, card: ModelCard) -> list[Finding]:
    hit = _OCCLUSION.search(draft.get("prompt") or "")
    if not hit:
        return []
    return [
        Finding(
            "object_permanence",
            SEVERITY_RISK,
            f"the prompt hides and restores something ({hit.group(0)!r}); current "
            "video models keep no persistent state for an occluded object",
            "keep the subject in frame, or cut between shots instead",
        )
    ]


def _rule_motion_rate(spec: GenSpec, draft: dict, card: ModelCard) -> list[Finding]:
    if "motion" not in card.skeleton and "movement" not in card.skeleton:
        return []
    text = spec.motion or spec.action
    if not text:
        return []
    if _RATE_WORDS.search(text):
        return []
    return [
        Finding(
            "motion_rate",
            SEVERITY_RISK,
            f"the motion slot names an action with no amplitude or rate ({text!r})",
            "say how fast and how far: 'swaying gently', 'pushing in slowly'",
        )
    ]


def _rule_action_count(spec: GenSpec, draft: dict, card: ModelCard) -> list[Finding]:
    text = " ".join((spec.action, spec.motion))
    actions = len(_ACTION_SPLIT.findall(text)) + 1 if text.strip() else 0
    if actions <= MAX_ACTIONS:
        return []
    return [
        Finding(
            "action_count",
            SEVERITY_RISK,
            f"{actions} chained actions in one clip; joint prompt-and-physics "
            "satisfaction falls with each causal step",
            "one causal action per clip; chain them as separate shots",
        )
    ]


def _rule_dropped_field(spec: GenSpec, draft: dict, card: ModelCard) -> list[Finding]:
    """Text the caller supplied that no slot in this skeleton could carry.

    This is a violation, not a risk. The caller described a camera move, the
    skeleton had no camera slot, and the words vanished between the request and
    the paid render with nothing said. A prompt that quietly means less than it
    was asked to mean is wrong, however well it reads.
    """
    dropped = draft.get("dropped") or []
    if not dropped:
        return []
    return [
        Finding(
            "dropped_field",
            SEVERITY_VIOLATION,
            f"{', '.join(dropped)} was filled in but {card.model_id}'s "
            f"{draft.get('skeleton')} skeleton has no slot for it: the text was dropped",
            f"fold it into a slot {card.model_id} does have, or clear the field",
        )
    ]


def _rule_card_confidence(spec: GenSpec, draft: dict, card: ModelCard) -> list[Finding]:
    if card.confidence == "strong":
        return []
    return [
        Finding(
            "card_confidence",
            SEVERITY_CAVEAT,
            f"{card.model_id}'s limits are second-hand: no vendor document was read. "
            "This prompt is shaped against unverified limits.",
        )
    ]


RULES: tuple[tuple[str, Callable[[GenSpec, dict, ModelCard], list[Finding]]], ...] = (
    ("word_band", _rule_word_band),
    ("i2v_appearance", _rule_i2v_appearance),
    ("negative_placement", _rule_negative_placement),
    ("parameter_beats_prose", _rule_parameter_beats_prose),
    ("on_screen_text", _rule_on_screen_text),
    ("object_permanence", _rule_occlusion),
    ("motion_rate", _rule_motion_rate),
    ("action_count", _rule_action_count),
    ("dropped_field", _rule_dropped_field),
    ("card_confidence", _rule_card_confidence),
)


# ------------------------------------------------------------------ grading


def grade_context(
    hits: Sequence[Hit], *, rewrite_step: int = 0, floor: float = CONTEXT_MIN_CONFIDENCE
) -> dict:
    """ISREL: decide whether this retrieved set may condition the draft.

    Three outcomes, and the third is why the function exists:

    * `pass` — the set is usable as demonstrations.
    * `fail` — a set was returned and it is too weak to condition on. This is
      NOT the same as no set: a top-ranked but irrelevant example is the
      documented worst case, worse for the answer than nothing at all, so a
      weak set is dropped rather than passed along at reduced weight.
    * `could not measure` — nothing was retrieved, so relevance is not a
      question that was asked.

    >>> grade_context([])["outcome"]
    'could not measure'
    """
    if not hits:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "nothing was retrieved: relevance was not judged",
            "confidence": 0.0,
            "kept": [],
        }
    score = retrieval_confidence(hits, rewrite_step=rewrite_step)
    if score < floor:
        return {
            "outcome": FAIL,
            "checked": len(hits),
            "violations": len(hits),
            "unmeasured": 0,
            "note": (
                f"retrieval confidence {score} is under the {floor} floor "
                f"(query was widened {rewrite_step} time(s)); the set is dropped, "
                "because conditioning on near-miss examples is worse than no examples"
            ),
            "confidence": score,
            "kept": [],
        }
    return {
        "outcome": PASS,
        "checked": len(hits),
        "violations": 0,
        "unmeasured": 0,
        "note": f"{len(hits)} examples at confidence {score}",
        "confidence": score,
        "kept": list(hits),
    }


def grade_draft(spec: GenSpec, draft: dict, *, rules: Sequence[str] | None = None) -> dict:
    """ISSUP: run the rule table over a drafted prompt. Three outcomes.

    :param rules: which rule names to run; all of them by default. Drop one in
        a test and a known-bad draft must stop being caught.
    :returns: the judging dict plus `findings`.
    """
    card = card_for(spec.model)
    if card is None:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"{spec.model!r} has no card: no rule could run",
            "findings": [],
        }
    if not draft.get("prompt"):
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": f"there is no prompt to grade: {draft.get('note', 'no note')}",
            "findings": [],
        }

    wanted = set(rules) if rules is not None else {name for name, _ in RULES}
    findings: list[Finding] = []
    ran = 0
    for name, rule in RULES:
        if name not in wanted:
            continue
        ran += 1
        findings.extend(rule(spec, draft, card))

    violations = [f for f in findings if f.severity == SEVERITY_VIOLATION]
    risks = [f for f in findings if f.severity == SEVERITY_RISK]
    unknown = [f for f in findings if f.severity == SEVERITY_UNMEASURED]
    caveats = [f for f in findings if f.severity == SEVERITY_CAVEAT]

    if ran == 0:
        # Zero checks is never a pass. This is the whole point of counting.
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "no rule ran: nothing was graded, which is not the same as nothing wrong",
            "findings": [],
        }
    if violations:
        outcome = FAIL
        note = f"{len(violations)} violation(s): " + "; ".join(f.message for f in violations)
    elif unknown:
        outcome = UNMEASURED
        note = f"{ran} rules ran, {len(unknown)} could not be measured: " + "; ".join(
            f.message for f in unknown
        )
    else:
        outcome = PASS
        note = f"{ran} rules ran, {len(risks)} risk(s) noted, nothing to refuse"
    if caveats:
        note = f"{note} [standing caveats: " + "; ".join(f.message for f in caveats) + "]"
    return {
        "outcome": outcome,
        "checked": ran,
        "violations": len(violations),
        "unmeasured": len(unknown),
        "note": note,
        "findings": findings,
        "risks": len(risks),
        "caveats": len(caveats),
    }


def judge(
    draft: dict,
    *,
    judge_model: Callable[[str], str],
    writer_model: Callable[[str], str] | None = None,
) -> dict:
    """ISUSE: ask a SECOND model whether the draft is any good.

    Refuses to run when the judge is the same callable as the writer. A model
    scoring its own output is a documented bias, not a measurement, and the
    house rule is that the verdict does not come from the doer.

    The judge is asked for one token — GOOD, WEAK or UNSURE — because a judge
    allowed to write prose writes a justification for whatever it said first.
    """
    if writer_model is not None and judge_model is writer_model:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "the judge is the writer: refused, that is not a measurement",
            "verdict": "",
        }
    prompt = (
        "You are grading a generation prompt written by someone else. Answer with "
        "exactly one word: GOOD, WEAK, or UNSURE. Answer UNSURE if you cannot tell.\n\n"
        f"PROMPT UNDER REVIEW:\n{draft.get('prompt')}\n"
    )
    try:
        raw = judge_model(prompt)
    except Exception as exc:  # noqa: BLE001 - any judge failure is "could not measure"
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"the judge did not answer: {type(exc).__name__}: {exc}",
            "verdict": "",
        }
    verdict = str(raw).strip().upper()[:6]
    if verdict.startswith("GOOD"):
        return {
            "outcome": PASS,
            "checked": 1,
            "violations": 0,
            "unmeasured": 0,
            "note": "the judge said GOOD",
            "verdict": "GOOD",
        }
    if verdict.startswith("WEAK"):
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": "the judge said WEAK",
            "verdict": "WEAK",
        }
    return {
        "outcome": UNMEASURED,
        "checked": 1,
        "violations": 0,
        "unmeasured": 1,
        "note": f"the judge answered {raw!r}, which is not one of the three words",
        "verdict": "UNSURE",
    }


def reflect(
    spec: GenSpec,
    *,
    reviser: Callable[[GenSpec, Sequence[Finding]], GenSpec] | None = None,
    rounds: int = MAX_ROUNDS,
) -> dict:
    """Draft, grade, revise, up to `rounds` times. Three outcomes.

    Every round is recorded in `history` with its own findings, so a reader can
    see whether the loop converged or merely ran out of budget — a distinction
    a single final verdict hides.

    :param reviser: turns a spec plus its findings into a better spec. `None`
        means one draft and one grade, no revision.
    :returns: the judging dict plus `spec`, `draft`, `findings`, `history`.
    """
    current = spec
    history: list[dict] = []
    draft: dict = {}
    grade: dict = {}

    for round_no in range(1, max(1, rounds) + 1):
        draft = assemble(current)
        grade = grade_draft(current, draft)
        history.append(
            {
                "round": round_no,
                "outcome": grade["outcome"],
                "violations": grade["violations"],
                "unmeasured": grade["unmeasured"],
                "note": grade["note"],
            }
        )
        if grade["outcome"] != FAIL or reviser is None:
            break
        try:
            revised = reviser(current, grade.get("findings", []))
        except Exception as exc:  # noqa: BLE001
            history[-1]["note"] += f" | the reviser raised {type(exc).__name__}: {exc}"
            break
        if not isinstance(revised, GenSpec) or revised == current:
            history[-1]["note"] += " | the reviser changed nothing: stopping"
            break
        current = revised

    converged = grade.get("outcome") != FAIL
    note = grade.get("note", "nothing was graded")
    if not converged and len(history) >= max(1, rounds):
        note = f"{note} | ran out of rounds after {len(history)}: this did not converge"
    return {
        "outcome": grade.get("outcome", UNMEASURED),
        "checked": grade.get("checked", 0),
        "violations": grade.get("violations", 0),
        "unmeasured": grade.get("unmeasured", 1),
        "note": note,
        "spec": current,
        "draft": draft,
        "findings": grade.get("findings", []),
        "history": history,
        "rounds_used": len(history),
    }
