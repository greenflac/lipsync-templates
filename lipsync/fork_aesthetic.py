"""Aesthetic: the template author's step. A prompt plus the demo identity -> an aesthetic."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .fork_identity import FAIL, PASS, SAME_PERSON_MAX, UNMEASURED
from . import clauses, fork_plan

BASE_PATH = Path(__file__).resolve().parent.parent / "assets" / "fork_aesthetics.json"

IDENTITY_CLAUSE = (
    "the person in the frame is the person from the input image: same face, "
    "same facial features, same skin tone and same hair colour; where the "
    "description above names a different appearance, the input image wins on "
    "identity and the description applies only to wardrobe, hairstyling, "
    "setting, lens, lighting, pose and mood"
)


ANTHROPOMETRY_CLAUSES = (
    r"\bhas\b[^,]*\bskin\b",
    r"\b\w+ skin with\b",
    r"\bflawless skin\b",
    r"\bfreckles?\b",
    r"\bcomplexion\b",
    r"\b(green|blue|brown|hazel|grey|gray|dark|light|piercing) eyes\b",
    r"\bfacial features?\b",
    r"\bcheekbones?\b",
    r"\bjawline\b",
    r"\bbody type\b",
    r"\bphysique\b",
)

#: An optional intensifier carries its own separator INSIDE the group
#: (`(?:very\s+)?word`), never beside it (`(?:very)?\s*word`): the second
#: shape matches the space in FRONT of the word whenever the group matches
#: empty, and the cut then welds the article to the noun. MEASURED
#: 01.09.2026: "a beautiful woman standing in the room" came back as
#: "Awoman standing in the room", the word boundary was gone, the gender
#: swap below never fired, and the report still said genders=[] pass.
ANTHROPOMETRY_WORDS = (
    r"\b(?:(?:extremely|very|incredibly|stunningly|exceptionally)\s+)?beautiful\b",
    r"\bsupermodel-level\b",
    r"\bsupermodel\b",
    r"\bbeauty\b",
    r"\b(?:(?:extremely|very)\s+)?(?:gorgeous|stunning|attractive|pretty)\b",
    r"\bbrunette\b",
    r"\bblonde?\b",
    r"\bplatinum\b",
    r"\bginger\b",
    r"\bauburn\b",
    r"\bredhead\b",
    r"\b(?:red|dark|fair)-haired\b",
    r"\btanned\b",
    r"\b(?:olive|pale|fair)-skinned\b",
    r"\bslavic\b",
    r"\bnordic\b",
    r"\bscandinavian\b",
    r"\basian\b",
    r"\bafrican\b",
    r"\blatina\b",
    r"\bcaucasian\b",
    r"\bslim\b",
    r"\bcurvy\b",
    r"\bpetite\b",
    r"\bathletic\b",
)

GENDER_SWAPS = (
    ("women", "people"),
    ("woman", "person"),
    ("men", "people"),
    ("man", "person"),
    ("girl", "person"),
    ("boy", "person"),
    ("lady", "person"),
    ("female", "person"),
    ("male", "person"),
    ("herself", "themselves"),
    ("himself", "themselves"),
    ("hers", "theirs"),
    ("her", "their"),
    ("his", "their"),
    ("she", "they"),
    ("he", "they"),
)


def _clause_is_anthropometric(clause: str) -> str | None:
    """Return the pattern that marked the clause as describing a person, or None."""
    for pattern in ANTHROPOMETRY_CLAUSES:
        if re.search(pattern, clause, re.IGNORECASE):
            return pattern
    return None


def strip_anthropometry(prompt: str) -> dict:
    """Strip everything that describes the person from the prompt, keeping everything about the frame."""
    if not isinstance(prompt, str) or not prompt.strip():
        return {
            **tally(0, 0, 1),
            "prompt": None,
            "dropped": [],
            "words": [],
            "genders": [],
            "cut_share": None,
            "note": "no prompt: nothing to cut",
        }

    kept, dropped = [], []
    for clause in prompt.split(","):
        hit = _clause_is_anthropometric(clause)
        if hit:
            dropped.append({"clause": clause.strip(), "pattern": hit})
        else:
            kept.append(clause)
    text = ",".join(kept)

    words: list[dict] = []
    for pattern in ANTHROPOMETRY_WORDS:
        text, n = re.subn(pattern + r"\s*", "", text, flags=re.IGNORECASE)
        if n:
            words.append({"pattern": pattern, "times": n})

    genders: list[dict] = []
    for src, dst in GENDER_SWAPS:
        text, n = re.subn(rf"\b{re.escape(src)}\b", dst, text, flags=re.IGNORECASE)
        if n:
            genders.append({"from": src, "to": dst, "times": n})

    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r"(,\s*){2,}", ", ", text).strip().strip(",").strip()
    text = re.sub(r"\ban\s+(?=[^aeiouAEIOU\s])", "a ", text)
    text = re.sub(r"\ba\s+(?=[aeiouAEIOU])", "an ", text)
    text = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)

    return {
        **tally(1, 0, 0),
        "prompt": text,
        "dropped": dropped,
        "words": words,
        "genders": genders,
        "cut_share": round(1 - len(text.split()) / len(prompt.split()), 4),
        "note": (
            f"clauses removed {len(dropped)}, body words "
            f"{sum(w['times'] for w in words)}, gender swaps "
            f"{sum(g['times'] for g in genders)}; words before "
            f"{len(prompt.split())}, after {len(text.split())}"
        ),
    }


#: CHOSEN (owner's decision, 22.08): the project's two demo identities, one per
#: declared gender, both already framed to the universal 9:16 plan. Gender is
#: declared and not classified — a classifier is one more instrument to measure
#: and guard, and it would be wrong on live clients — so these keys double as
#: the gender vocabulary `pair_check` holds the pairs to. Paid for by eye: a
#: male client built with the female y2k aesthetic came back in a mini skirt
#: while identity, leak, lettering and plan were all green.
DEMOS = {
    "m": "assets/fork_plan_man_fullbody.png",
    "f": "assets/fork_plan_woman_fullbody.png",
}

GENDERS = tuple(DEMOS)

AESTHETIC_DIR = Path("assets") / "aesthetics"


def demo_for(gender: str):
    """Return the demo identity for a gender. An unknown gender is an exception, not a default."""
    key = str(gender).strip().lower()
    if key not in DEMOS:
        raise KeyError(f"gender {gender!r} is not in {GENDERS}")
    return DEMOS[key]


def gender_of(aesthetic) -> str:
    """Return the template's gender, which by the template author's decision is also the aesthetic's gender."""
    if isinstance(aesthetic, str):
        aesthetic = load(aesthetic)
    got = (aesthetic or {}).get("demo")
    if str(got).strip().lower() not in DEMOS:
        raise KeyError(
            f"the aesthetic {(aesthetic or {}).get('id')!r} does not name "
            f"a gender (field 'demo' from {GENDERS}), got {got!r}"
        )
    return str(got).strip().lower()


