"""Free user text -> StyleSpec -> a prompt assembled from a template that lives in code.

The model never writes the prompt. It fills a fixed structure; `build_prompt`
assembles the text. An injected instruction can at best change a field value
out of an allow-list — it cannot change what the prompt is made of, add an
instruction for the generator, or ask the generator for anything.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Any, Callable

from lipsync.fork_e2e import NO_BRANDS_CLAUSE
from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from lipsync.fork_style_prompt import subject_leak

__all__ = [
    "LIGHT_WORDS",
    "MOOD_WORDS",
    "PALETTE_WORDS",
    "SETTING_MAX",
    "StyleSpec",
    "TEXTURE_WORDS",
    "build_prompt",
    "extract",
    "gate_input",
    "sanitise_setting",
    "setting_violations",
]


# The allow-lists. Small on purpose: every word here has to survive the engine's
# style adapter, and a word nobody measured is a word nobody can defend.
PALETTE_WORDS: tuple[str, ...] = (
    "amber",
    "charcoal",
    "copper",
    "crimson",
    "emerald",
    "gold",
    "indigo",
    "ivory",
    "rose",
    "sand",
    "slate",
    "teal",
)

LIGHT_WORDS: tuple[str, ...] = (
    "backlit",
    "candlelit",
    "golden-hour",
    "hard",
    "high-key",
    "low-key",
    "neon",
    "overcast",
    "soft",
    "studio",
)

TEXTURE_WORDS: tuple[str, ...] = (
    "crisp",
    "film-grain",
    "glossy",
    "hazy",
    "matte",
    "metallic",
    "painterly",
    "smoky",
    "velvet",
    "watercolour",
)

MOOD_WORDS: tuple[str, ...] = (
    "calm",
    "dramatic",
    "dreamy",
    "elegant",
    "energetic",
    "melancholic",
    "mysterious",
    "nostalgic",
    "playful",
    "serene",
)

PALETTE_MIN = 1
PALETTE_MAX = 4

SETTING_MAX = 60

TEXT_MAX = 2000

# The only characters `setting` may carry into the prompt (CONTRACTS.md).
SETTING_KEEP = re.compile(r"[^A-Za-z0-9 ,-]+")

# The fields the model is allowed to fill. `refusal` is deliberately absent:
# refusing is a code decision, never a value the model (or an injection) supplies.
SPEC_FIELDS: tuple[str, ...] = ("palette", "light", "texture", "mood", "setting")

# Topics that are refused outright. Matched as whole words on the user's text and
# on `setting`, so the ban does not depend on the model being persuaded to obey.
ADULT_WORDS: tuple[str, ...] = (
    "erotic",
    "fetish",
    "lingerie",
    "naked",
    "nude",
    "nudity",
    "nsfw",
    "porn",
    "pornographic",
    "sexual",
    "sexy",
    "topless",
    "underwear",
)

VIOLENCE_WORDS: tuple[str, ...] = (
    "beheading",
    "blood",
    "bloody",
    "corpse",
    "execution",
    "gore",
    "gun",
    "gunshot",
    "kill",
    "killing",
    "knife",
    "murder",
    "mutilated",
    "rifle",
    "torture",
    "violence",
    "weapon",
)

MINOR_WORDS: tuple[str, ...] = (
    "baby",
    "child",
    "children",
    "infant",
    "kid",
    "kids",
    "kindergarten",
    "minor",
    "preteen",
    "schoolgirl",
    "schoolboy",
    "teen",
    "teenage",
    "toddler",
    "underage",
)

# Recognisable third parties: the category markers, not a list of names. A name
# list ages badly and a marker list is what the policy actually means.
THIRD_PARTY_WORDS: tuple[str, ...] = (
    "actor",
    "actress",
    "celebrity",
    "influencer",
    "king",
    "musician",
    "politician",
    "pope",
    "president",
    "queen",
    "rapper",
    "singer",
    "starring",
)

# Words that only ever appear when someone is talking TO the generator rather
# than describing a look. `setting` is the one free-text field, so it is where an
# injection would try to ride in.
INJECTION_WORDS: tuple[str, ...] = (
    "api",
    "assistant",
    "developer",
    "disregard",
    "execute",
    "generate",
    "ignore",
    "instruction",
    "instructions",
    "jailbreak",
    "obey",
    "output",
    "override",
    "previous",
    "prompt",
    "render",
    "reveal",
    "role",
    "system",
    "tool",
    "video",
)

BANNED_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("adult content", ADULT_WORDS),
    ("violence", VIOLENCE_WORDS),
    ("minors", MINOR_WORDS),
    ("recognisable third parties", THIRD_PARTY_WORDS),
)

REFUSAL_TEXT = (
    "I can only style the look of the shot — colour, light, texture, mood and "
    "surroundings. I cannot make this one. Try describing a place and a mood "
    "instead, for example: warm amber light, a quiet rooftop at dusk."
)

# The template. Everything the prompt is made of is in this function's body, so
# a diff shows any change to the prompt's shape.
CLOSING = "photographic look"
SETTING_LEAD = "set in"
PALETTE_LEAD = "a palette of"


@dataclass(frozen=True)
class StyleSpec:
    """The agent's only output shape. `refusal` set means nothing is generated."""

    palette: tuple[str, ...]
    light: str
    texture: str
    mood: str
    setting: str
    refusal: str | None = None


