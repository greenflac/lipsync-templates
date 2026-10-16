"""Web search: does it stay honest when it is unconfigured, empty, or refused?

No test reaches the network. The transport is replaced, so the suite measures
this code rather than Google's uptime and rather than a daily quota.
"""

from __future__ import annotations

import json
import pathlib
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


class _Clean(unittest.TestCase):
    """Отказы аккаунтов помнятся в процессе (`NOT_SERVED_TTL_SECONDS`); каждый
    тест начинает с пустой памяти, иначе 402 одного теста выключал бы Gemini
    в следующем."""

    def setUp(self) -> None:
        search.forget_refusals()


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


# The spelling the owner actually used, as a literal. This is not a variable
# the package chose — it is what was found in the live container on
# 2026-08-27, and the package reported "no key" beside it for a whole session.
LIVE_SPELLING = "Gemini_API_KEY"


class CredentialNames(_Clean):
    """A lookup that guesses at a name will meet a name somebody else chose.

    Second occurrence of this shape in the package: `probe.py` looked for
    `KLING_API_KEY` while the environment set `KLING_KEY`.
    """

    def test_a_key_spelled_in_another_case_is_found_not_reported_missing(self) -> None:
        with mock.patch.dict("os.environ", {LIVE_SPELLING: "live-key"}, clear=True):
            key, name = search._first_env(search.GEMINI_KEY_ENV)
        assert key == "live-key"
        assert name == LIVE_SPELLING, "report the spelling that was set, not the expected one"

    def test_the_kling_lookup_is_the_same_lookup(self) -> None:
        from studio.mcp import probe

        with mock.patch.dict("os.environ", {"kling_key": "k1"}, clear=True):
            key, name = probe._key_for("api.klingai.com")
        assert (key, name) == ("k1", "kling_key")

    def test_an_exact_name_beats_a_case_folded_one(self) -> None:
        # Deliberately arranged so that dropping the exact-match pass changes
        # the answer: `GEMINI_Api_Key` sorts BEFORE `GOOGLE_API_KEY`, so a
        # lookup that only case-folds would return "folded" here. An earlier
        # version of this test used `GEMINI_API_KEY`/`gemini_api_key`, where
        # sort order happens to agree with the rule — it stayed green with the
        # exact-match pass deleted and was measuring nothing.
        both = {"GEMINI_Api_Key": "folded", "GOOGLE_API_KEY": "exact"}
        assert "GEMINI_Api_Key" < "GOOGLE_API_KEY", "the trap this test sets"
        with mock.patch.dict("os.environ", both, clear=True):
            key, name = search._first_env(search.GEMINI_KEY_ENV)
        assert key == "exact", "listing a preferred spelling must keep meaning something"
        assert name == "GOOGLE_API_KEY"

    def test_two_spellings_of_one_name_resolve_the_same_way_every_run(self) -> None:
        both = {"Gemini_Api_Key": "a", "gemini_api_KEY": "b"}
        with mock.patch.dict("os.environ", both, clear=True):
            first = search._first_env(search.GEMINI_KEY_ENV)
        with mock.patch.dict("os.environ", dict(reversed(both.items())), clear=True):
            second = search._first_env(search.GEMINI_KEY_ENV)
        assert first == second == ("a", "Gemini_Api_Key"), (
            "a lookup that picks by dict order changes its mind between processes"
        )

    def test_an_unrelated_variable_is_not_swept_in(self) -> None:
        with mock.patch.dict("os.environ", {"MY_GEMINI_API_KEY": "no"}, clear=True):
            key, name = search._first_env(search.GEMINI_KEY_ENV)
        assert (key, name) == ("", ""), "loose on case, not loose on the name"

    def test_a_variable_set_to_whitespace_counts_as_unset(self) -> None:
        # Both spellings, because the two are found by two different passes and
        # an earlier version only exercised one of them: an empty shell
        # substitution leaves whitespace behind either way.
        for spelling in (LIVE_SPELLING, "GEMINI_API_KEY"):
            with self.subTest(spelling=spelling):
                with mock.patch.dict("os.environ", {spelling: "   "}, clear=True):
                    key, name = search._first_env(search.GEMINI_KEY_ENV)
                assert (key, name) == ("", "")


