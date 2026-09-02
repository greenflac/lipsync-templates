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
from studio.selfrag.facts import FactStore

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
        # Было `in {"pass", "could not measure"}` — допуск, написанный вокруг
        # дефекта: имени нет в реестре доступности, и вердикт о знании до
        # 2026-09-02 падал в «не смогли» при двух согласных источниках выше
        # блога. Допуск снят вместе с дефектом; тест, разрешающий оба исхода,
        # не сторожит ни одного.
        assert out["outcome"] == "pass"
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


class TheCardAndTheBaseAreCompared(unittest.TestCase):
    """Found by a blind evaluation, 2026-08-27.

    Asked whether sora-2 could serve as a reference arm, the card answered
    that its duration and resolution "could not be sourced at all" — while the
    claims layer of the same answer held 20 seconds and 1280x720, both read
    off OpenAI's own page. Nothing compared the two, so the card could go on
    saying "unknown" indefinitely.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        patcher = mock.patch.dict(source_hosts.VENDOR_SOURCES, TEST_VENDOR_SOURCES, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    class _Card:
        def __init__(self, **fields: object) -> None:
            self.max_seconds = fields.get("max_seconds")
            self.fps = fields.get("fps")
            self.resolutions = fields.get("resolutions", ())
            self.aspect_ratios = fields.get("aspect_ratios", ())
            self.audio = fields.get("audio", False)

    def _store(self, rows: list[dict]) -> FactStore:
        path = self.tmp / "facts.jsonl"
        _write(path, rows)
        return advice.store_for(path)

    def test_a_silent_card_beside_a_knowing_base_is_reported(self) -> None:
        store = self._store([_fact(attribute="max_seconds", value="20")])
        out = advice._card_vs_base(self._Card(), store, "test-model")
        assert len(out) == 1, out
        assert out[0]["shape"] == "card is silent"
        assert out[0]["base"] == ["20"]

    def test_a_card_that_agrees_with_the_base_says_nothing(self) -> None:
        """The negative control. A check that fired on every model would be
        indistinguishable in the output from one that works."""
        store = self._store([_fact(attribute="max_seconds", value="20")])
        out = advice._card_vs_base(self._Card(max_seconds=20.0), store, "test-model")
        assert out == [], out

    def test_eight_point_zero_and_the_string_eight_are_the_same_number(self) -> None:
        """Found the first time this ran: a card holds 8.0 and a harvest holds
        "8", and a substring test called veo-3.1 self-contradictory."""
        store = self._store([_fact(attribute="max_seconds", value="8")])
        assert advice._card_vs_base(self._Card(max_seconds=8.0), store, "test-model") == []

    def test_a_real_disagreement_is_reported_and_never_resolved(self) -> None:
        store = self._store([_fact(attribute="max_resolution", value="3840x2160")])
        out = advice._card_vs_base(self._Card(resolutions=("720p", "1080p")), store, "test-model")
        assert len(out) == 1, out
        assert out[0]["shape"] == "card contradicts"
        assert out[0]["card"] == ("720p", "1080p")
        assert out[0]["base"] == ["3840x2160"]

    def test_a_blog_only_claim_does_not_accuse_the_card(self) -> None:
        """`claims` reports blog-only as `could not measure`, and something the
        base cannot establish must not be used to contradict anybody."""
        store = self._store(
            [_fact(attribute="max_seconds", value="99", tier="blog", source_url="https://b.test/x")]
        )
        assert advice._card_vs_base(self._Card(max_seconds=8.0), store, "test-model") == []

    def test_it_reaches_the_caller_through_advise(self) -> None:
        path = self.tmp / "facts.jsonl"
        _write(path, [_fact(attribute="max_seconds", value="20")])
        out = advice.advise("test-model", path=path)
        assert "card_vs_base" in out


if __name__ == "__main__":
    unittest.main()


class VerdictFollowsEvidence(unittest.TestCase):
    """Вердикт о ЗНАНИИ выносится по свидетельству, а не по реестру доступности.

    ДЕФЕКТ, РАДИ КОТОРОГО ЭТОТ КЛАСС НАПИСАН (воспроизведён 2026-09-02 на живой
    базе до правки): `advise` спрашивал `registry.availability`, в котором
    СЕМЬ имён, и если имени там нет — отдавал `could not measure` независимо от
    того, что записано в базе фактов, где 466 имён. ИЗМЕРЕНО: 457 моделей из
    466 получали «не смогли» при непустом свидетельстве; по парам
    «модель.атрибут» — 999 из 1236 при утверждении с исходом `pass`.
    Наблюдаемый пример: `seedance-2.5.max_seconds` возвращал `could not
    measure`, держа в руках значение `'30'` из вендорского источника.

    Ожидаемые значения — ЛИТЕРАЛЫ (правило Т2). Ступени берутся с обоих краёв
    лестницы и из середины (правило Т3): `vendor` — верх, `operator` —
    середина, `blog` — нижняя ступень, которая факта не устанавливает.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        patcher = mock.patch.dict(source_hosts.VENDOR_SOURCES, TEST_VENDOR_SOURCES, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _base(self, rows: list[dict]) -> Path:
        path = self.tmp / "facts.jsonl"
        _write(path, rows)
        return path

    def test_the_registry_does_not_know_this_name_and_that_is_the_setup(self) -> None:
        """Половина условия опыта: имени в реестре доступности нет.

        Без этой проверки следующий тест доказывает не то: он мог бы позеленеть
        просто потому, что имя в реестре ЕСТЬ.
        """
        from studio.selfrag import registry

        self.assertEqual(registry.availability("test-model")["outcome"], "could not measure")
        self.assertIsNone(registry.availability("test-model")["card"])

    def test_a_vendor_value_stands_even_when_the_registry_never_heard_the_name(self) -> None:
        path = self._base([_fact(value="10", tier="vendor")])
        out = advice.advise("test-model", "max_seconds", path=path)
        self.assertEqual(out["outcome"], "pass")
        self.assertEqual(out["reason"], "answered")
        self.assertEqual(out["claims"]["max_seconds"]["values"], ["10"])

    def test_the_middle_of_the_ladder_answers_too(self) -> None:
        path = self._base([_fact(value="10", tier="operator", source_url="https://ops.test/a")])
        out = advice.advise("test-model", "max_seconds", path=path)
        self.assertEqual(out["outcome"], "pass")
        self.assertEqual(out["reason"], "answered")

    def test_the_registry_stays_a_visible_axis_of_its_own(self) -> None:
        """Ось доступности не выносит вердикт — но и не исчезает."""
        path = self._base([_fact(value="10", tier="vendor")])
        out = advice.advise("test-model", "max_seconds", path=path)
        self.assertEqual(out["availability"]["outcome"], "could not measure")
        self.assertIn("SEPARATE axis", out["note"])
        self.assertIn("not in the registry", out["note"])

    def test_a_model_that_cannot_be_called_is_fail_no_matter_what_is_known(self) -> None:
        """Знать про модель всё и заплатить за 404 — разные вещи."""
        path = self._base([_fact(value="10", tier="vendor")])
        dead = {
            "outcome": "fail",
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": "test-model is retired",
            "card": object(),
        }
        with mock.patch.object(advice.registry, "availability", return_value=dead):
            out = advice.advise("test-model", "max_seconds", path=path)
        self.assertEqual(out["outcome"], "fail")
        self.assertEqual(out["reason"], "model_unusable")

    # --- негативный контроль, обе стороны (правило И5) ---

    def test_an_invented_name_is_still_could_not_measure(self) -> None:
        path = self._base([_fact(value="10", tier="vendor")])
        out = advice.advise("зззнесуществующая-модель-9000", path=path)
        self.assertEqual(out["outcome"], "could not measure")
        self.assertEqual(out["reason"], "model_unknown")
        self.assertEqual(out["checked"], 0)
        self.assertEqual(out["claims"], {})

    def test_an_empty_base_is_still_could_not_measure(self) -> None:
        path = self.tmp / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        out = advice.advise("test-model", "max_seconds", path=path)
        self.assertEqual(out["outcome"], "could not measure")
        self.assertEqual(out["checked"], 0)

    def test_the_bottom_rung_alone_never_becomes_an_answer(self) -> None:
        path = self._base(
            [
                _fact(value="10", tier="blog", source_url="https://blog.test/a"),
                _fact(value="10", tier="blog", source_url="https://blog.test/b"),
            ]
        )
        out = advice.advise("test-model", "max_seconds", path=path)
        self.assertEqual(out["outcome"], "could not measure")
        self.assertEqual(out["reason"], "sources_blog_only")

    # --- три «не смогли» обязаны быть различимы пользователем ---

    def test_the_three_could_not_measure_cases_are_told_apart(self) -> None:
        """Модели нет / имя набрано с опечаткой / атрибута нет — разная работа дальше."""
        path = self._base([_fact(value="10", tier="vendor")])
        unknown = advice.advise("nope-9000", path=path)
        # ОПЕЧАТКА, А НЕ ДРУГОЕ НАПИСАНИЕ. До 2026-09-02 здесь стояло
        # `testmodel`, и оно считалось опечаткой: имя сравнивалось сырой
        # строкой, поэтому дефис делал из одной модели две. Теперь `testmodel`
        # РАЗРЕШАЕТСЯ в `test-model` (см. соседний тест), и опечаткой служит
        # перепутанная буква, которой свёртка не лечит.
        mistyped = advice.advise("test-modle", path=path)
        gap = advice.advise("test-model", "выдуманный-атрибут", path=path)

        for out in (unknown, mistyped, gap):
            self.assertEqual(out["outcome"], "could not measure")
        self.assertEqual(unknown["reason"], "model_unknown")
        self.assertEqual(mistyped["reason"], "name_maybe_mistyped")
        self.assertEqual(gap["reason"], "attribute_unknown")
        self.assertEqual(len({unknown["reason"], mistyped["reason"], gap["reason"]}), 3)

        self.assertEqual(unknown["near"], [], "выдуманному имени сосед не предлагается")
        self.assertEqual(mistyped["near"], ["test-model"])
        self.assertEqual(gap["known_attributes"], ["max_seconds"], "чем спрашивать вместо")

    def test_a_separator_is_not_a_different_model(self) -> None:
        """ИЗМЕРЕНО 2026-09-02 на живой базе: 9 групп из 466 имён — одна
        модель под двумя написаниями. `advise("flux.2-klein-9b")` отвечал 4
        атрибутами и 6 провалами, `advise("flux-2-klein-9b")` — 2 и 0, и оба
        ответа были `pass`. Разрешение имени одно на проект
        (`studio/selfrag/modelnames.py`), и вот чем оно проверяется здесь."""
        path = self._base([_fact(value="10", tier="vendor")])
        for написание in ("testmodel", "TEST_MODEL", "test model", "test.model"):
            out = advice.advise(написание, path=path)
            self.assertEqual(out["outcome"], "pass", написание)
            self.assertEqual(out["reason"], "answered", написание)
        # Негативный контроль: соседнее имя — не то же самое имя.
        self.assertEqual(advice.advise("test-model-pro", path=path)["outcome"], "could not measure")

    def test_every_reason_returned_is_one_of_the_declared_words(self) -> None:
        path = self._base([_fact(value="10", tier="vendor")])
        declared = {
            "no_model_named",
            "model_unknown",
            "name_maybe_mistyped",
            "nothing_recorded",
            "attribute_unknown",
            "sources_blog_only",
            "sources_disagree",
            "model_unusable",
            "answered",
        }
        self.assertEqual(set(advice.REASONS), declared, "словарь причин закреплён литералом")
        for args in [(""), ("test-model",), ("nope-9000",), ("test-model", "max_seconds")]:
            call = (args,) if isinstance(args, str) else args
            self.assertIn(advice.advise(*call, path=path)["reason"], declared)

    def test_an_unnamed_model_says_so_in_its_own_words(self) -> None:
        self.assertEqual(advice.advise("")["reason"], "no_model_named")
        self.assertEqual(advice.advise("")["outcome"], "could not measure")

    def test_contested_sources_keep_their_own_reason(self) -> None:
        """Эта ветка работала образцово и обязана остаться нетронутой."""
        path = self._base(
            [
                _fact(value="10", tier="vendor", source_url="https://example.test/a"),
                _fact(value="15", tier="paper", source_url="https://example.test/b"),
            ]
        )
        out = advice.advise("test-model", "max_seconds", path=path)
        self.assertEqual(out["outcome"], "fail")
        self.assertEqual(out["reason"], "sources_disagree")
        self.assertEqual(sorted(out["claims"]["max_seconds"]["values"]), ["10", "15"])

    def test_found_sources_are_counted_not_asked_ones(self) -> None:
        """`claims_found` считает НАЙДЕННОЕ: у выдуманного атрибута это ноль."""
        path = self._base([_fact(value="10", tier="vendor")])
        real = advice.advise("test-model", "max_seconds", path=path)
        invented = advice.advise("test-model", "выдуманный-атрибут", path=path)
        self.assertEqual(advice.claims_found(real["claims"]), 1)
        self.assertEqual(advice.claims_found(invented["claims"]), 0)
        self.assertEqual(advice.claims_found(None), 0)

    def test_one_weak_attribute_does_not_sink_the_answered_ones(self) -> None:
        """Граница «всё слабое» против «часть слабая» — Е3: числами, а не флагом.

        Мутация `unmeasured == len(claims)` -> `unmeasured > 0` не краснела ни
        на одном тесте до этого (замер 2026-09-02): смешанного входа в наборе
        не было, и обе стороны границы проверялись одной её стороной.
        """
        path = self._base(
            [
                _fact(attribute="max_seconds", value="10", tier="vendor"),
                _fact(
                    attribute="resolution",
                    value="1080p",
                    tier="blog",
                    source_url="https://blog.test/x",
                ),
            ]
        )
        out = advice.advise("test-model", path=path)
        self.assertEqual(out["outcome"], "pass")
        self.assertEqual(out["reason"], "answered")
        self.assertEqual(out["unmeasured"], 1, "слабый атрибут сосчитан, а не спрятан")
        self.assertEqual(out["claims"]["max_seconds"]["outcome"], "pass")
        self.assertEqual(out["claims"]["resolution"]["outcome"], "could not measure")
        self.assertIn("1 of them only weakly", out["note"])

    def test_all_weak_attributes_do_sink_it(self) -> None:
        """Другая сторона той же границы: слабо ВСЁ — ответа нет."""
        path = self._base(
            [
                _fact(attribute="max_seconds", value="10", tier="blog"),
                _fact(
                    attribute="resolution",
                    value="1080p",
                    tier="blog",
                    source_url="https://blog.test/x",
                ),
            ]
        )
        out = advice.advise("test-model", path=path)
        self.assertEqual(out["outcome"], "could not measure")
        self.assertEqual(out["reason"], "sources_blog_only")


class КарточкаЭтоДанные(unittest.TestCase):
    """Найдено чтением собственной выдачи (П3, 2026-09-02).

    В ответе стояло `"card": "ModelCard(model_id='kling-3.0', media='video',
    ...)"` — `repr()` датакласса, засунутый в поле JSON сериализатором сервера
    (`default=str`). Прочесть из него поле нельзя иначе как регулярками, а
    потребитель, у которого `json.dumps` без `default`, прямо падает.
    """

    def test_ответ_сериализуется_без_подпорок(self):
        """Главное: `json.dumps` БЕЗ `default=str`. Именно подпорка и прятала
        дефект — сервер молча превращал объект в строку."""
        json.dumps(advice.advise("kling-3.0"), ensure_ascii=False)

    def test_поля_карточки_читаются_как_поля(self):
        карточка = advice.advise("kling-3.0")["availability"]["card"]
        self.assertIsInstance(карточка, dict)
        self.assertEqual(карточка["model_id"], "kling-3.0")
        self.assertIsInstance(карточка["skeleton"], list)

    def test_нет_карточки_остаётся_нет_карточки(self):
        """Вторая половина (И5): пустое не должно превратиться в объект с
        полями — «реестр этой модели не знает» обязано остаться отличимым."""
        self.assertIsNone(advice.advise("latentsync-1.6")["availability"]["card"])

    def test_чужой_объект_не_теряется_молча(self):
        """Р1 у преобразователя: то, что не датакласс и не словарь, отдаётся
        своим текстом, а не выбрасывается."""
        self.assertEqual(advice._card_as_dict("что-то"), {"repr": "что-то"})
        self.assertIsNone(advice._card_as_dict(None))


class ДатаПубликацииНеИзнос(unittest.TestCase):
    """Найдено чтением очереди «протухшего» (П3, 2026-09-02).

    Из 49 строк, объявленных протухшими, 21 оказалась СТАТЬЁЙ или бенчмарком,
    и первая — arXiv:2103.00020 от 2021 года. Статья говорит сегодня ровно то
    же, что и в день публикации; «поищи в сети и запиши, что найдёшь» для неё —
    работа, которую нельзя сделать. Очередь, где такой работы 43%, читают по
    диагонали, а вместе с ней по диагонали читают и 28 строк, которые
    действительно протухли: цены площадок и вендорские спеки.
    """

    def база(self) -> Path:
        каталог = tempfile.mkdtemp()
        файл = Path(каталог) / "facts.jsonl"
        строки = [
            {
                "model": "м",
                "attribute": "failure_mode",
                "value": "статья 2021 года",
                "source_url": "https://arxiv.org/abs/2103.00020",
                "tier": "paper",
                "stated_on": "2021-02-26",
            },
            {
                "model": "м",
                "attribute": "price_per_second_usd",
                "value": "0.06",
                "source_url": "https://fal.ai/models/x",
                "tier": "portal",
                "stated_on": "2024-01-01",
            },
        ]
        файл.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in строки), encoding="utf-8"
        )
        return файл

    def test_статья_не_попадает_в_очередь_перечитывания(self):
        out = advice.stale(path=self.база())
        self.assertEqual([r["tier"] for r in out["stale"]], ["portal"])
        self.assertEqual([r["tier"] for r in out["published_and_old"]], ["paper"])

    def test_цена_площадки_протухает_по_настоящему(self):
        """Вторая половина (И5): правило обязано оставить в очереди то, что
        действительно стареет, иначе оно просто выключает сторожа."""
        out = advice.stale(path=self.база())
        self.assertEqual(out["outcome"], "fail")
        self.assertEqual(out["violations"], 1)

    def test_старая_статья_не_прячется_молча(self):
        """Не выброшена, а отделена, и в ноте сказано, что с ней делать:
        измерять модель, а не перечитывать статью."""
        out = advice.stale(path=self.база())
        self.assertIn("a paper does not rot", out["note"])
        self.assertIn("fresh measurement of the model", out["note"])
