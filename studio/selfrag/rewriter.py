"""Turn a user's intent into a prompt for one model, inventing nothing.

OWNER: agent A. Nobody else writes this file.

THE PRODUCT RULE, and it is the whole design

The user cannot write a good prompt. This module writes one FROM THEIR INTENT.
It only re-organises what they said into the shape the target model's own
guide asks for. It never names an object, a material, a place, a colour or a
creature the user did not name.

The evidence: in the one randomised trial in this field (N=1,891, 300,000+
images, https://arxiv.org/abs/2407.14333, read via search summary — this
environment cannot open arxiv, so НЕПРОВЕРЕНО at first hand) automatic
rewriting **erased 58% of the model's gain**, because the rewrites "added
extra details or changed the meaning". Prompt length correlates with quality
at about -0.07. Longer is not better. Faithful is better.

TWO PATHS, AND THEY FAIL DIFFERENTLY

`model=None` — the deterministic path. It costs nothing, opens no socket, and
is **incapable of invention by construction**: it splits the user's text into
clauses, files each clause under a slot of the card's skeleton, and emits the
clauses in slot order. Every character of the output is a character of the
input. There is no vocabulary in this module that could reach a prompt. The
audit still runs over its output, as a negative control on that claim — a
by-construction argument that is never checked is a comment, not a property.

`model=<callable>` — the few-shot path. The retrieved `examples` are shown as
demonstrations of HOW prompts for this model are written, never as content to
borrow, and the audit's `sources` are the user's intent ALONE, so a word that
arrives from an example is reported as invention exactly like a word the model
made up. That is deliberate: a detail is not the user's intent because a
precedent happened to contain it.

The audit is not advisory. A model output that invents is retried once with
the invented words named, and if it invents again the deterministic prompt is
returned with `source="model_rejected"`. A refusal that leaves the user with
nothing is worse than a plain prompt.

WHAT "OPTIMISE FOR THE MODEL" IS ALLOWED TO MEAN HERE

Reordering into the card's slot order; dropping what the card has no slot for
and saying so; shortening for a model whose card says it expands the prompt
internally. Nothing else. In particular there is no synonym map: the last one
in this repository read the user's "porous volcanic stone" as the palette
colour "sand" and the generator put literal sand under the bottle.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.corpus import CorpusRecord
from studio.selfrag.facts import FactStore, claims as fact_claims
from studio.selfrag.fidelity import audit as fidelity_audit
from studio.selfrag.registry import ModelCard
from studio.selfrag.spec import SLOT_BUILDERS

__all__ = [
    "BOOSTERS",
    "CUE_SHARE",
    "FILLER_WORDS",
    "GIBBERISH_SHARE",
    "MAX_EXAMPLES",
    "MAX_ROUNDS",
    "MIN_INTENT_CONTENT_WORDS",
    "SHORTEN_MAX_WORDS",
    "SLOT_CUES",
    "SOURCE_DETERMINISTIC",
    "SOURCE_MODEL",
    "SOURCE_MODEL_REJECTED",
    "build_prompt",
    "deterministic",
    "expands_internally",
    "rewrite",
]

SOURCE_DETERMINISTIC = "deterministic"
SOURCE_MODEL = "model"
SOURCE_MODEL_REJECTED = "model_rejected"

#: Model attempts allowed before the deterministic prompt wins.
#:
#: ВЫБРАНО by agent A, from the contract's own wording: "retry once telling it
#: exactly which words were invented". One first attempt plus one corrected
#: attempt is two. Higher is not obviously better and is definitely more
#: expensive: each round is a paid call, and a model that invented twice with
#: the invented words quoted back at it has not misunderstood the instruction,
#: it has disagreed with it.
MAX_ROUNDS = 2

#: Word cap applied to the finished prompt when the card's facts say the model
#: expands the prompt internally.
#:
#: РАСЧЁТ from the one vendor fact in `studio/knowledge/model_facts.jsonl` that
#: was read at first hand: Wan's `prompt_extend.py` "rewrites to about 80-100
#: words". Handing that expander a prompt already at its output length leaves
#: it nothing to do but pad or discard, and which of the two it does is
#: undocumented. Half of the low end — 40 — leaves room for the expansion the
#: vendor recommends. It is a РАСЧЁТ and not an ИЗМЕРЕНО: nobody here has run
#: Wan and measured the difference between a 40-word and an 80-word input.
SHORTEN_MAX_WORDS = 40

#: Fewest content words an intent must carry to be rewritten at all.
#:
#: ВЫБРАНО by agent A, from what the three outcomes have to distinguish. One
#: content word ("bottle") is a noun, not an intent: a prompt built from it
#: would be that one word, and calling that a rewrite claims work nobody did.
#: The honest answer is `could not measure` — nothing was wrong with the
#: request, there was simply nothing in it to reorganise. Deliberately not
#: higher: it is not this module's business to tell a user their idea is too
#: small, only to say when there is nothing there at all.
MIN_INTENT_CONTENT_WORDS = 2

#: Precedents shown to the model. ВЫБРАНО by agent A: the retrieval layer's own
#: k is 5 (`studio.selfrag.pipeline`), and every example is prompt tokens paid
#: for on every round. Three demonstrations show a house style; ten teach the
#: model the examples' content, which is exactly the failure being guarded
#: against.
MAX_EXAMPLES = 3

#: What share of a clause's content words must be cue words before the clause
#: is filed by its cue rather than left where the user put it.
#:
#: ВЫБРАНО by agent A at 0.30, after `studio.selfrag.evidence.CRAFT_SHARE`
#: (0.50) but deliberately lower, because the two ratios are guarding opposite
#: harms. There, a false positive puts somebody else's petals in the picture.
#: Here, a false positive only MOVES the user's own clause, and a false
#: negative only leaves it where they wrote it.
#:
#: Checked against the clauses the control set actually contains: 0.30 files
#: "warm directional light" (1 of 3), "soft shadow" (1 of 2) and "handheld
#: medium shot" (2 of 3), and leaves alone "a matte black bluetooth speaker on
#: a desk" (1 of 5). That last one is why the ratio exists at all: a bare
#: contains-check read the finish word "matte" as a texture clause and DROPPED
#: the user's subject on a card with no texture slot (OBSERVED against
#: fixtures/rewriter_control_set.jsonl row r11).
CUE_SHARE = 0.30

#: Share of an intent's words that may be unpronounceable before the intent is
#: reported as unreadable rather than rewritten.
#:
#: ВЫБРАНО by agent A at 0.50: half. Below half, a strange token is a brand, a
#: model number or a typo, and refusing a real request over one of those is
#: the worse mistake. At half or more there is no intent left to be faithful
#: to, and a confident prompt built from it would be pure invention — which is
#: the failure the third outcome exists to prevent (control set row x04,
#: "asdkjhasd qwoieu zxcmnv").
GIBBERISH_SHARE = 0.50

#: Folklore that names no visible property. Quoted into the system instruction
#: so the ban is explicit rather than implied, and listed here so it is one
#: list rather than a sentence somebody edits.
#: Provenance: the contract's forbidden list, and docs/knowledge/core_rules.md
#: "Dead practices" — "they name no visible property".
BOOSTERS: tuple[str, ...] = (
    "masterpiece",
    "8k",
    "4k quality",
    "ultra detailed",
    "award-winning",
    "trending on artstation",
    "best quality",
    "highly detailed",
)

# A clause is where one thought ends. Prompts in this trade are written as
# comma-separated descriptors, and so is ordinary intent ("a bottle on stone,
# warm light, shot close"). Splitting on n-grams instead cuts sentences in
# half; `studio.selfrag.evidence` learned that the expensive way.
_CLAUSE_SPLIT = re.compile(r"[,;\n]+|(?<=[.!?])\s+")
_MULTI_WS = re.compile(r"\s+")
_WORD = re.compile(r"[a-z0-9][a-z0-9'-]*")

# Words that carry no scene content. Kept tiny on purpose: this list is only
# used to decide whether an intent is empty, and a long stop-list would start
# calling real requests empty.
_EMPTY_WORDS: frozenset[str] = frozenset(
    "a an and the is are of on in at by with to from it its this that for".split()
)


#: Words that are the user talking ABOUT the request rather than describing
#: the picture: first-person pronouns, hedges, and the vocabulary of asking.
#:
#: Used for exactly one decision — which clause to cut first when a prompt has
#: to be shortened — and it can only ever REMOVE words, never add any, so it
#: cannot become the synonym map that put sand under the bottle. Every removal
#: is reported in `dropped`.
#:
#: OBSERVED against fixtures/rewriter_control_set.jsonl rows s01, s03 and s06:
#: cutting from the end of the prompt kept "ok so basically what i am going for
#: here is" and "i will be honest i am not good at this" while cutting "and
#: there is a single lamp on" and "the main thing is the fabric moving". The
#: users' actual subjects were being spent to preserve their apologies.
FILLER_WORDS: frozenset[str] = frozenset(
    """
    i we you me my our us am be will can does do did going want wanted need
    ok okay so right basically honestly honest really just maybe guess like
    kind sort bit thing things main point whole rest all else something
    anything whatever make makes sense think feel know keep rewriting brief
    roughly here there please idea trying try what which who how why not
    would could should might must have has had been get got nothing
    hi hello thanks thank told tell say said means mean love
    """.split()
)


# ------------------------------------------------------------ slot routing

# Which kind of thing each cue word marks. The categories are the ones the
# vendor skeletons actually name, collapsed across vendors: Kling's "action",
# Seedance's "movement" and Wan's "motion" are one category with three names.
#
# The lists are deliberately SHORT. A clause that matches nothing goes to the
# skeleton's first slot, which keeps the user's words in the prompt; a clause
# that matches the WRONG category can be dropped, which loses them. So the
# failure direction of a missing cue is harmless and the failure direction of
# an over-eager cue is not, and the lists are sized accordingly.
SLOT_CUES: dict[str, tuple[str, ...]] = {
    "action": (
        "walking",
        "walks",
        "running",
        "runs",
        "turning",
        "turns",
        "spinning",
        "spins",
        "moving",
        "moves",
        "movement",
        "motion",
        "dancing",
        "pouring",
        "opening",
        "falling",
        "rising",
        "swaying",
        "drifting",
        "gesture",
    ),
    "camera": (
        "camera",
        "lens",
        "close-up",
        "closeup",
        "wide-angle",
        "pan",
        "pans",
        "panning",
        "tilt",
        "dolly",
        "zoom",
        "zooms",
        "tracking",
        "handheld",
        "aerial",
        "overhead",
        "low-angle",
        "eye-level",
        "macro",
        "framing",
        "orbit",
        "crane",
        "tripod",
        "bokeh",
        "focus",
    ),
    "light": (
        "light",
        "lighting",
        "lit",
        "backlit",
        "sunlight",
        "daylight",
        "moonlight",
        "candlelight",
        "shadow",
        "shadows",
        "glow",
        "silhouette",
        "illuminated",
        "softbox",
        "rim",
        "highlight",
        "highlights",
    ),
    "texture": (
        "texture",
        "matte",
        "glossy",
        "satin",
        "sheen",
        "polished",
        "brushed",
        "frosted",
        "grainy",
        "velvety",
        "rough",
        "smooth",
    ),
    "palette": (
        "palette",
        "colour",
        "color",
        "colours",
        "colors",
        "tones",
        "monochrome",
        "desaturated",
        "saturated",
        "muted",
    ),
    "audio": (
        "audio",
        "sound",
        "sounds",
        "music",
        "voice",
        "dialogue",
        "narration",
        "hum",
        "whisper",
        "says",
        "saying",
        "sfx",
    ),
    "style": (
        "style",
        "cinematic",
        "photorealistic",
        "hyperrealistic",
        "editorial",
        "documentary",
        "anime",
        "illustration",
        "painting",
        "photography",
        "photograph",
        "vintage",
        "retro",
        "aesthetic",
        "mood",
        "render",
    ),
    "setting": (
        "background",
        "backdrop",
        "environment",
        "setting",
        "indoors",
        "outdoors",
    ),
    "constraints": (
        "without",
        "avoid",
        "exclude",
        "no",
        "not",
        "never",
    ),
}

# Ties break by this order, strongest signal first. A clause naming both a
# camera and a light ("backlit close-up") is filed under the camera, because
# the camera slot exists in every skeleton that has a light slot and not the
# other way round, so the camera choice loses less.
_CUE_PRIORITY: tuple[str, ...] = (
    "constraints",
    "audio",
    "camera",
    "action",
    "light",
    "texture",
    "palette",
    "setting",
    "style",
)

# Which category each of `spec.SLOT_BUILDERS`' sources belongs to. The slot
# names themselves are NOT re-listed here: `SLOT_BUILDERS` is imported so that
# a new vendor slot is added in one place (Е1). What this table adds is the
# one thing `spec` has no opinion about — which cue words point at a source.
_CATEGORY_OF_SOURCE: dict[str, str] = {
    "subject": "subject",
    "camera": "camera",
    "audio": "audio",
    "_action": "action",
    "_motion": "action",
    "_light": "light",
    "_texture": "texture",
    "_palette": "palette",
    "_setting": "setting",
    "_style": "style",
    "_constraints": "constraints",
}


# Where a clause goes when the skeleton has no slot for its own category.
#
# The split is between what the model DOES and what the picture SHOWS. A
# silent model cannot make a sound and a still image cannot pan, so an audio,
# camera, action or constraints clause aimed at a card without that slot is a
# request the model cannot serve: it is dropped and reported. Everything that
# merely DESCRIBES the picture always has somewhere to ride, because every
# skeleton in the registry ends with a prose style slot and begins with a
# subject one — so a texture clause on veo-3.1 becomes part of its style
# rather than vanishing (OBSERVED against control set row u03, where "grainy
# 16mm look" was dropped from a prompt the user had written correctly).
_FALLBACK: dict[str, tuple[str, ...]] = {
    "texture": ("style", "subject"),
    "palette": ("style", "subject"),
    "light": ("style", "subject"),
    "setting": ("subject",),
    "style": ("subject",),
    "subject": (),
    "audio": (),
    "camera": (),
    "action": (),
    "constraints": (),
}


def _clauses(text: str) -> list[str]:
    """The comma-separated thoughts of an intent, whitespace normalised."""
    out: list[str] = []
    for piece in _CLAUSE_SPLIT.split(str(text or "")):
        clause = _MULTI_WS.sub(" ", piece or "").strip().strip(".")
        if clause:
            out.append(clause)
    return out


def _content_words(text: str) -> list[str]:
    return [w for w in _WORD.findall(str(text or "").lower()) if w not in _EMPTY_WORDS]


def _scene_share(clause: str) -> float:
    """What share of this clause describes the picture rather than the ask.

    The measure a shortening decision is made on. "does that make sense" scores
    0.0 and "it is stainless steel" scores 1.0, which is the whole difference
    between cutting an apology and cutting the machine.

    A SHARE and not a count, and the difference was measured: counting scene
    words outright preferred a long rambling clause (9 scene words inside 17)
    over the short clause naming the product (4 words, all of them the
    product), and cut the espresso machine out of a prompt about an espresso
    machine (OBSERVED against control set row s04).
    """
    content = _content_words(clause)
    if not content:
        return 0.0
    return len([w for w in content if w not in FILLER_WORDS]) / len(content)


#: A token nobody could pronounce: no vowel at all, or a run of four
#: consonants, or a run of four vowels. Checked rather than guessed against the
#: control set and this repository's own prose — the intents in
#: fixtures/rewriter_control_set.jsonl produce no hit outside row x04.
_VOWELS = "aeiouy"


def _unpronounceable(word: str) -> bool:
    run_consonant = run_vowel = 0
    has_vowel = False
    for letter in word:
        if not letter.isalpha():
            continue
        if letter in _VOWELS:
            has_vowel = True
            run_vowel += 1
            run_consonant = 0
        else:
            run_consonant += 1
            run_vowel = 0
        if run_consonant >= 4 or run_vowel >= 4:
            return True
    return len(word) > 2 and not has_vowel


def _category(clause: str) -> str | None:
    """Which kind of thing this clause is about, or None when nothing matched.

    None is a real answer and is not "subject": the caller decides where an
    unclassified clause goes, and it must not be routed by a guess made here.
    """
    content = _content_words(clause)
    if not content:
        return None
    words = set(content)
    scores = {
        name: len(words.intersection(cues))
        for name, cues in SLOT_CUES.items()
        if words.intersection(cues)
    }
    if not scores:
        return None
    best = max(scores.values())
    # One cue word inside a long clause is a mention, not a subject. The ratio
    # is what tells "warm directional light" from "a matte black bluetooth
    # speaker on a desk", and without it the second was filed as a texture.
    if best / len(content) < CUE_SHARE:
        return None
    for name in _CUE_PRIORITY:
        if scores.get(name) == best:
            return name
    return None


def _slot_categories(card: ModelCard, slot: str) -> set[str]:
    """Every category this card's slot can carry.

    `card.slot_sources` is honoured, which is the whole reason it exists: Kling
    packs camera, light, texture and mood into one "style" slot, so on a Kling
    card a camera clause has somewhere to go and is not dropped.
    """
    sources = card.slot_sources.get(slot) or (SLOT_BUILDERS.get(slot),)
    return {_CATEGORY_OF_SOURCE[s] for s in sources if s and s in _CATEGORY_OF_SOURCE}


def expands_internally(model_id: str, *, store: FactStore | None = None) -> bool:
    """Does this model's own pipeline rewrite the prompt before generating?

    True ONLY when the fact base agrees and says yes. A contested attribute, a
    blog-only attribute and an absent attribute all return False, because the
    action this answer triggers is DROPPING the user's words, and dropping them
    on a rumour is the more expensive mistake of the two.
    """
    attribute = "expands_internally"
    # The process-wide store is reused rather than rebuilt: `FactStore()` reads
    # the whole fact file, and this is called once per round and once per
    # deterministic build. A store is still injectable, because a test that has
    # to edit the repository's fact file to exercise a branch is a test that
    # edits the repository.
    claim = store.claims(model_id, attribute) if store else fact_claims(model_id, attribute)
    if claim["outcome"] != PASS:
        return False
    return any(str(value).strip().lower().startswith("yes") for value in claim["values"])


def deterministic(intent: str, card: ModelCard) -> dict:
    """Reorganise the intent into the card's slot order. Invents nothing.

    Every clause of the output is a clause of the input, verbatim. The only
    thing this function adds is the comma between them, so the "no word may
    appear that did not appear in the input" property is not a promise about
    behaviour, it is a fact about the code: there is no other string to emit.

    :returns: ``{"prompt", "slots", "dropped", "trimmed"}``. `dropped` holds
        clauses this card's skeleton has no slot for and `trimmed` holds
        clauses cut to fit an internally-expanding model — in the user's own
        words, because a clause that vanished silently is the failure these
        keys exist to prevent. The two are separate because they have
        different remedies: a dropped clause needs a different model, a
        trimmed one needs a shorter request. Reporting them as one list made
        the note say "had no slot" about clauses that had a slot and lost it
        (OBSERVED while building this, on a 60-word wan-2.6-flash intent).
    """
    filed: dict[str, list[str]] = {}
    dropped: list[str] = []
    default_slot = card.skeleton[0] if card.skeleton else ""
    # Where the previous clause went. An unclassified clause follows it rather
    # than being sent to the front, and that single line is what makes
    # "leave a good prompt alone" the DEFAULT behaviour instead of a case to
    # be detected. People write in runs — a subject clause, then more about the
    # subject; a camera clause, then more about the camera — and the cue lists
    # only recognise the first of each run. Sending the rest to slot 0 shuffled
    # prompts that were already in the vendor's own order (OBSERVED against
    # fixtures/rewriter_control_set.jsonl rows u02 and u03, both marked
    # `unchanged`, both reordered by the first version of this loop).
    previous = default_slot

    for clause in _clauses(intent):
        category = _category(clause)
        target = ""
        if category is None:
            target = previous
        else:
            for candidate in (category, *_FALLBACK.get(category, ())):
                for slot in card.skeleton:
                    if candidate in _slot_categories(card, slot):
                        target = slot
                        break
                if target:
                    break
        if not target:
            # The model cannot do this kind of thing at all: no audio slot on a
            # silent model, no camera on a still image. Reported, never hidden.
            dropped.append(clause)
            continue
        filed.setdefault(target, []).append(clause)
        previous = target

    ordered: list[tuple[str, str]] = [
        (slot, clause) for slot in card.skeleton for clause in filed.get(slot, ())
    ]

    # A model that expands the prompt itself is handed less, not more: the
    # expansion is coming either way, and stacking our words under its words
    # is the lengthening the trial measured the cost of. Clauses come off the
    # END, where every vendor skeleton keeps its style and mood material.
    trimmed: list[str] = []
    if expands_internally(card.model_id):
        while len(" ".join(c for _, c in ordered).split()) > SHORTEN_MAX_WORDS and len(ordered) > 1:
            # Cut the clause that describes the least of the picture, and among
            # equals the latest one — the tail of every vendor skeleton is its
            # style material, and the head is the subject. Cutting the tail
            # first, which is what this loop used to do, spent the user's
            # subject to keep their apology (see FILLER_WORDS).
            worst = min(
                range(len(ordered)),
                key=lambda i: (_scene_share(ordered[i][1]), -i),
            )
            trimmed.append(ordered.pop(worst)[1])

    slots: dict[str, str] = {}
    for slot, clause in ordered:
        slots[slot] = f"{slots[slot]}, {clause}" if slot in slots else clause
    return {
        "prompt": ", ".join(clause for _, clause in ordered),
        "slots": slots,
        "dropped": dropped,
        "trimmed": trimmed,
    }


# ------------------------------------------------------------- the model path


def build_prompt(
    intent: str,
    card: ModelCard,
    examples: Sequence[CorpusRecord] = (),
    *,
    invented_words: Sequence[str] = (),
) -> str:
    """The few-shot prompt sent to the rewriting model.

    Built as a function rather than inline so it can be read by a test without
    a model callable in sight (Т5): the system instruction IS the product rule,
    and a rule that lives only inside a call nobody can inspect degrades
    silently.

    The examples are introduced as demonstrations of FORM. They are the answer
    to "how does one write for this model", never to "what is in the picture" —
    and because the audit downstream is given the user's intent alone as its
    source, a word borrowed from an example is caught as invention.
    """
    lines = [
        "You rewrite a user's intent into a prompt for one specific "
        f"generation model: {card.model_id}.",
        "",
        "RULES, and the first one is absolute:",
        "1. INVENT NOTHING. Do not name any object, material, place, colour, "
        "creature or action the user did not name. You may reorder their "
        "words, restate them in this model's idiom, and drop what does not "
        "fit. You may not add content.",
        "2. Do NOT add quality boosters. These are forbidden and name no "
        f"visible property: {', '.join(BOOSTERS)}.",
        "3. Do not lengthen for its own sake. Longer is not better; faithful is better.",
        f"4. Write the prompt in this model's slot order: {', '.join(card.skeleton)}.",
        "5. Answer with the prompt only. No preamble, no explanation.",
    ]
    if card.word_band:
        low, high = card.word_band
        lines.append(f"6. This model's published working length is {low}-{high} words.")
    if expands_internally(card.model_id):
        lines.append(
            f"6. This model expands the prompt internally. Stay under "
            f"{SHORTEN_MAX_WORDS} words and leave it room."
        )
    for quirk in card.quirks:
        lines.append(f"- known behaviour of this model: {quirk}")

    shown = [e for e in examples if str(getattr(e, "prompt", "")).strip()][:MAX_EXAMPLES]
    if shown:
        lines += [
            "",
            f"{len(shown)} prompt(s) that were actually run against this kind of "
            "model, shown ONLY as demonstrations of how such prompts are "
            "written. Their content is not the user's and must not appear in "
            "your answer:",
        ]
        for example in shown:
            lines.append(f"  FORM EXAMPLE: {example.prompt}")

    if invented_words:
        lines += [
            "",
            "Your previous answer was REJECTED. It named these things the user "
            f"never mentioned: {', '.join(invented_words)}. Remove every one of "
            "them. Do not replace them with substitutes.",
        ]

    lines += ["", "USER INTENT, which is the only content you may use:", intent.strip()]
    return "\n".join(lines)


def _judging(
    outcome: str,
    *,
    checked: int,
    violations: int,
    unmeasured: int,
    note: str,
    prompt: str | None,
    dropped: Iterable[str] = (),
    invented: Iterable[str] = (),
    source: str = SOURCE_DETERMINISTIC,
    rounds: int = 0,
) -> dict:
    """One shape for every return, so no caller has to know which branch ran."""
    return {
        "outcome": outcome,
        "checked": checked,
        "violations": violations,
        "unmeasured": unmeasured,
        "note": note,
        "prompt": prompt,
        "dropped": list(dropped),
        "invented": list(invented),
        "source": source,
        "rounds": rounds,
    }


def rewrite(
    intent: str,
    *,
    card: ModelCard,
    examples: Sequence[CorpusRecord] = (),
    model: Callable[[str], str] | None = None,
) -> dict:
    """Turn intent into a prompt for `card`'s model. Three outcomes.

    `model=None` means no network and no cost: a deterministic reorganisation
    that cannot invent by construction. A callable means few-shot rewriting,
    whose output is then put through `fidelity.audit` and REJECTED if it
    invented anything — the gate is not advisory.

    * `pass` — a prompt exists and the audit returned `pass`.
    * `fail` — the model invented, and after `MAX_ROUNDS` it still invented.
      The deterministic prompt is returned anyway, with
      `source="model_rejected"`: a refusal that leaves the user with nothing
      is worse than a plain prompt.
    * `could not measure` — no intent, no card, or the model was asked and did
      not answer. Note the asymmetry with `fail`, and it is the point: nothing
      was measured, so nothing may be reported as clean.
    """
    if card is None:  # type: ignore[unreachable]
        return _judging(
            UNMEASURED,
            checked=0,
            violations=0,
            unmeasured=1,
            note="no model card: there is no skeleton to rewrite into",
            prompt=None,
        )

    words = _content_words(intent)
    if len(words) < MIN_INTENT_CONTENT_WORDS:
        return _judging(
            UNMEASURED,
            checked=1,
            violations=0,
            unmeasured=1,
            note=(
                f"the intent carries {len(words)} content word(s), fewer than "
                f"{MIN_INTENT_CONTENT_WORDS}: there is nothing here to reorganise, "
                "which is not the same as a request this module refused"
            ),
            prompt=None,
        )
    unreadable = [w for w in words if _unpronounceable(w)]
    if len(unreadable) / len(words) >= GIBBERISH_SHARE:
        return _judging(
            UNMEASURED,
            checked=len(words),
            violations=0,
            unmeasured=1,
            note=(
                f"{len(unreadable)} of {len(words)} words are unpronounceable "
                f"({', '.join(unreadable[:5])}): there is no intent here to be "
                "faithful to. A prompt built from this would be entirely this "
                "module's invention, which is the failure the third outcome exists "
                "to prevent"
            ),
            prompt=None,
        )

    if not card.skeleton:
        return _judging(
            UNMEASURED,
            checked=1,
            violations=0,
            unmeasured=1,
            note=f"{card.model_id} has no documented prompt skeleton in the registry",
            prompt=None,
        )

    plain = deterministic(intent, card)
    if not plain["prompt"]:
        return _judging(
            UNMEASURED,
            checked=len(card.skeleton),
            violations=0,
            unmeasured=1,
            note=(
                f"no clause of the intent could be filed under any of "
                f"{card.model_id}'s slots {card.skeleton}"
            ),
            prompt=None,
            dropped=plain["dropped"] + plain["trimmed"],
        )

    if model is None:
        # The by-construction claim, checked rather than asserted. If this ever
        # fails it is a defect in THIS module, not in the user's request, and
        # the note says so instead of blaming the input.
        self_check = fidelity_audit(plain["prompt"], [intent])
        note = (
            f"{len(plain['slots'])} of {len(card.skeleton)} slots filled from the "
            f"user's own clauses, {len(plain['prompt'].split())} words"
        )
        if plain["trimmed"]:
            note += (
                f"; shortened under {SHORTEN_MAX_WORDS} words because {card.model_id} "
                f"expands the prompt internally, cutting {len(plain['trimmed'])} clause(s): "
                f"{'; '.join(plain['trimmed'])}"
            )
        if plain["dropped"]:
            note += (
                f"; {len(plain['dropped'])} clause(s) had no slot in "
                f"{card.model_id}'s skeleton: {'; '.join(plain['dropped'])}"
            )
        if self_check["outcome"] == FAIL:
            return _judging(
                FAIL,
                checked=self_check["checked"],
                violations=self_check["violations"],
                unmeasured=0,
                note=(
                    "the deterministic path emitted words the intent does not "
                    f"contain ({', '.join(self_check['invented'])}). That is a defect "
                    "in the rewriter, not in the request"
                ),
                prompt=plain["prompt"],
                dropped=plain["dropped"] + plain["trimmed"],
                invented=self_check["invented"],
            )
        return _judging(
            PASS,
            checked=self_check["checked"],
            violations=0,
            unmeasured=0,
            note=note,
            prompt=plain["prompt"],
            dropped=plain["dropped"] + plain["trimmed"],
        )

    rounds = 0
    last_invented: list[str] = []
    while rounds < MAX_ROUNDS:
        rounds += 1
        try:
            answer = str(model(build_prompt(intent, card, examples, invented_words=last_invented)))
        except Exception as exc:  # a model that raises is a model that did not answer
            return _judging(
                UNMEASURED,
                checked=0,
                violations=0,
                unmeasured=1,
                note=(
                    f"the model was asked and raised {type(exc).__name__}: {exc}. "
                    "The deterministic prompt is returned; nothing about the model's "
                    "output was measured"
                ),
                prompt=plain["prompt"],
                dropped=plain["dropped"] + plain["trimmed"],
                rounds=rounds,
            )
        answer = _MULTI_WS.sub(" ", answer).strip()
        if not answer:
            return _judging(
                UNMEASURED,
                checked=0,
                violations=0,
                unmeasured=1,
                note=(
                    "the model was asked and answered with nothing. The deterministic "
                    "prompt is returned; the model's output was not measured"
                ),
                prompt=plain["prompt"],
                dropped=plain["dropped"] + plain["trimmed"],
                rounds=rounds,
            )

        # `sources` is the user's intent ALONE. Not the examples, not the card's
        # quirks: a word is the user's or it is invented, and a precedent
        # containing it changes nothing about whose idea it was.
        checked_audit = fidelity_audit(answer, [intent])
        if checked_audit["outcome"] == PASS:
            return _judging(
                PASS,
                checked=checked_audit["checked"],
                violations=0,
                unmeasured=0,
                note=(
                    f"model rewrite accepted on round {rounds} of {MAX_ROUNDS}; "
                    f"{checked_audit['note']}"
                ),
                prompt=answer,
                # The card's own drops only. `trimmed` is the deterministic
                # path's shortening and was never applied to THIS prompt;
                # reporting it here would claim a cut nobody made.
                dropped=plain["dropped"],
                source=SOURCE_MODEL,
                rounds=rounds,
            )
        if checked_audit["outcome"] == UNMEASURED:
            return _judging(
                UNMEASURED,
                checked=checked_audit["checked"],
                violations=0,
                unmeasured=1,
                note=(
                    f"the model answered but the audit could not judge it: "
                    f"{checked_audit['note']}. The deterministic prompt is returned"
                ),
                prompt=plain["prompt"],
                dropped=plain["dropped"] + plain["trimmed"],
                rounds=rounds,
            )
        last_invented = list(checked_audit["invented"])

    return _judging(
        FAIL,
        checked=len(_content_words(intent)),
        violations=len(last_invented),
        unmeasured=0,
        note=(
            f"the model invented on all {rounds} round(s) — last time: "
            f"{', '.join(last_invented)}. Its output is discarded and the "
            "deterministic prompt is returned instead, because a refusal that "
            "leaves the user with nothing is worse than a plain prompt"
        ),
        prompt=plain["prompt"],
        dropped=plain["dropped"] + plain["trimmed"],
        invented=last_invented,
        source=SOURCE_MODEL_REJECTED,
        rounds=rounds,
    )