class Search(_Clean):
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

    def test_a_refused_search_hit_does_not_become_an_allowlist_request(self) -> None:
        """The one that actually happened, on the first live search.

        One query tagged five result hosts as unreachable and put all five into
        the file a human reads to decide what access to grant — beside six
        hosts a real question was stuck behind. The refusals must still be
        recorded; they must not be presented as something somebody asked for.
        """
        from tempfile import TemporaryDirectory

        from studio.mcp import fetch as fetch_module

        payload = {"items": [_hit("https://wavespeed.ai/x", "wavespeed.ai")]}
        error = urllib.error.URLError(DENIAL_TEXT)

        with TemporaryDirectory() as tmp:
            denied = pathlib.Path(tmp) / "denied.jsonl"
            with mock.patch.object(fetch_module, "DENIED_PATH", denied):
                with mock.patch.dict("os.environ", CREDS, clear=True):
                    # The search call itself succeeds; only the per-host
                    # reachability probe underneath it is refused.
                    def _transport(request, *a, **k):  # type: ignore[no-untyped-def]
                        url = getattr(request, "full_url", str(request))
                        if ENDPOINT_HOST in url:
                            return _Response(payload)
                        raise error

                    with mock.patch.object(
                        search.urllib.request, "urlopen", side_effect=_transport
                    ):
                        out = search.search("q")

                assert out["results"][0]["fetchable"] is False, "the probe did run"
                assert denied.is_file(), "the refusal is still recorded, not swallowed"
                asked = fetch_module.wanted()

        assert asked["hosts"] == [], "nobody asked for a host that merely turned up"
        assert [r["host"] for r in asked["also_refused"]] == ["wavespeed.ai"]
        assert asked["also_refused"][0]["why_wanted"].strip(), (
            "a row nobody can explain is a row nobody can act on"
        )

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
        """An INVALID key (400) is ours to fix: `fail`, with the setup text.

        Until 2026-10-14 this case was a 403; 403 is now a permission/quota
        refusal and is tested below as `could not measure`."""
        body = json.dumps({"error": {"message": "API key not valid"}}).encode()
        error = urllib.error.HTTPError(search.ENDPOINT, 400, "Bad Request", {}, None)  # type: ignore[arg-type]
        error.read = lambda n=-1: body  # type: ignore[method-assign]
        with mock.patch.dict("os.environ", CREDS, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=error):
                out = search.search("q")
        assert out["outcome"] == "fail", "the backend answered; that is not 'could not measure'"
        assert "API key not valid" in out["note"]
        assert "programmablesearchengine" in out["note"]

    def test_a_403_from_the_search_api_is_permission_not_a_broken_key(self) -> None:
        body = json.dumps({"error": {"message": "Requests to this API are blocked."}}).encode()
        error = urllib.error.HTTPError(search.ENDPOINT, 403, "Forbidden", {}, None)  # type: ignore[arg-type]
        error.read = lambda n=-1: body  # type: ignore[method-assign]
        with mock.patch.dict("os.environ", CREDS, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=error):
                out = search.search("q")
        assert out["outcome"] == "could not measure"
        assert "PERMISSION" in out["note"]
        assert "client_side" in out

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


