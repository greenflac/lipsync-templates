# The chat agent

Two functions, asked for by the owner on 2026-08-27, delivered as an MCP server
so they are reachable from the chat rather than from a page.

1. **Consult** on what a generation model can and cannot do, out of a knowledge
   base that keeps getting refreshed from the web.
2. **Write lipsync prompts** that work, that do not break the engine's
   contract, and whose look comes from the corpus of prompts that actually ran.

## How to use it

The server is registered in `.mcp.json` at the repo root, so Claude Code picks
it up in this project with no further setup. To check it by hand:

```
python -m studio.mcp.server        # stdio; Ctrl-C to stop
```

Fourteen tools appear in the chat. Seven of them write; the rest only read.

| tool | what it does |
|---|---|
| `model_advice` | everything known about a model, with every source and its date |
| `record_model_fact` | **writes.** One web finding into the base, with who said it and when |
| `withdraw_model_fact` | **writes.** Takes back a claim its own page turns out not to make |
| `stale_model_facts` | which claims are old enough to need re-checking |
| `analyse_creative` | measure a creative you dropped in: palette, lighting, saturation, motion |
| `write_lipsync_prompt` | write a look prompt from your words plus the corpus |
| `check_lipsync_prompt` | judge any prompt, from any source, against the contract |
| `search_web` | **search the web — the research entry point** |
| `fetch_url` | **writes** a refused host to the allowlist request. Opens one page, through the policy and never around it |
| `blocked_hosts` | the allowlist request, built from refusals that really happened |
| `reachable_hosts` | re-probe which hosts answer right now |
| `probe_model_limit` | ask a vendor API for the impossible and read the real limit |
| `propose_measurement` | **writes.** File a paid generation for the operator to approve — you cannot approve it yourself |
| `measurement_proposals` | what has been proposed, approved and spent |

### Analysing a creative you uploaded by hand

`analyse_creative` takes an image — a reference you liked, a frame you
generated, a competitor's still — and answers in the SAME vocabulary
`write_lipsync_prompt` takes, so its words go straight back in. For a clip,
pass a directory of extracted frames as well and the engine's own loop and
motion instruments run over them. An mp4 cannot be decoded here: there is no
ffmpeg (MEASURED 2026-08-27).

Three of the prompt card's four slots come off the pixels honestly:

| slot | how |
|---|---|
| `palette` | the dominant colours, named against `style.PALETTE_WORDS` |
| `saturation` | mean chroma, against the card's own three buckets |
| `light` | `high-key` / `low-key` from the luminance histogram — **or neither** |
| `mood` | never. Nothing in a histogram says "melancholic" |

Measured end to end: a creative analysed, its own words fed back, and
`write_lipsync_prompt` fills 3 of 4 slots and ASKS for texture rather than
guessing it. That refusal is the design working, not a gap.

**Read `could_not_run` before trusting a clean answer.** Every face and pose
axis needs `insightface` or `mediapipe`, and neither is installed here, so they
come back named rather than skipped. No violations out of no checks is not a
clean creative, and the counts say which it was.

### The fact file is a log, and the latest row about a claim wins

Added 2026-08-27, when the vendor hosts opened and 25 second-hand facts became
readable. Recording something already recorded is an UPDATE, not a second
source agreeing: a claim is `(model, attribute, value, source_url)`, and a new
row supersedes the old one's tier, date, note and reading flag. Without that,
opening a page you already cite counted it twice — `checked` inflated, and the
note reading "1 of 2 source(s) were NOT read" about one page that had been.

`withdraw_model_fact` is for the other outcome of reading: the page does not
say it. The withdrawal is appended with its reason rather than deleting the
line, so why anybody believed it survives; the base simply stops asserting it.
Withdrawing something nobody recorded is `could not measure`, never `pass`.

Do not hand-edit a row to correct it. Append a corrected one, or withdraw it.
`scripts/read_sources.py --check` is a step in `scripts/check` and will notice.

Every tool returns `outcome` — `pass` / `fail` / `could not measure` — next to
`checked`, `violations` and `unmeasured`. Zero violations out of zero checks is
never a success, and the denominators are printed so nobody has to take it on
trust.

## Function 1: the consultant

### Where the knowledge lives

`studio/knowledge/model_facts.jsonl`, one claim per line, each with the model,
the attribute, the value, the **source URL**, the **tier** and the **date the
source stated it**. `studio/selfrag/facts.py` owns the schema and the rules;
this package joins it to `registry.py` and opens the write door.

Tiers, and why a blog can never be promoted by repetition. The owner's ladder,
2026-08-27 — the vendor's own URL, then specialised platforms, then everything
else — with the two rungs that describe a METHOD kept in place:

| tier | means | decided by |
|---|---|---|
| `vendor` | the model vendor's own page: docs, release, or repo | the URL |
| `probe` | the vendor's API was asked and refused | the recorder |
| `paper` | arXiv or a venue, with a method somebody can check | the recorder |
| `benchmark` | an independent evaluation with a published method | the recorder |
| `portal` | a platform that RUNS the model or hosts what people made with it | the URL |
| `blog` | everything else, including the good aggregators | the URL |

A claim carried only by blogs stays `could not measure` however many blogs
repeat it. Ten blogs quoting each other are one source.

**Three rungs are read off the URL and are not the recorder's to choose.**
`studio/selfrag/source_hosts.py` holds the table, keyed by model FAMILY so a
new version is not locked out of the first rung. `record_model_fact` refuses a
`vendor`/`portal`/`blog` tier the URL contradicts, and names the host it
judged. The other three say how the fact was obtained, which no URL can know.

Why the middle rung exists: measured over the 47 recorded facts, `blog` held
**9 vendor pages** and **11 platform pages** alongside real press. One rung was
doing three jobs. A platform documents an endpoint that answers, which is a
different kind of claim from an article — but it documents its OWN endpoint,
so its ceiling may be its plan rather than the model's, and it stays below the
vendor. A platform's own blog post is a blog post: 5 of those 11 URLs were
articles that happened to sit on a platform, and the path decides.

### Whose page it is, and whether anybody read it

Two questions, two fields. Most vendor hosts are refused by this environment's
egress policy, so a `vendor` row is often a summary of a page nobody could
open. `read_directly` records that, in three states:

| value | means |
|---|---|
| `true` | somebody opened the page, or the API answered us |
| `false` | not opened — the host is refused, or the note says summary |
| `null` | not recorded |

`null` is not `false`: collapsing them would invent evidence. `claims()` counts
the unread sources, names them in its note and returns
`sources_not_read` / `sources_reading_unrecorded` beside the verdict.

**Measured 2026-08-27, migrating the 47 facts** (`scripts/retier_facts.py`,
re-runnable and idempotent): 16 rows changed tier — 10 to `vendor`, 6 to
`portal` — and 15 attributes went from `could not measure` to `pass`, because
they were no longer blog-only. Of the sources behind them, **25 of 47 were not
read** and 21 have no reading recorded. The verdict is not demoted for that;
the count is printed so a caller can decide.

### How it refreshes from the web, and why it works that way

**Measured 2026-08-27 on this machine:**

```
curl https://docs.bfl.ai    -> CONNECT tunnel failed, gateway answered 403
curl https://arxiv.org      -> CONNECT tunnel failed, gateway answered 403
WebFetch https://kling.ai   -> EGRESS_BLOCKED
WebSearch "Kling lip sync"  -> returned current sources, August 2026
```

The egress proxy refuses the vendor domains. Going around a policy-closed host
is forbidden (house rule Ц3), so the server does not try. What is not refused
is the assistant's own search, in the conversation the owner is already in.

So the refresh is a two-step performed in the open:

