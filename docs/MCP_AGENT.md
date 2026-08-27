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

Five tools appear in the chat:

| tool | what it does |
|---|---|
| `model_advice` | everything known about a model, with every source and its date |
| `record_model_fact` | write one web finding into the base — **the only tool that writes** |
| `stale_model_facts` | which claims are old enough to need re-checking |
| `write_lipsync_prompt` | write a look prompt from your words plus the corpus |
| `check_lipsync_prompt` | judge any prompt, from any source, against the contract |

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

Tiers, and why a blog can never be promoted by repetition:

| tier | means |
|---|---|
| `vendor` | the vendor's own document or release |
| `benchmark` | an independent evaluation with a published method |
| `paper` | arXiv or a venue, with a method somebody can check |
| `blog` | everything else, including the good aggregators |

A claim carried only by blogs stays `could not measure` however many blogs
repeat it. Ten blogs quoting each other are one source.

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
