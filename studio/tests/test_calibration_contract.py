"""Judge `studio.prompt_templates.calibrate` against the calibration contract.

Written from `studio/CALIBRATION_CONTRACT.md` alone, by an agent that has not
read the implementation (И1): the verdict is not cast by whoever built the
thing, so nothing in this module may be derived from what the module under test
happens to do.

Two consequences shape the file:

* The templates are DEFINED HERE, not imported from the module under test. A
  control set run against the implementer's own examples measures the
  implementer, not the contract.
* The invariant is re-derived here from the base prompt and the spans, and the
  output is compared against that reconstruction. `verify` is not asked whether
  `verify` is happy — a substituter and its own grader fail together.

Every span is located with `str.find` (see `span_of`), never typed as a number:
a hand-typed offset is a second copy of the prompt's layout (Е1) and it rots
the moment a word changes.
"""

from __future__ import annotations

import json
import socket
import unittest
from pathlib import Path

# The three outcomes as LITERALS, not imported from anything under test (Т2):
# an expectation that travels with the code it grades cannot contradict it.
PASS, FAIL, UNMEASURED = "pass", "fail", "could not measure"

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "calibration_control_set.jsonl"

IMPORT_ERROR = ""
try:  # the module may not exist yet; that is a skip with the reason, not a stub
    from studio.prompt_templates import Element, PromptTemplate, calibrate
except Exception as exc:  # pragma: no cover - depends on build order
    IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

_REAL_SOCKET = socket.socket
_REAL_CONNECT = socket.create_connection


class NetworkTouched(AssertionError):
    """Raised when a test reaches for a socket. Calibration is offline by design."""


def setUpModule() -> None:
    """Close the network for the whole module. Enforcement, not agreement (Т4)."""

    def _blocked(*args: object, **kwargs: object) -> None:
        raise NetworkTouched("a test tried to open a socket")

    socket.socket = _blocked  # type: ignore[assignment, misc]
    socket.create_connection = _blocked  # type: ignore[assignment]


def tearDownModule() -> None:
    socket.socket = _REAL_SOCKET  # type: ignore[misc]
    socket.create_connection = _REAL_CONNECT


def span_of(prompt: str, needle: str, occurrence: int = 1) -> tuple[int, int]:
    """Locate the nth occurrence of `needle`, so no offset is ever typed by hand."""
    start = -1
    for _ in range(occurrence):
        start = prompt.find(needle, start + 1)
        if start < 0:
            raise AssertionError(f"control-set bug: {needle!r} not in {prompt!r}")
    return (start, start + len(needle))


# ---------------------------------------------------------------- the templates
#
# CHOSEN by the control set's author, not measured: each prompt is built to trip
# one specific way of substituting text wrongly, and the traps are named below.
#
# neon_alley  - "red coat" appears TWICE and only the first is an element, so a
#               str.replace corrupts the shop; the subject span starts at index
#               0 and the film span ends at the last character; allowed values
#               deliberately contain other elements' base text.
# focal_pair  - "35" and "mm" are ADJACENT with no separator, and "135" is a
#               superstring of "35".
# bare_slate  - declares nothing calibratable: the `could not measure` template.
# two_lamps   - the element is the SECOND of two identical phrases, and its
#               allowed values include another span's exact base text.

NEON_ALLEY_PROMPT = (
    "A young woman in a red coat walks past a red coat shop, "
    "lit by cold blue light, shot on 35mm film"
)
FOCAL_PAIR_PROMPT = "A dancer in a red silk dress spins in a marble hall, shot on 35mm at f1.8"
BARE_SLATE_PROMPT = "A portrait against a plain wall"
TWO_LAMPS_PROMPT = (
    "Two lamps: a warm lamp on the table and a warm lamp on the shelf, with dust in the air"
)

