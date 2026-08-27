"""The MCP server the owner talks to in chat. Five tools, no side effects but one.

RUN IT

    python -m studio.mcp.server          # stdio, which is what Claude Code speaks

`.mcp.json` at the repo root registers it, so it appears in the chat with no
further setup.

THE ONE TOOL THAT WRITES

`record_model_fact` appends to `studio/knowledge/model_facts.jsonl`. Everything
else reads. That asymmetry is deliberate and worth stating in the tool list a
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
from studio.mcp import advice, contract
from studio.mcp import lipsync_prompt as lp

server = MCPServer(
    name="lipsync-studio",
    instructions=(
        "Two jobs. (1) Advise on what a generation model can and cannot do: call "
        "`model_advice` FIRST, before answering from memory, because model limits "
        "change monthly and this base records who said what and when. When it "
        "reports a gap or a stale claim, search the web yourself and call "
        "`record_model_fact` with the value, the source URL, the source tier and "
        "the date the source stated it — this server cannot reach the web, you "
        "can. (2) Write lipsync prompts: call `write_lipsync_prompt`. It fills "
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


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
