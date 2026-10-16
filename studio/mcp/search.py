"""Search the web from inside the server, within the egress policy.

WHY THIS EXISTS

The owner asked the obvious question: every other assistant has a built-in
search, so what is the problem here. The answer turned out to be nothing —
the problem was that nobody had looked for a backend that this session is
allowed to reach.

MEASURED 2026-08-27, probing 19 search endpoints (and RE-MEASURED 2026-10-14
for the four commercial ones, see below):

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

2026-10-14: SEVERAL BACKENDS, TRIED IN ORDER, AND A FALLBACK THAT IS THE CALLER

A live run found the single-backend design failing in the dullest way: the
Gemini prepayment ran out, the API answered 402, and the tool reported `fail`
with "create an API key" — beside a working key, with a second search key
(`SERPER_KEY`) sitting unused in the environment. Re-measured the same day
with `fetch.reachability` (rows in `denied_hosts.jsonl`):

    open    google.serper.dev (answers 403 to a bare GET: wants a key)
            generativelanguage.googleapis.com  customsearch.googleapis.com
    closed  api.search.brave.com  api.tavily.com  api.exa.ai  (tunnel 403)

So the 2026-08-27 line above that lists `google.serper.dev` as closed is no
longer true; the policy changed under it. Backends now run in this order,
each only when its key is set, and the next is tried when one cannot answer:

    gemini → serper → programmable-search → brave → tavily → exa → yandex

(yandex added 2026-10-14, opt-in only — see `YANDEX_ENDPOINT`.) A billing or
quota refusal is remembered in the process for `NOT_SERVED_TTL_SECONDS`, and
the backend is skipped — said so in `attempts` — instead of being asked again.

Quota, billing and permission refusals (402, 429, 403, Tavily's 432/433, and
"not enough credits" in any body) are `could not measure` with the real
reason — the key exists, the account cannot pay — never "create a key". And
when no backend can answer, the result carries `client_side`: ready-to-run
queries for the calling agent's OWN web search tool, with the instruction to
record what it finds through `record_model_fact`. Search is not the server's
monopoly; refusing to help because our own backends are down would be.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Callable

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio.mcp import credentials
from studio.mcp.fetch import NO_JOURNAL_ENV, TIMEOUT_SECONDS, _DENIAL, note_denial

__all__ = [
    "search",
    "BACKENDS",
    "ENDPOINT",
    "GEMINI_ENDPOINT",
    "SERPER_ENDPOINT",
    "BRAVE_ENDPOINT",
    "TAVILY_ENDPOINT",
    "EXA_ENDPOINT",
    "KEY_ENV",
    "CSE_ENV",
    "GEMINI_KEY_ENV",
    "GEMINI_MODEL_ENV",
    "SERPER_KEY_ENV",
    "BRAVE_KEY_ENV",
    "TAVILY_KEY_ENV",
    "EXA_KEY_ENV",
    "YANDEX_ENDPOINT",
    "YANDEX_KEY_ENV",
    "YANDEX_FOLDER_ENV",
    "YANDEX_OPT_IN_ENV",
    "NOT_SERVED_TTL_SECONDS",
    "forget_refusals",
    "SETUP",
    "client_side",
    "gemini_model",
]

ENDPOINT = "https://customsearch.googleapis.com/customsearch/v1"

#: Gemini with its `google_search` tool. MEASURED reachable 2026-08-27, and it
#: answers 403 "callers without established identity" rather than a tunnel
#: refusal, which means it wants a key rather than a policy change.
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

#: Serper's Google results API. MEASURED reachable 2026-10-14 (403 to a bare
#: GET — the host answers and wants a key).
SERPER_ENDPOINT = "https://google.serper.dev/search"
#: MEASURED REFUSED by this sandbox's egress policy 2026-10-14. Kept, because
#: the server is also run elsewhere, and a refusal is recorded, not hidden.
BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
TAVILY_ENDPOINT = "https://api.tavily.com/search"
EXA_ENDPOINT = "https://api.exa.ai/search"

#: Yandex Search API v2, synchronous web search. MEASURED open from the
#: development sandbox 2026-08-27 (an unauthenticated POST answered 400
#: "query.search_type: Field is required", i.e. a schema hint, not a tunnel
#: refusal). The request shape below is READ from the vendor's own API
#: definition, 2026-10-14: `yandex/cloud/searchapi/v2/search_service.proto`
#: and `search_query.proto` in github.com/yandex-cloud/cloudapi (fetched
#: through raw.githubusercontent.com) — `WebSearchService.Search` is
#: `POST /v2/web/search`, body `WebSearchRequest{query: SearchQuery{
#: search_type (required), query_text (<=400, required), page}, group_spec,
#: max_passages (1-5), l10n, folder_id, response_format}`, answer
#: `WebSearchResponse{raw_data: bytes}` — XML by default. The proto's JSON
#: mapping is camelCase and `bytes` travel as base64. NEVER CALLED LIVE: the
#: key belongs to the owner's Yandex Direct work and the price per request is
#: unverified, so the backend is LAST in the chain and OFF unless
#: `STUDIO_SEARCH_ALLOW_YANDEX=1`.
YANDEX_ENDPOINT = "https://searchapi.api.cloud.yandex.net/v2/web/search"
YANDEX_KEY_ENV: tuple[str, ...] = ("YANDEX_SEARCH_API_KEY",)
YANDEX_FOLDER_ENV: tuple[str, ...] = ("YANDEX_FOLDER_ID",)
#: Opt-in, not opt-out: a key being present is NOT consent to spend it.
YANDEX_OPT_IN_ENV = "STUDIO_SEARCH_ALLOW_YANDEX"
#: The proto's own limit on `query_text` (`(length) = "<=400"`).
YANDEX_QUERY_MAX = 400

#: CHOSEN: the cheapest current Gemini that carries the search tool. Only the
#: DEFAULT: `GEMINI_SEARCH_MODEL` overrides it, because a model name is exactly
#: the kind of constant that goes stale between releases of this code.
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_MODEL_ENV: tuple[str, ...] = ("GEMINI_SEARCH_MODEL",)

#: Environment variables searched for credentials, in order. Never arguments:
#: a key passed as a parameter lands in a call log and a traceback.
KEY_ENV: tuple[str, ...] = ("GOOGLE_SEARCH_KEY", "GOOGLE_CSE_KEY")
CSE_ENV: tuple[str, ...] = ("GOOGLE_CSE_ID", "GOOGLE_SEARCH_CX", "GOOGLE_CX")
GEMINI_KEY_ENV: tuple[str, ...] = (
    "GEMINI_API_KEY",
    "GOOGLE_GENAI_API_KEY",
    "GOOGLE_API_KEY",
)
#: `SERPER_KEY` is what THIS environment sets (measured 2026-10-14); the
#: vendor's own docs say `SERPER_API_KEY`. Both, for the reason in
#: `credentials.py`.
SERPER_KEY_ENV: tuple[str, ...] = ("SERPER_API_KEY", "SERPER_KEY")
BRAVE_KEY_ENV: tuple[str, ...] = ("BRAVE_SEARCH_API_KEY", "BRAVE_API_KEY")
TAVILY_KEY_ENV: tuple[str, ...] = ("TAVILY_API_KEY",)
EXA_KEY_ENV: tuple[str, ...] = ("EXA_API_KEY",)

#: CHOSEN: the Custom Search API's own page size maximum is 10, and asking for
#: fewer wastes a query off a 100-per-day free tier without saving anything.
MAX_RESULTS = 10
#: CHOSEN for the other backends: Brave and Tavily cap a page at 20, and more
#: than 20 results is more than anybody reads before refining the query.
MAX_RESULTS_OTHER = 20

#: HTTP statuses that mean "the key exists, the ACCOUNT cannot be served right
#: now" — billing, quota, permission. `could not measure`, never `fail`:
#: nothing was searched, and no new key would change that. 432/433 are
#: Tavily's own plan-limit codes.
NOT_SERVED_STATUSES: frozenset[int] = frozenset({402, 403, 429, 432, 433})

#: Words in an error body that mean the same thing under a generic 400 —
#: Serper answers "Not enough credits" with HTTP 400.
_NOT_SERVED_WORDS = (
    "credit",
    "billing",
    "prepay",
    "payment",
    "quota",
    "insufficient",
    "balance",
    "exceeded",
    "rate limit",
    "depleted",
)

#: КАК ДОЛГО ПОМНИТЬ ОТКАЗ АККАУНТА. НАЙДЕНО валидатором 2026-10-14 (G15):
#: Gemini отвечал 402 на КАЖДЫЙ вызов — сервер каждый раз платил запросом и
#: временем, чтобы узнать то же самое. Отказ по оплате или квоте не проходит
#: за секунды. ВЫБРАНО: один час — квота у этих API считается в окнах от
#: минуты до суток, а пополнение счёта делает человек; час не держит здоровый
#: бэкенд выключенным надолго и не стучится в мёртвый на каждом вызове.
#: Помнится в ПРОЦЕССЕ (не на диске) и по отпечатку ключа: новый ключ —
#: новая попытка.
NOT_SERVED_TTL_SECONDS = 3600.0

#: Отказы, которые помнятся: оплата и квота. Права (`permission`) — нет:
#: включить API для ключа можно за минуту, и ждать час после этого незачем.
CACHED_REFUSALS: frozenset[str] = frozenset({"billing", "quota"})

#: (бэкенд, отпечаток ключа) -> (до какого момента, вид отказа, его нота).
_NOT_SERVED: dict[tuple[str, str], tuple[float, str, str]] = {}

#: Часы — отдельным именем, чтобы тест мог их подменить.
_now = time.monotonic


def forget_refusals() -> None:
    """Забыть все запомненные отказы аккаунтов (тесты; новая сессия владельца)."""
    _NOT_SERVED.clear()


SETUP = (
    "Ways to turn search on, tried in this order; one is enough.\n"
    "\n"
    "A. GEMINI GROUNDING — one key, no domain list, no 50-site cap.\n"
    "   aistudio.google.com → create an API key → GEMINI_API_KEY.\n"
    "   The model is GEMINI_SEARCH_MODEL (default gemini-2.5-flash).\n"
    "   This is general Google search: nothing to curate and nothing to\n"
    "   re-add when a vendor moves to a new subdomain.\n"
    "\n"
    "B. SERPER — Google results, one key: serper.dev → SERPER_API_KEY\n"
    "   (SERPER_KEY is read too). Paid per query after the free credits.\n"
    "\n"
    "C. PROGRAMMABLE SEARCH — two values, and a list you must maintain.\n"
    "   1. console.cloud.google.com → enable 'Custom Search API' → an API key\n"
    "      → GOOGLE_SEARCH_KEY\n"
    "   2. programmablesearchengine.google.com → create an engine → the\n"
    "      'Search engine ID' (cx) → GOOGLE_CSE_ID\n"
    "   NOTE: 'Search the entire web' was withdrawn for NEW engines in March\n"
    "   2026, so a new engine is restricted to at most 50 named domains, and\n"
    "   engines still using the full index must migrate by 2027-01-01.\n"
    "   That is why GEMINI GROUNDING leads and this is a fallback.\n"
    "\n"
    "D. BRAVE (BRAVE_SEARCH_API_KEY), TAVILY (TAVILY_API_KEY), EXA (EXA_API_KEY).\n"
    "   Their hosts were REFUSED by this sandbox's egress policy on 2026-10-14;\n"
    "   elsewhere they work as further fallbacks.\n"
    "\n"
    "E. YANDEX SEARCH API — LAST, and OFF unless STUDIO_SEARCH_ALLOW_YANDEX=1.\n"
    "   Needs YANDEX_SEARCH_API_KEY and YANDEX_FOLDER_ID. Price per request\n"
    "   unverified; the key may belong to other paid work — opt in knowingly."
)


#: Credential lookup lives in one module for the whole package; see
#: `credentials.find` for why it is not `os.environ.get`.
_first_env = credentials.find


def gemini_model() -> str:
    """The Gemini model used for grounding: `GEMINI_SEARCH_MODEL`, else the default."""
    name, _ = _first_env(GEMINI_MODEL_ENV)
    return name or GEMINI_MODEL


def _fetchable(host: str) -> bool | None:
    """Can this host be opened at all? None when the check itself failed.

    Decided by asking, not by consulting a list that goes stale.
    """
    from studio.mcp.fetch import fetch as _fetch

    # incidental: nobody asked for this host, it merely turned up in a result
    # list. Its refusal is recorded but stays out of the allowlist request.
    out = _fetch(
        f"https://{host}/",
        why_wanted="checking whether a search hit is readable",
        incidental=True,
    )
    if out["denied"]:
        return False
    if out["outcome"] in {PASS, FAIL}:
        # FAIL here means the host answered with an HTTP status, which is
        # still proof it is reachable.
        return True
    return None


def _host_of(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def _error_message(raw: str) -> str:
    """The human sentence inside a JSON error body, or the body itself."""
    try:
        parsed = json.loads(raw)
    except ValueError:
        return raw.strip()
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        for field in ("message", "detail", "error"):
            if isinstance(parsed.get(field), str) and parsed[field]:
                return str(parsed[field])
            if isinstance(parsed.get(field), dict):
                inner = parsed[field]
                if inner.get("error") or inner.get("message"):
                    return str(inner.get("error") or inner.get("message"))
    return raw.strip()


def _http_failure(backend: str, code: int, message: str, key_from: str, setup_hint: str) -> dict:
    """Classify an HTTP refusal from a search backend into one of the three outcomes.

    THE DEFECT, found by a live run 2026-10-14: Gemini answered 402 (the
    prepayment was depleted) and the tool printed `fail` with the SETUP text
    "create an API key" — beside a key that existed and was accepted. A
    billing or quota refusal is the ACCOUNT, not the key and not the query.
    """
    words = str(message or "").lower()
    if code in NOT_SERVED_STATUSES or any(w in words for w in _NOT_SERVED_WORDS):
        refusal = "permission"
        if code == 402 or any(
            w in words
            for w in (
                "credit",
                "billing",
                "prepay",
                "payment",
                "balance",
                "depleted",
                "insufficient",
            )
        ):
            kind = "BILLING: the account behind this key has no credit or prepayment left"
            refusal = "billing"
        elif code in (429, 432, 433) or any(
            w in words for w in ("quota", "rate limit", "exceeded")
        ):
            kind = "QUOTA: the account's rate or plan limit is spent for now"
            refusal = "quota"
        else:
            kind = (
                "PERMISSION: the key was refused for this API — not enabled for it, "
                "restricted by referrer/IP, or the project's quota is off"
            )
        out = _empty(
            UNMEASURED,
            f"{backend} answered {code}: {message}. {kind}. The key (from {key_from}) "
            "EXISTS — creating another one will not help; top up, wait for the "
            "quota window, or enable the API for this key. Nothing was searched.",
        )
        out["refusal"] = refusal
        return out
    if 500 <= code < 600:
        return _empty(
            UNMEASURED,
            f"{backend} answered {code}: {message}. The backend is unwell; "
            "nothing was searched. Worth retrying later.",
        )
    return _empty(
        FAIL,
        f"{backend} answered {code}: {message}\n\nThe key came from {key_from}."
        + (f"\n\n{setup_hint}" if setup_hint else ""),
    )


def _call(
    backend: str,
    request: urllib.request.Request,
    *,
    endpoint: str,
    key_from: str,
    setup_hint: str = "",
    cap: int = 800_000,
) -> tuple[Any, dict | None]:
    """(payload, None) when the backend answered 2xx with JSON; (None, result) otherwise."""
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read(cap).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        try:
            body = error.read(4_000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - a body we cannot read is not a new failure
            body = ""
        return None, _http_failure(
            backend, int(error.code), _error_message(body), key_from, setup_hint
        )
    except urllib.error.URLError as error:
        reason = str(getattr(error, "reason", error))
        if _DENIAL.search(reason):
            # ТЕКСТ ЗАПРОСА СЮДА НЕ ПОПАДАЕТ. Его печатает заказчик, а строка
            # уезжает в отслеживаемый git-ом файл. Для заявки на открытие ХОСТА
            # запрос ничего не добавляет: специфичность даёт сам адрес.
            записано = note_denial(endpoint, reason, f"web search backend {backend} refused")
            return None, _empty(
                UNMEASURED,
                f"the {backend} endpoint is refused by this organisation's egress "
                f"policy ({reason}). "
                + (
                    f"NOT recorded: the denial journal is off ({NO_JOURNAL_ENV})."
                    if записано.get("journal") == "off"
                    else "Recorded for the allowlist request."
                ),
            )
        return None, _empty(UNMEASURED, f"the {backend} endpoint could not be reached: {reason}")
    except Exception as error:  # noqa: BLE001 - a search must not take the chat down
        return None, _empty(
            UNMEASURED, f"{backend} search failed unexpectedly: {type(error).__name__}: {error}"
        )
    try:
        return json.loads(raw), None
    except ValueError:
        return None, _empty(
            UNMEASURED, f"{backend} answered something that is not JSON ({len(raw)} chars)"
        )


def _gemini(text: str, site: str, count: int) -> dict:
    """General Google search via Gemini's `google_search` tool.

    No domain list and no 50-site cap: this is the whole index, which is what
    Programmable Search stopped offering to new engines in March 2026.

    MEASURED 2026-08-27 against a live response, which is what this paragraph
    used to say was missing. `search("Kling 3.0 max duration seconds API")`
    returned `pass` on `gemini` with 7 grounded sources and an answer body;
    the documented shape held exactly — `candidates[0].groundingMetadata`
    carrying `groundingChunks[].web.{uri,title}` and `webSearchQueries`. The
    parsing needed no change. The `title` really is the publisher domain
    (atlascloud.ai, magnific.com, kie.ai, evolink.ai, wavespeed.ai) and the
    `uri` really is a `vertexaisearch.cloud.google.com` redirect.

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
    url = GEMINI_ENDPOINT.format(model=urllib.parse.quote(gemini_model(), safe="-._"))
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    payload, failed = _call(
        "the Gemini API", request, endpoint=url, key_from=key_from, setup_hint=SETUP
    )
    if failed is not None:
        return failed

    candidates = payload.get("candidates") or [] if isinstance(payload, dict) else []
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

    # НОЛЬ ИСТОЧНИКОВ — ЭТО НЕ «ГОДНО», ДАЖЕ КОГДА ТЕКСТ ЕСТЬ.
    #
    # Найдено проверкой продукта 2026-09-06. На запрос «what is two plus two»
    # и на прямое «из своей памяти, без веба» инструмент отвечал `pass`,
    # `checked 0`, а в ноте сам писал «Searches Gemini ran: not reported» — то
    # есть поиска НЕ БЫЛО ВООБЩЕ, и ответ нёс ПАМЯТЬ чужой модели, названную
    # «the substance». Это Р2 в чистом виде: ноль проверок при нуле нарушений
    # не бывает успехом.
    #
    # Цена ошибки названа в инструкции самого сервера: агенту велено после
    # поиска звать `record_model_fact`. Поверив `pass`, он записал бы в базу
    # фактов галлюцинацию под видом веб-находки — то есть отравил бы ровно то,
    # ради чистоты чего весь проект.
    искали = meta.get("webSearchQueries") or []
    без_основания = not results
    return {
        "outcome": UNMEASURED if без_основания else PASS,
        "checked": len(results),
        "violations": 0,
        "unmeasured": 1 if без_основания else 0,
        "note": (
            f"{len(results)} grounded source(s) via Gemini search ({gemini_model()}). URLs "
            "are Google redirect links and the publisher is in the title. "
            + (
                "НИ ОДНОГО ИСТОЧНИКА НЕ ВЕРНУЛОСЬ: текст ниже — это ответ модели "
                "по памяти, а не находка в вебе. Записывать его фактом нельзя; "
                "как основание он не годится. "
                if без_основания
                else ""
            )
            + f"Searches Gemini ran: {искали or 'not reported'}."
        ),
        "results": results,
        "answer": answer.strip(),
        "query": query,
        "backend": "gemini",
    }


