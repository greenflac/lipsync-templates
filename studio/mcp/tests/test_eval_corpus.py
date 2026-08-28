"""The corpus-derived gold set: does it measure retrieval, or does it flatter it?

A gold set is an instrument, and an instrument that cannot fail is not one. The
set this gates is derived from the corpus at run time by a fixed rule, so these
tests check the RULE — on a synthetic corpus, so nothing here needs the real
gallery file and nothing reaches the network (house rule T4).

The property that carries the most weight is the first one: a derived query must
not contain its own answer. Without it the set would score a retriever that only
echoes its input, and every number after that would be decoration.

Expected values are literals, not imports from the script (rule T2).
"""

from __future__ import annotations

import importlib.util
import random
import unittest
from pathlib import Path

from lipsync.fork_identity import UNMEASURED

import studio.knowledge as K

_SPEC = importlib.util.spec_from_file_location(
    "eval_corpus", Path(__file__).resolve().parents[3] / "scripts" / "eval_corpus.py"
)
assert _SPEC and _SPEC.loader
ec = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ec)


class _FakeEntry:
    """Just enough of an index Entry for the derivation rule to read."""

    def __init__(self, text: str) -> None:
        self.kind = K.KIND_GALLERY_PROMPT  # type: ignore[attr-defined]
        self.text = text
        self.palette: tuple[str, ...] = ()
        self.light = self.texture = self.mood = ""


def _corpus(n: int = 200) -> list[_FakeEntry]:
    """Rows sharing a common vocabulary plus one phrase unique to each.

    The shared half is what makes the set non-trivial: a retriever cannot win by
    matching any word, only by matching the right document.
    """
    rng = random.Random(1)
    common = "soft light warm tone shallow depth studio portrait muted colour film grain".split()
    rows = []
    for i in range(n):
        filler = " ".join(rng.sample(common, 8))
        rows.append(
            _FakeEntry(f"{filler} unique{i}alpha unique{i}beta unique{i}gamma unique{i}delta")
        )
    return rows


class DerivationRule(unittest.TestCase):
    def test_A_QUERY_NEVER_CONTAINS_ITS_OWN_ANSWER(self) -> None:
        """The load-bearing property. A set that quotes the target in the query
        scores an echo as a retrieval."""
        gold = ec.build_gold(_corpus(), rows=20)
        assert len(gold) == 20
        for row in gold:
            for word in row["must_retrieve"][0].split():
                assert word not in row["query"].split(), (
                    f"the target word {word!r} leaked into the query {row['query']!r}"
                )

    def test_every_target_is_unique_to_one_document(self) -> None:
        """A target that several rows carry is answerable by retrieving anything,
        so it would measure nothing."""
        rows = _corpus()
        texts = [r.text.lower() for r in rows]
        for row in ec.build_gold(rows, rows=20):
            target = row["must_retrieve"][0]
            assert sum(1 for t in texts if target in t) == 1

    def test_the_same_seed_derives_the_same_set(self) -> None:
        """A gold set that moves between runs measures the weather. Two builds,
        same corpus, same seed — identical rows."""
        rows = _corpus()
        assert ec.build_gold(rows, rows=15) == ec.build_gold(rows, rows=15)

    def test_a_different_seed_derives_a_different_set(self) -> None:
        """The other edge: if the seed did nothing, `SEED` would be decoration
        and the determinism above would be vacuous."""
        rows = _corpus()
        assert ec.build_gold(rows, rows=15) != ec.build_gold(rows, rows=15, seed=999)


class TheInstrumentCanFail(unittest.TestCase):
    def test_THE_NEGATIVE_CONTROL_a_random_retriever_scores_far_below_the_margin(self) -> None:
        """Rule I5. Measured on the real corpus 2026-08-28: the shipped retriever
        scores 0.4667 while five rows drawn at random score 0.0000. If a random
        picker could clear the bar, the number would not be about retrieval."""
        rows = _corpus()
        gold = ec.build_gold(rows, rows=20)
        as_rows = [ec._as_row(r) for r in rows]
        rng = random.Random(7)
        random_recall = sum(
            ec._recall(rng.sample(as_rows, 5), g["must_retrieve"]) for g in gold
        ) / len(gold)
        assert random_recall < 0.10, random_recall

    def test_a_perfect_answer_scores_one(self) -> None:
        """The other half of the control. If handing the instrument the right
        document did NOT score 1.0, the scorer would be broken and the low
        random number above would prove nothing."""
        rows = _corpus()
        gold = ec.build_gold(rows, rows=10)
        as_rows = [ec._as_row(r) for r in rows]
        for g in gold:
            target = g["must_retrieve"][0]
            holder = [r for r in as_rows if target in r["text"].lower()]
            assert ec._recall(holder, g["must_retrieve"]) == 1.0

    def test_an_absent_corpus_is_COULD_NOT_MEASURE_and_never_a_pass(self) -> None:
        """Rule R2, and the reason this script cannot run in CI: the corpus is
        deliberately not committed, so a CI run has nothing to measure and must
        say so rather than print a green light over an empty index."""
        index = K.build_index(gallery_prompts=Path("/nowhere/gallery.jsonl"))  # type: ignore[attr-defined]
        out = ec.report(index=index)
        assert out["outcome"] == UNMEASURED, out
        assert out["checked"] == 0
        assert out["unmeasured"] == 1


if __name__ == "__main__":
    unittest.main()
