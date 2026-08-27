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
