"""The control set, run against the rewriter — written without reading the rewriter.

The verdict is not cast by whoever built the thing (harness И1). This module was
written from `studio/selfrag/REWRITER_CONTRACT.md`, `fidelity.py`, `registry.py`
and `docs/SELFRAG_RESEARCH_AGENTS.md` only. `studio/selfrag/rewriter.py` and its
own test file were deliberately never opened, so what is asserted below is the
requirement rather than the implementation.

WHAT EACH `expect` MEANS HERE, and why it means that

    unchanged   The user already wrote a good prompt for that card. The content
                words come back in the same order, none added, none removed.
                Punctuation, case and slot separators may change — that is the
                vendor's idiom, which the contract explicitly allows — but a
                word may not. This is the most important row type in the file:
                if the agent cannot leave a good prompt alone, everything else
                it does is downside (SELFRAG_RESEARCH_AGENTS §4).

    reordered   A faithful prompt came back: it invents nothing, it does not
                lengthen for its own sake, and anything of the user's it left
                out is declared in `dropped`. It is deliberately NOT asserted
                that the word order actually changed — for a four-word intent
                there is nothing to reorder, and demanding motion would reward
                churn.

    shortened   The card's model expands its own prompts, so the output is
                strictly shorter in words than the intent.

    refused     The third outcome. `prompt is None` and `outcome` is
                `could not measure` — never `fail`, because nothing was
                measured, and never `pass`.

Every row is also put through `fidelity.audit` independently of whatever the
rewriter reports about itself: a flag and the evidence must agree, and when they
do not, the evidence wins (harness Е2).
"""

from __future__ import annotations

import json
import re
import socket
from typing import Callable
import unittest
from collections import Counter
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.fidelity import audit
from studio.selfrag.registry import card_for

# The rewriter is another agent's file and, when this test was written, did not
# exist yet. A missing implementation must SKIP with the reason printed, not
# crash the collection of every other test in the suite.
_rewrite: Callable[..., dict] | None
try:
    from studio.selfrag.rewriter import rewrite as _imported_rewrite
except Exception as exc:  # noqa: BLE001 - any import failure is the same report
    _rewrite = None
    IMPORT_ERROR = f"studio.selfrag.rewriter is not importable: {type(exc).__name__}: {exc}"
else:
    _rewrite = _imported_rewrite
    IMPORT_ERROR = ""

CONTROL_SET = Path(__file__).resolve().parents[1] / "fixtures" / "rewriter_control_set.jsonl"

#: How much longer than the intent a faithful prompt is allowed to get. CHOSEN,
#: not measured: the contract forbids "lengthening for its own sake" without
#: naming a number, and a short intent legitimately grows by slot punctuation
#: and vendor flags. Doubling, or fifteen words, whichever is kinder, is loose
#: enough that only real padding trips it. Tightening it to 1.2x is the mutation
#: that proves this assertion is load-bearing.
LENGTH_SLACK_FACTOR = 2.0
LENGTH_SLACK_WORDS = 15

#: Slot labels a prompt assembler may print around the user's words ("style:",
#: "subject —"). Stripped from BOTH sides of the `unchanged` comparison, because
#: a label is format, not content. The cost of this is known and accepted: if a
#: user's own word happens to be one of these and the rewriter drops it, this
#: test will not see it. Every `unchanged` row was written so that its load-
#: bearing nouns are not on this list.
SLOT_LABELS = frozenset(
    """
    subject action scene setting context movement motion composition framing
    lighting light texture palette style aesthetic stylisation ambiance audio
    constraints prompt negative aspect ratio ar
    """.split()
)