def aesthetic_file(aesthetic_id: str, gender: str | None = None, *, root=None) -> Path:
    """Return the aesthetic's path. The gender lives in the file name, not only in the base, so the name travels with the file."""
    g = gender_of(aesthetic_id) if gender is None else str(gender).strip().lower()
    demo_for(g)
    base = AESTHETIC_DIR if root is None else Path(root)
    return base / f"{aesthetic_id}_{g}.png"


#: CHOSEN (owner's contract 01.09.2026, decisions 3 and 4): what an aesthetic
#: must carry before it can take a client order. The driving and its window are
#: decision 4 — the aesthetic keeps its OWN copy of the driving in the
#: repository, because a driving that lives anywhere else is a driving that
#: changes under the aesthetic that was proven on it. The card is decision 3 —
#: the client frame is judged against the card taken from this aesthetic's own
#: demo, and the global plan bands are explicitly not applied to aesthetics.
#: `trial` is deliberately NOT in this tuple: decision 5 makes the paid trial a
#: condition of PUBLISHING an aesthetic, and once it is published the trial is
#: provenance of the build, not something a client order reads.
ORDER_FIELDS = ("driving", "window", "card")

#: DERIVED from `fork_plan.PERSON_AXES`: a card carries one median and one
#: tolerance per axis the plan measures. Imported rather than restated so that
#: an axis added to the plan cannot go silently missing from every card here.
CARD_AXES = fork_plan.PERSON_AXES