# name -> (span, allowed). Plain data, so the fixture can be self-checked even
# when the module under test does not import.
TEMPLATE_DATA: dict[str, dict] = {
    "neon_alley": {
        "prompt": NEON_ALLEY_PROMPT,
        "model": "control-set-only",
        "elements": [
            (
                "subject",
                "Who is in the shot",
                span_of(NEON_ALLEY_PROMPT, "A young woman"),
                (
                    "A young woman",
                    "An older man",
                    "A café violinist",
                    "A stunt double in a red coat",
                ),
            ),
            (
                "coat",
                "What they wear",
                span_of(NEON_ALLEY_PROMPT, "red coat", 1),
                (
                    "red coat",
                    "green parka",
                    "coat the colour of cold blue light",
                    "red coat shop apron",
                ),
            ),
            (
                "light",
                "How it is lit",
                span_of(NEON_ALLEY_PROMPT, "cold blue light"),
                (
                    "cold blue light",
                    "warm tungsten light",
                    "the red coat glow of a shop sign",
                ),
            ),
            (
                "film",
                "What it was shot on",
                span_of(NEON_ALLEY_PROMPT, "35mm film"),
                ("35mm film", "16mm film", "an anamorphic lens"),
            ),
        ],
    },
    "focal_pair": {
        "prompt": FOCAL_PAIR_PROMPT,
        "model": "control-set-only",
        "elements": [
            (
                "fabric",
                "The dress",
                span_of(FOCAL_PAIR_PROMPT, "silk"),
                ("silk", "linen", "velvet", "silk-and-velvet"),
            ),
            (
                "hall",
                "Where she spins",
                span_of(FOCAL_PAIR_PROMPT, "marble hall"),
                ("marble hall", "granite hall", "glass atrium"),
            ),
            (
                "focal",
                "Focal length",
                span_of(FOCAL_PAIR_PROMPT, "35"),
                ("35", "50", "85", "135"),
            ),
            (
                "gauge",
                "Lens gauge",
                span_of(FOCAL_PAIR_PROMPT, "mm"),
                ("mm", "mm anamorphic", "mm spherical"),
            ),
        ],
    },
    "bare_slate": {
        "prompt": BARE_SLATE_PROMPT,
        "model": "control-set-only",
        "elements": [],
    },
    "two_lamps": {
        "prompt": TWO_LAMPS_PROMPT,
        "model": "control-set-only",
        "elements": [
            (
                "lamp",
                "The second lamp",
                span_of(TWO_LAMPS_PROMPT, "a warm lamp", 2),
                (
                    "a warm lamp",
                    "a green lamp",
                    "a warm lamp with a paper shade",
                    "dust in the air",
                ),
            ),
            (
                "dust",
                "What hangs in the air",
                span_of(TWO_LAMPS_PROMPT, "dust in the air"),
                (
                    "dust in the air",
                    "smoke in the air",
                    "a warm lamp reflected in the air",
                ),
            ),
        ],
    },
}


def load_rows() -> list[dict]:
    """Read the control set, one JSON object per line."""
    with FIXTURE.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


ROWS = load_rows()


def base_prompt(template_id: str | None) -> str | None:
    """The owner's untouched prompt for a row, or None when the row has no template."""
    if template_id is None:
        return None
    return TEMPLATE_DATA[template_id]["prompt"]


def spans_for(template_id: str, choices: dict) -> list[tuple[str, tuple[int, int]]]:
    """The declared spans of the chosen elements, left to right."""
    data = TEMPLATE_DATA[template_id]
    picked = [(name, span) for name, _, span, _ in data["elements"] if name in choices]
    return sorted(picked, key=lambda item: item[1][0])


def expected_output(template_id: str, choices: dict) -> tuple[str, list[dict]]:
    """Rebuild the calibrated prompt HERE, from the base and the declared spans.

    This is the invariant restated as an equality: splicing the chosen values
    into their spans and leaving every other character alone produces exactly
    one string, so `out == this` is the same claim as "every changed character
    lies inside a calibrated span" — and it is computed without the module.
    """
    base = TEMPLATE_DATA[template_id]["prompt"]
    parts: list[str] = []
    moved: list[dict] = []
    cursor = 0
    for name, (start, end) in spans_for(template_id, choices):
        parts.append(base[cursor:start])
        position = sum(len(part) for part in parts)
        value = choices[name]
        parts.append(value)
        moved.append(
            {
                "name": name,
                "span": (position, position + len(value)),
                "was": base[start:end],
                "value": value,
            }
        )
        cursor = end
    parts.append(base[cursor:])
    return "".join(parts), moved