#: Filler a rewriter is entitled to delete without declaring it as dropped user
#: content. These are the user clearing their throat, not what they asked for.
POLITENESS = frozenset(
    """
    i im ive id you we our us it its is am are was were be been being do does
    did done have has had a an the this that these those and or but so if then
    of to in on at for with by from as like about just really quite kind sort
    bit basically honestly ok okay right please thanks thank hi hello want wants
    wanted need needs want-to going go get make makes made look looks looking
    feel feels feeling say saying said know knows knew think thinks thought
    guess suppose maybe not no yes what which who how why where when whatever
    something anything nothing thing things all my me her his him she he they
    them there here more most very much too can could would should will shall
    sure sorry oh well fine whole main point rest lot long else does-that-make
    sense possible idea brief roughly told bought new one two three
    """.split()
)

_WORD = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*")


def words(text: str) -> list[str]:
    """Lowercased word tokens. Punctuation and case are the vendor's business."""
    return _WORD.findall(str(text or "").lower())


def content_sequence(text: str) -> list[str]:
    """Word tokens with slot labels removed, in order."""
    return [w for w in words(text) if w not in SLOT_LABELS]


def mentions(haystack: str, needle: str) -> bool:
    """Whole-word (or whole-phrase) containment, case-insensitive.

    Word boundaries matter: "rain" must not match inside "train station", which
    is a real row in this file.
    """
    pattern = r"\b" + r"\s+".join(re.escape(part) for part in needle.lower().split()) + r"\b"
    return re.search(pattern, str(haystack or "").lower()) is not None


def over_length_ceiling(intent: str, prompt: str) -> bool:
    """Has the prompt grown past what reorganisation can explain?

    A function rather than an inline assertion so the instrument itself has a
    negative control: `Instruments` below feeds it a case where it must say yes
    and a case where it must say no. Without that, the constant above would be
    guarded by nothing — the first mutation run proved exactly that, since no
    row in this control set currently makes the rewriter grow at all.
    """
    before = len(words(intent))
    after = len(words(prompt))
    return after > max(int(before * LENGTH_SLACK_FACTOR), before + LENGTH_SLACK_WORDS)