def _listing(backend: str, query: str, results: list[dict], extra: dict | None = None) -> dict:
    """The house dict for a plain result list. Zero hits is never a pass."""
    if not results:
        return _empty(
            UNMEASURED,
            f"{backend} ran the search and returned nothing. Nothing was checked, "
            "which is not the same as nothing existing.",
        )
    return {
        "outcome": PASS,
        "checked": len(results),
        "violations": 0,
        "unmeasured": 0,
        "note": f"{len(results)} result(s) via {backend}.",
        "results": results,
        "query": query,
        "backend": backend,
        **(extra or {}),
    }


def _row(title: Any, url: Any, snippet: Any, date: Any = "") -> dict:
    link = str(url or "")
    row = {
        "title": str(title or ""),
        "url": link,
        "host": _host_of(link),
        "snippet": " ".join(str(snippet or "").split()),
        "fetchable": None,
    }
    if date:
        row["date"] = str(date)
    return row


def _serper(text: str, site: str, count: int) -> dict:
    key, key_from = _first_env(SERPER_KEY_ENV)
    query = f"site:{site} {text}" if site else text
    request = urllib.request.Request(
        SERPER_ENDPOINT,
        data=json.dumps({"q": query, "num": max(1, min(count, MAX_RESULTS_OTHER))}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-API-KEY": key},
    )
    payload, failed = _call("serper", request, endpoint=SERPER_ENDPOINT, key_from=key_from)
    if failed is not None:
        return failed
    organic = payload.get("organic") or [] if isinstance(payload, dict) else []
    rows = [
        _row(i.get("title"), i.get("link"), i.get("snippet"), i.get("date", ""))
        for i in organic[:count]
        if isinstance(i, dict) and i.get("link")
    ]
    box = payload.get("answerBox") if isinstance(payload, dict) else None
    extra = {}
    if isinstance(box, dict) and (box.get("answer") or box.get("snippet")):
        extra["answer"] = str(box.get("answer") or box.get("snippet"))
    return _listing("serper", query, rows, extra)


def _programmable(text: str, site: str, count: int) -> dict:
    key, key_from = _first_env(KEY_ENV)
    cse, cse_from = _first_env(CSE_ENV)
    params = {
        "key": key,
        "cx": cse,
        "q": f"site:{site} {text}" if site else text,
        "num": str(max(1, min(int(count), MAX_RESULTS))),
    }
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    hint = (
        f"The credentials came from {key_from} and {cse_from}. A 400 usually means "
        "the search engine id is wrong or the key is not valid.\n\n" + SETUP
    )
    payload, failed = _call(
        "the Programmable Search API",
        request,
        endpoint=ENDPOINT,
        key_from=f"{key_from} and {cse_from}",
        setup_hint=hint,
        cap=400_000,
    )
    if failed is not None:
        return failed
    items = payload.get("items") or [] if isinstance(payload, dict) else []
    if not items:
        total = (payload.get("searchInformation") or {}).get("totalResults", "0")
        return _empty(
            UNMEASURED,
            f"the search ran and returned nothing (totalResults {total}). "
            "Nothing was checked, which is not the same as nothing existing.",
        )
    rows = []
    for item in items:
        row = _row(item.get("title"), item.get("link"), item.get("snippet"))
        row["host"] = str(item.get("displayLink", "")).lower() or row["host"]
        rows.append(row)
    return _listing("programmable-search", params["q"], rows)


def _brave(text: str, site: str, count: int) -> dict:
    key, key_from = _first_env(BRAVE_KEY_ENV)
    query = f"site:{site} {text}" if site else text
    params = {"q": query, "count": str(max(1, min(count, MAX_RESULTS_OTHER)))}
    request = urllib.request.Request(
        f"{BRAVE_ENDPOINT}?{urllib.parse.urlencode(params)}",
        headers={"Accept": "application/json", "X-Subscription-Token": key},
    )
    payload, failed = _call("brave", request, endpoint=BRAVE_ENDPOINT, key_from=key_from)
    if failed is not None:
        return failed
    web = payload.get("web") or {} if isinstance(payload, dict) else {}
    rows = [
        _row(i.get("title"), i.get("url"), i.get("description"), i.get("age", ""))
        for i in (web.get("results") or [])[:count]
        if isinstance(i, dict) and i.get("url")
    ]
    return _listing("brave", query, rows)


def _tavily(text: str, site: str, count: int) -> dict:
    key, key_from = _first_env(TAVILY_KEY_ENV)
    body: dict[str, Any] = {"query": text, "max_results": max(1, min(count, MAX_RESULTS_OTHER))}
    if site:
        body["include_domains"] = [site]
    request = urllib.request.Request(
        TAVILY_ENDPOINT,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    payload, failed = _call("tavily", request, endpoint=TAVILY_ENDPOINT, key_from=key_from)
    if failed is not None:
        return failed
    items = payload.get("results") or [] if isinstance(payload, dict) else []
    rows = [
        _row(i.get("title"), i.get("url"), i.get("content"), i.get("published_date", ""))
        for i in items[:count]
        if isinstance(i, dict) and i.get("url")
    ]
    return _listing("tavily", f"site:{site} {text}" if site else text, rows)


def _exa(text: str, site: str, count: int) -> dict:
    key, key_from = _first_env(EXA_KEY_ENV)
    body: dict[str, Any] = {"query": text, "numResults": max(1, min(count, MAX_RESULTS_OTHER))}
    if site:
        body["includeDomains"] = [site]
    request = urllib.request.Request(
        EXA_ENDPOINT,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "x-api-key": key},
    )
    payload, failed = _call("exa", request, endpoint=EXA_ENDPOINT, key_from=key_from)
    if failed is not None:
        return failed
    items = payload.get("results") or [] if isinstance(payload, dict) else []
    rows = [
        _row(i.get("title"), i.get("url"), i.get("text") or "", i.get("publishedDate", ""))
        for i in items[:count]
        if isinstance(i, dict) and i.get("url")
    ]
    return _listing("exa", f"site:{site} {text}" if site else text, rows)


#: Кириллица в запросе -> русский индекс; иначе международный. Это выбор
#: ИНДЕКСА (yandex.ru против yandex.com), а не языка ответа.
_КИРИЛЛИЦА = re.compile(r"[а-яё]", re.I)


def _yandex_xml(raw: str, count: int) -> tuple[list[dict], str]:
    """(строки результатов, текст ошибки Яндекса) из XML-ответа Search API.

    Форма — классический Yandex XML: `yandexsearch/response/results/grouping/
    group/doc/{url,domain,title,headline,passages/passage}`, ошибка —
    `response/error[@code]`. ПРОВЕРЕНО ТОЛЬКО НА ФИКСТУРЕ: живого ответа не было.
    """
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        return [], f"the answer is not XML: {error}"
    err = root.find(".//response/error")
    if err is not None:
        return [], f"error {err.get('code', '?')}: {' '.join(''.join(err.itertext()).split())}"
    rows: list[dict] = []
    for doc in root.iter("doc"):
        url = (doc.findtext("url") or "").strip()
        if not url:
            continue
        title_node = doc.find("title")
        title = " ".join("".join(title_node.itertext()).split()) if title_node is not None else ""
        passages = [" ".join("".join(p.itertext()).split()) for p in doc.iter("passage")]
        headline = doc.find("headline")
        snippet = " ".join(passages) or (
            " ".join("".join(headline.itertext()).split()) if headline is not None else ""
        )
        row = _row(title, url, snippet, (doc.findtext("modtime") or "").strip())
        domain = (doc.findtext("domain") or "").strip().lower()
        row["host"] = row["host"] or domain
        rows.append(row)
        if len(rows) >= count:
            break
    return rows, ""


def _yandex(text: str, site: str, count: int) -> dict:
    key, key_from = _first_env(YANDEX_KEY_ENV)
    folder, folder_from = _first_env(YANDEX_FOLDER_ENV)
    query = f"site:{site} {text}" if site else text
    clipped = query[:YANDEX_QUERY_MAX]
    russian = bool(_КИРИЛЛИЦА.search(clipped))
    body = {
        "query": {
            "searchType": "SEARCH_TYPE_RU" if russian else "SEARCH_TYPE_COM",
            "queryText": clipped,
            "page": 0,
        },
        "groupSpec": {
            "groupMode": "GROUP_MODE_FLAT",
            "groupsOnPage": max(1, min(count, MAX_RESULTS_OTHER)),
            "docsInGroup": 1,
        },
        "maxPassages": 2,
        "l10n": "LOCALIZATION_RU" if russian else "LOCALIZATION_EN",
        "folderId": folder,
        "responseFormat": "FORMAT_XML",
    }
    request = urllib.request.Request(
        YANDEX_ENDPOINT,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Api-Key {key}"},
    )
    payload, failed = _call(
        "yandex", request, endpoint=YANDEX_ENDPOINT, key_from=f"{key_from} and {folder_from}"
    )
    if failed is not None:
        return failed
    data = payload.get("rawData") if isinstance(payload, dict) else None
    if not data:
        return _empty(UNMEASURED, "yandex answered without `rawData`; nothing to read")
    try:
        raw = base64.b64decode(str(data)).decode("utf-8", "replace")
    except (ValueError, TypeError) as error:
        return _empty(UNMEASURED, f"yandex `rawData` is not base64: {error}")
    rows, error_text = _yandex_xml(raw, count)
    if error_text:
        return _empty(UNMEASURED, f"yandex answered, but with {error_text}. Nothing was searched.")
    out = _listing("yandex", clipped, rows)
    if len(query) > YANDEX_QUERY_MAX and out["outcome"] == PASS:
        out["note"] += f" The query was cut to Yandex's {YANDEX_QUERY_MAX}-character limit."
    return out


def _yandex_allowed() -> bool:
    if str(os.environ.get(YANDEX_OPT_IN_ENV, "") or "").strip() != "1":
        return False
    return bool(_first_env(YANDEX_KEY_ENV)[0] and _first_env(YANDEX_FOLDER_ENV)[0])


def _configured_cse() -> bool:
    return bool(_first_env(KEY_ENV)[0] and _first_env(CSE_ENV)[0])


#: The order backends are tried in, with what makes each one "configured".
#: Gemini first because it searches the whole index; Serper second because it
#: is Google's index too and one key; Programmable Search third because a new
#: engine is capped at 50 domains; the three non-Google ones after.
BACKENDS: tuple[tuple[str, Callable[[], bool], Callable[[str, str, int], dict]], ...] = (
    ("gemini", lambda: bool(_first_env(GEMINI_KEY_ENV)[0]), _gemini),
    ("serper", lambda: bool(_first_env(SERPER_KEY_ENV)[0]), _serper),
    ("programmable-search", _configured_cse, _programmable),
    ("brave", lambda: bool(_first_env(BRAVE_KEY_ENV)[0]), _brave),
    ("tavily", lambda: bool(_first_env(TAVILY_KEY_ENV)[0]), _tavily),
    ("exa", lambda: bool(_first_env(EXA_KEY_ENV)[0]), _exa),
    # ПОСЛЕДНИМ и только по явному согласию: см. `YANDEX_ENDPOINT`.
    ("yandex", _yandex_allowed, _yandex),
)

#: Чьим ключом платит каждый бэкенд — для отпечатка в памяти отказов.
_KEY_ENVS: dict[str, tuple[str, ...]] = {
    "gemini": GEMINI_KEY_ENV,
    "serper": SERPER_KEY_ENV,
    "programmable-search": KEY_ENV,
    "brave": BRAVE_KEY_ENV,
    "tavily": TAVILY_KEY_ENV,
    "exa": EXA_KEY_ENV,
    "yandex": YANDEX_KEY_ENV,
}


def _fingerprint(backend: str) -> str:
    """Отпечаток ключа бэкенда: сам ключ в памяти отказов не хранится."""
    key, _ = _first_env(_KEY_ENVS.get(backend, ()))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12] if key else ""


