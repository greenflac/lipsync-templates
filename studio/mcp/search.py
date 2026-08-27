"""Search the web from inside the server, within the egress policy.

WHY THIS EXISTS

The owner asked the obvious question: every other assistant has a built-in
search, so what is the problem here. The answer turned out to be nothing —
the problem was that nobody had looked for a backend that this session is
allowed to reach.

MEASURED 2026-08-27, probing 19 search endpoints:

    open    customsearch.googleapis.com   www.googleapis.com
    closed  api.search.brave.com  api.tavily.com  api.exa.ai  serpapi.com
            google.serper.dev  duckduckgo.com (and html/lite/api)
            api.bing.microsoft.com  searx.be  api.perplexity.ai
            api.you.com  api.openalex.org  api.semanticscholar.org
            api.crossref.org

`api.github.com` answers, but its search paths do not: this session is bound
to its configured repositories and returns 403 with
"Use repository-scoped endpoints" for any search query. So GitHub is a fetch
channel, not a search one.

One backend is open, and one is enough. Google's Programmable Search JSON API
returns a proper API error rather than a tunnel refusal, which is the whole
difference: it wants a key, not an allowlist change.

WHAT SEARCH BUYS WHEN HALF THE WEB IS STILL BLOCKED

Two separate things, and confusing them is how this gets over-promised:

1. A result CARRIES information — title, snippet, the site that published it,
   often a date. That is a citable source on its own, and it is exactly the
   material this base has been recording as `blog` tier all along.
2. A result POINTS at a page, and whether that page can be read in full is a
   different question with a different answer per host. So every result comes
   back tagged `fetchable`, decided by trying the host rather than by
   guessing, and the caller can see at a glance which ones `fetch_url` will
   actually open.

Searching does not widen the egress policy and this module does not pretend
otherwise. It finds the door; `fetch_url` says whether it opens.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio.mcp.fetch import TIMEOUT_SECONDS, _DENIAL, note_denial

__all__ = ["search", "ENDPOINT", "KEY_ENV", "CSE_ENV", "SETUP"]

ENDPOINT = "https://customsearch.googleapis.com/customsearch/v1"

#: Environment variables searched for credentials, in order. Never arguments:
#: a key passed as a parameter lands in a call log and a traceback.
KEY_ENV: tuple[str, ...] = ("GOOGLE_SEARCH_KEY", "GOOGLE_API_KEY", "GOOGLE_CSE_KEY")
CSE_ENV: tuple[str, ...] = ("GOOGLE_CSE_ID", "GOOGLE_SEARCH_CX", "GOOGLE_CX")

#: CHOSEN: the API's own page size maximum is 10, and asking for fewer wastes
#: a query off a 100-per-day free tier without saving anything.
MAX_RESULTS = 10

SETUP = (
    "Two values are needed, both free:\n"
    "  1. an API key — console.cloud.google.com, enable 'Custom Search API', "
    "create an API key, put it in GOOGLE_SEARCH_KEY\n"
    "  2. a search engine id — programmablesearchengine.google.com, create an "
    "engine, turn ON 'Search the entire web', copy the 'Search engine ID' (cx) "
    "into GOOGLE_CSE_ID\n"
    "The free tier is 100 queries a day; past that the API charges."
)


def _first_env(names: tuple[str, ...]) -> tuple[str, str]:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value, name
    return "", ""


def _fetchable(host: str) -> bool | None:
    """Can this host be opened at all? None when the check itself failed.

    Decided by asking, not by consulting a list that goes stale.
    """
    from studio.mcp.fetch import fetch as _fetch

    out = _fetch(f"https://{host}/", why_wanted="checking whether a search hit is readable")
    if out["denied"]:
        return False
    if out["outcome"] in {PASS, FAIL}:
        # FAIL here means the host answered with an HTTP status, which is
        # still proof it is reachable.
        return True
    return None


def search(query: str, *, count: int = 8, site: str = "", check_fetchable: bool = True) -> dict:
    """Search the web and say, per result, whether the page can also be read.

    :param site: restrict to one domain, e.g. "kling.ai". Useful even for a
        blocked host: the snippets still come back.
    :param check_fetchable: probe each distinct host. Costs one request per
        host; turn it off when only the snippets are wanted.

    :returns: the house judging dict plus `results` — title, url, snippet,
        host, and `fetchable`.

    Three outcomes. No credentials is `could not measure`, not `fail`: nothing
    was searched, and that is different from searching and finding nothing.
    Zero hits for a real query is also `could not measure`, because zero
    checks is never a pass.
    """
    text = str(query or "").strip()
    if not text:
        return _empty(UNMEASURED, "no query was given, so nothing was searched")

    key, key_from = _first_env(KEY_ENV)
    cse, cse_from = _first_env(CSE_ENV)
    if not key or not cse:
        missing = []
        if not key:
            missing.append(f"an API key (looked at {', '.join(KEY_ENV)})")
        if not cse:
            missing.append(f"a search engine id (looked at {', '.join(CSE_ENV)})")
        return _empty(
            UNMEASURED,
            "search is not configured: " + " and ".join(missing) + ".\n\n" + SETUP,
        )

    params = {
        "key": key,
        "cx": cse,
        "q": f"site:{site} {text}" if site else text,
        "num": str(max(1, min(int(count), MAX_RESULTS))),
    }
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"

    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read(400_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        body = error.read(4_000).decode("utf-8", "replace")
        message = body
        try:
            message = json.loads(body).get("error", {}).get("message", body)
        except ValueError:
            pass
        hint = ""
        if error.code in (400, 403):
            hint = (
                f"\n\nThe credentials came from {key_from} and {cse_from}. "
                "A 400 usually means the search engine id is wrong; a 403 "
                "usually means the key is not enabled for the Custom Search "
                "API, or the daily free quota is spent.\n\n" + SETUP
            )
        return _empty(FAIL, f"the search API answered {error.code}: {message}{hint}")
    except urllib.error.URLError as error:
        reason = str(getattr(error, "reason", error))
        if _DENIAL.search(reason):
            note_denial(ENDPOINT, reason, f"web search for: {text}")
            return _empty(
                UNMEASURED,
                f"the search backend is refused by this organisation's egress "
                f"policy ({reason}). Recorded for the allowlist request.",
            )
        return _empty(UNMEASURED, f"the search backend could not be reached: {reason}")
    except Exception as error:  # noqa: BLE001 - a search must not take the chat down
        return _empty(UNMEASURED, f"search failed unexpectedly: {type(error).__name__}: {error}")

    items = payload.get("items") or []
    if not items:
        total = payload.get("searchInformation", {}).get("totalResults", "0")
        return _empty(
            UNMEASURED,
            f"the search ran and returned nothing (totalResults {total}). "
            "Nothing was checked, which is not the same as nothing existing.",
        )

    results = []
    verdicts: dict[str, bool | None] = {}
    for item in items:
        link = str(item.get("link", ""))
        host = str(item.get("displayLink", "")).lower()
        if check_fetchable and host and host not in verdicts:
            verdicts[host] = _fetchable(host)
        results.append(
            {
                "title": str(item.get("title", "")),
                "url": link,
                "host": host,
                "snippet": " ".join(str(item.get("snippet", "")).split()),
                "fetchable": verdicts.get(host) if check_fetchable else None,
            }
        )

    readable = sum(1 for r in results if r["fetchable"] is True)
    blocked = sum(1 for r in results if r["fetchable"] is False)
    return {
        "outcome": PASS,
        "checked": len(results),
        "violations": 0,
        "unmeasured": blocked,
        "note": (
            f"{len(results)} result(s); {readable} on hosts this session can open, "
            f"{blocked} on hosts the policy refuses. A refused host still gives you "
            "its snippet and its URL to cite — it just cannot be read in full."
        ),
        "results": results,
        "query": params["q"],
    }


def _empty(outcome: str, note: str) -> dict:
    return {
        "outcome": outcome,
        "checked": 0,
        "violations": 1 if outcome == FAIL else 0,
        "unmeasured": 0 if outcome == FAIL else 1,
        "note": note,
        "results": [],
        "query": "",
    }
