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
        "first_seen": date.today().isoformat(),
    }
    DENIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    # A host first met by a bulk probe and later actually needed gets a second
    # row, so it can be promoted into the ask. Without this, the order two
    # calls happened in would decide whether a host the owner needs is ever
    # asked for.
    known = {r.get("host"): bool(r.get("incidental", False)) for r in _read_denied()}
    fresh = host not in known
    promoted = not fresh and known[host] and not incidental
    if fresh or promoted:
        with DENIED_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"recorded": fresh or promoted, "host": host}


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
    url: str, *, why_wanted: str = "", max_bytes: int = 400_000, incidental: bool = False
) -> dict:
    """GET one URL through the configured proxy. Three outcomes, no fallbacks.

    :param why_wanted: what this fetch was for. Carried into the denial record
        when the policy refuses, so the allowlist request explains itself.
    :param incidental: True when this host is being swept by a bulk probe
        rather than actually wanted; see `note_denial`. A refusal is recorded
        either way — this only keeps it out of the ask.
    :returns: the house judging dict plus `host`, `status`, `text` and
        `denied` — True only when the refusal came from the egress policy.

    A denial is never retried and never re-routed. That is the whole contract.
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
    request = urllib.request.Request(target, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(max_bytes)
            text = body.decode("utf-8", "replace")
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
        # doing, and the two must not print the same.
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": f"{host} answered {error.code} {error.reason}",
            "host": host,
            "status": error.code,
            "text": "",
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


def reachability(hosts: Any = None) -> dict:
    """Probe hosts now rather than trusting the map in the docstring.

    A reachability map is a measurement with a date on it, and this is how the
    date gets refreshed. Cheap: one HEAD-shaped GET per host.
    """
    targets = list(hosts) if hosts else _DEFAULT_HOSTS
    open_hosts: list[str] = []
    closed: list[str] = []
    other: list[dict] = []
    for host in targets:
        out = fetch(f"https://{host}/", why_wanted="reachability probe")
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
        }
    by_host: dict[str, dict] = {}
    for row in rows:
        host = row.get("host", "")
        if not host:
            continue
        kept = by_host.get(host)
        # A host wanted for a real question outranks the same host met by a
        # bulk probe, whichever row was written first.
        if kept is None or (
            bool(kept.get("incidental", False)) and not row.get("incidental", False)
        ):
            by_host[host] = row

    asked = [by_host[h] for h in sorted(by_host) if not by_host[h].get("incidental", False)]
    swept = [by_host[h] for h in sorted(by_host) if by_host[h].get("incidental", False)]

    if not asked:
        return {
            "outcome": UNMEASURED,
            "checked": len(rows),
            "violations": 0,
            "unmeasured": len(swept),
            "note": (
                f"nothing to ask for: every one of the {len(swept)} refused host(s) "
                "was swept up by a bulk probe, not needed for a question. Listed "
                "under `also_refused` so the refusals are not lost."
            ),
            "hosts": [],
            "also_refused": swept,
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
