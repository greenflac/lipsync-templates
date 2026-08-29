"""Two lanes, and a query the search can actually read.

WHAT THESE GUARD, AND WHY IT IS NOT PROSE

Three defects were found on 2026-08-28 by a critic reviewing the record design,
reproduced by hand, and fixed. Each one is here as a test, because a rule that
can be broken observably does not belong in a comment (house rule C7).

1. THE TOKENIZER COULD NOT READ RUSSIAN. `_WORD` matched Latin only, so
   `query_terms` on a Russian question returned [], every channel admitted
   nothing, and `retrieve` answered `fail` — "nothing in the index clears the
   relevance floor". That is the system claiming it searched 5074 entries and
   found nothing relevant, when it had not been able to read the question. Our
   operators write in Russian.

2. AN UNSEARCHABLE QUERY GOT A CONFIDENT ANSWER. The empty string got the same
   `fail` as a real question. "I could not search this" and "there is nothing
   here" are different answers (rule R1).

3. THE QUOTA STARVED THE KNOWLEDGE LANE. MEASURED by the critic: with 300
   knowledge records under one provenance, `retrieve(k=8)` returned 2 and turned
   away 298. Right for 4601 prompts from one gallery; wrong for records that are
   each a different mechanism.

Expected values are literals, not imports from the module under test (rule T2).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

# `studio/knowledge.py` (module) and `studio/knowledge/` (data directory) share
# a name: at runtime the module wins, for the type checker the directory does.
# The repository's existing workaround is a named import with the ignore on it
# (see studio/mcp/lipsync_prompt.py), not a bare module alias.
from studio.knowledge import (  # type: ignore[attr-defined]
    MAX_PER_PROVENANCE,
    MAX_PER_PROVENANCE_KNOWLEDGE,
    build_index,
    provenance_weight,
    query_terms,
    retrieve,
)

NOWHERE = Path("/nowhere/craft")


def _record(rid: str, title: str, claim: str, provenance: str = "vendor:test") -> dict:
    return {
        "id": rid,
        "title": title,
        "question": [title],
        "claim": claim,
        "provenance": provenance,
        "evidence": [{"url": "https://example.invalid/x", "tier": "vendor"}],
    }


class TheTokenizerReadsRussian(unittest.TestCase):
    def test_a_russian_question_yields_terms(self) -> None:
        """THE DEFECT. Before the fix this returned []."""
        terms = query_terms("почему кожа пластиковая на портрете")
        assert terms, "русский запрос не дал ни одного термина"
        assert "кожа" in terms, terms

    def test_english_still_tokenizes_unchanged(self) -> None:
        """The other edge. Widening the pattern must not break what worked."""
        assert query_terms("warm golden hour light") == ["warm", "golden", "hour", "light"]

    def test_a_mixed_query_keeps_both_alphabets(self) -> None:
        terms = query_terms("какой параметр guidance у flux")
        assert "guidance" in terms and "параметр" in terms, terms


class AnUnsearchableQueryIsNotAFailure(unittest.TestCase):
    def setUp(self) -> None:
        self.index = build_index(craft_records=NOWHERE)

    def test_the_empty_string_is_COULD_NOT_MEASURE(self) -> None:
        """Before the fix this was `fail`: the index reporting a verdict on a
        question it never read."""
        out = retrieve("", index=self.index)
        assert out["outcome"] == UNMEASURED, out["note"]
        assert out["checked"] == 0

    def test_whitespace_is_COULD_NOT_MEASURE(self) -> None:
        assert retrieve("   ", index=self.index)["outcome"] == UNMEASURED

    def test_THE_NEGATIVE_CONTROL_a_real_query_that_matches_nothing_is_still_FAIL(self) -> None:
        """Rule I5, and the edge that matters most. If everything unmatched
        became `could not measure`, the index could never say "nothing here" and
        the third outcome would have eaten the second."""
        out = retrieve("zzqqxx flurbulator sprocketing", index=self.index)
        assert out["outcome"] == FAIL, out["note"]
        assert out["checked"] > 0, "a real query must be recorded as searched"


class TwoLanes(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.craft = Path(self._dir.name)
        rows = [
            _record(
                "r1",
                "Почему кожа читается как силикон",
                "без подповерхностного рассеивания кожа выглядит пластиковой",
            ),
            _record("r2", "Пережжённая кожа при высоком CFG", "контраст уезжает в один тон"),
        ]
        (self.craft / "craft_t.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
        )

    def test_knowledge_comes_back_in_its_own_list(self) -> None:
        """The whole point of not guessing intent: a caller sees both lanes and
        picks, instead of a router deciding for it from marker words."""
        index = build_index(craft_records=self.craft)
        out = retrieve("почему кожа пластиковая", index=index)
        assert out["outcome"] == PASS, out["note"]
        assert out["knowledge"], "полоса знания пуста"
        assert all(e["kind"] == "knowledge" for e in out["knowledge"])
        assert all(e["kind"] != "knowledge" for e in out["examples"])

    def test_THE_NEGATIVE_CONTROL_without_the_lane_the_same_question_fails(self) -> None:
        """Without this, the test above would pass on any index that happened to
        answer, and would prove nothing about the lane."""
        index = build_index(craft_records=NOWHERE)
        out = retrieve("почему кожа пластиковая", index=index)
        assert out["outcome"] == FAIL, out["note"]
        assert out["knowledge"] == []

    def test_an_english_prompt_query_still_returns_prompts(self) -> None:
        """No regression: adding a lane must not cost the one that worked."""
        index = build_index(craft_records=self.craft)
        out = retrieve("warm golden hour amber palette film grain", index=index)
        assert out["outcome"] == PASS
        assert out["examples"], "промты пропали из выдачи"

    def test_neither_lane_exceeds_k(self) -> None:
        """OBSERVED while writing this: the first version ran until BOTH lanes
        were full and returned 43 examples for k=5."""
        index = build_index(craft_records=self.craft)
        out = retrieve("warm golden hour amber palette", index=index, k=3)
        assert len(out["examples"]) <= 3
        assert len(out["knowledge"]) <= 3


class TheQuotas(unittest.TestCase):
    def test_the_two_lanes_have_DIFFERENT_caps_and_knowledge_gets_the_larger(self) -> None:
        """Literals, not imports (rule T2). If somebody equalises the caps, the
        knowledge lane goes back to answering with two records out of six
        mechanisms, and this is the test that says so."""
        assert MAX_PER_PROVENANCE == 2
        assert MAX_PER_PROVENANCE_KNOWLEDGE == 6
        assert MAX_PER_PROVENANCE_KNOWLEDGE > MAX_PER_PROVENANCE

    def test_a_knowledge_provenance_outweighs_the_gallery(self) -> None:
        """The critic measured the bug: `vendor:comfyui` fell to the unknown-
        family fallback of 0.5, BELOW the third-party gallery it is meant to
        outrank. A vendor's own documentation is not worth less than a
        stranger's prompt."""
        assert provenance_weight("vendor:comfyui") > provenance_weight("third_party_gallery")
        assert provenance_weight("knowledge:anything") > provenance_weight("gallery")

    def test_an_unknown_family_still_falls_back_below_everything(self) -> None:
        """The other edge: the fallback must keep working, or an unclassified
        provenance could outrank a classified one."""
        assert provenance_weight("whoknows:someone") == 0.5


if __name__ == "__main__":
    unittest.main()