def first_difference(left: str, right: str) -> int:
    """Index of the first differing character, or -1 when the strings match."""
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    if len(left) != len(right):
        return min(len(left), len(right))
    return -1


def as_template(template_id: str):
    """Build the module's own shapes from this file's data, at call time."""
    data = TEMPLATE_DATA[template_id]
    return PromptTemplate(
        id=template_id,
        prompt=data["prompt"],
        model=data["model"],
        elements=tuple(
            Element(name=name, label=label, span=span, allowed=allowed)
            for name, label, span, allowed in data["elements"]
        ),
    )


class ControlSetIsSound(unittest.TestCase):
    """Check the instrument before trusting its readings (И5).

    These run whether or not the module under test exists: a control set whose
    own phrases are wrong would grade a correct implementation as broken.
    """

    def test_rows_are_unique_and_typed(self) -> None:
        self.assertGreaterEqual(len(ROWS), 25, "a control set this thin is a sample")
        self.assertLessEqual(len(ROWS), 40)
        ids = [row["id"] for row in ROWS]
        self.assertEqual(len(ids), len(set(ids)), "duplicate row ids")
        for row in ROWS:
            with self.subTest(row=row["id"]):
                self.assertIn(row["expect"], (PASS, FAIL, UNMEASURED))
                self.assertIsInstance(row["choices"], dict)
                self.assertTrue(row["why"].strip(), "a row without a reason is noise")

    def test_every_required_case_is_present(self) -> None:
        """The contract lists seven cases; a set missing one is not a control set."""
        by_id = {row["id"]: row for row in ROWS}
        required = (
            "t1-no-choices",
            "t1-one-element",
            "t1-all-four",
            "t1-value-not-allowed",
            "t1-unknown-element",
            "t2-adjacent-both",
            "t1-two-values-swallow-each-other",
        )
        for row_id in required:
            self.assertIn(row_id, by_id)
        counts = {
            outcome: sum(1 for row in ROWS if row["expect"] == outcome)
            for outcome in (PASS, FAIL, UNMEASURED)
        }
        for outcome, count in counts.items():
            self.assertGreater(count, 0, f"no {outcome} rows: {counts}")

    def test_declared_spans_are_legal(self) -> None:
        """Non-overlapping, inside the prompt, non-empty — for THIS file's templates."""
        for template_id, data in TEMPLATE_DATA.items():
            with self.subTest(template=template_id):
                prompt = data["prompt"]
                spans = sorted(span for _, _, span, _ in data["elements"])
                previous_end = 0
                for start, end in spans:
                    self.assertGreaterEqual(start, 0)
                    self.assertLessEqual(end, len(prompt))
                    self.assertGreater(end, start, "an empty span is a broken template")
                    self.assertGreaterEqual(start, previous_end, "spans overlap")
                    previous_end = end

    def test_allowed_values_cover_every_pass_row(self) -> None:
        for row in ROWS:
            if row["expect"] != PASS or row["template_id"] is None:
                continue
            with self.subTest(row=row["id"]):
                allowed = {
                    name: values
                    for name, _, _, values in TEMPLATE_DATA[row["template_id"]]["elements"]
                }
                for name, value in row["choices"].items():
                    self.assertIn(name, allowed)
                    self.assertIn(value, allowed[name])

    def test_phrases_match_the_independently_built_output(self) -> None:
        """must_keep/must_change are literals; prove they are true of the base."""
        for row in ROWS:
            template_id = row["template_id"]
            if template_id is None:
                continue
            with self.subTest(row=row["id"]):
                base = TEMPLATE_DATA[template_id]["prompt"]
                if row["expect"] == PASS:
                    target, _ = expected_output(template_id, row["choices"])
                else:
                    target = base
                for phrase in row["must_keep"]:
                    self.assertIn(phrase, base, "must_keep is not in the base")
                    self.assertIn(phrase, target, "must_keep would not survive")
                for phrase in row["must_change"]:
                    self.assertIn(phrase, base, "must_change is not in the base")
                    self.assertNotIn(phrase, target, "must_change would survive")


