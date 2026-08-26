# Code review of the existing architecture

Reviewed on 2026-08-26, at commit `f5e5bfa`, on a fresh clone.

**Status: the four findings marked FIXED below were fixed later the same day,
after the module's owner asked for repairs rather than a hand-off. The measured
output that follows each one is what the code did BEFORE the fix — it is kept
because a finding with its evidence deleted is a finding nobody can re-check.
Everything marked OPEN belongs to a module this branch did not touch.**

The request said the architecture to review was "presented above". It was not
in the message. What exists is this repository's `studio/` package, and that is
what was reviewed: `studio/knowledge.py` (1302 lines, hybrid retrieval),
`studio/style.py` (621 lines, StyleSpec extraction and prompt assembly),
`studio/CONTRACTS.md`, and the surrounding web layer.

Everything below was run, not read. Commands and their output are quoted.

---

## What is genuinely good, and worth not breaking

**The security boundary is in the right place.** The model never writes the
prompt. It fills a frozen `StyleSpec` whose every field is an allow-list, and
`build_prompt` assembles the string in code. An injected instruction can change
a field's value; it cannot change what the prompt is made of. Most systems in
this space hand the model the final string and hope. This one does not, and the
new package inherits the boundary rather than reopening it.

**Three outcomes are real here, not decorative.** `gate_input` will not return
PASS when zero rules ran. `extract` distinguishes "the model returned
non-JSON" (unmeasured) from "the fields do not match the contract" (fail). That
distinction is the single most valuable thing in the codebase and it is applied
consistently.

**The retriever can say no.** `BM25_MIN_HITS`, `STRUCTURAL_MIN_FIELDS` and
`DENSE_FLOOR` are admission floors, and `retrieve` returns FAIL when nothing
clears them. A retriever with no floor always answers, and a retriever that
always answers is measuring nothing.

**The fusion is mutable and was actually mutated.** `FUSION_CHANNELS` is data,
and the docstring records what happened when channels were removed — including
the finding that the structural channel bought 0 recall and cost 0.079
precision. A recorded negative result is rarer than a recorded positive one and
worth more.

**Provenance is tracked as who wrote the text, not what shape it has.**
`PROVENANCE_WEIGHT` and `MAX_PER_PROVENANCE` are the right instinct: the
poisoning risk in a harvested corpus is about the author, and one answer should
not fill up with one source.

---

## FIXED — Critical: the retrieval system was empty on any machine but one

This is the finding that matters. Everything else is smaller than it.

`studio/knowledge.py` reads its two largest corpora from absolute paths:

```python
OUR_PROMPTS_DIR = Path("/home/user/cyclerunner/demo/instories/fixtures/gen")
REFERENCE_CARDS_DIR = Path("/home/user/cyclerunner/demo/instories/references")
```

On a fresh clone of this repository those directories do not exist. MEASURED,
2026-08-26:

```
$ ls /home/user/cyclerunner
ls: cannot access '/home/user/cyclerunner': No such file or directory

$ python3 -c "from studio.knowledge import build_index, retrieve, evaluate, load_eval_set; ..."
counts: {'core': 12, 'total': 12}
retrieve outcome: could not measure | examples: 0 | core: 12 | note: index holds no examples
evaluate: {'outcome': 'could not measure', 'checked': 0, 'unmeasured': 1,
           'note': 'index holds no examples'}
```

So: 12 entries instead of 822. Zero examples. Every retrieval answers "could
not measure". `evaluate` cannot run at all, which means **the headline numbers
in `HANDOFF_studio-mvp.md` — recall@5 0.9737, precision@5 0.7237 — are not
reproducible from this repository.** They may well be true; nobody outside that
one machine can check, and a number nobody can re-derive is a number that will
be quoted long after it stops being true.

The tests that should have caught this skip instead:

```
$ python3 -m pytest studio/tests -q -rs
SKIPPED [1] studio/tests/test_knowledge.py:620: the prompt fixtures are not on this machine
SKIPPED [1] studio/tests/test_knowledge.py:607: the prompt fixtures are not on this machine
143 passed, 2 skipped
```

A skipped test is not a passed test, and here the skip is load-bearing: it is
the only signal that the system under test is empty, and it is printed in grey
next to 143 green dots.

**Fixed.** `_resolve_dir` now takes an environment override
(`STUDIO_KNOWLEDGE_OUR_PROMPTS`, `STUDIO_KNOWLEDGE_REFERENCE_CARDS`), then a
directory inside this repository, then the original absolute path last so the
machine that has the data keeps working. When nothing exists the reported path
is the in-repo one, because an error should name a path the reader can create.

**And the second half, which mattered more:** `build_index` reported `pass` for
an index of 12 core rules and 0 examples. It now reports `could not measure`,
because such an index cannot answer a single retrieval query.
`test_core_rules_alone_build_and_pass` — the test that asserted the old
behaviour, and so the reason this survived a session — is renamed to
`test_core_rules_alone_are_not_a_built_index` and inverted, with
`test_one_example_is_enough_to_make_it_a_built_index` as the other direction.

The two tests that skip still skip: they need fixtures that are not in this
repository. A skip is honest there. What changed is that the build report now
says so out loud instead of saying `pass`.

---

## FIXED — would have broken in production

### The sqlite connection was not thread-safe, and FastAPI uses it from threads

`studio/knowledge.py:801` opens the index with sqlite3's default
`check_same_thread=True`, and `default_index()` caches that one connection in a
module global with no lock:

```python
conn = sqlite3.connect(str(db_path))
...
_DEFAULT_INDEX: KnowledgeIndex | None = None
```

