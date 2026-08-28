"""Can a vendor be reached without anybody opening a door?

Every test writes its own denial log to a temporary file, so nothing here
depends on the repository's own and nothing reaches the network (house rule T4).

The test that carries the most weight is the one about ABSENCE: the first
version of this module inferred "closed" from "not recorded open", and reported
five families as unreachable through `huggingface.co` — a host it had read from
successfully minutes before, and which has no row in the denial log at all.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio.mcp import routes
from studio.selfrag import source_hosts

#: A fictional ladder, so these tests do not move when the real table does.
TEST_VENDORS = {
    "twoway": ("shut.test", "huggingface.co/twoway-ai/"),
    "onlyshut": ("shut.test", "alsoshut.test"),
    "onlyopen": ("huggingface.co/onlyopen/",),
    "neverheard": ("nobody-recorded-this.test",),
}


def _log(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )


class Reachability(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.log = Path(self._dir.name) / "denied.jsonl"
        _log(
            self.log,
            [
                {"host": "shut.test", "state": "refused"},
                {"host": "alsoshut.test", "state": "refused"},
                {"host": "noted-open.test", "state": "open"},
            ],
        )

    def test_a_recorded_refusal_is_refused(self) -> None:
        assert routes.reachability("shut.test", path=self.log) == routes.REACH_REFUSED

    def test_a_recorded_open_is_open(self) -> None:
        assert routes.reachability("noted-open.test", path=self.log) == routes.REACH_OPEN

    def test_a_HUB_is_open_even_with_no_row_in_the_log(self) -> None:
        """THE BUG THIS MODULE EXISTS FOR. `huggingface.co` carries most of this
        base and has never been refused, so it has no row at all. Reading
        absence as closure reported it unreachable."""
        assert "huggingface.co" not in json.dumps(self.log.read_text())
        assert routes.reachability("huggingface.co", path=self.log) == routes.REACH_OPEN

    def test_an_unrecorded_stranger_is_UNKNOWN_and_not_closed(self) -> None:
        """The third outcome, and the whole point: unknown means try it. A
        harvester that treated unknown as closed would stop discovering."""
        assert routes.reachability("never-seen.test", path=self.log) == routes.REACH_UNKNOWN

    def test_a_refusal_OUTRANKS_the_hub_table(self) -> None:
        """A hub that goes dark must read as refused the moment the log says
        so, without anybody editing OPEN_HUBS by hand."""
        _log(self.log, [{"host": "huggingface.co", "state": "refused"}])
        assert routes.reachability("huggingface.co", path=self.log) == routes.REACH_REFUSED


class Routing(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.log = Path(self._dir.name) / "denied.jsonl"
        _log(
            self.log,
            [
                {"host": "shut.test", "state": "refused"},
                {"host": "alsoshut.test", "state": "refused"},
            ],
        )
        patcher = mock.patch.dict(source_hosts.VENDOR_SOURCES, TEST_VENDORS, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_open_route_is_offered_ahead_of_the_shut_one(self) -> None:
        out = routes.routes_for("twoway", path=self.log)
        assert out["outcome"] == PASS
        assert out["routes"][0]["entry"] == "huggingface.co/twoway-ai/"
        assert out["routes"][0]["reach"] == routes.REACH_OPEN

    def test_a_family_with_every_route_shut_is_a_REAL_access_request(self) -> None:
        """The negative control on the whole idea. If nothing ever came back
        `fail`, the module would be claiming the policy costs nothing — and a
        request nobody can distinguish from noise is how a needed vendor stays
        shut."""
        out = routes.routes_for("onlyshut", path=self.log)
        assert out["outcome"] == FAIL
        assert "THIS is a real whitelist request" in out["note"]

    def test_an_undeclared_family_is_a_TABLE_edit_not_an_access_request(self) -> None:
        """Three outcomes. Silence about a family is not a closed door, and
        confusing the two sends somebody to ask for access they already have."""
        out = routes.routes_for("nobody-has-declared-this", path=self.log)
        assert out["outcome"] == UNMEASURED
        assert "table edit, not an access request" in out["note"]

    def test_an_unknown_host_still_counts_as_usable_and_is_counted(self) -> None:
        out = routes.routes_for("neverheard", path=self.log)
        assert out["outcome"] == PASS
        assert out["unmeasured"] == 1, "an untried route is offered AND counted as untried"

    def test_blocked_families_names_only_the_ones_with_no_way_in(self) -> None:
        out = routes.blocked_families(path=self.log)
        assert out["outcome"] == FAIL
        assert [b["family"] for b in out["blocked"]] == ["onlyshut"]

    def test_blocked_families_is_PASS_when_every_family_has_a_way_in(self) -> None:
        """The other half: a table where nothing is blocked must not report a
        violation, or the access request cries wolf every run."""
        with mock.patch.dict(
            source_hosts.VENDOR_SOURCES, {"onlyopen": TEST_VENDORS["onlyopen"]}, clear=True
        ):
            out = routes.blocked_families(path=self.log)
        assert out["outcome"] == PASS
        assert out["blocked"] == []


class TheRealTable(unittest.TestCase):
    def test_every_declared_family_has_a_reachable_route_today(self) -> None:
        """The measurement that answers the owner's question, run as a test.

        If this goes red, a vendor really has been walled off and a whitelist
        entry is genuinely needed — and the failure names which one, so the
        request is a fact rather than a wish.
        """
        out = routes.blocked_families()
        assert out["outcome"] == PASS, out["note"]


if __name__ == "__main__":
    unittest.main()