class CalibrationContract(unittest.TestCase):
    """Run the control set through `calibrate` and hold it to the contract."""

    def setUp(self) -> None:
        if IMPORT_ERROR:
            self.skipTest(f"studio.prompt_templates did not import: {IMPORT_ERROR}")

    def run_row(self, row: dict) -> dict:
        template_id = row["template_id"]
        template = None if template_id is None else as_template(template_id)
        return calibrate(template, row["choices"])

    def assert_shape(self, result: dict) -> None:
        """The studio judging dict, plus the four calibration keys."""
        self.assertIsInstance(result, dict)
        for key in ("outcome", "prompt", "applied", "rejected", "changed_spans"):
            self.assertIn(key, result)
        self.assertIsInstance(result["applied"], dict)
        self.assertIsInstance(result["rejected"], dict)
        self.assertIsInstance(result["changed_spans"], list)

    def assert_untouched(self, result: dict, base: str | None, row_id: str) -> None:
        """A refused or unmeasurable request never returns a modified prompt.

        The contract says both `prompt is None when refused` (the shapes) and
        `return the untouched base prompt` (the outcomes). Those two cannot both
        be pinned down, so this asserts what they agree on: never a third string,
        and nothing applied.
        """
        prompt = result["prompt"]
        if prompt is not None:
            self.assertEqual(prompt, base, f"{row_id}: a non-pass row changed the base")
        self.assertEqual(result["applied"], {}, f"{row_id}: applied on a non-pass row")
        self.assertEqual(list(result["changed_spans"]), [])

    def test_control_set(self) -> None:
        for row in ROWS:
            with self.subTest(row=row["id"], why=row["why"]):
                result = self.run_row(row)
                self.assert_shape(result)
                self.assertEqual(
                    result["outcome"],
                    row["expect"],
                    f"{row['id']}: {row['why']}\nnote: {result.get('note')!r}",
                )
                base = base_prompt(row["template_id"])
                if row["expect"] == PASS:
                    self.check_pass_row(row, result, base)
                else:
                    self.assert_untouched(result, base, row["id"])
                    if row["expect"] == FAIL:
                        self.assertTrue(result["rejected"], f"{row['id']}: a fail with no reason")
                        self.assertLessEqual(set(result["rejected"]), set(row["choices"]))
                    if result["prompt"] is not None:
                        for phrase in row["must_keep"]:
                            self.assertIn(phrase, result["prompt"])

    def check_pass_row(self, row: dict, result: dict, base: str | None) -> None:
        """Grade a `pass` against a reconstruction built without the module."""
        row_id = row["id"]
        template_id = row["template_id"]
        assert template_id is not None and base is not None
        out = result["prompt"]
        self.assertIsInstance(out, str, f"{row_id}: a pass with no prompt")

        wanted, moved = expected_output(template_id, row["choices"])
        if out != wanted:
            index = first_difference(wanted, out)
            self.fail(
                f"{row_id}: the output is not the base with only the calibrated "
                f"spans replaced.\nfirst difference at character {index}\n"
                f"  wanted: {wanted[max(0, index - 25) : index + 25]!r}\n"
                f"  got   : {out[max(0, index - 25) : index + 25]!r}\n"
                f"  why   : {row['why']}"
            )

        # The same claim again, stated as untouched segments rather than as one
        # equality, so a failure names the piece of the owner's prompt that moved.
        cursor_base = 0
        cursor_out = 0
        for item in moved:
            start, end = item["span"]
            length = start - cursor_out
            self.assertEqual(
                base[cursor_base : cursor_base + length],
                out[cursor_out:start],
                f"{row_id}: text outside every calibrated span moved",
            )
            self.assertEqual(out[start:end], item["value"])
            cursor_base += length + len(item["was"])
            cursor_out = end
        self.assertEqual(
            base[cursor_base:],
            out[cursor_out:],
            f"{row_id}: the tail after the last calibrated span moved",
        )

        self.assertEqual(result["applied"], row["choices"], f"{row_id}: applied")
        self.assertEqual(result["rejected"], {}, f"{row_id}: rejected on a pass")

        reported = {tuple(span) for span in result["changed_spans"]}
        legal = {item["span"] for item in moved}
        self.assertLessEqual(
            reported, legal, f"{row_id}: changed_spans names a range nobody calibrated"
        )
        must_report = {item["span"] for item in moved if item["value"] != item["was"]}
        self.assertLessEqual(
            must_report,
            reported,
            f"{row_id}: a span whose text really changed is missing from changed_spans",
        )
        for start, end in reported:
            self.assertLessEqual(end, len(out))

        for phrase in row["must_keep"]:
            self.assertIn(phrase, out, f"{row_id}: must_keep lost")
        for phrase in row["must_change"]:
            self.assertNotIn(phrase, out, f"{row_id}: must_change survived")

    def test_judging_dict_counts_its_denominators(self) -> None:
        """Zero checks is never a pass, and a fail says how many violations (Р2)."""
        for row in ROWS:
            with self.subTest(row=row["id"]):
                result = self.run_row(row)
                for key in ("checked", "violations", "unmeasured", "note"):
                    self.assertIn(key, result, "the studio judging dict")
                for key in ("checked", "violations", "unmeasured"):
                    self.assertIsInstance(result[key], int)
                if result["outcome"] == PASS:
                    self.assertGreater(result["checked"], 0)
                    self.assertEqual(result["violations"], 0)
                if result["outcome"] == FAIL:
                    self.assertGreater(result["violations"], 0)
                if result["outcome"] == UNMEASURED:
                    self.assertGreater(result["unmeasured"], 0)

    def test_calibrate_does_not_mutate_the_template(self) -> None:
        """The owner's base survives the call itself, not just the return value."""
        for row in ROWS:
            if row["template_id"] is None:
                continue
            with self.subTest(row=row["id"]):
                template = as_template(row["template_id"])
                before = template.prompt
                calibrate(template, dict(row["choices"]))
                self.assertEqual(template.prompt, before)

    def test_a_broken_span_is_reported_not_skipped(self) -> None:
        """Overlapping / out-of-range / empty spans are broken templates.

        The contract says they must be validated at construction and reported.
        Whether that report is an exception at construction or a `fail` from
        `calibrate` is not pinned down, so either is accepted — silence is not.
        """
        prompt = NEON_ALLEY_PROMPT
        coat = span_of(prompt, "red coat", 1)
        # Built lazily: `Element` itself may be where the report happens, and a
        # raise inside a dict literal would take the whole test down with it.
        broken = {
            "overlapping": lambda: (
                Element("a", "A", coat, ("red coat", "green parka")),
                Element("b", "B", (coat[0] + 1, coat[1] + 3), ("t shirt",)),
            ),
            "out of range": lambda: (
                Element("a", "A", (len(prompt) - 2, len(prompt) + 40), ("x",)),
            ),
            "empty": lambda: (Element("a", "A", (coat[0], coat[0]), ("x",)),),
        }
        for label, build in broken.items():
            with self.subTest(broken=label):
                try:
                    elements = build()
                    template = PromptTemplate(
                        id=f"broken_{label}",
                        prompt=prompt,
                        model="control-set-only",
                        elements=elements,
                    )
                except Exception:
                    continue  # reported at construction: that is the contract met
                result = calibrate(template, {"a": elements[0].allowed[0]})
                self.assertEqual(
                    result["outcome"],
                    FAIL,
                    f"a {label} span was accepted and calibrated anyway",
                )


if __name__ == "__main__":
    unittest.main()
