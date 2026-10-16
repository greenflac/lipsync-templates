"""Control set for the template linter: planted defects and clean templates.

OWNER: agent B. This module is the LINTER'S NEGATIVE AND POSITIVE CONTROL and
it was written from `studio/LINTER_CONTRACT.md` alone, by an agent that has not
read `studio/template_lint.py` (harness rule И1 — the verdict is not cast by
whoever built the thing). Nothing here may be derived from what the linter
happens to do; every expectation below comes from the contract's own wording.

Why both halves exist (И5, a measuring instrument needs a negative control):

* **Planted defects** — a linter that reports nothing passes any test made only
  of clean input. Each planted template carries EXACTLY ONE defect and records
  which `check` must fire and which element/value must be blamed.
* **Clean templates** — a linter that reports everything is as useless as one
  that reports nothing, and this is the half people forget. On these the
  linter must be silent.

The hardest case is `base_repeats_*`: the BASE ALREADY repeats a word and no
allowed value makes it worse. The contract's measurement (2026-08-26) found 12
repetitions in the shipped catalogue of which 10 were the base's own — a check
without that subtraction reports 6 lies per truth, and these two templates are
what tells the two linters apart.

Every span is MEASURED by `studio.prompt_templates.element`, which calls
`str.find`; no offset in this file is typed by hand (Е1: a typed offset is a
second copy of the prompt's layout and it rots the first time a comma moves).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from studio.prompt_templates import Element, PromptTemplate, element

# The six check names, as LITERALS (Т2). They are the contract's words, not an
# import from the module being judged: an expectation that travels with the
# code it grades can never contradict it.
CHECK_REPETITION = "repetition"
CHECK_ARTICLE = "article"
CHECK_SEAM = "seam"
CHECK_DUPLICATE_VALUE = "duplicate_value"
CHECK_IDENTITY_ONLY = "identity_only"
CHECK_CROSS_ELEMENT = "cross_element"

# Which checks are VIOLATION and which are RISK — again the contract's own
# table (section "The checks"), not the implementation's opinion.
VIOLATION_CHECKS = (CHECK_REPETITION, CHECK_ARTICLE, CHECK_SEAM)
RISK_CHECKS = (CHECK_DUPLICATE_VALUE, CHECK_IDENTITY_ONLY, CHECK_CROSS_ELEMENT)
CHECKS = VIOLATION_CHECKS + RISK_CHECKS

# The three outcomes, as literals for the same reason.
PASS, FAIL, UNMEASURED = "pass", "fail", "could not measure"

MODEL = "midjourney"  # every template here is judged as text; no model is called


@dataclass(frozen=True)
class Expected:
    """One defect planted on purpose, and who must be blamed for it.

    :param check: the `Finding.check` name that MUST appear.
    :param element: the element name that must be blamed.
    :param value: the allowed value that provokes it.
    :param value_may_be_blank: `identity_only` is a property of an element
        rather than of a value — no value provokes it — so a linter may
        reasonably report `value=""` there. The test accepts either, and
        accepts nothing else. Marked here rather than loosened in the test so
        the leniency is visible where the expectation is written.
    """

    check: str
    element: str
    value: str
    value_may_be_blank: bool = False


@dataclass(frozen=True)
class Case:
    """A template plus the verdict the contract requires on it."""

    id: str
    template: PromptTemplate
    outcome: str
    planted: tuple[Expected, ...] = field(default_factory=tuple)
    why: str = ""

    @property
    def is_clean(self) -> bool:
        """A clean case is one where the linter must report NOTHING at all."""
        return not self.planted and self.outcome == PASS


# ---------------------------------------------------------------------------
# 1. repetition — three distances, because a window is a number and a number
#    can be too small. The contract records that a 3-word window MISSED the
#    motivating defect, which sits 4 words apart (OBSERVED 2026-08-26).
#    Distance here = difference of word index between the two occurrences,
#    counted the same way the contract counts its own example:
#        a(0) tailored(1) FOLDED(2) ivory(3) linen(4) suit(5) FOLDED(6)  -> 4
# ---------------------------------------------------------------------------

_REP_2 = "cool morning light, a plain white plate on a scrubbed pine table, shot on a 50mm lens"

REP_TWO_APART = PromptTemplate(
    id="rep_two_words_apart",
    prompt=_REP_2,
    model=MODEL,
    elements=(
        element(
            _REP_2,
            "plate",
            "What is on the table",
            "plain white plate",
            (
                # "light" already stands two words to the left; picking this
                # value puts a second one immediately after it.
                #   cool(0) morning(1) light(2) a(3) LIGHT(4)   -> distance 2
                "light grey stoneware bowl",
                "shallow copper bowl",
            ),
        ),
        element(_REP_2, "table", "What it stands on", "scrubbed pine table", ("dark walnut table",)),
    ),
)

_REP_4 = "a tailored wool overcoat, folded once and left on a snowy bench under a low sun"

REP_FOUR_APART = PromptTemplate(
    id="rep_four_words_apart",
    prompt=_REP_4,
    model=MODEL,
    elements=(
        element(
            _REP_4,
            "subject",
            "What is on the bench",
            "wool overcoat",
            (
                # The motivating defect itself, rebuilt in this project's own
                # words: "a tailored FOLDED ivory linen suit, FOLDED once".
                #   a(0) tailored(1) FOLDED(2) ivory(3) linen(4) suit(5) FOLDED(6)
                "folded ivory linen suit",
                "grey flannel jacket",
            ),
        ),
        element(_REP_4, "light", "What lights it", "a low sun", ("a pale winter moon",)),
    ),
)

_REP_7 = "a plain glass jar set down on a folded linen cloth, soft north light from the left"

REP_SEVEN_APART = PromptTemplate(
    id="rep_seven_words_apart",
    prompt=_REP_7,
    model=MODEL,
    elements=(
        element(
            _REP_7,
            "jar",
            "What is set down",
            "plain glass jar",
            (
                #   a(0) FOLDED(1) paper(2) lantern(3) set(4) down(5) on(6) a(7) FOLDED(8)
                "folded paper lantern",
                "small ceramic bottle",
            ),
        ),
        element(_REP_7, "light", "What lights it", "soft north light", ("cool grey light",)),
    ),
)

# ---------------------------------------------------------------------------
# 2. article — the article sits in the BASE and the substitution changes the
#    sound that follows it. Both directions, because a check written for one
#    of them usually forgets the other.
# ---------------------------------------------------------------------------

_ART_A = "a wooden crate beside the loading door, cold blue light on the wet floor"

ARTICLE_A_BEFORE_VOWEL = PromptTemplate(
    id="article_a_before_vowel",
    prompt=_ART_A,
    model=MODEL,
    elements=(
        element(
            _ART_A,
            "crate",
            "What stands by the door",
            "wooden crate",
            ("empty oil drum", "battered tin trunk"),  # "a empty oil drum"
        ),
        element(_ART_A, "light", "What lights it", "cold blue light", ("warm sodium light",)),
    ),
)

_ART_AN = "an amber glass bottle on a windowsill, low sun through the slats"

ARTICLE_AN_BEFORE_CONSONANT = PromptTemplate(
    id="article_an_before_consonant",
    prompt=_ART_AN,
    model=MODEL,
    elements=(
        element(
            _ART_AN,
            "bottle",
            "What is on the sill",
            "amber glass bottle",
            ("green ceramic vase", "ivory enamel jug"),  # "an green ceramic vase"
        ),
        element(_ART_AN, "sun", "What lights it", "low sun", ("high midday sun",)),
    ),
)

# ---------------------------------------------------------------------------
# 3. seam — the author's value carries its own punctuation or whitespace and
#    the join goes wrong. All three of the contract's shapes are planted: a
#    doubled comma, a space before a comma, a doubled space. These are typing
#    accidents in an allow-list, which is exactly what this tool is for.
# ---------------------------------------------------------------------------

_SEAM_COMMA = "a red bicycle, leaning against a wall, puddles across the yard"

SEAM_DOUBLED_COMMA = PromptTemplate(
    id="seam_doubled_comma",
    prompt=_SEAM_COMMA,
    model=MODEL,
    elements=(
        element(
            _SEAM_COMMA,
            "subject",
            "What leans on the wall",
            "a red bicycle",
            ("a green tandem,", "a black scooter"),  # "a green tandem,, leaning"
        ),
        element(
            _SEAM_COMMA, "ground", "The ground", "puddles across the yard", ("long shadows across the yard",)
        ),
    ),
)

_SEAM_SPACE_COMMA = "a bronze bell above a low doorway, dusty afternoon light in the hall"

SEAM_SPACE_BEFORE_COMMA = PromptTemplate(
    id="seam_space_before_comma",
    prompt=_SEAM_SPACE_COMMA,
    model=MODEL,
    elements=(
        element(
            _SEAM_SPACE_COMMA,
            "doorway",
            "What the bell hangs over",
            "a low doorway",
            ("an arched stone gate ", "a narrow side door"),  # "...gate , dusty"
        ),
        element(
            _SEAM_SPACE_COMMA, "light", "What lights it", "dusty afternoon light", ("cool evening light",)
        ),
    ),
)

_SEAM_DOUBLE_SPACE = "a copper lantern on a stone step, mist along the lane"

SEAM_DOUBLED_SPACE = PromptTemplate(
    id="seam_doubled_space",
    prompt=_SEAM_DOUBLE_SPACE,
    model=MODEL,
    elements=(
        element(
            _SEAM_DOUBLE_SPACE,
            "lantern",
            "What stands on the step",
            "a copper lantern",
            # "an iron lantern" is correct English; the defect is the trailing
            # space alone, so the seam check cannot be passed by the article
            # check firing instead.
            ("an iron lantern ", "a paper lantern"),
        ),
        element(_SEAM_DOUBLE_SPACE, "air", "The air", "mist along the lane", ("frost along the lane",)),
    ),
)

# ---------------------------------------------------------------------------
# 4. duplicate_value — RISK. The same value written twice in one allow-list.
#    `element()` places the base phrase first and drops alternatives equal to
#    it, so the duplicate has to be a pair of equal ALTERNATIVES.
# ---------------------------------------------------------------------------

_DUP_1 = "a small ceramic bowl on a windowsill, soft light from the side"

DUPLICATE_VALUE_BOWL = PromptTemplate(
    id="duplicate_value_bowl",
    prompt=_DUP_1,
    model=MODEL,
    elements=(
        element(_DUP_1, "bowl", "What is on the sill", "a small ceramic bowl", ("a worn brass cup", "a worn brass cup")),
        element(_DUP_1, "light", "What lights it", "soft light from the side", ("cool light from the left",)),
    ),
)

_DUP_2 = "a folded newspaper on a café table, rain on the window behind"

DUPLICATE_VALUE_PAPER = PromptTemplate(
    id="duplicate_value_paper",
    prompt=_DUP_2,
    model=MODEL,
    elements=(
        element(_DUP_2, "paper", "What is on the table", "a folded newspaper", ("a leather notebook", "a leather notebook")),
        element(_DUP_2, "weather", "Outside", "rain on the window behind", ("low sun on the window behind",)),
    ),
)

# ---------------------------------------------------------------------------
# 5. identity_only — RISK. One entry on the allow-list, so the knob is shown to
#    the user and can never move. Built by passing no alternatives at all.
# ---------------------------------------------------------------------------

_ID_1 = "a tin kettle on a camp stove, steam in cold morning air"

IDENTITY_ONLY_STOVE = PromptTemplate(
    id="identity_only_stove",
    prompt=_ID_1,
    model=MODEL,
    elements=(
        element(_ID_1, "kettle", "What is on the stove", "a tin kettle", ("an enamel pot",)),
        element(_ID_1, "stove", "What it stands on", "a camp stove", ()),
    ),
)

_ID_2 = "product photo of a ceramic vase on a white backdrop, soft studio lighting"

IDENTITY_ONLY_BACKDROP = PromptTemplate(
    id="identity_only_backdrop",
    prompt=_ID_2,
    model=MODEL,
    elements=(
        element(_ID_2, "vase", "The product", "a ceramic vase", ("a matte black jug", "a clear glass carafe")),
        element(_ID_2, "backdrop", "What is behind it", "a white backdrop", ()),
    ),
)

# ---------------------------------------------------------------------------
# 6. cross_element — RISK. A value that CONTAINS another element's base text.
#    Legal, and the substituter handles it (that is the scarf-shaped-like-a-
#    full-moon trap `studio/prompt_templates.py` is built around), but the
#    author probably did not mean the same words to appear twice.
#
#    The two occurrences are placed far apart on purpose (21 and 23 words):
#    what is being tested here is the CONTAINMENT, and a repetition VIOLATION
#    landing on the same template would make the row unable to tell which
#    check fired for the right reason.
# ---------------------------------------------------------------------------

_CROSS_1 = (
    "a pale grey scarf laid on a wooden bench, frost creeping along the slats, "
    "long soft shadows on the snow, everything under a full moon"
)

CROSS_ELEMENT_MOON = PromptTemplate(
    id="cross_element_moon",
    prompt=_CROSS_1,
    model=MODEL,
    elements=(
        element(
            _CROSS_1,
            "subject",
            "What is on the bench",
            "a pale grey scarf",
            ("a cashmere wrap shaped like a full moon", "a folded tartan blanket"),
        ),
        element(_CROSS_1, "light", "What lights it", "a full moon", ("a low winter sun",)),
    ),
)

_CROSS_2 = (
    "a small ceramic bowl on a scrubbed pine table, a folded linen cloth beside it, "
    "steam drifting slowly upward, all of it under a bare hanging bulb"
)

CROSS_ELEMENT_BULB = PromptTemplate(
    id="cross_element_bulb",
    prompt=_CROSS_2,
    model=MODEL,
    elements=(
        element(
            _CROSS_2,
            "bowl",
            "What is on the table",
            "a small ceramic bowl",
            ("a wide copper pan mirroring a bare hanging bulb", "a shallow tin tray"),
        ),
        element(_CROSS_2, "light", "What lights it", "a bare hanging bulb", ("a narrow skylight",)),
    ),
)

# ---------------------------------------------------------------------------
# The clean half. Four templates on which every allowed value substitutes
# cleanly: no word repeats that the base did not already have, no article goes
# wrong, no seam moves, no allow-list has a duplicate or a single entry, no
# value contains another element's base text. The linter must say NOTHING.
# ---------------------------------------------------------------------------

_CLEAN_KETTLE = "a copper kettle on a slate ledge, steam rising into the cold air, shot on a 50mm lens"

CLEAN_KETTLE = PromptTemplate(
    id="clean_kettle",
    prompt=_CLEAN_KETTLE,
    model=MODEL,
    elements=(
        element(
            _CLEAN_KETTLE,
            "vessel",
            "What is on the ledge",
            "a copper kettle",
            ("a white enamel jug", "an old tin pot"),
        ),
        element(_CLEAN_KETTLE, "lens", "The lens", "a 50mm lens", ("a 35mm lens", "a wide-angle lens")),
    ),
)

_CLEAN_PRODUCT = (
    "product photo of a matte black speaker on a pale grey backdrop, soft studio lighting from above"
)

CLEAN_PRODUCT = PromptTemplate(
    id="clean_product",
    prompt=_CLEAN_PRODUCT,
    model=MODEL,
    elements=(
        element(
            _CLEAN_PRODUCT,
            "product",
            "The product",
            "a matte black speaker",
            ("a brushed steel kettle", "a small walnut radio"),
        ),
        element(
            _CLEAN_PRODUCT,
            "backdrop",
            "What is behind it",
            "a pale grey backdrop",
            ("a deep navy backdrop", "a warm sand backdrop"),
        ),
    ),
)

_CLEAN_BASKET = (
    "close-up of a woven basket, dried lavender spilling over its rim, "
    "low afternoon sun raking across the surface"
)

CLEAN_BASKET = PromptTemplate(
    id="clean_basket",
    prompt=_CLEAN_BASKET,
    model=MODEL,
    elements=(
        element(
            _CLEAN_BASKET,
            "contents",
            "What is in the basket",
            "dried lavender",
            ("bleached seed heads", "a bundle of sage"),
        ),
        element(
            _CLEAN_BASKET,
            "sun",
            "What lights it",
            "low afternoon sun",
            ("soft morning sun", "cool overcast daylight"),
        ),
    ),
)

_CLEAN_STREET = (
    "a violinist in a black coat on a wet street, neon signs reflected in the puddles, shot on 35mm film"
)

CLEAN_STREET = PromptTemplate(
    id="clean_street",
    prompt=_CLEAN_STREET,
    model=MODEL,
    elements=(
        element(
            _CLEAN_STREET,
            "subject",
            "Who is on the street",
            "a violinist in a black coat",
            ("a cyclist in a yellow rain cape", "a courier in a grey hooded jacket"),
        ),
        element(_CLEAN_STREET, "film", "The stock", "35mm film", ("16mm film", "65mm film")),
    ),
)

# ---------------------------------------------------------------------------
# The hardest case, and the one the whole design exists for: the BASE ALREADY
# repeats a word, in a place no element can touch, and no allowed value adds a
# second one. A check that does not subtract the base fires here on every
# single value — that is the 10-lies-in-12 measurement in the contract. The
# linter must be SILENT on both of these.
#
# Both repetitions are deliberately placed INSIDE any plausible window (3 and 5
# words apart), so a linter that skips them can only be skipping them because
# it subtracted the base, not because they were out of range.
# ---------------------------------------------------------------------------

_BASE_REP_STONE = "a stone lantern beside a stone wall, moss between the flagstones, cold blue light before dawn"

BASE_REPEATS_STONE = PromptTemplate(
    id="base_repeats_stone",
    prompt=_BASE_REP_STONE,
    model=MODEL,
    elements=(
        # Neither element can reach either "stone": the repetition survives
        # every combination, so it is the base's own and never the user's.
        element(
            _BASE_REP_STONE,
            "growth",
            "What grows there",
            "moss between the flagstones",
            ("ivy in the joints", "frost in the joints"),
        ),
        element(
            _BASE_REP_STONE, "light", "What lights it", "cold blue light", ("pale grey light", "low amber light")
        ),
    ),
)

_BASE_REP_LIGHT = (
    "warm light through the doorway, warm light on the floorboards, a wooden stool at the centre"
)

BASE_REPEATS_WARM_LIGHT = PromptTemplate(
    id="base_repeats_warm_light",
    prompt=_BASE_REP_LIGHT,
    model=MODEL,
    elements=(
        element(
            _BASE_REP_LIGHT,
            "seat",
            "What is at the centre",
            "a wooden stool",
            ("a rush-seated chair", "a low bench"),
        ),
        element(
            _BASE_REP_LIGHT, "surface", "What the light falls on", "the floorboards", ("the bare boards", "the tiled floor")
        ),
    ),
)

# ---------------------------------------------------------------------------
# The third outcome. A template declaring no elements renders nothing, so no
# combination exists to judge. The contract is explicit: combinations == 0 is
# NEVER `pass` (Р1/Р2 — "not measurable" is its own outcome and does not fold
# into either of the other two).
# ---------------------------------------------------------------------------

NO_ELEMENTS = PromptTemplate(
    id="no_elements",
    prompt="a plain white plate on a scrubbed pine table",
    model=MODEL,
    elements=(),
)


CONTROL_SET: tuple[Case, ...] = (
    # ---- planted VIOLATIONS ------------------------------------------------
    Case(
        id="rep-2-words-apart",
        template=REP_TWO_APART,
        outcome=FAIL,
        planted=(Expected(CHECK_REPETITION, "plate", "light grey stoneware bowl"),),
        why="the tightest repetition: two words apart, and a value that reads fine on its own",
    ),
    Case(
        id="rep-4-words-apart",
        template=REP_FOUR_APART,
        outcome=FAIL,
        planted=(Expected(CHECK_REPETITION, "subject", "folded ivory linen suit"),),
        why="the distance of the real defect; a 3-word window MISSED this one (contract, 2026-08-26)",
    ),
    Case(
        id="rep-7-words-apart",
        template=REP_SEVEN_APART,
        outcome=FAIL,
        planted=(Expected(CHECK_REPETITION, "jar", "folded paper lantern"),),
        why="a window tuned to exactly the motivating defect and no wider is blind here",
    ),
    Case(
        id="article-a-before-vowel",
        template=ARTICLE_A_BEFORE_VOWEL,
        outcome=FAIL,
        planted=(Expected(CHECK_ARTICLE, "crate", "empty oil drum"),),
        why="the base's 'a' now stands before a vowel because of the value",
    ),
    Case(
        id="article-an-before-consonant",
        template=ARTICLE_AN_BEFORE_CONSONANT,
        outcome=FAIL,
        planted=(Expected(CHECK_ARTICLE, "bottle", "green ceramic vase"),),
        why="the other direction, which a check written for 'a' alone forgets",
    ),
    Case(
        id="seam-doubled-comma",
        template=SEAM_DOUBLED_COMMA,
        outcome=FAIL,
        planted=(Expected(CHECK_SEAM, "subject", "a green tandem,"),),
        why="the value carries its own comma and the base supplies another",
    ),
    Case(
        id="seam-space-before-comma",
        template=SEAM_SPACE_BEFORE_COMMA,
        outcome=FAIL,
        planted=(Expected(CHECK_SEAM, "doorway", "an arched stone gate "),),
        why="a trailing space in front of the base's comma",
    ),
    Case(
        id="seam-doubled-space",
        template=SEAM_DOUBLED_SPACE,
        outcome=FAIL,
        planted=(Expected(CHECK_SEAM, "lantern", "an iron lantern "),),
        why="a trailing space in front of the base's space; the article stays correct on purpose",
    ),
    # ---- planted RISKS: reported, and they do NOT change a pass ------------
    Case(
        id="duplicate-value-bowl",
        template=DUPLICATE_VALUE_BOWL,
        outcome=PASS,
        planted=(Expected(CHECK_DUPLICATE_VALUE, "bowl", "a worn brass cup"),),
        why="the same alternative listed twice; the UI shows the user two identical choices",
    ),
    Case(
        id="duplicate-value-paper",
        template=DUPLICATE_VALUE_PAPER,
        outcome=PASS,
        planted=(Expected(CHECK_DUPLICATE_VALUE, "paper", "a leather notebook"),),
        why="the same defect on a different element name, so a hard-coded name cannot pass it",
    ),
    Case(
        id="identity-only-stove",
        template=IDENTITY_ONLY_STOVE,
        outcome=PASS,
        planted=(Expected(CHECK_IDENTITY_ONLY, "stove", "a camp stove", value_may_be_blank=True),),
        why="a knob with one position, next to an element that really does move",
    ),
    Case(
        id="identity-only-backdrop",
        template=IDENTITY_ONLY_BACKDROP,
        outcome=PASS,
        planted=(
            Expected(CHECK_IDENTITY_ONLY, "backdrop", "a white backdrop", value_may_be_blank=True),
        ),
        why="the same, with the frozen element listed LAST, so position cannot be what is detected",
    ),
    Case(
        id="cross-element-moon",
        template=CROSS_ELEMENT_MOON,
        outcome=PASS,
        planted=(
            Expected(CHECK_CROSS_ELEMENT, "subject", "a cashmere wrap shaped like a full moon"),
        ),
        why="the value contains the light element's whole base text, 21 words from it",
    ),
    Case(
        id="cross-element-bulb",
        template=CROSS_ELEMENT_BULB,
        outcome=PASS,
        planted=(
            Expected(CHECK_CROSS_ELEMENT, "bowl", "a wide copper pan mirroring a bare hanging bulb"),
        ),
        why="the same containment with different words, 23 apart, so no repetition check can claim it",
    ),
    # ---- the clean half: the linter must say NOTHING ------------------------
    Case(
        id="clean-kettle",
        template=CLEAN_KETTLE,
        outcome=PASS,
        why="every value substitutes cleanly; two elements, three values each",
    ),
    Case(
        id="clean-product",
        template=CLEAN_PRODUCT,
        outcome=PASS,
        why="all three backdrop values end in the same noun, which is one occurrence each time",
    ),
    Case(
        id="clean-basket",
        template=CLEAN_BASKET,
        outcome=PASS,
        why="a value that is a whole noun phrase with its own article, landing after a comma",
    ),
    Case(
        id="clean-street",
        template=CLEAN_STREET,
        outcome=PASS,
        why="values repeating only function words ('a', 'in'), which no content-word check may count",
    ),
    Case(
        id="base-repeats-stone",
        template=BASE_REPEATS_STONE,
        outcome=PASS,
        why="THE case: 'stone' repeats 3 words apart in the base, out of reach of every element",
    ),
    Case(
        id="base-repeats-warm-light",
        template=BASE_REPEATS_WARM_LIGHT,
        outcome=PASS,
        why="THE case again: 'warm light' twice, 5 words apart, present whatever the user picks",
    ),
    # ---- the third outcome --------------------------------------------------
    Case(
        id="no-elements",
        template=NO_ELEMENTS,
        outcome=UNMEASURED,
        why="nothing to render, so nothing was measured; combinations == 0 is never a pass",
    ),
)

PLANTED: tuple[Case, ...] = tuple(c for c in CONTROL_SET if c.planted)
CLEAN: tuple[Case, ...] = tuple(c for c in CONTROL_SET if c.is_clean)


def combinations_of(template: PromptTemplate) -> int:
    """How many element/value pairs this template offers, counted independently.

    The linter reports its own `combinations`; this is the control set's own
    arithmetic to compare it against (a count that trusts the thing it counts
    is not a count). One combination per (element, allowed value) pair, which
    is what the contract's word "rendered" means for a per-element sweep.
    """
    return sum(len(el.allowed) for el in template.elements)


def elements_by_name(template: PromptTemplate) -> dict[str, Element]:
    """Elements keyed by name, for tests that need the allow-list of one of them."""
    return {el.name: el for el in template.elements}
