"""Whose page is this? The tier ladder's first rung, decided by the URL.

The owner's rule, 2026-08-27:

    1. the model vendor's own URL
    2. specialised portals for exchanging artifacts, prompts and the like
    3. blogs and everything else

Tiering by WHOSE PAGE IT IS rather than by how well it is written. The middle
rung was missing and it mattered: measured over the 47 recorded facts, the
`blog` tier held **9 vendor pages** (kling.ai, docs.bfl.ai, help.runwayml.com,
docs.byteplus.com, cloud.google.com, bfl.ai) and **11 platform pages**
(wavespeed.ai ×4, piapi.ai ×2, evolink.ai, apiframe.ai, fal.ai, gaga.art,
atlascloud.ai) alongside genuine press. One rung was doing three jobs.

WHY A PORTAL IS NOT A BLOG

A platform that RUNS the model publishes what its own API accepts. That is a
statement about a running system, checkable against a request, and it is a
different kind of claim from an article describing the model from outside. It
is still below the vendor, because a platform exposes its own configuration —
its ceiling may be its plan rather than the model's.

WHY THE MODEL IS PART OF THE QUESTION

`kling.ai` is the vendor for `kling-3.0` and a competitor writing about
`veo-3.1`. A host alone cannot answer "is this the vendor"; the pair (model,
host) can. Nothing in the current base cites a rival vendor, and this is here
so that stays true as it grows.

WHY PATHS APPEAR AND NOT ONLY HOSTS

`github.com/Wan-Video/` is Alibaba's own repository for Wan; `github.com/
Vchitect/RAPO` is a paper's code. Same host, different owners. Where a host is
shared, the entry carries the path prefix that identifies the owner.

WHAT THIS FILE IS NOT

It is not a reachability map — see `studio/mcp/fetch.py` for that, and note
that most of the vendor hosts below are refused by this environment's egress
policy. Being the vendor's URL and having been read are different questions,
and `Fact.read_directly` answers the second one.
"""

from __future__ import annotations

import re

__all__ = [
    "BLOG_PATH_SEGMENTS",
    "PORTAL_SOURCES",
    "VENDOR_SOURCES",
    "classify",
    "vendor_sources_for",
    "host_of",
]

#: CHOSEN by reading each source URL already in `model_facts.jsonl` on
#: 2026-08-27 and asking "who controls this page". Entries are `host` or
#: `host/path-prefix`; a prefix is used only where the host is shared.
#:
#: Keyed by MODEL FAMILY, not by model id: being the vendor is a relation
#: between a page and a model, but the vendor does not change when the version
#: does. Keyed by version, this table locked every unreleased version out of
#: the first rung until somebody remembered to edit it — OBSERVED 2026-08-27,
#: when the blind control set recorded a `deepmind.google` claim about `veo-3`
#: and was refused because only `veo-3.1` was listed. A rule that needs an edit
#: per version is a rule that will be wrong by the next release.
#:
#: A family matches a model id exactly, or up to a `-` or `.` separator, so
#: `wan` claims `wan-2.6-flash` and not `wandering-model`. Longest match wins,
#: so a family can be split later if two versions really do change hands.
VENDOR_SOURCES: dict[str, tuple[str, ...]] = {
    "kling": (
        "kling.ai",
        "klingai.com",
        "api.klingai.com",
        "app.klingai.com",
        "ir.kuaishou.com",
    ),
    "flux": ("bfl.ai", "docs.bfl.ai", "api.bfl.ai", "blackforestlabs.ai"),
    "runway-gen": ("runwayml.com", "help.runwayml.com", "docs.dev.runwayml.com"),
    "seedance": ("docs.byteplus.com", "byteplus.com", "seed.bytedance.com"),
    "omnihuman": ("docs.byteplus.com", "byteplus.com", "seed.bytedance.com"),
    "veo": ("cloud.google.com", "docs.cloud.google.com", "ai.google.dev", "deepmind.google"),
    "sora": ("openai.com", "platform.openai.com", "help.openai.com"),
    "wan": ("github.com/Wan-Video/", "wan.video", "tongyi.aliyun.com"),
    "elevenlabs": ("elevenlabs.io", "help.elevenlabs.io", "docs.elevenlabs.io"),
}

