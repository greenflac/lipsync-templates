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

---

# Session 2026-08-27 — the allowlist request, assembled and rendered

The owner asked for a final host list to add to the whitelist, then a handoff.

## First, correcting the premise: web access EXISTS, it is just narrow

"У нас всё ещё нет доступа к вебу?" — no, we have it, and it worked twice in
this session. Re-measured across 51 hosts: **15 open, 36 refused.**

Gemini grounding search runs and returns real results
(`generativelanguage.googleapis.com`). The vendors' **API** hosts answer
(`api.klingai.com`, `api.fal.ai`). `cloud.google.com`, `github.com`,
`huggingface.co`, `pypi.org` all answer. What is shut is almost every
**documentation** host and **every** community platform. That shape is the
whole problem: we can call the models but not read about them, and we can
search the web but not open most of what the search returns.

## `docs/ALLOWLIST_REQUEST.md` — generated, not typed

`scripts/allowlist_request.py` probes each host NOW, records the refusal with
its own question, and renders the document. Re-run it and a host that has since
opened drops off by itself; a hand-typed list would not.

**20 hosts asked for**, in groups ordered by how cheap they are to say yes to,
so the list can be cut at any group boundary:

1. **a narrowing** — `docs.cloud.google.com` (parent `cloud.google.com` is
   already open, so this grants no new organisation)
2. **settles a contradiction** — `kling.ai`, `help.runwayml.com`,
   `ir.kuaishou.com`
3. **vendor pages nobody has read** — `docs.bfl.ai`, `docs.byteplus.com`,
   `elevenlabs.io`, `help.elevenlabs.io`, `ai.google.dev`,
   `platform.openai.com`
4. **the paper rung** — `arxiv.org` (10 paper-tier facts, not one read)
5. **community corpora** — `civitai.com`, `api.civitai.com`,
   `image.civitai.com`, `www.reddit.com`, `reddit.com`, `oauth.reddit.com`,
   `old.reddit.com`
6. **platforms already cited** — `fal.ai`, `wavespeed.ai`

The document also lists the **15 already-open hosts** (re-measured on every
run, so nobody is asked for access they already have) and the **23 incidental**
refusals that are deliberately NOT part of the ask.

Reddit carries the licence caveat from the previous section, restated in the
document itself: its free Data API tier reportedly bars commercial use.

## A defect found by reading what was produced (rule П3)

Six hosts came out of the generator still carrying reasons written days
earlier, because `wanted()` kept the FIRST row per host. One of them,
`docs.bfl.ai`, was being asked for on the grounds that "every recorded claim
about it is blog tier" — **which the re-tiering had made false that same
morning**. A stale reason in a request a human has to justify is worse than a
short one.

Fixed: `denied_hosts.jsonl` stays append-only, a re-probe with a DIFFERENT
reason appends a row (an identical one does not, so the generator is
idempotent — verified, 63 lines before and after a second run), and `wanted()`
now presents the LATEST reason per host. The history of how a request was
argued is readable back from the file.

3 mutations both ways, all red. One existing test encoded the old
first-reason-wins rule and was updated rather than deleted.

## Next session: start here

1. `bash scripts/check` — exits 0 today. Note `mypy` and `mcp` are not
   preinstalled: `python3 -m pip install --ignore-installed PyJWT -r
   requirements-dev.txt`.
2. **Re-run `python scripts/allowlist_request.py`.** If the owner has granted
   hosts, the granted ones vanish from the ask by themselves and the document
   shrinks. That is the signal to start reading vendor pages and recording
   facts with `read_directly=True`.
3. If Civitai opened, the collector is the next real piece of work: the
   `/api/v1/images` endpoint returns prompts WITH results, which is the pairing
   this project has never had. Tier it `portal` (already in the table). Check
   the per-upload licence FIRST (rule C5).
4. If Reddit did not open, or its commercial terms are refused, drop it and
   say so — do not keep it in the ask indefinitely (rule C9: a stop condition
   is written before the attempt, not after).

## Still open from before, unchanged

