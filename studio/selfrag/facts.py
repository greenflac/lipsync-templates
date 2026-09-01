"""What is known about each model, who said it, when, and where they disagree.

`registry.py` holds ONE answer per attribute, because the assembler needs one
number to build a prompt against. This module holds ALL the answers anybody has
given, and that difference is the point.

The failure this exists to prevent is specific and was measured. Asked how long
a single Kling 3.0 generation can be, the available sources say 15 seconds, and
10 seconds, and "3 minutes" (which turns out to mean several renders joined by
an Extend feature, not one generation). A third-party summary of those same
sources confidently reported "up to 5 minutes in a single generation", which
matches none of them. That is what happens when a pile of secondary sources is
flattened into one confident sentence: the flattening invents an answer nobody
gave.

So contradiction is a FIRST-CLASS OUTCOME here. `claims()` returns `fail` when
sources disagree, and it returns every side with its URL, its tier and its
date. It never votes, never averages, and never picks the newest. A caller that
wants one number goes to `registry.py` and gets the conservative one; a caller
that wants the truth gets told that the truth is contested.

TIERS, and why a blog can never promote a fact:

    vendor     the model vendor's own page: documentation, release, or repo
    probe      the vendor's own API, asked and refused: the running system
               rather than a document about it. Below `vendor` because one
               probe sees one account at one moment, and a limit it reports
               may belong to a billing plan rather than to the model.
    operator   the OWNER RAN IT AND SAW WHAT CAME OUT. First-hand, about the
               exact model and the exact workflow, today — and recorded by a
               person rather than by a machine, which is the whole difference
               from `probe`. Added 2026-08-31 on the owner's decision, and it
               is not a courtesy rung: the sharpest correction of that week
               ("nano-banana is fed pre-rendered Pillow text, which is why the
               text holds") came from the owner and had nowhere to live, so it
               survived only in a chat that was about to end.
    paper      arXiv or a venue, with a method somebody can check
    benchmark  an independent leaderboard or evaluation with a method
    portal     a platform that RUNS the model or hosts what people made with
               it — what its own API accepts, or the prompts and results
               themselves. A statement about a running system, so above a
               blog; below the vendor, because a platform exposes its own
               configuration and its ceiling may be its plan.
    blog       everything else, including the well-written aggregators

The vendor, portal and blog rungs are decided by WHOSE PAGE IT IS, from the
table in `source_hosts.py`, not by how the page reads. `probe`, `paper`,
`benchmark` and `operator` are decided by HOW THE FACT WAS OBTAINED, which no
URL can tell you — those are declared by whoever records the fact.

WHY `operator` SITS WHERE IT SITS, AND WHAT IT HAD TO EARN

Directly below `probe`, and the argument is symmetry: both are ONE first-hand
observation of the running system, with the same confound — one account, one
region, one moment, one workflow. A probe is written down by the API; an
operator report is written down by a person, and a person remembers a
conclusion more easily than what they actually saw.

So this rung costs something the others do not: an `operator` fact MUST carry
`witnessed` — what was run and what came out, in observable terms. Without it
the record is refused, not merely weighted down. "Nano-banana keeps text" is an
opinion; "fed nano-banana-edit a frame with Pillow-rendered text, the text
survived unchanged" is a fact somebody else can go and contradict.

It has no URL and needs none — there is no page. `source_url` carries the
operator's own reference (a chat date, a job id, a file) and `read_directly`
is True by construction: they were there.

A fact carried only by `blog` sources stays weak however many blogs repeat it,
because ten blogs quoting each other is one source. This is not snobbery about
writing quality: it is that a blog states a number without stating how it was
obtained, so a reader cannot tell a measurement from a guess.

BEING THE VENDOR'S PAGE AND HAVING BEEN READ ARE DIFFERENT QUESTIONS

Most vendor hosts are refused by this environment's egress policy, so a fact
citing `kling.ai` may be known only through somebody else's summary of it.
The tier says whose page it is; `read_directly` says whether anyone opened it.
Three states, because "nobody recorded it" is not "nobody read it":

    True   somebody opened the page or the API answered us
    False  it was not opened — the host is refused, or the note says summary
    None   not recorded

Collapsing None into False would invent evidence; collapsing it into True
would launder a summary into a reading. Neither is allowed.

THE FILE IS A LOG, AND THE LATEST ROW ABOUT A CLAIM WINS

Reading a page you already cite is not a second source saying the same thing.
Until 2026-08-27 it was: `record` appends, nothing collapsed, and re-recording
`kling-3.0.max_seconds = 15` after finally opening the Kuaishou release would
have made `claims()` report two sources where one page exists — with
`checked` inflated and the note reading "1 of 2 source(s) were NOT read"
about a single page that HAD been read. The upgrade in evidence would have
printed as corroboration.

So a claim is identified by `(model, attribute, value, source_url)` and the
LAST row carrying that key is the one that counts. An appended row supersedes
its predecessor's tier, date, note and reading flag, and the file keeps the
history of how the claim was argued — the same shape `denied_hosts.jsonl`
uses for refusals.

The key includes the VALUE deliberately. One page can state two values for one
attribute and that is not always a mistake to collapse: MEASURED in this file,
`seedance2-video.com/seedance-2-0-specs` gives `12` in its headline and `4 to
15` from the technical report it cites, on the same page. Keying without the
value would silently drop one of them and hide a source contradicting itself.

A row with `"withdrawn": true` REMOVES the claim instead of restating it. That
is for a page which, once opened, does not say what a summary of it said —
MEASURED the same day: `wavespeed.ai/` was cited for what Veo 3.1 is best for
and the page does not contain the word "Veo". Deleting the line would lose why
anybody believed it, so the withdrawal is appended and carries its reason.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

__all__ = [
    "DEFAULT_FACTS_PATH",
    "BREAKAGE_ATTRIBUTES",
    "CLASS_SUFFIX",
    "MULTI_VALUED",
    "STALE_AFTER_DAYS",
    "TIERS",
    "TIER_BLOG",
    "TIER_OPERATOR",
    "TIER_BENCHMARK",
    "TIER_PORTAL",
    "TIER_PAPER",
    "TIER_PROBE",
    "TIER_VENDOR",
    "UNKNOWN_TIER_RANK",
    "Fact",
    "claim_key",
    "FactStore",
    "claims",
    "load_facts",
]

TIER_VENDOR = "vendor"
TIER_PROBE = "probe"
TIER_BENCHMARK = "benchmark"
TIER_PORTAL = "portal"
TIER_BLOG = "blog"
TIER_PAPER = "paper"
TIER_OPERATOR = "operator"

#: Strongest first. Order is the only ranking; there are deliberately no
#: numeric weights, because a weight invites averaging and averaging a vendor
#: doc with three blogs produces a number nobody published.
#:
#: `probe` is a fact obtained by asking the vendor's own API and reading its
#: refusal — the running system rather than a document about it. It sits below
#: `vendor` and above everything else, and the reason it is not first is a real
#: confound: a probe observes ONE account, ONE region and ONE moment, so a
#: limit it reports may belong to a billing plan rather than to the model. A
#: vendor's general statement outranks a single observation of a special case;
#: everything written from the outside does not.
#:
#: `portal` was inserted directly above `blog` on 2026-08-27, on the owner's
#: ladder: vendor page, then specialised platforms, then everything else. It
#: goes above `blog` because a platform documents an endpoint that answers, and
#: below `benchmark` because it documents its OWN endpoint and has no published
#: method. Nothing else moved.
TIERS: tuple[str, ...] = (
    TIER_VENDOR,
    TIER_PROBE,
    TIER_OPERATOR,
    TIER_PAPER,
    TIER_BENCHMARK,
    TIER_PORTAL,
    TIER_BLOG,
)

#: Ranked below every named tier. A tier nobody declared cannot corroborate
#: anything, and until 2026-08-27 it silently did: an unrecognised tier sorted
#: to position 99 — worse than `blog` — but the "is this only blogs" check
#: compared against `blog` by NAME, so a typo'd tier sailed past it and the
#: claim was reported as `pass`. Ranking and judging must agree, so the check
#: now asks whether the best tier is blog OR unknown.
UNKNOWN_TIER_RANK = 99

#: Past this, a fact is reported as stale rather than current. CHOSEN: the
#: video field re-versioned roughly every two months through 2026.
#: Сколько символов должно совпасть, чтобы имена считались соседними. ВЫБРАНО:
#: три символа дают шум (`gen` цепляет всё подряд), шесть теряют короткие
#: имена вроде `h3-max`. Сторожится мутацией в обе стороны (правило Т1).
NEAR_MIN_SHARED = 4

STALE_AFTER_DAYS = 90

#: Attributes where several different values are a LIST, not a disagreement.
#: A model has many failure modes; it has one maximum duration. Treating the
#: two the same made every failure-mode entry read as a contradiction between
#: sources (OBSERVED 2026-08-26: 7 "contested" attributes, 4 of them merely
#: lists). The distinction is about the attribute, not about the sources.
#: The attribute names that all answer "where does this stop working". Kept as
#: a named tuple rather than spelled out inside `failure_modes`, so a fourth
#: word somebody starts harvesting is added in one visible place.
#: A model id ending in this is a SCOPE, not a model: `*` is the whole field
#: and `elevenlabs-*` is one vendor's line. Kept as a constant because two
#: places have to agree on it — the recorder that writes such a row and
#: `class_claims`, which is the only thing that can find one again.
CLASS_SUFFIX = "*"

BREAKAGE_ATTRIBUTES: tuple[str, ...] = ("failure_mode", "limitation", "degrades_when")

MULTI_VALUED: frozenset[str] = frozenset(
    {
        # Added 2026-09-01 with the body-reading harvest, and MEASURED before
        # and after: the base went from 7 contested pairs to 93, and 30 of the
        # new ones were `observed_behaviour`. Not one is a disagreement. Two
        # practitioners describing two different runs — one on a 3060 at
        # 960x544, one on a 3090 at 720p — are not contradicting each other;
        # they are two observations, which is the whole point of collecting
        # them. Flattening them to a contradiction would bury the pairs that
        # are real, and three of those are `max_seconds`.
        "observed_behaviour",
        # Same pass, 1 pair, and it is the same shape: three practitioners
        # reported LTX-2.5 running — on a 3060 12GB, on a 3090 with 128GB RAM,
        # and on the distilled ComfyUI workflow. "It runs on X" and "it runs on
        # Y" are both true; a model runs on many rigs.
        "runs_on",
        # Same pass, 7 pairs. A licence carries several restrictions at once:
        # a non-commercial clause and a territorial exclusion coexist in one
        # document, and MiniMax H3 alone lists four.
        "license_restriction",
        "failure_mode",
        # Added 2026-08-27 with the applicability harvest, and MEASURED before
        # and after: the base reported 38 contested (model, attribute) pairs,
        # 15 of them `limitation` and 9 `degrades_when`. None of the 24 was a
        # disagreement. A model card that says both "faces may not be generated
        # properly" and "no text control" is listing two limitations, exactly
        # as a model lists two failure modes. Reporting them as a contradiction
        # buries the 14 that are real — and three of those are `max_seconds`,
        # which is the kind nobody may flatten.
        "limitation",
        "degrades_when",
        # Added 2026-08-27 in the same pass, and this is a CORRECTION of a
        # judgement made an hour earlier in this same file. Both were kept out
        # on the argument that "holds a face for six seconds" against "loses
        # it at three" is a real disagreement. Then 155 verified rows landed
        # and the data settled it: every one of the six contested
        # `holds_identity` pairs is a list — hunyuanvideo carries two VBench-2.0
        # readings that agree to the decimal, sora-2 two paraphrases of one
        # finding — and every `benchmark_score` pair names a DIFFERENT
        # benchmark. A model has one maximum duration and many scores.
        #
        # The argument was not wrong in principle; it was made about data
        # nobody had looked at yet.
        "holds_identity",
        "benchmark_score",
        "metric_blind_spot",
        "best_for",
        "artifact_taxonomy",
        "override_parameter",
        "long_video_method",
        # Three findings that read as a contradiction and are not one. Longer
        # prompts helped when the USER wrote the extra words (+24% length, half
        # the measured gain); machine rewriting HURT (-58% of the gain); and
        # length alone barely correlates with quality (r about -0.07). The
        # reconciliation is in who adds the words, not in which source is
        # wrong, so these belong in a list rather than in a dispute.
        "expander_evidence",
        "retrieval_grounding",
        "expands_internally",
    }
)

DEFAULT_FACTS_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "model_facts.jsonl"


@dataclass(frozen=True)
class Fact:
    """One claim about one model, with who made it and when."""

    model: str
    attribute: str
    value: str
    source_url: str
    tier: str
    stated_on: str = ""
    note: str = ""
    fix: str = ""

    #: Did anybody open this page? See the module docstring: three states, and
    #: None means nobody recorded it rather than nobody read it.
    read_directly: bool | None = None

    #: Обязательно для тира `operator` и бессмысленно для остальных: ЧТО именно
    #: оператор запустил и что увидел, в наблюдаемых словах. Вывод без этого —
    #: мнение с ярлыком, а ярлык нужен ровно затем, чтобы такие записи можно
    #: было отличать друг от друга.
    witnessed: str = ""

    @property
    def age_days(self) -> int | None:
        """Days since the source stated it; None when the source gave no date."""
        if not self.stated_on:
            return None
        try:
            return (date.today() - date.fromisoformat(self.stated_on)).days
        except ValueError:
            return None


def claim_key(model: str, attribute: str, value: str, source_url: str) -> tuple[str, str, str, str]:
    """What identifies one claim, so a later row about it supersedes an earlier.

    Model and attribute are matched case-insensitively because that is how
    every lookup in this module matches them. Value and URL are matched as
    written: a page that states two values states two claims, and two URLs are
    two pages even when one redirects to the other.
    """
    return (model.strip().lower(), attribute.strip().lower(), value.strip(), source_url.strip())


def load_facts(path: Path = DEFAULT_FACTS_PATH) -> list[Fact]:
    """Read the fact file, latest row per claim winning. See the module docstring.

    A missing file returns nothing, and says nothing. A row with
    `"withdrawn": true` removes the claim it names rather than restating it,
    and a withdrawal of something never recorded is simply nothing — it is not
    an error here, because this function reports no outcomes; `advice.withdraw`
    is where a caller finds out.
    """
    if not path.is_file():
        return []
    # Insertion-ordered: a claim keeps the position of its FIRST appearance
    # while carrying the content of its LAST, so re-reading a page does not
    # shuffle the file's reading order.
    latest: dict[tuple[str, str, str, str], Fact | None] = {}
    for fact, withdrawn in _rows(path):
        key = claim_key(fact.model, fact.attribute, fact.value, fact.source_url)
        latest[key] = None if withdrawn else fact
    return [fact for fact in latest.values() if fact is not None]


def _rows(path: Path) -> list[tuple[Fact, bool]]:
    """Every row in the file, in file order, with whether it is a withdrawal."""
    facts: list[tuple[Fact, bool]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not row.get("model") or not row.get("attribute"):
            continue
        facts.append(
            (
                Fact(
                    model=str(row["model"]),
                    attribute=str(row["attribute"]),
                    value=str(row.get("value", "")),
                    source_url=str(row.get("source_url", "")),
                    tier=str(row.get("tier", TIER_BLOG)),
                    stated_on=str(row.get("stated_on", "")),
                    note=str(row.get("note", "")),
                    fix=str(row.get("fix", "")),
                    # Absent stays None. A row written before the field existed
                    # recorded nothing about reading, and that is what it says.
                    read_directly=(
                        None if row.get("read_directly") is None else bool(row["read_directly"])
                    ),
                    witnessed=str(row.get("witnessed", "")),
                ),
                bool(row.get("withdrawn")),
            )
        )
    return facts


class FactStore:
    """Every claim anybody has made, indexed by (model, attribute)."""

    def __init__(self, facts: Sequence[Fact] | None = None) -> None:
        self.facts: list[Fact] = list(facts) if facts is not None else load_facts()
        self._index: dict[tuple[str, str], list[Fact]] = defaultdict(list)
        for fact in self.facts:
            self._index[(fact.model.lower(), fact.attribute.lower())].append(fact)

    def attributes(self, model: str) -> list[str]:
        """Every attribute anybody has stated for this model."""
        low = model.lower()
        return sorted({a for (m, a) in self._index if m == low})

    def models(self) -> list[str]:
        """Every model anybody has stated anything about."""
        return sorted({m for (m, _) in self._index})

    def claims(self, model: str, attribute: str) -> dict:
        """Everything said about one attribute. Three outcomes, and no voting.

        * `pass` — every source that spoke agrees, and at least one is above
          blog tier.
        * `fail` — the sources contradict each other. Both sides are returned.
          This is not an error in this module; it is the state of the world,
          and hiding it is how an agent becomes confidently wrong.
        * `could not measure` — nobody has said anything, or everything said
          comes from blog tier alone, which cannot establish a fact.
        """
        found = self._index.get((model.lower(), attribute.lower()), [])
        if not found:
            return {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "note": f"nothing recorded about {model}.{attribute}",
                "claims": [],
                "values": [],
            }

        by_value: dict[str, list[Fact]] = defaultdict(list)
        for fact in found:
            by_value[fact.value].append(fact)
        rows = [
            {
                "value": value,
                "sources": [
                    {
                        "url": f.source_url,
                        "tier": f.tier,
                        "stated_on": f.stated_on,
                        "age_days": f.age_days,
                        "note": f.note,
                        # None means nobody recorded it, and prints as such.
                        "read_directly": f.read_directly,
                        "witnessed": f.witnessed,
                    }
                    for f in sorted(
                        facts,
                        key=lambda f: TIERS.index(f.tier) if f.tier in TIERS else UNKNOWN_TIER_RANK,
                    )
                ],
                "best_tier": min(
                    (f.tier for f in facts),
                    key=lambda t: TIERS.index(t) if t in TIERS else UNKNOWN_TIER_RANK,
                ),
            }
            for value, facts in sorted(by_value.items())
        ]

        stale = [f for f in found if (f.age_days or 0) > STALE_AFTER_DAYS]
        multi = attribute.lower() in MULTI_VALUED
        if len(by_value) > 1 and not multi:
            summary = "; ".join(f"{r['value']!r} ({r['best_tier']})" for r in rows)
            return {
                "outcome": FAIL,
                "checked": len(found),
                "violations": len(by_value),
                "unmeasured": 0,
                "note": (
                    f"sources disagree on {model}.{attribute}: {summary}. "
                    "Reported as contested rather than resolved: picking one would "
                    "invent a confidence nobody published."
                ),
                "claims": rows,
                "values": sorted(by_value),
            }

        best = min(
            (r["best_tier"] for r in rows),
            key=lambda t: TIERS.index(t) if t in TIERS else UNKNOWN_TIER_RANK,
        )
        if best == TIER_BLOG or best not in TIERS:
            return {
                "outcome": UNMEASURED,
                "checked": len(found),
                "violations": 0,
                "unmeasured": len(found),
                "note": (
                    f"{model}.{attribute}: {len(rows)} value(s) recorded, but every "
                    f"source is blog tier ({len(found)} of them). Repetition is not "
                    "corroboration: blogs quoting each other are one source."
                ),
                "claims": rows,
                "values": sorted(by_value),
            }
        shape = f"{len(rows)} value(s)" if multi else f"{rows[0]['value']!r}"
        note = f"{model}.{attribute}: {shape}, from {len(found)} source(s), best tier {best}"
        if stale:
            note += f"; {len(stale)} source(s) older than {STALE_AFTER_DAYS} days"
        # Counted and printed, never folded into the verdict: the ladder says
        # whose page it is and the owner set that ladder. But a `vendor` line
        # with nobody behind it reads as "the vendor says so", and 10 of the
        # 47 facts here cite a vendor page this environment cannot open. The
        # count goes out so a caller can gate on it; the policy is not
        # invented here.
        unread = [f for f in found if f.read_directly is False]
        unrecorded = [f for f in found if f.read_directly is None]
        if unread:
            note += (
                f"; {len(unread)} of {len(found)} source(s) were NOT read — known "
                "through somebody else's summary, not the page itself"
            )
        if unrecorded:
            note += f"; {len(unrecorded)} source(s) have no reading recorded either way"
        return {
            "outcome": PASS,
            "checked": len(found),
            "violations": 0,
            "unmeasured": len(stale),
            "note": note,
            "sources_not_read": len(unread),
            "sources_reading_unrecorded": len(unrecorded),
            "claims": rows,
            "values": sorted(by_value),
        }

    def failure_modes(self, model: str) -> list[Fact]:
        """Known ways this model breaks, each with its fix and its source.

        THREE ATTRIBUTE NAMES, ONE QUESTION. A caller asking what breaks does
        not care whether the harvester wrote `failure_mode`, `limitation` or
        `degrades_when` — those are three words for "here is where it stops
        working", and which one a page earns depends on how its vendor phrased
        the sentence. MEASURED 2026-08-27: reading only `failure_mode` hid 89
        `limitation` and 41 `degrades_when` rows from every caller, on the day
        a harvest put them there.

        `metric_blind_spot` is deliberately NOT here. It says a MEASUREMENT
        cannot see something — "subject consistency is maximised by a static
        video" is a fact about the benchmark, not about a model breaking, and
        folding it in would answer a question nobody asked.
        """
        low = model.lower()
        return [
            f
            for (m, a), facts in self._index.items()
            if m == low and a in BREAKAGE_ATTRIBUTES
            for f in facts
        ]

    def model_count(self) -> int:
        """How many model ids the base holds. Not the registry's seven."""
        return len({model for model, _attribute in self._index})

    def near(self, model: str, *, limit: int = 8) -> list[str]:
        """Ids in the base close to this one: общее начало, затем вхождение.

        For the caller who asked about `omnihuman-1.5` and was handed the
        registry's list of seven — the base may well hold the model under a
        neighbouring id, and pointing at it costs one line.

        ВХОЖДЕНИЕ ДОБАВЛЕНО 2026-08-31, и вот на чём это поймано. Владелец
        спросил про «H3 max» — так модель называет вендор. В базе она лежит
        под `minimax-h3-max`, с именем вендора впереди. Общего НАЧАЛА у этих
        строк нет вовсе («h» против «m»), поэтому подсказка возвращала пустоту,
        и ответ читался как «о такой модели ничего не известно» — при
        четырнадцати записанных о ней фактах. Спрашивают продуктовым именем, а
        хранится оно вендорским, и одно правило по префиксу этого не ловит
        никогда.

        Порядок сохранён: сначала совпадения по началу, они точнее; вхождения
        после. Иначе короткое общее имя вытеснило бы точного соседа.
        """
        low = str(model or "").strip().lower()
        if len(low) < NEAR_MIN_SHARED:
            return []
        every = sorted({m for m, _a in self._index})
        hits: list[tuple[int, int, str]] = []
        for candidate in every:
            if candidate == low:
                continue
            shared = 0
            for a, b in zip(low, candidate):
                if a != b:
                    break
                shared += 1
            if shared >= NEAR_MIN_SHARED:
                hits.append((0, -shared, candidate))
            elif low in candidate or candidate in low:
                hits.append((1, -len(low), candidate))
        return [c for _rank, _s, c in sorted(hits)][:limit]

    def class_claims(self, model: str) -> list[Fact]:
        """Facts recorded about the CLASS this model belongs to.

        WHY THESE EXIST AND WHY THEY WERE INVISIBLE

        Some findings are not about one model. "FVD barely moves under large
        temporal corruption" is about the metric; "logos smear when each shot
        is an independent request" is about the technique. They were recorded
        with `*` as the model, which is the honest scope — and it meant no
        query ever returned them, because every query starts with a model
        name. MEASURED 2026-08-27: 26 such rows sat in the base, reachable by
        nobody.

        Two scopes are understood, and the narrower one is not a decoration:

        * `*`             — true of the field. Returned for every model.
        * `<family>-*`    — true of one vendor's line, e.g. `elevenlabs-*`.
          Returned only for models in that family, because "a voice clone
          never reproduces the source acoustics" is a claim about ElevenLabs'
          cloning and saying it about Veo would be a different kind of wrong.

        A class fact is never merged into the per-model answer and never votes
        in a contradiction. It comes back in its own list, so a reader can see
        that it was said about the class rather than measured on this model.
        """
        low = str(model or "").strip().lower()
        out: list[Fact] = []
        for (recorded, _attribute), facts in self._index.items():
            if not recorded.endswith(CLASS_SUFFIX):
                continue
            family = recorded[: -len(CLASS_SUFFIX)].rstrip("-_.")
            if family and not (
                low == family or any(low.startswith(family + sep) for sep in ("-", "_", "."))
            ):
                continue
            out.extend(facts)
        return out

    def contested(self) -> list[tuple[str, str]]:
        """Every (model, attribute) the sources do not agree on."""
        out: list[tuple[str, str]] = []
        for model, attribute in sorted(self._index):
            if self.claims(model, attribute)["outcome"] == FAIL:
                out.append((model, attribute))
        return out

    def audit(self) -> dict:
        """How trustworthy the whole fact base is. Three outcomes.

        A fact base built entirely from blogs reports `could not measure`,
        however large it is. Volume is not evidence.
        """
        if not self.facts:
            return {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "note": "the fact base is empty: the agent knows nothing it can cite",
            }
        tiers: dict[str, int] = defaultdict(int)
        for fact in self.facts:
            tiers[fact.tier] += 1
        contested = self.contested()
        above_blog = sum(n for t, n in tiers.items() if t != TIER_BLOG)
        note = (
            f"{len(self.facts)} facts over {len(self.models())} models; "
            f"by tier {dict(sorted(tiers.items()))}; {len(contested)} contested"
        )
        if above_blog == 0:
            return {
                "outcome": UNMEASURED,
                "checked": len(self.facts),
                "violations": len(contested),
                "unmeasured": len(self.facts),
                "note": note + ". Every fact is blog tier: nothing here is established.",
            }
        return {
            "outcome": FAIL if contested else PASS,
            "checked": len(self.facts),
            "violations": len(contested),
            "unmeasured": tiers[TIER_BLOG],
            "note": note,
            "contested": [f"{m}.{a}" for m, a in contested],
        }


def claims(model: str, attribute: str, *, store: FactStore | None = None) -> dict:
    """Convenience wrapper over a process-wide store."""
    return (store or _default_store()).claims(model, attribute)


_STORE: FactStore | None = None


def _default_store() -> FactStore:
    global _STORE
    if _STORE is None:
        _STORE = FactStore()
    return _STORE