DRIVING_DIR = Path("assets") / "drivings"

TRIAL_DIR = Path("docs") / "trials"


def _resolve(aesthetic, path=None) -> dict:
    """Return the aesthetic as a dict, loading it from the base when a name was given."""
    if isinstance(aesthetic, str):
        return load(aesthetic, path)
    if isinstance(aesthetic, dict):
        return aesthetic
    raise TypeError(
        f"an aesthetic is a name or a dict, got {type(aesthetic).__name__}: {aesthetic!r}"
    )


def _missing(got: dict, name: str) -> bool:
    """Say whether the field is absent or empty. An empty field is an absent field, not a value."""
    return got.get(name) in (None, "", [], {}, ())


def _window_fault(value) -> str | None:
    """Return why the window is unusable, or None. One reader, two callers: the accessor and the gate."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return f"a window is [first, last], two frame numbers, got {value!r}"
    first, last = value
    if not all(isinstance(n, int) and not isinstance(n, bool) for n in (first, last)):
        return f"frame numbers are whole numbers, got {value!r}"
    if first < 0:
        return f"the first frame {first} is before the start of the driving"
    if first > last:
        return f"the first frame {first} is after the last {last}"
    return None


def _card_fault(value) -> str | None:
    """Return why the card is unusable, or None. Checks every axis, and says how many were missing."""
    if not isinstance(value, dict):
        return f"a card is an object with {len(CARD_AXES)} axes and their tolerances, got {value!r}"
    tolerances = value.get("tolerances")
    if not isinstance(tolerances, dict):
        return f"the card carries no 'tolerances' object, got {tolerances!r}"
    absent = [a for a in CARD_AXES if not isinstance(value.get(a), (int, float))]
    no_tol = [a for a in CARD_AXES if not isinstance(tolerances.get(a), (int, float))]
    if absent or no_tol:
        return (
            f"of {len(CARD_AXES)} axes {len(absent)} carry no median {absent} "
            f"and {len(no_tol)} carry no tolerance {no_tol}"
        )
    return None


def _demand(aesthetic, name: str, path=None):
    """Return one required field, or raise naming the aesthetic and what an order needs."""
    got = _resolve(aesthetic, path)
    if _missing(got, name):
        raise KeyError(
            f"the aesthetic {got.get('id')!r} carries no {name!r}. An aesthetic "
            f"without {' and '.join(ORDER_FIELDS)} is NOT ready for an order; "
            f"ask order_ready() for the verdict with its numbers instead of "
            f"guessing a default here"
        )
    return got[name]


def driving_of(aesthetic, path=None, *, root=None) -> Path:
    """Return the aesthetic's own copy of the driving. A missing driving is an exception, not a default.

    `aesthetic` is a name or the loaded dict; `root` prefixes the stored
    repository-relative path, for reading a base that is not the shipped one.

    >>> driving_of({"id": "ramp", "driving": "assets/drivings/ramp_f.mp4"})
    PosixPath('assets/drivings/ramp_f.mp4')
    """
    got = Path(str(_demand(aesthetic, "driving", path)))
    return got if root is None else Path(root) / got


def window_of(aesthetic, path=None) -> tuple[int, int]:
    """Return the aesthetic's driving window as (first, last) frame numbers, both inclusive.

    `aesthetic` is a name or the loaded dict. A window that is not two ordered
    frame numbers is an exception: cutting by time is forbidden on this project.

    >>> window_of({"id": "ramp", "window": [150, 299]})
    (150, 299)
    """
    got = _demand(aesthetic, "window", path)
    fault = _window_fault(got)
    if fault:
        raise ValueError(
            f"the aesthetic {_resolve(aesthetic, path).get('id')!r} has a broken window: {fault}"
        )
    return int(got[0]), int(got[1])


def card_of(aesthetic, path=None) -> dict:
    """Return the aesthetic's composition card in the nested form the contract declares.

    The contract of 01.09 declares ONE shape for a card — the four axes beside
    a `tolerances` object — and this returns that shape, validated, so the
    declared form and the stored form cannot drift apart. `fork_plan.in_card`
    reads a flat `tol_<axis>` instead, and the caller that hands the card to
    the plan converts it; the conversion is deliberately not done here, because
    the contract's shape is what every reader of the base is promised.

    `aesthetic` is a name or the loaded dict. A card that is missing an axis or
    a tolerance is an exception, not a card with holes in it.

    >>> card_of({"id": "ramp", "card": {"shoulders": 0.53, "ankles": 0.92,
    ...     "centre": 0.53, "width": 0.31, "tolerances": {"shoulders": 0.05,
    ...     "ankles": 0.05, "centre": 0.1837, "width": 0.1326}}})["tolerances"]["centre"]
    0.1837
    """
    got = _demand(aesthetic, "card", path)
    fault = _card_fault(got)
    if fault:
        raise ValueError(
            f"the aesthetic {_resolve(aesthetic, path).get('id')!r} has a broken card: {fault}"
        )
    return {
        **{axis: float(got[axis]) for axis in CARD_AXES},
        "tolerances": {axis: float(got["tolerances"][axis]) for axis in CARD_AXES},
    }


def trial_of(aesthetic, path=None, *, root=None) -> Path:
    """Return the paid trial clip the aesthetic was signed off on. Absent is an exception, not a default.

    `aesthetic` is a name or the loaded dict; `root` prefixes the stored path.

    >>> trial_of({"id": "ramp", "trial": "docs/trials/ramp_f.mp4"})
    PosixPath('docs/trials/ramp_f.mp4')
    """
    got = Path(str(_demand(aesthetic, "trial", path)))
    return got if root is None else Path(root) / got


def order_ready(aesthetic, path=None) -> dict:
    """Check that an aesthetic carries everything a client order needs. A gate, with its numbers.

    Three outcomes: a pass, a fail listing what is missing or broken, and
    `could not measure` when the aesthetic itself could not be read — that last
    one is not permission to continue, and it is not folded into either of the
    other two.

    `aesthetic` is a name or the loaded dict.

    >>> order_ready({"id": "y2k", "demo": "f"})["outcome"]
    'fail'
    """
    try:
        got = _resolve(aesthetic, path)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        return {
            **tally(0, 0, 1),
            "missing": list(ORDER_FIELDS),
            "broken": [],
            "note": (
                f"the aesthetic could not be read, so NOTHING of the "
                f"{len(ORDER_FIELDS)} fields was checked: {exc}. This is NOT "
                f"permission to continue"
            ),
        }

    faults = {"window": _window_fault, "card": _card_fault}
    missing, broken = [], []
    for name in ORDER_FIELDS:
        if _missing(got, name):
            missing.append(name)
            continue
        fault = faults.get(name, lambda _v: None)(got[name])
        if fault:
            broken.append(f"{name}: {fault}")

    checked = len(ORDER_FIELDS)
    violations = len(missing) + len(broken)
    head = f"checked {checked}, missing {len(missing)}, broken {len(broken)}"
    if not violations:
        return {
            **tally(checked, 0, 0),
            "missing": [],
            "broken": [],
            "note": f"{head}: the aesthetic {got.get('id')!r} is ready for an order",
        }
    return {
        **tally(checked, violations, 0),
        "missing": missing,
        "broken": broken,
        "note": (
            f"{head}: the aesthetic {got.get('id')!r} is NOT ready for an "
            f"order — missing {missing or 'nothing'}, broken "
            f"{broken or 'nothing'}. The six aesthetics shipped before the "
            f"contract of 01.09 carry none of these fields, and they read as "
            f"not ready ON PURPOSE rather than being filled with placeholders"
        ),
    }


def pair_check(*, client_gender: str, aesthetic_gender: str) -> dict:
    """Check that the client's gender and the aesthetic's gender match. A gate, not advice."""

    def known(value):
        return str(value).strip().lower() if str(value).strip().lower() in DEMOS else None

    c, a = known(client_gender), known(aesthetic_gender)
    if c is None or a is None:
        return {
            **tally(0, 0, 1),
            "client": c,
            "aesthetic": a,
            "note": (
                f"gender not named or not in {GENDERS}: client "
                f"{client_gender!r}, aesthetic {aesthetic_gender!r}. "
                f"This is NOT permission to continue"
            ),
        }
    if c != a:
        return {
            **tally(1, 1, 0),
            "client": c,
            "aesthetic": a,
            "note": (
                f"GENDER MISMATCH: client {c}, aesthetic {a}. MEASURED "
                f"how this ends: a male client with a female "
                f"aesthetic got a women's mini skirt, and no "
                f"instrument saw it"
            ),
        }
    return {**tally(1, 0, 0), "client": c, "aesthetic": a, "note": f"genders match: {c}"}


AESTHETIC_ROLE_CLAUSE = (
    "keep the FACE and identity of the person from the FIRST image completely "
    "unchanged — same face, same facial features, same skin tone, same hair "
    "colour, same body; take the wardrobe, styling, accessories, hairstyling, "
    "pose, framing, lens, lighting, colour grade and setting from the SECOND "
    "image"
)

NEVER_THE_FACE_CLAUSE = (
    "never copy the face, facial features or identity of the person in the "
    "SECOND image; that person is a wardrobe and styling reference only, and "
    "must not appear in the result"
)


def assemble_prompt(*, legacy: bool = False, card=None) -> str:
    """Build the reference-assembly prompt. `legacy=True` gives the old stand lines."""
    if legacy:
        return f"{clauses.ROLE_CLAUSE}. {clauses.NO_LOOK_TRANSFER_CLAUSE}. {no_brands_clause()}"
    framing = framing_clause(card)
    tail = f" {framing}." if framing else ""
    return f"{AESTHETIC_ROLE_CLAUSE}. {NEVER_THE_FACE_CLAUSE}.{tail} {no_brands_clause()}"


# Empty since 2026-09-01: `leak_verdict` left this list on the day it gained a
# production caller. The aesthetic builder runs it at stage 4, so the claim that
# it never reaches the paid path stopped being true, and a stale declaration here
# is a gate voting for itself. The reasoning below is why the measurement exists,
# not a claim about who calls it.
#
# `accept` — the axis the pipeline does run — asks one question: is the demo
# identity still on the aesthetic? One distance cannot answer the question that
# actually costs money. A similarity measure can say "close", it cannot say
# "close to THIS person rather than THAT one", so a reference carrying the
# DEMO's face instead of the client's reads as a pass on that axis. Measuring
# both distances and looking at their difference is the only way to see it, and
# a stranger in the client's clip is the most expensive defect this repository
# can ship.
INSTRUMENTS: tuple[str, ...] = ()


def leak_verdict(*, made, client, demo, distances=None) -> dict:
    """Measure from both sides: who is on the assembled reference — the client or the demo."""
    t0 = time.perf_counter()
    if distances is None:
        from . import fork_identity  # noqa: PLC0415

        distances = fork_identity.distances
    out: dict = {"seconds": None, "to_client": None, "to_demo": None, "gap": None}
    try:
        c = distances([str(made)], str(client))
        d = distances([str(made)], str(demo))
    except Exception as exc:  # noqa: BLE001
        return {**tally(0, 0, 1), **out, "note": f"instrument crashed: {type(exc).__name__}: {exc}"}
    to_client, to_demo = c.get("median"), d.get("median")
    out.update(
        {"to_client": to_client, "to_demo": to_demo, "seconds": round(time.perf_counter() - t0, 3)}
    )
    if to_client is None or to_demo is None:
        return {
            **tally(0, 0, 1),
            **out,
            "note": (
                f"one of the distances was not taken: to client {to_client}, to demo {to_demo}"
            ),
        }
    gap = round(to_demo - to_client, 4)
    out["gap"] = gap
    tail = (
        f"to client {to_client}, to demo {to_demo}, gap {gap} "
        f"(the 'same person' bar {SAME_PERSON_MAX})"
    )
    if to_demo < to_client:
        return {
            **tally(1, 1, 0),
            **out,
            "note": f"IDENTITY LEAKED: the demo is CLOSER than the client; {tail}",
        }
    if to_client <= SAME_PERSON_MAX < to_demo:
        return {
            **tally(1, 0, 0),
            **out,
            "note": f"the client is in place, the demo did not leak; {tail}",
        }
    return {
        **tally(0, 0, 1),
        **out,
        "note": (
            f"the instrument cannot tell: neither distance sits on "
            f"opposite sides of the bar; {tail}. THE OPERATOR JUDGES BY EYE"
        ),
    }


PLAN_NOTE = (
    "the 9:16 plan is NOT REQUIRED on the aesthetic: the plan is imposed "
    "on the assembled client reference, and the aesthetic carries the "
    "look, not the frame"
)


def tally(checked: int, violations: int, unmeasured: int) -> dict:
    """Return the numbers next to the verdict."""
    if checked == 0:
        outcome = UNMEASURED
    elif violations:
        outcome = FAIL
    elif unmeasured:
        outcome = UNMEASURED
    else:
        outcome = PASS
    return {
        "outcome": outcome,
        "checked": checked,
        "violations": violations,
        "unmeasured": unmeasured,
    }


def load_base(path=None) -> dict:
    """Load the aesthetics base from disk. A missing file is an exception, not an empty base."""
    p = Path(BASE_PATH if path is None else path)
    if not p.is_file():
        raise FileNotFoundError(f"aesthetics base missing: {p}")
    doc = json.loads(p.read_text(encoding="utf-8"))
    got = doc.get("aesthetics")
    if not isinstance(got, list) or not got:
        raise ValueError(f"the base {p} holds no aesthetics")
    return doc


def ids(path=None) -> list:
    return [a["id"] for a in load_base(path)["aesthetics"]]


def load(aesthetic_id: str, path=None) -> dict:
    """Return one aesthetic by name. An unknown name is an exception listing what exists."""
    for a in load_base(path)["aesthetics"]:
        if a["id"] == aesthetic_id:
            return a
    raise KeyError(f"no aesthetic {aesthetic_id!r}; have: {', '.join(ids(path))}")


def brand_conflict(aesthetic: dict) -> dict:
    """List the brands named in the prompt. A reference note, not a gate."""
    text = str(aesthetic.get("prompt", ""))
    hits = [
        w
        for w in ("Adidas", "Balenciaga", "Nike", "Gucci", "Prada", "Zara", "Levi's", "Chanel")
        if w.lower() in text.lower()
    ]
    if not hits:
        return {**tally(1, 0, 0), "brands": [], "note": "no brands named in the prompt"}
    return {
        **tally(1, 0, 0),
        "brands": hits,
        "note": (
            f"the prompt names brands {hits} — ALLOWED by the template "
            f"author's decision; only a drawn mark is forbidden, and its "
            f"absence is JUDGED BY EYE: there is no instrument for lettering"
        ),
    }


def no_brands_clause() -> str:
    """Return the lettering ban from its single source per project."""
    return clauses.NO_BRANDS_CLAUSE


def framing_clause(card) -> str:
    """Return the framing line built from the driving card."""
    return fork_plan.framing_clause(card)


def compose(aesthetic, *, with_ban: bool = True, cut_body: bool = True, card=None) -> dict:
    """Build the aesthetic prompt: the template author's material plus the identity-conflict resolution."""
    if isinstance(aesthetic, str):
        aesthetic = load(aesthetic)
    if not isinstance(aesthetic, dict) or not aesthetic.get("prompt"):
        return {
            **tally(0, 0, 1),
            "prompt": None,
            "note": "aesthetic without a prompt: nothing to assemble",
        }
    own = aesthetic["prompt"].strip()
    cut = strip_anthropometry(own) if cut_body else None
    body = cut["prompt"] if cut and cut["outcome"] == PASS else own

    parts = [body, IDENTITY_CLAUSE]
    framing = framing_clause(card)
    if framing:
        parts.append(framing)
    if with_ban:
        parts.append(no_brands_clause())
    text = ". ".join(parts)
    how = (
        "the template author's prompt without anthropometry"
        if cut_body
        else "the template author's prompt VERBATIM (CUT DISABLED EXPLICITLY)"
    )
    return {
        **tally(1, 0, 0),
        "prompt": text,
        "id": aesthetic.get("id"),
        "kind": aesthetic.get("kind"),
        "words": len(text.split()),
        "cut": cut,
        "framed": bool(framing),
        "brand_conflict": brand_conflict(aesthetic),
        "note": (
            f"aesthetic {aesthetic.get('id')}: words {len(text.split())}, "
            f"{how} + identity"
            + ("" if with_ban else " (LETTERING BAN DISABLED EXPLICITLY)")
            + (f"; {cut['note']}" if cut else "")
        ),
    }


