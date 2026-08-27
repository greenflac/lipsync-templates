"""The consultant: does it refuse to vote, refuse to guess, and refuse a bad claim?

Every test here writes to a temporary fact file. None of them touches the real
knowledge base, and none of them reaches the network — the module cannot, and
the tests must not pretend otherwise.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock
from datetime import date, timedelta
from pathlib import Path

from studio.mcp import advice
from studio.selfrag import source_hosts

# The fictional vendor these tests record against. Declared here rather than
# leaned on: since 2026-08-27 the identity rungs are read off the URL, so a
# model whose vendor hosts nobody has declared cannot be recorded at `vendor`
# tier at all — which is the point of the rule and is covered below.
TEST_VENDOR_SOURCES = {"test-model": ("vendor.test", "example.test")}


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def _fact(**over: object) -> dict:
    row = {
        "model": "test-model",
        "attribute": "max_seconds",
        "value": "10",
        "source_url": "https://example.test/a",
        "tier": "vendor",
        "stated_on": date.today().isoformat(),
        "note": "",
        "fix": "",
    }
    row.update(over)  # type: ignore[arg-type]
    return row


class Consultant(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        patcher = mock.patch.dict(source_hosts.VENDOR_SOURCES, TEST_VENDOR_SOURCES, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_vendor_tier_on_a_url_the_vendor_does_not_own_is_refused(self) -> None:
        """The rule that keeps the ladder honest, added 2026-08-27.

        Before the identity rungs were read off the URL, `blog` held nine
        vendor pages and eleven platform pages, because the tier was whatever
        the recorder typed.
        """
        path = self.tmp / "facts.jsonl"
        out = advice.record(
            "test-model",
            "resolution",
            "1080p",
            "https://some-magazine.test/review",
            "vendor",
            "2026-08-01",
            path=path,
        )
        assert out["outcome"] == "fail"
        assert out["written"] is None
        assert "some-magazine.test" in out["note"], "name the host that was judged"
        assert not path.exists() or path.read_text(encoding="utf-8") == ""

    def test_the_same_claim_at_the_tier_the_url_earns_is_written(self) -> None:
        path = self.tmp / "facts.jsonl"
        out = advice.record(
            "test-model",
            "resolution",
            "1080p",
            "https://some-magazine.test/review",
            "blog",
            "2026-08-01",
            path=path,
        )
        assert out["outcome"] == "pass", "the finding is kept; only the rung was wrong"

    def test_a_model_with_no_declared_vendor_cannot_claim_one(self) -> None:
        path = self.tmp / "facts.jsonl"
        out = advice.record(
            "model-nobody-has-tabled",
            "resolution",
            "1080p",
            "https://vendor.test/docs",
            "vendor",
            "2026-08-01",
            path=path,
        )
        assert out["outcome"] == "fail"
        assert "source_hosts.py" in out["note"], "say where the table is"

    def test_a_method_tier_survives_a_url_that_says_vendor(self) -> None:
        """`probe` on the vendor's own API is the case this protects.

        The API host classifies as `vendor` — it IS the vendor's — but the rung
        the row earns is `probe`, because what makes it a probe is that
        somebody asked it, and no URL can say whether anybody did. Reading the
        rung off the URL here would erase the distinction between the vendor's
        documentation and the vendor's API answering.
        """
        path = self.tmp / "facts.jsonl"
        out = advice.record(
            "test-model",
            "duration",
            "10",
            "https://vendor.test/v1/videos",
            "probe",
            "2026-08-01",
            read_directly=True,
            path=path,
        )
        assert out["outcome"] == "pass"
        assert out["written"]["tier"] == "probe", "not rewritten to what the host is"

    def test_reading_is_recorded_in_three_states_not_two(self) -> None:
        path = self.tmp / "facts.jsonl"
        for flag in (True, False, None):
            advice.record(
                "test-model",
                f"attr_{flag}",
                "v",
                "https://vendor.test/docs",
                "vendor",
                "2026-08-01",
                read_directly=flag,
                path=path,
            )
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        assert [r["read_directly"] for r in rows] == [True, False, None], (
            "None means nobody recorded it; folding it into False invents evidence"
        )

    def test_an_unknown_model_is_could_not_measure_never_fail(self) -> None:
        path = self.tmp / "facts.jsonl"
        _write(path, [_fact()])
        out = advice.advise("no-such-model-9000", path=path)
        assert out["outcome"] == "could not measure"
        assert out["checked"] == 0
        assert "search the web" in out["note"].lower()

    def test_disagreeing_sources_fail_and_both_sides_are_returned(self) -> None:
        path = self.tmp / "facts.jsonl"
        _write(
            path,
            [
                _fact(value="10", source_url="https://example.test/a", tier="vendor"),
                _fact(value="15", source_url="https://example.test/b", tier="paper"),
            ],
        )
        out = advice.advise("test-model", path=path)
        assert out["outcome"] == "fail"
        assert out["contested"] == ["max_seconds"]
        values = out["claims"]["max_seconds"]["values"]
        assert sorted(values) == ["10", "15"], "neither side may be dropped"

    def test_agreeing_sources_pass(self) -> None:
        path = self.tmp / "facts.jsonl"
        _write(
            path,
            [
                _fact(value="10", source_url="https://example.test/a", tier="vendor"),
                _fact(value="10", source_url="https://example.test/b", tier="paper"),
            ],
        )
        out = advice.advise("test-model", path=path)
        assert out["outcome"] in {"pass", "could not measure"}
        assert out["contested"] == []

    def test_blog_only_claims_never_reach_pass(self) -> None:
        path = self.tmp / "facts.jsonl"
        _write(
            path,
            [
                _fact(value="10", source_url="https://blog.test/a", tier="blog"),
                _fact(value="10", source_url="https://blog.test/b", tier="blog"),
                _fact(value="10", source_url="https://blog.test/c", tier="blog"),
            ],
        )
        out = advice.advise("test-model", path=path)
        assert out["outcome"] == "could not measure", (
            "three blogs repeating each other are one source, not corroboration"
        )

    def test_record_writes_a_good_claim_and_it_is_visible_at_once(self) -> None:
        path = self.tmp / "facts.jsonl"
        out = advice.record(
            "test-model",
            "resolution",
            "1080p",
            "https://vendor.test/docs",
            "vendor",
            "2026-08-01",
            path=path,
        )
        assert out["outcome"] == "pass"
        assert path.read_text(encoding="utf-8").count("\n") == 1
        again = advice.advise("test-model", "resolution", path=path)
        assert again["claims"]["resolution"]["values"] == ["1080p"]

    def test_record_refuses_every_missing_field_and_writes_nothing(self) -> None:
        path = self.tmp / "facts.jsonl"
        good = dict(
            model="test-model",
            attribute="resolution",
            value="1080p",
            source_url="https://vendor.test/docs",
            tier="vendor",
            stated_on="2026-08-01",
        )
        for field in good:
            broken = dict(good)
            broken[field] = ""
            out = advice.record(path=path, **broken)  # type: ignore[arg-type]
            assert out["outcome"] == "fail", f"a blank {field} must be refused"
            assert out["written"] is None
        assert not path.exists() or path.read_text(encoding="utf-8") == ""

    def test_record_refuses_a_tier_it_does_not_know(self) -> None:
        out = advice.record(
            "test-model",
            "resolution",
            "1080p",
            "https://vendor.test/docs",
            "twitter",
            "2026-08-01",
            path=self.tmp / "f.jsonl",
        )
        assert out["outcome"] == "fail"
        assert "twitter" in out["note"]

    def test_record_refuses_a_source_that_is_not_a_url(self) -> None:
        out = advice.record(
            "test-model",
            "resolution",
            "1080p",
            "vendor.test/docs",
            "vendor",
            "2026-08-01",
            path=self.tmp / "f.jsonl",
        )
        assert out["outcome"] == "fail"

    def test_record_refuses_a_date_that_is_not_a_date_or_is_ahead(self) -> None:
        ahead = (date.today() + timedelta(days=1)).isoformat()
        for bad in ("yesterday", "01-08-2026", ahead):
            out = advice.record(
                "test-model",
                "resolution",
                "1080p",
                "https://vendor.test/docs",
                "vendor",
                bad,
                path=self.tmp / "f.jsonl",
            )
            assert out["outcome"] == "fail", f"{bad!r} must be refused"

    def test_stale_counts_old_and_undated_separately(self) -> None:
        path = self.tmp / "facts.jsonl"
        old = (date.today() - timedelta(days=400)).isoformat()
        _write(
            path,
            [
                _fact(value="10", source_url="https://a.test", stated_on=old),
                _fact(value="10", source_url="https://b.test", stated_on=""),
                _fact(value="10", source_url="https://c.test"),
            ],
        )
        out = advice.stale(days=90, path=path)
        assert out["outcome"] == "fail"
        assert out["violations"] == 1, "one claim is past the age limit"
        assert out["unmeasured"] == 1, "an undated claim is not a fresh one"
        assert out["checked"] == 3

    def test_stale_on_an_empty_base_is_could_not_measure(self) -> None:
        out = advice.stale(path=self.tmp / "missing.jsonl")
        assert out["outcome"] == "could not measure"
        assert out["checked"] == 0


if __name__ == "__main__":
    unittest.main()
