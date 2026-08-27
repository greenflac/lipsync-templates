"""The MCP server the owner talks to in chat. Nine tools, two of which write.

RUN IT

    python -m studio.mcp.server          # stdio, which is what Claude Code speaks

`.mcp.json` at the repo root registers it, so it appears in the chat with no
further setup.

THE TOOLS THAT WRITE

`record_model_fact` appends to `studio/knowledge/model_facts.jsonl`, and
`fetch_url` appends a refused host to `denied_hosts.jsonl` so the allowlist
request assembles itself. Everything else reads. That asymmetry is deliberate and worth stating in the tool list a
model sees: an assistant deciding on its own to "tidy" the knowledge base is a
worse outcome than a stale one, because a stale claim announces its age and a
rewritten one does not.

WHAT EVERY TOOL RETURNS

The house judging dict — `outcome` of `pass` / `fail` / `could not measure`,
plus `checked`, `violations` and `unmeasured` — rendered as JSON. The counts
travel with the verdict on purpose: zero violations out of zero checks is not
a success, and a caller that only reads `outcome` can still be shown the
denominator.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from studio import knowledge
from studio.mcp import advice, contract, fetch, probe
from studio.mcp import lipsync_prompt as lp

server = MCPServer(
    name="lipsync-studio",
    instructions=(
        "Two jobs. (1) Advise on what a generation model can and cannot do: call "
        "`model_advice` FIRST, before answering from memory, because model limits "
        "change monthly and this base records who said what and when. When it "
        "reports a gap or a stale claim, search the web yourself and call "
        "`record_model_fact` with the value, the source URL, the source tier and "
        "the date the source stated it. Prefer a VENDOR artefact over an article: "
        "`fetch_url` reaches raw.githubusercontent.com, api.github.com, pypi.org, "
        "huggingface.co and cloud.google.com, so an SDK source or an OpenAPI spec "
        "is readable. For a numeric limit whose documentation host is blocked, use "
        "`probe_model_limit` — the vendor API's own refusal is the measurement, and "
        "it records at `probe` tier. A host the policy refuses is reported, never "
        "routed around: no mirror, no cache, no read-through proxy. "
        "(2) Write lipsync prompts: call `write_lipsync_prompt`. It fills "
        "the engine's card from the owner's words and the corpus, and refuses "
        "with a question when a slot is unresolved. Do not answer the question "
        "on the owner's behalf — ask them."
    ),
)

_INDEX: Any = None


def _index() -> Any:
    """The corpus index, built once per process. 4601 rows is not a per-call cost.

    Typed `Any` because `studio/knowledge.py` is shadowed for a type checker by
    the same-named directory beside it; see the note in `lipsync_prompt.py`.
    """
    global _INDEX
    if _INDEX is None:
        _INDEX = knowledge.build_index()  # type: ignore[attr-defined]
    return _INDEX


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


@server.tool()
def model_advice(model: str, attribute: str = "") -> str:
    """What is known about a generation model, with every source and its date.

    Call this before answering any question about what a model can do. Returns
    the registry's conservative answer, every recorded claim with its tier and
    URL, the known failure modes, and — as `fail` — any attribute whose sources
    disagree. It never resolves a disagreement for you.

    :param model: e.g. "kling-3.0", "veo-3.1", "flux-2".
    :param attribute: one attribute such as "max_seconds"; empty for everything.
    """
    return _json(advice.advise(model, attribute))


@server.tool()
def record_model_fact(
    model: str,
    attribute: str,
    value: str,
    source_url: str,
    tier: str,
    stated_on: str,
    note: str = "",
    fix: str = "",
) -> str:
    """Write one thing you found on the web into the knowledge base.

    This is the only tool that writes. Use it after searching, when
    `model_advice` showed a gap, a contradiction or a stale claim.

    :param tier: "vendor" (the vendor's own doc or release), "paper" (arXiv or
        a venue), "benchmark" (an evaluation with a published method) or "blog"
        (everything else). Ten blogs repeating each other stay one blog.
    :param stated_on: the ISO date THE SOURCE stated it (YYYY-MM-DD), not
        today. Dating an old article as today is how a stale claim looks fresh.
    :param fix: for a failure mode, what to do about it.
    """
    return _json(
        advice.record(
            model,
            attribute,
            value,
            source_url,
            tier,
            stated_on,
            note=note,
            fix=fix,
        )
    )


@server.tool()
def stale_model_facts(days: int = 90) -> str:
    """Which recorded claims are old enough to be worth re-checking on the web."""
    return _json(advice.stale(days=days))


@server.tool()
def write_lipsync_prompt(intent: str) -> str:
    """Write a lipsync style prompt from the owner's words plus the corpus.

    The prompt describes the LOOK only — the subject comes from the user's
    photo and the driving clip, and naming it breaks the engine's contract.

    Returns `could not measure` with a question when a card slot cannot be
    filled from what the owner said or from what the corpus agrees on. Put that
    question to the owner; do not answer it for them.

    :param intent: the owner's own words, e.g. "muted ivory and slate,
        low-key light, matte".
    """
    found = knowledge.retrieve(  # type: ignore[attr-defined]
        intent, k=lp.DEFAULT_K, index=_index()
    )
    result = lp.write(intent, found.get("examples", ()))
    result["retrieval"] = {
        "outcome": found["outcome"],
        "examples": len(found.get("examples", ())),
        "below_floor": found.get("below_floor"),
        "note": found.get("note"),
    }
    return _json(result)


@server.tool()
def check_lipsync_prompt(prompt: str) -> str:
    """Judge any lipsync prompt against the engine's contract, from any source.

    Three checks: the forbidden subject zone, the word band and the clause
    band. A violation is reported, never repaired — trimming a prompt into
    shape would report `pass` for text the owner never approved.
    """
    return _json({**contract.gate(prompt), "bands": contract.BANDS})


@server.tool()
def fetch_url(url: str, why_wanted: str = "") -> str:
    """Fetch a page or a file from the web through this session's egress policy.

    Use it to read a vendor's own artefact instead of somebody's article about
    it. Measured 2026-08-27, these answer: raw.githubusercontent.com,
    api.github.com, pypi.org, huggingface.co, cloud.google.com,
    api.klingai.com, api.fal.ai. Vendor SDK source and OpenAPI specs on GitHub
    are vendor-tier material and are reachable.

    A host the policy refuses comes back `could not measure` with `denied:
    true` and is recorded for the allowlist request. Do NOT look for a mirror,
    a cache or a read-through proxy for it — report it instead.

    :param why_wanted: what you were trying to learn. It is carried into the
        denial record, so the allowlist request explains itself.
    """
    return _json(fetch.fetch(url, why_wanted=why_wanted))


@server.tool()
def blocked_hosts() -> str:
    """The allowlist request, assembled from hosts the policy actually refused.

    Hand this to whoever owns the egress policy. Every row is a host something
    real needed, with the reason it was wanted.
    """
    return _json(fetch.wanted())


@server.tool()
def reachable_hosts() -> str:
    """Re-probe which documentation and API hosts answer right now.

    The reachability map is a measurement with a date on it; this refreshes the
    date instead of trusting a comment.
    """
    return _json(fetch.reachability())


@server.tool()
def probe_model_limit(
    url: str, field: str, absurd_value: str, payload_json: str = "{}", why_wanted: str = ""
) -> str:
    """Ask a vendor's API for an impossible value and read the real limit out of its refusal.

    This is how a numeric limit gets a `probe`-tier source when the vendor's
    documentation host is blocked. The refusal text IS the measurement.

    The value must be absurd — a number at or above 1000000, or a string
    containing "absurd-probe". Anything a vendor could plausibly honour is
    refused before a request is built, because a honoured request is a billed
    one. Do not lower that floor; raise the value.

    Returns `suggested_fact` — a draft row for `record_model_fact`. Read the
    response and write the real value into it yourself; do not record the
    draft as it stands.

    :param absurd_value: sent as a number when it parses as one, else as a string.
    :param payload_json: the rest of the request body, as JSON.
    """
    try:
        payload = json.loads(payload_json or "{}")
    except ValueError as error:
        return _json(
            {
                "outcome": "fail",
                "checked": 0,
                "violations": 1,
                "unmeasured": 0,
                "note": f"payload_json is not JSON: {error}",
            }
        )
    try:
        value: Any = float(absurd_value) if "." in absurd_value else int(absurd_value)
    except ValueError:
        value = absurd_value
    return _json(probe.probe_limit(url, field, value, payload=payload, why_wanted=why_wanted))


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