Every route in `studio/app.py` is a plain `def`, which FastAPI runs in a
threadpool worker. The first route that calls `retrieve()` from a worker thread
raises `sqlite3.ProgrammingError`. It has never fired because nothing in
`app.py` calls `knowledge` yet — `grep -n "knowledge" studio/app.py` returns
nothing — so this is latent, not live. It becomes live on the commit that wires
retrieval into the web layer, which is the commit where nobody will be looking
for it.

**Fixed**, and the failure was reproduced first rather than assumed. Reverting
the flag in the test helper produces exactly the predicted error:

```
FAILED test_knowledge.py::Building::test_retrieve_is_safe_from_several_threads
threaded retrieval raised [ProgrammingError('SQLite objects created in a thread
can only be used in that same thread. ...')]
```

The connection is now opened `check_same_thread=False`, and every statement on
it — `add`, `reload`, `attach_dense`, `load_dense_from_db`, `counts`, and the
BM25 read on the query path — runs under `KnowledgeIndex.lock`.
`test_the_thread_guard_would_notice_the_old_connection` is the negative control
on that guard.

### OPEN — `default_index()` never invalidates

The cached index is rebuilt only when someone passes `rebuild=True`. Drop a new
`gallery_prompts.jsonl` into place and a long-running server serves the old
index until it restarts. There is no fingerprint, no mtime check, nothing.

**Fix:** the pattern in `studio/selfrag/cache.py` — hash what shaped the answer
(corpus contents, registry, rule table) and key on it, so a change expires
entries with no manual invalidation step.

### FIXED — `retrieve` counted below-floor candidates as "violations"

```python
ordered = sorted((i for i in fused if i in admitted), ...)
rejected = len(fused) - len(ordered)
...
return _result(outcome, note, checked=len(candidates), violations=rejected, ...)
```

A record that scored but did not clear the floor is the floor working, not a
violation. Feeding it into the same field as a real breach makes the
`violations` count unreadable across the codebase, which is a shame given how
carefully the three outcomes are handled everywhere else.

**Fixed:** `violations` is 0 and the count moved to a new `below_floor` key.

---

## Bottlenecks, honestly sized

Three of the four channels scan the whole corpus per query: `_channel_bm25`
issues one FTS5 query **per term** and fetches every matching row;
`_channel_structural` and `_channel_dense` iterate all entries. At 822 entries
this is microseconds and completely fine — the module's own docstring says so
and is right. It stops being fine somewhere around 10^5 entries. This is worth
knowing, not worth fixing now; the research is unambiguous that at 10^3–10^4
records a brute-force scan beats any ANN index, and adding a vector service
here would cost a second place for the truth to live and buy a speedup below
perception.

---

## What is missing, measured against the stated goal

The stated goal is a Self-RAG agent that writes prompts for Flux, Kling, Veo
and the rest. Against that goal:

1. **The RAG is built and unwired.** `studio/knowledge.py` implements retrieval
   and nothing calls it. `studio/style.py:extract` never sees a retrieved
   example. The corpus informs no prompt that ships.
2. **There is no reflection of any kind.** `extract` is single-shot: bad JSON
   returns `could not measure` and stops. No critique, no revision, no second
   look. This is the largest gap against the word "Self-RAG" in the request.
3. **`StyleSpec` cannot express a video prompt.** Five fields — palette, light,
   texture, mood, setting. Correct for the studio product, where naming the
   subject or the motion would be a bug. But Kling, Veo, Runway and Wan all ask
   for a subject, an action and a camera, and Veo asks for audio. **A StyleSpec
   cannot describe a camera move, so a StyleSpec cannot write a Veo prompt.**
4. **The `rating` field is never read back.** The corpus format records how well
   each prompt did and nothing in the ranking looks at it. The feedback loop is
   open.
5. **No cache, no journal, no report.** Every extraction pays for a model call,
   and there is no record of which prompts worked to look at afterwards.
6. **No model registry.** Nothing anywhere knows that Runway maxes at 10
   seconds, that Veo quantises to 4/6/8, or that Sora's API stops on
   2026-09-24. A prompt built against limits nobody checked fails at the
   vendor, after payment.

Items 1–6 are what `studio/selfrag/` adds. It adds them **beside** the existing
modules, importing them and editing neither, because they have other owners.

---

## OPEN — smaller notes, for their owners

- `studio/tests/` has no `__init__.py`, so `python -m unittest discover -s
  studio/tests -t .` fails with "Start directory is not importable". Only
  pytest can run that suite.
- `scripts/check` — the file that calls itself the single source of truth for
  all checks — runs lint, format, mypy and tests for `lipsync/` only. **No
  studio test runs in CI.** 143 tests are unexecuted on every push.
- Adding them is blocked by a missing pin: `studio/tests/test_app.py` needs
  `httpx2` (starlette's TestClient requires it) and `requirements-dev.txt` does
  not list it. Installing the pinned dev requirements and running the studio
  suite fails at collection.
- `mypy` resolves `studio.knowledge` to the data directory `studio/knowledge/`
  rather than to `studio/knowledge.py`. At runtime the module wins and a
  regression test holds that, but every typed import from it needs an ignore.
  `studio/selfrag/retrieval.py` carries one with a `DEBT` marker.

## Summary

The foundations are better than most: the security boundary is right, the three
outcomes are real, the retriever can abstain, and somebody has already been
mutating the fusion and writing down what happened. The system's problem is not
its design. Its problem was that **on any machine but one it was empty, and it said so only
in a skipped test**, and that the retrieval it does have is connected to
nothing that ships.

The first half is fixed. The second is what `studio/selfrag/` exists to
address — and it does so beside these modules, not inside them.
