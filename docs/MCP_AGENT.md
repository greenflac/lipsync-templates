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
    -> card {colours: [ivory, slate, charcoal], value_key: dark,
             saturation: muted, texture: matte}
    -> "a palette of ivory, slate and charcoal, low-key shadowed lighting,
        desaturated restrained colour, matte, photographic look"
    -> gate: pass — 16 words (band 9..67), 6 clauses (band 1..13), 0 forbidden
```

### Who wins, and when it refuses

**The owner wins.** A value you name is taken as given; the corpus only fills
what you left silent, and every filled slot comes back with the record ids that
voted for it. A corpus value is accepted only with support from **two distinct
records** — one precedent saying "teal" is a coincidence, not evidence.

Where you said nothing and the corpus does not agree either, the slot is
reported unresolved and the run returns `could not measure` **with a question**:

```
"burgundy velvet under moonlight, elegant"
    -> could not measure — 2 of 4 card slots filled
    ask: Which colours? Name one to three of: amber, charcoal, copper, ...
    ask: How much colour — muted, moderate, saturated?
```

It does not pick. `saturation` in particular is never defaulted, because no
corpus field carries it: it is your word or it is a question.

Naming more colours than the engine takes is also a question, not a trim. The
engine truncates a wider palette silently, so a colour you named would vanish
from the prompt with nobody told.

## What is checked, and how it was verified

`bash scripts/check` gates ruff, ruff format, mypy, 32 tests and a live server
handshake for this package. Exit 0 as of 2026-08-27.

The handshake is not an import check: the tools register by decorator at import
time, so an import succeeds even when the transport is broken. It starts the
server, lists the tools and puts two prompts through the gate.

**Mutation, both directions** (`python -m unittest discover`, bytecode caching
off — see the caveat below):

| mutation | result |
|---|---|
| control, before any mutation | OK |
| `MIN_SUPPORT` 2 → 1 (weaker) | 2 failures |
| `MIN_SUPPORT` 2 → 3 (stricter) | 2 failures, 1 error |
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
  six for "saturated", four for "moderate". An owner who writes "chalky" gets a
  question rather than a guess, which is the safe direction to be wrong in.
* **Seven of the ten light words are placed by hand.** The engine's own table
  maps three; the other seven are a decision recorded in the source where it
  can be argued with.