class GeminiBackend(_Clean):
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

    def test_ANSWER_WITHOUT_A_SINGLE_SOURCE_IS_NOT_A_PASS(self) -> None:
        """Найдено проверкой продукта 2026-09-06, и это худшее из найденного.

        На «what is two plus two» и на прямое «из своей памяти, без веба» этот
        инструмент отвечал `pass`, `checked 0`, и сам же писал в ноте «Searches
        Gemini ran: not reported» — поиска не было ВООБЩЕ. Поле `answer` несло
        память чужой модели, а нота называла её «the substance».

        Цена названа в инструкции самого сервера: агенту велено после поиска
        звать `record_model_fact`. Поверив `pass`, он записал бы галлюцинацию в
        базу фактов под видом веб-находки — то есть отравил бы ровно то, ради
        чистоты чего весь проект.
        """
        пусто = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Two plus two is four."}]},
                    "groundingMetadata": {},
                }
            ]
        }
        with mock.patch.dict("os.environ", GEMINI_CREDS, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", return_value=_Response(пусто)):
                out = search.search("what is two plus two")
        assert out["outcome"] == "could not measure", out["outcome"]
        assert out["checked"] == 0
        assert out["unmeasured"] == 1
        assert out["results"] == []
        assert "НИ ОДНОГО ИСТОЧНИКА" in out["note"]
        # Текст остаётся в выдаче — но названный тем, что он есть.
        assert out["answer"].startswith("Two plus two")

    def test_A_GROUNDED_ANSWER_IS_STILL_A_PASS(self) -> None:
        """Негативный контроль (И5) к предыдущему: инструмент, отвечающий «не
        смогли» всегда, не отличается от отсутствующего инструмента."""
        with mock.patch.dict("os.environ", GEMINI_CREDS, clear=True):
            with mock.patch.object(
                search.urllib.request,
                "urlopen",
                return_value=_Response(_grounded(["kling.ai"])),
            ):
                with mock.patch.object(search, "_fetchable", return_value=True):
                    out = search.search("q")
        assert out["outcome"] == "pass"
        assert out["checked"] == 1
        assert out["unmeasured"] == 0

    def test_unmeasured_holds_both_meanings_apart(self) -> None:
        """Е3: счётчик нечитаемых хостов не смеет затирать «источников нет»."""
        with mock.patch.dict("os.environ", GEMINI_CREDS, clear=True):
            with mock.patch.object(
                search.urllib.request,
                "urlopen",
                return_value=_Response(_grounded(["kling.ai", "arxiv.org"])),
            ):
                with mock.patch.object(search, "_fetchable", return_value=False):
                    out = search.search("q")
        assert out["outcome"] == "pass"
        assert out["unmeasured"] == 2, "два нечитаемых хоста обязаны быть посчитаны"

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

    def test_an_answer_with_no_sources_is_NOT_a_pass(self) -> None:
        """ИСХОД ЭТОГО СЛУЧАЯ ИЗМЕНЁН 2026-09-06, и прежний был неправдой.

        Тест назывался «...still counts as unmeasured» и при этом требовал
        `outcome == pass`: неизмеримость честно считалась ЧИСЛОМ, а вердикт всё
        равно был успехом. Проверка продукта показала цену — инструмент отвечал
        `pass` на запрос, где Gemini не сделал ни одного поиска, и агент,
        которому велено после поиска звать `record_model_fact`, записал бы
        память чужой модели в базу фактов как веб-находку.

        Текст в выдаче остаётся: он может быть полезен человеку. Вердиктом он
        не становится (Р2: ноль проверок — не успех).
        """
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
        assert out["outcome"] == "could not measure"
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


def _http_error(url: str, code: int, payload: dict | str) -> urllib.error.HTTPError:
    body = (payload if isinstance(payload, str) else json.dumps(payload)).encode()
    error = urllib.error.HTTPError(url, code, "x", {}, None)  # type: ignore[arg-type]
    error.read = lambda n=-1: body  # type: ignore[method-assign]
    return error


def _router(routes: dict):  # type: ignore[no-untyped-def]
    """A transport that answers by host: value is a payload dict or an exception."""

    def _transport(request, *a, **k):  # type: ignore[no-untyped-def]
        url = getattr(request, "full_url", str(request))
        for needle, answer in routes.items():
            if needle in url:
                if isinstance(answer, BaseException):
                    raise answer
                return _Response(answer)
        raise AssertionError(f"unexpected request to {url}")

    return _transport


SERPER = {"SERPER_KEY": "test-serper"}
SERPER_HIT = {
    "organic": [
        {
            "title": "Kling docs",
            "link": "https://docs.klingai.test/a",
            "snippet": " 10  s ",
            "date": "2026-09-01",
        }
    ]
}


class BillingAndFallback(_Clean):
    """2026-10-14, live: Gemini answered 402 (prepayment depleted) and the tool
    said `fail` + "create an API key" beside a working key, while SERPER_KEY
    sat unused. Literals below are the statuses and words that happened (T2)."""

    def test_402_is_billing_could_not_measure_and_never_says_create_a_key(self) -> None:
        error = _http_error(
            "https://g", 402, {"error": {"message": "Your prepayment credits are depleted."}}
        )
        with mock.patch.dict("os.environ", GEMINI_CREDS, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=error):
                out = search.search("q")
        assert out["outcome"] == "could not measure", out["note"]
        assert "BILLING" in out["note"]
        assert "create an API key" not in out["note"], "the key exists; the account cannot pay"
        assert out["client_side"]["queries"][0] == "q"

    def test_the_status_alone_decides_without_any_telling_words(self) -> None:
        """T1: the body here carries no billing/quota word, so only the status
        set can make these `could not measure` — drop a code and it goes red."""
        for code in (402, 403, 429, 432, 433):
            search.forget_refusals()
            with self.subTest(code=code):
                error = _http_error("https://g", code, {"error": {"message": "x"}})
                with mock.patch.dict("os.environ", GEMINI_CREDS, clear=True):
                    with mock.patch.object(search.urllib.request, "urlopen", side_effect=error):
                        out = search.search("q")
                assert out["outcome"] == "could not measure", (code, out["note"])
        search.forget_refusals()
        error = _http_error("https://g", 401, {"error": {"message": "x"}})
        with mock.patch.dict("os.environ", GEMINI_CREDS, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=error):
                assert search.search("q")["outcome"] == "fail", "the other side: 401 is the key"

    def test_429_is_quota(self) -> None:
        error = _http_error("https://g", 429, {"error": {"message": "Resource has been exhausted"}})
        with mock.patch.dict("os.environ", GEMINI_CREDS, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=error):
                out = search.search("q")
        assert out["outcome"] == "could not measure"
        assert "QUOTA" in out["note"]

    def test_gemini_402_falls_back_to_serper(self) -> None:
        routes = {
            "generativelanguage": _http_error("https://g", 402, {"error": {"message": "depleted"}}),
            "google.serper.dev": SERPER_HIT,
        }
        with mock.patch.dict("os.environ", {**GEMINI_CREDS, **SERPER}, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=_router(routes)):
                with mock.patch.object(search, "_fetchable", return_value=True):
                    out = search.search("kling max seconds")
        assert out["outcome"] == "pass"
        assert out["backend"] == "serper"
        assert [a["backend"] for a in out["attempts"]] == ["gemini", "serper"]
        assert out["attempts"][0]["outcome"] == "could not measure"
        assert out["results"][0]["host"] == "docs.klingai.test"
        assert out["results"][0]["snippet"] == "10 s"
        assert out["results"][0]["date"] == "2026-09-01"
        assert "Fell back after: gemini" in out["note"]

    def test_negative_control_gemini_that_works_is_not_skipped(self) -> None:
        """И5: with Gemini healthy, Serper must NOT be called (it costs credits)."""
        routes = {"generativelanguage": _grounded(["kling.ai"])}
        with mock.patch.dict("os.environ", {**GEMINI_CREDS, **SERPER}, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=_router(routes)):
                with mock.patch.object(search, "_fetchable", return_value=True):
                    out = search.search("q")
        assert out["backend"] == "gemini"
        assert [a["backend"] for a in out["attempts"]] == ["gemini"]

    def test_serper_out_of_credits_under_a_400_is_billing(self) -> None:
        error = _http_error(
            search.SERPER_ENDPOINT, 400, {"message": "Not enough credits", "statusCode": 400}
        )
        with mock.patch.dict("os.environ", SERPER, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=error):
                out = search.search("q")
        assert out["outcome"] == "could not measure"
        assert "BILLING" in out["note"]

    def test_serper_sends_its_key_as_a_header_and_never_returns_it(self) -> None:
        seen: dict = {}

        def _capture(request, timeout=None):  # type: ignore[no-untyped-def]
            seen["url"] = request.full_url
            seen["key"] = request.get_header("X-api-key")
            seen["body"] = json.loads(request.data)
            return _Response(SERPER_HIT)

        with mock.patch.dict("os.environ", {"SERPER_API_KEY": "SECRET-serper-7"}, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=_capture):
                out = search.search("q", site="kling.ai", check_fetchable=False)
        assert seen["url"] == "https://google.serper.dev/search"
        assert seen["key"] == "SECRET-serper-7"
        assert seen["body"]["q"] == "site:kling.ai q"
        assert "SECRET-serper-7" not in json.dumps(out)

    def test_order_is_gemini_serper_cse_brave_tavily_exa_then_yandex_last(self) -> None:
        assert [name for name, _c, _r in search.BACKENDS] == [
            "gemini",
            "serper",
            "programmable-search",
            "brave",
            "tavily",
            "exa",
            "yandex",
        ]

    def test_every_backend_failing_gives_client_side_queries(self) -> None:
        routes = {
            "generativelanguage": _http_error("https://g", 402, {"error": {"message": "depleted"}}),
            "google.serper.dev": _http_error("https://s", 429, {"message": "rate limit"}),
        }
        with mock.patch.dict("os.environ", {**GEMINI_CREDS, **SERPER}, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=_router(routes)):
                out = search.search("veo 3.1 max resolution", site="ai.google.dev")
        assert out["outcome"] == "could not measure"
        assert out["checked"] == 0
        assert [a["backend"] for a in out["attempts"]] == ["gemini", "serper"]
        side = out["client_side"]
        assert side["mode"] == "client-side search"
        assert side["queries"][0] == "site:ai.google.dev veo 3.1 max resolution"
        assert "record_model_fact" in side["then"]

    def test_an_invalid_key_with_nothing_else_is_still_fail(self) -> None:
        """P1: the backend refused OUR key, and no backend answered — `fail`."""
        routes = {
            "generativelanguage": _http_error("https://g", 402, {"error": {"message": "depleted"}}),
            "google.serper.dev": _http_error("https://s", 401, {"message": "Unauthorized."}),
        }
        with mock.patch.dict("os.environ", {**GEMINI_CREDS, **SERPER}, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=_router(routes)):
                out = search.search("q")
        assert out["outcome"] == "fail"
        assert out["violations"] == 1

    def test_unconfigured_also_offers_client_side(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            out = search.search("anything")
        assert out["client_side"]["queries"][0] == "anything"
        for name in ("SERPER_API_KEY", "BRAVE_SEARCH_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY"):
            assert name in out["note"]


class OtherBackends(_Clean):
    def _one(self, env: dict, payload: dict) -> tuple[dict, dict]:
        seen: dict = {}

        def _capture(request, timeout=None):  # type: ignore[no-untyped-def]
            seen["url"] = request.full_url
            seen["headers"] = dict(request.header_items())
            seen["body"] = json.loads(request.data) if request.data else None
            return _Response(payload)

        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=_capture):
                out = search.search("q", count=3, check_fetchable=False)
        return out, seen

    def test_brave(self) -> None:
        out, seen = self._one(
            {"BRAVE_SEARCH_API_KEY": "b"},
            {"web": {"results": [{"title": "T", "url": "https://x.test/1", "description": "d"}]}},
        )
        assert out["backend"] == "brave" and out["outcome"] == "pass"
        assert seen["url"].startswith("https://api.search.brave.com/res/v1/web/search?")
        assert seen["headers"]["X-subscription-token"] == "b"
        assert out["results"][0]["host"] == "x.test"

    def test_tavily(self) -> None:
        out, seen = self._one(
            {"TAVILY_API_KEY": "t"},
            {"results": [{"title": "T", "url": "https://y.test/1", "content": "c"}]},
        )
        assert out["backend"] == "tavily" and out["outcome"] == "pass"
        assert seen["url"] == "https://api.tavily.com/search"
        assert seen["headers"]["Authorization"] == "Bearer t"
        assert seen["body"]["max_results"] == 3

    def test_tavily_plan_limit_432_is_quota(self) -> None:
        error = _http_error(search.TAVILY_ENDPOINT, 432, {"detail": {"error": "plan limit"}})
        with mock.patch.dict("os.environ", {"TAVILY_API_KEY": "t"}, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=error):
                out = search.search("q")
        assert out["outcome"] == "could not measure"

    def test_exa(self) -> None:
        out, seen = self._one(
            {"EXA_API_KEY": "e"},
            {"results": [{"title": "T", "url": "https://z.test/1", "publishedDate": "2026-01-02"}]},
        )
        assert out["backend"] == "exa" and out["outcome"] == "pass"
        assert seen["url"] == "https://api.exa.ai/search"
        assert seen["headers"]["X-api-key"] == "e"
        assert out["results"][0]["date"] == "2026-01-02"

    def test_zero_hits_on_a_backend_is_not_a_pass(self) -> None:
        out, _ = self._one({"EXA_API_KEY": "e"}, {"results": []})
        assert out["outcome"] == "could not measure"
        assert out["checked"] == 0


class GeminiModelFromEnv(_Clean):
    def test_default_model_is_a_literal(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            assert search.gemini_model() == "gemini-2.5-flash"

    def test_env_overrides_the_model_in_the_url(self) -> None:
        seen: dict = {}

        def _capture(request, timeout=None):  # type: ignore[no-untyped-def]
            seen["url"] = request.full_url
            return _Response(_grounded(["kling.ai"]))

        env = {**GEMINI_CREDS, "GEMINI_SEARCH_MODEL": "gemini-3-flash"}
        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=_capture):
                with mock.patch.object(search, "_fetchable", return_value=True):
                    search.search("q")
        assert "/models/gemini-3-flash:generateContent" in seen["url"]


class RefusalKeepsTheQuery(_Clean):
    """G15, 2026-10-14: a refusal answer carried `"query": ""`, so a caller with
    several searches in flight could not tell which one had failed."""

    def test_a_billing_refusal_still_names_the_query(self) -> None:
        error = _http_error("https://g", 402, {"error": {"message": "depleted"}})
        with mock.patch.dict("os.environ", GEMINI_CREDS, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=error):
                out = search.search("veo 3.1 max resolution", site="ai.google.dev")
        assert out["query"] == "site:ai.google.dev veo 3.1 max resolution"

    def test_unconfigured_still_names_the_query(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=True):
            assert search.search("kling limits")["query"] == "kling limits"


class AccountRefusalsAreRemembered(_Clean):
    """G15, 2026-10-14: Gemini answered 402 on EVERY call — the server paid a
    request and a timeout each time to learn the same thing."""

    def _calls(self, routes: dict, n: int, env: dict, clock: list[float]) -> tuple[list, list]:
        seen: list[str] = []
        transport = _router(routes)

        def _counting(request, *a, **k):  # type: ignore[no-untyped-def]
            seen.append(request.full_url)
            return transport(request, *a, **k)

        outs = []
        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=_counting):
                with mock.patch.object(search, "_now", side_effect=lambda: clock[0]):
                    for _ in range(n):
                        outs.append(search.search("q", check_fetchable=False))
        return seen, outs

    def test_a_402_is_asked_once_then_skipped_with_an_honest_note(self) -> None:
        routes = {
            "generativelanguage": _http_error("https://g", 402, {"error": {"message": "depleted"}}),
            "google.serper.dev": SERPER_HIT,
        }
        clock = [1000.0]
        seen, outs = self._calls(routes, 3, {**GEMINI_CREDS, **SERPER}, clock)
        assert sum("generativelanguage" in u for u in seen) == 1, seen
        assert outs[2]["backend"] == "serper"
        skipped = outs[2]["attempts"][0]
        assert skipped["backend"] == "gemini" and skipped.get("skipped") is True
        assert "SKIPPED" in skipped["note"] and "BILLING" in skipped["note"]

    def test_after_the_ttl_the_backend_is_asked_again(self) -> None:
        routes = {
            "generativelanguage": _http_error("https://g", 402, {"error": {"message": "depleted"}}),
            "google.serper.dev": SERPER_HIT,
        }
        clock = [1000.0]
        seen: list[str] = []
        transport = _router(routes)

        def _counting(request, *a, **k):  # type: ignore[no-untyped-def]
            seen.append(request.full_url)
            return transport(request, *a, **k)

        with mock.patch.dict("os.environ", {**GEMINI_CREDS, **SERPER}, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=_counting):
                with mock.patch.object(search, "_now", side_effect=lambda: clock[0]):
                    search.search("q", check_fetchable=False)
                    clock[0] = 1000.0 + 3599.0
                    search.search("q", check_fetchable=False)
                    assert sum("generativelanguage" in u for u in seen) == 1, "inside 1 h"
                    clock[0] = 1000.0 + 3601.0
                    search.search("q", check_fetchable=False)
        assert sum("generativelanguage" in u for u in seen) == 2, "after 1 h it is asked again"

    def test_the_ttl_is_one_hour_as_a_literal(self) -> None:
        assert search.NOT_SERVED_TTL_SECONDS == 3600.0

    def test_a_new_key_is_a_new_attempt(self) -> None:
        routes = {
            "generativelanguage": _http_error("https://g", 402, {"error": {"message": "depleted"}}),
        }
        clock = [5.0]
        seen, _ = self._calls(routes, 1, {"GEMINI_API_KEY": "old"}, clock)
        seen2, _ = self._calls(routes, 1, {"GEMINI_API_KEY": "new"}, clock)
        assert len(seen) == 1 and len(seen2) == 1, "a different key must be asked"

    def test_a_401_bad_key_is_NOT_remembered(self) -> None:
        """Negative control: only billing and quota are cached; a key error is
        the caller's to fix and must be re-asked at once."""
        routes = {"generativelanguage": _http_error("https://g", 401, {"error": {"message": "x"}})}
        clock = [5.0]
        seen, _ = self._calls(routes, 2, GEMINI_CREDS, clock)
        assert len(seen) == 2

    def test_a_403_permission_is_NOT_remembered(self) -> None:
        routes = {"generativelanguage": _http_error("https://g", 403, {"error": {"message": "x"}})}
        clock = [5.0]
        seen, _ = self._calls(routes, 2, GEMINI_CREDS, clock)
        assert len(seen) == 2

    def test_a_429_quota_IS_remembered(self) -> None:
        routes = {"generativelanguage": _http_error("https://g", 429, {"error": {"message": "x"}})}
        clock = [5.0]
        seen, outs = self._calls(routes, 2, GEMINI_CREDS, clock)
        assert len(seen) == 1
        assert "QUOTA" in outs[1]["attempts"][0]["note"]
        assert outs[1]["outcome"] == "could not measure"

    def test_the_key_itself_is_not_kept(self) -> None:
        routes = {"generativelanguage": _http_error("https://g", 402, {"error": {"message": "x"}})}
        self._calls(routes, 1, {"GEMINI_API_KEY": "SECRET-123"}, [5.0])
        assert "SECRET-123" not in repr(search._NOT_SERVED)


