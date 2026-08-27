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

    # -- reading a page you already cite is an update, not a second source ----
    #
    # Added 2026-08-27, the day the vendor hosts were unblocked and 25 facts
    # marked "not read" became readable. Without these, replacing a summary
    # with a reading DOUBLES the source count for a single page.

    def test_re_recording_the_same_claim_supersedes_instead_of_adding_a_source(self) -> None:
        path = self.tmp / "facts.jsonl"
        advice.record(
            "test-model",
            "max_seconds",
            "10",
            "https://vendor.test/spec",
            "vendor",
            "2026-01-05",
            note="via summary",
            read_directly=False,
            path=path,
        )
        out = advice.record(
            "test-model",
            "max_seconds",
            "10",
            "https://vendor.test/spec",
            "vendor",
            "2026-01-05",
            note="opened it",
            read_directly=True,
            path=path,
        )
        assert out["outcome"] == "pass"
        claims = advice.store_for(path).claims("test-model", "max_seconds")
        assert claims["checked"] == 1, "one page is one source however often it is read"
        assert claims["sources_not_read"] == 0
        assert out["superseded"]["read_directly"] is False, "what it replaced is returned"

    def test_the_superseded_row_stays_in_the_file(self) -> None:
        """The history of how a claim was argued survives the correction."""
        path = self.tmp / "facts.jsonl"
        advice.record(
            "test-model",
            "max_seconds",
            "10",
            "https://vendor.test/spec",
            "vendor",
            "2026-01-05",
            note="via summary",
            read_directly=False,
            path=path,
        )
        advice.record(
            "test-model",
            "max_seconds",
            "10",
            "https://vendor.test/spec",
            "vendor",
            "2026-01-05",
            note="opened it",
            read_directly=True,
            path=path,
        )
        assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 2

    def test_recording_a_row_that_changes_nothing_appends_nothing(self) -> None:
        """So a script that replays a reading pass can be re-run."""
        path = self.tmp / "facts.jsonl"
        for _ in range(3):
            out = advice.record(
                "test-model",
                "max_seconds",
                "10",
                "https://vendor.test/spec",
                "vendor",
                "2026-01-05",
                note="opened it",
                read_directly=True,
                path=path,
            )
            assert out["outcome"] == "pass"
        assert len(path.read_text(encoding="utf-8").strip().splitlines()) == 1
        assert out["written"] is None, "nothing was written, and it says so"

    def test_a_reading_flag_is_the_only_change_and_it_still_gets_written(self) -> None:
        """The mutation that caught this: dropping `read_directly` from the
        compared fields stayed GREEN, because every other supersession test
        also changed the note. Upgrading a summary to a reading changes ONLY
        this flag, and that is the whole job the reading pass does."""
        path = self.tmp / "facts.jsonl"
        advice.record(
            "test-model",
            "max_seconds",
            "10",
            "https://vendor.test/spec",
            "vendor",
            "2026-01-05",
            note="",
            read_directly=False,
            path=path,
        )
        out = advice.record(
            "test-model",
            "max_seconds",
            "10",
            "https://vendor.test/spec",
            "vendor",
            "2026-01-05",
            note="",
            read_directly=True,
            path=path,
        )
        assert out["written"] is not None, "the upgrade was not recorded at all"
        sources = advice.store_for(path).claims("test-model", "max_seconds")["claims"][0]["sources"]
        assert [s["read_directly"] for s in sources] == [True]

    def test_every_field_a_correction_can_move_is_actually_written(self) -> None:
        """Each of the five is a correction this session's reading pass made:
        `read_directly` when a summary became a reading, `stated_on` when a
        page turned out to be dated November 2025 and not the day it was
        harvested, `note` when the reading said something the summary did not,
        `tier` when a URL's rung changed, `fix` when a failure mode gained one.

        The names are LITERAL (house rule Т2) and compared against the module's
        list, so dropping one there breaks this rather than sliding past it."""
        assert advice.MUTABLE_FIELDS == ("tier", "stated_on", "note", "fix", "read_directly")
        moved: dict[str, tuple[str, str, str, str, bool]] = {
            # tier, stated_on, note, fix, read_directly
            "tier": ("probe", "2026-01-05", "", "", False),
            "stated_on": ("vendor", "2025-11-24", "", "", False),
            "note": ("vendor", "2026-01-05", "read it", "", False),
            "fix": ("vendor", "2026-01-05", "", "use 5s", False),
            "read_directly": ("vendor", "2026-01-05", "", "", True),
        }
        for field, (tier, stated_on, note, fix, read) in moved.items():
            with self.subTest(field=field):
                path = self.tmp / f"facts-{field}.jsonl"
                advice.record(
                    "test-model",
                    "max_seconds",
                    "10",
                    "https://vendor.test/spec",
                    "vendor",
                    "2026-01-05",
                    note="",
                    fix="",
                    read_directly=False,
                    path=path,
                )
                out = advice.record(
                    "test-model",
                    "max_seconds",
                    "10",
                    "https://vendor.test/spec",
                    tier,
                    stated_on,
                    note=note,
                    fix=fix,
                    read_directly=read,
                    path=path,
                )
                assert out["written"] is not None, f"a changed {field} was not written"
                assert field in out["note"], f"the caller is not told {field} moved"

    def test_two_values_from_one_page_stay_two_claims(self) -> None:
        """MEASURED in the real base: seedance2-video.com states 12 and 4-to-15
        on the same page. Keying supersession without the value would have
        dropped one and hidden a source contradicting itself."""
        path = self.tmp / "facts.jsonl"
        for value in ("12", "4 to 15"):
            advice.record(
                "test-model",
                "max_seconds",
                value,
                "https://vendor.test/spec",
                "vendor",
                "2026-01-05",
                path=path,
            )
        claims = advice.store_for(path).claims("test-model", "max_seconds")
        assert claims["outcome"] == "fail", "one page disagreeing with itself is contested"
        assert sorted(claims["values"]) == ["12", "4 to 15"]

    # -- withdrawal: the page does not say what the summary said --------------

    def test_withdrawing_a_claim_removes_it_and_keeps_the_reason(self) -> None:
        path = self.tmp / "facts.jsonl"
        advice.record(
            "test-model",
            "max_seconds",
            "10",
            "https://vendor.test/spec",
            "vendor",
            "2026-01-05",
            path=path,
        )
        out = advice.withdraw(
            "test-model",
            "max_seconds",
            "10",
            "https://vendor.test/spec",
            "the page does not mention a duration at all",
            path=path,
        )
        assert out["outcome"] == "pass"
        assert advice.store_for(path).claims("test-model", "max_seconds")["checked"] == 0
        assert "does not mention a duration" in path.read_text(encoding="utf-8")

    def test_withdrawing_something_nobody_recorded_is_could_not_measure(self) -> None:
        """Never `pass`: a caller who misspelled the model would be told it worked."""
        path = self.tmp / "facts.jsonl"
        advice.record(
            "test-model",
            "max_seconds",
            "10",
            "https://vendor.test/spec",
            "vendor",
            "2026-01-05",
            path=path,
        )
        out = advice.withdraw(
            "test-model", "max_seconds", "11", "https://vendor.test/spec", "typo", path=path
        )
        assert out["outcome"] == "could not measure"
        assert out["withdrawn"] is None
        assert advice.store_for(path).claims("test-model", "max_seconds")["checked"] == 1

    def test_a_withdrawal_without_a_reason_is_refused(self) -> None:
        """A withdrawal nobody explained is a deletion with extra steps."""
        path = self.tmp / "facts.jsonl"
        advice.record(
            "test-model",
            "max_seconds",
            "10",
            "https://vendor.test/spec",
            "vendor",
            "2026-01-05",
            path=path,
        )
        out = advice.withdraw(
            "test-model", "max_seconds", "10", "https://vendor.test/spec", "   ", path=path
        )
        assert out["outcome"] == "fail"
        assert advice.store_for(path).claims("test-model", "max_seconds")["checked"] == 1

    def test_a_withdrawn_claim_can_be_recorded_again(self) -> None:
        """A page that was misread once is not banned; the latest row wins."""
        path = self.tmp / "facts.jsonl"
        advice.record(
            "test-model",
            "max_seconds",
            "10",
            "https://vendor.test/spec",
            "vendor",
            "2026-01-05",
            path=path,
        )
        advice.withdraw(
            "test-model", "max_seconds", "10", "https://vendor.test/spec", "misread", path=path
        )
        advice.record(
            "test-model",
            "max_seconds",
            "10",
            "https://vendor.test/spec",
            "vendor",
            "2026-01-05",
            note="it does say 10",
            read_directly=True,
            path=path,
        )
        claims = advice.store_for(path).claims("test-model", "max_seconds")
        assert claims["checked"] == 1
        assert claims["claims"][0]["sources"][0]["read_directly"] is True


