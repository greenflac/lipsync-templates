"""Web search: does it stay honest when it is unconfigured, empty, or refused?

No test reaches the network. The transport is replaced, so the suite measures
this code rather than Google's uptime and rather than a daily quota.
"""

from __future__ import annotations

import json
import unittest
import urllib.error
from unittest import mock

from studio.mcp import search

# The endpoint measured reachable on 2026-08-27, as a literal. If somebody
# repoints this at a host nobody probed, the test is SUPPOSED to fail.
ENDPOINT_HOST = "customsearch.googleapis.com"

DENIAL_TEXT = "Tunnel connection failed: 403 Forbidden"

# Programmable Search credentials, with every Gemini variable explicitly
# absent — otherwise these tests would silently exercise the other backend.
CREDS = {"GOOGLE_SEARCH_KEY": "test-key", "GOOGLE_CSE_ID": "test-cx"}

GEMINI_CREDS = {"GEMINI_API_KEY": "test-gemini-key"}


def _grounded(hosts: list[str], answer: str = "an answer") -> dict:
    return {
        "candidates": [
            {
                "content": {"parts": [{"text": answer}]},
                "groundingMetadata": {
                    "webSearchQueries": ["what the model searched"],
                    "groundingChunks": [
                        {"web": {"uri": f"https://redirect.google/{n}", "title": host}}
                        for n, host in enumerate(hosts)
                    ],
                },
            }
        ]
    }


class _Response:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode()

    def read(self, n: int = -1) -> bytes:
        return self._body[:n] if n and n > 0 else self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _hit(link: str, host: str) -> dict:
    return {"title": "T", "link": link, "displayLink": host, "snippet": "  a   snippet "}