1. the assistant searches the web,
2. the assistant calls `record_model_fact` with the value, the URL, the tier
   and the date **the source** stated it.

Nothing is written without those four. A claim with no URL cannot be
re-checked; a claim with no date cannot go stale; and a claim that cannot go
stale is the one that quietly rots. `record_model_fact` refuses a blank field,
an unknown tier, a source that is not a URL, a date that is not ISO and a date
in the future — and in every one of those cases writes nothing at all.

### What it refuses to do

**It never resolves a contradiction.** Asked how long one Kling 3.0 generation
runs, the recorded sources say 15 seconds, and 10 seconds, and "3 minutes"
(which turns out to mean several renders joined by an Extend feature). A
third-party summary of those same sources confidently reported "up to 5 minutes
in a single generation", which matches none of them. That is what flattening
does. So `model_advice` returns `fail` on a contested attribute and hands back
every side with its URL, its tier and its date. It does not vote, average, or
take the newest.

Run against the real base today, that is not hypothetical:

```
kling-3.0    fail               sources disagree on max_seconds
sora-2       could not measure  end of life 2026-09-24, 28 days away
kling-3.1    could not measure  in neither the registry nor the fact base
flux-2       could not measure  3 of 3 attributes rest on blog-tier sources
stale        fail               14 of 41 claims older than 90 days
```

An unknown model is `could not measure`, never `fail`. Not knowing is a gap in
this base, not a defect in the model, and the two must never print the same.

## Function 2: the prompt writer

### The contract it may not break

A lipsync prompt describes the **look**. It never describes the subject,
because the subject arrives from the user's photo and from the driving clip.
`lipsync/fork_style_prompt.py` enforces that with `SUBJECT_WORDS`, and the same
module holds the bands the corpus produced: 9–67 words, 1–13 clauses.

`studio/mcp/contract.py` imports those constants rather than restating them. A
copy would drift, and a drifted copy would pass prompts the engine rejects.

### The method that was tried first, and thrown away

The obvious way to lean on a corpus is to splice clauses out of prompts that
worked. It was built, it ran, and it **passed the gate** — no forbidden word,
both bands respected. Then the output was read rather than measured:

> "…faint frost forming on its surface, smooth gradients and elegant shadows.
> faces and visual details exactly as provided. Behind the laptop hangs a full
> wall of luxurious floor-to-ceiling velvet curtains"

A laptop, a sleigh and somebody else's snow, in a prompt asked for burgundy
velvet under moonlight. Splicing a clause imports the **scene** that clause was
written for, and no rule in the engine can see that. A number passed and a
reader would have binned it in a second.

### What is done instead

The corpus is read for the one thing that generalises across scenes: which
**look attributes** the prompts that worked commit to.
`knowledge.structure_from_text` already extracts them against fixed
allow-lists — palette, light, texture, mood — and an attribute carries no scene
with it, so nobody's laptop can ride along.

Those attributes fill the engine's own card, and the engine's own `compose()`
builds the sentence over its frozen skeleton. This package does not write the
sentence at all.

```
"muted ivory and slate, low-key light, matte"
    -> card {colours: [ivory, slate], value_key: dark,
             saturation: muted, texture: matte}
    -> "a palette of ivory and slate, low-key shadowed lighting,
        desaturated restrained colour, matte, photographic look"
    -> gate: pass — 15 words (band 9..67), 5 clauses (band 1..13), 0 forbidden
```

### Who wins, and when it refuses

**The owner wins, and is never topped up.** A value you name is taken as given
and the corpus does not add to it: name two colours and you get a two-colour
palette, because adding a third is an addition and the product rule allows only
substitution. The corpus fills what you left **silent**, and every slot it fills
comes back with the record ids that voted for it — a slot you filled carries
none, so the label can never disagree with the evidence beside it.

A corpus value is accepted only with support from **two distinct records** — one
precedent saying "teal" is a coincidence, not evidence. That floor is the same
for every slot, `saturation` included.

Where you said nothing and the corpus does not agree either, the slot is
reported unresolved and the run returns `could not measure` **with a question**:

```
"burgundy velvet under moonlight, elegant"
    -> could not measure — 2 of 4 card slots filled
    ask: Which colours? Name one to three of: amber, charcoal, copper, ...
    ask: How much colour — muted, moderate, saturated?
```

It does not pick, and it never defaults `saturation` — no corpus *field*
carries it, so it comes from your words or from two corpus prompts that both
say "muted" in plain words, and otherwise it is a question.

Naming more colours than the engine takes is also a question, not a trim. The
engine truncates a wider palette silently, so a colour you named would vanish
from the prompt with nobody told.

## What is checked, and how it was verified

`bash scripts/check` gates ruff, ruff format, mypy, 35 tests, a 54-case blind
control set and a live server handshake for this package. Exit 0 as of
2026-08-27.

### The blind control set, and the three defects it found

`studio/mcp/fixtures/blind_control_set.py` was written by an agent forbidden to
read any of `contract.py`, `lipsync_prompt.py`, `advice.py` or the tests. It
judged the modules from the contracts alone, by importing them and reading what
they returned — the verdict cast by somebody who did not build the thing. It
reported 51 of 54 green, and all three failures were real:

1. **A corpus colour was added to a palette the owner had already filled.**
   Asked for "muted teal and slate" with three precedents shouting crimson, the
   tool built `a palette of slate, teal and crimson`. Nothing the owner said was
   *overruled*, so every override test stayed green — a colour was simply
   *added*, which the product rule forbids. Worse, `chosen["palette"]` was
   stamped `from: "owner"` while carrying the corpus record ids: the label
   contradicted the evidence beside it. Fixed — a named palette is now taken
   exactly as named.
2. **Saturation could never be filled from the corpus.** Two independent records
   both saying "muted desaturated restrained colour" filled light and texture
   and left saturation unresolved, so a request fully covered by evidence still
   came back `could not measure`. The stated rule is two distinct records for
   any slot; one slot had a different rule. Fixed — saturation is corroborated
   like everything else, and one record is still not enough.
3. **An empty intent asked no questions.** `write("", [])` returned `could not
   measure` with an empty `unresolved`, so the caller most in need of the four
   questions got none. Fixed — the empty case is no longer short-circuited.

The control set is itself checked: restoring defect 1 turns it red (`нарушений
1`) and removing it turns it green again.

The handshake is not an import check: the tools register by decorator at import
time, so an import succeeds even when the transport is broken. It starts the
server, lists the tools and puts two prompts through the gate.

**Mutation, both directions** (`python -m unittest discover`, bytecode caching
off — see the caveat below):

| mutation | result |
|---|---|
| control, before any mutation | OK |
| `MIN_SUPPORT` 2 → 1 (weaker) | 3 failures |
| `MIN_SUPPORT` 2 → 3 (stricter) | 3 failures, 1 error |
| subject guard disabled | 3 failures |
| word band removed | 2 failures |
| tier validation removed | 1 failure |
| control, after restoring | OK |

**A caveat worth keeping.** The first mutation run was measured through a stale
`__pycache__`: `sed` replaced a constant with one of the same byte length in the
same second, and CPython's `(mtime, size)` check reused the old `.pyc`. The
numbers it produced were wrong and were discarded. Mutation runs here use
`python -B` with the caches cleared first.

**A negative control that was measuring nothing.** The handshake first used
`"a woman in a red dress"` to prove the subject guard fires. With the guard
disabled it still went red — on the word band, because the phrase is six words.
It is now a prompt that sits inside both bands, so the subject guard is the
only rule that can reject it, and it is paired with a clean twin that must
pass. Verified: green on clean code, **red with the guard disabled**, green
again after restoring.