`MAX_PER_PROVENANCE = 2` in another module's file; Yandex as a third search
backend (open and keyed, price unverified, owner's ad-work key); no prompt in
this package has been proven by a generation; the 7 facts citing a bare site
root, 5 of which now sit above `blog` on a link pointing at no statement.

---

# Session 2026-08-27 — wildcards, because the owner was right

> «а разве не лучше wildcard использовать в вайтлисте, полетит ведь опять
> доступность по субдоменам»

Yes. Measured, rather than agreed with:

- **`cloud.google.com` is OPEN and `docs.cloud.google.com` is REFUSED.** A
  subdomain of an already-granted host was not covered by that grant, so the
  whitelist matches exact hosts today. The failure the owner predicted has
  already happened once.
- Probing sibling subdomains of the SAME vendors already in the request found
  **23 more, every one refused, and not one of them on the 20-host list** —
  `api.bfl.ai`, `app.klingai.com`, `docs.elevenlabs.io`, `seed.bytedance.com`,
  `developers.reddit.com`, `www.civitai.com`, `export.arxiv.org` and the rest.
  Each would have been another round of asking.
- **The sharpest case: `export.arxiv.org`.** The exact list asked for
  `arxiv.org`, the human-facing site. arXiv's API is on `export.arxiv.org` and
  arXiv asks programmatic users to go there instead (UNVERIFIED — grounded
  search, since arxiv.org is refused and nobody read the manual). The exact
  grant would have handed us the pages we should not be scraping and left the
  endpoint we should be using shut.

`docs/ALLOWLIST_REQUEST.md` now leads with the wildcard form: 14 registrable
domains, each as `*.domain` plus the bare apex, since a wildcard does not
always cover the apex and for several of these the apex is itself a host we
want.

## Where a wildcard is the WRONG ask, and why that is in the table

- `google.com` → **not** `*.google.com`, which is Search, Mail, Drive and
  everything else Google runs, for the sake of one documentation subdomain.
  Asked as `*.cloud.google.com` — a wildcard UNDER a host already permitted.
- `google.dev` → **not** `*.google.dev`. `ai.google.dev` is the only host under
  it this project needs and it is the host itself, so a wildcard buys nothing
  and grants Google's other developer sites for free.

Vendors spread across several registrable domains — Kling uses `kling.ai`,
`klingai.com` AND `kuaishou.com` — so a wildcard is per domain, not per vendor.
`klingai.com` was added to the request while writing this: `api.klingai.com`
under it is already open and is the API this project calls, while the domain
itself and `app.klingai.com` are refused. 21 hosts asked for now, 14 domains.

## Two defects found by reading the rendered file (rule П3, again)

1. The exceptions were rendered **inside the code fence**. A block that has to
   be edited before it is pasted is a block that gets pasted wrong.
2. The prose claimed Kling uses `klingai.com` while the generated list did not
   contain it — the text promised what the list did not deliver.

Both are now gated: `studio/mcp/tests/test_allowlist_request.py` asserts that
nothing but hostnames reaches the paste block, that every host in `WANTED` is
covered by something in the block, and — the negative control — that
`mail.google.com` and other strangers are NOT covered. 4 mutations both ways,
all red.

## For the next session

Run `python scripts/allowlist_request.py`. Whatever the owner granted vanishes
from the ask by itself; whatever is still listed is still shut. If the wildcard
form was accepted, expect `export.arxiv.org`, `api.bfl.ai` and the other 21
siblings to be open too — probe before assuming, `reachable_hosts` takes a
comma-separated list now.

---

# Session 2026-08-27 — the grant landed, and the request closed itself

The owner added the wildcard list to the environment's whitelist. **It took
effect live, with no container restart** — unlike the Gemini key, which needed
one.

## Measured immediately

**41 hosts now answer.** All 21 that were asked for, plus **20 sibling
subdomains that were never asked for individually** — which is the wildcard
argument coming true:

```
api.bfl.ai  api.dev.runwayml.com  api.elevenlabs.io  api.openai.com
api.wavespeed.ai  app.klingai.com  bfl.ai  byteplus.com  cdn.openai.com
console.byteplus.com  dashboard.bfl.ai  developers.reddit.com
docs.dev.runwayml.com  docs.elevenlabs.io  docs.fal.ai  export.arxiv.org
openai.com  orchestration.civitai.com  static.arxiv.org  www.civitai.com
```

`export.arxiv.org` — the arXiv API host, which the exact-host list would have
missed — is open. So is every host named in the argument for wildcards.

**Still refused, 15**, and only two are interesting: the apex `runwayml.com` is
shut while `help.runwayml.com` and `docs.dev.runwayml.com` under it are open,
so wildcards were granted and some apexes were not. `wan.video`,
`seed.bytedance.com`, `tongyi.aliyun.com` and `deepmind.google` were never in
the ask. The remaining ten are incidental sweep hosts nobody wanted.

`docs/ALLOWLIST_REQUEST.md` now reads **CLOSED**.

## The defect the grant exposed, within a minute of it landing

The request is assembled from refusals that happened, and **a refusal never
expired**. The moment 21 hosts were granted, the generator went on asking for
all 21 — and the docstring I had written an hour earlier claimed "re-run it and
a host that has since opened drops off by itself", which was simply false.

A request that asks for access already granted is worse than no request: it is
the reason the next one does not get read.

Fixed: `denied_hosts.jsonl` is now a log of STATE CHANGES. Rows carry
`state: "refused" | "open"` (absent means refused — every earlier row was one),
`note_open()` writes one row the first time a refused host answers, and
`wanted()` reads the latest row per host. `fetch()` calls it on any successful
response INCLUDING an HTTPError, because a 404 on a bare root is a very common
way for a granted host to greet us — so the ask retires itself through ordinary
use, not only when somebody re-runs the generator. A grant withdrawn puts the
host back. `wanted()` distinguishes three ways of having nothing to ask for:
all granted (`pass`), granted plus incidental leftovers, and nobody ever asked.

5 mutations both ways. Two rounds were needed and both misses were the same
shape: **a test passing through a path other than the one it named.** The
revocation test was satisfied by the restatement rule because the reasons
differed; given identical reasons it was satisfied by the restatement rule
again, because an `open` row carries no reason and reset "the latest reason",
making the reopening rule dead code. `latest_reason` now considers refusal rows
only, the reopening rule is load-bearing, and the mutation goes red.

## Where the project actually stands now

The premise that has shaped every session so far — "the vendors' docs are
unreachable, so everything is second-hand" — **is no longer true.** As of now:

- 25 of 47 facts are marked `read_directly=false` and 21 `None`. Nearly all of
  those hosts are now open, so those facts can be replaced by ones somebody
  actually read.
- 10 paper-tier facts cite `arxiv.org` and none was read. `export.arxiv.org` is
  the API and it answers.
- `civitai.com/api/v1/images` answers. That is prompts WITH the results they
  produced — the pairing this project has never had.
- Reddit answers, but its licence question is untouched and unchanged: the free
  Data API tier reportedly bars commercial use. **Measured reachability does not
  settle a licence.**

---

# Session 2026-08-27 (later) — the reading pass, and what reading changed

The grant held: `python scripts/allowlist_request.py` re-probed and the document
read CLOSED at the start of this session. So the work the previous handoff
listed as "next" was possible for the first time, and this session did it.

## Start here next time

```
python3 -m pip install --ignore-installed PyJWT -r requirements-dev.txt
bash scripts/check          # exits 0; blind control 54/0/0; 11 tools now
```

`scripts/check` gained a step: `python scripts/read_sources.py --check`. It
reads the fact file only — no network — and fails if a claim the reading pass
withdrew has come back or a recorded reading has been edited away. Verified by
mutation in both directions.

## The mechanism the reading needed, and the defect it prevented

Re-recording a fact you have now READ is not a second source agreeing with the
first. Before this session it was: `record` appended, nothing collapsed, and
upgrading `kling-3.0.max_seconds` after opening the Kuaishou release would have
made `claims()` report two sources for one page, with `checked` inflated and
the note reading "1 of 2 source(s) were NOT read" about a page that had been.

`model_facts.jsonl` is now a LOG. Latest row per
`(model, attribute, value, source_url)` wins; a row with `"withdrawn": true`
removes the claim and keeps the reason. Same shape as `denied_hosts.jsonl`.
The value is in the key deliberately — `seedance2-video.com` states `12` in its
headline and `4 to 15` from the report it cites, on one page, and keying
without the value would have hidden a source contradicting itself.

**Eleventh tool: `withdraw_model_fact`.** For the other thing reading finds —
a claim whose page does not make it. It appends, it demands a reason, and
withdrawing something nobody recorded is `could not measure`, never `pass`.

15 mutations both ways, all red. **Three were green at first and all three were
one shape: no test moved ONLY the field the reading pass moves.** Every
supersession test also changed the note, so dropping `read_directly`, `tier` or
`stated_on` from the compared fields broke nothing anybody checked. That is the
fourth time in this package that a test passed through a path other than the
one it named.

## What the reading actually found

`scripts/read_sources.py` is the pass, in the repository and re-runnable,
because provenance living in a chat log cannot be checked. Of the 39 URLs the
base cites, **18 opened**. Of the 24 claims behind them:

- **8 confirmed word for word** — and those notes now quote the page.
- **8 said something materially different.**
- **6 rest on a page that does not make the claim at all**, now withdrawn with
  the string that is missing.

`read_directly` went from 1 True to 18. The base asserts 49 claims where it
asserted 47, and six of the old ones were unsupported.

### The bare-root question is answered by measurement

The previous handoff left it for the owner: 7 facts cite a site root, 5 of them
above `blog` on a link pointing at no statement. Of the roots that opened, **not
one supports its claim**:

- `wavespeed.ai/` is cited for what Veo 3.1 is best for and contains **0**
  occurrences of "Veo"; **0** of "motion control"; **0** of "9 images".
- `fal.ai/` is cited for how to write an image-to-video prompt and is a GPU
  pricing page.
- `docs.byteplus.com/en/docs/ModelArk/1587798` is cited twice for Seedance 2.0
  and documents **seedance-1.0-pro**, 2~12 seconds, with `camera_fixed`
  appearing nowhere on it.

The one exception is the one that was predicted: `docs.bfl.ai/` carrying
"no expander documented". A doc index is the right citation for a negative
finding — you cannot cite the page that does not exist. No rule was invented;
the evidence is now on the record for the owner to make one from.

### The correction that matters most

**arXiv 2407.14333 was revised to v7 on 2026-01-07 and retitled.** This base
carried "automatic GPT-4 rewriting erased 58% of DALL-E 3's performance gain,
N=1891" — the current abstract reports 3,750 participants and ~37,000 prompts
and contains neither figure. The anti-expander finding survives in weaker form
("automated rewriting cannot generally substitute for human adaptation; aligned
it modestly helps, misaligned it actively undermines the gains").

And v7 adds something that **qualifies this project's own thesis**, recorded
and NOT acted on: *in an open-ended creative task, prompt adaptation plays a
limited role and improvements are driven primarily by model capability.*
Writing generation prompts is that task. The "roughly half the gain" figure
this project leans on belongs to the fixed-criteria task, not to ours.

Other corrections: VBench does not name the artifact taxonomy attributed to it
(only "flicker" overlaps its 16 dimensions); oversaturation at high CFG is the
component of the update term PARALLEL to the conditional prediction, not an
off-manifold trajectory; Veo's prompt formula has five parts, not eight; Kling's
keeps its last group optional, which the summary dropped; FLUX.2's 32B belongs
to `[dev]`, the open-weight derivative, not to the base transformer.

Two dates were wrong and are corrected from the pages: the Kling prompt guide
is dated 2025-11-24 and describes **model 2.0 at 5 or 10 seconds** — a 3.0 fact
was resting on a 2.0 page — and Google's Veo guide is 2025-10-16. **33 of the
47 rows carried the harvest date instead of the source's**, which is exactly
how a stale claim looks fresh.

### A source nobody had used

**Runway publishes an OpenAPI document at
`https://docs.dev.runwayml.com/openapi.json`** with duration and ratio enums
PER MODEL, for the models it resells as well as its own. A validated enum beats
every prose page, and it carries its own negative control:

| | duration | 4K ratios |
|---|---|---|
| `gen4.5` | 2..10 | none; largest is 1280:720 |
| `veo3.1` | enum [4, 6, 8] | none |
| `seedance2` | 4..15 | 3840:2160 and five more |
| `seedance2_5` | 4..30 | none |

So `runway-gen-4.5.max_resolution` is 720p **because the same schema offers 4K
to another model and not to this one** — the absence is the schema saying no,
not the schema being silent. `docs.dev.runwayml.com` is now on BOTH source
tables: vendor for the `runway-gen` family, portal for the endpoints it merely
runs. One host, two rungs, decided by which model the claim is about.

The spec also names `kling3.0_pro`, `kling3.0_4k` and `kling3.0_standard` in
its model list, but no request schema constrains them, so **`kling-3.0`
max_seconds stays contested** — `'10'` (blog, host still refused) against
`'15'` (vendor, now read first-hand).

## Civitai: the collector died twice, and the licence was read

Rule C5, first-hand this time rather than a grounded summary.

- **Licence.** ToS 6.1 grants access "solely for your personal, non-commercial
  use". ToS 11.4 permits automated access only through the public API with your
  own credentials and within rate limits, "or as we otherwise authorize in
  writing". So the CHANNEL is sanctioned and the USE is not — this repository
  is a commercial service. Per-upload model licences (Anima, LTX-derived,
  Cosmos-derived) stack their own restrictions on top.
- **The data is not there anyway.** MEASURED, unauthenticated: 300 images across
  three pages of `/api/v1/images`, `meta` null on **300 of 300**. No prompt, no
  sampler, no seed. Also null for `?postId=`, `?sort=Newest`,
  `?sort=Most Reactions`. Third outcome kept: this environment holds no Civitai
  credential, so whether a key unlocks the metadata is NOT measured.

Both are recorded as `civitai-api.licence` and
`civitai-api.prompt_metadata_exposed`, so the next agent meets them through
`model_advice` before proposing the collector for a third time. **No collector
was written.**

## Reddit: still the owner's call, and still unreadable

`reddit.com`, `www.reddit.com`, `old.reddit.com` and `developers.reddit.com`
all answer. **The terms do not live on any of them.** `www.redditinc.com` and
`support.reddithelp.com` are both refused by the policy, so the claim that the
free Data API tier bars commercial use stays UNVERIFIED (C4) and cannot be
checked from here. Not routed around; both hosts are in the ask with that
question as their reason.

## The allowlist generator, third defect of the same shape

The block a human pastes was built from `WANTED`, the seed list of hosts the
generator probes — and a host stays in that list forever. So the day after the
grant, the document offered fourteen already-granted domains under a header
saying sixteen hosts. Fixed: the block is built from the measured ask. Two
tests, five mutations, all red, including the negative control that a granted
domain must be ABSENT.

Two more staleness bugs in the same file: the wildcard argument was still being
argued from examples that had since been granted (replaced by its outcome —
21 asked over 14 domains, 41 answered), and "already open" was re-measured
against a 15-host literal while the proxy answered 41.

**The ask is 16 hosts now.** 14 are pages this base cites that nobody could
open; two of those settle live contradictions and say so in their own reason
(`www.atlascloud.ai` for Kling 10-vs-15, `gaga.art` for Gen-4.5 720p-vs-4K).
The other two are the Reddit terms. The rest are blog-tier corroboration and
the list can be cut at any group boundary.

## Waiting on the owner

1. **Reddit.** Its terms cannot be read from here. Open the two hosts, or
   decide from outside, or drop Reddit — C9 says the stop condition is written
   before the attempt, and there is not one yet.
2. **Civitai.** Ask under the written-authorisation clause, or drop it. Note
   that even with permission the anonymous API returns no prompts, so the
   question is really "is a Civitai API key worth getting".
3. **`huggingface.co/Wan-AI/`.** `huggingface.co` is on the portal rung. A
   model card in the VENDOR'S OWN organisation is the vendor's page, and `wan`
   already has exactly this shape for GitHub (`github.com/Wan-Video/`). One
   line, not added without the owner saying so.
4. Unchanged from before: `MAX_PER_PROVENANCE = 2` in another module's file;
   Yandex as a third search backend (open, keyed, price unverified, and the key
   is the owner's ad-work key); **no prompt in this package has been proven by
   a generation.**
5. New: `veo-3.1.max_seconds` now reads `'8'` against `'8, quantised to 4/6/8'`
   and is reported as contested. Those are the same claim spelled twice. The
   base has no notion of value normalisation and inventing one silently would
   be worse than the contest — but it is the next thing that will annoy a
   reader of `model_advice`.

---

# Session 2026-08-27 (last) — the licence was cleared, so the collectors got built

> «Решили вопросы лицензий с юристом, получили разрешения, юридические риски
> отсутствуют. За тобой техническая реализация.»

Recorded as `rights: "owner_authorisation_2026-08-27"` on every collected row,
and in `studio/knowledge/PROVENANCE.md` beside the ToS text it is an exception
to. The ToS wording is kept deliberately — an authorisation you cannot see the
shape of is one nobody can check later.

Two collectors were asked for. **One collects; one cannot, and the reason is
not the licence.** Both answers came from measuring before building.

## Civitai — collecting, 473 pairs on target families

`studio/mcp/civitai.py`, run by `scripts/collect_civitai.py`.

**The plan two sessions carried was aimed at the wrong endpoint.** Measured,
unauthenticated, all three routes:

| route | meta |
|---|---|
| `/api/v1/images` | null on **300 of 300** — also for `?postId=`, `?sort=Newest`, `?sort=Most Reactions` |
| `/api/v1/models` | `hasMeta` and `hasPositivePrompt` FLAGS, `meta` null on **0 of 1754** |
| `/api/v1/model-versions/{id}` | populated — **60 of 63** carry a prompt |

So the walk is: list models, take version ids, fetch each version. The listing
is what makes it affordable — `hasPositivePrompt` says in advance which
versions are worth a request, and 499 of 2284 were skipped without one.

`civitai-api.prompt_metadata_exposed = "no"` was in the fact base from the
previous session. It was measured on ONE route and stated about the API, so it
is withdrawn and replaced by a claim per endpoint. **Worth knowing for next
time:** `replaces` in a reading only withdraws at the SAME url — correct, since
a claim is identified by its source — so a correction that moves to a DIFFERENT
source needs an explicit `WITHDRAWN` entry. This one did.

### Three defects, each found a different way

1. **By looking at the summary.** The first run: 29 pairs, ONE uploader. The
   listing arrives grouped by model, so any ceiling cuts inside the first one.
   The walk is now round-robin by (uploader, model) — same set collected, only
   the order changes. Re-run: 170 pairs, 20 uploaders.
2. **By looking at the base-model column.** 750 pairs by Most Downloaded gave
   368 SD 1.5, 127 SDXL — and **zero** rows on any family this project
   targets. Civitai hosts weights, so our closed API models are barely there.
   `--base-model "Flux.1 D"` and friends reach the open-weight ones. The filter
   is CASE-SENSITIVE and an unknown name returns 200 with an empty list, so a
   typo collects nothing in silence; an empty harvest under a filter now says
   so itself.
3. **By looking at one row with eyes (rule П3).** It passed the image ceiling
   at level 2 and its checkpoint was named "NSFW MASTER". The model's own
   `nsfw` BOOLEAN is False for it — the signal is `nsfwLevel`, a BITMASK of
   every rung the model's images span (3 = 1|2, 31 = 1|2|4|8|16). Comparing it
   as a rating would have let 31 through on the strength of its 1 bit.

   The count of rows from such checkpoints prints on every run;
   `--safe-models-only` skips them. **90 of 100 candidate versions on a
   Flux.1 D run.** A count and a switch rather than a quiet default, because
   the image gate is a question about the data and this is one about the
   product — the owner's, with the number in front of them.

### The corpus

Not committed; `.gitignore` carries it beside `gallery_prompts.jsonl`. This
repository is public and its LICENCE clause 2(d) would assert rights over other
people's prompts. Collecting and using them is covered by the authorisation;
republishing them under this licence is a separate decision, and **that one is
still open.**

Provenance is `civitai:<uploader>`, not `civitai`. `MAX_PER_PROVENANCE` admits
2 records per provenance, so one bucket would cap the whole corpus at two —
the defect already recorded against the gallery rows, repeated. The platform
stays recoverable from the prefix, so a removal request naming Civitai matches
every row with one grep.

## Reddit — built, blocked, and a credential probably will not help

`studio/mcp/reddit.py`. Parsing and credential handling complete and tested;
**it has collected nothing.** Measured, and the pair of lines is the point:

| endpoint | answer |
|---|---|
| `www.reddit.com/api/v1/access_token` | `401 {"message": "Unauthorized", "error": 401}` |
| `www.reddit.com/r/comfyui/hot.json` | 403, a Reddit web page |
| `oauth.reddit.com/r/comfyui/hot` | 403, Reddit's **"Blocked"** page — identical with and without an `Authorization` header |

The token host behaves like an API. `oauth.reddit.com`, where every
authenticated read goes, serves the Blocked page regardless of what
authorisation is presented: an edge block on this caller, decided before any
credential is examined.

**So an app id and secret would probably NOT make this work from this
container.** Strong evidence, not proof — a valid token has never been
presented, and only that settles it. Recorded as
`reddit-api.authenticated_read_reachable` so nobody registers an app on the
strength of the 401 alone.

The egress policy is not the obstacle; it lets reddit.com through. This is
Reddit's own decision about being read from a datacentre and it is not routed
around — no proxy, no residential exit, no scraping past the 403.

The live POST path IS verified as far as Reddit allows: a deliberately wrong
credential reached the token endpoint and came back 401 through this module's
own error handling, so the request shape, the Basic auth encoding and the
failure reporting are exercised against the real host. No runner script was
written — a command whose only possible output today is a 403 is a command
nobody can check.

Separately still unread: the Data API TERMS live on `www.redditinc.com` and
`support.reddithelp.com`, both refused by the egress policy. So no rate limit
in this package is quoted from a page anybody opened; the 100-queries-per-
minute figure is relayed, marked UNVERIFIED, and the collector's interval is
chosen to sit under it rather than read from it.

## `fetch()` grew two parameters, deliberately in one place

`headers` and `data`, so an authenticated API is reached THROUGH the one client
rather than beside it. A second HTTP path would be a second place a policy
refusal could be swallowed, retried, or fail to reach the allowlist request —
the bookkeeping only works because there is one door.

It also keeps the error BODY now. That is what distinguished "you are blocked"
from "your token is wrong" above, which is the difference between a credential
being worth obtaining and not; discarding it turns a diagnosable refusal into a
bare number.

## Where this leaves the owner

1. **Publishing the Civitai corpus.** Collecting and using it is covered.
   Committing it to a public repository whose LICENCE claims rights over "the
   prompts contained here" is a different act and is not done.
2. **`--safe-models-only`.** 90 of 100 candidate Flux versions come from
   checkpoints that publish above PG-13. Every collected IMAGE is PG or PG-13
   regardless. Your call which matters for this product.
3. **Reddit.** Either accept that it is unreachable from here and drop it —
   rule Ц9 wants that stop condition written down — or move the collector
   somewhere Reddit does not block, in which case the module is ready and only
   the credential is missing.
4. Unchanged: `MAX_PER_PROVENANCE = 2` in another module's file; Yandex as a
   third search backend; **no prompt in this package has been proven by a
   generation** — and there are now 473 collected prompts with the images they
   produced, which is the closest this project has come to material for that.

---

# Session 2026-08-27 (final) — Reddit dropped, and the agent learned to look

> «reddit снимаем, все остальное финализируй и проверь функционал который
> позволяет анализировать загруженные вручную креативы»

## Reddit is gone, and the stop condition is written down

The collector is deleted rather than left as code nobody can run. What survives
is the measurement, as `reddit-api.authenticated_read_reachable`:
`oauth.reddit.com` serves the "Blocked" page identically with and without a
bearer, so a registered app would probably not have helped from this container.

**Reopen only if** the work moves somewhere Reddit does not block, or a valid
token gets something other than the Blocked page from `oauth.reddit.com`.
Written in `studio/knowledge/PROVENANCE.md` per rule Ц9, so it is a condition
rather than a thing that trailed off.

### A third state in the allowlist file

Its two terms hosts had to leave the ask and there was no honest way to do it:
the file recorded `refused` and `open`, and marking them open would have put a
lie in it — they never answered. So `unwanted` exists: still refused, no longer
wanted, with the reason beside it. The ask went **16 → 14**.

Adding a third state broke two rules written when there were two, and **both
were found by the tests written for the new behaviour, not by reading**:

- a host withdrawn and then refused again did not return to the ask — the
  re-refusal rule tested for `open` instead of "not refused";
- a withdrawn host that LATER answered was never recorded as open, because
  `note_open` fired only from `refused`, so the file would have lost the fact
  that access arrived.

Both are now written against "not refused" and "not already open", so a fourth
state cannot slip past them the way the third did.

## The creative-analysis question, answered by measuring

**What already existed.** The product path is real and correct:
`studio/app.py` saves an upload and runs `lipsync.fork_intake.photo_intake` on
it, which reports per axis and degrades to `could not measure` — verified by
running it.

**What did not.** The chat agent had eleven tools and **not one took a file**.

**What can actually run here, MEASURED:**

| | |
|---|---|
| present | `numpy`, `Pillow` — so the look measurements and `lipsync.motion` run |
| absent | `insightface`, `mediapipe`, `cv2`, `onnxruntime`, `torch`, `ffmpeg`, `ffprobe` |

So every face axis, every pose axis and any mp4 decoding cannot run in this
container at all. `pose.*` and `identity_arcface.*` **raise
`ModuleNotFoundError`** rather than returning the third outcome; `photo_intake`
wraps them properly and does return it.

## `analyse_creative`, the twelfth tool

Takes an image, plus a directory of frames for a clip. Answers in the SAME
vocabulary `write_lipsync_prompt` takes — imported from `style.py` and the
prompt card, never restated.

| slot | how |
|---|---|
| `palette` | dominant colours named against `PALETTE_WORDS` |
| `saturation` | mean chroma against the card's own three buckets |
| `light` | `high-key` / `low-key` from the luminance histogram, **or neither** |
| `mood` | never — nothing in a histogram says "melancholic" |

**Measured end to end through the MCP server:** a creative analysed, its own
words fed back as an intent, and `write_lipsync_prompt` fills **3 of 4** card
slots and ASKS for texture instead of guessing. That refusal is the design
working.

Two design points worth keeping:

- The lighting middle band returns **no word at all** rather than the nearer of
  the two. An instrument that always answers looks exactly like a working one.
  Saturation genuinely covers its whole range, so its control is three-point —
  both ends and the middle — instead.
- `could_not_run` NAMES each instrument that did not run and why. No violations
  out of no checks is not a clean creative, and `unmeasured` carries them.

24 tests, 22 mutations both ways, all red. Two were green at first: dropping
the palette de-duplication, and measuring grain on the small sample — every
other fixture is flat and reads zero either way. Both have a fixture that can
tell now.

## Findings for other owners — NOT patched, both modules are theirs

`lipsync/**` is frozen by `studio/CONTRACTS.md`; `studio/app.py` is agent C's.

1. **`photo_intake` returns no top-level `note`.** `studio/app.py` renders
   `f"the photo could not be checked: {report.get('note', '')}"` — so the user
   is told nothing, while "nothing to ask with: ModuleNotFoundError: No module
   named 'insightface'. This is not 'there is no face'" sits one level down in
   `axes`. `analyse_creative` lifts the axis notes to work around it.
2. **A missing file and an unanalysable one give the identical intake report**,
   because the first axis cannot run at all and short-circuits. A path check
   costs 1 ms and would separate them — rule П2, cheap checks before expensive.
3. **`pose.*` and `identity_arcface.*` raise instead of returning
   `could not measure`.** Every other judging function in this repository
   returns the third outcome. A caller that does not wrap them crashes on a
   machine without the models.

## Where the project stands

- **Civitai collects.** 1409 pairs held, 659 on families this project targets,
  106 uploaders. `--base-model` points it; `--safe-models-only` and its counter
  handle the checkpoint question.
- **Reddit is closed**, with a reopen condition.
- **The agent can look at a creative** and hand what it sees to the prompt
  writer.
- Still open, unchanged: publishing the Civitai corpus (it is gitignored);
  `MAX_PER_PROVENANCE = 2` in another module's file; Yandex as a third search
  backend; and **no prompt in this package has been proven by a generation** —
  though there are now 659 on-target prompts with the images they produced.

---

# Сессия 2026-08-27, вторая половина: ярус фактов, корпус в индексе, заявка на замер

## Что сделано и чем измерено

### 1. Урожай 375 фактов встал в базу (коммит `0516442`)

    строк 375 / записано 375 / уже стояло 0 / отказано 0 / негодных 0
    повторный прогон: записано 0 / уже стояло 375     (идемпотентно)
    база: фактов 433 | моделей 150
    по тирам: {'vendor': 205, 'blog': 19, 'portal': 182, 'paper': 23, 'probe': 4}
    прочитано лично: 409

База выросла с 59 фактов / 15 моделей до 433 / 150. Доля `blog` — 4%, была 72%.
`scripts/ingest_harvest.py --check` держит это в гейте: 374 проверено, 0
расхождений, 1 уступлено разбору `read_sources.py` (осцилляция на
`runway-gen-4.5.max_seconds`, см. `_reading_pass_keys`).

### 2. Провенанс стал двухчастным (коммит `c2406cd`)

`"<family>:<who>"` — семейство несёт вес, вся строка несёт личность.
ИЗМЕРЕНО до и после: было 2 примера и 16 отвергнутых квотой; стало 6 примеров
от 6 разных авторов, `quota_blocked` 0. `MAX_PER_PROVENANCE` остался **2** —
измерено, что не он был узким местом.

### 3. Механизм заявки на платный замер (коммит `7c6200c`)

Правило владельца: платные замеры — под конкретную задачу и с одобрения
оператора каждый раз. Значит агенту нужен не бюджет и не запрет, а **заявка**.

`studio/mcp/proposal.py` — автомат `proposed → approved/declined → recorded`.
Заявка обязана назвать задачу, дыру, точный тест, цену, **откуда взята цена** и
что решает каждый из возможных исходов; без любого из этого — отказ. Заявка на
то, что база уже отвечает свежо и непротиворечиво, отклоняется до оператора;
спорное и протухшее — пропускается (это и есть случай, когда замер стоит денег).

**Одобрение не является инструментом MCP.** Сервер отдаёт `propose_measurement`
и `measurement_proposals` — и всё. Одобряет человек командой
`python scripts/measurement.py approve mp-…`. `record_result` отказывает, пока
заявка не стоит `approved`, — агенту, запустившему генерацию самовольно, некуда
положить результат так, чтобы он выглядел санкционированным. Это проверено
тестом: временно добавленный инструмент `approve_measurement` красит его.

Перерасход не проглатывается: факт всё равно пишется (деньги уже потрачены, и
скрыть результат — потратить их дважды), а исход `fail` с суммой.

Мутации в обе стороны по всем константам-решениям: четыре порога длины,
сравнение перерасхода, гейт состояния `approved`, перечень решений — все краснеют.
Две мутации сначала были зелёными и купили два теста: задача в одно слово
(единственной фикстурой была ПУСТАЯ) и протухший устоявшийся факт.

### 4. Корпус комьюнити стал источником индекса (коммит `37e1f18`)

ИЗМЕРЕНО на этом клоне (`our_prompts` и `reference_cards` здесь отсутствуют):

    до     per_source {'core': 12, 'ours': 0, 'reference_card': 0, 'gallery': 0}
           evaluate -> could not measure, "index holds no examples"
    после  per_source {..., 'community': 473} от 30 разных загрузивших
           evaluate -> fail, recall@5 0.4342, precision@5 0.3842,
                       негативные контроли 2/2 ok, позитивные 0/2

Читать честно: корпус — то, что вообще сделало индекс измеримым; до него
`evaluate` не мог запуститься. На этот золотой набор он не отвечает: оба
позитивных контроля возвращают ПУСТО, потому что названные в них строки лежат в
`our_prompts` и `reference_cards`, которых на этом клоне нет. Число, которое
относится к самой проводке, — негативные контроли: 473 новые строки не заставили
поиск отвечать на вопрос про НДС и про динамометрический ключ. Он по-прежнему
воздерживается.

Два теста `studio/tests/test_knowledge.py` покраснели ровно на том, на чём
должны были: они изолировали все корпуса, кроме этого, и реальный файл на 473
строки протекал в сборки, которые обязаны быть пустыми.

## Что осталось открытым

- **Фаза 2 сбора (применимость).** Воркфлоу `genai-applicability-harvest`
  (12 агентов доказательств + 12 опровержений) был убит компактификацией
  контекста и перезапущен как `wf_7c0f8853-e0d`. Цель — различие
  CAPABILITY / APPLICABILITY: схема вендора доказывает, что API принимает вход,
  и не доказывает, что результат держится.
- **Публикация корпуса Civitai** — по-прежнему решение владельца; файл в
  `.gitignore` из-за пункта 2(d) их лицензии.
- **Ни один промт этого пакета не подтверждён генерацией.** Теперь под это есть
  механизм: заявка на замер. Первая заявка ещё не подана — для неё нужна цена
  с проверяемым основанием, а не оценка.
- Yandex третьим поисковым бэкендом.

---

# Сессия 2026-08-27, фаза 2: применимость, и два дефекта, которые она вскрыла

## Урожай применимости (коммит `b4a8bea`)

Фаза 1 спрашивала, что API принимает. Эта — что держится. Два прогона
`genai-applicability-harvest`: 16 агентов доказательств, 17 опровергающих
(7 опровергающих умерли на лимите сессии — засчитаны как «не отработали», а не
как согласие). 479 сырых утверждений.

    строк 277 / записано 277 / отказано 0 / негодных 0
    повторно: записано 0 / уже стояло 277        (идемпотентно)
    база: фактов 710 | моделей 211               (было 433 | 150)
    тиры: vendor 394, portal 186, paper 55, blog 44, benchmark 24, probe 7
    атрибуты: limitation 89, failure_mode 88, degrades_when 41,
              metric_blind_spot 21, holds_identity 18
    прочитано лично: 686 из 710

Верх таблицы атрибутов — то, что модель делает неправильно. Ради этого фаза и
была.

### Что НЕ пошло в базу

158 утверждений с `model: "*"` — про технику или поколение, не про модель,
которую можно спросить по имени. Лежат в `class_findings_2026-08-27.jsonl` +
`CLASS_FINDINGS.md`. **Ни одно из них не проверено**: опровергатели вернули
отказы ключами `model.attribute`, и для `*` один опровергнутый и сорок
нетронутых делят ключ. ИЗМЕРЕНО: буквальное чтение убивает 156 из 158,
«ключ = одно утверждение» — максимум 6. Третий исход, написан первым абзацем.

### 44 отказа лестницы разделились надвое

28 — пробел таблицы: `vendor_sources_for` сопоставляет ключ точно или до
разделителя, поэтому `hunyuan` не доставал до `hunyuanvideo`, а `wan` — до
`wan2.1-*`. И у лаборатории с открытыми весами нет сайта документации: README
в её собственной организации и есть страница вендора. Объявлено по префиксу
пути, никогда по голому хосту — `raw.githubusercontent.com` целиком это чьё
угодно письмо.

16 переразмечены видимо, с сохранением заявленного в `tier_claimed_by_harvester`;
11 из них — README сторонних нод ComfyUI, заявленные как `portal`. Одна строка
выброшена: записывала 403 как доказательство.

## Два дефекта, которые стали видны только с этими данными (коммит `a1c4ca9`)

**Список читался как противоречие.** Спорных пар было 38, из них 15
`limitation` и 9 `degrades_when` — ни одна не была разногласием. Стало 14, и
это настоящие: `holds_identity` 6, `max_seconds` 3, `benchmark_score` 2,
`architecture` 2, `max_resolution` 1. `holds_identity` и `benchmark_score`
намеренно НЕ внесены в `MULTI_VALUED`: «держит лицо 6 секунд» против «теряет
на третьей» — это разногласие, которое кто-то должен закрыть замером.

**У вопроса было одно имя, а у ответов три.** `failure_modes()` читал только
атрибут `failure_mode`, поэтому 89 `limitation` и 41 `degrades_when` были
записаны в базу и не доходили ни до одного вызывающего.
`hunyuanvideo-avatar` был 0 режимов отказа, стал 1; `flux.1-kontext-dev` был
1, стал 5. `metric_blind_spot` намеренно снаружи: он говорит, что чего-то не
видит ИЗМЕРЕНИЕ, а это утверждение про бенчмарк, не про поломку модели.

## Что осталось открытым

- **Класс-уровневые находки не имеют вердикта.** Чтобы поднять любую строку:
  открыть её `source_url`, проверить цитату в `evidence`, записать против
  конкретной модели, к которой она относится.
- **У большинства открытых моделей раздела «ограничения» просто нет** — ни у
  Wan 2.2, ни у CogVideoX, ни у HunyuanVideo-Avatar, ни у FLUX.2 [dev].
  Ответ на «что оно ломает» — «вендор не сказал». Это дыра под
  `propose_measurement`.
- `artificialanalysis.ai` закрыт политикой (Tunnel 403), лидерборд VBench
  читается только через закрытый датасет (401). Оба доложены, ни один не
  обойдён.
- Ни один промт этого пакета по-прежнему не подтверждён генерацией.

---

# Сессия 2026-08-27, итерации 5–7: целостность данных и первая заявка

## Слияние id и охват класса (коммит `690b2d5`)

Одна модель под несколькими написаниями: вызывающий видел **23 факта из 37**.
`model_advice("eleven-turbo-v2.5")` отвечал из нуля при двух в базе. После
слияния — 11/11, 5/5, 5/5, 2/2, 14/14; 211 id стали 205, потерь нет.
Отрицательный результат: слияние не вскрыло ни одного скрытого противоречия
(спорных 14 до и 14 после). Каноническое написание — вендорское, потому что
id вендора уже стоят внутри прочитанных цитат (`eleven_v3`, с подчёркиванием).
Слияние идёт через `record`+`withdraw`, гейт `scripts/merge_model_ids.py --check`.

26 строк с охватом `*` и `elevenlabs-*` не возвращал ни один запрос: запрос
всегда начинается с имени модели. `class_claims` их находит, `model_advice`
отдаёт отдельным списком `class_findings` — не подмешивая и не давая голосовать
в противоречии.

## Верификация 158 класс-находок (коммит `1d4731f`)

Вердикты **по индексу строки** — это и было исправлением прошлой
неразрешимости. 12 агентов, 158 вердиктов, 0 дублей, 0 пропусков.

    field 145   model 8   reject 3   family 1   unreachable 1

Двенадцать поправок настоящие: `[110]` ограничена статьёй ровно двумя
системами (VACE, Phantom); `[20]`/`[53]` — число одной базовой модели, поданное
как константа поля; `[2]` отклонена чтением той самой таблицы (у Janus-Pro-7B
Position — вторая **лучшая** ось, его из перечисления выкинули); `[144]` —
неверно прочитанные столбцы. База 710 → 865.

**Поправка к решению часом ранее:** `holds_identity` и `benchmark_score`
внесены в `MULTI_VALUED` — данные показали, что все спорные пары там списки.
Спорных 16 → 6.

Класс-находки ограничены 12 в выдаче с печатью знаменателя и разбросом по
атрибутам: сортировка по тиру возвращала двенадцать строк одного атрибута.

## Фальшивые противоречия и первая заявка (коммит `4bf3cdd`)

Из шести спорных **три оказались шумом** — одно чтение, записанное дважды
разной длиной, и два согласных источника, поссоренных лишней деталью внутри
значения. То есть половина сигнала в самом важном выводе базы была мусором.

**Я снял не ту сторону**, и гейт разбора это поймал до пуша: короткая
формулировка была записью ручного разбора. Настоящая дыра глубже — сбор
уступал разбору по ключу **со значением**, поэтому переформулировка проходила
насквозь. Теперь уступка по «модель + атрибут + страница»; возврат старого
ключа красит гейт.

**Проба отработала и не решила спор** — это тоже измерение. `ABSURD_MIN`
сработал на 999999 (ничего не отправлено), на 1000000 api.klingai.com ответил
400 / код 1201 / «duration value '1000000' is invalid», **не назвав потолка**.
Сузить можно только правдоподобной длительностью, то есть платной генерацией.
Записано отрицательным результатом на тире `probe`.

**Заявка `mp-eaed2081b8`** — kling-3.0.max_seconds, $1.05, ждёт оператора.
Основание цены прочитано со страницы эндпоинта fal.ai; в заявке сказано, что
собственная цена kling-3.0 недоступна и цифра может быть неверна в обе стороны.

    python scripts/measurement.py show    mp-eaed2081b8
    python scripts/measurement.py approve mp-eaed2081b8 --by <имя>

## Что осталось открытым

- Три настоящих противоречия: kling-3.0 max_seconds, runway-gen-4.5
  max_resolution, seedance-2.0 max_seconds. Все три — блог против более
  высокого тира.
- 54 тройки (модель, атрибут, url) несут больше одной формулировки; 10 из них
  почти дубли. Нечёткое слияние удалило бы настоящие находки — записано, а не
  угадано.
- Ни один промт этого пакета не подтверждён генерацией.

---

# Сессия 2026-08-27, итерации 8–9: измерение продукта и закрытие молчаний

## Слепая оценка базы (коммит с `eval_base_2026-08-27.json`)

Семь итераций база росла; эта спросила, отвечает ли она. 12 агентов, по
настоящей задаче каждому, каждый подвопрос — только к `model_advice`.

    114 подвопросов, вернулись 12/12
    answered 42 (37%) | silent 50 (44%) | contested 17 (15%) | wrong 5 (4%)

**Из пяти «неверных» настоящих оказалось два.** База докладывает
`veo-3.1.max_resolution` как спорный с обеими сторонами — это верное
поведение, а два агента подали его как уверенно неправильный ответ.
`veo-3.1.reference_images` отвечен на вендорском тире, третий агент назвал
это молчанием. **Вердикт агента — такое же утверждение, как любое другое, и
проверять его обязательно.**

Два настоящих дефекта, оба починены и загейчены:

1. **Карточка и база рассказывали разное, и никто их не сверял.** Карточка
   sora-2 отвечала, что длительность и разрешение «не удалось найти вовсе»,
   тогда как слой фактов ТОГО ЖЕ ответа держал 20 с и 1280x720. Теперь
   `advise` возвращает `card_vs_base` с двумя разными жалобами: «карточка
   молчит» и «карточка противоречит». Сравнению пришлось сначала научиться
   арифметике: карточка держит `8.0`, сбор — `"8"`.
2. **«Известны: семь моделей» при 214 в базе.** Агент письменно заключил, что
   в базе нет ни одной модели липсинка — в репозитории lipsync-studio.
   `FactStore.near` теперь предлагает ближайшие id самой базы; порог в четыре
   общих символа прибит с обеих сторон.

## Закрытие молчаний (коммиты `…facefusion/inswapper`, `…jina-clip`, и др.)

10 агентов по 5 названных целей. Девять пачек отработали, десятая (физика)
потеряна при перезапуске контейнера. Итог: **81 факт**, из них по правилу Ц5
две лицензии, найденные ДО встраивания — FaceFusion OpenRAIL-AS (не OSI) и
inswapper_128 (только некоммерческое исследование).

Самое ценное — опровержение общего места: **CLIP не слеп к тексту**, он
читает отрисованный текст хорошо, а плохо обобщает вне распределения (88% на
MNIST, где его обходит логистическая регрессия). Команда, вычеркнувшая CLIP
«потому что он не читает текст», сделала бы это по неверной причине.

**42 цели остались закрытыми, с причиной у каждой** —
`still_silent_2026-08-27.json`: 13 хост закрыт политикой, 7 никто не
публиковал, 2 за авторизацией, 6 оказались не молчаниями вовсе.

## Тест, который пришлось убрать

`test_the_real_base_lands_on_all_three_rungs` прибивал точный размер базы. Под
работающим в фоне сбором он краснел на каждой законной записи — шесть
перефиксаций за день, дважды счётчик менялся между фиксацией и прогоном. Тест,
у которого единственный режим отказа «число опять другое», учит перепечатывать
число не глядя. Заменён свойствами, переживающими дописывание: ни один тир не
пуст, `vendor` крупнейший, база не проседает ниже порога 700.

## Состояние на конец сессии

    факты 917 | модели/охваты 231 | прочитано лично 894
    тиры: vendor 416, portal 196, paper 174, benchmark 66, blog 56, probe 9
    о поломках 308 | спорных 6 | класс-находок 170
    bash scripts/check — exit 0, 14 инструментов

## Что осталось открытым

- **Доля отвеченного не перемерена после сбора.** 42/114 — это ДО +81 факта.
  Перемер должен быть отдельным прогоном того же набора, и честнее он выйдет
  не у того, кто собирал.
- Десятая пачка сбора (5 целей по физике) не отработала.
- Заявка `mp-eaed2081b8` (kling-3.0.max_seconds, $1.05) ждёт оператора.
- 13 хостов закрыты политикой; это потолок бесплатного сбора здесь.
- Ни один промт пакета по-прежнему не подтверждён генерацией.