def accept(*, made, demo, distances=None) -> dict:
    """Check whether the demo identity survived on the aesthetic. The only measurable axis."""
    t0 = time.perf_counter()
    if distances is None:
        from . import fork_identity  # noqa: PLC0415

        distances = fork_identity.distances
    try:
        d = distances([str(made)], str(demo))
    except Exception as exc:  # noqa: BLE001
        return {
            **tally(0, 0, 1),
            "median": None,
            "seconds": round(time.perf_counter() - t0, 3),
            "note": f"identity instrument crashed: {type(exc).__name__}: {exc}",
        }

    med = d.get("median")
    tail = f"ladder: 0.0652 same, {SAME_PERSON_MAX} bar, 0.7137 different, 1.0217 stranger"
    if d.get("outcome") == UNMEASURED or med is None:
        return {
            **tally(0, 0, 1),
            "median": med,
            "seconds": round(time.perf_counter() - t0, 3),
            "note": f"identity NOT MEASURED: {d.get('note')}",
        }
    if med <= SAME_PERSON_MAX:
        return {
            **tally(1, 0, 0),
            "median": med,
            "seconds": round(time.perf_counter() - t0, 3),
            "note": (
                f"the demo identity is in place: median {med} against the "
                f"bar {SAME_PERSON_MAX} ({tail}). {PLAN_NOTE}. "
                f"THE AESTHETIC FIT IS JUDGED BY THE TEMPLATE AUTHOR'S EYE — "
                f"there is no instrument for it"
            ),
        }
    if med < 0.7137:
        return {
            **tally(0, 0, 1),
            "median": med,
            "seconds": round(time.perf_counter() - t0, 3),
            "note": (
                f"median {med} between the bar {SAME_PERSON_MAX} and "
                f"the 'different person' step 0.7137: the face is altered "
                f"or covered, ArcFace is NOT THE JUDGE here, the template "
                f"author judges ({tail})"
            ),
        }
    return {
        **tally(1, 1, 0),
        "median": med,
        "seconds": round(time.perf_counter() - t0, 3),
        "note": (
            f"median {med} above the 'different person' step 0.7137: "
            f"the prompt REPAINTED the person, this is not our demo "
            f"identity ({tail})"
        ),
    }
