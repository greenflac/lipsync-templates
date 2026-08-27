#!/usr/bin/env python3
"""Replace second-hand facts with ones somebody opened, and say what changed.

WHY THIS EXISTS AS A SCRIPT AND NOT AS A CHAT TRANSCRIPT

Until 2026-08-27 the vendors' documentation hosts were refused by this
environment's egress policy, so every fact in `model_facts.jsonl` was a search
engine's summary OF a page rather than the page. The owner had a wildcard
allowlist granted; 41 hosts answer now. This is the pass that went and read
them.

Each entry below records ONE reading: the page, what it actually says, and
which recorded claim that confirms, corrects or destroys. Kept in the
repository rather than done by hand in a conversation, because the alternative
is a fact base whose provenance lives in a chat log nobody can re-run.

RE-RUNNING IS SAFE AND IS THE POINT

`advice.record` appends nothing when the row it would write already stands, and
`advice.withdraw` reports `could not measure` for a claim already gone. So a
second run prints the same table and changes no bytes — verified, and asserted
by the `--check` flag which fails if a run would still change something.

WHAT THE READING FOUND, IN ONE LINE

Of 24 claims whose page could be opened, 8 were confirmed, 8 said something
materially different from the summary, and 6 rested on a page that does not
make the claim at all. That ratio is the argument for the `read_directly` flag
the owner asked for.

It also found a source nobody had used: Runway publishes an OpenAPI document
at docs.dev.runwayml.com/openapi.json giving the accepted duration and ratio
enums PER MODEL, for the models it resells as well as its own. A validated
enum beats every prose page, and the file carries its own negative control —
see the Runway block below.

    python scripts/read_sources.py            # apply
    python scripts/read_sources.py --check    # fail if anything would change
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import PASS, UNMEASURED  # noqa: E402

from studio.mcp import advice  # noqa: E402
from studio.selfrag.facts import (  # noqa: E402
    DEFAULT_FACTS_PATH,
    claim_key,
    load_facts,
)

#: The date this pass opened the pages. Used as `stated_on` ONLY for a source
#: that carries no date of its own — a live API reference or a product page,
#: which states what it states on the day you read it. Never used to re-date a
#: page that has a date: that is how a 2025 article comes to look like today's
#: news, and 33 of the 47 rows in this file had exactly that done to them.
READ_ON = "2026-08-27"

#: Confirmed or corrected by opening the page. Each is `record`'s arguments,
#: plus an optional `replaces` — the exact value this reading supersedes AT THE
#: SAME URL, which the runner withdraws first.
#:
#: `replaces` is structural and not a convenience. Writing this script I
#: recorded three corrected values and forgot their withdrawals, and the base
#: immediately reported cloud.google.com, kling.ai and bfl.ai each
#: contradicting itself — the exact failure `withdraw_model_fact`'s own
#: docstring warns about, made by the person who wrote the warning. A pairing
#: that has to be remembered in two places is a pairing that gets forgotten;
#: this way the correction carries its retraction.
READINGS: tuple[dict[str, object], ...] = (
    # -- confirmed, word for word ------------------------------------------
    {
        "model": "kling-3.0",
        "attribute": "max_seconds",
        "value": "15",
        "source_url": (
            "https://ir.kuaishou.com/news-releases/news-release-details/"
            "kling-ai-launches-30-model-ushering-era-where-everyone-can-be"
        ),
        "tier": "vendor",
        "stated_on": "2026-02-05",
        "note": (
            "READ: 'major upgrades in consistency, photorealistic output, extended "
            "video duration of up to 15 seconds, and native audio generation'. "
            "Kuaishou's own investor release, opened and quoted, not summarised."
        ),
        "read_directly": True,
    },
    {
        "model": "wan-2.6-flash",
        "attribute": "max_seconds",
        "value": "15",
        "source_url": "https://wavespeed.ai/models/alibaba/wan-2.6/image-to-video-flash",
        "tier": "portal",
        "stated_on": READ_ON,
        "note": (
            "READ: the parameter table says 'duration — video length in seconds, up "
            "to 15 (default: 15)', and resolution '720p or 1080p (default: 720p)'. "
            "The page carries no date of its own; stated_on is the day it was read."
        ),
        "read_directly": True,
    },
    {
        "model": "flux-2",
        "attribute": "prompt_rule_edit",
        "value": "quote text literally: Replace 'old' with 'new'",
        "source_url": "https://docs.bfl.ai/kontext/kontext_image_editing",
        "tier": "vendor",
        "stated_on": READ_ON,
        "note": (
            "READ: 'The most effective way to edit text is using quotation marks "
            "around the specific text you want to change: Replace \\'[original "
            "text]\\' with \\'[new text]\\''. Note this is the FLUX.1 Kontext editing "
            "guide; it is BFL's page and BFL is the vendor, but the rule is stated "
            "for Kontext and carried to FLUX.2 by family, not by the page saying so."
        ),
        "read_directly": True,
    },
    {
        "model": "elevenlabs-pvc",
        "attribute": "training_audio_minutes",
        "value": "30 minutes is the floor, 3 hours of consistent studio-grade audio for production grade",
        "source_url": (
            "https://elevenlabs.io/docs/eleven-creative/voices/voice-cloning/"
            "professional-voice-cloning"
        ),
        "tier": "vendor",
        "stated_on": READ_ON,
        "note": (
            "READ, and the page is slightly softer than the recorded wording: 'the "
            "bare minimum we recommend is 30 minutes of audio, but for the optimal "
            "result and the most accurate clone, we recommend closer to 2-3 hours'. "
            "Elsewhere: 'Professional Voice Cloning: higher fidelity, using 30 "
            "minutes to about 3 hours of audio. Fine-tuning usually takes 3-6 "
            "hours.' So the floor is exact and the ceiling is a range, not a number."
        ),
        "read_directly": True,
    },
    {
        "model": "*",
        "attribute": "metric_blind_spot",
        "value": "FVD is blind to motion: it barely moves under large temporal corruption",
        "source_url": "https://arxiv.org/abs/2404.12391",
        "tier": "paper",
        "stated_on": "2024-04-18",
        "note": (
            "READ (abstract, arXiv): 'we first quantify the FVD's sensitivity to the "
            "temporal axis by decoupling the frame and motion quality and find that "
            "the FVD increases only slightly with large temporal corruption'. The "
            "recorded wording is the paper's own finding, not a paraphrase of one."
        ),
        "read_directly": True,
    },
    {
        "model": "*",
        "attribute": "failure_mode",
        "value": "text garbling is a character-blind text encoder, not a resolution problem",
        "source_url": "https://arxiv.org/abs/2212.10562",
        "tier": "paper",
        "stated_on": "2022-12-20",
        "note": (
            "READ (abstract, arXiv): 'popular text-to-image models lack "
            "character-level input features, making it much harder to predict a "
            "word's visual makeup as a series of glyphs'; character-aware variants "
            "beat character-blind ones across their DrawText benchmark. Confirmed."
        ),
        "read_directly": True,
    },
    {
        "model": "flux-2",
        "attribute": "expands_internally",
        "value": "unknown",
        "source_url": "https://docs.bfl.ai/",
        "tier": "vendor",
        "stated_on": READ_ON,
        "note": (
            "READ: the documentation index itself, which lists every page BFL "
            "publishes. No prompt-expander or prompt-rewriting page among them. A "
            "negative finding, and a doc ROOT is the right citation for one — you "
            "cannot cite the page that does not exist. Noted while reading: the "
            "index now leads with FLUX 3, so the FLUX.2 rows here are one "
            "generation behind the vendor."
        ),
        "read_directly": True,
    },
    {
        "model": "kling-3.0",
        "attribute": "expands_internally",
        "value": "unknown",
        "source_url": "https://kling.ai/quickstart/text-to-video-prompt-guide",
        "tier": "vendor",
        "stated_on": "2025-11-24",
        "note": (
            "READ, and the reading weakens the citation: the guide is dated "
            "'Kling AI Nov 24, 2025', calls itself 'the new incarnation of the AI "
            "video model 2.0' and says the model 'generates a 5-second or 10-second "
            "video'. It is not a 3.0 page. It describes no expander, so the negative "
            "finding stands for what it covers; stated_on corrected from the "
            "harvest date to the date the page carries."
        ),
        "read_directly": True,
    },
    # -- corrected: the page says something materially different ------------
    {
        "model": "veo-3.1",
        "attribute": "prompt_skeleton",
        "value": "cinematography, subject, action, context, style and ambiance",
        "source_url": (
            "https://cloud.google.com/blog/products/ai-machine-learning/"
            "ultimate-prompting-guide-for-veo-3-1"
        ),
        "tier": "vendor",
        "stated_on": "2025-10-16",
        "note": (
            "READ: 'Consider this five-part formula for optimal control. "
            "[Cinematography] + [Subject] + [Action] + [Context] + [Style & "
            "Ambiance]'. The summary had recorded eight parts, omitting Context and "
            "promoting composition, focus and audio — which the page lists as "
            "VOCABULARY for the cinematography slot, not as slots. Page date "
            "October 16, 2025, replacing the harvest date."
        ),
        "replaces": (
            "subject, action, style, camera, composition, focus, ambiance, audio",
            (
                "the page gives FIVE parts and the summary recorded eight, dropping "
                "Context and promoting composition, focus and audio, which the page "
                "lists as vocabulary for the cinematography slot rather than as slots"
            ),
        ),
        "read_directly": True,
    },
    {
        "model": "kling-3.0",
        "attribute": "prompt_skeleton",
        "value": (
            "subject (+description) + subject movement + scene (+description) + "
            "optional (camera language + lighting + atmosphere)"
        ),
        "source_url": "https://kling.ai/quickstart/text-to-video-prompt-guide",
        "tier": "vendor",
        "stated_on": "2025-11-24",
        "note": (
            "READ: 'Prompt = Subject (Subject Description) + Subject Movement + "
            "Scene (Scene Description) + (Camera Language + Lighting + Atmosphere) "
            "-- optional'. The summary had flattened Scene into 'context' and lost "
            "that the last group is optional, which is the only part a prompt writer "
            "acts on. Same caveat as the row above: the guide predates 3.0."
        ),
        "replaces": (
            "subject, action, context, style (style = camera + lighting + mood)",
            (
                "the summary flattened the page's 'Scene' into 'context' and lost "
                "that the camera/lighting/atmosphere group is marked optional, which "
                "is the only part of the formula a prompt writer decides about"
            ),
        ),
        "read_directly": True,
    },
    {
        "model": "flux-2",
        "attribute": "architecture",
        "value": (
            "latent flow matching: a rectified flow transformer coupled with the "
            "Mistral-3 24B VLM (the 32B figure is FLUX.2 [dev], the open-weight "
            "derivative, not the base transformer)"
        ),
        "source_url": "https://bfl.ai/blog/flux-2",
        "tier": "vendor",
        "stated_on": "2025-11-25",
        "note": (
            "READ: 'FLUX.2 builds on a latent flow matching architecture... The "
            "model couples the Mistral-3 24B parameter vision-language model with a "
            "rectified flow transformer.' Separately: 'FLUX.2 [dev]: 32B open-weight "
            "model, derived from the FLUX.2 base model.' The summary had welded the "
            "32B onto the transformer, which the page does not do."
        ),
        "replaces": (
            "rectified flow transformer 32B plus Mistral-3 24B VLM",
            (
                "the page attaches 32B to FLUX.2 [dev], the open-weight derivative, "
                "not to the base model's transformer; the summary welded the two"
            ),
        ),
        "read_directly": True,
    },
    {
        "model": "*",
        "attribute": "artifact_taxonomy",
        "value": (
            "16 disentangled dimensions, among them temporal flickering, motion "
            "smoothness, subject identity inconsistency and spatial relationship"
        ),
        "source_url": "https://arxiv.org/abs/2311.17982",
        "tier": "paper",
        "stated_on": "2023-11-29",
        "note": (
            "READ (abstract, arXiv): 'VBench comprises 16 dimensions in video "
            "generation (e.g., subject identity inconsistency, motion smoothness, "
            "temporal flickering, and spatial relationship, etc)'. The recorded "
            "taxonomy — jitter, warp, texture crawl, boundary defects, object "
            "mismatches — is practitioner vocabulary and is NOT what VBench names. "
            "Only 'flicker' survives. The abstract lists 4 of the 16 by name; the "
            "rest are in the paper, unread here."
        ),
        "read_directly": True,
    },
    {
        "model": "*",
        "attribute": "failure_mode",
        "value": (
            "the best model satisfies caption AND physical law together in 39.6% of "
            "instances (CogVideoX-5B on VideoPhy)"
        ),
        "source_url": "https://arxiv.org/html/2406.03520v1",
        "tier": "paper",
        "stated_on": "2024-06-05",
        "note": (
            "READ (VideoPhy, arXiv): 'the best performing model, CogVideoX-5B, "
            "generates videos that adhere to the caption and physical laws for 39.6% "
            "of the instances'. The number replaces the recorded 'is low'. The other "
            "half of the recorded claim — that it falls with each causal step — is "
            "NOT in the abstract; it may be in the body, which was not read."
        ),
        "fix": "one causal action per clip",
        "read_directly": True,
    },
    {
        "model": "*",
        "attribute": "failure_mode",
        "value": (
            "oversaturation at high classifier-free guidance comes from the "
            "component of the CFG update parallel to the conditional prediction"
        ),
        "source_url": "https://arxiv.org/pdf/2410.02416",
        "tier": "paper",
        "stated_on": "2024-10-03",
        "note": (
            "READ (abstract, via export.arxiv.org): 'we decompose the update term in "
            "CFG into parallel and orthogonal components with respect to the "
            "conditional model prediction and observe that the parallel component "
            "primarily causes oversaturation, while the orthogonal component "
            "enhances image quality'. The recorded 'off-manifold trajectory' is a "
            "different mechanism and is not the paper's. Their fix, APG, is "
            "down-weighting the parallel component."
        ),
        "fix": "lower CFG or use APG (adaptive projected guidance); a parameter, not an adjective",
        "read_directly": True,
    },
    {
        "model": "*",
        "attribute": "expander_evidence",
        "value": (
            "automated prompt rewriting cannot generally substitute for human "
            "adaptation: aligned with the task objective it modestly helps, "
            "misaligned it actively undermines the gains from a model upgrade"
        ),
        "source_url": "https://arxiv.org/abs/2407.14333",
        "tier": "paper",
        "stated_on": "2026-01-07",
        "note": (
            "READ (abstract of v7, dated 2026-01-07, via export.arxiv.org). THE "
            "PAPER HAS BEEN REVISED AND RETITLED since this base recorded it: it is "
            "now 'Prompt Adaptation as a Dynamic Complement in Generative AI "
            "Systems', 3,750 participants and ~37,000 prompts across two "
            "preregistered tasks. The 58% figure and N=1891 this base carried are "
            "from a superseded version and appear nowhere in v7's abstract."
        ),
        "fix": "add nothing the user did not ask for; measure intent preservation, not length",
        "read_directly": True,
    },
    {
        "model": "*",
        "attribute": "expander_evidence",
        "value": (
            "user prompt adaptation accounts for roughly half the gain from a model "
            "upgrade in a task with fixed criteria and an unambiguous goal"
        ),
        "source_url": "https://arxiv.org/abs/2407.14333",
        "tier": "paper",
        "stated_on": "2026-01-07",
        "note": (
            "READ (abstract of v7). The 'about half' survives the revision; the "
            "'24% longer prompts' the base recorded does not appear in v7's abstract."
        ),
        "read_directly": True,
    },
    {
        "model": "*",
        "attribute": "expander_evidence",
        "value": (
            "in an open-ended creative task, prompt adaptation plays a LIMITED role "
            "and the gains come from model capability instead"
        ),
        "source_url": "https://arxiv.org/abs/2407.14333",
        "tier": "paper",
        "stated_on": "2026-01-07",
        "note": (
            "READ (abstract of v7), and new to this base. It qualifies the evidence "
            "this project's own architecture rests on: 'in an open-ended creative "
            "task where the space of acceptable outputs is effectively unbounded and "
            "quality is subjective, performance improvements are driven primarily by "
            "model capability; prompt adaptation plays a limited role'. Writing "
            "generation prompts IS that task. The anti-expander argument survives — "
            "misaligned rewriting still undermines gains — but the size of the prize "
            "for getting prompts right is smaller here than in the fixed-criteria "
            "task the 'about half' comes from. FOR THE OWNER, not acted on."
        ),
        "read_directly": True,
    },
    # -- Runway's OpenAPI contract, found while settling a contradiction ----
    #
    # https://docs.dev.runwayml.com/openapi.json — the vendor's own
    # machine-readable request schema, per model, with the enums the API will
    # actually accept. Stronger than any prose page: a documented enum is what
    # the server validates against, and it cannot be a journalist's rounding.
    #
    # This one document carries the NEGATIVE CONTROL that makes it decisive.
    # `seedance2` in the same file accepts 3840:2160 and five other 4K-class
    # ratios; `gen4.5` accepts six ratios and the largest is 1280:720. So the
    # absence of 4K for Gen-4.5 is the spec saying no, not the spec being
    # silent about resolution.
    {
        "model": "runway-gen-4.5",
        "attribute": "max_resolution",
        "value": "720p",
        "source_url": "https://docs.dev.runwayml.com/openapi.json",
        "tier": "vendor",
        "stated_on": READ_ON,
        "note": (
            "READ (OpenAPI 3.1, info.version 2024-11-06, fetched and parsed): the "
            "`gen4.5` variant of POST /v1/image_to_video accepts ratio in "
            "['1280:720','720:1280','1104:832','960:960','832:1104','1584:672'] and "
            "text_to_video only ['1280:720','720:1280']. NEGATIVE CONTROL in the "
            "same document: `seedance2` accepts '3840:2160' and five more 4K-class "
            "ratios, so this schema does describe 4K where 4K exists. It does not "
            "for Gen-4.5. The page carries no date; stated_on is the day it was read."
        ),
        "read_directly": True,
    },
    {
        "model": "runway-gen-4.5",
        "attribute": "max_seconds",
        "value": "10",
        "source_url": "https://docs.dev.runwayml.com/openapi.json",
        "tier": "vendor",
        "stated_on": READ_ON,
        "note": (
            "READ (OpenAPI): duration is 'an integer from 2 to 10' for `gen4.5` on "
            "both text_to_video and image_to_video. Not an enum but a range, so 2-10 "
            "inclusive; the ceiling is the claim."
        ),
        "read_directly": True,
    },
    {
        "model": "veo-3.1",
        "attribute": "max_seconds",
        "value": "8",
        "source_url": "https://docs.dev.runwayml.com/openapi.json",
        "tier": "portal",
        "stated_on": READ_ON,
        "note": (
            "READ (OpenAPI): `veo3.1` and `veo3.1_fast` take duration from the enum "
            "[4, 6, 8] — an enum, not a range, so 5 and 7 are refused. This is "
            "PORTAL tier and not vendor: it is Runway documenting an endpoint it "
            "resells, and Google may allow elsewhere what Runway does not expose."
        ),
        "read_directly": True,
    },
    {
        "model": "seedance-2.0",
        "attribute": "max_seconds",
        "value": "4 to 15",
        "source_url": "https://docs.dev.runwayml.com/openapi.json",
        "tier": "portal",
        "stated_on": READ_ON,
        "note": (
            "READ (OpenAPI): `seedance2` takes duration 4..15 inclusive. This "
            "corroborates the '4 to 15' side of the contradiction on that page "
            "against its own headline '12', with a running endpoint's schema rather "
            "than another article. Note `seedance2_5` in the same file goes to 30."
        ),
        "read_directly": True,
    },
    {
        "model": "seedance-2.0",
        "attribute": "max_resolution",
        "value": "3840x2160",
        "source_url": "https://docs.dev.runwayml.com/openapi.json",
        "tier": "portal",
        "stated_on": READ_ON,
        "note": (
            "READ (OpenAPI): `seedance2` accepts ratio '3840:1646', '3840:2160', "
            "'3840:2880', '3840:3840', '2880:3840' and '2160:3840' among its 24. "
            "The largest 16:9 is 3840:2160."
        ),
        "read_directly": True,
    },
    # -- Civitai: the licence checked BEFORE the collector (rule C5) --------
    #
    # Two sessions carried the plan "civitai.com/api/v1/images returns prompts
    # WITH the results they produced -- the pairing this project has never
    # had". Both halves of that plan are now measured, and both fail.
    {
        "model": "civitai-api",
        "attribute": "licence",
        "value": (
            "personal, non-commercial use only; automated access only through the "
            "public API with your own credentials, or written authorisation"
        ),
        "source_url": "https://civitai.com/content/tos",
        "tier": "portal",
        "stated_on": READ_ON,
        "note": (
            "READ, first-hand, replacing the UNVERIFIED grounded summary the "
            "previous session recorded. ToS 6.1: 'Civitai grants you, SOLELY FOR "
            "YOUR PERSONAL, NON-COMMERCIAL USE, a limited, non-exclusive, "
            "non-transferable, non-sublicensable, revocable license to ... access "
            "and use the Service.' ToS 11.4 forbids spiders, robots, crawlers and "
            "data mining tools 'except (a) through interfaces we expressly provide "
            "for automated access, such as our public API ... accessed with your own "
            "valid credentials and within any applicable rate limits ... or (c) as "
            "we otherwise authorize in writing.' So the CHANNEL is sanctioned and "
            "the USE is not: this repository is a commercial service. Separately, "
            "per-upload model licences (Anima, LTX-derived, Cosmos-derived) carry "
            "their own commercial restrictions on top. RESOLVED 2026-08-27: the "
            "owner obtained legal clearance and confirmed there is no outstanding "
            "legal risk; that is the basis stamped on every collected row. The ToS "
            "text above is unchanged and kept deliberately, because it is what the "
            "authorisation is an exception to. See studio/knowledge/PROVENANCE.md "
            "and the collector at studio/mcp/civitai.py."
        ),
        "read_directly": True,
    },
    {
        "model": "civitai-api",
        "attribute": "images_endpoint_metadata",
        "value": "stripped",
        "source_url": "https://civitai.com/api/v1/images",
        "tier": "probe",
        "stated_on": READ_ON,
        "note": (
            "MEASURED, unauthenticated: 300 images across three pages, `meta` null "
            "on 300 of 300; also null for ?postId=, ?sort=Newest and ?sort=Most "
            "Reactions, and a bogus ?token= is accepted with 200 rather than "
            "refused, so the route does not appear to gate this behind a key. Kept "
            "as its own attribute because it is a true fact about THIS endpoint, "
            "and it was the belief that sank two sessions' plans."
        ),
        "read_directly": True,
    },
    {
        "model": "civitai-api",
        "attribute": "prompt_metadata_exposed",
        "value": "only on /api/v1/model-versions/{id}, never on /api/v1/images",
        "replaces": (
            "no",
            (
                "measured only on /api/v1/images, and generalised from it. Walking "
                "the rest of the API found the pairs on the model-version endpoint, "
                "so 'the API does not expose prompts' was a claim about one route "
                "reported as a claim about the API"
            ),
        ),
        "source_url": "https://civitai.com/api/v1/model-versions/128713",
        "tier": "probe",
        "stated_on": READ_ON,
        "note": (
            "MEASURED, unauthenticated, both ways. /api/v1/images: `meta` null on "
            "300 of 300 across three pages, and null for ?postId=, ?sort=Newest and "
            "?sort=Most Reactions. /api/v1/models: the nested images carry "
            "`hasMeta` and `hasPositivePrompt` FLAGS while `meta` itself is null — "
            "0 of 1754. /api/v1/model-versions/{id}: the same images WITH `meta`, "
            "60 of 63 carrying a prompt, keys stable (prompt, negativePrompt, seed, "
            "steps, sampler, cfgScale, Size, Model). So the pairing this project "
            "has never had is obtainable, from the third route. No API key was "
            "used or needed. Collector: studio/mcp/civitai.py."
        ),
        "read_directly": True,
    },
    # -- Reddit: reachable, authenticated-read blocked ----------------------
    {
        "model": "reddit-api",
        "attribute": "authenticated_read_reachable",
        "value": "no",
        "source_url": "https://oauth.reddit.com/r/comfyui/hot",
        "tier": "probe",
        "stated_on": READ_ON,
        "note": (
            "MEASURED, and it is the fact that decides whether a Reddit app is worth "
            "registering. The token endpoint at www.reddit.com/api/v1/access_token "
            "behaves like an API: a wrong credential comes back "
            '401 {"message": "Unauthorized", "error": 401}. But '
            "oauth.reddit.com — the host every authenticated read goes to — answers "
            "403 with Reddit's 'Blocked' page, IDENTICALLY with and without an "
            "Authorization header. That is an edge block on this caller decided "
            "before any credential is examined. So an app id and secret would "
            "probably NOT make this work from here. Strong evidence, not proof: a "
            "VALID token has never been presented. The egress policy is not the "
            "obstacle — it lets reddit.com through. Not routed around. "
            "DROPPED by the owner 2026-08-27: the collector is deleted and this "
            "measurement is what survives it. Reopen only if the work moves somewhere "
            "Reddit does not block, or a valid token gets something other than the "
            "Blocked page. See studio/knowledge/PROVENANCE.md for the stop condition."
        ),
        "read_directly": True,
    },
    # -- putting a NEW character into an EXISTING scene ---------------------
    #
    # Recorded because the base had nothing on it and the assistant answered
    # from what was lying in the repository instead. Three architectures, and
    # the difference between them decides the job: only the first keeps the
    # original footage.
    {
        "model": "runway-aleph2",
        "attribute": "architecture",
        "value": "edits the input video, so the original scene survives",
        "source_url": "https://docs.dev.runwayml.com/openapi.json",
        "tier": "vendor",
        "stated_on": READ_ON,
        "note": (
            "READ (OpenAPI): POST /v1/video_to_video, model `aleph2`, field "
            "`videoUri` — 'The input video to edit. Must be 30 seconds or shorter.' "
            "Plus `keyframes` (up to 5 timed guidance images) and `promptText`. "
            "This is the family that preserves a real plate: the real lighting, "
            "grain and camera motion stay because the footage stays."
        ),
        "read_directly": True,
    },
    {
        "model": "runway-aleph2",
        "attribute": "output_formats",
        "value": "mp4, prores (up to 4444 XQ), png_sequence, sdr_rec709_10bit",
        "source_url": "https://docs.dev.runwayml.com/openapi.json",
        "tier": "vendor",
        "stated_on": READ_ON,
        "note": (
            "READ (OpenAPI): `outputFormat` and `proresProfile` enums. The only "
            "candidate in this comparison that delivers a finishing-grade "
            "container rather than an H.264 preview."
        ),
        "read_directly": True,
    },
    {
        "model": "runway-act-two",
        "attribute": "architecture",
        "value": "performance transfer ONTO a character, so the scene comes from the character",
        "source_url": "https://docs.dev.runwayml.com/openapi.json",
        "tier": "vendor",
        "stated_on": READ_ON,
        "note": (
            "READ (OpenAPI): POST /v1/character_performance, model `act_two`. "
            "`character` — 'The character to control. You can either provide a "
            "video or an image. A visually recognizable face must be present.' "
            "`reference` — 'The reference video containing the performance to "
            "apply to the character.' Also `bodyControl` and `expressionIntensity` "
            "1-5. So the reference supplies MOVEMENT, not the set. Using it to "
            "keep an existing room is a category error."
        ),
        "read_directly": True,
    },
    {
        "model": "runway-act-two",
        "attribute": "max_resolution",
        "value": "720p",
        "source_url": "https://docs.dev.runwayml.com/openapi.json",
        "tier": "vendor",
        "stated_on": READ_ON,
        "note": (
            "READ (OpenAPI): ratio enum 1280:720, 720:1280, 960:960, 1104:832, "
            "832:1104, 1584:672. Nothing above 720p, in a document that offers "
            "3840:2160 to another model."
        ),
        "read_directly": True,
    },
    {
        "model": "wan-animate-replace",
        "attribute": "architecture",
        "value": "replaces the character in a reference video, keeping the scene",
        "source_url": "https://fal.ai/models/fal-ai/wan/v2.2-14b/animate/replace/api",
        "tier": "portal",
        "stated_on": READ_ON,
        "note": (
            "READ: 'Wan-Animate Replace is a model that can integrate animated "
            "characters into reference videos, replacing the original character "
            "while preserving the scene's lighting and color tone for seamless "
            "environmental integration.' Inputs `video_url` and `image_url`, both "
            "required. Portal tier and not vendor: this is fal running Alibaba's "
            "model, not Alibaba's own page."
        ),
        "read_directly": True,
    },
    {
        "model": "wan-animate-replace",
        "attribute": "max_resolution",
        "value": "720p",
        "source_url": "https://fal.ai/models/fal-ai/wan/v2.2-14b/animate/replace/api",
        "tier": "portal",
        "stated_on": READ_ON,
        "note": "READ: resolution enum 480p, 580p, 720p; default 480p.",
        "read_directly": True,
    },
    {
        "model": "wan-animate-replace",
        "attribute": "max_frames",
        "value": "161",
        "source_url": "https://fal.ai/models/fal-ai/wan/v2.2-14b/animate/replace/api",
        "tier": "portal",
        "stated_on": READ_ON,
        "note": (
            "READ: `num_frames` 17 to 161 inclusive, default 81; "
            "`frames_per_second` 4 to 60. So the ceiling is a FRAME count, not a "
            "duration: 161 frames is 5.4 s at 30 fps and 10.1 s at 16 fps. A "
            "10-second plate at 30 fps needs chunking."
        ),
        "read_directly": True,
    },
    {
        "model": "kling-3.0",
        "attribute": "motion_control_architecture",
        "value": "motion transfer onto a character image, not an edit of the reference",
        "source_url": "https://fal.ai/models/fal-ai/kling-video/v2.6/standard/motion-control/api",
        "tier": "portal",
        "stated_on": READ_ON,
        "note": (
            "READ: the endpoint description says it applies 'the motion from a reference "
            "video to any character image. Cost-effective mode for motion "
            "transfer, perfect for portraits and simple animations.' Duration enum "
            "3-13. Same family as act_two: the reference gives movement, the "
            "character gives the scene. Recorded because this repository's own "
            "engine calls this endpoint and it was recommended for a job that "
            "required keeping an existing room, which it cannot do."
        ),
        "read_directly": True,
    },
    # -- opened, and the reading could NOT settle it: three outcomes --------
    {
        "model": "*",
        "attribute": "metric_blind_spot",
        "value": "warp error scores a frozen video near-perfect",
        "source_url": "https://arxiv.org/pdf/2403.14773",
        "tier": "paper",
        "stated_on": "2024-03-21",
        "note": (
            "COULD NOT CHECK, and that is recorded rather than resolved. The "
            "StreamingT2V abstract (read via export.arxiv.org) does not mention warp "
            "error at all; it discusses 'video stagnation' in competing methods. The "
            "claim is plausibly in the body, and the body is a PDF this environment's "
            "fetcher returns as raw bytes rather than text. Not withdrawn — an "
            "unread body is not a silent one — and not marked read either."
        ),
        "fix": "pair it with an optical-flow score, as MAWE does",
        "read_directly": False,
    },
    {
        "model": "*",
        "attribute": "expander_evidence",
        "value": "prompt length correlates with quality at about -0.07, i.e. essentially not at all",
        "source_url": "https://arxiv.org/pdf/2403.11821",
        "tier": "paper",
        "stated_on": "2024-03-18",
        "note": (
            "COULD NOT CHECK. The abstract (read via export.arxiv.org) is a taxonomy "
            "of text-to-image quality metrics and states no correlation coefficient. "
            "Same reason as the row above: the body is a PDF that comes back as raw "
            "bytes. The -0.07 is unverified against the source, and this note is "
            "where the next reader finds that out."
        ),
        "read_directly": False,
    },
)

#: Claims whose own page, once opened, does not make them. Each is
#: `withdraw`'s arguments: the four fields that identify the claim, and why.
WITHDRAWN: tuple[dict[str, str], ...] = (
    {
        "model": "civitai-api",
        "attribute": "prompt_metadata_exposed",
        "value": "no",
        "source_url": "https://civitai.com/api/v1/images",
        "reason": (
            "measured on one route and stated about the whole API. /api/v1/images "
            "really does return meta: null (300 of 300), but the pairs are on "
            "/api/v1/model-versions/{id}, so the unqualified 'no' was false. "
            "Replaced by a scoped claim at this same URL and by the finding at the "
            "endpoint that has them. NOTE for the next reader: `replaces` in a "
            "reading only withdraws at the SAME url, which is right — a claim is "
            "identified by its source — so a correction that moves to a DIFFERENT "
            "source needs an explicit withdrawal here, as this one did"
        ),
    },
    {
        "model": "veo-3.1",
        "attribute": "best_for",
        "value": "cinematic realism and prompt fidelity, native synchronised audio",
        "source_url": "https://wavespeed.ai/",
        "reason": (
            "the cited page is WaveSpeed's marketing homepage and does not contain "
            "the string 'Veo' anywhere (MEASURED: 0 occurrences in 16913 characters)"
        ),
    },
    {
        "model": "kling-3.0",
        "attribute": "best_for",
        "value": "motion control and camera work on stylised content",
        "source_url": "https://wavespeed.ai/",
        "reason": (
            "the cited page does not contain the phrase 'motion control' (MEASURED: "
            "0 occurrences); it mentions Kling only as one of 1000+ models it hosts"
        ),
    },
    {
        "model": "seedance-2.0",
        "attribute": "best_for",
        "value": "multimodal references, up to 3 videos and 9 images",
        "source_url": "https://wavespeed.ai/",
        "reason": (
            "the cited page states neither '3 videos' nor '9 images' (MEASURED: 0 "
            "occurrences of either); the numbers came from a summary, not the page"
        ),
    },
    {
        "model": "wan-2.6-flash",
        "attribute": "prompt_rule_i2v",
        "value": "the prompt describes what CHANGES, not what the picture already shows",
        "source_url": "https://fal.ai/",
        "reason": (
            "the cited page is fal's homepage — GPU pricing and a model gallery — "
            "and says nothing about how to write an image-to-video prompt. The rule "
            "may well be right; this URL is not evidence for it"
        ),
    },
    {
        "model": "seedance-2.0",
        "attribute": "override_parameter",
        "value": "camera_fixed overrides any camera language in the prompt",
        "source_url": "https://docs.byteplus.com/en/docs/ModelArk/1587798",
        "reason": (
            "the cited page documents seedance-1.0-pro, not 2.0 — 'Resolution: 480p, "
            "720p, 1080p. Frame rate: 24 fps. Duration: 2~12 seconds' — and the "
            "string 'camera_fixed' does not appear on it"
        ),
    },
    {
        "model": "seedance-2.0",
        "attribute": "expands_internally",
        "value": "unknown",
        "source_url": "https://docs.byteplus.com/en/docs/ModelArk/1587798",
        "reason": (
            "a negative finding needs the right page to be negative about: this one "
            "documents seedance-1.0-pro, so 'no expander described' says nothing "
            "about 2.0. Withdrawn rather than re-pointed, because no 2.0 page was read"
        ),
    },
    {
        "model": "*",
        "attribute": "artifact_taxonomy",
        "value": "flicker, jitter, warp, texture crawl, boundary defects, object mismatches",
        "source_url": "https://arxiv.org/abs/2311.17982",
        "reason": (
            "VBench does not name these dimensions. Its abstract names subject "
            "identity inconsistency, motion smoothness, temporal flickering and "
            "spatial relationship; only 'flicker' overlaps. Replaced by the "
            "paper's own wording"
        ),
    },
    {
        "model": "*",
        "attribute": "failure_mode",
        "value": "joint caption-and-physics satisfaction is low and falls with each causal step",
        "source_url": "https://arxiv.org/html/2406.03520v1",
        "reason": (
            "replaced by the paper's own number (39.6% for CogVideoX-5B). The "
            "'falls with each causal step' half is not in the abstract and the body "
            "was not read, so it is not asserted by this base"
        ),
    },
    {
        "model": "*",
        "attribute": "failure_mode",
        "value": "oversaturation at high classifier-free guidance is an off-manifold trajectory",
        "source_url": "https://arxiv.org/pdf/2410.02416",
        "reason": (
            "the paper attributes oversaturation to the component of the CFG update "
            "PARALLEL to the conditional prediction, not to leaving the manifold. "
            "Replaced by the mechanism the abstract states"
        ),
    },
    {
        "model": "*",
        "attribute": "expander_evidence",
        "value": (
            "automatic GPT-4 rewriting erased 58% of DALL-E 3's performance gain: "
            "rewrites added details or changed meaning"
        ),
        "source_url": "https://arxiv.org/abs/2407.14333",
        "reason": (
            "the paper was revised to v7 on 2026-01-07 and retitled; its abstract "
            "now reports 3,750 participants and ~37,000 prompts, and contains "
            "neither the 58% figure nor N=1891. The finding survives in weaker form "
            "and is recorded in the replacing row"
        ),
    },
    {
        "model": "*",
        "attribute": "expander_evidence",
        "value": (
            "human-written longer prompts DID help: DALL-E 3 users wrote 24% longer "
            "prompts and about half the gain came from that adaptation"
        ),
        "source_url": "https://arxiv.org/abs/2407.14333",
        "reason": (
            "same revision: v7's abstract keeps 'roughly half the performance gains' "
            "but not the 24% length figure. Replaced by the v7 wording"
        ),
    },
)


def _standing() -> dict[tuple[str, str, str, str], object]:
    """Every claim the base currently asserts, keyed the way `record` keys them."""
    return {
        claim_key(f.model, f.attribute, f.value, f.source_url): f
        for f in load_facts(DEFAULT_FACTS_PATH)
    }


def check() -> int:
    """Would this pass still change anything? Reads only — it must not write.

    A dry run that calls `withdraw` would withdraw, so this compares against the
    file instead. Three outcomes: nothing left to do, something left to do, or
    a row that cannot be checked because the base is missing.
    """
    standing = _standing()
    if not standing:
        print("не смогли проверить: фактов не загружено")
        return 1
    left = []
    for row in WITHDRAWN:
        key = claim_key(row["model"], row["attribute"], row["value"], row["source_url"])
        if key in standing:
            left.append(f"still asserted: {row['model']}.{row['attribute']} <- {row['source_url']}")
    for entry in READINGS:
        replaces = entry.get("replaces")
        if replaces is not None:
            old_value = replaces[0]  # type: ignore[index]
            old = claim_key(
                str(entry["model"]),
                str(entry["attribute"]),
                str(old_value),
                str(entry["source_url"]),
            )
            if old in standing:
                left.append(
                    f"still asserted: {entry['model']}.{entry['attribute']} = {old_value!r}"
                )
        key = claim_key(
            str(entry["model"]),
            str(entry["attribute"]),
            str(entry["value"]),
            str(entry["source_url"]),
        )
        fact = standing.get(key)
        if fact is None:
            left.append(f"not recorded: {entry['model']}.{entry['attribute']}")
        elif fact.read_directly != entry.get("read_directly") or fact.note != entry.get("note", ""):
            left.append(f"differs: {entry['model']}.{entry['attribute']}")
    for line in left:
        print(f"  {line}")
    print(f"\nпроверено {len(WITHDRAWN) + len(READINGS)}\nрасхождений {len(left)}\nне смогли 0")
    return 1 if left else 0


def main(argv: list[str]) -> int:
    """Apply every reading. Three outcomes, and the counts are printed beside them."""
    if "--check" in argv:
        return check()
    applied = failed = nothing = 0

    print(f"== withdrawing {len(WITHDRAWN)} claim(s) their own page does not make")
    for row in WITHDRAWN:
        out = advice.withdraw(**row)
        label = f"{row['model']}.{row['attribute']}"
        if out["outcome"] == PASS:
            applied += 1
        elif out["outcome"] == UNMEASURED:
            nothing += 1
        else:
            failed += 1
        print(f"  {str(out['outcome']):<18} {label}")

    print(f"\n== recording {len(READINGS)} reading(s)")
    for entry in READINGS:
        entry = dict(entry)
        replaces = entry.pop("replaces", None)
        if replaces is not None:
            old_value, reason = replaces  # type: ignore[misc]
            gone = advice.withdraw(
                str(entry["model"]),
                str(entry["attribute"]),
                str(old_value),
                str(entry["source_url"]),
                str(reason),
            )
            if gone["outcome"] == PASS:
                applied += 1
            elif gone["outcome"] == UNMEASURED:
                nothing += 1
            else:
                failed += 1
        out = advice.record(**entry)  # type: ignore[arg-type]
        label = f"{entry['model']}.{entry['attribute']}"
        if out["outcome"] != PASS:
            failed += 1
        elif out["written"] is None:
            nothing += 1
        else:
            applied += 1
        print(f"  {str(out['outcome']):<18} {label}: {str(out['note'])[:96]}")

    print(f"\nизменено {applied}\nуже стояло {nothing}\nотказано {failed}")
    if failed:
        print("\nFAIL: a reading was refused; nothing about it was written")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
