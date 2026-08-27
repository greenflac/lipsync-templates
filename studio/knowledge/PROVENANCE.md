# Where every piece of the knowledge base comes from

Provenance is data, not documentation: every record carries its own origin
fields, so anyone who takes the file sees where it came from without reading
this page. This page explains the basis.

## Sources

| Source | Records | Origin | Basis |
|---|---|---|---|
| `core_rules.md` | — | written by us from the model vendor's published prompt guidance | ours |
| our prompts | 288 | our own generations, we paid for them | ours |
| style cards | 522 | derived measurements over a third party's public gallery: palette in our own vocabulary, wordless skeleton, digest, URL | derivative, no wording reproduced |
| judge verdicts | 528 | our own evaluations | ours |
| `gallery_prompts.jsonl` | 522 (expected) | prompt wording from the same third-party gallery | owner decision, see DEBT below |
| `civitai_prompts.jsonl` | grows per run | prompt, negative prompt, generation parameters and the resulting image URL, uploaded to Civitai by the person who ran the generation | owner authorisation 2026-08-27, see below |

## Format of `gallery_prompts.jsonl`

One JSON object per line. The two rights fields are mandatory on every row:
a file that travels without its origin is a file whose origin gets forgotten.

```json
{"id": "00094d24d42befc7",
 "prompt": "<the wording as published>",
 "source_url": "https://aidsgn.ru/<page>",
 "section": "<the gallery's own category label>",
 "harvested": "2026-08-25",
 "provenance": "third_party_gallery",
 "rights": "owner_decision_2026-08-25"}
```

`id` matches a card in the reference corpus, or is `null` when it did not
match. Match on `source.record` + `source.element`: that pair is the card's
identity, so matching is exact rather than heuristic.

Loading rules already enforced by `knowledge.py`:
- rows with `provenance: "third_party_gallery"` carry a lower weight than
  `core_rules.md`, which stays the source of truth;
- no more than 2 of any 5 retrieved examples may share one provenance, so a
  single source cannot fill the answer.

## DEBT(2026-08-25): third-party prompt wording in the knowledge base

The reference corpus was originally built to hold **no** wording from the
gallery. That was a deliberate decision, recorded in four places in the
`cyclerunner` repository — the collector's own module docstring, its README,
the project NOTICE, and a handoff entry that named and rejected the
alternative: *"Rejected: mirroring a paid library into a branch — both a
licence problem and the kind of thing a reviewer notices."*

Those objections were put to the owner verbatim, together with the facts that
the gallery is a third party's commercial catalogue and that paid access
grants use rather than redistribution. The owner reviewed them and confirmed
the decision to collect the wording (2026-08-25). It is the owner's
repository, the owner's paid access and the owner's commercial risk.

Consequences to keep in view:
- the NOTICE in `cyclerunner` states that no wording is reproduced; it stops
  being true the moment the file lands and must be corrected in the same
  commit (replacement text: `NOTICE_replacement.md`, next to this file);
- the rights-holder may ask for removal, and the origin fields above are what
  makes an exact removal possible;
- this entry exists so the departure stays greppable and does not quietly
  become the norm.


## `civitai_prompts.jsonl` — prompts paired with the results they produced

The thing this knowledge base has never had. Everywhere else the wording and
the image live apart: our own prompts have our own generations, and the gallery
rows have wording with no result attached. Civitai's uploaders post both.

### Basis

The owner obtained legal clearance and confirmed on 2026-08-27 that the licence
questions are resolved and there is no outstanding legal risk. Stamped on every
row as `rights: "owner_authorisation_2026-08-27"`.

What that authorisation is against, so a future reader can check it is still
the right basis rather than assuming: Civitai's ToS 6.1 grants access "solely
for your personal, non-commercial use", and 11.4 permits automated access
through the public API with your own credentials and within rate limits, "or as
we otherwise authorize in writing". Both were READ first-hand on 2026-08-27 and
are recorded in `model_facts.jsonl` under `civitai-api.licence`. Per-upload
model licences (Anima, LTX-derived, Cosmos-derived) carry their own commercial
restrictions on top and this collector does not read them — it collects images
and wording, not weights.

### Format

One JSON object per line. Six fields are mandatory and a row missing any of
them stops the whole write rather than being dropped quietly:

```json
{"prompt": "<the wording as the uploader wrote it>",
 "negative_prompt": "<or empty>",
 "image_url": "https://image.civitai.com/<...>",
 "width": 1096, "height": 1648, "nsfw_level": 1,
 "parameters": {"seed": 1, "steps": 28, "sampler": "...", "cfgScale": 7,
                "Size": "512x768", "Model": "...", "clipSkip": 2},
 "model_name": "DreamShaper", "base_model": "SD 1.5", "version_id": 128713,
 "source_url": "https://civitai.com/api/v1/model-versions/128713",
 "harvested": "2026-08-27",
 "provenance": "civitai:<uploader>",
 "rights": "owner_authorisation_2026-08-27"}
```

### The provenance is the uploader, not the platform

A decision worth stating because it interacts with a rule in `knowledge.py`.
`MAX_PER_PROVENANCE` admits at most 2 of any 5 retrieved examples from one
provenance, so that a single source cannot fill an answer. Tagging every row
`civitai` would make the whole corpus one source and cap it at two records —
which is the defect already recorded against the gallery rows, repeated.

One Civitai uploader is one author, so the provenance is
`civitai:<uploader>` and the platform stays recoverable from the prefix: a
removal request naming Civitai matches every row with one grep, and a request
naming one uploader matches exactly theirs.

MEASURED on the first real run of 170 pairs: 20 uploaders, the largest holding
19. That distribution is what the rule needs, and it exists only because the
walk visits models round-robin — an earlier depth-first walk collected 29 pairs
from **one** uploader before `summarise` said so.

### What is deliberately dropped, and counted

- images above `nsfw_level` 2 (Civitai's PG and PG-13 rungs are kept, R and
  above are not) — 27 of 210 on the first real run;
- images whose wording is under three words — 13 of 210;
- workflow-specific parameters (ADetailer, Hires) that belong to the
  uploader's tooling rather than to the prompt.

Every one of those is REPORTED in the run's note. "We collected 170" reads very
differently from "we collected 170 and threw 40 away", and only the second is
true.

### Not committed

`.gitignore` carries the file. This repository is public and its LICENCE clause
2(d) asserts rights over "the prompts ... contained here" — which, over this
file, would be a claim on other people's work. Collecting and using it is
covered; republishing it under this repository's licence is a separate decision
and not one `git add -A` should be able to take.
