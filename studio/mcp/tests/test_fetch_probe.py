"""The web client and the API probe: do they tell three different failures apart?

No test here touches the network. The transport is replaced, because a test
that reaches out goes red when somebody else's server has a bad morning and
green off a cache — and this suite is supposed to measure our own code.
"""

from __future__ import annotations

import json
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from studio.mcp import fetch, probe

# The absurdity floor as of 2026-08-27, written as a literal. If somebody
# lowers the constant, this test is SUPPOSED to fail and make them explain.
ABSURDITY_FLOOR = 1_000_000

# The proxy's own wording for a policy denial, copied from an observed error.
DENIAL_TEXT = "Tunnel connection failed: 403 Forbidden"


class _Response:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self, n: int = -1) -> bytes:
        return self._body[:n] if n and n > 0 else self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class WebClient(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.denied = Path(self._dir.name) / "denied.jsonl"
        patcher = mock.patch.object(fetch, "DENIED_PATH", self.denied)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_policy_denial_is_could_not_measure_and_is_flagged_denied(self) -> None:
        error = urllib.error.URLError(DENIAL_TEXT)
        with mock.patch.object(fetch.urllib.request, "urlopen", side_effect=error):
            out = fetch.fetch("https://arxiv.org/abs/1", why_wanted="a paper")
        assert out["outcome"] == "could not measure"
        assert out["denied"] is True
        assert "policy" in out["note"]

    def test_a_404_is_our_bad_url_and_must_not_read_as_a_denial(self) -> None:
        error = urllib.error.HTTPError("https://x.test/y", 404, "Not Found", {}, None)  # type: ignore[arg-type]
        with mock.patch.object(fetch.urllib.request, "urlopen", side_effect=error):
            out = fetch.fetch("https://x.test/y")
        assert out["outcome"] == "fail"
        assert out["denied"] is False, "a host that answered is not a blocked host"

    def test_a_plain_network_failure_is_neither_denial_nor_failure(self) -> None:
        error = urllib.error.URLError("timed out")
        with mock.patch.object(fetch.urllib.request, "urlopen", side_effect=error):
            out = fetch.fetch("https://x.test/y")
        assert out["outcome"] == "could not measure"
        assert out["denied"] is False
        assert "retrying" in out["note"]

    def test_a_good_fetch_returns_the_body(self) -> None:
        with mock.patch.object(
            fetch.urllib.request, "urlopen", return_value=_Response(b"hello world")
        ):
            out = fetch.fetch("https://x.test/y")
        assert out["outcome"] == "pass"
        assert out["text"] == "hello world"
        assert out["denied"] is False

    def test_something_that_is_not_a_url_sends_nothing(self) -> None:
        out = fetch.fetch("kling.ai")
        assert out["outcome"] == "fail"
        assert out["host"] == ""

    def test_the_ask_is_one_row_per_host_carrying_its_latest_reason(self) -> None:
        error = urllib.error.URLError(DENIAL_TEXT)
        with mock.patch.object(fetch.urllib.request, "urlopen", side_effect=error):
            fetch.fetch("https://arxiv.org/abs/1", why_wanted="a paper")
            fetch.fetch("https://arxiv.org/abs/2", why_wanted="another paper")
            fetch.fetch("https://docs.bfl.ai/", why_wanted="flux limits")

        asked = fetch.wanted()
        assert asked["outcome"] == "fail"
        hosts = [row["host"] for row in asked["hosts"]]
        assert hosts == ["arxiv.org", "docs.bfl.ai"], "one row per host, not per attempt"
        assert asked["hosts"][0]["why_wanted"] == "another paper", (
            "the newest reason is the one written against today's fact base"
        )

    def test_with_nothing_denied_there_is_nothing_to_ask_for(self) -> None:
        out = fetch.wanted()
        assert out["outcome"] == "pass"
        assert out["hosts"] == []
        assert out["checked"] == 0

    # The allowlist request is read by a human who then goes and asks for the
    # hosts in it. A host swept up by a bulk probe is still recorded — routing
    # around a refusal is what is forbidden — but it is not part of the ask.
    # OBSERVED 2026-08-27: one live search put five such hosts into a file that
    # held six real ones.
    def _deny(self, url: str, why: str, *, incidental: bool) -> None:
        error = urllib.error.URLError(DENIAL_TEXT)
        with mock.patch.object(fetch.urllib.request, "urlopen", side_effect=error):
            fetch.fetch(url, why_wanted=why, incidental=incidental)

    def test_a_host_swept_by_a_bulk_probe_is_not_part_of_the_ask(self) -> None:
        self._deny("https://arxiv.org/abs/1", "a paper", incidental=False)
        self._deny("https://wavespeed.ai/", "a search hit", incidental=True)

        asked = fetch.wanted()
        assert [row["host"] for row in asked["hosts"]] == ["arxiv.org"]
        assert [row["host"] for row in asked["also_refused"]] == ["wavespeed.ai"]
        assert asked["violations"] == 1, "the ask is one host, not two"
        assert asked["unmeasured"] == 1, "the swept host is still counted somewhere"

    def test_only_swept_hosts_is_could_not_measure_and_asks_for_nothing(self) -> None:
        self._deny("https://wavespeed.ai/", "a search hit", incidental=True)

        asked = fetch.wanted()
        assert asked["outcome"] == "could not measure", (
            "refusals nobody asked for are not an allowlist request, and they "
            "are not a clean bill of health either"
        )
        assert asked["hosts"] == []
        assert [row["host"] for row in asked["also_refused"]] == ["wavespeed.ai"]

    def test_a_better_reason_replaces_the_one_the_ask_was_frozen_at(self) -> None:
        """OBSERVED 2026-08-27, by reading the rendered request.

        `docs.bfl.ai` was still being asked for because "every recorded claim
        about it is blog tier" — which the re-tiering had made false that same
        morning. Keeping only the first reason freezes the request at whatever
        the base looked like the day the host was first refused, and a stale
        reason in a request a human has to justify is worse than a short one.
        """
        self._deny("https://docs.bfl.ai/", "every claim about it is blog tier", incidental=False)
        self._deny("https://docs.bfl.ai/", "three claims cite it, none read", incidental=False)

        asked = fetch.wanted()
        assert [row["host"] for row in asked["hosts"]] == ["docs.bfl.ai"], "still one host"
        assert asked["hosts"][0]["why_wanted"] == "three claims cite it, none read"

    def test_restating_the_same_reason_writes_nothing(self) -> None:
        """Otherwise re-running the request generator grows the file forever."""
        self._deny("https://arxiv.org/", "ten paper facts, none read", incidental=False)
        first = fetch.DENIED_PATH.read_text(encoding="utf-8")
        self._deny("https://arxiv.org/", "ten paper facts, none read", incidental=False)
        assert fetch.DENIED_PATH.read_text(encoding="utf-8") == first

    def test_the_history_of_reasons_is_kept_not_overwritten(self) -> None:
        self._deny("https://arxiv.org/", "first reason", incidental=False)
        self._deny("https://arxiv.org/", "second reason", incidental=False)
        rows = [
            json.loads(line)
            for line in fetch.DENIED_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [r["why_wanted"] for r in rows] == ["first reason", "second reason"], (
            "append-only: the request can be read back as it changed"
        )

    def test_a_granted_host_retires_itself_from_the_ask(self) -> None:
        """OBSERVED 2026-08-27, the moment the owner granted 21 hosts.

        The request is assembled from refusals that happened, and a refusal
        never expires — so the generated document went on asking for all 21.
        A request that asks for access already granted is worse than none: it
        is the reason the next one does not get read.
        """
        self._deny("https://arxiv.org/abs/1", "ten paper facts, none read", incidental=False)
        assert [r["host"] for r in fetch.wanted()["hosts"]] == ["arxiv.org"]

        with mock.patch.object(fetch.urllib.request, "urlopen", return_value=_Response(b"hello")):
            fetch.fetch("https://arxiv.org/abs/1")

        asked = fetch.wanted()
        assert asked["hosts"] == [], "it answers now; it is not asked for"
        assert asked["granted"] == ["arxiv.org"], "and the grant is reported, not silent"
        assert asked["outcome"] == "pass"
        assert "granted" in asked["note"]

    def test_a_host_that_answers_with_an_http_error_still_counts_as_granted(self) -> None:
        """A 404 on a bare root is a very common way for a granted host to greet us."""
        self._deny("https://kling.ai/", "contested max_seconds", incidental=False)
        error = urllib.error.HTTPError("https://kling.ai/", 404, "Not Found", {}, None)  # type: ignore[arg-type]
        with mock.patch.object(fetch.urllib.request, "urlopen", side_effect=error):
            fetch.fetch("https://kling.ai/")
        assert fetch.wanted()["granted"] == ["kling.ai"]

    def test_a_grant_taken_away_puts_the_host_back_in_the_ask(self) -> None:
        self._deny("https://arxiv.org/", "ten paper facts", incidental=False)
        with mock.patch.object(fetch.urllib.request, "urlopen", return_value=_Response(b"hi")):
            fetch.fetch("https://arxiv.org/")
        assert fetch.wanted()["hosts"] == []

        # Deliberately the SAME reason as the first refusal. With a different
        # one the restatement rule would write the row and this test would pass
        # without the reopening rule existing at all — which is what an earlier
        # version of it did.
        self._deny("https://arxiv.org/", "ten paper facts", incidental=False)
        asked = fetch.wanted()
        assert [r["host"] for r in asked["hosts"]] == ["arxiv.org"], (
            "a grant that went away is a fresh refusal, not a stale row"
        )
        assert asked["granted"] == []

    def test_answering_repeatedly_writes_one_row_not_one_per_fetch(self) -> None:
        self._deny("https://arxiv.org/", "a reason", incidental=False)
        with mock.patch.object(fetch.urllib.request, "urlopen", return_value=_Response(b"hi")):
            fetch.fetch("https://arxiv.org/")
            size = fetch.DENIED_PATH.read_text(encoding="utf-8")
            for _ in range(3):
                fetch.fetch("https://arxiv.org/x")
        assert fetch.DENIED_PATH.read_text(encoding="utf-8") == size, "only transitions"

    def test_a_host_nobody_ever_asked_about_does_not_get_a_row_for_answering(self) -> None:
        """The negative control: this file is the ask, not a traffic log."""
        with mock.patch.object(fetch.urllib.request, "urlopen", return_value=_Response(b"hi")):
            fetch.fetch("https://pypi.org/simple/")
        assert not fetch.DENIED_PATH.exists() or fetch.DENIED_PATH.read_text() == ""

    def test_a_map_refresh_does_not_fill_the_ask_with_hosts_nobody_wanted(self) -> None:
        """Second place this shape appeared, 2026-08-27.

        `reachability()` sweeps a list of hosts to re-date the map. Recording
        every refusal as an ask put hosts nobody wanted into the file a human
        reads, under the reason "reachability probe", which says nothing.
        """
        error = urllib.error.URLError(DENIAL_TEXT)
        with mock.patch.object(fetch.urllib.request, "urlopen", side_effect=error):
            fetch.reachability(("arxiv.org", "docs.bfl.ai"))

        asked = fetch.wanted()
        assert asked["hosts"] == [], "a map refresh asks for nothing"
        assert len(asked["also_refused"]) == 2, "and loses no refusal either"

    def test_probing_hosts_you_actually_need_does_fill_the_ask(self) -> None:
        error = urllib.error.URLError(DENIAL_TEXT)
        with mock.patch.object(fetch.urllib.request, "urlopen", side_effect=error):
            fetch.reachability(("civitai.com",), why_wanted="community prompt corpus")

        asked = fetch.wanted()
        assert [r["host"] for r in asked["hosts"]] == ["civitai.com"]
        assert asked["hosts"][0]["why_wanted"] == "community prompt corpus"

    def test_a_swept_host_later_really_needed_is_promoted_into_the_ask(self) -> None:
        self._deny("https://kling.ai/", "a search hit", incidental=True)
        self._deny("https://kling.ai/docs", "max_seconds is contested", incidental=True)
        asked = fetch.wanted()
        assert asked["hosts"] == [], "still nobody has asked for it"

        self._deny("https://kling.ai/docs", "max_seconds is contested", incidental=False)
        asked = fetch.wanted()
        assert [row["host"] for row in asked["hosts"]] == ["kling.ai"]
        assert asked["hosts"][0]["why_wanted"] == "max_seconds is contested", (
            "the reason that promoted it is the reason the owner needs to read"
        )
        assert asked["also_refused"] == [], "a host is in one list or the other"


class WithdrawingFromTheAsk(unittest.TestCase):
    """A host still refused, and no longer wanted. Added when Reddit was dropped.

    The ask had already been fixed once for carrying hosts that were granted.
    This is the mirror: hosts nobody needs any more. Recording them as `open`
    would have been the easy fix and it would have put a lie in the file — the
    host never answered.
    """

    def setUp(self) -> None:
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.denied = Path(self._dir.name) / "denied.jsonl"
        patcher = mock.patch.object(fetch, "DENIED_PATH", self.denied)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _refuse(self, host: str) -> None:
        fetch.note_denial(f"https://{host}/x", "Tunnel connection failed", "a real question")

    def test_a_withdrawn_host_leaves_the_ask_without_being_called_granted(self) -> None:
        self._refuse("example.test")
        assert [row["host"] for row in fetch.wanted()["hosts"]] == ["example.test"]
        fetch.note_unwanted("example.test", "the plan it was for was dropped")
        after = fetch.wanted()
        assert after["hosts"] == []
        assert after["granted"] == [], "it never answered, so it was never granted"
        assert after["withdrawn"] == ["example.test"]

    def test_the_reason_is_required(self) -> None:
        self._refuse("example.test")
        out = fetch.note_unwanted("example.test", "   ")
        assert out["outcome"] == "fail"
        assert [row["host"] for row in fetch.wanted()["hosts"]] == ["example.test"]

    def test_withdrawing_a_host_nobody_asked_for_is_could_not_measure(self) -> None:
        """Never `pass`: a typo would otherwise report a withdrawal that did
        not happen."""
        out = fetch.note_unwanted("never-seen.test", "dropped")
        assert out["outcome"] == "could not measure"

    def test_withdrawing_twice_writes_one_row(self) -> None:
        self._refuse("example.test")
        fetch.note_unwanted("example.test", "dropped")
        size = self.denied.read_text(encoding="utf-8")
        again = fetch.note_unwanted("example.test", "dropped again")
        assert again["outcome"] == "pass"
        assert self.denied.read_text(encoding="utf-8") == size, "only transitions"

    def test_a_host_withdrawn_and_then_refused_again_returns_to_the_ask(self) -> None:
        """A plan can come back. The latest row decides, as for every other
        state in this file."""
        self._refuse("example.test")
        fetch.note_unwanted("example.test", "dropped")
        self._refuse("example.test")
        assert [row["host"] for row in fetch.wanted()["hosts"]] == ["example.test"]

    def test_a_withdrawn_host_that_later_opens_is_reported_as_granted(self) -> None:
        self._refuse("example.test")
        fetch.note_unwanted("example.test", "dropped")
        fetch.note_open("https://example.test/x")
        out = fetch.wanted()
        assert out["granted"] == ["example.test"]
        assert out["withdrawn"] == []


class Probe(unittest.TestCase):
    URL = "https://api.klingai.com/v1/videos/text2video"

    def test_the_absurdity_floor_is_what_the_module_says_it_is(self) -> None:
        assert probe.ABSURD_MIN == ABSURDITY_FLOOR

    def test_a_plausible_value_is_refused_before_anything_is_sent(self) -> None:
        for value in (1, 15, 999, 999_999):
            out = probe.probe_limit(self.URL, "duration", value)
            assert out["outcome"] == "fail", f"{value} must not be sent"
            assert out["sent"] is None
            assert "absurdity floor" in out["note"]

    def test_a_value_at_the_floor_clears_the_guard(self) -> None:
        # It stops at "no key" rather than at the guard, which is the point:
        # the guard let it through and the environment did not.
        with mock.patch.dict("os.environ", {}, clear=True):
            out = probe.probe_limit(self.URL, "duration", ABSURDITY_FLOOR)
        assert out["outcome"] == "could not measure"
        assert "no API key" in out["note"]

    def test_a_string_probe_must_carry_the_sentinel(self) -> None:
        # THE ENVIRONMENT IS CLEARED HERE FOR THE SAME REASON AS IN ITS
        # NEIGHBOURS, and it was missing. Found 2026-09-04 by the new runner
        # (`scripts/run_tests.py`), which blocks sockets for the whole suite:
        # the sentinel value clears the absurdity guard, so with an API key in
        # the environment this line went on to open a real connection to the
        # vendor — a network call in a test (rule T4), and a PAID one at that.
        # Cleared, it stops at "no API key", which is what the assertion below
        # has always been about: the guard let the sentinel through.
        with mock.patch.dict("os.environ", {}, clear=True):
            out = probe.probe_limit(self.URL, "aspect_ratio", "21:9")
            assert out["outcome"] == "fail"
            assert out["sent"] is None
            ok = probe.probe_limit(self.URL, "aspect_ratio", "absurd-probe:9999")
        assert ok["outcome"] != "fail", "the sentinel form must clear the guard"

    def test_a_boolean_is_not_a_probe_value(self) -> None:
        out = probe.probe_limit(self.URL, "duration", True)
        assert out["outcome"] == "fail"
        assert "bool" in out["note"]

    def test_plain_http_is_refused(self) -> None:
        out = probe.probe_limit("http://api.klingai.com/x", "duration", 9_000_000)
        assert out["outcome"] == "fail"
        assert out["sent"] is None

    def test_a_validation_error_is_the_measurement_not_a_failure(self) -> None:
        body = json.dumps({"code": 1201, "message": "duration must be 5 or 10"}).encode()
        error = urllib.error.HTTPError(self.URL, 400, "Bad Request", {}, None)  # type: ignore[arg-type]
        error.read = lambda n=-1: body  # type: ignore[method-assign]
        with mock.patch.dict("os.environ", {"KLING_KEY": "test-key"}, clear=True):
            with mock.patch.object(probe.urllib.request, "urlopen", side_effect=error):
                out = probe.probe_limit(self.URL, "duration", 9_000_000)
        assert out["outcome"] == "pass", "a 400 carrying the limit is a success here"
        assert "duration must be 5 or 10" in out["response"]
        assert out["suggested_fact"]["tier"] == "probe"

    def test_the_key_never_appears_in_what_is_returned(self) -> None:
        body = json.dumps({"message": "nope"}).encode()
        error = urllib.error.HTTPError(self.URL, 400, "Bad Request", {}, None)  # type: ignore[arg-type]
        error.read = lambda n=-1: body  # type: ignore[method-assign]
        with mock.patch.dict("os.environ", {"KLING_KEY": "SECRET-abc123"}, clear=True):
            with mock.patch.object(probe.urllib.request, "urlopen", side_effect=error):
                out = probe.probe_limit(self.URL, "duration", 9_000_000)
        assert "SECRET-abc123" not in json.dumps(out, default=str)
        assert out["key_from"] == "KLING_KEY", "which var, never the value"

    def test_the_name_this_environment_actually_uses_is_searched_first(self) -> None:
        # OBSERVED 2026-08-27: the table listed KLING_API_KEY and KLINGAI_API_KEY
        # while the live variable was KLING_KEY, so the probe reported "no API
        # key" with a working key beside it.
        assert probe.KEY_ENV["api.klingai.com"][0] == "KLING_KEY"

    def test_an_environment_with_no_key_at_all_is_could_not_measure(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            out = probe.probe_limit(self.URL, "duration", 9_000_000)
        assert out["outcome"] == "could not measure"
        assert out["sent"] is None

    def test_a_denied_host_is_could_not_measure_and_is_recorded(self) -> None:
        with TemporaryDirectory() as tmp:
            denied = Path(tmp) / "denied.jsonl"
            with mock.patch.object(fetch, "DENIED_PATH", denied):
                with mock.patch.dict("os.environ", {"KLING_KEY": "test-key"}, clear=True):
                    error = urllib.error.URLError(DENIAL_TEXT)
                    with mock.patch.object(probe.urllib.request, "urlopen", side_effect=error):
                        out = probe.probe_limit(self.URL, "duration", 9_000_000)
            assert out["outcome"] == "could not measure"
            assert denied.is_file(), "a refused probe still feeds the allowlist request"


class FactTiers(unittest.TestCase):
    """The tier ladder studio/mcp records into. Literals, not imports of the ladder."""

    LADDER = ("vendor", "probe", "operator", "paper", "benchmark", "portal", "blog")

    def test_the_ladder_is_what_it_says_it_is(self) -> None:
        from studio.selfrag.facts import TIERS

        assert TIERS == self.LADDER

    def test_probe_sits_below_vendor_and_above_everything_written_outside(self) -> None:
        from studio.selfrag.facts import TIERS

        assert TIERS.index("probe") > TIERS.index("vendor")
        for weaker in ("operator", "paper", "benchmark", "portal", "blog"):
            assert TIERS.index("probe") < TIERS.index(weaker)

    def test_operator_sits_below_probe_and_above_everything_written_outside(self) -> None:
        """Добавлено 2026-08-31 по решению владельца. Ниже `probe`, потому что
        у них общий изъян — одно наблюдение одного аккаунта в один момент, — а
        записано оно человеком, не машиной. Выше статьи и бенчмарка, потому что
        те говорят про метод вообще, а оператор про эту модель и этот рабочий
        процесс сегодня."""
        from studio.selfrag.facts import TIERS

        assert TIERS.index("operator") > TIERS.index("probe")
        for weaker in ("paper", "benchmark", "portal", "blog"):
            assert TIERS.index("operator") < TIERS.index(weaker)

    def test_a_portal_outranks_a_blog_and_nothing_else(self) -> None:
        """The owner's middle rung, 2026-08-27: vendor page, then platforms,
        then everything else. A platform documents an endpoint that answers, so
        it beats an article; it documents its OWN endpoint with no published
        method, so it beats nothing above it."""
        from studio.selfrag.facts import TIERS

        assert TIERS.index("portal") < TIERS.index("blog")
        for stronger in ("vendor", "probe", "paper", "benchmark"):
            assert TIERS.index("portal") > TIERS.index(stronger)

    def test_a_probe_source_can_carry_a_claim_to_pass(self) -> None:
        from studio.selfrag.facts import Fact, FactStore

        store = FactStore([Fact("m", "a", "10", "https://api.test/x", "probe", "2026-08-27")])
        assert store.claims("m", "a")["outcome"] == "pass"

    def test_an_unrecognised_tier_never_reaches_pass(self) -> None:
        # It used to. The tier sorted below `blog`, but the "is this only
        # blogs" check compared against `blog` BY NAME, so a typo sailed past
        # the guard and the claim was reported as `pass` (OBSERVED 2026-08-27).
        from studio.selfrag.facts import Fact, FactStore

        for typo in ("twiter", "Vendor ", "probe-ish", ""):
            store = FactStore([Fact("m", "a", "10", "https://x.test", typo, "2026-08-27")])
            assert store.claims("m", "a")["outcome"] == "could not measure", (
                f"tier {typo!r} is not on the ladder and must not corroborate anything"
            )

    def test_blog_alone_still_never_reaches_pass(self) -> None:
        from studio.selfrag.facts import Fact, FactStore

        store = FactStore(
            [
                Fact("m", "a", "10", "https://b1.test", "blog", "2026-08-27"),
                Fact("m", "a", "10", "https://b2.test", "blog", "2026-08-27"),
            ]
        )
        assert store.claims("m", "a")["outcome"] == "could not measure"


if __name__ == "__main__":
    unittest.main()