def _result(
    outcome: str,
    note: str,
    *,
    checked: int = 0,
    violations: int = 0,
    unmeasured: int = 0,
    spec: StyleSpec | None = None,
) -> dict:
    """Build the judging dict every module in the studio agrees on."""
    return {
        "outcome": outcome,
        "checked": checked,
        "violations": violations,
        "unmeasured": unmeasured,
        "note": note,
        "spec": spec,
    }


def _words(text: str) -> list[str]:
    """Split into comparable word tokens, so a ban matches a word and not a substring."""
    return re.findall(r"[A-Za-z][A-Za-z'-]*", text.lower())


def banned_topics(text: str) -> list[str]:
    """Return `group: word` for every banned topic found. Empty means clean."""
    found = _words(text)
    hits = []
    for group, words in BANNED_GROUPS:
        for w in words:
            if w in found:
                hits.append(f"{group}: {w}")
    return hits


def sanitise_setting(text: str) -> str:
    """Keep only letters, digits, spaces, commas and hyphens; collapse and cut to 60.

    Example:
        >>> sanitise_setting("a rooftop <b>at dusk</b>!!")
        'a rooftop b at dusk b'
    """
    kept = SETTING_KEEP.sub(" ", text)
    kept = re.sub(r"\s+", " ", kept).strip()
    return kept[:SETTING_MAX].strip()


def setting_violations(text: str) -> list[str]:
    """Return every reason `setting` may not go into a prompt. Empty means it may."""
    reasons = list(banned_topics(text))
    found = _words(text)
    reasons += [f"instruction to the generator: {w}" for w in INJECTION_WORDS if w in found]
    reasons += [f"subject word: {w}" for w in subject_leak(text)]
    if len(text) > SETTING_MAX:
        reasons.append(f"setting is {len(text)} chars, the cap is {SETTING_MAX}")
    if sanitise_setting(text) != text:
        reasons.append("setting carries characters outside the allowed alphabet")
    return reasons


def refusal_spec(reason: str) -> StyleSpec:
    """A spec that generates nothing. Values are placeholders; `refusal` is the payload."""
    return StyleSpec(
        palette=(PALETTE_WORDS[0],),
        light=LIGHT_WORDS[0],
        texture=TEXTURE_WORDS[0],
        mood=MOOD_WORDS[0],
        setting="",
        refusal=f"{REFUSAL_TEXT} [{reason}]",
    )


SYSTEM_INSTRUCTION = (
    "You fill a JSON structure that describes the LOOK of a photograph. "
    "Return strict JSON and nothing else, with exactly these keys: "
    f"palette (a list of {PALETTE_MIN}-{PALETTE_MAX} words from {list(PALETTE_WORDS)}), "
    f"light (one of {list(LIGHT_WORDS)}), "
    f"texture (one of {list(TEXTURE_WORDS)}), "
    f"mood (one of {list(MOOD_WORDS)}), "
    f"setting (free text, at most {SETTING_MAX} characters, describing the "
    "surroundings only). Never describe a person, clothing, a pose or an action. "
    "Use only the words listed; do not invent values."
)


def _live_model(request: str) -> str:
    """Ask the real model. Imported lazily so importing this module touches no network."""
    from lipsync.pollinations import chat  # noqa: PLC0415

    return chat(
        [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": request},
        ]
    )