## Known gaps, stated rather than hidden

* **No generation has been run through this.** Every verdict here is about the
  prompt, not about what the model does with it. Nothing in this package has
  been shown to produce a better video, because that needs a paid call and a
  blind rating from somebody who did not write the prompt.
* **`studio/knowledge.py` and `studio/knowledge/` share a name.** At run time
  the module wins (the directory has no `__init__.py`); a type checker resolves
  the other way, so the imports here carry an `attr-defined` ignore. The
  collision predates this package and belongs to whoever owns those two paths.
* **The saturation cue list is CHOSEN, not measured.** Six words for "muted",
  six for "saturated", four for "moderate". The same list reads your words and
  the corpus prompts, so a look the corpus describes with a word outside it goes
  unnoticed. An owner who writes "chalky" gets a question rather than a guess,
  which is the safe direction to be wrong in.
* **Seven of the ten light words are placed by hand.** The engine's own table
  maps three; the other seven are a decision recorded in the source where it
  can be argued with.

## The sourcing problem, and what was done about it

**Measured 2026-08-27: 72% of the fact base was blog tier** — 33 of 46 claims,
against 10 paper and 3 vendor. The owner spotted it and asked how it gets
fixed.

The reflex diagnosis was "the proxy blocks everything". Probing 28 hosts said
otherwise:

```
open    raw.githubusercontent.com  api.github.com  github.com  pypi.org
        files.pythonhosted.org  huggingface.co  cloud.google.com
        storage.googleapis.com  api.klingai.com  api.fal.ai
closed  docs.bfl.ai  arxiv.org  kling.ai  help.runwayml.com  elevenlabs.io
        platform.openai.com  ai.google.dev  api.openai.com  unpkg.com  …18
```

Read the shape of that: **the API hosts of the two vendors this project holds
keys for are open, and the documentation hosts are shut.** The vendor is
reachable — as a running system rather than as prose. What was missing was not
access. It was a client that used the access.

### `fetch_url` — a client that tells three failures apart

```
could not measure   the policy refused the host (CONNECT 403/407)
could not measure   the network failed or timed out
fail                the host answered and said no — 404, 500, our bad URL
```

Collapsing those is how "we could not reach the vendor" becomes "the vendor
has no such page", and that error is precisely what put 33 blog claims in.

A blocked host stays blocked: no mirror, no cache, no archive copy, no
read-through proxy, no second attempt at a refusal. The proxy README says do
not route around policy denials, and the house rule says the decision belongs
to whoever owns the policy. So refusals are **recorded** instead, and
`blocked_hosts` renders them as an allowlist request assembled from attempts
that really happened. Six hosts are in it, each with the question it blocked.

### `probe_model_limit` and the `probe` tier

When a documentation host is blocked but the vendor's API answers, ask the API
for something impossible and read the refusal — `{"duration": 999999}` comes
back naming the real ceiling, stated by the vendor's own code.

`probe` was added to the tier ladder **below `vendor`**:

```
vendor  probe  paper  benchmark  blog
```

Not first, and the reason is a real confound: one probe sees one account, one
region, one moment, so a limit it reports may belong to a billing plan rather
than to the model. A vendor's general statement outranks a single observation
of a special case; everything written from the outside does not.

**The probe cannot quietly become a paid generation**, and that is guarded
mechanically rather than promised. A probe value must be at or past
`ABSURD_MIN` = 1000000 — no model renders a million seconds, so no vendor can
bill for rendering one. A plausible value is refused before a request object
exists. Verified: 1, 15, 999 and 999999 are all refused with `sent: None`;
1000000 clears the guard and stops at "no API key" instead.

The key is read from the environment inside the module, never passed as an
argument, and never appears in what the tool returns — only which variable it
came from. There is a test for that.

### A defect found while adding the tier

An unrecognised tier reached `pass`. It sorted to position 99 — below `blog` —
but the "is this only blogs" check compared against `blog` **by name**, so a
typo'd tier sailed past the guard and its claim was reported as corroborated.
Measured both ways on 2026-08-27: with the old check, tier `twiter-typo`
returned `pass`; with the fix, `could not measure`.

### What still needs the owner

The allowlist request. Six hosts, each blocking a specific question:

| host | what it unblocks |
|---|---|
| `arxiv.org` | the Kling-Avatar paper — the only paper-tier source for the avatar route |
| `kling.ai` | Kling lip-sync limits; `max_seconds` is **contested** in the base, 10 vs 15 |
| `docs.bfl.ai` | Flux — every recorded claim about it is blog tier |
| `help.runwayml.com` | Runway Gen-4.5 — `max_resolution` is **contested**, 720p vs 4K |
| `elevenlabs.io` | the voice-clone consent gate and training minutes |
| `docs.cloud.google.com` | Veo 3.1 — `cloud.google.com` is already allowed, only this subdomain is refused |

That last row is worth leading with: the allowlist already contains the parent
domain, so it is a narrowing, not a new grant.

## `search_web` — the research entry point

The owner's question was blunt and correct: every other assistant has a
built-in search, so what is the problem here. The answer was nothing — nobody
had looked for a backend this session is allowed to reach.

**Measured 2026-08-27, 19 search endpoints probed:**

```
open    customsearch.googleapis.com   www.googleapis.com
closed  api.search.brave.com  api.tavily.com  api.exa.ai  serpapi.com
        google.serper.dev  duckduckgo.com (+ html/lite/api)
        api.bing.microsoft.com  searx.be  api.perplexity.ai  api.you.com
        api.openalex.org  api.semanticscholar.org  api.crossref.org
```

`api.github.com` answers but refuses its search paths — this session is bound
to its configured repositories and returns *"Use repository-scoped
endpoints"*. So GitHub is a fetch channel, not a search one.

One backend is open, and one is enough. Google's Programmable Search JSON API
came back with a proper API error rather than a tunnel refusal, and that is
the whole difference: **it wants a key, not an allowlist change.**

### Turning it on

Two free values, into the environment:

```
GOOGLE_SEARCH_KEY   console.cloud.google.com → enable "Custom Search API" → create an API key
GOOGLE_CSE_ID       programmablesearchengine.google.com → new engine →
                    turn ON "Search the entire web" → copy the Search engine ID (cx)
```

Free tier is 100 queries a day. Unconfigured, the tool returns `could not
measure` and prints exactly those two names and where to get them — it does not
fail, because nothing was searched, and that differs from searching and
finding nothing.

### What search buys when half the web is still blocked

Two separate things, and confusing them is how this gets over-promised:

1. **A result carries information** — title, snippet, publisher, often a date.
   That is a citable source by itself, and it is exactly the material this base
   has been recording as `blog` tier all along.
2. **A result points at a page**, and whether that page opens is a different
   question per host. So every result comes back tagged `fetchable`, decided by
   trying the host rather than guessing, and the note counts both:

   > *8 result(s); 5 on hosts this session can open, 3 on hosts the policy
   > refuses. A refused host still gives you its snippet and its URL to cite —
   > it just cannot be read in full.*

`site:` works even against a blocked domain: the snippets still come back.

Searching does not widen the egress policy and this module does not pretend
otherwise. It finds the door; `fetch_url` says whether it opens.

### Verified

13 tests, none touching the network. Mutation red in both directions: zero
hits forced to `pass`, missing credentials ignored, the per-host probe cache
removed, the page-size clamp removed — each turns the suite red, with a green
control before and after.

### A correction: "Search the entire web" is gone

This document recommended turning that switch on. **That advice was already
wrong when it was written.** Google withdrew "Search the entire web" for NEW
Programmable Search engines in **March 2026**; a new engine is capped at 50
named domains, and engines still on the full index must migrate by
2027-01-01. The owner hit the wall in the setup form and asked whether general
Google search could just be connected instead. It can.

