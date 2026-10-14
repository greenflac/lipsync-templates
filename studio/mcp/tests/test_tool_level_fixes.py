"""Tool-level defects found by the 2026-10-14 audit and live run, one class per item.

Each expected value is a literal (T2). No test reaches the network (T4): the
transport is replaced, and the one end-to-end test of the connection guard
talks to a server on the loopback interface that the guard must refuse to
reach. No test writes `studio/knowledge/*.jsonl`: every journal path is
replaced with a temporary one.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from studio.mcp import fetch, probe
from studio.mcp import server as S


class _Response:
    def __init__(self, body: bytes, status: int = 200, content_type: str = "") -> None:
        self._body = body
        self.status = status
        self.headers = {"Content-Type": content_type} if content_type else {}

    def read(self, n: int = -1) -> bytes:
        return self._body[:n] if n and n > 0 else self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


DENIAL = urllib.error.URLError("Tunnel connection failed: 403 Forbidden")


class _TempJournal(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)
        self.denied = self.tmp / "denied.jsonl"
        patcher = mock.patch.object(fetch, "DENIED_PATH", self.denied)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rows(self) -> list[dict]:
        if not self.denied.exists():
            return []
        return [json.loads(x) for x in self.denied.read_text(encoding="utf-8").splitlines() if x]


# --- item 5: reachable_hosts parses URLs, never records junk -----------------


class HostParsing(unittest.TestCase):
    def test_a_url_is_reduced_to_its_host(self) -> None:
        for given in ("https://x.y/z", "x.y", "X.Y.", "x.y:443", "http://x.y:8080/a?b=c"):
            with self.subTest(given=given):
                assert fetch.нормализовать_хост(given) == ("x.y", "")

    def test_junk_is_refused_with_a_reason(self) -> None:
        for given in ("https", "https://", "not a host", "-bad-.com", "ftp://x.y/", ""):
            with self.subTest(given=given):
                host, why = fetch.нормализовать_хост(given)
                assert host == "" and why, (given, host, why)

    def test_the_old_regex_traps_are_closed(self) -> None:
        assert fetch._host("https://https://x.y/z") == ""
        assert fetch._host("https://evil.test@127.0.0.1/") == "127.0.0.1"
        assert fetch._host("https://docs.vendor.test/a") == "docs.vendor.test"


class ReachabilityNeverRecordsJunk(_TempJournal):
    def test_the_live_input_records_the_real_host_and_nothing_else(self) -> None:
        sent: list[str] = []

        def _transport(request, *a, **k):  # type: ignore[no-untyped-def]
            sent.append(request.full_url)
            raise DENIAL

        with mock.patch.object(urllib.request, "urlopen", side_effect=_transport):
            out = fetch.reachability(["https://x.y/z", "https", "not a host"])
        assert sent == ["https://x.y/"]
        assert out["closed"] == ["x.y"]
        assert [i["input"] for i in out["invalid"]] == ["https", "not a host"]
        assert [r["host"] for r in self.rows()] == ["x.y"]

    def test_all_junk_is_fail_and_nothing_is_sent(self) -> None:
        with mock.patch.object(urllib.request, "urlopen") as transport:
            out = fetch.reachability(["https", "  "])
        assert transport.call_count == 0
        assert out["outcome"] == "fail"
        assert self.rows() == []

    def test_a_comma_string_is_split_not_iterated_by_character(self) -> None:
        with mock.patch.object(urllib.request, "urlopen", return_value=_Response(b"ok")):
            out = fetch.reachability("a.test, b.test")
        assert out["open"] == ["a.test", "b.test"]

    def test_the_map_carries_its_date_and_vantage(self) -> None:
        with mock.patch.object(urllib.request, "urlopen", return_value=_Response(b"ok")):
            out = fetch.reachability(["a.test"])
        assert out["measured_on"]
        assert out["vantage"].startswith("this server's process")


# --- item 4: SSRF ------------------------------------------------------------


class SSRFBeforeSending(_TempJournal):
    REFUSED = (
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "http://172.16.5.4/",
        "http://192.168.1.1/",
        "http://127.0.0.1:8080/admin",
        "http://2130706433/",
        "http://0x7f.1/",
        "http://[::1]/",
        "http://[fd00::1]/",
        "http://[fe80::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://100.64.0.1/",
        "http://localhost/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "ftp://files.test/x",
        "file:///etc/passwd",
    )

    def test_internal_addresses_are_refused_without_dns(self) -> None:
        with mock.patch.object(socket, "getaddrinfo", side_effect=AssertionError("no DNS")):
            for url in self.REFUSED:
                with self.subTest(url=url):
                    assert fetch.адрес_закрыт(url), url

    def test_negative_control_public_addresses_pass(self) -> None:
        for url in ("https://docs.vendor.test/x", "http://8.8.8.8/", "https://[2001:4860::8888]/"):
            with self.subTest(url=url):
                assert fetch.адрес_закрыт(url) == "", url

    def test_fetch_refuses_without_calling_the_transport_or_the_journal(self) -> None:
        with mock.patch.object(urllib.request, "urlopen") as transport:
            out = fetch.fetch("http://169.254.169.254/latest/meta-data/", why_wanted="x")
        assert transport.call_count == 0
        assert out["outcome"] == "fail"
        assert out["ssrf"] is True
        assert out["denied"] is False
        assert self.rows() == []

    def test_the_tool_refuses_too(self) -> None:
        with mock.patch.object(urllib.request, "urlopen") as transport:
            out = json.loads(S.fetch_url("http://127.0.0.1:9/"))
        assert transport.call_count == 0
        assert out["outcome"] == "fail"


class SSRFAtConnection(unittest.TestCase):
    def test_a_name_that_resolves_inside_is_refused_before_a_socket_opens(self) -> None:
        infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80))]
        with mock.patch.object(socket, "getaddrinfo", return_value=infos):
            with mock.patch.object(socket, "socket") as opened:
                with self.assertRaises(fetch.SSRFRefused):
                    fetch._guarded_create_connection(("rebind.test", 80), 5)
        assert opened.call_count == 0

    def test_negative_control_a_public_address_is_connected(self) -> None:
        infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))]
        with mock.patch.object(socket, "getaddrinfo", return_value=infos):
            with mock.patch.object(socket, "socket") as opened:
                got = fetch._guarded_create_connection(("public.test", 80), 5)
        opened.return_value.connect.assert_called_once_with(("93.184.216.34", 80))
        assert got is opened.return_value

    def test_a_redirect_into_the_inside_is_refused(self) -> None:
        handler = fetch._GuardedRedirect()
        request = urllib.request.Request("https://public.test/")
        with self.assertRaises(fetch.SSRFRefused):
            handler.redirect_request(request, None, 302, "Found", {}, "http://169.254.169.254/")
        with self.assertRaises(fetch.SSRFRefused):
            handler.redirect_request(request, None, 302, "Found", {}, "file:///etc/passwd")
        ok = handler.redirect_request(request, None, 302, "Found", {}, "https://other.test/")
        assert ok.full_url == "https://other.test/"

    def test_end_to_end_the_guarded_opener_never_reaches_a_loopback_server(self) -> None:
        """A real server on 127.0.0.1, a name that RESOLVES to it, no proxy.
        If the guard failed, the server would answer 200 and this would see it."""
        hits: list[str] = []

        class _H(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                hits.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"secret")

            def log_message(self, *a: object) -> None:
                return None

        srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
        port = srv.server_address[1]
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch.object(fetch, "_GUARDED_OPENER", None):
                with mock.patch.object(socket, "getaddrinfo", return_value=infos):
                    out = fetch.fetch(f"http://rebind.test:{port}/x")
        assert hits == [], "the request reached the loopback server"
        assert out["outcome"] == "fail" and out["ssrf"] is True, out["note"]


# --- item 4: text extraction and paging --------------------------------------

HTML = (
    b"<!doctype html><html><head><title>Kling  API</title><style>.a{}</style>"
    b"<script>var tracking=1</script></head><body><nav>Home | Pricing</nav>"
    b"<h2>Limits</h2><p>Max duration is <b>10</b> seconds.</p>"
    b"<ul><li>16:9</li><li>9:16</li></ul></body></html>"
)


class PageIsText(_TempJournal):
    def _page(
        self, body: bytes, content_type: str = "text/html; charset=utf-8", **kw: object
    ) -> dict:
        with mock.patch.object(
            urllib.request, "urlopen", return_value=_Response(body, content_type=content_type)
        ):
            return fetch.page("https://docs.vendor.test/x", **kw)  # type: ignore[arg-type]

    def test_markup_scripts_and_nav_are_gone(self) -> None:
        out = self._page(HTML)
        assert out["title"] == "Kling API"
        assert out["text"] == "## Limits\nMax duration is 10 seconds.\n- 16:9\n- 9:16"
        assert "tracking" not in out["text"] and "Pricing" not in out["text"]
        assert out["truncated"] is False and out["next_offset"] is None

    def test_paging_reports_what_is_left(self) -> None:
        first = self._page(HTML, max_chars=10)
        assert first["text"] == "## Limits\n"
        assert first["total_chars"] == 51
        assert first["remaining_chars"] == 41
        assert first["next_offset"] == 10
        assert first["truncated"] is True
        assert "offset=10" in first["note"]
        second = self._page(HTML, max_chars=10, offset=10)
        assert second["text"] == "Max durati"

    def test_raw_returns_the_markup(self) -> None:
        out = self._page(HTML, raw=True)
        assert out["text"].startswith("<!doctype html>")

    def test_json_is_not_extracted(self) -> None:
        out = self._page(b'{"a": "<b>x</b>"}', content_type="application/json")
        assert out["text"] == '{"a": "<b>x</b>"}'

    def test_the_cap_is_a_literal_and_enforced(self) -> None:
        assert fetch.PAGE_CHARS == 20_000
        assert fetch.PAGE_CHARS_MAX == 80_000
        out = self._page(b"x" * 100_000, content_type="text/plain", max_chars=10**9)
        assert out["returned_chars"] == 80_000

    def test_the_tool_defaults_to_the_page_size(self) -> None:
        with mock.patch.object(
            urllib.request,
            "urlopen",
            return_value=_Response(b"y" * 30_000, content_type="text/plain"),
        ):
            out = json.loads(S.fetch_url("https://docs.vendor.test/x"))
        assert out["returned_chars"] == 20_000 and out["next_offset"] == 20_000


# --- item 6: blocked_hosts ---------------------------------------------------


class BlockedHostsAsk(_TempJournal):
    def _write(self, *rows: dict) -> None:
        self.denied.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def test_an_open_row_never_stands_in_for_the_reason(self) -> None:
        """2026-10-14: `docs.qingque.cn` sat in `hosts` with state `open`."""
        self._write(
            {
                "host": "docs.q.test",
                "url": "https://docs.q.test/",
                "why_wanted": "read the API",
                "incidental": False,
                "state": "refused",
            },
            {"host": "docs.q.test", "url": "https://docs.q.test/d/1", "state": "open"},
            {
                "host": "docs.q.test",
                "url": "https://docs.q.test/",
                "why_wanted": "map refresh",
                "incidental": True,
                "state": "refused",
            },
        )
        out = fetch.wanted()
        assert [r["state"] for r in out["hosts"]] == ["refused"]
        assert out["hosts"][0]["why_wanted"] == "read the API"
        assert out["hosts"][0]["also_answered"] == ["https://docs.q.test/d/1"]

    def test_compact_is_the_tools_default_and_full_is_opt_in(self) -> None:
        self._write(
            {
                "host": "a.test",
                "why_wanted": "x" * 500,
                "incidental": False,
                "state": "refused",
                "first_seen": "2026-10-01",
            },
            {"host": "b.test", "why_wanted": "search hit", "incidental": True, "state": "refused"},
        )
        compact = json.loads(S.blocked_hosts())
        assert compact["counts"] == {"asked": 1, "also_refused": 1, "granted": 0, "withdrawn": 0}
        assert compact["also_refused"] == ["b.test"]
        assert len(compact["hosts"][0]["why_wanted"]) == 161
        full = json.loads(S.blocked_hosts(full=True))
        assert full["hosts"][0]["why_wanted"] == "x" * 500
        assert "counts" not in full


# --- item 3: probe ------------------------------------------------------------


class ProbeFalHostsAndPayload(unittest.TestCase):
    def test_fal_run_hosts_find_the_fal_key(self) -> None:
        with mock.patch.dict("os.environ", {"FAL_KEY": "k"}, clear=True):
            for host in ("queue.fal.run", "fal.run", "api.fal.ai", "some-model.fal.run"):
                with self.subTest(host=host):
                    assert probe._key_for(host) == ("k", "FAL_KEY")

    def test_negative_control_an_unrelated_host_has_no_key(self) -> None:
        with mock.patch.dict("os.environ", {"FAL_KEY": "k"}, clear=True):
            assert probe._key_for("notfal.run.test") == ("", "")

    def test_fal_gets_the_key_scheme_kling_gets_bearer(self) -> None:
        assert probe._auth_scheme("queue.fal.run") == "Key"
        assert probe._auth_scheme("api.fal.ai") == "Key"
        assert probe._auth_scheme("api.klingai.com") == "Bearer"

    def test_the_header_actually_sent_to_fal(self) -> None:
        seen: dict = {}

        def _capture(request, timeout=None):  # type: ignore[no-untyped-def]
            seen["auth"] = request.get_header("Authorization")
            raise urllib.error.HTTPError(request.full_url, 422, "x", {}, None)  # type: ignore[arg-type]

        with mock.patch.dict("os.environ", {"FAL_KEY": "k"}, clear=True):
            with mock.patch.object(urllib.request, "urlopen", side_effect=_capture):
                with mock.patch.object(probe, "note_probe"):
                    probe.probe_limit("https://queue.fal.run/fal-ai/x", "duration", 1_000_000)
        assert seen["auth"] == "Key k"

    def test_a_non_object_payload_is_a_clean_refusal(self) -> None:
        with mock.patch.object(urllib.request, "urlopen") as transport:
            for payload_json in ("[1]", "1", '"s"', "null"):
                with self.subTest(payload_json=payload_json):
                    out = json.loads(
                        S.probe_model_limit(
                            "https://queue.fal.run/x", "duration", "1000000", payload_json
                        )
                    )
                    assert out["outcome"] == "fail"
                    assert "JSON OBJECT" in out["note"]
            out = probe.probe_limit("https://queue.fal.run/x", "d", 1_000_000, payload=[1])  # type: ignore[arg-type]
            assert out["outcome"] == "fail"
        assert transport.call_count == 0

    def test_probe_refuses_internal_addresses(self) -> None:
        with mock.patch.dict("os.environ", {"FAL_KEY": "k"}, clear=True):
            with mock.patch.object(urllib.request, "urlopen") as transport:
                out = probe.probe_limit("https://169.254.169.254/x", "d", 1_000_000)
        assert out["outcome"] == "fail"
        assert transport.call_count == 0


# --- item 9: transport, lifespan, honest instructions ------------------------


class Transport(unittest.TestCase):
    def test_stdio_is_the_default(self) -> None:
        args = S.parse_args([])
        assert (args.transport, args.host, args.port) == ("stdio", "127.0.0.1", 8000)

    def test_http_flags_parse(self) -> None:
        args = S.parse_args(
            ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9100"]
        )
        assert (args.transport, args.host, args.port) == ("streamable-http", "0.0.0.0", 9100)

    def test_no_env_leaves_the_sdk_default(self) -> None:
        assert S.transport_security("127.0.0.1", {}) is None

    def test_env_hosts_are_added_and_protection_stays_on(self) -> None:
        got = S.transport_security(
            "127.0.0.1",
            {
                "STUDIO_ALLOWED_HOSTS": "studio.example.org, studio.example.org:443",
                "STUDIO_ALLOWED_ORIGINS": "https://studio.example.org",
            },
        )
        assert got.enable_dns_rebinding_protection is True
        assert "studio.example.org" in got.allowed_hosts
        assert "studio.example.org:443" in got.allowed_hosts
        assert "127.0.0.1:*" in got.allowed_hosts
        assert "https://studio.example.org" in got.allowed_origins

    def test_main_passes_transport_and_security(self) -> None:
        env = {"STUDIO_ALLOWED_HOSTS": "studio.example.org"}
        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch.object(S.server, "run") as run:
                S.main(["--transport", "streamable-http", "--port", "9100"])
        (transport,), kwargs = run.call_args
        assert transport == "streamable-http"
        assert kwargs["port"] == 9100 and kwargs["host"] == "127.0.0.1"
        assert "studio.example.org" in kwargs["transport_security"].allowed_hosts

    def test_main_stdio_calls_run_without_arguments(self) -> None:
        with mock.patch.object(S.server, "run") as run:
            S.main([])
        run.assert_called_once_with()


class IndexIsWarmedAtStartup(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(S, "_INDEX", None)
        patcher.start()
        self.addCleanup(patcher.stop)
        warming = mock.patch.object(S, "_WARMING", None)
        warming.start()
        self.addCleanup(warming.stop)

    def test_the_server_has_a_lifespan_that_warms(self) -> None:
        assert S.server.settings.lifespan is S._lifespan

        async def _run() -> None:
            async with S._lifespan(S.server):
                pass

        with mock.patch.object(S, "warm_index") as warm:
            asyncio.run(_run())
        warm.assert_called_once_with()

    def test_warming_builds_once_even_when_a_call_races_it(self) -> None:
        gate = threading.Event()
        calls: list[int] = []

        def _slow_build(**_kw: object) -> str:
            calls.append(1)
            gate.wait(5)
            return "INDEX"

        with mock.patch.object(S.knowledge, "build_index", side_effect=_slow_build):
            thread = S.warm_index({})
            assert thread is not None
            racer = threading.Thread(target=S._index)
            racer.start()
            gate.set()
            thread.join(5)
            racer.join(5)
            assert S._index() == "INDEX"
        assert calls == [1]

    def test_it_can_be_turned_off(self) -> None:
        with mock.patch.object(S.knowledge, "build_index") as build:
            assert S.warm_index({"STUDIO_MCP_WARM_INDEX": "0"}) is None
        assert build.call_count == 0


class InstructionsSayMeasuredNotFact(unittest.TestCase):
    def test_the_reachable_list_carries_a_date_and_a_vantage(self) -> None:
        text = S.server.instructions or ""
        assert "2026-08-27, from the development sandbox" in text
        assert "reachable_hosts" in text


# --- item 10: stale_model_facts params, guarded by signature -----------------


class StaleParamsAreGuarded(unittest.TestCase):
    def _old(self, *, days: int = 180, path: object = None) -> dict:
        return {"outcome": "pass", "note": "old", "days": days}

    def _new(
        self,
        *,
        days: int = 180,
        path: object = None,
        model: str | None = None,
        limit: int = 0,
        full: bool = False,
    ) -> dict:
        return {"outcome": "pass", "note": "new", "got": [days, model, limit, full]}

    def test_an_old_signature_gets_only_days_and_says_what_was_dropped(self) -> None:
        out = S.stale_call(30, model="veo-3.1", limit=5, full=True, stale_fn=self._old)
        assert out["days"] == 30
        assert out["ignored_params"] == ["full", "limit", "model"]
        assert "not applied" in out["note"]

    def test_a_new_signature_gets_everything(self) -> None:
        out = S.stale_call(30, model="veo-3.1", limit=5, full=True, stale_fn=self._new)
        assert out["got"] == [30, "veo-3.1", 5, True]
        assert "ignored_params" not in out

    def test_limit_becomes_top_when_that_is_the_name_advice_chose(self) -> None:
        def _top(
            *,
            days: int = 180,
            path: object = None,
            model: str = "",
            full: bool = False,
            top: int = 20,
        ) -> dict:
            return {"outcome": "pass", "note": "top", "got": [model, top, full]}

        out = S.stale_call(30, model="veo-3.1", limit=3, stale_fn=_top)
        assert out["got"] == ["veo-3.1", 3, False]
        assert "ignored_params" not in out

    def test_defaults_pass_nothing_extra(self) -> None:
        out = S.stale_call(stale_fn=self._new)
        assert out["got"] == [S.STALE_AFTER_DAYS, None, 0, False]

    def test_bad_days_is_fail_not_an_empty_list(self) -> None:
        for bad in (-1, "soon", True):
            with self.subTest(bad=bad):
                out = S.stale_call(bad, stale_fn=self._new)
                assert out["outcome"] == "fail"


if __name__ == "__main__":
    unittest.main()