def extract(text: str, *, model: Callable[[str], str] | None = None) -> dict:
    """Turn free user text into a StyleSpec. `model` is the injection point.

    Args:
        text: what the user typed, in any language.
        model: a callable taking the request string and returning the model's raw
            answer. `None` calls the live gateway; tests pass a stub.

    Returns:
        The judging dict; `spec` is None unless a spec was produced. A spec with
        `refusal` set is returned with outcome FAIL: it is shown, not generated.

    Example:
        >>> out = extract("warm gold light on a rooftop", model=lambda _: '{"palette": ["gold"], "light": "golden-hour", "texture": "film-grain", "mood": "calm", "setting": "a rooftop at dusk"}')
        >>> out["outcome"], out["spec"].setting
        ('pass', 'a rooftop at dusk')
    """
    if not isinstance(text, str) or not text.strip():
        return _result(UNMEASURED, "no text was given: nothing to read", unmeasured=1)
    if len(text) > TEXT_MAX:
        return _result(
            FAIL,
            f"the text is {len(text)} chars, the cap is {TEXT_MAX}",
            checked=1,
            violations=1,
        )

    # Cheapest check first, and before any money is spent on the model.
    hits = banned_topics(text)
    if hits:
        return _result(
            FAIL,
            f"the request asks for a banned topic ({', '.join(hits)}): refused, nothing generated",
            checked=1,
            violations=1,
            spec=refusal_spec(", ".join(hits)),
        )

    caller = _live_model if model is None else model
    try:
        raw = caller(text)
    except Exception as exc:  # noqa: BLE001 - any model failure is "could not measure"
        return _result(
            UNMEASURED,
            f"the model did not answer: {type(exc).__name__}: {exc}",
            unmeasured=1,
        )
    if not isinstance(raw, str):
        return _result(
            UNMEASURED,
            f"the model returned {type(raw).__name__}, not text: nothing to parse",
            unmeasured=1,
        )
    try:
        data: Any = json.loads(raw)
    except (ValueError, TypeError) as exc:
        return _result(
            UNMEASURED,
            f"the model's answer is not JSON ({exc}): NOT READ, which is not 'no style'",
            unmeasured=1,
        )
    if not isinstance(data, dict):
        return _result(
            UNMEASURED,
            f"the model returned a JSON {type(data).__name__}, not an object: NOT READ",
            unmeasured=1,
        )

    keys = set(data)
    missing = sorted(set(SPEC_FIELDS) - keys)
    extra = sorted(keys - set(SPEC_FIELDS))
    if missing or extra:
        return _result(
            FAIL,
            f"fields do not match the contract: missing {missing}, unexpected {extra}",
            checked=1,
            violations=1,
        )

    problems: list[str] = []
    palette_raw = data["palette"]
    if isinstance(palette_raw, str):
        palette_raw = [palette_raw]
    if not isinstance(palette_raw, (list, tuple)):
        problems.append(f"palette is {type(data['palette']).__name__}, expected a list")
        palette: tuple[str, ...] = ()
    else:
        palette = tuple(str(c).strip().lower() for c in palette_raw)
        if not PALETTE_MIN <= len(palette) <= PALETTE_MAX:
            problems.append(
                f"palette has {len(palette)} words, the band is {PALETTE_MIN}..{PALETTE_MAX}"
            )
        problems += [
            f"palette word {c!r} is outside the allow-list"
            for c in palette
            if c not in PALETTE_WORDS
        ]

    scalars = {}
    for field, allowed in (
        ("light", LIGHT_WORDS),
        ("texture", TEXTURE_WORDS),
        ("mood", MOOD_WORDS),
    ):
        value = data[field]
        if not isinstance(value, str):
            problems.append(f"{field} is {type(value).__name__}, expected a string")
            scalars[field] = allowed[0]
            continue
        value = value.strip().lower()
        if value not in allowed:
            # No nearest-neighbour substitution: a wrong value is a wrong value.
            problems.append(f"{field} {value!r} is outside the allow-list {list(allowed)}")
        scalars[field] = value

    setting_raw = data["setting"]
    if not isinstance(setting_raw, str):
        problems.append(f"setting is {type(setting_raw).__name__}, expected a string")
        setting_raw = ""
    setting = sanitise_setting(setting_raw)
    stripped = setting != setting_raw
    bad_setting = setting_violations(setting)
    problems += [f"setting rejected — {r}" for r in bad_setting]

    if problems:
        spec = refusal_spec("; ".join(bad_setting)) if bad_setting else None
        return _result(
            FAIL,
            "the model's answer breaks the contract: " + "; ".join(problems),
            checked=len(SPEC_FIELDS),
            violations=len(problems),
            spec=spec,
        )

    spec = StyleSpec(
        palette=palette,
        light=scalars["light"],
        texture=scalars["texture"],
        mood=scalars["mood"],
        setting=setting,
        refusal=None,
    )
    note = f"checked {len(SPEC_FIELDS)} fields against the allow-lists, 0 violations"
    if stripped:
        note += f"; setting was sanitised to {setting!r}"
    return _result(PASS, note, checked=len(SPEC_FIELDS), violations=0, spec=spec)


# Each rule must fire for the input to be allowed. Nothing is allowed by default:
# the verdict starts at Denied and only a full sweep of firing rules flips it.
def _rule_refusal(spec: StyleSpec) -> str | None:
    return None if spec.refusal is None else "the spec carries a refusal: nothing is generated"


def _rule_palette(spec: StyleSpec) -> str | None:
    if not isinstance(spec.palette, tuple):
        return f"palette is {type(spec.palette).__name__}, expected a tuple"
    if not PALETTE_MIN <= len(spec.palette) <= PALETTE_MAX:
        return f"palette has {len(spec.palette)} words, the band is {PALETTE_MIN}..{PALETTE_MAX}"
    outside = [c for c in spec.palette if c not in PALETTE_WORDS]
    return f"palette words outside the allow-list: {outside}" if outside else None


