# Where every piece of the knowledge base comes from

Provenance is data, not documentation: every record carries its own origin
fields, so anyone who takes the file sees where it came from without reading
this page. This page explains the basis.

RIGHTS: we hold the right to use the aidsgn.ru gallery cards as training and
retrieval material for the prompt writer — the owner holds paid access to that
gallery and confirmed the use on 2026-08-26. The right covers use, not
redistribution: what is stored here is our own derived measurement of each
card (see the style cards row below), and every record keeps the origin fields
that make an exact removal possible if the rights-holder asks for one.

## Sources

Two columns, because "in the corpus" and "we have it" are different facts.
`build_index()` reports the same split under `per_source` and `excluded`.

| Source | Records | In default corpus | Origin | Basis |
|---|---|---|---|---|
| `core_rules.md` | 12 | yes | written by us from the model vendor's published prompt guidance | ours |
| style cards | 522 | yes | derived measurements over a third party's public gallery: palette in our own vocabulary, wordless skeleton, digest, URL | derivative, no wording reproduced |
| our prompts | 288 | **no** — excluded 2026-08-26 | our own generations, we paid for them | ours |
| judge verdicts | 528 | no — never indexed | our own evaluations | ours |
| `gallery_prompts.jsonl` | 522 (expected) | yes, once harvested | prompt wording from the same third-party gallery | owner decision, see DEBT below |

Default corpus today: **534 entries** (12 + 522). The excluded rows are not
deleted and not lost; `build_index(our_prompts=...)` puts ours back for a
deliberate experiment, and the exclusion travels in the build report so it
cannot be mistaken for a source that broke.

## DECISION(2026-08-26): our own 288 prompts are not training material

They were written for several unrelated projects and tasks. Merged into one
index they teach the writer the average of jobs that share nothing, and the
retrieval quota cannot separate them because provenance, not subject, is what
it counts. The owner decided to take them out of the default corpus.

Measured consequence, recorded because it is a cost and not a footnote: on the
40-record gold set, recall@5 falls from 0.9737 (822 entries, with our prompts)
to 0.4474 (534 entries, without), and both positive controls stop passing. The
gold set was written against the larger corpus and most of its expected
phrases lived only in our prompts, so the number currently measures that
mismatch rather than the retriever. Numbers and channel breakdown are in the
measurement block in `knowledge.py`.

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