**Measured 2026-08-27** — every `*.googleapis.com` host probed answers:

```
discoveryengine.googleapis.com  generativelanguage.googleapis.com
aiplatform.googleapis.com  vertexai.googleapis.com  us-central1-aiplatform...
```

So `search_web` now has two backends, and prefers the one without a list:

| backend | key | coverage |
|---|---|---|
| **Gemini grounding** (preferred) | `GEMINI_API_KEY` from aistudio.google.com | the whole index, no domain list |
| Programmable Search (fallback) | `GOOGLE_SEARCH_KEY` + `GOOGLE_CSE_ID` | at most 50 curated domains |

`backend` in every result says which one answered.

A curated list is not merely tedious here, it is wrong for this job in a way
already measured: `cloud.google.com` is reachable and `docs.cloud.google.com`
is not. Vendors move documentation between subdomains, and a fixed list stops
covering them without ever saying so.

**Stated plainly: the Gemini response parsing is UNVERIFIED.** No key has been
available on this machine, so it follows the documented `groundingMetadata`
shape and is written to survive a shape it does not recognise. The first real
call is the test, and it belongs to the owner. One documented wrinkle is
handled up front: the URLs in `groundingChunks` are Google redirect links, not
publisher addresses, so the host is taken from `web.title` instead.

## `plan_pipeline`: decisions read from the spec first (round 15)

The product contract is that the CALLING model fills `spec` — it reads the
customer's brief in any language — and `plan_pipeline` plans from `spec`. Round
15's hidden set showed what happened when a decision was keyed on words of the
brief instead: the round 13-14 fixes worked in English and Russian and failed on
the same orders written in Chinese, Japanese, Korean, Spanish, Portuguese,
German and French (a single-take length caveat, a training-data licence caveat,
cross-shot light, lettering edits routed to a character swap, a face-swap data
set, series dialogue without lip sync, a visualiser given a lip-sync step).

The rule now, for every decision below: **the spec field decides when the caller
filled it; the EN/RU words are read only when it is absent; when the field and
the words disagree, the field wins.** Each new field is typed and strict (an
unknown value is a spec error naming the allowed list), is listed in the tool
description, in `spec_needed.allowed`, and — for a text-only call answered with
`нужна_спецификация` — in `spec_needed.draft.decision_fields` with what the
fallback words would have read (`read_from_text`; null on a brief the words do
not cover, which is exactly when the caller must fill it).

### Inventory: decision -> spec field -> fallback words

New fields of round 15 are in **bold**. Tests: `studio/tests/test_round15_spec.py`
(each decision: the field alone with a zh/ja/ko/es/pt/de/fr brief, the field
against contradicting words both ways, the words with the field absent);
mutants: `scripts/mutate_round15_spec.py`.