def _rule_light(spec: StyleSpec) -> str | None:
    return None if spec.light in LIGHT_WORDS else f"light {spec.light!r} is outside the allow-list"


def _rule_texture(spec: StyleSpec) -> str | None:
    if spec.texture in TEXTURE_WORDS:
        return None
    return f"texture {spec.texture!r} is outside the allow-list"


def _rule_mood(spec: StyleSpec) -> str | None:
    return None if spec.mood in MOOD_WORDS else f"mood {spec.mood!r} is outside the allow-list"


def _rule_setting(spec: StyleSpec) -> str | None:
    if not isinstance(spec.setting, str):
        return f"setting is {type(spec.setting).__name__}, expected a string"
    bad = setting_violations(spec.setting)
    return "; ".join(bad) if bad else None


GATE_RULES: tuple[tuple[str, Callable[[StyleSpec], str | None]], ...] = (
    ("refusal", _rule_refusal),
    ("palette", _rule_palette),
    ("light", _rule_light),
    ("texture", _rule_texture),
    ("mood", _rule_mood),
    ("setting", _rule_setting),
)


def gate_input(spec: StyleSpec) -> dict:
    """Judge a spec on its STRUCTURE, not on its prose. Default deny.

    Args:
        spec: the structure to judge.

    Returns:
        The judging dict. PASS only when every rule fired clean and at least one
        rule ran; anything else is Denied (FAIL) or NOT JUDGED (UNMEASURED).

    Example:
        >>> gate_input(StyleSpec(("teal",), "soft", "matte", "calm", "a quiet rooftop"))["outcome"]
        'pass'
    """
    if not isinstance(spec, StyleSpec):
        return _result(
            UNMEASURED,
            f"got {type(spec).__name__}, not a StyleSpec: NOT JUDGED, which is not 'allowed'",
            unmeasured=1,
        )
    denials = []
    for name, rule in GATE_RULES:
        reason = rule(spec)
        if reason is not None:
            denials.append(f"{name}: {reason}")
    checked = len(GATE_RULES)
    if checked == 0:
        # Zero checks is never PASS: a gate that judged nothing allowed nothing.
        return _result(UNMEASURED, "no rule ran: the gate judged nothing", unmeasured=1)
    if denials:
        return _result(
            FAIL,
            f"Denied — checked {checked}, violations {len(denials)}: " + "; ".join(denials),
            checked=checked,
            violations=len(denials),
            spec=spec,
        )
    return _result(
        PASS,
        f"Allowed — checked {checked}, violations 0: every allow-rule fired",
        checked=checked,
        violations=0,
        spec=spec,
    )


def build_prompt(spec: StyleSpec) -> str:
    """Assemble the generation prompt from the template below. The template is code.

    Args:
        spec: a gated spec. A spec the gate would deny raises instead of building.

    Returns:
        The prompt string: palette, light, texture, mood, setting, closing, brand ban.

    Example:
        >>> build_prompt(StyleSpec(("teal", "gold"), "soft", "matte", "calm", "a rooftop"))
        'a palette of teal and gold, soft light, matte texture, calm mood, set in a rooftop, photographic look, no logo, no logos, no brand marks, no lettering or text anywhere in the frame or on clothing'
    """
    gate = gate_input(spec)
    if gate["outcome"] != PASS:
        raise ValueError(f"build_prompt refused the spec — {gate['note']}")

    colours = list(spec.palette)
    palette = (
        PALETTE_LEAD
        + " "
        + (", ".join(colours[:-1]) + " and " + colours[-1] if len(colours) > 1 else colours[0])
    )
    parts = [
        palette,
        f"{spec.light} light",
        f"{spec.texture} texture",
        f"{spec.mood} mood",
    ]
    if spec.setting:
        parts.append(f"{SETTING_LEAD} {spec.setting}")
    parts += [CLOSING, NO_BRANDS_CLAUSE]
    prompt = ", ".join(parts)

    # The engine's product limit: style describes the look, never the subject —
    # the person, the clothing and the pose come from the client photo and the
    # driving clip. `subject_leak` is the engine's own definition of that limit.
    leak = [w for w in subject_leak(prompt) if w not in subject_leak(NO_BRANDS_CLAUSE)]
    if leak:
        raise ValueError(f"the assembled prompt touched the subject zone {leak}: not shipped")
    return prompt


def with_refusal(spec: StyleSpec, reason: str) -> StyleSpec:
    """Return the same spec marked refused, so callers never mutate a frozen spec."""
    return replace(spec, refusal=f"{REFUSAL_TEXT} [{reason}]")
