"""Fetch from the web through the policy, and never around it.

WHAT THIS IS FOR

72% of the knowledge base was blog tier on 2026-08-27 — second-hand writing
about vendors rather than vendors. The reflex diagnosis was "the proxy blocks
everything". Measuring it said otherwise: of 28 hosts probed, 10 answered.
What was missing was not access, it was a client that USED the access.

    open    raw.githubusercontent.com  api.github.com  github.com
            pypi.org  files.pythonhosted.org  huggingface.co
            cloud.google.com  storage.googleapis.com
            api.klingai.com  api.fal.ai
    closed  docs.bfl.ai  arxiv.org  kling.ai  help.runwayml.com
            elevenlabs.io  platform.openai.com  ai.google.dev
            api.openai.com  api.replicate.com  unpkg.com  ... (18 total)

The shape of that is worth reading: the API hosts of the two vendors this
project holds keys for are open, and the documentation hosts are shut. So the
vendor is reachable — as a running system, not as prose.

WHAT THIS WILL NOT DO, AND WHY IT IS NOT A LIMITATION TO ENGINEER AROUND

A blocked host stays blocked. No mirror, no read-through proxy, no cache, no
archive copy, no second attempt at a refusal. The proxy README says it plainly
— do not retry or route around organisation policy denials, report them — and
the house rule says the same: the decision belongs to whoever owns the policy,
and going around it silently takes that decision away from them.

So the refusals are not swallowed. Every one is recorded with the URL that
wanted it and why, and `wanted()` renders the accumulated list. That list is
the allowlist request, assembled out of real attempts rather than guesses.

THREE THINGS THAT MUST NEVER PRINT THE SAME

    could not measure   the policy refused the host (CONNECT 403/407)
    could not measure   the network failed, timed out, or DNS died
    fail                the host answered and said no: 404, 500, bad URL

The first is somebody else's decision, the second is worth retrying, the third
is our own mistake. Collapsing them is how "we cannot reach the vendor" turns
into "the vendor has no such page", and that error is exactly what put 33 blog
claims into this base.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

__all__ = ["fetch", "reachability", "wanted", "note_denial", "DENIED_PATH", "MEASURED_ON"]

#: When the map in this docstring was measured. A reachability claim with no
#: date is the same rot the fact base guards against.
MEASURED_ON = "2026-08-27"

#: CHOSEN: long enough for a slow documentation host, short enough that a
#: chat waiting on it does not feel hung.
TIMEOUT_SECONDS = 25

#: Where refusals accumulate, so the allowlist request writes itself.
DENIED_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "denied_hosts.jsonl"

#: The proxy's signature for an organisation policy denial, as observed:
#: `URLError(<urlopen error Tunnel connection failed: 403 Forbidden>)`.
_DENIAL = re.compile(r"tunnel connection failed:\s*(403|407)", re.I)

_UA = "lipsync-studio-knowledge/1.0 (+https://github.com/greenflac/lipsync-templates)"


def _host(url: str) -> str:
    match = re.match(r"https?://([^/:]+)", str(url or ""), re.I)
    return match.group(1).lower() if match else ""


def note_denial(url: str, reason: str, why_wanted: str = "", *, incidental: bool = False) -> dict:
    """Record that the policy refused a host, so the request for it writes itself.

    :param why_wanted: what the caller was trying to learn. An allowlist request
        that says "we need arxiv.org" is weaker than one that says which claim
        is stuck on blog tier without it.
    :param incidental: True when nobody asked for this host — it was swept up by
        a bulk probe, such as tagging search hits with whether they open.

        OBSERVED 2026-08-27, on the first live Gemini search: one query added
        five hosts nobody had ever wanted (atlascloud.ai, magnific.com, kie.ai,
        evolink.ai, wavespeed.ai) to a file holding six hosts that a real
        question was stuck behind. `wanted()` presents that file to a human who
        then goes and asks for the hosts in it, and its own note claimed each
        one "was needed for a real question". A few more searches and the ask
        the owner has to justify is mostly noise. Refusals are still all
        recorded — routing around them is what is forbidden, not counting them —
        but an incidental one is reported apart from the ask.
    """
    host = _host(url)
    if not host:
        return {"recorded": False, "host": ""}
    row = {
        "host": host,
        "url": str(url),
        "reason": reason,
        "why_wanted": why_wanted,
        "incidental": bool(incidental),
        "state": STATE_REFUSED,
        "first_seen": date.today().isoformat(),
    }
    DENIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    # This file is append-only history, and three things make a new row worth
    # appending:
    #
    #  fresh     nobody has recorded this host at all
    #  promoted  it was met by a bulk probe and is now actually needed, so it
    #            can move into the ask. Without this, the order two calls
    #            happened in would decide whether a host the owner needs is
    #            ever asked for.
    #  restated  it is already in the ask, but for a DIFFERENT reason. The
    #            reason is the whole request — OBSERVED 2026-08-27, docs.bfl.ai
    #            was still asked for because "every recorded claim about it is
    #            blog tier", which the re-tiering had made false that morning.
    #            Keeping only the first reason freezes the request at whatever
    #            the base looked like the day the host was first refused.
    rows = _read_denied()
    known = {
        r.get("host"): bool(r.get("incidental", False))
        for r in rows
        if str(r.get("state", STATE_REFUSED)) == STATE_REFUSED
    }
    # A host whose latest row is NOT a refusal, refused again, is a fresh
    # refusal rather than a restatement: the grant went away, or the plan came
    # back. Written against "not refused" and not against the list of other
    # states, because this rule was first written when there were two states
    # and it silently stopped covering the third the day `unwanted` was added
    # — OBSERVED 2026-08-27, by a test that expected a withdrawn host to
    # return to the ask when it was refused again, and it did not.
    latest_state = _latest_states(rows)
    for row_host, state in latest_state.items():
        if state != STATE_REFUSED:
            known.pop(row_host, None)
    # The last reason we gave for ASKING. An `open` row carries no reason, so
    # letting it reset this made the restatement rule fire on a re-refusal and
    # quietly do the reopening rule's job — which left that rule dead code that
    # no test could distinguish from a working one (OBSERVED 2026-08-27).
    latest_reason = ""
    for previous in rows:
        if (
            previous.get("host") == host
            and not previous.get("incidental", False)
            and str(previous.get("state", STATE_REFUSED)) == STATE_REFUSED
        ):
            latest_reason = str(previous.get("why_wanted", ""))
    fresh = host not in known
    promoted = not fresh and known[host] and not incidental
    restated = not fresh and not incidental and why_wanted.strip() != latest_reason.strip()
    if fresh or promoted or restated:
        with DENIED_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"recorded": fresh or promoted or restated, "host": host}


#: A row's state. Absent means `refused`: every row written before 2026-08-27
#: was a refusal, because that was the only thing this file recorded.
STATE_REFUSED = "refused"
STATE_OPEN = "open"
#: Still refused, and no longer wanted. A third state because dropping a plan
#: is not the same event as being granted access, and recording it as `open`
#: would put a lie in the file — the host never answered.
#:
#: OBSERVED 2026-08-27: Reddit was dropped, and the two hosts carrying its
#: terms stayed in the ask with the reason "decides whether a collector may be
#: written at all". Nobody was going to write one. A request that asks for
#: access nobody needs any more is the same defect as one that asks for access
#: already granted, and this file had already been fixed once for the second.
STATE_UNWANTED = "unwanted"


def _latest_states(rows: list[dict]) -> dict[str, str]:
    """The last state recorded for each host. Absent `state` means refused."""
    latest: dict[str, str] = {}
    for row in rows:
        host = row.get("host", "")
        if host:
            latest[host] = str(row.get("state", STATE_REFUSED))
    return latest


def note_open(url: str) -> dict:
    """Record that a previously-refused host now answers, retiring it from the ask.

    OBSERVED 2026-08-27: the allowlist request is assembled from refusals that
    happened, and a refusal never expires. When the owner granted 21 hosts, the
    generated request went on asking for all 21 — it had no way to learn it had
    been answered. A request that asks for access you already granted is worse
    than no request: it is the reason the next one is not read.

    So this file is a log of STATE CHANGES, not of refusals. One row is written
    the first time a refused host answers, and `wanted()` reads the latest row
    per host. The history of "asked on this date, granted by that one" survives
    in the file, which is the part worth keeping.

    Called from `fetch()` on any successful response, so the ask retires itself
    through ordinary use rather than only when somebody remembers to re-run the
    request generator.
    """
    host = _host(url)
    if not host:
        return {"recorded": False, "host": ""}
    latest = _latest_states(_read_denied()).get(host, "")
    # Only a transition is written. Without this, every fetch of an open host
    # appends a row forever.
    #
    # The test is "not already open", not "is refused": written the second way,
    # a host withdrawn from the ask that LATER answered was never recorded as
    # open, so the file lost the fact that access had arrived — OBSERVED
    # 2026-08-27, the day `unwanted` was added, by the test that expected it.
    if latest == "" or latest == STATE_OPEN:
        return {"recorded": False, "host": host}
    DENIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DENIED_PATH.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "host": host,
                    "url": str(url),
                    "state": STATE_OPEN,
                    "first_seen": date.today().isoformat(),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return {"recorded": True, "host": host}


def note_unwanted(host: str, reason: str) -> dict:
    """Withdraw a host from the ask without claiming it opened. Three outcomes.

    For a plan that was abandoned. The host stays refused — that is the truth —
    and stops being asked for, and the reason travels with it so the next
    reader can see the ask shrank by a decision rather than by a grant.

    A host nobody ever asked for is `could not measure`, not a success: a typo
    would otherwise report that it had been withdrawn.
    """
    name = str(host or "").strip().lower()
    why = str(reason or "").strip()
    if not name or not why:
        missing = [n for n, v in (("host", name), ("reason", why)) if not v]
        return {
            "outcome": FAIL,
            "checked": 2,
            "violations": len(missing),
            "unmeasured": 0,
            "note": ", ".join(missing)
            + " is required; a withdrawal without a reason is a deletion",
            "host": name,
        }
    latest = ""
    for row in _read_denied():
        if row.get("host") == name:
            latest = str(row.get("state", STATE_REFUSED))
    if latest == "":
        return {
            "outcome": UNMEASURED,
            "checked": 1,
            "violations": 0,
            "unmeasured": 1,
            "note": f"{name} has never been recorded as refused, so there was nothing to withdraw",
            "host": name,
        }
    if latest == STATE_UNWANTED:
        return {
            "outcome": PASS,
            "checked": 1,
            "violations": 0,
            "unmeasured": 0,
            "note": f"{name} was already withdrawn from the ask",
            "host": name,
        }
    DENIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DENIED_PATH.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "host": name,
                    "state": STATE_UNWANTED,
                    "reason": why,
                    "first_seen": date.today().isoformat(),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return {
        "outcome": PASS,
        "checked": 1,
        "violations": 0,
        "unmeasured": 0,
        "note": f"{name} withdrawn from the ask: {why}",
        "host": name,
    }


def _read_denied() -> list[dict]:
    if not DENIED_PATH.is_file():
        return []
    rows: list[dict] = []
    for line in DENIED_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def fetch(
    url: str,
    *,
    why_wanted: str = "",
    max_bytes: int = 400_000,
    incidental: bool = False,
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
) -> dict:
    """Open one URL through the configured proxy. Three outcomes, no fallbacks.

    :param why_wanted: what this fetch was for. Carried into the denial record
        when the policy refuses, so the allowlist request explains itself.
    :param incidental: True when this host is being swept by a bulk probe
        rather than actually wanted; see `note_denial`. A refusal is recorded
        either way — this only keeps it out of the ask.
    :param headers: extra request headers, merged over the User-Agent. For an
        API that authenticates per request — an OAuth bearer token, an API key
        header. The User-Agent stays unless a caller replaces it deliberately.
    :param data: a request body. Its presence is what makes this a POST, which
        is how an OAuth token endpoint is asked for a token.
    :returns: the house judging dict plus `host`, `status`, `text` and
        `denied` — True only when the refusal came from the egress policy.

    A denial is never retried and never re-routed. That is the whole contract.

    `headers` and `data` exist so an authenticated API is reached THROUGH this
    function rather than beside it. A second HTTP path would be a second place
    where a policy refusal could be swallowed, retried or routed around, and a
    second place where a refusal fails to reach the allowlist request — the
    bookkeeping only works because there is one door.
    """
    target = str(url or "").strip()
    if not target.startswith(("http://", "https://")):
        return {
            "outcome": FAIL,
            "checked": 0,
            "violations": 1,
            "unmeasured": 0,
            "note": f"{target!r} is not an http(s) URL, so nothing was attempted",
            "host": "",
            "status": None,
            "text": "",
            "denied": False,
        }

    host = _host(target)
    sent = {"User-Agent": _UA}
    sent.update({str(k): str(v) for k, v in (headers or {}).items()})
    request = urllib.request.Request(target, headers=sent, data=data)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(max_bytes)
            text = body.decode("utf-8", "replace")
            # The host answered, so if it was in the ask it no longer belongs
            # there. Retiring it here rather than in the request generator
            # means ordinary use keeps the ask honest.
            note_open(target)
            return {
                "outcome": PASS,
                "checked": 1,
                "violations": 0,
                "unmeasured": 0,
                "note": f"{host} answered {response.status}, {len(body)} bytes read",
                "host": host,
                "status": response.status,
                "text": text,
                "denied": False,
            }
    except urllib.error.HTTPError as error:
        # The host answered and said no. That is OUR bad URL, not the policy's
        # doing, and the two must not print the same. It is also proof the host
        # is reachable, which is what retires it from the ask — a 404 on a bare
        # root is a very common way for a granted host to greet us.
        note_open(target)
        # The error BODY is kept. An API that refuses you usually says why in
        # it, and throwing it away turns a diagnosable refusal into a bare
        # number — MEASURED 2026-08-27, when oauth.reddit.com answered 403 and
        # only the body distinguished "you are blocked" from "your token is
        # wrong", which is the difference between a credential being worth
        # obtaining and not.
        try:
            body = error.read(max_bytes).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - a body we cannot read is not a new failure
            body = ""
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": f"{host} answered {error.code} {error.reason}",
            "host": host,
            "status": error.code,
            "text": body,
            "denied": False,
        }
    except urllib.error.URLError as error:
        reason = str(getattr(error, "reason", error))
        if _DENIAL.search(reason):
            note_denial(target, reason, why_wanted, incidental=incidental)
            return {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "note": (
                    f"{host} is refused by this organisation's egress policy "
                    f"({reason}). Not retried and not routed around: that is the "
                    "policy owner's decision. Recorded — run `wanted()` for the "
                    "list to ask them for."
                ),
                "host": host,
                "status": None,
                "text": "",
                "denied": True,
            }
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"{host} could not be reached: {reason}. Worth retrying.",
            "host": host,
            "status": None,
            "text": "",
            "denied": False,
        }
    except Exception as error:  # noqa: BLE001 - a fetch must not take the chat down
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"{host} failed unexpectedly: {type(error).__name__}: {error}",
            "host": host,
            "status": None,
            "text": "",
            "denied": False,
        }


def reachability(hosts: Any = None, *, why_wanted: str = "") -> dict:
    """Probe hosts now rather than trusting the map in the docstring.

    A reachability map is a measurement with a date on it, and this is how the
    date gets refreshed. Cheap: one HEAD-shaped GET per host.

    :param why_wanted: the question these hosts are being probed FOR. Given, the
        refusals join the allowlist request under that reason. Left empty, this
        is a map refresh — nobody asked for any particular host — and refusals
        are recorded as incidental, out of the ask.

        OBSERVED 2026-08-27, twice: a bulk sweep wrote every refused host into
        the file a human reads to decide what access to grant. Search results
        was the first place, this was the second, and the reason recorded here
        was the literal string "reachability probe", which tells that human
        nothing at all. A host really wanted is promoted into the ask by
        `note_denial` the first time somebody probes it WITH a question, so
        nothing is lost by defaulting to incidental.
    """
    targets = list(hosts) if hosts else _DEFAULT_HOSTS
    asked_for = str(why_wanted or "").strip()
    open_hosts: list[str] = []
    closed: list[str] = []
    other: list[dict] = []
    for host in targets:
        out = fetch(
            f"https://{host}/",
            why_wanted=asked_for or "refreshing the reachability map; nobody asked for this host",
            incidental=not asked_for,
        )
        if out["denied"]:
            closed.append(host)
        elif out["outcome"] in {PASS, FAIL}:
            # FAIL here means the host ANSWERED — 400 or 404 on a bare root is
            # still proof the host is reachable, which is what this measures.
            open_hosts.append(host)
        else:
            other.append({"host": host, "note": out["note"]})

    if not targets:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "no hosts were given, so nothing was probed",
            "open": [],
            "closed": [],
            "unreached": [],
        }

    return {
        "outcome": FAIL if closed else PASS,
        "checked": len(targets),
        "violations": len(closed),
        "unmeasured": len(other),
        "note": (
            f"{len(open_hosts)} open, {len(closed)} refused by policy, "
            f"{len(other)} unreached for other reasons, out of {len(targets)} probed"
        ),
        "open": sorted(open_hosts),
        "closed": sorted(closed),
        "unreached": other,
    }


def wanted() -> dict:
    """The allowlist request, assembled from refusals that actually happened."""
    rows = _read_denied()
    if not rows:
        return {
            "outcome": PASS,
            "checked": 0,
            "violations": 0,
            "unmeasured": 0,
            "note": "no host has been refused yet, so there is nothing to ask for",
            "hosts": [],
            "also_refused": [],
            "granted": [],
            "withdrawn": [],
        }
    # The latest row per host decides. A host recorded open has been granted
    # and is no longer asked for; the rows stay in the file so the history of
    # "asked on this date, granted on that one" can be read back.
    state: dict[str, str] = {}
    for row in rows:
        host = row.get("host", "")
        if host:
            state[host] = str(row.get("state", STATE_REFUSED))
    opened = sorted(h for h, s in state.items() if s == STATE_OPEN)
    withdrawn = sorted(h for h, s in state.items() if s == STATE_UNWANTED)

    by_host: dict[str, dict] = {}
    for row in rows:
        host = row.get("host", "")
        if not host or state.get(host) in (STATE_OPEN, STATE_UNWANTED):
            continue
        kept = by_host.get(host)
        # Two rules, in this order. A host wanted for a real question outranks
        # the same host met by a bulk probe, whichever was written first. And
        # among real questions the LATEST wins, because the file is append-only
        # history and the newest reason is the one written against today's
        # fact base — an old reason can have gone stale under it.
        if kept is None or not row.get("incidental", False):
            by_host[host] = row

    asked = [by_host[h] for h in sorted(by_host) if not by_host[h].get("incidental", False)]
    swept = [by_host[h] for h in sorted(by_host) if by_host[h].get("incidental", False)]

    if not asked:
        # Three ways to have nothing to ask for, and they are not the same
        # thing. Printing one message for all three is how "they granted
        # everything" becomes indistinguishable from "nobody ever asked".
        if opened and not swept:
            note = (
                f"nothing to ask for: all {len(opened)} host(s) that were asked for "
                "have since been granted and now answer. The request is closed."
            )
        elif opened:
            note = (
                f"nothing to ask for: {len(opened)} host(s) asked for have since "
                f"been granted, and the remaining {len(swept)} refused host(s) were "
                "swept up by bulk probes rather than needed for a question."
            )
        else:
            note = (
                f"nothing to ask for: every one of the {len(swept)} refused host(s) "
                "was swept up by a bulk probe, not needed for a question. Listed "
                "under `also_refused` so the refusals are not lost."
            )
        return {
            "outcome": PASS if opened and not swept else UNMEASURED,
            "checked": len(rows),
            "violations": 0,
            "unmeasured": len(swept),
            "note": note,
            "hosts": [],
            "also_refused": swept,
            "granted": opened,
            "withdrawn": withdrawn,
        }
    return {
        "outcome": FAIL,
        "checked": len(rows),
        "violations": len(asked),
        "unmeasured": len(swept),
        "note": (
            f"{len(asked)} host(s) refused by egress policy while answering a real "
            "question; ask the policy owner rather than routing around them."
            + (
                f" A further {len(swept)} host(s) were refused during bulk probes "
                "and are under `also_refused` — they are NOT part of the ask."
                if swept
                else ""
            )
        ),
        "hosts": asked,
        "also_refused": swept,
        "granted": opened,
        "withdrawn": withdrawn,
    }


#: MEASURED 2026-08-27 on this machine. Kept as the default probe list so a
#: caller can ask "is this still true" in one call.
_DEFAULT_HOSTS: tuple[str, ...] = (
    "raw.githubusercontent.com",
    "api.github.com",
    "pypi.org",
    "huggingface.co",
    "cloud.google.com",
    "api.klingai.com",
    "api.fal.ai",
    "docs.bfl.ai",
    "arxiv.org",
    "kling.ai",
    "help.runwayml.com",
    "elevenlabs.io",
)
