#!/usr/bin/env python3
"""Turn the denial log into a whitelist request somebody will actually approve.

    python scripts/whitelist_request.py            # the request, tier by tier
    python scripts/whitelist_request.py --tier 1   # just the must-haves
    python scripts/whitelist_request.py --check    # fail if a host is unclassified

WHY THIS IS A GENERATOR AND NOT A LIST

`studio/knowledge/denied_hosts.jsonl` grows every time a harvest meets a shut
door. A list typed out today is wrong tomorrow — and this file has grown by
twenty hosts in a single afternoon. So the tiers live here as a curated table
and the request is regenerated from the log.

WHY THE TIERS MATTER MORE THAN THE HOSTS

The log holds 206 refusals. Handing all of them over as one request gets the
whole thing refused, because `docs.anthropic.com` would be sitting next to
`seedance2pro.io` and `youtube.com`, and whoever owns the egress policy has to
justify every line. A request is approved on its weakest entry.

So the hosts are sorted by WHAT THEY ARE, using the same ladder the fact base
uses to decide what a source is worth:

  1 vendor     the model owner's own pages. Without these the base records a
               blog where a vendor statement exists — which is exactly how it
               came to claim Veo 3.1 tops out at 1080p while Google documents
               4k. Highest value per domain, smallest count.
  2 portal     platforms that RUN models. Where prices, schemas and real
               parameter enums live. Second rung, and the practical source for
               anything a closed vendor will not publish.
  3 benchmark  published evaluations and paper hosts. The only rung that can
               say a model is WORSE than its vendor claims.
  4 reference  general technical documentation. Useful, not load-bearing.
  x excluded   asked for by nobody. SEO clones, API resellers of resellers,
               social sites and blogspam. NAMED HERE ON PURPOSE: a request
               that visibly excludes junk is a request somebody can believe.

WILDCARDS

Hosts are collapsed to their registrable domain and requested as `*.domain`,
because the useful pages sit on subdomains nobody can enumerate in advance —
`docs.`, `api.`, `platform.`, `developer.`, `blog.`, `www.`. Fifteen domains
in the current log already appear under two to four subdomains each.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DENIED = Path(__file__).resolve().parents[1] / "studio" / "knowledge" / "denied_hosts.jsonl"

#: Registrable domains whose own pages ARE the vendor's word on their models.
#: Rung 1 of the fact base's ladder; a claim read here outranks every summary.
VENDOR: dict[str, str] = {
    "anthropic.com": "Claude models — limits, pricing, tool use",
    "x.ai": "Grok — the vendor's only stated specification",
    "mistral.ai": "Mistral — model cards, API reference",
    "deepseek.com": "DeepSeek — API docs and pricing",
    "cohere.com": "Cohere — embed and rerank, context and dimensions",
    "voyageai.com": "voyage-multimodal-3 — dimension, image payload limits",
    "deepmind.google": "Veo and Imagen — Google's own model pages",
    "google.dev": "Gemini API reference",
    "blog.google": "Google model announcements with stated limits",
    "googleblog.com": "Google developer announcements",
    "bfl.ml": "Black Forest Labs, older domain (bfl.ai already answers)",
    "minimax.io": "MiniMax / Hailuo — video and speech models",
    # Second root domain, and the docs live here rather than on the .io:
    # `platform.minimaxi.com` is what `source_hosts.py` already calls the
    # vendor of the `minimax` family, so the base can cite a page it is
    # not allowed to open. Owner said 2026-08-31 they add it upstream.
    "minimaxi.com": "MiniMax platform docs — the API reference itself",
    "hailuoai.video": "Hailuo product pages",
    "kimi.ai": "Moonshot Kimi — platform docs",
    "qwen.ai": "Qwen — Alibaba's model line",
    "z.ai": "Zhipu GLM",
    "skywork.ai": "Skywork models",
    "bytedance.com": "Seedance and OmniHuman — the lab's own pages",
    "alibabacloud.com": "Wan and Qwen on Alibaba's own cloud docs",
    "aliyun.com": "the same, Chinese-language docs",
    # Alibaba hosts some Wan documentation on its DingTalk docs service.
    # Vendor-adjacent rather than a vendor domain: the CONTENT is the lab's,
    # the host is a document service. Requested for the content, and the
    # distinction is stated so nobody later reads a DingTalk page as if the
    # host itself vouched for it.
    "dingtalk.com": "Alibaba doc hosting — Wan pages the base went looking for",
    "ideogram.ai": "Ideogram — typography-focused image model",
    "hedra.com": "Hedra Character — audio-driven avatar",
    "sync.so": "sync.so lipsync API",
    "deepgram.com": "Deepgram speech models",
    "leonardo.ai": "Leonardo image models",
    "comfy.org": "ComfyUI itself (api.comfy.org answers, the site does not)",
    "runwayml.com": "Runway — already partly open, listed for completeness",
    "elevenlabs.io": "ElevenLabs — already partly open, listed for completeness",
}

#: Platforms that RUN other people's models. Rung 2. Where a price, a duration
#: enum or a real parameter list can be read when the vendor publishes none.
PORTAL: dict[str, str] = {
    "replicate.com": "the largest model-running platform; schemas and prices",
    "openrouter.ai": "a paged CATALOGUE of closed LLMs — ids, context, price",
    "together.xyz": "the same shape, second source",
    "segmind.com": "hosted diffusion endpoints",
    "runware.ai": "hosted inference, published rates",
    "eachlabs.ai": "hosted video and avatar models",
    "fal.run": "fal's API host (fal.ai pages already answer)",
    "runcomfy.com": "hosted ComfyUI — node and workflow compatibility",
    "rundiffusion.com": "hosted diffusion tooling",
    "piapi.ai": "reseller with published enums",
    "aimlapi.com": "reseller catalogue",
    "kie.ai": "reseller catalogue",
    "apiframe.ai": "reseller catalogue",
}

#: Published evaluations. Rung 3, and the ONLY rung that can say a model is
#: worse than its vendor claims.
BENCHMARK: dict[str, str] = {
    "artificialanalysis.ai": "cross-vendor latency, price and quality index",
    "lmarena.ai": "human preference arena for LLMs and image models",
    "swebench.com": "SWE-bench leaderboards",
    "epoch.ai": "compute and capability trend data",
    "vals.ai": "independent model evaluations",
    "llm-stats.com": "aggregated LLM specifications and scores",
    "models.dev": "model specification catalogue",
    "semanticscholar.org": "paper metadata and citations",
    "alphaxiv.org": "arXiv discussion layer",
    "posttrainbench.com": "post-training benchmark",
    "benchlm.ai": "LLM benchmark aggregation",
    "agents-last-exam.org": "agent benchmark",
    "swe-marathon.org": "agent benchmark",
    "frontierswe.com": "agent benchmark",
    "datacurve.ai": "DeepSWE evaluation",
    "physion.net": "physical-reasoning benchmark",
    "myphysicslab.com": "physics reference for evaluating physical plausibility",
}

#: General technical documentation. Useful, never load-bearing for a claim
#: about a model.
REFERENCE: dict[str, str] = {
    "wikipedia.org": "definitions and background",
    "microsoft.com": "Azure-hosted model documentation (learn.microsoft.com)",
    "amazon.com": "AWS Bedrock model documentation",
    "mozilla.org": "web standards, for the creative-analysis side",
    "cloudflare.com": "Workers AI model catalogue",
    "ai-sdk.dev": "Vercel AI SDK — provider capability matrix",
    "apidog.com": "API reference mirrors",
    "datacamp.com": "tutorials",
    "github.io": "project pages of research repositories",
    "deepset.ai": "RAG tooling documentation",
    "mongodb.com": "vector search documentation",
    "union.ai": "orchestration documentation",
    "vellum.ai": "prompt tooling",
    "labellerr.com": "annotation tooling",
    "kili-technology.com": "annotation tooling",
    "learnprompting.org": "prompting reference",
    "ntnu.no": "academic hosting",
    "scale.com": "evaluation vendor",
    "takara.ai": "research index",
}

#: Deliberately NOT requested, and listed so the request can be seen to
#: exclude them. Three kinds: SEO clone domains that impersonate a model's
#: name, resellers-of-resellers, and general media.
EXCLUDED_REASONS: dict[str, str] = {
    "seo-clone": "a domain squatting on a model name; not the vendor",
    "reseller-of-reseller": "wraps another API; documents nothing first-hand",
    "media": "social, news or blog platform; blog tier at best",
    "tool-directory": "aggregated listings with no primary source",
    "not-needed": (
        "the refusal is real, and a MEASUREMENT showed nothing depends on it. "
        "Asking anyway spends the owner's attention on access we would not use"
    ),
}

EXCLUDED: dict[str, str] = {
    # MEASURED 2026-08-28: `docker pull qdrant/qdrant` resolves the manifest and
    # is then refused on the blob CDN (production.cloudfront.docker.com,
    # Forbidden), so Qdrant cannot run as a container here. It does not need to:
    # `QdrantClient(path=...)` — local mode, no server — created a collection,
    # upserted 500 points and answered a query in 0.79 s, and 1000 x 1024-dim
    # vectors persist across a reopen in 9.6 MB. An access request for a
    # dependency we measured away would be a request nobody can act on.
    "docker.com": "not-needed",
    # domains squatting on model names — none of these is the vendor
    "kling3.ai": "seo-clone",
    "kling3.io": "seo-clone",
    "kling3api.com": "seo-clone",
    "kling2-6.com": "seo-clone",
    "klingmotion.com": "seo-clone",
    "klingaimotioncontrol.com": "seo-clone",
    "kling-motion-control.com": "seo-clone",
    "motioncontrolai.com": "seo-clone",
    "acttwo.cv": "seo-clone",
    "seedance2-video.com": "seo-clone",
    "seedance20.com": "seo-clone",
    "seedance2ai.io": "seo-clone",
    "seedance2pro.io": "seo-clone",
    "seedanceapi.org": "seo-clone",
    "seavidgen.com": "seo-clone",
    "wan2-1.com": "seo-clone",
    "wan27.org": "seo-clone",
    "nanobanana.org": "seo-clone",
    # wrappers over other people's APIs
    "cometapi.com": "reseller-of-reseller",
    "apiyi.com": "reseller-of-reseller",
    "apimart.ai": "reseller-of-reseller",
    "gptproto.com": "reseller-of-reseller",
    "glbgpt.com": "reseller-of-reseller",
    "unifuncs.com": "reseller-of-reseller",
    "puter.com": "reseller-of-reseller",
    "evolink.ai": "reseller-of-reseller",
    "apob.ai": "reseller-of-reseller",
    # directories and listicles
    "aibase.com": "tool-directory",
    "kingy.ai": "tool-directory",
    "vibedex.ai": "tool-directory",
    "ai-compare-hub.com": "tool-directory",
    "aitooltier.com": "tool-directory",
    "toolcenter.ai": "tool-directory",
    "modelhunter.ai": "tool-directory",
    "localaimaster.com": "tool-directory",
    "theaibuilders.dev": "tool-directory",
    "themoonlight.io": "tool-directory",
    "imagebattle.ai": "tool-directory",
    "lmcouncil.ai": "tool-directory",
    "flaq.ai": "tool-directory",
    # media
    "youtube.com": "media",
    "facebook.com": "media",
    "forbes.com": "media",
    "scmp.com": "media",
    "medium.com": "media",
    "substack.com": "media",
    "dev.to": "media",
    "the-decoder.com": "media",
    "filmthreat.com": "media",
    "redditinc.com": "media",
    "emergentmind.com": "media",
    "chatpaper.ai": "media",
    "andlukyane.com": "media",
    "andreaskuhr.com": "media",
    "jonathanmast.com": "media",
    "christytuckerlearning.com": "media",
    "commandlinux.com": "media",
    "ourcodeworld.com": "media",
    "new3jcn.com": "media",
    "swfte.com": "media",
    "vultr.com": "media",
    "morphic.com": "media",
}

TIERS: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("1", "VENDOR — the model owner's own pages", VENDOR),
    ("2", "PORTAL — platforms that run the models", PORTAL),
    ("3", "BENCHMARK — published independent evaluation", BENCHMARK),
    ("4", "REFERENCE — general technical documentation", REFERENCE),
)

#: Multi-part public suffixes seen in this log. Not a full PSL — a short list
#: kept honest by `--check`, which fails on anything unclassified.
MULTI_PART_SUFFIXES: frozenset[str] = frozenset({"co.uk", "com.cn", "co.jp", "com.au"})


def registrable(host: str) -> str:
    """The domain a wildcard should be written against."""
    parts = str(host or "").strip().lower().split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in MULTI_PART_SUFFIXES:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else ".".join(parts)


def refused_hosts(path: Path | None = None) -> dict[str, list[str]]:
    """Registrable domain -> the refused hosts seen under it.

    The log is a state machine per host: `refused`, `open`, `unwanted`. Only
    the LAST row for a host counts, so a host that was refused and later
    answered does not end up in a request for access it already has.
    """
    latest: dict[str, dict] = {}
    for line in (path or DENIED).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("host"):
            latest[str(row["host"])] = row
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for host, row in latest.items():
        if row.get("state") != "refused":
            continue
        groups[registrable(host)].append(host)
    return dict(groups)


#: Why a host was first opened, as the log recorded it. This is EVIDENCE about
#: how badly a domain is wanted, and it beats any guess I could make from the
#: name — 44 of the 48 domains I could not classify by hand turned out to have
#: been touched once, as "checking whether a search hit is readable". Asking
#: for those weakens the request; asking for a page the base CITES and nobody
#: could open is the strongest line in it.
WANT_CITED = "cites"
WANT_INCIDENTAL = "search hit is readable"


def wanted_reasons(path: Path | None = None) -> dict[str, str]:
    """Registrable domain -> the first `why_wanted` the log recorded for it."""
    out: dict[str, str] = {}
    for line in (path or DENIED).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        host, why = str(row.get("host") or ""), str(row.get("why_wanted") or "")
        if host and why:
            out.setdefault(registrable(host), why)
    return out


def _report(groups: dict[str, list[str]], only: str = "") -> int:
    known = set()
    for _n, _t, table in TIERS:
        known |= set(table)
    known |= set(EXCLUDED)

    # The tail is classified by the log rather than by hand. A domain the base
    # CITES but nobody could open is a claim standing on an unread page, and
    # that is the most defensible line in any access request. A domain a search
    # engine showed us once is not wanted at all.
    reasons = wanted_reasons()
    cited = sorted(d for d in groups if d not in known and WANT_CITED in reasons.get(d, ""))
    incidental = sorted(
        d for d in groups if d not in known and WANT_INCIDENTAL in reasons.get(d, "")
    )
    unclassified = sorted(
        d for d in groups if d not in known and d not in cited and d not in incidental
    )

    print("ЗАЯВКА НА РАСШИРЕНИЕ WHITELIST")
    print(f"источник: {DENIED.name}, только строки в состоянии `refused`")
    print(f"хостов отказано: {sum(len(v) for v in groups.values())}")
    print(f"регистрируемых доменов: {len(groups)}\n")

    total = 0
    for number, title, table in TIERS:
        if only and only != number:
            continue
        rows = sorted(d for d in table if d in groups)
        if not rows:
            continue
        print(f"--- ТИР {number}: {title}  ({len(rows)} доменов)")
        for domain in rows:
            seen = ", ".join(sorted(groups[domain]))
            print(f"  *.{domain}")
            print(f"       зачем: {table[domain]}")
            print(f"       упирались в: {seen}")
        total += len(rows)
        print()

    if (not only or only == "5") and cited:
        print(f"--- ТИР 5: ЦИТИРУЕТСЯ БАЗОЙ, НО НЕ ПРОЧИТАНО  ({len(cited)} доменов)")
        print("     самая сильная строка заявки: под этими URL стоят утверждения,")
        print("     которые никто не смог проверить.")
        for domain in cited:
            print(f"  *.{domain}")
            print(f"       упирались в: {', '.join(sorted(groups[domain]))}")
        total += len(cited)
        print()

    if not only:
        excluded = sorted(d for d in EXCLUDED if d in groups)
        by_reason: dict[str, list[str]] = collections.defaultdict(list)
        for domain in excluded:
            by_reason[EXCLUDED[domain]].append(domain)
        print(f"--- НЕ ЗАПРАШИВАЕТСЯ НАМЕРЕННО ({len(excluded)} доменов)")
        for reason, domains in sorted(by_reason.items()):
            print(f"  {reason}: {EXCLUDED_REASONS.get(reason, '')}")
            print(f"       {', '.join(domains)}")
        if incidental:
            print(f"  incidental ({len(incidental)}): открыт один раз как результат поиска,")
            print("       ни одного факта на него не опирается — в заявке только ослабил бы её")
            print(f"       {', '.join(incidental)}")
        print()

    if unclassified:
        print(f"--- НЕ РАЗОБРАНО ({len(unclassified)}) — не идёт в заявку, пока не отнесено")
        for domain in unclassified:
            print(f"  {domain}   ({', '.join(sorted(groups[domain]))})")
        print()

    print(f"итого запрошено: {total} доменов")
    print(f"не разобрано: {len(unclassified)}")
    return len(unclassified)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", default="", choices=("", "1", "2", "3", "4", "5"))
    parser.add_argument(
        "--check",
        action="store_true",
        help="red when a refused domain is in neither a tier nor the exclusions",
    )
    args = parser.parse_args(argv)

    groups = refused_hosts()
    unclassified = _report(groups, only=args.tier)
    if args.check and unclassified:
        print(
            "\nFAIL: домены выше не отнесены ни к одному тиру и не исключены. "
            "Заявка, собранная сейчас, их молча потеряет — что и есть тот способ, "
            "которым нужный вендор не попадает в whitelist."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