class ClassFindingsRideAlong(unittest.TestCase):
    """What is known about the field reaches a caller asking about a model."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        patcher = mock.patch.dict(source_hosts.VENDOR_SOURCES, TEST_VENDOR_SOURCES, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _base(self, extra: list[dict]) -> Path:
        path = self.tmp / "facts.jsonl"
        _write(path, [_fact()] + extra)
        return path

    def test_the_cap_prints_its_denominator_and_never_hides_the_rest(self) -> None:
        """A silent truncation reads as "that is all there is" (rule R2)."""
        many = [
            _fact(
                model="*",
                attribute="metric_blind_spot",
                value=f"blind spot {n}",
                source_url=f"https://arxiv.org/abs/{n}",
                tier="paper",
            )
            for n in range(30)
        ]
        out = advice.advise("test-model", path=self._base(many))
        assert len(out["class_findings"]) == advice.CLASS_FINDINGS_SHOWN
        assert out["class_findings_total"] == 30
        assert "12 of 30" in out["class_findings_note"]
        assert "NOT measured on this model" in out["class_findings_note"]

    def test_the_shown_ones_cover_the_attributes_rather_than_the_alphabet(self) -> None:
        """Found by observation: sorting by tier alone returned twelve rows of
        ONE attribute out of 170, so the cap was choosing by alphabet. A
        caller who gets twelve metric caveats and no failure mode has been
        told less than a caller who gets one of each."""
        rows = []
        for attribute in ("failure_mode", "metric_blind_spot", "degrades_when"):
            rows += [
                _fact(
                    model="*",
                    attribute=attribute,
                    value=f"{attribute} {n}",
                    source_url=f"https://arxiv.org/abs/{attribute}{n}",
                    tier="paper",
                )
                for n in range(20)
            ]
        out = advice.advise("test-model", path=self._base(rows))
        shown = {item["attribute"] for item in out["class_findings"]}
        assert shown == {"failure_mode", "metric_blind_spot", "degrades_when"}, shown

    def test_a_class_finding_is_not_folded_into_the_model_s_own_claims(self) -> None:
        """The control. If it were merged, a statement about the field would
        read as a measurement of this model and could make it contested."""
        out = advice.advise(
            "test-model",
            path=self._base(
                [
                    _fact(
                        model="*",
                        attribute="max_seconds",
                        value="99",
                        source_url="https://arxiv.org/abs/x",
                        tier="paper",
                    )
                ]
            ),
        )
        assert out["claims"]["max_seconds"]["values"] == ["10"]
        assert out["contested"] == []
        assert out["class_findings"][0]["value"] == "99"
        assert out["class_findings"][0]["scope"] == "*"


if __name__ == "__main__":
    unittest.main()
