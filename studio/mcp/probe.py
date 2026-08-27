"""Ask the vendor's own API what its limits are, by asking for something absurd.

THE IDEA

A vendor's documentation is a statement of intent, written once and left. The
vendor's API is the running system, and it answers today. When the docs are
unreachable — MEASURED 2026-08-27: `docs.bfl.ai`, `kling.ai`,
`help.runwayml.com`, `elevenlabs.io`, `platform.openai.com` all refused, while
`api.klingai.com` and `api.fal.ai` answered — the API is not a consolation
prize. It is the better source of the two for a numeric limit.

So: send a request asking for a value no system could honour, and read the
refusal. `{"duration": 999999}` comes back as a validation error naming the
real ceiling, and that ceiling was stated by the vendor's own code.

WHY THIS CANNOT QUIETLY BECOME A PAID GENERATION

That is the one real danger here, and it is guarded mechanically rather than
promised in prose. A probe value must be at or past `ABSURD_MIN` — a million.
No video model renders a million seconds, no image model returns a million
pixels of width; a request carrying one cannot be fulfilled, so it cannot be
billed as a fulfilment. A value below the sentinel is refused BEFORE the
request is built, and the refusal says why.

This is the same shape as the house rule about counters before knobs: the
guard exists so that "it should not have charged" is a property somebody can
test rather than a thing somebody believed.

WHAT A PROBE IS WORTH, STATED HONESTLY

One probe observes one account, one region, one moment. A limit it reports may
belong to a billing plan rather than to the model, which is exactly why the
`probe` tier sits BELOW `vendor` in `facts.py` and above everything written
from the outside. Every probe fact carries the request it sent and the
response it got, so the confound stays visible and anybody can re-run it.

THE KEY NEVER TRAVELS THROUGH AN ARGUMENT

It is read from the environment inside this module. A key passed as a
parameter ends up in a call log, a transcript and a traceback; a key read from
`os.environ` ends up in none of those.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date
from typing import Any

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio.mcp.fetch import TIMEOUT_SECONDS, _DENIAL, _host, note_denial

__all__ = ["probe_limit", "ABSURD_MIN", "KEY_ENV"]

#: CHOSEN, and it is the safety constant of this module. A probe value must be
#: at least this large. A million seconds is 11 days of video and a million
#: pixels of width is not a format; no vendor can satisfy either, so no vendor
#: can charge for satisfying it. Lowering this is how a probe turns into a bill.
ABSURD_MIN = 1_000_000

#: Environment variables searched for a key, in order. Never an argument.
#:
#: `KLING_KEY` is first because that is what this environment actually sets.
#: OBSERVED 2026-08-27: this table looked for `KLING_API_KEY` and `KLINGAI_API_KEY`
#: only, while the live variable was `KLING_KEY` — so the probe reported "no API
#: key" with a working key sitting beside it. A credential lookup that guesses
#: names must list the names somebody used, not the names somebody expected.
KEY_ENV: dict[str, tuple[str, ...]] = {
    "api.klingai.com": ("KLING_KEY", "KLING_API_KEY", "KLINGAI_API_KEY"),
    "api.fal.ai": ("FAL_KEY", "FAL_API_KEY"),
}


def _key_for(host: str) -> tuple[str, str]:
    """(key, which env var it came from). Empty strings when nothing is set."""
    for name in KEY_ENV.get(host, ()):
        value = os.environ.get(name, "").strip()
        if value:
            return value, name
    return "", ""


def probe_limit(
    url: str,
    field: str,
    absurd_value: Any,
    *,
    payload: dict | None = None,
    why_wanted: str = "",
) -> dict:
    """Ask an API for an impossible value and read what it says the real one is.

    :param field: the request field being probed, e.g. "duration".
    :param absurd_value: what to put there. A number must be at least
        `ABSURD_MIN`; a string must contain "absurd-probe". Anything that could
        plausibly be honoured is refused before a request is built.
    :param payload: the rest of the request body. The probed field is written
        into it here, so a caller cannot accidentally send a valid one.
    :param why_wanted: which stuck claim this is meant to settle.

    :returns: the house judging dict plus `sent`, `status`, `response` and
        `suggested_fact` — a ready row for `advice.record` at `probe` tier,
        which a human still reads before it is written.

    Three outcomes. `fail` means the guard refused, or the URL is wrong.
    `could not measure` means no key, or the policy refused the host. `pass`
    means the API answered — including, and especially, when it answered with
    a validation error, because that error is the measurement.
    """
    target = str(url or "").strip()
    if not target.startswith("https://"):
        return _bad(f"{target!r} is not an https URL; nothing was sent")

    if not str(field or "").strip():
        return _bad("no field was named, so there is nothing to probe")

    # The guard. It runs before a request object exists.
    if isinstance(absurd_value, bool) or not isinstance(absurd_value, (int, float, str)):
        return _bad(
            f"a probe value must be a number or a string, not {type(absurd_value).__name__}"
        )
    if isinstance(absurd_value, (int, float)):
        if absurd_value < ABSURD_MIN:
            return _bad(
                f"{absurd_value} is below the absurdity floor of {ABSURD_MIN}, so a "
                "vendor could plausibly honour it and charge for it. Nothing was "
                "sent. Raise the value; do not lower the floor."
            )
    elif "absurd-probe" not in absurd_value:
        return _bad(
            "a string probe value must contain 'absurd-probe' so it cannot be a "
            "request somebody meant. Nothing was sent."
        )

    host = _host(target)
    key, key_from = _key_for(host)
    if not key:
        names = ", ".join(KEY_ENV.get(host, ())) or "(none configured for this host)"
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"no API key in the environment for {host}. Looked at: {names}. "
                "Nothing was sent, and no limit was learned."
            ),
            "sent": None,
            "status": None,
            "response": "",
            "suggested_fact": None,
        }

    body = dict(payload or {})
    body[field] = absurd_value
    encoded = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        target,
        data=encoded,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            text = response.read(20_000).decode("utf-8", "replace")
            status = response.status
    except urllib.error.HTTPError as error:
        # This is the good path. A 4xx carrying a validation message IS the
        # measurement; treating it as a failure would throw away the answer.
        text = error.read(20_000).decode("utf-8", "replace")
        status = error.code
    except urllib.error.URLError as error:
        reason = str(getattr(error, "reason", error))
        if _DENIAL.search(reason):
            note_denial(target, reason, why_wanted or f"probe {field} on {host}")
            return {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "note": (
                    f"{host} is refused by this organisation's egress policy "
                    f"({reason}). Recorded for the allowlist request; not retried."
                ),
                "sent": None,
                "status": None,
                "response": "",
                "suggested_fact": None,
            }
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"{host} could not be reached: {reason}",
            "sent": None,
            "status": None,
            "response": "",
            "suggested_fact": None,
        }

    # The request is echoed back WITHOUT the Authorization header, which never
    # leaves this function.
    sent = {"url": target, "method": "POST", "body": body}

    return {
        "outcome": PASS,
        "checked": 1,
        "violations": 0,
        "unmeasured": 0,
        "note": (
            f"{host} answered {status} to {field}={absurd_value!r}. The refusal text "
            "is the measurement; read it and decide what limit it states before "
            "recording anything."
        ),
        "sent": sent,
        "status": status,
        "response": text,
        "key_from": key_from,
        "suggested_fact": {
            "model": "",
            "attribute": field,
            "value": "<read it out of the response yourself>",
            "source_url": target,
            "tier": "probe",
            "stated_on": date.today().isoformat(),
            "note": (f"probe: sent {field}={absurd_value!r}, got {status}. Response: {text[:300]}"),
        },
    }


def _bad(note: str) -> dict:
    return {
        "outcome": FAIL,
        "checked": 0,
        "violations": 1,
        "unmeasured": 0,
        "note": note,
        "sent": None,
        "status": None,
        "response": "",
        "suggested_fact": None,
    }