def load_rows() -> list[dict]:
    rows = []
    for number, line in enumerate(CONTROL_SET.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError as exc:  # a broken fixture is not a passing test
            raise AssertionError(f"{CONTROL_SET}:{number} is not JSON: {exc}") from exc
    return rows


ROWS = load_rows()


def _refuse_socket(*_args, **_kwargs):
    raise AssertionError("a test in test_rewriter_contract tried to open a socket")


_REAL_SOCKET = socket.socket
_REAL_CREATE = socket.create_connection


def setUpModule() -> None:
    """No network, enforced by the runner rather than by agreement (harness Т4).

    A rewriter that quietly reached a model API would otherwise pass here and
    bill in production. `model=` is never passed by this module, so no paid call
    is legitimate for the whole of it.
    """
    socket.socket = _refuse_socket  # type: ignore[misc,assignment]
    socket.create_connection = _refuse_socket  # type: ignore[assignment]


def tearDownModule() -> None:
    socket.socket = _REAL_SOCKET  # type: ignore[misc,assignment]
    socket.create_connection = _REAL_CREATE  # type: ignore[assignment]


class ControlSet(unittest.TestCase):
    """The fixture judges itself first. These run even with no rewriter."""

    def test_rows_have_the_contract_shape(self) -> None:
        allowed = {"unchanged", "reordered", "shortened", "refused"}
        seen: set[str] = set()
        for row in ROWS:
            with self.subTest(row=row.get("id")):
                for key in (
                    "id",
                    "intent",
                    "model",
                    "expect",
                    "must_not_contain",
                    "must_contain",
                    "why",
                ):
                    self.assertIn(key, row)
                self.assertIn(row["expect"], allowed)
                self.assertNotIn(row["id"], seen)
                seen.add(row["id"])
                self.assertTrue(row["why"].strip(), "a row with no stated purpose is not a control")
                for word in row["must_not_contain"]:
                    self.assertFalse(
                        mentions(row["intent"], word),
                        f"{word!r} is in the intent, so forbidding it in the output is a trap",
                    )
                for word in row["must_contain"]:
                    self.assertTrue(
                        mentions(row["intent"], word),
                        f"{word!r} is not in the intent, so requiring it would require inventing it",
                    )

    def test_coverage_the_contract_demands(self) -> None:
        """A set missing any of these is not a control set (contract §control set)."""
        by_expect = Counter(row["expect"] for row in ROWS)
        print(f"\ncontrol set: {len(ROWS)} rows, {dict(sorted(by_expect.items()))}")

        self.assertGreaterEqual(
            by_expect["unchanged"], 3, "the most important case, and it needs several"
        )
        self.assertGreaterEqual(by_expect["refused"], 2)
        self.assertGreaterEqual(by_expect["shortened"], 1)
        self.assertGreaterEqual(by_expect["reordered"], 1)

        expanders = {row["model"] for row in ROWS if row["expect"] == "shortened"}
        self.assertEqual(
            expanders,
            {"wan-2.6-flash"},
            "wan-2.6-flash is the only model whose expands_internally is 'yes' from a vendor "
            "source that was actually opened (studio/knowledge/model_facts.jsonl)",
        )

        bait = [row for row in ROWS if row["must_not_contain"]]
        self.assertGreaterEqual(len(bait), 5)
        named = {word.lower() for row in bait for word in row["must_not_contain"]}
        for folklore in ("swan", "sunset", "marble", "8k", "masterpiece", "award-winning"):
            self.assertIn(folklore, named, f"the contract names {folklore!r} as bait")

        lengths = sorted(len(words(row["intent"])) for row in ROWS if row["expect"] != "refused")
        print(
            f"intent lengths (words): min {lengths[0]}, median {lengths[len(lengths) // 2]}, max {lengths[-1]}"
        )
        self.assertLessEqual(lengths[0], 6, "no short end")
        self.assertGreaterEqual(lengths[-1], 40, "no long end")
        self.assertTrue(
            any(12 <= n <= 35 for n in lengths),
            "nothing in the middle of the length range",
        )

    def test_empty_and_nonsense_intents_are_present(self) -> None:
        refused = [row for row in ROWS if row["expect"] == "refused"]
        self.assertTrue(any(not row["intent"].strip() for row in refused), "no empty intent")
        self.assertTrue(
            any(row["intent"].strip() and card_for(row["model"]) is None for row in refused),
            "no unknown-model row: 'no card' is one of the contract's three could-not-measure causes",
        )


@unittest.skipIf(_rewrite is None, IMPORT_ERROR or "rewriter missing")
class Contract(unittest.TestCase):
    """Every row through `rewrite`, with no model and therefore no network."""

    results: dict[str, dict] = {}

    @classmethod
    def setUpClass(cls) -> None:
        assert _rewrite is not None  # the skipIf above guarantees this
        cls.results = {}
        for row in ROWS:
            card = card_for(row["model"])
            # A row naming a model with no card is a REFUSAL case, and the
            # rewriter is entitled to be handed one. Calling it with None is
            # the test's own way of asking "what do you do with no skeleton?".
            cls.results[row["id"]] = _rewrite(row["intent"], card=card)

    def rows(self, *expects: str):
        for row in ROWS:
            if not expects or row["expect"] in expects:
                yield row, self.results[row["id"]]

    def test_the_return_shape(self) -> None:
        checked = 0
        for row, out in self.rows():
            with self.subTest(row=row["id"]):
                self.assertIsInstance(out, dict)
                for key in ("prompt", "dropped", "invented", "source", "rounds", "outcome"):
                    self.assertIn(key, out, f"the contract names {key!r} in the return")
                self.assertIn(out["outcome"], (PASS, FAIL, UNMEASURED))
                self.assertIsInstance(out["dropped"], list)
                self.assertIsInstance(out["invented"], list)
                self.assertEqual(
                    out["rounds"], 0, "no model was passed, so no model attempt can have been made"
                )
                checked += 1
        print(f"\nreturn shape: checked {checked}, violations 0, could not measure 0")

    def test_refused_rows_say_could_not_measure(self) -> None:
        """The third outcome, and it is neither of the other two (harness Р1)."""
        for row, out in self.rows("refused"):
            with self.subTest(row=row["id"], why=row["why"]):
                self.assertIsNone(
                    out["prompt"], "a refusal that hands back a prompt is not a refusal"
                )
                self.assertEqual(out["outcome"], UNMEASURED)

    def test_a_prompt_comes_back_for_every_buildable_row(self) -> None:
        for row, out in self.rows("unchanged", "reordered", "shortened"):
            with self.subTest(row=row["id"]):
                self.assertIsNotNone(out["prompt"])
                self.assertTrue(str(out["prompt"]).strip())
                self.assertEqual(
                    out["source"],
                    "deterministic",
                    "model=None means the deterministic path, by the contract's own docstring",
                )

    def test_nothing_is_invented(self) -> None:
        """Checked twice: what the rewriter says, and what fidelity.audit finds.

        The deterministic path is supposed to be unable to invent by
        construction. This is the assertion that says so out loud.
        """
        violations = 0
        for row, out in self.rows("unchanged", "reordered", "shortened"):
            with self.subTest(row=row["id"]):
                self.assertEqual(out["invented"], [], "invented is non-empty, so outcome is FAIL")
                self.assertEqual(out["outcome"], PASS)
                verdict = audit(out["prompt"], [row["intent"]])
                if verdict["outcome"] != PASS:
                    violations += 1
                self.assertEqual(
                    verdict["outcome"],
                    PASS,
                    f"fidelity.audit disagrees with the rewriter: {verdict['note']}",
                )
        self.assertEqual(violations, 0)

    def test_the_bait_is_not_taken(self) -> None:
        """What a careless rewriter would add, named per row.

        This catches things `fidelity.audit` cannot: "matte", "glossy" and "8k"
        are on CRAFT_TOKENS or read as measurements, so the audit lets them
        through even when the user asked for the opposite finish. That exact
        substitution has already cost this project a real generation.
        """
        for row, out in self.rows("unchanged", "reordered", "shortened"):
            for word in row["must_not_contain"]:
                with self.subTest(row=row["id"], word=word):
                    self.assertFalse(
                        mentions(out["prompt"], word),
                        f"{row['id']}: added {word!r}, which the user never wrote. {row['why']}",
                    )

    def test_what_the_user_asked_for_survives(self) -> None:
        for row, out in self.rows("unchanged", "reordered", "shortened"):
            for word in row["must_contain"]:
                with self.subTest(row=row["id"], word=word):
                    self.assertTrue(
                        mentions(out["prompt"], word),
                        f"{row['id']}: {word!r} is the user's own subject and it is gone",
                    )

    def test_a_good_prompt_is_left_alone(self) -> None:
        """The negative control. Adding nothing is the correct output."""
        for row, out in self.rows("unchanged"):
            with self.subTest(row=row["id"], why=row["why"]):
                before = content_sequence(row["intent"])
                after = content_sequence(out["prompt"])
                self.assertEqual(
                    after,
                    before,
                    f"{row['id']}: the words changed. dropped={out['dropped']}",
                )
                self.assertEqual(out["dropped"], [], "nothing here has anywhere else to go")

    def test_a_model_that_expands_gets_less(self) -> None:
        for row, out in self.rows("shortened"):
            with self.subTest(row=row["id"]):
                before = len(words(row["intent"]))
                after = len(words(out["prompt"]))
                self.assertLess(
                    after,
                    before,
                    f"{row['id']}: {before} words in, {after} out, for a model that expands "
                    "internally. Stacking an expander on an expander is the trial's losing arm",
                )

    def test_nothing_lengthens_for_its_own_sake(self) -> None:
        for row, out in self.rows("unchanged", "reordered", "shortened"):
            with self.subTest(row=row["id"]):
                before = len(words(row["intent"]))
                after = len(words(out["prompt"]))
                self.assertFalse(
                    over_length_ceiling(row["intent"], out["prompt"]),
                    f"{row['id']}: {before} words in, {after} out. Length correlates with quality "
                    "at about -0.07; faithful is better",
                )

    def test_dropped_content_is_declared(self) -> None:
        """ "Drop what the card says the model ignores, AND SAY SO in `dropped`."

        Only applied where the contract's own wording applies cleanly: rows whose
        expected outcome is a reorganisation of the user's words. Shortened rows
        are exempt, because deleting a rambling user's filler is the job there
        and itemising every "basically" would be noise.
        """
        for row, out in self.rows("unchanged", "reordered"):
            declared = " ".join(str(item) for item in out["dropped"]).lower()
            missing = [
                word
                for word in content_sequence(row["intent"])
                if word not in POLITENESS
                and word not in SLOT_LABELS
                and not mentions(out["prompt"], word)
                and word not in declared
            ]
            with self.subTest(row=row["id"]):
                self.assertEqual(
                    missing,
                    [],
                    f"{row['id']}: dropped the user's {missing} without declaring it. "
                    f"dropped={out['dropped']}",
                )


class Instruments(unittest.TestCase):
    """Each check gets an input it must accept and an input it must reject.

    Harness И5: a pribor with no negative control returns a number that measures
    something else. Every expected value here is a literal, never imported from
    what it judges (harness Т2). These run whether or not the rewriter exists.
    """

    SHORT = "red sneaker on white"

    def test_the_length_check_can_say_yes_and_no(self) -> None:
        dressed = "subject: red sneaker | composition: on white | palette: red and white --ar 1:1"
        self.assertFalse(
            over_length_ceiling(self.SHORT, dressed),
            "slot labels and a vendor flag around four words are format, not padding",
        )
        padded = self.SHORT + ", " + "ultra detailed intricate stunning gorgeous " * 10
        self.assertTrue(
            over_length_ceiling(self.SHORT, padded),
            "forty words of booster on a four-word intent is padding and must be caught",
        )

    def test_the_bait_check_can_say_yes_and_no(self) -> None:
        self.assertTrue(mentions("a wide still lake at dawn, a swan drifting", "swan"))
        self.assertTrue(mentions("shot on MARBLE, top down", "marble"), "case must not matter")
        self.assertTrue(mentions("a plain studio backdrop", "studio backdrop"), "phrases too")
        self.assertFalse(
            mentions("a woman walking through a train station", "rain"),
            "'rain' inside 'train' is the substring bug this function exists to avoid",
        )
        self.assertFalse(mentions("a wide still lake at dawn", "swan"))

    def test_the_unchanged_comparison_can_say_yes_and_no(self) -> None:
        good = "a folded linen shirt, flat lay, soft window light"
        self.assertEqual(
            content_sequence(good),
            content_sequence("A FOLDED LINEN SHIRT | FLAT LAY | SOFT WINDOW LIGHT"),
            "case and slot punctuation are the vendor's idiom and are allowed to change",
        )
        self.assertNotEqual(
            content_sequence(good),
            content_sequence("a folded linen shirt, flat lay, soft window light, marble table"),
            "an added object must not survive this comparison",
        )
        self.assertNotEqual(
            content_sequence(good),
            content_sequence("flat lay, a folded linen shirt, soft window light"),
            "a reordering must not survive it either, or 'unchanged' means nothing",
        )
        self.assertNotEqual(
            content_sequence(good),
            content_sequence("a folded linen shirt, soft window light"),
            "a dropped clause must not survive it",
        )


class NoNetwork(unittest.TestCase):
    """The guard's own negative control (harness И5): it must be able to say no."""

    def test_the_socket_guard_is_armed(self) -> None:
        with self.assertRaises(AssertionError):
            socket.socket()


if __name__ == "__main__":
    unittest.main()