| decision (module) | spec field (first) | fallback words (only when the field is absent) |
|---|---|---|
| live / interactive system is a recorded gap, not a batch plan (`realtime.applies`) | **`live`** | `realtime.LIVE`, `SPEED` + `INTERACTIVE` |
| lettering edit is a video edit, not a character swap (`edit_intent.wants_text_edit`, `reroute`) | `edit: ["replace-text"]`, then **`edit_target`** (`text` / `person` / …) | `edit_intent.TEXT_EDIT_WORDS`, `PERSON_EDIT` |
| on-screen speaker gets a lip-sync step — presenter, series dialogue, cutscene (`brief_spec.говорят_в_кадре`) | `lipsync` on a generated clip, then **`people[].on_screen` + `people[].speaks`** | `ON_SCREEN_SPEAKER`, `SPEAKING_IN_FRAME`, `DIALOGUE`, `CHARACTER_VOICES`, `CUTSCENE`, `VOICE_OFF_FRAME` |
| performer sings the customer's track on camera -> lip sync (`brief_spec.поют_в_кадре`) | `lipsync`, **`people[].on_screen` + `people[].speaks`** | `SINGING` minus `NO_PERFORMER`, `PERFORMER_NOT_ON_SCREEN`, **`NO_LIPSYNC`** |
| music video with one performer -> performer reference (`brief_spec.клип_с_исполнителем`) | **`people[].on_screen`**, `lipsync` | `PERFORMER`, `SINGING` |
| visualiser with nobody on screen: loops, no performer, no lip sync (`brief_spec.визуализатор`) | `task: music-visualiser`; a person with **`on_screen: false`** does not block it; `lipsync: false` | `VISUALISER_WORDS` |
| short generated clip where someone speaks -> native audio (`brief_spec.говорящий_ролик`) | `audio`, then `lipsync` / **`people[].on_screen` + `speaks`** | `SPEAKING_IN_FRAME`, `VOICE_OFF_FRAME` |
| characters share the frame -> keyframe edit per shot (`brief_spec.персонажи_в_одном_кадре`) | **`cast_together`** | `CAST_TOGETHER`, `DIALOGUE`, `NO_DIALOGUE` |
| recurring character -> one reference + edits (`brief_spec.персонажи_по_умолчанию`) | `characters`, `people[].real: false`, **`consistency: ["character"]`** | `RECURRING_CHARACTER`, `SERIES_WORDS` + `SERIES_HERO`, `клип_с_исполнителем` |
| single take longer than one run (`checklist.single_take_limit`) | **`single_take_s`** (else `per_shot_s` / `duration_s` / `shots`, and the chosen model's `run_limit`) | — (structure only) |
| outputs used as ML training data (`checklist.outputs_as_training_data`) | **`training_use`** | `checklist.W_TRAINING_DATA` |
| face-swap data set: consent per identity (`checklist.face_swap_dataset_consent`) and its size (`brief_spec.face_swap_items`) | **`dataset_count`**, **`training_use`**, `shots`, `inputs[].count` | `W_TRAINING_DATA` |
| relighting / one light across shots (`checklist.relight_limits`) | `edit: ["relight"]`, **`consistency: ["light"]`**, **`edit_target: "light"`** | `checklist.W_RELIGHT` |
| seamless loop caveat (`checklist.seamless_loop`) and loop clip length (`apply.loop_seconds`) | **`outputs[].loop`** | `checklist.W_LOOP`, `apply.LOOP`, `LOOP_LENGTH` (the length) |
| tileable texture | **`outputs[].tileable`** (parsed for the round-15 knowledge rules) | — |
| transparent background: alpha delivery, no alpha-only upscaler on an opaque frame (`apply.wants_alpha`, `upscale_reach.alpha_specialised`) | **`outputs[].alpha`** | `apply.ALPHA`, `ALPHA_EXPLICIT`, `checklist.W_HOLOGRAM` |
| made for kids (`checklist.made_for_kids`) | `audience` (`children`) | `checklist.W_KIDS` |
| how many pictures are priced (`planner.кадров_заказано`) | `shots` | `_КАДРОВ_ЗАКАЗАНО` ("6 images") |
| frame rate (`planner.fps_из_брифа`) | `fps` | `_FPS_В_БРИФЕ` |
| length of the clip / one shot (`planner.длительности_плана`) | `duration_s`, `per_shot_s`, `inputs[].duration_s` | `duration.просят` |
| what the customer brings (`planner.входы_плана`) | `inputs` | `inputs_of` (HAVE_*_CUES) |
| own presenter reading own newsroom's news is planned (`inhouse_news.decide`) | `people[].role`, `consent`, `claim`; `claims[].own_brand`, `fabricated`, `real_brand` | none — structured only |
| synthetic presenter of own programme is planned (`synthetic_presenter.decide`) | `people[].real: false`; `claims[].own_brand`, `fabricated`, `parody`, `brand` | none open it; `FABRICATED_WORDS`, `broadcast_marks.BROADCASTER` in the brief only CLOSE it (a refusal guard, never a door) |
| video edit by assembly (trim, LUT, crop, burn captions …) (`brief_spec.правки_монтажа`) | `edit` | `монтажные_правки_словами`, `KEEP_WHOLE_FRAME`, `STYLE_WORDS` |
| sign language is a recorded gap (`brief_spec.sign_language`) | `languages` (`ase`, `bfi` …) | `SIGN_WORDS` |
| upscaler reach, per-frame upscalers, alpha upscalers (`upscale_reach`) | — | reads the MODEL's recorded rows, not the brief |

The plan's text-only path (`план_по_тексту`, golden set and rendering tests) and
the draft of the spec question still read everything from words
(`planner.OPERATIONS[*].cues`, `brief_spec.from_text`, `DRAFT_*_CUES`): the draft
is never a plan, and `plan_pipeline` plans only from spec.

### Round 16: the rest of the words-only list moved to fields

Round 15 left the expert caveats of `studio/recipes/checklist.py`, the recipe words
of `studio/recipes/apply.py` and the planner's community words on EN/RU keywords
(each caveat named the field it would need in `spec_field`). The round-16 hidden
set failed exactly there: a halftone newspaper scan in Spanish got no descreen
note; passers-by anonymised in German got no model and no GDPR note; a witness
whose voice had to be unrecognisable was planned as a DUB (a dubbing endpoint is
built to keep the speaker's timbre); a documentary face swap got no model and no
price; a cut into shorts with no voice-over got no no-speech note.

Every decision below now has its field, with the same rule as round 15: **the
field decides when the caller filled it, the EN/RU words are read only when it is
absent, a named field wins both ways.** The readers live in `studio/spec_first.py`
(each returns None when the field is not named); the caveats read them through
`checklist.SPEC_FOR_WORDS` (one line per word set). All new fields are strict (an
unknown value is a spec error with the allowed list), listed in the
`plan_pipeline` description, in `spec_needed.allowed` (`brief_spec.OPTIONAL_HELP`)
and in `spec_needed.draft.decision_fields` with what the fallback words read
(`brief_spec.DECISION_FIELDS_R16`). Tests: `studio/tests/test_round16_spec.py`
(every caveat of `spec_fields_to_add()` with the field alone in a zh / ja / ko /
es / pt / de / fr / it / tr / ar brief, the named "no" against EN words, the EN
words without the field, and the same foreign brief without the field silent);
mutants: `scripts/mutate_round16_spec.py` (59, both ways).

| decision | spec field (round 16) | fallback words |
|---|---|---|
| anonymisation route and the GDPR caveat (`anonymise.face_method` / `voice`, `checklist.anonymisation_gdpr`, `voice_anonymisation`) | **`anonymise`** `{faces, voice, method: swap \| blur \| pixelate \| voice-replace}` or `false` | `W_ANONYMISE`, `expert_r15.SWAP_WORDS` / `BLUR_WORDS`, **`W_VOICE_ANON`** (anonymity words only — «change the voice» is not one) |
| no-speech short (`no_speech_short`) | **`voiceover: false`**, then **`audio_content`** without `speech`, then `people[].speaks` | `W_NO_SPEECH` — structure alone (a cut from own footage) does not decide |
| platform caveats: broadcast, cinema / DCP, premium streaming, podcast, audiobook, telephony, voice agent, game engine, marketplace, print, VFX, editorial, app store, music distribution, social encode / thumbnail / short-form cap | **`delivery.platform`** | `W_BROADCAST`, `W_CINEMA`, `W_STREAMING`, `W_PODCAST`, `W_AUDIOBOOK`, `W_TELEPHONY`, `W_VOICE_BOT`, `W_GAME`, `W_MARKETPLACE`, `delivery.PRINT`, `W_VFX`, `W_EDITORIAL`, `W_APP_STORE`, `W_DISTRIBUTION`, `W_MONETISE`, `W_PLATFORM` |
| HDR master; M&E stems; outbound AI calls; 3D model delivery; the French retouched-photo label | **`delivery.dynamic_range`**, **`delivery.stems`**, **`delivery.direction`**, **`delivery.format`** (glb / usdz …), **`delivery.markets`** (FR) | `W_HDR`, `W_LOCALISE`, `W_OUTBOUND`, `apply.MESH`, `W_FRANCE` |
| advertising, health / financial ads, branded content, news / documentary label, real estate, political | **`domain`** | `W_AD`, `W_HEALTH`, `W_FINANCE`, `W_SPONSORED`, `W_NEWS`, `W_REAL_ESTATE`, `W_POLITICAL` |
| photoreal disclosure, anime on twos, drawn / stylised faces (lip sync model, drawn dub) | **`style`** (photoreal \| stylised \| limited-animation) | `W_REALISTIC`, `W_ANIMATION_TWOS`, `W_STYLISED_FACE`, `apply.DRAWN` |
| product fidelity, cosmetics, reflective / transparent material, before-after, logo / exact text, try-on garment, property walkthrough, mascot (whole-character swap), retouched person | **`subject`** (and `edit_target: person` for a retouch; `domain: real-estate` also opens the walkthrough) | `W_PRODUCT`, `W_COSMETIC`, `W_REFLECTIVE`, `W_BEFORE_AFTER`, `apply.LOGO` / `TEXT_EXACT`, `W_TEXT_IN_FRAME`, `apply.TRY_ON` + `GARMENT`, `apply.WALKTHROUGH`, `apply.CHARACTER` / `FACE_ONLY`, `W_RETOUCH` |
| captions / audio description (WCAG) — now per need | **`accessibility`** | `W_A11Y` (both rules) |
| hologram on black | **`display: additive`** | `W_HOLOGRAM` |
| vocal stem of a song | **`audio_content: ["song"]`** | `W_SINGING` |
| print scan descreen; audio clean-up; deblur on archive film | **`inputs[].defects`** (halftone \| noise \| hum \| echo \| blur …), `inputs[].source: print-scan` | `W_HALFTONE`, `W_AUDIO_CLEAN`, `apply.BLUR` |
| slides / screen recording, archival grain and disclosure, cine film speed, timelapse, green screen, stock licence, cover song | **`inputs[].source`**, **`inputs[].fps`** (≤ 20 = cine film) | `W_SLIDES`, `W_ARCHIVAL`, `W_CINE_FILM`, `W_TIMELAPSE`, `W_GREEN_SCREEN`, `W_STOCK`, `W_COVER_SONG` |
| sound follows the brought picture (video-to-audio) | **`follows_picture`** | `apply.FOLLOWS_PICTURE` |
| visualiser: static audiogram vs animated art; loops vs scenes | **`animate_input`**, `outputs[].loop` (false = scenes) | `apply.ANIMATE_ART`, `apply.SCENES` (in `conditions`) |
| community checkpoints / LoRA / workflows | **`community`** | `planner.COMMUNITY_ASKED`, `endpoints.COMMUNITY_ASKED` |
| everything on the customer's machine | `self_host` (now: `self_host: false` is a named no), `open_weights` | `apply.LOCAL_ONLY` |
| flashing / strobe content | `conditions: ["flashing"]` (existing field; a caller-written EN phrase) | `W_FLASH` |

**Routes (spec-driven, `studio/anonymise.py`).** Faces: `swap` (the default) = one
generated synthetic face + a video face swap, priced per second, with the blur
named as the irreversible alternative; `blur` / `pixelate` = at assembly, 0 usd.
Voice: the speech is transcribed (redacted before synthesis) and re-spoken by a
DIFFERENT stock TTS voice — dubbing, voice cloning and lip sync steps are removed,
clone endpoints are ranked last on the TTS step, and a same-language
`dub-translate` with `anonymise.voice` takes this route (its checklist no longer
carries the dub's translation caveats). Both = both. The GDPR caveat
(`anonymisation_gdpr` on pictures, `voice_anonymisation` on voices) names
irreversibility, missed faces / voices and the DPIA.

**Face swap with no face image listed (documentary, consented).** `task:
face-replace` on the customer's video with no image in `inputs` had no candidate:
every video face-swap endpoint `requires_inputs` an image, and the candidate
filter did not count the reference the route already names as an assumption
("the new face comes from YOUR reference image — attach it"). It is counted now
(`anonymise.assumed_inputs`), so the step gets its face-swap model and clip price;
the assumption line still asks the customer to attach the photo.

Still words only, by design: the text-only path (`план_по_тексту`, the draft of
the spec question) reads everything from words — it is never a plan. Flashing
content uses the existing free-text `conditions`. `W_SELL_STOCK` (the outputs
are SOLD to a stock site — it only silences the stock-licence caveat) and
`checklist.W_INTERVIEW` / `W_DIALOGUE` (read beside `people` and `characters`,
which decide first) keep their words.

## `plan_pipeline`: model expertise and pricing (round 16)

`studio/expert_r16.py` holds the round's decisions; each reads a spec field first and
the EN/RU words only when the field is absent. Tests: `studio/tests/test_round16_knowledge.py`
(EN, RU and at least one other language per theme, both ways); mutants:
`scripts/mutate_round16_knowledge.py`.

| decision | spec field (first) | fallback words |
|---|---|---|
| open weights with no API route run on the customer's GPU (ASR: faster-whisper, Whisper, Parakeet) instead of "no candidate" (`open_weights_route`) | `open_weights` (without `self_host`) | — |
| sensitive transcription caveat: self-host, pyannote diarisation, human review (`checklist.confidential_transcription`) | `self_host`, `open_weights` | `expert_r16.W_SENSITIVE` |
| a still whose job is lettering is ranked by RECORDED text rendering (`text_legibility`; a `text_rendering` value is "for" only on that condition, never as general good news) | `conditions` (any language, `attrfamily.УСЛОВИЯ_СИНОНИМЫ`) | `W_TEXT_HEAVY`, a quoted string in any script |
| spatial / VR / 360 sound caveat (ambisonics, binaural, head tracking, stereo models, spatialiser at assembly) | **`outputs[].spatial`** (new flag of a sound output) | `W_SPATIAL` |
| a video edit takes the cheapest adequate tier of its evidence band (frame not below the order) | `objective: quality` keeps the premium | — |
| a lip-sync / avatar batch (3+ clips) takes the cheapest adequate model (output recorded, frame not below) when the chosen one costs more than 1.5x | `objective: quality` keeps it | — |
| a narrated series / explainer of 4+ shots without characters is made from key visuals (t2i per shot, then i2v) | `consistency: ["style"]` | `W_SERIES_EXPLAINER` (sets `consistency` as an assumption) |
| a narrator off screen gets no lip sync | `people[].on_screen` / `speaks`, `lipsync` | `VOICE_OFF_FRAME` (now with «за кадром», «рассказчик») |
| a drawn (anime / cartoon) dub adapts the script to the mouth flaps; visual lip sync is an OPTIONAL step priced apart (`steps[].optional`, `pipeline_price.conditional_steps[].optional`, not in the clip price) | `lipsync: true` makes it required | `apply.DRAWN` (conditions / words) |

New facts (2026-10-20, sources in each row): Parakeet TDT 0.6B v3 (licence, ASR tag, 25
languages, long form), faster-whisper / whisper.cpp GPU seconds per 13-minute clip (the
self-host compute estimate), text rendering of Ideogram 3, Recraft V3, FLUX.2 / FLUX.2 [flex],
Qwen-Image, Nano Banana Pro / 2.1 and the GPT Image models' own limitation; gaps recorded
for Imagen 4 and Seedream 5 (hosts refused or pages client-rendered, `denied_hosts.jsonl`).

### Round 16 integration: where the two halves meet

`outputs[].spatial` is the one output-item flag the expertise half added
(`brief_spec.OUTPUT_ITEM_FLAGS_R16`); it parses beside `loop` / `tileable` /
`alpha` on its own item, is listed in the `plan_pipeline` description, in
`spec_needed.allowed` and in `spec_needed.draft.decision_fields`
(`brief_spec.DECISION_FIELDS_R16_OUTPUTS`, read from `expert_r16.W_SPATIAL`
when absent). Decisions settled where a field of one half meets a rule of the
other (tests: `studio/tests/test_round16_integration.py`):

| interaction | outcome |
|---|---|
| `anonymise.voice` on a drawn (anime / cartoon) dub | the voice route (transcript + a different stock voice) wins; no dub, no optional lip-sync upgrade, and the "adapted to the mouth flaps" assembly line is dropped with the dub (`recipes.apply.DUB_ONLY_ASSEMBLY`) |
| a video edit whose `edit_target` is not the person + `anonymise.faces` | the edit stays on the route next to the face route (`recipes.apply.ANONYMISE_KEEPS_EDIT`) and keeps its own model choice, the edit-tier swap included; with `edit_target: person` or none the edit is the anonymisation and is replaced as before |
| `voiceover: false` + series / explainer words | not a narrated series: the words do not switch to key visuals (`expert_r16.key_visual_words`); `consistency: ["style"]` still does |

## `plan_pipeline`: the missing routes (round 17)

A fresh hidden set found seven orders the planner had no route for. Each is now a route in
`studio/routes_r17.py` (hooked into `recipes.apply.rewrite`, one prior and one recipe each in
`recipes/table.py`), decided by a spec field in any brief language; the EN/RU words are read only
when the field is absent, and a named field wins both ways. New fields were added only where no
existing one could carry the decision; all are strict, listed in the `plan_pipeline` description,
in `spec_needed.allowed` (`brief_spec.OPTIONAL_HELP`) and in `spec_needed.draft.decision_fields`
(`brief_spec.DECISION_FIELDS_R17`, with what the words read). Tests:
`studio/tests/test_round17_routes.py`; mutants: `scripts/mutate_round17_routes.py` (both ways).

| route | spec field (first) | fallback words | plan |
|---|---|---|---|
| translate footage with BURNED-IN subtitles | **`inputs[].subtitles`** burned \| soft \| none (video item) | `routes_r17.W_BURNED_SUBS` | transcript (ASR, priced) + OCR of the strip and machine translation as priced assembly lines (Google Video Intelligence text detection $0.15/min over 1,000 free min; Cloud Translation NMT $20 / 1M chars over 500k free) -> the old band removed by a masked edit (`edit: remove-object`, `edit_target: text`, priced per step) -> new subtitles burned in at assembly, or a soft SRT / WebVTT track when `delivery.format` has srt or every `delivery.platform` takes one (`SOFT_SUB_PLATFORMS`); a dub-translate order keeps its dub and gets the removal step; caveat `burned_subtitles_translation` |
| singer music video from a performer reference | `lipsync`, `people[].on_screen + speaks`; **`performer_shots`** | `brief_spec.SINGING` | performer photos (or one generated reference) -> reference-to-video on the performer shots -> lip sync on THOSE shots only (seconds = performer shots × shot length); the other shots: key stills -> image-to-video, no lips. The planner no longer folds lip sync + i2v into one avatar step when the plan has the r2v step |
| 3D walkthrough / tour of a real place | **`reconstruct_3d`**; `delivery.format` **ply \| splat \| spz** | `routes_r17.W_SCENE_3D` | one step `реконструкция_3d` (gaussian splat: COLMAP poses, gsplat / nerfstudio splatfacto, Apache-2.0; the Inria original is non-commercial) with no orderable endpoint; capture guidance, a rendered camera path or a viewer file at assembly; the compute price is a RECORDED GAP (`gaussian-splat-training.gpu_seconds_gap`), never a guess; no video model on the route; caveat `splat_scene_capture` |
| consented internal deepfake for security-awareness training | `domain` **security-awareness** + `delivery.platform` **internal** (only) + `people[]` real, consent stated, role employee / self | none open it; `consented_simulation.W_KEEP_REFUSED` (politics) only CLOSES it | `studio/consented_simulation.py` lifts ONLY the public-figure + news-statement refusal of the customer's own consenting staff, after the same order re-screened with that claim read as "other" passes every screen (the screens are called, never read or changed); voice clone + TTS + lip sync (or avatar) planned with a visible watermark line at assembly and caveat `consented_simulation_safeguards` (written consent record, C2PA, internal LMS only, debrief, deletion date). Missing consent, an external platform, an endorsement, a political claim, a hired actor: refused as before |
| whole-person replacement vs face swap | `edit` **replace-person** | `routes_r17.W_WHOLE_PERSON` (beside a person edit, only when `edit` is not named) | `замена_фигуры` (Wan Animate replace class, e.g. wan-2.2-14b-animate-replace 720p $0.08/s), a generated character reference first when none is brought; `face-replace` without it stays a face swap |
| UGC product batch | **`products`**; brought product photos with `subject: product` | `routes_r17.W_PRODUCTS` + `W_UGC` / `subject` | stills = one shared presenter + one packshot per product (not brought), never a still per clip; the stills are a shared asset |
| narration named, no audio brought | `voiceover: true`, `audio: voiceover`, `audio_content: ["speech"]` (a named `voiceover: false` wins) | — | `speech` joins the outputs (`routes_r17.with_narration`), so the route has a TTS step; on the customer's own video only `voiceover` / `audio` name a narration (its own speech is not one) |

Facts recorded 2026-10-20 (sources in each row): Google Cloud Translation NMT and Video Intelligence
text-detection prices, gsplat licence and memory / time claim, nerfstudio splatfacto VRAM and export,
the Inria gaussian-splatting non-commercial licence and 24 GB VRAM. Gaps recorded (hosts refused,
`denied_hosts.jsonl`): Postshot (jawset.com), Polycam (poly.cam), Luma 3D capture (lumalabs.ai) prices
and GPU minutes per splat scene (docs.gsplat.studio).

## `plan_pipeline`: specialist knowledge and pricing (round 17)

`studio/expert_r17.py` holds the round's decisions; each reads an EXISTING spec field
first and the EN/RU words only when the field is absent (no new top-level field; one new
`edit` value). The caveats are `checklist.RULES_R17`, each with its source URLs and EN/RU
text; the pricing is three recipes in `studio/recipes/apply.py` (priors in
`recipes/table.py`, switchable with `spec.priors`). Tests:
`studio/tests/test_round17_knowledge.py` (EN, RU and at least one other language per theme,
both ways, literal totals); mutants: `scripts/mutate_round17_knowledge.py`.

| decision | spec field (first) | fallback words |
|---|---|---|
| audio description is a production: script in the dialogue gaps, extended AD (SC 1.2.7) where gaps are short, a voice distinct from the cast, ducking, a separate AD stem + audio language track, captions apart (`audio_description_track`) | `accessibility: ["audio-description"]` (input or output video) | `W_AUDIO_DESCRIPTION` |
| an accessibility package (captions / transcribe on the customer's video) with AD: ONE transcript (captions, text, translation and the gaps come from it) and a description voice (`озвучка`, clone-only models ranked last) priced for `AD_GAP_SHARE` = 15 % of the runtime, not the runtime (prior `ad_gap_voice`) | `task`, `accessibility` | as above |
| code-switching speech: per-segment language ID (Whisper fixes one language from the first 30 s; Deepgram `language=multi`, faster-whisper `multilingual=True`), per-segment tags, a multilingual voice, ONE mixed track priced once (not × languages) (`code_switching_speech`) | the `mul` language tag; `conditions` | `W_CODE_SWITCH` |
| client / personal / confidential uploads to hosted APIs: retention, training, region, DPA, deletion — OpenAI 30-day abuse logs, fal request history + public CDN URLs by default (`X-Fal-Store-IO: 0`), ElevenLabs Zero Retention Mode enterprise-only and not for dubbing (`provider_data_terms`); not on `self_host`, not beside `confidential_transcription` | `training_use: true`, `people[].minor`, `domain` ∩ {corporate, health-advertising, financial-advertising}, `self_host` silences | `W_CLIENT_DATA` |
| highlight / recap moments: shot detection (PySceneDetect, TransNet V2) + transcript ranking, a human pick, tracked reframing, nothing regenerated (`highlight_selection`) | `task: cut-to-shorts` | `W_RECAP` |
| a recap of the customer's series: the cut is assembly (a recap ordered as `video-edit` with no `edit` / `edit_target` loses the generative edit) and the narrator is priced by the RECAP length (`duration_s`, or `shots` × `per_shot_s`), never the series (prior `recap_short_vo`) | `audio: "voiceover"`, a script input with a speech output | `W_NARRATION` |
| frame-rate standards conversion: motion-compensated 25 <-> 29.97, PAL speed-up with pitch correction for 23.976 -> 25, 2:3 pulldown, deinterlace first (`standards_conversion`) | `inputs[].fps` against `fps`, else `delivery.markets` (60 Hz markets `NTSC_MARKETS`; a web / social `delivery.platform` keeps the native rate) | `W_STANDARDS` |
| stem separation: Demucs v4 / BS-RoFormer facts, artefacts, ask for the multitrack / M&E first, separation is not a licence (`stem_separation`) | `delivery.stems` on brought audio / video | `W_STEM_SEPARATION` |
| background blur (bokeh) of own footage: a person matte (`удаление_фона_видео` step) + lens blur at assembly, never a generative video edit; hair halos, temporal stability (`background_blur`, prior `matte_background_blur`) | **`edit: ["blur-background"]`** (aliases bokeh, background-blur, depth-of-field), `edit_target` | `W_BACKGROUND_BLUR` |

Measured on the round's own cases (no paid call): a 60-minute lecture package in two
languages 0.89 usd (transcript 0.48 + 2 × 540 s of description voice), a 90-second recap of
ten 12-minute episodes 1.07 usd (transcript of all 7200 s 0.96 + a 90 s narrator), a 3-minute
bokeh interview 9.00 usd (a hosted matte at 0.05 usd/s; the generative edit it replaces was
25.20 usd), a 30 s Spanglish spot 0.04 usd (one mixed track, 0.07 usd as two versions).

New facts (read 2026-10-20, sources in each row): Demucs v4 (MIT, 9.0 / 9.2 dB SDR, stems,
karaoke mode, unmaintained repo; fal Demucs 0.0007 usd/s), BS-RoFormer (9.80 dB SDR, SDX23
first, arXiv 2309.02612), Robust Video Matting (GPL-3.0, recurrent, speeds), Video Depth
Anything (Small Apache-2.0, Base / Large CC-BY-NC-4.0), SAM 2 (MIT), Whisper's 30-second
language detection, faster-whisper's per-segment `multilingual`, Deepgram code-switching,
ElevenLabs Zero Retention Mode coverage for Scribe v2, Eleven v3 and dubbing (new attribute
`data_retention`, family `restrictions`). Refused by the egress proxy and recorded in
`denied_hosts.jsonl`, not routed around: w3.org, ffmpeg.org, trac.ffmpeg.org, ada.gov,
ecfr.gov, ebu.ch (the rules still cite the canonical URLs).

## `plan_pipeline`: round-17 integration (routes × knowledge)

`checklist.RULES_R17` is ONE tuple: `RULES_R17_ROUTES + RULES_R17_KNOWLEDGE`. Tests:
`studio/tests/test_round17_integration.py`; mutants: `scripts/mutate_round17_integration.py`.

| interaction | plan |
|---|---|
| recap / `cut-to-shorts` of footage with `inputs[].subtitles: burned` | the removal of the old band is added beside the cut and priced on the CUT's seconds (`duration_s`, per clip by `shots`), the transcript once over the material; a recap ordered as `video-edit` keeps the removal (the recap rewrite no longer replaces it with the transcript) |
| burned-subtitle route | the "your SRT burned in — no transcription needed" assembly line is dropped (the route transcribes and burns its own subtitles) |
| `mul` language tag + burned subtitles | `mul` is the source's mixed speech, never a translation target: the translation line is priced for the real targets only |
| `edit: ["blur-background", "replace-person"]` | both: `замена_фигуры`, then `удаление_фона_видео` over the replaced footage and the blur at assembly |
| consented internal drill (`studio/consented_simulation.py`) | the door also stays closed for a `minor` person, a minor named in the brief (`W_MINOR`, words only close), a `fabricated: true` claim, and `spec.audience` other than absent / `adults` (`INTERNAL_AUDIENCES`) |

## `plan_pipeline`: routes and decomposition (round 18)

A fresh hidden set found plans with the right job but the wrong decomposition: a try-on batch with no
on-model base, a restoration chain without its upscale / colour links, a batch of game barks priced as
one clip, a podcast rendered as 45 minutes of text-to-video, a vertical cut done by a generative edit, a
motion comic with a talking avatar, a dance from a still per shot, a 3D tour that asked a question. Each
is now a route in `studio/routes_r18.py` (spec transforms from `brief_spec.with_defaults`, steps from
`recipes.apply.rewrite`; one prior and one recipe each in `recipes/table.py`). The contract of rounds
15-17 holds: a named field decides both ways in any brief language; the EN/RU words are read only when
it is absent. Tests: `studio/tests/test_round18_routes.py`; mutants: `scripts/mutate_round18_routes.py`.

| route | spec field (first) | fallback words | plan |
|---|---|---|---|
| on-model product images | **`inputs[].role`** (model / garment / product), `products`, **`views`** | `W_MODEL_PHOTO`, `W_NO_MODEL`, `W_GARMENTS`, `W_VIEWS` | no model photo: ONE generated model, a still per view (shared asset) -> `примерка` per SKU × view (e.g. 6 × 3 = 18 try-ons at 0.04 usd = 0.72 usd + 3 base stills); a model photo: try-on only. Without a role, one photo item of N = N garments; two items = garment + model (the r10 reading) |
| archival photo / film restoration | `task` chain (a named chain is kept), **`colorize`**, `resolution` vs `inputs[].resolution`, `fps` vs `inputs[].fps`, `inputs[].source / defects`, `people` / `subject: person` | `W_COLORIZE` / `W_KEEP_BW`, `W_UPSCALE`, `W_INTERP`, `W_RESTORE`, `W_FACES` | restore -> `восстановление_лиц` (new step, registry job `face-restore`: codeformer on fal, 0.0021 usd/MP) on photos with faces -> colourise -> upscale to the delivery frame (named `resolution` above `inputs[].resolution`; with the source frame unknown only a 4K-class delivery; colour before upscale is the r8 order: colourise at the source frame) -> film: deflicker / true speed at assembly, interpolation only when `fps` is above the source's; faces in film are a self-host line (no video endpoint recorded) |
| batch of speech lines | **`lines`**, **`variations`**, `characters` (voices), `shots` on a speech-only order | `W_LINES`, `W_VARIATIONS` | one `озвучка` step priced on lines × voices × variations × the line's characters (line length: `per_shot_s`, else game 2 s / telephony 6 s / web or education 8 s / 4 s); the Runway eleven_v3 per-request minimum (1 credit = 50 chars) priced beside it; one file per line + a manifest |
| podcast / interview audio -> video | `audio_content` (speech, not song), `delivery.platform` podcast; an avatar only with `lipsync` / task `avatar` / people on screen speaking | `W_PODCAST` vs `W_SONG`, `W_AVATAR` | one cover still (none when brought) + a transcript of the whole episode (priced) -> cover + waveform + captions at assembly (soft track for youtube, burned for tiktok / reels); the clip price is the plan price (`ASSEMBLED_CLIP_PRIORS`) |
| vertical cut of horizontal footage | `aspect` (W:H < 1) over `inputs[].resolution` not vertical, no `edit` named | — | `edit: reframe` derived -> the tracked crop at assembly; a transcript + burned captions for `SOCIAL_BURN_PLATFORMS`; the recorded `ltx-2.3-reframe` (0.10 / 0.20 usd per s) priced as the fallback line |
| motion comic | **`inputs[].source: comic`**, `inputs[].role: panel` (another source / role named = not a comic) | `W_COMIC` | `оживление` per panel (count = panels, seconds = duration / panels), `озвучка` (script / speech / voiceover; `voiceover: false` none), `звук_фон` unless `audio: none`; panel split and a 2.5D parallax alternative at assembly; no avatar, no lip sync |
| dance / idol performance | **`dance`** | `W_DANCE` | one full-length reference per performer not brought -> `перенос_движения` per performer (seconds × performers); a driving dance video is named as an assembly line (filmed in-house, or `inputs` video / `role: motion`); standard / Wan move / Act-Two ranked last (`DANCE_AVOID`): the kling-3.0 pro motion control (0.168 usd/s) is chosen |
| 3D tour without a task | `reconstruct_3d` unnamed, video / splat output; ≥ 20 photos with a 3D / virtual-tour intent, or a walk-through video with no photos | `W_TOUR_3D` (photo set), `W_TOUR` (video only; "walkthrough video" over photos stays the round-12 camera path) | `task` derived (no question) with an assumption line, `reconstruct_3d: true` derived -> the round-17 splat route |
| explainer with a script | `voiceover` / `audio` / `audio_content` / `lipsync` / `people[].speaks` all unnamed, a script brought, video out | — | `voiceover: true` derived with an assumption line -> a TTS step |
| avatar series with one presenter | task `avatar`, no photo / video, `shots` ≥ 2, ≤ 1 character | — | ONE presenter still (shared) |

New spec fields (strict, in `SPEC_FIELDS`, `OPTIONAL_HELP`, `DECISION_FIELDS_R18` and the tool
description): `inputs[].role`, `views`, `lines`, `variations`, `colorize`, `dance`; `comic` joins
`inputs[].source`.

Facts recorded 2026-10-21 (sources in each row): CodeFormer on fal (face restoration, 0.0021 usd/MP,
"Commercial use" label); the upstream CodeFormer S-Lab licence (non-commercial) under
`codeformer-upstream` (the row first written under `codeformer` was withdrawn and re-attributed: it
governs the self-hosted code, not the hosted endpoint; fal's label is `portal_license`; licence rows use the
base spelling `license`); GFPGAN Apache-2.0; Kling 2.6 motion control
records dance / full-body transfer from 3-30 s references (kling.ai guide); the standard Kling v3 motion
control is "for portraits and simple animations" (fal). Gaps recorded: no hosted GFPGAN endpoint (fal
search, 0 items); a per-request TTS minimum at ElevenLabs direct and at fal is not recorded.
