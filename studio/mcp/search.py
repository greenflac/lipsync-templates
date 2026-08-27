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

Two Google endpoints answer, and both want a key rather than an allowlist
change — which is the whole difference between "blocked" and "not set up".

    generativelanguage.googleapis.com   Gemini, with its `google_search` tool
    customsearch.googleapis.com         Programmable Search JSON API

GEMINI IS THE RECOMMENDATION, AND NOT MERELY THE ALTERNATIVE

Programmable Search used to have a "Search the entire web" switch, and this
module recommended it. That advice was wrong by the time it was written:
Google withdrew the switch for NEW engines in **March 2026**, so an engine
created today is restricted to at most 50 named domains, and engines still on
the full index must migrate by 2027-01-01.

A 50-domain list is not merely tedious to maintain, it is wrong for this job
in a specific way already measured here: `cloud.google.com` is reachable and
`docs.cloud.google.com` is not. Vendors move their documentation between
subdomains, and a curated list quietly stops covering them without ever
saying so. Gemini grounding searches the whole index with one key and nothing
to curate.

Programmable Search stays as the fallback, because a key somebody already has
beats a key they must go and create.

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

__all__ = [
    "search",
    "ENDPOINT",
    "GEMINI_ENDPOINT",
    "KEY_ENV",
    "CSE_ENV",
    "GEMINI_KEY_ENV",
    "SETUP",
]

ENDPOINT = "https://customsearch.googleapis.com/customsearch/v1"

#: Gemini with its `google_search` tool. MEASURED reachable 2026-08-27, and it
#: answers 403 "callers without established identity" rather than a tunnel
#: refusal, which means it wants a key rather than a policy change.
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

#: CHOSEN: the cheapest current Gemini that carries the search tool.
GEMINI_MODEL = "gemini-2.5-flash"

#: Environment variables searched for credentials, in order. Never arguments:
#: a key passed as a parameter lands in a call log and a traceback.
KEY_ENV: tuple[str, ...] = ("GOOGLE_SEARCH_KEY", "GOOGLE_CSE_KEY")
CSE_ENV: tuple[str, ...] = ("GOOGLE_CSE_ID", "GOOGLE_SEARCH_CX", "GOOGLE_CX")
GEMINI_KEY_ENV: tuple[str, ...] = (
    "GEMINI_API_KEY",
    "GOOGLE_GENAI_API_KEY",
    "GOOGLE_API_KEY",
)

#: CHOSEN: the Custom Search API's own page size maximum is 10, and asking for
#: fewer wastes a query off a 100-per-day free tier without saving anything.
MAX_RESULTS = 10