def _remembered_refusal(backend: str) -> tuple[str, str, float] | None:
    """(вид, нота, секунд до повтора), если аккаунт этого бэкенда отказал недавно."""
    ключ = (backend, _fingerprint(backend))
    hit = _NOT_SERVED.get(ключ)
    if hit is None:
        return None
    until, kind, note = hit
    left = until - _now()
    if left <= 0:
        _NOT_SERVED.pop(ключ, None)
        return None
    return kind, note, left


def client_side(text: str, site: str = "") -> dict:
    """What the CALLING agent can do itself when no backend here can answer.

    Most MCP clients carry their own web search. When ours is unconfigured, out
    of credit or refused, the honest help is to hand over the queries and say
    how the findings get back into the base — not to stop at "could not".
    """
    base = " ".join(str(text or "").split())
    prefix = f"site:{site} " if site else ""
    queries = [f"{prefix}{base}"]
    for suffix in ("official documentation", "API reference limits"):
        candidate = f"{prefix}{base} {suffix}"
        if candidate not in queries:
            queries.append(candidate)
    return {
        "mode": "client-side search",
        "queries": queries,
        "then": (
            "Run these with YOUR OWN web search tool (e.g. WebSearch). Prefer the "
            "vendor's own page; open it with fetch_url to read it. For every value "
            "you rely on, call record_model_fact with the value, the source URL, "
            "the source tier and the date the SOURCE stated it — and read_directly="
            "False when you only saw a snippet. A snippet is not a vendor statement."
        ),
    }


