"""The consultant: does it refuse to vote, refuse to guess, and refuse a bad claim?

Every test here writes to a temporary fact file. None of them touches the real
knowledge base, and none of them reaches the network — the module cannot, and
the tests must not pretend otherwise.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from studio.mcp import advice


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
