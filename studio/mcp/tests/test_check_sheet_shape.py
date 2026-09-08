"""Can the shape control be red, and can it be quiet when it should be?

Every fixture is written here as a literal (rule T2) and nothing reads the case
bank, which is gitignored — a test that needs it passes here and fails in CI.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

_SPEC = importlib.util.spec_from_file_location(
    "check_sheet_shape", Path(__file__).resolve().parents[3] / "scripts" / "check_sheet_shape.py"
)
assert _SPEC and _SPEC.loader
shape = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(shape)


def _mixed(value_a: str, value_b: str, n: int = 8) -> list[tuple[str, str, dict[str, str]]]:
    """n cases per source, sharing one property value or not sharing it.

    Both sources are VIDEO on purpose: telling a strip from a single picture is
    something a reader does by looking, and the question here is whether one
    video source can be told from another for free.
    """
    return [("kling", "video", {"высота полосы": value_a}) for _ in range(n)] + [
        ("civitai", "video", {"высота полосы": value_b}) for _ in range(n)
    ]


class APropertyThatSortsTheSourcesIsALeak(unittest.TestCase):
    def test_a_height_unique_to_each_source_is_caught(self) -> None:
        """The real risk this was written for: Kling's clips are one house
        format, Civitai's are whatever the uploader rendered, and the strip's
        height follows the aspect ratio without a pixel being read."""
        out = shape.check(_mixed("188", "336"))
        assert out["outcome"] == FAIL, out["note"]
        assert out["протекают"] == ["video: высота полосы"]
        assert out["по_признаку"]["video: высота полосы"]["доля"] == 1.0

    def test_a_shared_value_is_NOT_reported_as_a_leak(self) -> None:
        """The negative control (rule I5). Without an input on which this stays
        quiet, a control that always fires would pass its own suite."""
        out = shape.check(_mixed("188", "188"))
        assert out["outcome"] == PASS, out["note"]
        assert out["протекают"] == []
        assert out["по_признаку"]["video: высота полосы"]["доля"] == 0.0

    def test_the_tolerance_lets_a_minority_through_and_stops_a_majority(self) -> None:
        """Both edges of the decision constant, so it is a threshold and not a
        wall: three of sixteen unique is tolerated, six of sixteen is not."""
        shared = [("kling", "video", {"h": "188"}) for _ in range(8)]
        shared += [("civitai", "video", {"h": "188"}) for _ in range(5)]
        few = shared + [("civitai", "video", {"h": "999"}) for _ in range(3)]
        many = shared + [("civitai", "video", {"h": f"{i}"}) for i in range(6)]
        assert shape.check(few)["outcome"] == PASS
        assert shape.check(many)["outcome"] == FAIL


class OneSourceIsAQuestionWithNoAnswer(unittest.TestCase):
    def test_a_bank_of_one_source_says_could_not_measure_not_LEAK(self) -> None:
        """With one source every value is trivially unique to it, which would
        read as a total leak. It is an unanswerable question instead, and the
        third outcome is what says so (rule R1)."""
        only = [("kling", "video", {"высота полосы": f"{i}"}) for i in range(10)]
        out = shape.check(only)
        assert out["outcome"] == UNMEASURED, out["note"]
        assert out["violations"] == 0
        assert out["unmeasured"] == 10
        assert out["среды_с_одним_источником"] == ["video"]

    def test_an_empty_bank_is_also_could_not_measure(self) -> None:
        out = shape.check([])
        assert out["outcome"] == UNMEASURED
        assert out["checked"] == 0


class MediaAreJudgedApart(unittest.TestCase):
    """A picture is not a strip and a reader sees that by looking. What must not
    be free is telling one VIDEO source from another."""

    def test_the_only_image_source_does_not_count_as_a_leak(self) -> None:
        cases = _mixed("214", "214")
        cases += [("openfake", "image", {"высота полосы": f"{i}"}) for i in range(6)]
        out = shape.check(cases)
        assert out["outcome"] == PASS, out["note"]
        assert out["среды_с_одним_источником"] == ["image"]
        assert out["unmeasured"] == 6
        assert out["checked"] == 16

    def test_a_leak_INSIDE_the_video_medium_is_still_caught(self) -> None:
        """The negative control on the split: judging media apart must not make
        the instrument blind to the thing it was written for."""
        cases = _mixed("214", "336")
        cases += [("openfake", "image", {"высота полосы": f"{i}"}) for i in range(6)]
        out = shape.check(cases)
        assert out["outcome"] == FAIL, out["note"]
        assert out["протекают"] == ["video: высота полосы"]


class SizesAreBucketedOrEveryFileLooksUnique(unittest.TestCase):
    def test_two_clips_of_similar_size_land_in_one_bucket(self) -> None:
        """Raw byte counts are unique per file by nature and would report a leak
        on any bank at all. The literals are the two sizes, not the boundary."""
        assert shape._size_bucket(1_500_000) == shape._size_bucket(1_900_000)

    def test_a_clip_an_order_of_magnitude_bigger_does_not(self) -> None:
        """The negative control on the bucketing: if everything collapsed into
        one bucket the property would be blind rather than tolerant."""
        assert shape._size_bucket(1_500_000) != shape._size_bucket(22_000_000)


if __name__ == "__main__":
    unittest.main()