#: CHOSEN the same way. A portal here is a platform that RUNS models or hosts
#: the artifacts people made with them — it publishes what its own API takes,
#: or the prompts and results themselves. An aggregator that merely resells API
#: access still qualifies: what it documents is a running endpoint.
#:
#: `huggingface.co`, `replicate.com` and `civitai.com` are listed although
#: nothing cites them yet; they are the canonical shape of this rung, and a
#: table that only lists what has already been seen teaches nobody what belongs.
#: `reddit.com/r/comfyui/` and not `reddit.com`: a subreddit where people post
#: workflows with the results they got is the middle rung; the rest of Reddit
#: is a forum. This is what the path prefix is for. Add a sibling community the
#: same way — one line, `reddit.com/r/<name>/`.
PORTAL_SOURCES: tuple[str, ...] = (
    "apiframe.ai",
    "atlascloud.ai",
    "civitai.com",
    "evolink.ai",
    "fal.ai",
    "gaga.art",
    "huggingface.co",
    "openart.ai",
    "piapi.ai",
    "prompthero.com",
    "reddit.com/r/comfyui/",
    "old.reddit.com/r/comfyui/",
    "replicate.com",
    "wavespeed.ai",
)

#: A portal's own writing is writing, not its API. `atlascloud.ai/blog/tips/
#: kling-ai-video-length-limit` is an article that happens to sit on a platform,
#: and it earns the platform's rung no more than a vendor's press page earns a
#: measurement. Matched as a whole path segment, so `/blogging-api/` is not one.
#:
#: MEASURED: 1 of the 11 portal URLs in the base is such a page.
BLOG_PATH_SEGMENTS: frozenset[str] = frozenset(
    {"blog", "blogs", "news", "press", "review", "reviews"}
)

_HOST = re.compile(r"https?://([^/:?#]+)", re.I)


def host_of(url: str) -> str:
    """The host, lowercased and without a leading `www.`. "" when not a URL."""
    match = _HOST.match(str(url or "").strip())
    if not match:
        return ""
    host = match.group(1).lower()
    return host[4:] if host.startswith("www.") else host


def _path_of(url: str) -> str:
    text = str(url or "").strip()
    match = _HOST.match(text)
    if not match:
        return ""
    return text[match.end() :].split("?", 1)[0].split("#", 1)[0]


def _matches(url: str, entry: str) -> bool:
    """Does `url` sit under `entry`, which is a host or a host/path-prefix?"""
    host, _, prefix = entry.partition("/")
    if host_of(url) != host.lower():
        return False
    if not prefix:
        return True
    return _path_of(url).lstrip("/").lower().startswith(prefix.lower())


def vendor_sources_for(model: str) -> tuple[str, ...]:
    """The pages this model's own vendor controls, by family. () when unknown.

    Longest family wins, so a more specific key added later overrides a broader
    one without the broader one having to be touched.
    """
    name = str(model or "").strip().lower()
    if not name:
        return ()
    best = ""
    for family in VENDOR_SOURCES:
        low = family.lower()
        if name == low or name.startswith(low + "-") or name.startswith(low + "."):
            if len(low) > len(best):
                best = low
    return VENDOR_SOURCES[best] if best else ()


def classify(model: str, url: str, *, vendor_tier: str, portal_tier: str, blog_tier: str) -> str:
    """Which rung this URL sits on for this model: vendor, portal, or blog.

    The tiers are passed in rather than imported so that this module holds the
    table and `facts.py` holds the ladder; one name for the ladder, one name
    for who owns what, and no second copy of either.

    Anything not named in a table is `blog` — that is what "and everything
    else" means, and an unknown host is exactly the case the third rung is for.
    """
    if not host_of(url):
        return blog_tier
    for entry in vendor_sources_for(model):
        if _matches(url, entry):
            return vendor_tier
    for entry in PORTAL_SOURCES:
        if _matches(url, entry):
            segments = {s for s in _path_of(url).lower().split("/") if s}
            return blog_tier if segments & BLOG_PATH_SEGMENTS else portal_tier
    return blog_tier
