"""Collect workflow posts from r/comfyui through Reddit's Data API.

WHAT IS REACHABLE, MEASURED 2026-08-27, and it decides whether this can work

    www.reddit.com/api/v1/access_token   401  {"message": "Unauthorized", ...}
    www.reddit.com/r/comfyui/hot.json    403  a Reddit web page
    oauth.reddit.com/r/comfyui/hot       403  Reddit's "Blocked" page,
                                              IDENTICALLY with and without an
                                              Authorization header

Read those three together, because the pair matters more than either line.

The token endpoint answers like an API: a JSON 401 that says "authenticate".
`oauth.reddit.com` — the host every authenticated read goes to — answers with
the "Blocked" page, and answers it the same whether a bearer is sent or not.
That is an edge block on this caller, decided before any credential is looked
at, not a refusal of our credentials.

So the honest reading is: **a Reddit app id and secret would probably NOT make
this work from this container**, because the host that would serve the data is
not evaluating credentials at all. Strong evidence, not proof — a VALID token
has never been presented, and only that would settle it. It is recorded here
so that nobody registers an app on the strength of the 401 alone.

The egress policy is not the obstacle: it lets reddit.com through. This is
Reddit's own decision about being read from a datacentre, and it is not routed
around — no proxy, no residential exit, no scraping past the 403. Answering
somebody's "no" with a workaround is the one thing this package does not do.

WHAT IS THEREFORE BUILT, AND WHAT IS NOT

The parsing, the credential handling and the three outcomes are complete and
tested offline. The live POST path IS verified as far as Reddit allows: a
deliberately wrong credential reached the token endpoint and came back
`401 Unauthorized` through this module's own error handling, so the request
shape, the Basic auth encoding and the failure reporting are exercised against
the real host.

UNVERIFIED, and it will stay so until the block lifts: a successful token
exchange, and any authenticated read. `collect` reports `could not measure` —
never `pass` — when the credential is absent, so an empty run cannot be
mistaken for an empty subreddit.

No runner script was written. A command whose only possible output today is a
403 is a command nobody can check, and this package does not ship code nobody
has run any further than it has to.

WHY r/comfyui AND NOT REDDIT

The owner's own reason: it is where people post workflows together with the
results they got. The source table already rates `reddit.com/r/comfyui/` as
`portal` and plain `reddit.com` as `blog`, by path, for exactly that reason —
a community posting work is not the same source as a forum.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio.mcp import credentials, fetch

__all__ = [
    "CLIENT_ID_ENV",
    "CLIENT_SECRET_ENV",
    "DEFAULT_OUTPUT_PATH",
    "MIN_BODY_WORDS",
    "REQUIRED_ROW_FIELDS",
    "collect",
    "posts_from_listing",
    "token",
]

DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "reddit_workflows.jsonl"

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
LISTING_URL = "https://oauth.reddit.com/r/{subreddit}/{sort}"

#: Spellings to accept for the credential, most preferred first. Loose matching
#: is `credentials.find`'s job and it exists because this package has twice
#: reported "no key" beside a working one whose name a human spelled
#: differently. What comes back is the spelling that was FOUND.
CLIENT_ID_ENV: tuple[str, ...] = ("REDDIT_CLIENT_ID", "REDDIT_ID", "REDDIT_APP_ID")
CLIENT_SECRET_ENV: tuple[str, ...] = ("REDDIT_CLIENT_SECRET", "REDDIT_SECRET", "REDDIT_APP_SECRET")

#: A workflow post is a post with a body. A title alone is a link, and this
#: collects the wording, so a post with nothing written in it is not a row.
MIN_BODY_WORDS = 20

#: Same contract as every other collected file here: origin travels with the
#: row or the row does not get written.
REQUIRED_ROW_FIELDS: tuple[str, ...] = (
    "title",
    "body",
    "permalink",
    "source_url",
    "harvested",
    "provenance",
    "rights",
)

PROVENANCE_PREFIX = "reddit:"

#: CHOSEN, 60 requests a minute. A figure of 100 queries per minute per OAuth
#: client circulates for the free tier, and it is UNVERIFIED here (rule C4):
#: it comes from a grounded search summary, and Reddit's own terms and API
#: documentation live on www.redditinc.com and support.reddithelp.com, both of
#: which this environment's egress policy refuses. Not routed around; both
#: hosts are in the allowlist request with that as their reason.
#:
#: So this is a floor picked to sit under the number we believe, not a limit
#: read from the publisher. Raise it only against a page somebody has opened.
DEFAULT_DELAY_SECONDS = 1.0


def _words(text: str) -> int:
    return len(str(text or "").split())


def token(
    *,
    fetcher: Callable[..., dict] | None = None,
    user_agent: str = "",
) -> dict:
    """Exchange the client credentials for a bearer token. Three outcomes.

    `could not measure` when no credential is set — that is a gap in this
    environment, not a failure of Reddit's, and the two must not print the
    same. The variable name REPORTED is the one that was found, so an owner who
    spelled it differently sees their own spelling rather than ours.
    """
    get = fetcher or fetch.fetch
    client_id, id_name = credentials.find(CLIENT_ID_ENV)
    secret, secret_name = credentials.find(CLIENT_SECRET_ENV)
    if not client_id or not secret:
        missing = [
            label
            for label, value in (("client id", client_id), ("client secret", secret))
            if not value
        ]
        return {
            "outcome": UNMEASURED,
            "checked": 2,
            "violations": 0,
            "unmeasured": len(missing),
            "note": (
                f"no Reddit {' and no '.join(missing)} in this environment, so nothing "
                f"was attempted. Set {CLIENT_ID_ENV[0]} and {CLIENT_SECRET_ENV[0]} from "
                "a registered script app. Reddit refuses the unauthenticated browse "
                "routes with 403 (MEASURED), so there is no read path without this."
            ),
            "token": "",
            "found_as": [name for name in (id_name, secret_name) if name],
        }

    basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    answer = get(
        TOKEN_URL,
        why_wanted="authenticate to Reddit's Data API to collect r/comfyui workflow posts",
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            **({"User-Agent": user_agent} if user_agent else {}),
        },
        data=urllib.parse.urlencode({"grant_type": "client_credentials"}).encode(),
    )
    if answer.get("outcome") != PASS:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": (
                f"the token endpoint refused the credential found as "
                f"{id_name or '?'}: {answer.get('note')}"
            ),
            "token": "",
            "found_as": [name for name in (id_name, secret_name) if name],
        }
    try:
        body = json.loads(answer.get("text") or "")
    except ValueError:
        body = {}
    bearer = str((body or {}).get("access_token") or "")
    if not bearer:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": "the token endpoint answered without an access_token in the body",
            "token": "",
            "found_as": [name for name in (id_name, secret_name) if name],
        }
    return {
        "outcome": PASS,
        "checked": 1,
        "violations": 0,
        "unmeasured": 0,
        "note": f"authenticated with the credential found as {id_name} / {secret_name}",
        "token": bearer,
        "found_as": [id_name, secret_name],
    }


def posts_from_listing(payload: Any, subreddit: str, harvested: str, rights: str) -> dict:
    """The workflow posts in one listing page. Pure, so it is tested offline.

    Three outcomes, and the middle one carries the count that explains it: a
    page of link posts is not a failure and is not a harvest either.
    """
    children = []
    after = ""
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            children = [c for c in (data.get("children") or []) if isinstance(c, dict)]
            after = str(data.get("after") or "")

    rows: list[dict] = []
    no_body = 0
    removed = 0
    for child in children:
        post = child.get("data")
        if not isinstance(post, dict):
            no_body += 1
            continue
        body = str(post.get("selftext") or "").strip()
        # Reddit keeps the row and blanks the text when a post is taken down.
        # That is a deletion, not a short post, and counting it as one would
        # quietly report other people's removals as thin content.
        if body in ("[removed]", "[deleted]"):
            removed += 1
            continue
        if _words(body) < MIN_BODY_WORDS:
            no_body += 1
            continue
        permalink = str(post.get("permalink") or "").strip()
        if not permalink:
            no_body += 1
            continue
        rows.append(
            {
                "title": str(post.get("title") or "").strip(),
                "body": body,
                "permalink": f"https://www.reddit.com{permalink}",
                "flair": str(post.get("link_flair_text") or ""),
                "score": post.get("score"),
                "num_comments": post.get("num_comments"),
                "created_utc": post.get("created_utc"),
                "over_18": bool(post.get("over_18")),
                "subreddit": subreddit,
                "source_url": f"https://www.reddit.com/r/{subreddit}/",
                "harvested": harvested,
                "provenance": PROVENANCE_PREFIX + str(post.get("author") or "unknown"),
                "rights": rights,
            }
        )

    if not children:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"r/{subreddit} answered with no posts at all",
            "rows": [],
            "after": after,
            "no_body": 0,
            "removed": 0,
        }
    if not rows:
        return {
            "outcome": UNMEASURED,
            "checked": len(children),
            "violations": 0,
            "unmeasured": len(children),
            "note": (
                f"r/{subreddit}: {len(children)} post(s) and none usable — "
                f"{no_body} without a body, {removed} removed or deleted"
            ),
            "rows": [],
            "after": after,
            "no_body": no_body,
            "removed": removed,
        }
    return {
        "outcome": PASS,
        "checked": len(children),
        "violations": 0,
        "unmeasured": no_body + removed,
        "note": (
            f"r/{subreddit}: {len(rows)} workflow post(s) of {len(children)}; "
            f"{no_body} without a body, {removed} removed or deleted"
        ),
        "rows": rows,
        "after": after,
        "no_body": no_body,
        "removed": removed,
    }


def _incomplete(row: dict) -> list[str]:
    return [name for name in REQUIRED_ROW_FIELDS if not str(row.get(name) or "").strip()]


def _existing(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        link = str(row.get("permalink") or "")
        if link:
            seen.add(link)
    return seen


def collect(
    *,
    harvested: str,
    rights: str,
    subreddit: str = "comfyui",
    sort: str = "hot",
    pages: int = 1,
    per_page: int = 100,
    path: Path | None = None,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    fetcher: Callable[..., dict] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    bearer: str = "",
) -> dict:
    """Walk a subreddit's listing and append the workflow posts. Three outcomes.

    :param bearer: an existing token. Empty means fetch one, which is what
        makes the missing-credential case reachable and reported rather than
        raised.

    An absent credential is `could not measure`. An empty harvest with a
    working credential is `could not measure` too, and says which of the two it
    was — because "no posts had bodies" and "we could not log in" are different
    facts and only one of them is Reddit's.
    """
    get = fetcher or fetch.fetch
    target = path or DEFAULT_OUTPUT_PATH
    already = _existing(target)

    if not bearer:
        got = token(fetcher=get)
        if got["outcome"] != PASS:
            return {
                "outcome": got["outcome"],
                "checked": 0,
                "violations": got["violations"],
                "unmeasured": got["unmeasured"],
                "note": got["note"],
                "written": 0,
                "rows": [],
            }
        bearer = str(got["token"])

    rows: list[dict] = []
    no_body = 0
    removed = 0
    pages_read = 0
    after = ""
    for index in range(max(0, int(pages))):
        if index:
            sleeper(delay_seconds)
        url = LISTING_URL.format(subreddit=subreddit, sort=sort) + f"?limit={int(per_page)}"
        if after:
            url += f"&after={after}"
        answer = get(
            url,
            why_wanted="collect r/comfyui workflow posts",
            headers={"Authorization": f"Bearer {bearer}"},
            max_bytes=2_000_000,
        )
        if answer.get("outcome") != PASS:
            if pages_read:
                break
            return {
                "outcome": FAIL,
                "checked": 0,
                "violations": 1,
                "unmeasured": 0,
                "note": f"the listing did not answer: {answer.get('note')}",
                "written": 0,
                "rows": [],
            }
        try:
            payload = json.loads(answer.get("text") or "")
        except ValueError:
            return {
                "outcome": FAIL,
                "checked": pages_read,
                "violations": 1,
                "unmeasured": 0,
                "note": "the listing answered with something that is not JSON",
                "written": 0,
                "rows": [],
            }
        pages_read += 1
        found = posts_from_listing(payload, subreddit, harvested, rights)
        rows.extend(found["rows"])
        no_body += int(found["no_body"])
        removed += int(found["removed"])
        after = str(found["after"])
        if not after:
            break

    fresh = []
    bad: list[str] = []
    for row in rows:
        missing = _incomplete(row)
        if missing:
            bad.append(f"{row.get('permalink', '?')}: {', '.join(missing)}")
            continue
        if row["permalink"] in already:
            continue
        already.add(row["permalink"])
        fresh.append(row)

    if bad:
        return {
            "outcome": FAIL,
            "checked": len(rows),
            "violations": len(bad),
            "unmeasured": 0,
            "note": (
                f"{len(bad)} row(s) came out without their origin fields and NOTHING "
                f"was written: {bad[0]}"
            ),
            "written": 0,
            "rows": [],
        }

    if fresh:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            for row in fresh:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    detail = (
        f"{pages_read} page(s) of r/{subreddit}; {len(rows)} workflow post(s) parsed, "
        f"{len(rows) - len(fresh)} already held, {no_body} without a body, "
        f"{removed} removed or deleted"
    )
    if not rows:
        return {
            "outcome": UNMEASURED,
            "checked": pages_read,
            "violations": 0,
            "unmeasured": max(1, pages_read),
            "note": "authenticated, and the listing produced no usable post. " + detail,
            "written": 0,
            "rows": [],
        }
    return {
        "outcome": PASS,
        "checked": pages_read,
        "violations": 0,
        "unmeasured": no_body + removed,
        "note": f"{len(fresh)} new post(s) written to {target}. " + detail,
        "written": len(fresh),
        "rows": fresh,
    }


def summarise(rows: Sequence[dict]) -> dict:
    """What is held, by author, so concentration is visible before use."""
    rows = list(rows)
    by_provenance: dict[str, int] = {}
    for row in rows:
        key = str(row.get("provenance") or "")
        by_provenance[key] = by_provenance.get(key, 0) + 1
    if not rows:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "nothing collected yet",
            "by_provenance": {},
        }
    return {
        "outcome": PASS,
        "checked": len(rows),
        "violations": 0,
        "unmeasured": 0,
        "note": (
            f"{len(rows)} post(s) from {len(by_provenance)} author(s); "
            f"the largest holds {max(by_provenance.values())}"
        ),
        "by_provenance": by_provenance,
    }