class Search(unittest.TestCase):
    def test_the_endpoint_is_the_host_that_was_probed(self) -> None:
        assert ENDPOINT_HOST in search.ENDPOINT

    def test_unconfigured_is_could_not_measure_and_names_both_variables(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            out = search.search("anything")
        assert out["outcome"] == "could not measure"
        assert out["checked"] == 0
        for name in ("GOOGLE_SEARCH_KEY", "GOOGLE_CSE_ID"):
            assert name in out["note"], f"{name} must be named so it can be set"

    def test_half_configured_is_still_could_not_measure(self) -> None:
        with mock.patch.dict("os.environ", {"GOOGLE_SEARCH_KEY": "k"}, clear=True):
            out = search.search("anything")
        assert out["outcome"] == "could not measure"
        assert "search engine id" in out["note"]

    def test_an_empty_query_searches_nothing(self) -> None:
        with mock.patch.dict("os.environ", CREDS, clear=True):
            out = search.search("   ")
        assert out["outcome"] == "could not measure"
        assert out["results"] == []

    def test_zero_hits_is_could_not_measure_not_pass(self) -> None:
        payload = {"items": [], "searchInformation": {"totalResults": "0"}}
        with mock.patch.dict("os.environ", CREDS, clear=True):
            with mock.patch.object(
                search.urllib.request, "urlopen", return_value=_Response(payload)
            ):
                out = search.search("something nobody wrote about")
        assert out["outcome"] == "could not measure", "zero checks is never a pass"
        assert out["checked"] == 0

    def test_results_come_back_tagged_by_whether_the_host_opens(self) -> None:
        payload = {
            "items": [
                _hit("https://open.test/a", "open.test"),
                _hit("https://shut.test/b", "shut.test"),
                _hit("https://open.test/c", "open.test"),
            ]
        }

        def _probe(host: str) -> bool:
            return host == "open.test"

        with mock.patch.dict("os.environ", CREDS, clear=True):
            with mock.patch.object(
                search.urllib.request, "urlopen", return_value=_Response(payload)
            ):
                with mock.patch.object(search, "_fetchable", side_effect=_probe):
                    out = search.search("q")

        assert out["outcome"] == "pass"
        assert out["checked"] == 3
        assert out["unmeasured"] == 1, "the blocked host is counted, not hidden"
        assert [r["fetchable"] for r in out["results"]] == [True, False, True]
        assert out["results"][0]["snippet"] == "a snippet", "whitespace is squeezed"

    def test_each_host_is_probed_once_however_many_hits_it_has(self) -> None:
        payload = {"items": [_hit(f"https://same.test/{n}", "same.test") for n in range(4)]}
        with mock.patch.dict("os.environ", CREDS, clear=True):
            with mock.patch.object(
                search.urllib.request, "urlopen", return_value=_Response(payload)
            ):
                with mock.patch.object(search, "_fetchable", return_value=True) as probe:
                    search.search("q")
        assert probe.call_count == 1, "four hits on one host is one probe, not four"

    def test_the_fetchable_check_can_be_turned_off(self) -> None:
        payload = {"items": [_hit("https://x.test/a", "x.test")]}
        with mock.patch.dict("os.environ", CREDS, clear=True):
            with mock.patch.object(
                search.urllib.request, "urlopen", return_value=_Response(payload)
            ):
                with mock.patch.object(search, "_fetchable") as probe:
                    out = search.search("q", check_fetchable=False)
        assert probe.call_count == 0
        assert out["results"][0]["fetchable"] is None

    def test_a_site_filter_reaches_the_query(self) -> None:
        payload = {"items": [_hit("https://kling.ai/x", "kling.ai")]}
        with mock.patch.dict("os.environ", CREDS, clear=True):
            with mock.patch.object(
                search.urllib.request, "urlopen", return_value=_Response(payload)
            ):
                with mock.patch.object(search, "_fetchable", return_value=False):
                    out = search.search("duration", site="kling.ai")
        assert out["query"] == "site:kling.ai duration"

    def test_an_api_error_is_fail_and_repeats_the_setup(self) -> None:
        body = json.dumps({"error": {"message": "API key not valid"}}).encode()
        error = urllib.error.HTTPError(search.ENDPOINT, 403, "Forbidden", {}, None)  # type: ignore[arg-type]
        error.read = lambda n=-1: body  # type: ignore[method-assign]
        with mock.patch.dict("os.environ", CREDS, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=error):
                out = search.search("q")
        assert out["outcome"] == "fail", "the backend answered; that is not 'could not measure'"
        assert "API key not valid" in out["note"]
        assert "programmablesearchengine" in out["note"]

    def test_a_policy_denial_is_could_not_measure_not_fail(self) -> None:
        error = urllib.error.URLError(DENIAL_TEXT)
        with mock.patch.dict("os.environ", CREDS, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=error):
                with mock.patch.object(search, "note_denial") as noted:
                    out = search.search("q")
        assert out["outcome"] == "could not measure"
        assert noted.call_count == 1, "a refused backend feeds the allowlist request"

    def test_the_key_never_appears_in_what_is_returned(self) -> None:
        payload = {"items": [_hit("https://x.test/a", "x.test")]}
        creds = {"GOOGLE_SEARCH_KEY": "SECRET-key-42", "GOOGLE_CSE_ID": "SECRET-cx-42"}
        with mock.patch.dict("os.environ", creds, clear=True):
            with mock.patch.object(
                search.urllib.request, "urlopen", return_value=_Response(payload)
            ):
                with mock.patch.object(search, "_fetchable", return_value=True):
                    out = search.search("q")
        rendered = json.dumps(out, default=str)
        assert "SECRET-key-42" not in rendered
        assert "SECRET-cx-42" not in rendered

    def test_more_than_the_page_size_is_clamped(self) -> None:
        payload = {"items": [_hit("https://x.test/a", "x.test")]}
        captured: dict = {}

        def _capture(request, timeout=None):  # type: ignore[no-untyped-def]
            captured["url"] = request.full_url
            return _Response(payload)

        with mock.patch.dict("os.environ", CREDS, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=_capture):
                with mock.patch.object(search, "_fetchable", return_value=True):
                    search.search("q", count=500)
        assert "num=10" in captured["url"], "the API's page size maximum is 10"


class GeminiBackend(unittest.TestCase):
    """The whole-index route. Preferred, because the 50-domain cap is not."""

    def test_gemini_wins_when_both_are_configured(self) -> None:
        both = {**CREDS, **GEMINI_CREDS}
        with mock.patch.dict("os.environ", both, clear=True):
            with mock.patch.object(
                search.urllib.request, "urlopen", return_value=_Response(_grounded(["kling.ai"]))
            ):
                with mock.patch.object(search, "_fetchable", return_value=False):
                    out = search.search("q")
        assert out["backend"] == "gemini", (
            "the whole index beats 50 curated domains when both are available"
        )

    def test_the_publisher_becomes_the_host_because_the_url_is_a_redirect(self) -> None:
        with mock.patch.dict("os.environ", GEMINI_CREDS, clear=True):
            with mock.patch.object(
                search.urllib.request,
                "urlopen",
                return_value=_Response(_grounded(["kling.ai", "arxiv.org"])),
            ):
                with mock.patch.object(search, "_fetchable", return_value=True):
                    out = search.search("q")
        assert out["outcome"] == "pass"
        assert [r["host"] for r in out["results"]] == ["kling.ai", "arxiv.org"]
        assert all(r["url"].startswith("https://redirect.google/") for r in out["results"])

    def test_a_title_that_is_not_a_domain_yields_no_host(self) -> None:
        with mock.patch.dict("os.environ", GEMINI_CREDS, clear=True):
            with mock.patch.object(
                search.urllib.request,
                "urlopen",
                return_value=_Response(_grounded(["Some Article Headline"])),
            ):
                with mock.patch.object(search, "_fetchable") as probe:
                    out = search.search("q")
        assert out["results"][0]["host"] == ""
        assert probe.call_count == 0, "there is no host to probe, so none is invented"

    def test_grounding_nothing_at_all_is_could_not_measure(self) -> None:
        empty = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "  "}]},
                    "groundingMetadata": {"groundingChunks": []},
                }
            ]
        }
        with mock.patch.dict("os.environ", GEMINI_CREDS, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", return_value=_Response(empty)):
                out = search.search("q")
        assert out["outcome"] == "could not measure"
        assert out["checked"] == 0

    def test_an_answer_with_no_sources_still_counts_as_unmeasured(self) -> None:
        # Text but no citations: something came back, but nothing is checkable.
        payload = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "a real answer"}]},
                    "groundingMetadata": {"groundingChunks": []},
                }
            ]
        }
        with mock.patch.dict("os.environ", GEMINI_CREDS, clear=True):
            with mock.patch.object(
                search.urllib.request, "urlopen", return_value=_Response(payload)
            ):
                out = search.search("q")
        assert out["outcome"] == "pass"
        assert out["checked"] == 0
        assert out["unmeasured"] == 1, "an uncited answer is not a sourced one"
        assert out["answer"] == "a real answer"

    def test_an_api_error_is_fail_and_says_which_variable_held_the_key(self) -> None:
        body = json.dumps({"error": {"message": "API key not valid"}}).encode()
        error = urllib.error.HTTPError("https://x", 400, "Bad Request", {}, None)  # type: ignore[arg-type]
        error.read = lambda n=-1: body  # type: ignore[method-assign]
        with mock.patch.dict("os.environ", GEMINI_CREDS, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=error):
                out = search.search("q")
        assert out["outcome"] == "fail"
        assert "GEMINI_API_KEY" in out["note"]

    def test_the_gemini_key_never_appears_in_what_is_returned(self) -> None:
        creds = {"GEMINI_API_KEY": "SECRET-gemini-99"}
        with mock.patch.dict("os.environ", creds, clear=True):
            with mock.patch.object(
                search.urllib.request, "urlopen", return_value=_Response(_grounded(["x.test"]))
            ):
                with mock.patch.object(search, "_fetchable", return_value=True):
                    out = search.search("q")
        assert "SECRET-gemini-99" not in json.dumps(out, default=str)

    def test_the_setup_text_leads_with_gemini_and_warns_about_the_cap(self) -> None:
        assert search.SETUP.index("GEMINI GROUNDING") < search.SETUP.index("PROGRAMMABLE SEARCH")
        assert "March" in search.SETUP and "50" in search.SETUP


if __name__ == "__main__":
    unittest.main()
