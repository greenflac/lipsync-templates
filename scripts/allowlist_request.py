"""Render the allowlist request: every host we need, with the question it blocks.

WHY THIS IS A SCRIPT AND NOT A DOCUMENT

A hand-typed list of hosts goes stale the day a host opens, and nobody notices
because nothing re-checks it. This probes each host NOW, records the refusal
with its own reason, and renders the request from what actually happened. Run
it again and a host that has since opened drops off by itself.

Rules it obeys:

- A closed host is never routed around (C3). This asks; it does not work around.
- Each entry carries the QUESTION it blocks, not just a hostname. "We need
  arxiv.org" is a weaker request than "10 of our paper-tier facts cite arxiv
  and not one of them has been read".
- Hosts swept up by bulk probes stay out (`incidental`); only what is asked
  for here enters the ask.

Run:  python scripts/allowlist_request.py            # probe and render
      python scripts/allowlist_request.py --render   # render from what is recorded
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.mcp import fetch  # noqa: E402

OUT_PATH = Path(__file__).resolve().parents[1] / "docs" / "ALLOWLIST_REQUEST.md"

#: Hosts this environment already permits, MEASURED 2026-08-27. Re-probed on
#: every run rather than trusted: the point of listing them is so nobody is
#: asked for access they already have, and a stale list of those is worse than
#: none.
ALREADY_OPEN: tuple[str, ...] = (
    "aiplatform.googleapis.com",
    "api.fal.ai",
    "api.github.com",
    "api.klingai.com",
    "cloud.google.com",
    "customsearch.googleapis.com",
    "discoveryengine.googleapis.com",
    "files.pythonhosted.org",
    "generativelanguage.googleapis.com",
    "github.com",
    "huggingface.co",
    "pypi.org",
    "raw.githubusercontent.com",
    "searchapi.api.cloud.yandex.net",
    "storage.googleapis.com",
)

#: (priority group, host, the question it blocks). Ordered as it should be read:
#: the narrowing first, then what settles a contradiction, then new capability.
#:
#: Every reason below points at something recorded in this repository — a
#: contested attribute, an unread tier, a corpus with one provenance. A reason
#: that cannot be checked against the base does not belong here.
WANTED: tuple[tuple[str, str, str], ...] = (
    # ---- 1. A narrowing of an existing grant. Cheapest thing to say yes to.
    (
        "1. narrowing",
        "docs.cloud.google.com",
        "Veo 3.1 duration and negativePrompt. The PARENT cloud.google.com is "
        "already permitted and open, so this grants no new organisation — it is "
        "the documentation subdomain of a host you have already allowed.",
    ),
    # ---- 2. Hosts that settle a contradiction we cannot settle any other way.
    (
        "2. settles a contradiction",
        "kling.ai",
        "kling-3.0.max_seconds is CONTESTED in the fact base: 15 (Kuaishou's own "
        "investor release) against 10 (a blog). MEASURED: the probe channel "
        "reveals nothing on Kling — duration, aspect_ratio, mode and model_name "
        "all return the identical code 1201 'value is invalid' and never name the "
        "allowed set. The vendor's own page is the only remaining route.",
    ),
    (
        "2. settles a contradiction",
        "help.runwayml.com",
        "runway-gen-4.5.max_resolution is CONTESTED: 720p against 4K, and the 4K "
        "claim comes from a review whose own credit table implies 4K is a paid "
        "tier. Billing a customer against the wrong one is a real cost.",
    ),
    (
        "2. settles a contradiction",
        "ir.kuaishou.com",
        "Kuaishou investor relations — the source of the '15 seconds' side of the "
        "Kling contradiction above. Currently vendor tier and NOT read.",
    ),
    # ---- 3. Vendor pages behind facts nobody has ever opened.
    (
        "3. vendor pages nobody has read",
        "docs.bfl.ai",
        "Flux 2. Three recorded claims cite it — prompt_rule_edit, "
        "expands_internally, architecture — and all three are marked "
        "read_directly=false: known only through somebody else's summary.",
    ),
    (
        "3. vendor pages nobody has read",
        "docs.byteplus.com",
        "Seedance 2.0 and OmniHuman 1.5: override_parameter (camera_fixed beats "
        "any camera adjective) and expands_internally. Both unread.",
    ),
    (
        "3. vendor pages nobody has read",
        "elevenlabs.io",
        "The professional voice-clone CONSENT GATE and the training-audio "
        "minutes. This is a legal gate in a product that clones voices; it is "
        "recorded at vendor tier and has never been read.",
    ),
    (
        "3. vendor pages nobody has read",
        "help.elevenlabs.io",
        "The other half of the same consent-gate answer: can a clone be made of "
        "someone else's voice, and on what evidence of consent.",
    ),
    (
        "3. vendor pages nobody has read",
        "ai.google.dev",
        "Google's own model documentation, including the Gemini grounding API "
        "this agent's web search runs on. The API host is open; the docs are not.",
    ),
    (
        "3. vendor pages nobody has read",
        "platform.openai.com",
        "sora-2 is recorded as scheduled to stop 2026-09-24 and the registry "
        "returns `fail` after that date rather than letting a paid call 404. That "
        "date is load-bearing and second-hand.",
    ),
    # ---- 4. The paper rung, which is entirely unread.
    (
        "4. the paper rung",
        "arxiv.org",
        "10 of the 47 recorded facts are paper tier and cite arxiv.org. NOT ONE "
        "has been read — every one is somebody's summary of a paper. The "
        "Kling-Avatar paper is the only paper-tier source for the avatar route.",
    ),
    # ---- 5. New capability: prompts with the results they actually produced.
    (
        "5. community corpora",
        "civitai.com",
        "Public REST API at /api/v1/. The /images endpoint returns user-submitted "
        "images WITH their generation metadata — the prompt-and-result pairing "
        "this project has none of. Today the corpus is 4601 rows under a single "
        "provenance label, and no prompt this package writes has ever been proven "
        "by a generation. Requested by the owner by name.",
    ),
    (
        "5. community corpora",
        "api.civitai.com",
        "The same API on its own subdomain.",
    ),
    (
        "5. community corpora",
        "image.civitai.com",
        "The image CDN. Needed to LOOK at a result rather than only read its "
        "metadata — a prompt that scores well and looks wrong is the failure this "
        "catches.",
    ),
    (
        "5. community corpora",
        "www.reddit.com",
        "r/comfyui: workflows posted together with the results they produced, and "
        "the community's own account of what went wrong. Requested by the owner "
        "by name. NOTE, UNVERIFIED: Reddit's free Data API tier reportedly "
        "prohibits commercial use without their approval, so this host may need a "
        "commercial agreement independently of the egress policy.",
    ),
    ("5. community corpora", "reddit.com", "The same site without the www prefix."),
    (
        "5. community corpora",
        "oauth.reddit.com",
        "The authenticated Data API endpoint. The free tier's 100 queries/minute "
        "applies only to OAuth clients; without it the limit is 10.",
    ),
    (
        "5. community corpora",
        "old.reddit.com",
        "The same content as server-rendered HTML rather than a JavaScript app — "
        "cheaper and steadier to parse than the modern front end.",
    ),
    # ---- 6. Platforms already cited by the fact base.
    (
        "6. platforms already cited",
        "fal.ai",
        "FAL_KEY is set and api.fal.ai is open, but the model pages are not, so "
        "the platform whose API we can call is one we cannot read. "
        "wan-2.6-flash.prompt_rule_i2v cites it.",
    ),
    (
        "6. platforms already cited",
        "wavespeed.ai",
        "Four recorded facts cite it — best_for for Kling, Veo and Seedance, and "
        "wan-2.6-flash.max_seconds. All four cite the bare site root, which is a "
        "separate weakness: nobody can go and check them.",
    ),
)


def main() -> int:
    render_only = "--render" in sys.argv[1:]

    if not render_only:
        print(f"probing {len(WANTED)} host(s); a refusal is the point, not a failure\n")
        for _group, host, why in WANTED:
            out = fetch.fetch(f"https://{host}/", why_wanted=why, incidental=False)
            state = "REFUSED" if out["denied"] else out["outcome"]
            print(f"  {state:16} {host}")

    asked = fetch.wanted()
    by_host = {row["host"]: row for row in asked.get("hosts", [])}

    # Measured, not remembered: a request that lists a host which is already
    # open wastes the reader's time and makes the rest look unchecked.
    print("\nre-measuring what is already open")
    live = fetch.reachability(ALREADY_OPEN)
    open_now = sorted(live.get("open", []))
    shut_now = sorted(live.get("closed", []))

    lines = [
        "# Allowlist request",
        "",
        "**Generated by `scripts/allowlist_request.py` — do not hand-edit.**",
        "Re-run it and a host that has since opened drops off by itself.",
        "",
        "Every host below was probed and refused by the egress proxy "
        "(`Tunnel connection failed: 403`). None was routed around: no mirror, "
        "no cache, no archive copy, no read-through proxy.",
        "",
        f"**{len(by_host)} host(s) asked for.** "
        f"{len(asked.get('also_refused', []))} further host(s) were refused during "
        "bulk probes and are deliberately NOT part of this request.",
        "",
        "## The list, to paste",
        "",
        "```",
        *sorted(by_host),
        "```",
        "",
        "Each one is justified below, grouped so the list can be cut at any "
        "group boundary and still make sense. The groups are ordered by how "
        "cheap they are to say yes to, not by how much we want them.",
        "",
        "## Already open — do not add these",
        "",
        f"Re-measured when this file was generated: {len(open_now)} of "
        f"{len(ALREADY_OPEN)} still answer.",
        "",
        "```",
        *open_now,
        "```",
        "",
    ]
    if shut_now:
        lines += [
            "**Regressed** — these used to answer and no longer do, which is worth "
            "knowing before anything is granted:",
            "",
            "```",
            *shut_now,
            "```",
            "",
        ]

    seen_group = ""
    for group, host, _why in WANTED:
        row = by_host.get(host)
        if row is None:
            continue
        if group != seen_group:
            lines += [f"## {group[3:].capitalize()}", ""]
            seen_group = group
        lines += [f"### `{host}`", "", row["why_wanted"], ""]

    extra = [h for h in sorted(by_host) if h not in {w[1] for w in WANTED}]
    if extra:
        lines += ["## Recorded earlier, still wanted", ""]
        for host in extra:
            lines += [f"### `{host}`", "", by_host[host]["why_wanted"], ""]

    lines += [
        "## Not part of this request",
        "",
        "Hosts refused while a bulk probe swept past them — search results being "
        "tagged with whether they open, or the reachability map being re-dated. "
        "Nobody asked for these; they are listed so no refusal is lost.",
        "",
        ", ".join(f"`{row['host']}`" for row in asked.get("also_refused", [])) or "none",
        "",
    ]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{len(by_host)} host(s) in the ask -> {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
