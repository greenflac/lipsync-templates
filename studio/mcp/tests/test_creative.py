"""The creative analyser: does it name only what the pixels carry?

Every fixture is generated here with Pillow, so the tests need no assets and no
network. Expected values are literals (house rule T2).

The tests that matter most are the negative controls (house rule I5). An
instrument that names a lighting word for every image, or a palette word for
every colour, would look exactly like a working one in its output — so a
mid-grey frame must come back with NO lighting word, and a crimson frame must
not be called teal.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from studio.mcp import creative


def _solid(path: Path, rgb: tuple[int, int, int], size: tuple[int, int] = (64, 64)) -> str:
    Image.new("RGB", size, rgb).save(path)
    return str(path)


class Look(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def test_a_dark_frame_is_low_key_and_a_bright_one_is_high_key(self) -> None:
        dark = creative.look(_solid(self.tmp / "d.png", (10, 10, 10)))
        bright = creative.look(_solid(self.tmp / "b.png", (245, 245, 245)))
        assert dark["light"] == "low-key"
        assert bright["light"] == "high-key"

    def test_a_mid_grey_frame_is_named_NEITHER(self) -> None:
        """The negative control. Without it the thresholds could be anything at
        all and every test above would still pass — an instrument that always
        answers is one that measures nothing."""
        mid = creative.look(_solid(self.tmp / "m.png", (128, 128, 128)))
        assert mid["light"] == "", f"a mid-grey frame was called {mid['light']!r}"
        assert mid["unmeasured"] >= 2, "the unnamed lighting axis is counted, not ignored"

    def test_the_thresholds_hold_on_both_sides(self) -> None:
        """Literal values either side of each bar, so moving a bar goes red."""
        just_under = creative.look(_solid(self.tmp / "u.png", (160, 160, 160)))
        just_over = creative.look(_solid(self.tmp / "o.png", (200, 200, 200)))
        assert just_under["light"] == ""
        assert just_over["light"] == "high-key"
        just_above_low = creative.look(_solid(self.tmp / "a.png", (100, 100, 100)))
        well_below = creative.look(_solid(self.tmp / "w.png", (40, 40, 40)))
        assert just_above_low["light"] == ""
        assert well_below["light"] == "low-key"

    def test_a_colour_is_named_with_the_prompt_writers_own_word(self) -> None:
        out = creative.look(_solid(self.tmp / "c.png", (220, 20, 60)))
        assert out["palette"] == ["crimson"]

    def test_a_colour_is_NOT_named_something_it_is_not(self) -> None:
        """The other half of the control: a naming function that returns the
        same word for everything would satisfy the test above."""
        out = creative.look(_solid(self.tmp / "t.png", (0, 128, 128)))
        assert out["palette"] == ["teal"]
        assert "crimson" not in out["palette"]

    def test_at_most_three_colours_are_named(self) -> None:
        """A StyleSpec palette holds three; more would be an answer nobody can
        use. Built from six distinct bands so the quantiser really finds more."""
        path = self.tmp / "many.png"
        image = Image.new("RGB", (60, 60))
        bands = [
            (220, 20, 60),
            (0, 128, 128),
            (255, 176, 0),
            (75, 0, 130),
            (0, 155, 119),
            (214, 190, 148),
        ]
        for index, colour in enumerate(bands):
            image.paste(Image.new("RGB", (60, 10), colour), (0, index * 10))
        image.save(path)
        out = creative.look(str(path))
        assert len(out["palette"]) == 3
        assert len(set(out["palette"])) == 3, "a repeated word is not a second colour"

    def test_two_shades_of_one_word_are_one_palette_entry(self) -> None:
        """Found by mutation: dropping the de-duplication stayed green, because
        the six-band fixture happened to produce six distinct words. Here two
        bands are both nearest to `charcoal`, so a collector that appends
        blindly reports charcoal twice and never reaches the third colour."""
        path = self.tmp / "dupes.png"
        image = Image.new("RGB", (60, 60))
        bands = [(54, 57, 61), (58, 61, 65), (220, 20, 60)]
        for index, colour in enumerate(bands):
            image.paste(Image.new("RGB", (60, 20), colour), (0, index * 20))
        image.save(path)
        out = creative.look(str(path))
        assert out["palette"].count("charcoal") == 1, out["palette"]
        assert "crimson" in out["palette"], out["palette"]

    def test_grain_is_measured_before_the_image_is_shrunk_for_the_statistics(self) -> None:
        """Found by mutation: measuring grain on the 256px sample stayed green,
        because every other fixture is flat and reads zero either way.
        Resampling is exactly what destroys high-frequency detail, so a grain
        number taken from a thumbnail measures the resampler and not the
        creative. Vertical one-pixel stripes are the sharpest thing a grain
        statistic along x can be given."""
        path = self.tmp / "stripes.png"
        image = Image.new("RGB", (512, 512))
        for x in range(0, 512, 2):
            for y in range(512):
                image.putpixel((x, y), (255, 255, 255))
        image.save(path)
        grain = creative.look(str(path))["measurements"]["grain"]
        # At native size every neighbouring pair differs by the full range.
        assert grain > 200.0, f"stripes read as grain {grain}"

    def test_saturation_is_pinned_at_both_ends_and_in_the_middle(self) -> None:
        """Three-point control. Every image gets a saturation word, unlike
        lighting, so both ends AND the middle have to be pinned — an
        instrument that always answers is only trustworthy if the answer moves
        with the input."""
        grey = creative.look(_solid(self.tmp / "g.png", (128, 128, 128)))
        primary = creative.look(_solid(self.tmp / "p.png", (255, 0, 0)))
        middle = creative.look(_solid(self.tmp / "mid.png", (200, 140, 90)))
        assert grey["saturation"] == "muted"
        assert primary["saturation"] == "saturated"
        assert middle["saturation"] == "moderate"

    def test_the_saturation_words_are_the_prompt_cards_own(self) -> None:
        """Literal, so a rename in the card goes red here rather than producing
        a word `write_lipsync_prompt` will not recognise."""
        from studio.mcp.lipsync_prompt import SATURATION_CUES

        assert sorted(SATURATION_CUES) == ["moderate", "muted", "saturated"]

    def test_mood_is_never_named(self) -> None:
        """Nothing in a histogram says `melancholic`. A word here would be
        indistinguishable in the output from one somebody measured."""
        for rgb in ((10, 10, 10), (245, 245, 245), (220, 20, 60)):
            out = creative.look(_solid(self.tmp / f"{rgb[0]}.png", rgb))
            assert out["mood"] is None
            assert "mood NOT measurable" in out["note"]

    def test_a_missing_file_is_could_not_measure_not_fail(self) -> None:
        out = creative.look(self.tmp / "nope.png")
        assert out["outcome"] == "could not measure"
        assert out["palette"] == []

    def test_a_file_that_is_not_an_image_is_could_not_measure(self) -> None:
        broken = self.tmp / "broken.png"
        broken.write_text("this is not a PNG", encoding="utf-8")
        out = creative.look(broken)
        assert out["outcome"] == "could not measure"
        assert "could not be decoded" in out["note"]

    def test_the_numbers_the_words_came_from_are_returned(self) -> None:
        """So a reader can disagree with the naming instead of taking it."""
        out = creative.look(_solid(self.tmp / "n.png", (10, 10, 10), size=(90, 160)))
        m = out["measurements"]
        assert m["width"] == 90 and m["height"] == 160
        assert m["aspect"] == 0.5625, "9:16, the frame the product targets"
        assert m["luminance_mean"] < 85.0
        assert "saturation" in m and "grain" in m

    def test_a_flat_colour_has_no_grain(self) -> None:
        """The negative control for the grain statistic: a synthetic solid must
        read as zero, or the number is measuring the resampler."""
        out = creative.look(_solid(self.tmp / "flat.png", (120, 90, 60)))
        assert out["measurements"]["grain"] == 0.0


class Motion(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def _frames(self, count: int, *, loop: bool) -> list[str]:
        paths = []
        for index in range(count):
            # A loop returns to where it started; a drift does not.
            shift = index if not loop else min(index, count - 1 - index)
            image = Image.new("RGB", (64, 64), (20, 20, 20))
            image.paste(Image.new("RGB", (8, 8), (240, 240, 240)), (shift * 3, 20))
            path = self.tmp / f"{index:03d}.png"
            image.save(path)
            paths.append(str(path))
        return paths

    def test_two_frames_cannot_be_judged_and_says_so(self) -> None:
        out = creative.motion_of(self._frames(2, loop=False))
        assert out["outcome"] == "could not measure"
        assert "at least 3" in out["note"]

    def test_a_clip_that_returns_where_it_started_passes(self) -> None:
        out = creative.motion_of(self._frames(9, loop=True))
        assert out["outcome"] == "pass"
        assert out["loop"]["seamless"] is True

    def test_a_clip_that_drifts_away_fails(self) -> None:
        """The negative control: without it a motion check that always passed
        would look identical in the output."""
        out = creative.motion_of(self._frames(9, loop=False))
        assert out["outcome"] == "fail"
        assert out["violations"] == 1


class Analyse(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def test_an_instrument_that_could_not_run_is_named_not_skipped(self) -> None:
        """The reason this returns a list rather than a count: an answer with
        no violations and a silent instrument is not a clean creative."""
        out = creative.analyse(_solid(self.tmp / "x.png", (10, 10, 10)))
        names = [item["instrument"] for item in out["could_not_run"]]
        assert "intake" in names, "no face model here, and it must say so"
        assert out["unmeasured"] > 0
        assert "NOT RUN: intake" in out["note"]

    def test_a_creative_nothing_could_be_measured_on_is_could_not_measure(self) -> None:
        """Never `pass`. Zero violations out of zero checks is the failure mode
        this whole package is built against."""
        out = creative.analyse(self.tmp / "missing.png")
        assert out["outcome"] == "could not measure"
        assert out["checked"] == 0
        assert out["violations"] == 0

    def test_motion_is_only_attempted_when_frames_are_given(self) -> None:
        """An mp4 cannot be decoded here, so a caller with a video passes
        frames. Without them the motion axis is absent, not failed."""
        alone = creative.analyse(_solid(self.tmp / "a.png", (10, 10, 10)))
        assert "motion" not in alone["parts"]

    def test_a_violation_anywhere_makes_the_whole_creative_fail(self) -> None:
        frames = []
        for index in range(9):
            image = Image.new("RGB", (64, 64), (20, 20, 20))
            image.paste(Image.new("RGB", (8, 8), (240, 240, 240)), (index * 3, 20))
            path = self.tmp / f"f{index}.png"
            image.save(path)
            frames.append(str(path))
        out = creative.analyse(frames[0], frames=frames)
        assert out["outcome"] == "fail"
        assert out["violations"] >= 1


class TheVocabularyIsImportedNotRestated(unittest.TestCase):
    def test_every_palette_word_the_prompt_writer_knows_has_an_anchor(self) -> None:
        """One knowledge, one place. A word added to `style.py` and forgotten
        here would be unnameable, and nothing else would notice."""
        from studio.style import PALETTE_WORDS

        assert set(creative.NAMED_COLOURS) == set(PALETTE_WORDS)

    def test_the_lighting_words_it_can_produce_are_in_the_allow_list(self) -> None:
        """Both are literals here, because importing the answer from the module
        under test would check nothing."""
        from studio.style import LIGHT_WORDS

        assert "high-key" in LIGHT_WORDS
        assert "low-key" in LIGHT_WORDS


if __name__ == "__main__":
    unittest.main()