SETUP = (
    "Two ways to turn search on. Prefer the first.\n"
    "\n"
    "A. GEMINI GROUNDING — one key, no domain list, no 50-site cap.\n"
    "   aistudio.google.com → create an API key → GEMINI_API_KEY.\n"
    "   This is general Google search: nothing to curate and nothing to\n"
    "   re-add when a vendor moves to a new subdomain.\n"
    "\n"
    "B. PROGRAMMABLE SEARCH — two values, and a list you must maintain.\n"
    "   1. console.cloud.google.com → enable 'Custom Search API' → an API key\n"
    "      → GOOGLE_SEARCH_KEY\n"
    "   2. programmablesearchengine.google.com → create an engine → the\n"
    "      'Search engine ID' (cx) → GOOGLE_CSE_ID\n"
    "   NOTE: 'Search the entire web' was withdrawn for NEW engines in March\n"
    "   2026, so a new engine is restricted to at most 50 named domains, and\n"
    "   engines still using the full index must migrate by 2027-01-01.\n"
    "   That is why A is the recommendation and not merely the alternative."
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


def _gemini(text: str, site: str, count: int) -> dict:
    """General Google search via Gemini's `google_search` tool.

    No domain list and no 50-site cap: this is the whole index, which is what
    Programmable Search stopped offering to new engines in March 2026.

    UNVERIFIED against a live response — no key has been available on this
    machine, so the parsing below follows the documented `groundingMetadata`
    shape and is written to survive a shape it does not recognise rather than
    to assume one. The first real call is the test, and it is the owner's to
    run.

    One documented wrinkle worth knowing before it surprises somebody: the URLs
    in `groundingChunks` are Google redirect links, not the publisher's own
    address. The publisher shows up in `web.title`, so that is what the host
    is taken from, and the redirect is kept as the URL because following it
    would be a second request per result.
    """
    key, key_from = _first_env(GEMINI_KEY_ENV)
    query = f"site:{site} {text}" if site else text
    body = {
        "contents": [{"parts": [{"text": query}]}],
        "tools": [{"google_search": {}}],
    }
    url = GEMINI_ENDPOINT.format(model=GEMINI_MODEL)
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read(800_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as error:
        raw = error.read(4_000).decode("utf-8", "replace")
        message = raw
        try:
            message = json.loads(raw).get("error", {}).get("message", raw)
        except ValueError:
            pass
        return _empty(
            FAIL,
            f"the Gemini API answered {error.code}: {message}\n\n"
            f"The key came from {key_from}.\n\n" + SETUP,
        )
    except urllib.error.URLError as error:
        reason = str(getattr(error, "reason", error))
        if _DENIAL.search(reason):
            note_denial(url, reason, f"web search for: {text}")
            return _empty(
                UNMEASURED,
                f"the Gemini endpoint is refused by this organisation's egress "
                f"policy ({reason}). Recorded for the allowlist request.",
            )
        return _empty(UNMEASURED, f"the Gemini endpoint could not be reached: {reason}")
    except Exception as error:  # noqa: BLE001
        return _empty(UNMEASURED, f"search failed unexpectedly: {type(error).__name__}: {error}")

    candidates = payload.get("candidates") or []
    meta = (candidates[0] if candidates else {}).get("groundingMetadata") or {}
    chunks = meta.get("groundingChunks") or []

    results = []
    for chunk in chunks[:count]:
        web = chunk.get("web") or {}
        title = str(web.get("title", ""))
        results.append(
            {
                "title": title,
                "url": str(web.get("uri", "")),
                # `title` is the publisher domain in this API, not a headline.
                "host": title.lower() if "." in title else "",
                "snippet": "",
                "fetchable": None,
            }
        )

    answer = ""
    parts = (candidates[0] if candidates else {}).get("content", {}).get("parts") or []
    for part in parts:
        answer += str(part.get("text", ""))

    if not results and not answer.strip():
        return _empty(
            UNMEASURED,
            "Gemini answered but grounded nothing: no sources and no text. "
            "Nothing was checked, which is not the same as nothing existing.",
        )

    return {
        "outcome": PASS,
        "checked": len(results),
        "violations": 0,
        "unmeasured": 1 if not results else 0,
        "note": (
            f"{len(results)} grounded source(s) via Gemini search. URLs are Google "
            "redirect links and the publisher is in the title. "
            + (
                "The answer text carries the substance; no source list came back. "
                if not results
                else ""
            )
            + f"Searches Gemini ran: {meta.get('webSearchQueries') or 'not reported'}."
        ),
        "results": results,
        "answer": answer.strip(),
        "query": query,
        "backend": "gemini",
    }


def search(query: str, *, count: int = 8, site: str = "", check_fetchable: bool = True) -> dict:
    """Search the web and say, per result, whether the page can also be read.

    Two backends. Gemini grounding is used when its key is set, because it
    searches the whole index; Programmable Search is the fallback and is
    capped at 50 curated domains since Google withdrew "search the entire web"
    from new engines in March 2026.

    :param site: restrict to one domain, e.g. "kling.ai". Useful even for a
        blocked host: the snippets still come back.
    :param check_fetchable: probe each distinct host. Costs one request per
        host; turn it off when only the snippets are wanted.

    :returns: the house judging dict plus `results` — title, url, snippet,
        host, and `fetchable` — and `backend`, so a reader can tell which one
        answered.

    Three outcomes. No credentials is `could not measure`, not `fail`: nothing
    was searched, and that is different from searching and finding nothing.
    Zero hits for a real query is also `could not measure`, because zero
    checks is never a pass.
    """
    text = str(query or "").strip()
    if not text:
        return _empty(UNMEASURED, "no query was given, so nothing was searched")

    gemini_key, _ = _first_env(GEMINI_KEY_ENV)
    if gemini_key:
        out = _gemini(text, site, max(1, int(count)))
        if check_fetchable and out.get("results"):
            seen: dict[str, bool | None] = {}
            for row in out["results"]:
                host = row["host"]
                if host and host not in seen:
                    seen[host] = _fetchable(host)
                row["fetchable"] = seen.get(host)
            out["unmeasured"] = sum(1 for r in out["results"] if r["fetchable"] is False)
        return out

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
            "search is not configured. The Programmable Search route is missing "
            + " and ".join(missing)
            + ", and no Gemini key was found either (looked at "
            + ", ".join(GEMINI_KEY_ENV)
            + ").\n\n"
            + SETUP,
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
        "backend": "programmable-search",
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
        "backend": "",
    }
