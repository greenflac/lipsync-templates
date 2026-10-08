"""The prompt writer: does it stay inside the contract, and refuse rather than guess?

The precedents here are hand-written fixtures, not the real corpus. A test that
depends on 4601 live rows measures the corpus, not the code, and changes its
verdict the day somebody adds a row.
"""

from __future__ import annotations

import unittest

from studio.mcp import lipsync_prompt as lp

# MIN_SUPPORT is 2 as of 2026-08-27. Written as a literal so that changing the
# module's constant makes these tests fail rather than follow along.
SUPPORT_FLOOR = 2


def _row(text: str, source: str) -> dict:
    return {"text": text, "source": source}


# Two precedents agreeing on ivory, soft light and matte; one outlier on teal.
AGREEING = [
    _row("ivory walls in soft light, matte plaster surface", "rec-a"),
    _row("soft ivory drapes, a matte ceramic bowl", "rec-b"),
    _row("teal glass under hard studio light, glossy", "rec-c"),
]

LONELY = [_row("teal glass under hard studio light, glossy", "rec-c")]


class PromptWriter(unittest.TestCase):
    def test_the_support_floor_is_what_the_module_says_it_is(self) -> None:
        assert lp.MIN_SUPPORT == SUPPORT_FLOOR

    def test_what_the_owner_named_is_read_in_the_engines_vocabulary(self) -> None:
        named = lp.read_intent("muted ivory and slate, low-key light, matte finish")
        assert named["palette"] == ["ivory", "slate"]
        assert named["light"] == ["low-key"]
        assert named["texture"] == ["matte"]
        assert named["saturation"] == "muted"

    def test_a_fully_named_intent_needs_no_corpus_at_all(self) -> None:
        out = lp.write("muted ivory and slate, low-key light, matte", [])
        assert out["outcome"] == "pass"
        assert out["card"] == {
            "colours": ["ivory", "slate"],
            "value_key": "dark",
            "saturation": "muted",
            "texture": "matte",
        }
        assert out["gate"]["outcome"] == "pass"

    def test_the_corpus_fills_only_what_the_owner_left_silent(self) -> None:
        out = lp.write("muted, low-key light", AGREEING)
        assert out["outcome"] == "pass"
        assert out["card"]["colours"][0] == "ivory", "two precedents agreed on ivory"
        assert out["card"]["texture"] == "matte"
        assert out["chosen"]["palette"]["from"] == "corpus"
        assert out["chosen"]["value_key"]["from"] == "owner"

    def test_the_owner_is_never_overruled_by_a_vote(self) -> None:
        # Every precedent says soft light and matte; the owner said low-key.
        out = lp.write("muted ivory, low-key light, glossy", AGREEING)
        assert out["card"]["value_key"] == "dark"
        assert out["card"]["texture"] == "glossy"

    def test_a_single_precedent_is_not_enough_to_decide(self) -> None:
        out = lp.write("muted, low-key light", LONELY)
        assert out["outcome"] == "could not measure", (
            "one precedent saying teal is a coincidence, not evidence"
        )
        assert [row["slot"] for row in out["unresolved"]] == ["palette", "texture"]

    def test_an_unresolved_slot_returns_a_question_and_no_prompt(self) -> None:
        out = lp.write("ivory and slate", [])
        assert out["outcome"] == "could not measure"
        assert out["prompt"] is None
        slots = {row["slot"] for row in out["unresolved"]}
        assert slots == {"value_key", "texture", "saturation"}
        for row in out["unresolved"]:
            assert row["ask"].endswith("?") or ":" in row["ask"]

    def test_saturation_is_never_defaulted_because_no_corpus_field_carries_it(self) -> None:
        out = lp.write("ivory, low-key light, matte", AGREEING)
        assert out["outcome"] == "could not measure"
        assert [row["slot"] for row in out["unresolved"]] == ["saturation"]

    def test_an_empty_intent_still_asks_all_four_questions(self) -> None:
        # Somebody who said nothing needs the questions MOST. An earlier version
        # short-circuited the empty case and handed back an empty `unresolved`.
        out = lp.write("   ", [])
        assert out["outcome"] == "could not measure"
        assert out["prompt"] is None
        assert [row["slot"] for row in out["unresolved"]] == [
            "palette",
            "value_key",
            "texture",
            "saturation",
        ]
        assert out["checked"] == 4, "four slots were examined, and none was filled"

    def test_a_named_colour_is_never_topped_up_from_the_corpus(self) -> None:
        # Substitution only: the owner named two colours, so the palette is two
        # colours. Adding a third from precedent is an addition, not a fill.
        shouting = [
            _row("crimson and gold walls, low-key light, matte", f"rec-{n}") for n in (1, 2, 3)
        ]
        out = lp.write("muted teal and slate, low-key light, matte", shouting)
        assert out["card"]["colours"] == ["slate", "teal"]
        assert out["chosen"]["palette"]["from"] == "owner"
        assert out["chosen"]["palette"]["record_ids"] == [], (
            "a slot the owner filled must not carry corpus ids: the label would lie"
        )

    def test_saturation_is_corroborated_from_the_corpus_like_every_other_slot(self) -> None:
        two = [
            _row("muted desaturated restrained colour, soft light, matte", "a"),
            _row("muted desaturated restrained colour, soft light, matte", "b"),
        ]
        out = lp.write("ivory", two)
        assert out["outcome"] == "pass"
        assert out["card"]["saturation"] == "muted"
        assert out["chosen"]["saturation"]["record_ids"] == ["a", "b"]

    def test_one_record_cannot_fill_saturation_either(self) -> None:
        lonely = [_row("muted desaturated colour, soft light, matte", "a")]
        out = lp.write("ivory", lonely)
        assert out["outcome"] == "could not measure"
        assert "saturation" in [row["slot"] for row in out["unresolved"]]

    def test_a_written_prompt_never_names_the_subject(self) -> None:
        out = lp.write("muted ivory and slate, low-key light, matte", [])
        assert out["gate"]["leak"] == []
        assert out["gate"]["outcome"] == "pass"

    def test_too_many_colours_is_a_question_not_a_silent_truncation(self) -> None:
        # The engine takes three and drops the rest without a word. Dropping a
        # colour the owner named is exactly the silent repair this refuses.
        out = lp.write("muted amber and charcoal and copper and crimson, low-key light, matte", [])
        assert out["outcome"] == "could not measure"
        assert out["prompt"] is None
        ask = [row["ask"] for row in out["unresolved"] if row["slot"] == "palette"]
        assert ask and "Which 3?" in ask[0]

    def test_three_colours_is_still_fine(self) -> None:
        out = lp.write("muted amber and charcoal and copper, low-key light, matte", [])
        assert out["outcome"] == "pass"
        assert out["card"]["colours"] == ["amber", "charcoal", "copper"]

    def test_every_corpus_filled_slot_carries_the_records_that_voted_for_it(self) -> None:
        out = lp.write("muted, low-key light", AGREEING)
        assert out["chosen"]["palette"]["record_ids"], "a corpus choice with no source is a guess"
        assert set(out["chosen"]["texture"]["record_ids"]) == {"rec-a", "rec-b"}


if __name__ == "__main__":
    unittest.main()