def search(query: str, *, count: int = 8, site: str = "", check_fetchable: bool = True) -> dict:
    """Search the web and say, per result, whether the page can also be read.

    Backends are tried in `BACKENDS` order — Gemini, Serper, Programmable
    Search, Brave, Tavily, Exa, and Yandex only with `STUDIO_SEARCH_ALLOW_YANDEX=1`
    — each only when its key is set, and the next is
    tried when one cannot answer (billing, quota, permission, policy refusal,
    no sources, an invalid key). `attempts` lists every backend that was asked
    and what it said; `backend` names the one that answered.

    :param site: restrict to one domain, e.g. "kling.ai". Useful even for a
        blocked host: the snippets still come back.
    :param check_fetchable: probe each distinct host. Costs one request per
        host; turn it off when only the snippets are wanted.

    :returns: the house judging dict plus `results` — title, url, snippet,
        host, and `fetchable` — `backend`, `attempts`, and `client_side` when
        no backend produced sources.

    Three outcomes. No credentials is `could not measure`, not `fail`: nothing
    was searched, and that is different from searching and finding nothing.
    Zero hits for a real query is also `could not measure`, because zero
    checks is never a pass. A billing or quota refusal is `could not measure`
    too. `fail` is left for a backend that refused the KEY or the request as
    malformed, when no other backend answered either.
    """
    text = str(query or "").strip()
    if not text:
        return _empty(UNMEASURED, "no query was given, so nothing was searched")
    # ЗАПРОС ВОЗВРАЩАЕТСЯ И В ОТКАЗЕ. НАЙДЕНО валидатором 2026-10-14 (G15):
    # ответ без источников нёс `"query": ""` — вызывающий, у которого в
    # контексте несколько поисков, не мог сказать, какой из них не удался.
    asked = f"site:{site} {text}" if site else text
    try:
        wanted = max(1, int(count))
    except (TypeError, ValueError):
        wanted = 8

    ready = [(name, run) for name, configured, run in BACKENDS if configured()]
    if not ready:
        missing = []
        if not _first_env(KEY_ENV)[0]:
            missing.append(f"an API key (looked at {', '.join(KEY_ENV)})")
        if not _first_env(CSE_ENV)[0]:
            missing.append(f"a search engine id (looked at {', '.join(CSE_ENV)})")
        out = _empty(
            UNMEASURED,
            "search is not configured. The Programmable Search route is missing "
            + " and ".join(missing)
            + ", and no Gemini key was found either (looked at "
            + ", ".join(GEMINI_KEY_ENV)
            + "), nor a Serper, Brave, Tavily or Exa key (looked at "
            + ", ".join(SERPER_KEY_ENV + BRAVE_KEY_ENV + TAVILY_KEY_ENV + EXA_KEY_ENV)
            + "). Use client_side below in the meantime.\n\n"
            + SETUP,
        )
        out["attempts"] = []
        out["client_side"] = client_side(text, site)
        out["query"] = asked
        return out

    attempts: list[dict] = []
    first: dict | None = None
    for name, run in ready:
        remembered = _remembered_refusal(name)
        if remembered is not None:
            kind, why, left = remembered
            skipped = _empty(
                UNMEASURED,
                f"SKIPPED, not asked again: {name} refused this account for "
                f"{kind.upper()} within the last {NOT_SERVED_TTL_SECONDS / 60:.0f} min "
                f"(retry in {left / 60:.0f} min, or with another key). "
                f"What it said then: {why[:240]}",
            )
            attempts.append(
                {"backend": name, "outcome": UNMEASURED, "note": skipped["note"], "skipped": True}
            )
            if first is None:
                first = skipped
            continue
        out = run(text, site, wanted)
        attempts.append({"backend": name, "outcome": out["outcome"], "note": out["note"]})
        if out.get("refusal") in CACHED_REFUSALS:
            _NOT_SERVED[(name, _fingerprint(name))] = (
                _now() + NOT_SERVED_TTL_SECONDS,
                str(out["refusal"]),
                str(out["note"]),
            )
        if out["outcome"] == PASS:
            if check_fetchable and out.get("results"):
                seen: dict[str, bool | None] = {}
                for row in out["results"]:
                    host = row["host"]
                    if host and host not in seen:
                        seen[host] = _fetchable(host)
                    row["fetchable"] = seen.get(host) if host else None
                # ПРИСВАИВАНИЕ, А НЕ ПРИБАВЛЕНИЕ, И ЭТО ПРОВЕРЕНО. Приёмка
                # 2026-09-06 сочла, что счётчик нечитаемых хостов затирает
                # сигнал «источников не вернулось». Сигналы НЕ СТАЛКИВАЮТСЯ —
                # эта ветка идёт только при непустом `results` и исходе `pass`,
                # а «источников нет» бывает только при пустом.
                out["unmeasured"] = sum(1 for r in out["results"] if r["fetchable"] is False)
                readable = sum(1 for r in out["results"] if r["fetchable"] is True)
                out["note"] += (
                    f" {readable} on hosts this session can open, {out['unmeasured']} on "
                    "hosts the policy refuses. A refused host still gives you its snippet "
                    "and its URL to cite — it just cannot be read in full."
                )
            if len(attempts) > 1:
                out["note"] += " Fell back after: " + "; ".join(
                    f"{a['backend']} — {a['outcome']}: {a['note'][:200]}" for a in attempts[:-1]
                )
            out["attempts"] = attempts
            return out
        if first is None:
            first = out

    assert first is not None
    final = dict(first)
    final["outcome"] = FAIL if any(a["outcome"] == FAIL for a in attempts) else UNMEASURED
    final["violations"] = sum(1 for a in attempts if a["outcome"] == FAIL)
    final["unmeasured"] = max(1, sum(1 for a in attempts if a["outcome"] == UNMEASURED))
    final["checked"] = 0
    final["note"] = (
        f"no search backend produced sources ({len(attempts)} tried). "
        + " | ".join(f"{a['backend']} — {a['outcome']}: {a['note']}" for a in attempts)
        + " | Use client_side: run its queries with your own web search tool."
    )
    final["attempts"] = attempts
    final["client_side"] = client_side(text, site)
    final["query"] = asked
    final.pop("refusal", None)
    return final


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