YANDEX_ENV = {
    "YANDEX_SEARCH_API_KEY": "SECRET-yandex-1",
    "YANDEX_FOLDER_ID": "b1gfolder",
    "STUDIO_SEARCH_ALLOW_YANDEX": "1",
}

# The classic Yandex XML shape. A FIXTURE, not a captured response: no live
# call was made (the key is the owner's and the price is unverified).
YANDEX_XML = """<?xml version="1.0" encoding="utf-8"?>
<yandexsearch version="1.0"><response><results><grouping>
<group><doc><url>https://docs.example.test/veo</url><domain>docs.example.test</domain>
<title>Veo <hlword>3.1</hlword> limits</title><modtime>20260901T000000</modtime>
<passages><passage>up to <hlword>4k</hlword> output</passage></passages></doc></group>
<group><doc><url>https://blog.example.test/x</url><domain>blog.example.test</domain>
<title>Other</title><headline>a headline</headline></doc></group>
</grouping></results></response></yandexsearch>"""


def _yandex_payload(xml: str) -> dict:
    import base64

    return {"rawData": base64.b64encode(xml.encode("utf-8")).decode("ascii")}


class YandexBackend(_Clean):
    """G15: Yandex as the LAST backend, opt-in only. All mocked: no live call."""

    def _capture(self, env: dict, payload: dict | BaseException, query: str = "veo 3.1"):
        seen: dict = {}

        def _transport(request, timeout=None):  # type: ignore[no-untyped-def]
            seen["url"] = request.full_url
            seen["auth"] = request.get_header("Authorization")
            seen["body"] = json.loads(request.data)
            if isinstance(payload, BaseException):
                raise payload
            return _Response(payload)

        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=_transport):
                out = search.search(query, check_fetchable=False)
        return seen, out

    def test_a_key_alone_is_not_consent(self) -> None:
        env = {k: v for k, v in YANDEX_ENV.items() if k != "STUDIO_SEARCH_ALLOW_YANDEX"}
        seen, out = self._capture(env, _yandex_payload(YANDEX_XML))
        assert seen == {}, "without the opt-in nothing may be sent to Yandex"
        assert out["outcome"] == "could not measure"

    def test_opt_in_must_be_exactly_1(self) -> None:
        seen, _ = self._capture({**YANDEX_ENV, "STUDIO_SEARCH_ALLOW_YANDEX": "yes"}, {})
        assert seen == {}

    def test_the_request_follows_the_vendor_proto(self) -> None:
        seen, out = self._capture(YANDEX_ENV, _yandex_payload(YANDEX_XML))
        assert seen["url"] == "https://searchapi.api.cloud.yandex.net/v2/web/search"
        assert seen["auth"] == "Api-Key SECRET-yandex-1"
        body = seen["body"]
        assert body["query"]["searchType"] == "SEARCH_TYPE_COM"
        assert body["query"]["queryText"] == "veo 3.1"
        assert body["folderId"] == "b1gfolder"
        assert body["responseFormat"] == "FORMAT_XML"
        assert "SECRET-yandex-1" not in json.dumps(out)

    def test_a_cyrillic_query_goes_to_the_russian_index(self) -> None:
        seen, _ = self._capture(YANDEX_ENV, _yandex_payload(YANDEX_XML), query="длительность veo")
        assert seen["body"]["query"]["searchType"] == "SEARCH_TYPE_RU"

    def test_the_xml_is_parsed_into_rows(self) -> None:
        _, out = self._capture(YANDEX_ENV, _yandex_payload(YANDEX_XML))
        assert out["outcome"] == "pass", out["note"]
        assert out["backend"] == "yandex"
        first = out["results"][0]
        assert first["url"] == "https://docs.example.test/veo"
        assert first["host"] == "docs.example.test"
        assert first["title"] == "Veo 3.1 limits"
        assert first["snippet"] == "up to 4k output"
        assert out["results"][1]["snippet"] == "a headline"

    def test_a_yandex_error_element_is_could_not_measure(self) -> None:
        xml = (
            '<yandexsearch><response><error code="15">No results</error></response></yandexsearch>'
        )
        _, out = self._capture(YANDEX_ENV, _yandex_payload(xml))
        assert out["outcome"] == "could not measure"
        assert "error 15" in out["note"]

    def test_yandex_is_asked_only_after_everything_else(self) -> None:
        routes = {
            "generativelanguage": _http_error("https://g", 402, {"error": {"message": "x"}}),
            "searchapi.api.cloud.yandex.net": _yandex_payload(YANDEX_XML),
        }
        with mock.patch.dict("os.environ", {**GEMINI_CREDS, **YANDEX_ENV}, clear=True):
            with mock.patch.object(search.urllib.request, "urlopen", side_effect=_router(routes)):
                out = search.search("q", check_fetchable=False)
        assert [a["backend"] for a in out["attempts"]] == ["gemini", "yandex"]
        assert out["backend"] == "yandex"

    def test_a_long_query_is_cut_to_the_proto_limit(self) -> None:
        seen, _ = self._capture(YANDEX_ENV, _yandex_payload(YANDEX_XML), query="x" * 450)
        assert len(seen["body"]["query"]["queryText"]) == 400


if __name__ == "__main__":
    unittest.main()
