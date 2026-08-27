# Handoff: the chat agent, from this session to the next

Branch `claude/multiagent-prompt-engineer-orchestrator-7yamj4`, PR
[greenflac/lipsync-templates#1](https://github.com/greenflac/lipsync-templates/pull/1),
base `studio/mvp`. `bash scripts/check` exits 0; CI green on both 3.11 and 3.12.

Read this first, then `docs/MCP_AGENT.md` for the detail.

## Do this first, in a new session

1. **Confirm the Gemini key arrived.** It was added to the session on
   2026-08-27 and was NOT visible to the process — `os.environ` had nothing
   matching `GEMINI|GENAI|GOOGLE_API`. A container picks env up at start, so a
   fresh session should have it.

   ```
   python3 -c "from studio.mcp import search; k,n = search._first_env(search.GEMINI_KEY_ENV); print(n or 'STILL MISSING', len(k))"
   ```

2. **Run the first real search.** This is the one unverified thing in the
   package — the Gemini response parsing follows the documented
   `groundingMetadata` shape and has never met a live response.

   ```
   python3 -c "
   from studio.mcp import search
   o = search.search('Kling 3.0 max duration seconds API')
   print(o['outcome'], o['backend'], o['note'])
   for r in o['results'][:5]: print(' ', r['host'], r['fetchable'], r['url'][:70])
   print(o.get('answer','')[:400])"
   ```

   If the shape differs, fix `_gemini()` in `studio/mcp/search.py` and delete
   the UNVERIFIED paragraph from its docstring. Do not delete the paragraph
   without a live call behind it.

## One thing that does NOT migrate

The PR watch. `subscribe_pr_activity` binds to the session that called it, so
the previous session receives CI and review events for #1 and this one does
not. If you want them here, subscribe again:

    subscribe_pr_activity(owner="greenflac", repo="lipsync-templates", pullNumber=1)

Scheduled check-ins are the same — they fire into the session that scheduled
them.

## What exists

`studio/mcp/` — an MCP server, registered in `.mcp.json`, ten tools:

| tool | notes |
|---|---|
| `search_web` | research entry point. Gemini grounding preferred, Programmable Search fallback |
| `fetch_url` | opens one page through the policy. **Writes** refused hosts to `denied_hosts.jsonl` |
| `blocked_hosts` | the allowlist request, from refusals that really happened |
| `reachable_hosts` | re-probe what answers now |
| `probe_model_limit` | ask a vendor API for the impossible, read the refusal |
| `model_advice` | everything known about a model, with sources and dates |
| `record_model_fact` | **writes** to `model_facts.jsonl` |
| `stale_model_facts` | what needs re-checking |
| `write_lipsync_prompt` | look-only prompt from owner's words + corpus |
| `check_lipsync_prompt` | judge any prompt against the engine's contract |

Two tools write. Everything else reads.

## The environment, MEASURED 2026-08-27

Re-measure rather than trust this; that is what `reachable_hosts` is for.

```
open    raw.githubusercontent.com  api.github.com  github.com  pypi.org
        files.pythonhosted.org  huggingface.co  cloud.google.com
        storage.googleapis.com  api.klingai.com  api.fal.ai
        customsearch.googleapis.com  generativelanguage.googleapis.com
        discoveryengine.googleapis.com  aiplatform.googleapis.com
        searchapi.api.cloud.yandex.net
closed  docs.cloud.google.com  docs.bfl.ai  arxiv.org  kling.ai
        help.runwayml.com  elevenlabs.io  platform.openai.com  ai.google.dev
        api.openai.com  api.replicate.com  unpkg.com  cdn.jsdelivr.net
        every non-Google search backend probed (brave, tavily, exa, serpapi,
        serper, duckduckgo, bing, searx, perplexity, you.com, openalex,
        semanticscholar, crossref)
```

Shape worth remembering: **the API hosts of vendors we hold keys for are open;
their documentation hosts are shut.** `api.github.com` answers but refuses its
search paths — this session is bound to its repositories.

**Never route around a closed host.** No mirror, no cache, no archive copy, no
read-through proxy, no retry on a refusal. Refusals accumulate in
`studio/knowledge/denied_hosts.jsonl` and that file is the allowlist request.

## Credentials in this environment

| variable | present | used by |
|---|---|---|
| `KLING_KEY` | yes | `probe.py` — **note the name**, not `KLING_API_KEY` |
| `FAL_KEY` | yes | `probe.py` |
| `YANDEX_SEARCH_API_KEY` + `YANDEX_FOLDER_ID` | yes | **nothing yet — see below** |
| `POLLINATIONS_API_KEY` | yes | paid; do not call |
| `GEMINI_API_KEY` | added, not yet visible | `search.py` |

## Open, in the order I would take them

1. **Verify the Gemini parsing** (step 2 above). Everything else in search is
   tested; this is not.

2. **Yandex as a third search backend.** `searchapi.api.cloud.yandex.net` is
   OPEN and both `YANDEX_SEARCH_API_KEY` and `YANDEX_FOLDER_ID` are already
   set. Probed without auth it returned a schema hint rather than a refusal:

   ```
   POST /v2/web/search  {"query":{"queryText":"test"}}
   -> 400  "query.search_type: Field is required"
   ```

   **Not built, and deliberately not called: the pricing is unverified and the
   key belongs to the owner's Yandex Direct work.** Ask before spending.

3. **The allowlist request** — six hosts in `denied_hosts.jsonl`, each with the
   question it blocked. Lead with `docs.cloud.google.com`: the parent
   `cloud.google.com` is already permitted, so it is a narrowing.

4. **The retrieval quota.** `MAX_PER_PROVENANCE = 2` in `studio/knowledge.py`
   and all 4601 gallery rows share one provenance, so **exactly 2 records ever
   reach the voter** (measured: k=12 asked, 2 returned, 2464 turned away).
   `MIN_SUPPORT` is 2, so corpus filling works only when those two agree.
   Fixing it means either tagging the corpus with real provenances or raising
   the quota — the owner's call, and it is another module's file.

5. **Nothing has been proven by a generation.** No prompt from this package
   has been rendered and rated. That needs a paid call plus a blind rating.

## Measured negative results — do not re-derive these

- **Clause splicing from the corpus is a dead end.** It passed the contract
  gate and produced a prompt carrying somebody else's laptop and sleigh.
  Replaced by voting on look attributes, which carry no scene.
- **The `probe` channel reveals nothing on Kling.** With a live key, `duration`,
  `aspect_ratio`, `mode` and `model_name` all return the identical
  `code 1201 "value is invalid"` and never name the allowed set. It costs
  nothing and answers nothing there. `max_seconds` 10-vs-15 stays contested.
  Recorded as `kling-3.0.probe_discloses_limits`.
- **"Search the entire web" is gone** from new Programmable Search engines
  since March 2026; a new engine is capped at 50 domains. That is why Gemini
  grounding is the recommendation.
- **BM25 alone scores identically to four-channel fusion** on the shipped
  fixture. The fusion is unproven, not proven.

## Defects found by tools in this session, all fixed

Kept because each is a shape worth grepping for:

1. A corpus colour was **added** to a palette the owner had already filled, and
   the provenance label said `from: "owner"` while carrying corpus ids.
2. `saturation` could never be filled from the corpus — one slot had a
   different rule from every other slot.
3. An empty intent returned **no questions**, failing the caller who needed
   them most.
4. An **unrecognised tier reached `pass`**: it sorted below `blog` but the
   "is this only blogs" check compared by name, so a typo sailed past.
5. `advice.py` **restated** the tier ladder instead of importing it, and the
   copy went stale the moment `probe` was added — `record` refused the tier its
   own module had introduced.
6. `probe.py` looked for `KLING_API_KEY` while the environment sets
   `KLING_KEY`, so it reported "no API key" beside a working one.
7. The handshake's negative control (`"a woman in a red dress"`) went red on
   the **word band**, not the subject guard, and stayed green with the guard
   disabled — it was measuring nothing.
8. A mutation run was read through a stale `__pycache__`: `sed` replaced a
   constant with one of equal byte length in the same second. Mutation runs
   use `python -B` with caches cleared.

## House rules this package leans on

`I1` a verdict is cast by somebody who did not build the thing — hence
`studio/mcp/fixtures/blind_control_set.py`, 54 cases written by an agent
forbidden to read the implementation, which found defects 1–3 above.
`P1` three outcomes everywhere; zero checks is never `pass`.
`T1` mutate decision constants both ways; `T2` expected values are literals.
`C3` never route around a policy-closed host.
`C11`/`C12` (added this session) measure before concluding "no access", and an
API error means a missing key rather than a missing permission.

---

# Session 2026-08-27 (later) — the key had arrived; two defects it uncovered

Appended, nothing above rewritten.

## 1. The Gemini key was there all along, spelled `Gemini_API_KEY`

The previous session concluded the key had not arrived. It had. `os.environ`
is case-sensitive on Linux, the package listed `GEMINI_API_KEY`, and so it
reported "no key" beside a working 53-character one — and a session was spent
believing the credential was missing.

This is the **second** time in this package: `probe.py` looked for
`KLING_API_KEY` while the environment set `KLING_KEY`. One shape —
**a lookup that guesses at a name will meet a name somebody else chose.**

Fixed in one place, `studio/mcp/credentials.py`, imported by both `search.py`
and `probe.py`; neither reads `os.environ` for a credential any more. Exact
names still win where they exist; only when nothing matches exactly does a
case-folded pass run, over `sorted(os.environ)` so two spellings resolve the
same way on every run. The name reported back is **the spelling that was
found**, not the one that was expected — that difference is the thing the
owner needs to see.

Grep shape for the next one: any `os.environ.get(<a credential name>)`.

## 2. The live Gemini call: the parsing was right, the bookkeeping was not

`search("Kling 3.0 max duration seconds API")` → `pass`, backend `gemini`,
7 grounded sources, answer body present. The documented shape held exactly:
`candidates[0].groundingMetadata` with `groundingChunks[].web.{uri,title}`
and `webSearchQueries`. `title` really is the publisher domain, `uri` really
is a `vertexaisearch.cloud.google.com` redirect. **`_gemini()` needed no
change**, and its UNVERIFIED paragraph is now a MEASURED one.

What the live call *did* expose: that one query wrote **five hosts nobody had
ever wanted** (atlascloud.ai, magnific.com, kie.ai, evolink.ai, wavespeed.ai)
into `denied_hosts.jsonl` — the file a human reads to decide what access to
grant, which until then held six hosts a real question was stuck behind. The
per-host `fetchable` probe records a refusal like any other, and `wanted()`
was announcing all of them as "needed for a real question". A few more
searches and the ask the owner has to justify is mostly noise.

Fix: `note_denial(..., incidental=True)`, threaded through `fetch()` and set
by `search._fetchable`. Refusals are **still all recorded** — routing around
one is what is forbidden, counting it is not — but `wanted()` now returns
`hosts` (the ask) and `also_refused` (swept up), and only-swept is
`could not measure`, never `pass`. A host first met by a probe and later
actually needed is promoted into the ask, so the order two calls happened in
no longer decides whether the owner ever hears about a host they need.

Measured after the fix, on a second live search: ask still the same 6 hosts,
8 swept hosts filed apart.

## Mutation runs (T1), `python -B` with caches cleared

Eight decision points, mutated both ways; all red, with two rounds needed:

| mutation | result |
|---|---|
| credentials: exact name only | red |
| credentials: exact match not preferred | red **(green at first — see below)** |
| credentials: non-deterministic order | red |
| credentials: whitespace counts as a value (both passes) | red (green at first) |
| `wanted`: swept hosts enter the ask | red |
| `wanted`: only-swept returns `pass` | red |
| `wanted`: a real question does not outrank a probe | red |
| `search`: the reachability probe is recorded as an ask | red **(green at first)** |

Two tests were measuring nothing and were rewritten (house rule И5):

- `test_an_exact_name_beats_a_case_folded_one` used
  `GEMINI_API_KEY`/`gemini_api_key`, where ASCII sort order happens to agree
  with the rule — it stayed green with the exact-match pass deleted. Now
  `GEMINI_Api_Key`/`GOOGLE_API_KEY`, where sort order disagrees.
- the whitespace test only exercised one of the two lookup passes.

And the defect site itself — `search._fetchable` marking its probes
incidental — had no test at all until the mutation said so.

`bash scripts/check` exits 0; blind control set 54 checked, 0 violations,
0 unmeasured.

Note: `mypy` and `mcp` are not preinstalled in a fresh container, so
`scripts/check` fails at its third step until
`python3 -m pip install --ignore-installed PyJWT -r requirements-dev.txt`
runs. `--ignore-installed PyJWT` is needed because a debian-owned PyJWT has
no RECORD file and pip refuses to uninstall it.

## What the two live searches said, NOT recorded as facts

Search-tier, and the source URLs are Google redirects that do not open, so
nobody has read the publisher. Left for the owner to decide the tier:

- Kling 3.0: "a single generation is typically capped at 10 seconds, 5 the
  default". Bears on the CONTESTED `max_seconds` 10-vs-15 but does not settle
  it — this is a grounded summary, not a vendor page.
- Veo 3.1: "8 seconds native single-pass, 4/6/8 at 720p and 1080p, 4K locked
  at 8", extendable beyond that.

## Still waiting on the owner, unchanged

The four items in the previous section stand: the six-host allowlist request
(lead with `docs.cloud.google.com`), Yandex as a third backend (open, keyed,
**price unverified and the key is the owner's ad-work key**), the
`MAX_PER_PROVENANCE = 2` quota in another module's file, and the fact that no
prompt in this package has been proven by a generation.

---

# Session 2026-08-27 (later still) — the owner's tier ladder

Appended. Owner's decision, given in chat:

> 1. url вендора модели
> 2. специализированные порталы обмена артефактами, промтами и пр
> 3. блоги и прочее

Two follow-up questions were put to the owner before any code moved, because
either answer changed the work materially:

- **probe and paper, which the list does not name** → *insert the portal rung,
  keep the others*. So `TIERS` is now
  `(vendor, probe, paper, benchmark, portal, blog)`; nothing was removed and
  nothing else moved.
- **a vendor URL nobody could open** (the host is refused, the fact is known
  only through somebody's summary) → *tier by the URL, plus a flag for whether
  it was read*. Not tier by what was actually read.

## What the ladder was measuring before, and what it is now

The old `tier` recorded HOW a fact was obtained. The owner's ladder records
WHOSE PAGE IT IS. Those are different axes, and the old single rung was doing
three jobs at once. Measured over the 47 facts, `blog` held:

- **9 vendor pages** — kling.ai, docs.bfl.ai, help.runwayml.com,
  docs.byteplus.com, cloud.google.com, bfl.ai
- **11 platform pages** — wavespeed.ai ×4, piapi.ai ×2, evolink.ai,
  apiframe.ai, fal.ai, gaga.art, atlascloud.ai
- the actual press

Both axes are now kept. `vendor`, `portal` and `blog` are read off the URL by
`studio/selfrag/source_hosts.py`; `probe`, `paper` and `benchmark` describe how
the fact was obtained and stay the recorder's to state, because no URL can say
whether an API was asked.

`advice.record()` **refuses** an identity tier the URL contradicts, naming the
host, rather than quietly correcting it — a caller who is wrong needs to find
out, and a caller who is right needs the table updated.

## Consequences, measured

`scripts/retier_facts.py` (in the repo, re-runnable, idempotent — a second run
reports 0 changes):

```
rows 47, tier changed 16      blog -> vendor 10,  blog -> portal 6
read_directly: False 25, None 21, True 1
claims() over every (model, attribute):
    before   pass  9   fail 3   could not measure 23
    after    pass 24   fail 3   could not measure  8
```

**15 attributes went from `could not measure` to `pass`** — they were no longer
blog-only. Ten of those rest on vendor pages nobody opened, which is exactly
what the owner's flag is for, so `claims()` now counts unread sources, says so
in its note ("N of M source(s) were NOT read"), and returns
`sources_not_read` / `sources_reading_unrecorded`. The verdict is NOT demoted
for it: the owner set the ladder, and a counter was added rather than a policy
invented (house rule П1).

A visible improvement straight away: `kling-3.0.max_seconds` now reads
`'10' (blog)` against `'15' (vendor)` — the 15 comes from Kuaishou's own
investor release. Still `fail`/contested, correctly; but the sides are now
distinguishable, which they were not when both read `blog`.

`read_directly` is three states and `None` is not `False`. It was filled from
evidence only: the note saying "read via summary", or the host being recorded
in `denied_hosts.jsonl` as policy-refused, plus the one probe row (the API
answered us). Everything else stayed `None`.

## Defect found by the blind control set, again

Case A8 (positive control for `record()`) went red: it records a
`deepmind.google` claim about **`veo-3`** while the table listed `veo-3.1`, so
the fact was refused. The table was keyed by model id — meaning **every
unreleased version is locked out of the first rung until somebody edits the
table**, and a rule needing an edit per release will be wrong by the next one.

Now keyed by model FAMILY, matched exactly or up to a `-`/`.` separator, so
`wan` claims `wan-2.6-flash` and not `wandering-model`, and longest match wins
so a family can be split later. That is the third defect this control set has
found, and the second one that no test of mine would have caught.

## Mutations (T1), `python -B`, caches cleared — 12, all red

Ladder: portal below blog; portal above vendor. Table: a platform's blog post
counts as the platform; vendor not bound to the model; path ignored; prefix
without a separator; first family wins instead of longest. Flag: `None` folded
into `False`; unread not named in the note; absent read as `False`. Record:
tier taken on trust; method tiers rewritten from the URL.

Two were green at first and needed a test written: **method tiers surviving a
vendor URL** (a `probe` on the vendor's own API classifies as `vendor` by host
— erasing that would lose the difference between the vendor's docs and the
vendor's API answering), and the family-longest-match rule.

`bash scripts/check` exits 0; blind control set 54 checked, 0 violations,
0 unmeasured.

## Found, NOT fixed — the owner's call

**Seven facts cite a bare site root** with no path: `wavespeed.ai/` ×3,
`skywork.ai/` ×2, `fal.ai/`, `docs.bfl.ai/`. Five of them now sit above `blog`
on the strength of a link that points at no statement — you cannot go and check
`best_for = "motion control and camera work"` against `https://wavespeed.ai/`.

A rule suggests itself (a root URL earns no rung above `blog`) but it was NOT
added: one of the seven is `docs.bfl.ai/` supporting
`flux-2.expands_internally = unknown`, i.e. "we looked at the docs and found no
statement" — for a negative finding a doc-root citation is legitimate. Telling
the two apart is a judgement the owner did not ask for. Decide and it is a
five-line change.

---

# Session 2026-08-27 — Civitai and the ComfyUI subreddit, asked about by the owner

> «ComfyUI Subreddit и Civitai API очень большие и достоверные источники данных,
> там комьюнити выкладывает свои воркфлоу, составляют описания и приводят
> результаты. Это можно как-то собирать?»

Measured before designing anything. **Both are refused by the egress policy —
7 of 7 hosts, 0 open:** `civitai.com`, `api.civitai.com`, `image.civitai.com`,
`reddit.com`, `www.reddit.com`, `oauth.reddit.com`, `old.reddit.com`. Not
routed around (C3). They are now in `denied_hosts.jsonl` carrying the owner's
own reason, so the ask is 13 hosts rather than 6.

## A licence blocker that outranks the network one

НЕПРОВЕРЕНО (C4) — from Gemini grounding, since both hosts are shut and no
terms page was read by anyone:

- **Reddit Data API**: free tier is 100 QPM per OAuth client, and **commercial
  use is prohibited on it without Reddit's explicit approval**; new apps need
  approval under a "Responsible Builder Policy". Commercial access is a
  contract, reported around **$0.24 per 1,000 calls** and a tier starting near
  **$12,000/month**. This repository is a commercial content-creator service,
  so the free tier is very likely not available to it *whatever* the proxy
  says. **This needs the owner's decision and possibly money before any
  collector is worth writing** (C5: the licence is checked before the
  integration, not after).
- **Civitai**: a public REST API at `https://civitai.com/api/v1/`, with
  `/images` returning user-submitted images and their generation metadata —
  which is exactly the prompt-plus-result pairing this project has none of.
  Per-upload licence terms were NOT established and are the open question.

## What was done anyway, because it is testable now

Both sources are in the tier table, so if access arrives their facts land on
the right rung with no further thought:

- `civitai.com` → `portal`
- `reddit.com/r/comfyui/` and `old.reddit.com/r/comfyui/` → `portal`;
  `reddit.com/r/aww/` → `blog`

A subreddit where people post workflows with the results they got is the
owner's middle rung by their own description; Reddit as a whole is a forum.
The rung is claimed **by path**, which is what the path-prefix mechanism was
built for. A sibling community is one line.

## The same defect, found a second time in an hour (rule И7 earning its keep)

`reachability()` — the other bulk sweep — recorded every refused host into the
allowlist request under the reason `"reachability probe"`. Fixed the same way:
a sweep with no question is incidental; `reachability(hosts, why_wanted=...)`
and the `reachable_hosts` tool now take the question, and a host really wanted
is promoted into the ask. The earlier fix to `search._fetchable` had not been
grepped for its own shape — that is what И7 says to do and it was not done.

Ask now: 13 hosts with real reasons; 8 incidental, listed apart.

## Not built, and why

No collector was written. It cannot be exercised against a live API from here,
so it would be code nobody has run — and the Reddit licence question may make
part of it moot. The shape is understood and it is a short job once the two
answers exist:

1. does the owner get the hosts opened, and
2. is Reddit's commercial tier acceptable, or is Civitai alone the target?

`bash scripts/check` exits 0; blind control set 54 checked, 0 violations,
0 unmeasured.
