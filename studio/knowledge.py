"""Retrieval of prompt-writing knowledge: core rules plus worked examples.

The build order is deliberate. `evaluate` and the gold set exist before the
index does, so that "the agent did not get the right example" can be told
apart from "the index never loaded" — a counter before a knob.

Storage is one sqlite file with FTS5. At ~1300 entries a full scan over the
vectors takes microseconds, so a separate vector service would buy nothing and
would cost a second place where the truth lives and a second write to keep in
sync.

Retrieval is a hybrid. BM25 carries the jargon — film stocks, light names,
lens words are rare tokens where lexical search beats a dense model. The
structural channel carries the allow-list fields the studio already speaks in
(`studio.style`). A dense channel carries paraphrase when its weights are
available. The three rankings are merged with reciprocal rank fusion.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.style import (
    LIGHT_WORDS,
    MOOD_WORDS,
    PALETTE_WORDS,
    TEXTURE_WORDS,
    StyleSpec,
)

__all__ = [
    "DEFAULT_K",
    "DEDUP_PREFIX",
    "DENSE_FLOOR",
    "FUSION_CHANNELS",
    "KIND_CORE",
    "KIND_GALLERY_PROMPT",
    "KIND_OUR_PROMPT",
    "KIND_STYLE_CARD",
    "MAX_PER_PROVENANCE",
    "PHRASE_MAX",
    "PROVENANCE_COMMUNITY_CIVITAI",
    "PROVENANCE_NAMESPACE",
    "PROVENANCE_WEIGHT",
    "provenance_family",
    "provenance_weight",
    "RECALL_FLOOR",
    "RRF_K",
    "KnowledgeIndex",
    "build_index",
    "dense_probe",
    "evaluate",
    "load_eval_set",
    "retrieve",
    "structure_from_text",
]


# ---------------------------------------------------------------- vocabulary

KIND_CORE = "core"
KIND_OUR_PROMPT = "our_prompt"
KIND_GALLERY_PROMPT = "gallery_prompt"
KIND_STYLE_CARD = "style_card"

KINDS: tuple[str, ...] = (
    KIND_CORE,
    KIND_OUR_PROMPT,
    KIND_GALLERY_PROMPT,
    KIND_STYLE_CARD,
)

# Where an entry came from. Retrieval quotas count these, not `kind`, because
# the poisoning risk is about who wrote the text, not what shape it has.
PROVENANCE_CORE = "core"
PROVENANCE_OURS = "ours"
PROVENANCE_REFERENCE_CARD = "reference_card"
PROVENANCE_GALLERY = "gallery"
# The harvester writes its own origin field on every row (see
# knowledge/PROVENANCE.md). We carry that value through rather than renaming
# it: the row's own statement of where it came from is the evidence, and a
# name we invent here would be a second, divergent story.
PROVENANCE_THIRD_PARTY = "third_party_gallery"
# A community platform is its OWN family, named after the platform, because
# `civitai:Lykon` and some future `openart:someone` are different populations
# with different norms and should be weighable apart. Rows arrive already
# namespaced from `studio/mcp/civitai.py`; adding another platform is one line
# here and one prefix there.
PROVENANCE_COMMUNITY_CIVITAI = "civitai"

# CHOSEN by us as starting values (not measured): core is the source of truth,
# our own shipped prompts outrank harvested style cards, and anything scraped
# from a public gallery is the least trusted thing in the index.
PROVENANCE_WEIGHT: dict[str, float] = {
    PROVENANCE_CORE: 1.0,
    PROVENANCE_OURS: 0.9,
    PROVENANCE_REFERENCE_CARD: 0.8,
    PROVENANCE_GALLERY: 0.6,
    PROVENANCE_THIRD_PARTY: 0.6,
    # CHOSEN, same rung as the gallery: it is third-party wording either way.
    # Arguably it deserves more — these are prompts posted WITH the image they
    # produced, by the person who ran them, which the gallery rows are not —
    # but "arguably" is not a measurement, so it starts level and moves when
    # something measures it.
    PROVENANCE_COMMUNITY_CIVITAI: 0.6,
}

#: A provenance may be NAMESPACED: `"<family>:<who>"`, where the family is a
#: key of `PROVENANCE_WEIGHT` and the part after the colon names the individual
#: author. `civitai:Lykon` and `civitai:Merjic` weigh the same and count as two
#: DIFFERENT sources against the per-answer quota.
#:
#: This exists because of a defect measured 2026-08-27. A community corpus was
#: collected with one provenance per uploader — 1409 rows across 106 people —
#: precisely so the quota would see many sources. The loader then collapsed
#: every unrecognised provenance to `PROVENANCE_GALLERY`, so all 106 became one
#: and the quota capped every answer at 2 again. The corpus had done the right
#: thing and the reader undid it.
#:
#: The family is what carries the WEIGHT, because how much a source is trusted
#: is a property of the kind of source, not of the person. The whole string is
#: what carries IDENTITY, because "no single source fills the answer" is a
#: statement about people, not about platforms.
PROVENANCE_NAMESPACE = ":"


def provenance_family(provenance: str) -> str:
    """The part of a provenance that decides how much it is trusted.

    `"civitai:Lykon"` -> `"civitai"`, `"ours"` -> `"ours"`. Splitting on the
    FIRST separator only, so an author whose name contains a colon still lands
    in the right family.
    """
    return str(provenance or "").split(PROVENANCE_NAMESPACE, 1)[0]


def _known_provenance(provenance: str) -> bool:
    """Is this a provenance the index recognises, plain or namespaced?"""
    text = str(provenance or "")
    return text in PROVENANCE_WEIGHT or provenance_family(text) in PROVENANCE_WEIGHT


def provenance_weight(provenance: str) -> float:
    """How much one provenance is trusted. A namespaced one inherits its family.

    The fallback stays 0.5 — below every declared weight, so a provenance
    nobody has classified cannot outrank one somebody has.
    """
    text = str(provenance or "")
    if text in PROVENANCE_WEIGHT:
        return PROVENANCE_WEIGHT[text]
    return PROVENANCE_WEIGHT.get(provenance_family(text), 0.5)


# The structural fields. Imported from studio.style, never re-declared: one
# word list, one place. A word that is not on these lists cannot be a field
# value, in the index or in a query.
STRUCTURAL_FIELDS: tuple[str, ...] = ("palette", "light", "texture", "mood")
FIELD_WORDS: dict[str, tuple[str, ...]] = {
    "palette": PALETTE_WORDS,
    "light": LIGHT_WORDS,
    "texture": TEXTURE_WORDS,
    "mood": MOOD_WORDS,
}

# How a user's word maps onto the allow-list. CHOSEN, and deliberately small:
# every pair here is a claim that two words mean the same look, and a wrong
# pair is invisible until it drags a bad example into the context.
SYNONYMS: dict[str, tuple[str, str]] = {
    # palette
    "beige": ("palette", "sand"),
    "black": ("palette", "charcoal"),
    "blue": ("palette", "indigo"),
    "bronze": ("palette", "copper"),
    "brown": ("palette", "copper"),
    "camel": ("palette", "sand"),
    "chocolate": ("palette", "copper"),
    "coral": ("palette", "rose"),
    "cream": ("palette", "ivory"),
    "graphite": ("palette", "charcoal"),
    "green": ("palette", "emerald"),
    "grey": ("palette", "slate"),
    "gray": ("palette", "slate"),
    "maroon": ("palette", "crimson"),
    "moss": ("palette", "emerald"),
    "navy": ("palette", "indigo"),
    "olive": ("palette", "emerald"),
    "orange": ("palette", "amber"),
    "pink": ("palette", "rose"),
    "red": ("palette", "crimson"),
    "rust": ("palette", "copper"),
    "sage": ("palette", "emerald"),
    "silver": ("palette", "slate"),
    "steel": ("palette", "slate"),
    "stone": ("palette", "sand"),
    "tan": ("palette", "sand"),
    "taupe": ("palette", "sand"),
    "terracotta": ("palette", "copper"),
    "turquoise": ("palette", "teal"),
    "white": ("palette", "ivory"),
    "yellow": ("palette", "gold"),
    # light
    "daylight": ("light", "soft"),
    "dawn": ("light", "golden-hour"),
    "diffused": ("light", "soft"),
    "dusk": ("light", "golden-hour"),
    "goldenhour": ("light", "golden-hour"),
    "sunrise": ("light", "golden-hour"),
    "sunset": ("light", "golden-hour"),
    "cloudy": ("light", "overcast"),
    "contrasty": ("light", "hard"),
    "harsh": ("light", "hard"),
    "nocturne": ("light", "low-key"),
    "airy": ("light", "high-key"),
    "bright": ("light", "high-key"),
    "moody": ("light", "low-key"),
    "candle": ("light", "candlelit"),
    "rimlight": ("light", "backlit"),
    # texture
    "flat": ("texture", "matte"),
    "grain": ("texture", "film-grain"),
    "grainy": ("texture", "film-grain"),
    "misty": ("texture", "hazy"),
    "paper": ("texture", "matte"),
    "shiny": ("texture", "glossy"),
    "sharp": ("texture", "crisp"),
    "smoke": ("texture", "smoky"),
    "watercolor": ("texture", "watercolour"),
    "chrome": ("texture", "metallic"),
    "painted": ("texture", "painterly"),
    # mood
    "cosy": ("mood", "calm"),
    "cozy": ("mood", "calm"),
    "moody-mood": ("mood", "melancholic"),
    "quiet": ("mood", "calm"),
    "romantic": ("mood", "dreamy"),
    "sad": ("mood", "melancholic"),
    "lively": ("mood", "energetic"),
    "upbeat": ("mood", "energetic"),
    "vintage": ("mood", "nostalgic"),
    "retro": ("mood", "nostalgic"),
    "luxurious": ("mood", "elegant"),
    "premium": ("mood", "elegant"),
    "peaceful": ("mood", "serene"),
    "intense": ("mood", "dramatic"),
}

# British and American spellings of the same word. The allow-lists in
# studio.style are British; the harvested corpora are mixed. Without this the
# lexical channel silently misses every "watercolour"/"watercolor" pair.
SPELLINGS: dict[str, str] = {
    "watercolour": "watercolor",
    "watercolor": "watercolour",
    "colour": "color",
    "color": "colour",
    "grey": "gray",
    "gray": "grey",
    "centre": "center",
    "center": "centre",
    "moustache": "mustache",
}


# Words too common in this corpus to be evidence of anything.
STOPWORDS: frozenset[str] = frozenset(
    """a an and are as at be by for from how i in into is it its like make me my
    of on or that the their them there they this to want with you your image
    photo picture shot look style want need please something make give""".split()
)


# ------------------------------------------------------------- tuning knobs

DEFAULT_K = 5

# RRF's smoothing constant. CHOSEN: 60 is the value the original fusion paper
# used and every hybrid-search implementation copies.
RRF_K = 60

# Which rankings are fused. Naming the channels as data (rather than as three
# hard-wired calls) is what makes the fusion mutable in a test: drop this to
# ("bm25",) and recall must fall.
FUSION_CHANNELS: tuple[str, ...] = ("bm25", "phrase", "structural", "dense")

# Per-channel weight in the fusion. CHOSEN.
CHANNEL_WEIGHT: dict[str, float] = {
    "bm25": 1.0,
    "phrase": 1.2,
    "structural": 0.8,
    "dense": 0.7,
}

# Longest query n-gram the phrase channel looks for. The jargon of this trade
# is multi-word ("matte paper texture", "low key diffuse nocturne"), and a
# single-token BM25 cannot tell that document apart from one that merely says
# "paper" three times.
PHRASE_MAX = 3

# MEASURED on the 40-record gold set in knowledge/eval_set.jsonl, 822 entries,
# 2026-08-25, k=5:
#   bm25 + phrase + structural + dense  recall@5 0.9737  precision@5 0.7237  PASS
#   bm25 + phrase + structural          recall@5 0.8947  precision@5 0.6711  PASS
#   bm25 + phrase                       recall@5 0.8947  precision@5 0.7500  PASS
#   bm25 only                           recall@5 0.8289  precision@5 0.7039  FAIL
# Two readings to keep: the fusion is worth 0.14 recall over BM25 alone, and
# the structural channel currently buys no recall at all while costing 0.079
# precision. It is kept because it is the only channel that can rank a query
# carrying no corpus vocabulary at all, but that case does not occur in this
# gold set — so the claim is unproven, not proven.

# Admission floors. An entry only competes if some channel has real evidence
# for it; without a floor the index can never answer "nothing here", and a
# retriever that never says no is measuring nothing.
BM25_MIN_HITS = 2  # distinct query terms an entry must carry
STRUCTURAL_MIN_FIELDS = 1  # allow-list fields that must agree
DENSE_FLOOR = 0.35  # cosine; CHOSEN, then checked: both negative controls
# still come back empty with the dense channel on, and both positive controls
# still come back full. A floor of 0.0 fills the answer with noise (mutation
# test), a floor of 0.99 empties it.

# No more than this many examples from one provenance in one answer. Structural
# fuse against an answer filling up with a single kind of source.
MAX_PER_PROVENANCE = 2

# Near-duplicate suppression inside one answer. Our own prompt corpus is
# template-generated, so the top of a ranking is often the same paragraph
# twice; two identical demonstrations teach the writer nothing and cost a slot.
DEDUP_PREFIX = 120

# Recall@k below which `evaluate` calls the index not good enough. CHOSEN.
RECALL_FLOOR = 0.60

DEFAULT_DB_PATH = Path(__file__).with_name("knowledge") / "index.sqlite3"
CORE_RULES_PATH = Path(__file__).with_name("knowledge") / "core_rules.md"
EVAL_SET_PATH = Path(__file__).with_name("knowledge") / "eval_set.jsonl"
GALLERY_PROMPTS_PATH = Path(__file__).with_name("knowledge") / "gallery_prompts.jsonl"

#: The community corpus: prompts posted on Civitai together with the image they
#: produced, by the person who ran them. Same row shape as the gallery harvest,
#: so it goes through the same loader — one knowledge, one place.
#:
#: It is NOT committed. `LICENCE` clause 2(d) of that site would have this
#: repository claim rights over other people's prompts, so the file is
#: gitignored and rebuilt with `python scripts/collect_civitai.py`. A build on
#: a fresh clone therefore reports it absent, which is correct and is why a
#: missing source has always been reported rather than fatal.
COMMUNITY_PROMPTS_PATH = Path(__file__).with_name("knowledge") / "civitai_prompts.jsonl"

# Where the two example corpora live. These were absolute paths into one
# developer's home directory, and the consequence was measured on 2026-08-26:
# on a fresh clone the index built with 12 core entries and 0 examples, every
# `retrieve` answered "could not measure", `evaluate` could not run at all, and
# the two tests that would have caught it skipped. The recall numbers in
# HANDOFF_studio-mvp.md were not reproducible by anybody else.
#
# Resolution order, first existing directory wins:
#   1. $STUDIO_KNOWLEDGE_OUR_PROMPTS / $STUDIO_KNOWLEDGE_REFERENCE_CARDS
#   2. a directory inside this repository
#   3. the original absolute path, kept last so the machine that has the data
#      keeps working — but no longer the only way to have any data at all.
OUR_PROMPTS_ENV = "STUDIO_KNOWLEDGE_OUR_PROMPTS"
REFERENCE_CARDS_ENV = "STUDIO_KNOWLEDGE_REFERENCE_CARDS"

_LEGACY_ROOT = Path("/home/user/cyclerunner/demo/instories")


def _resolve_dir(env_name: str, in_repo: Path, legacy: Path) -> Path:
    """First existing candidate, or the in-repo path so the error names this repo.

    Returning the in-repo path when nothing exists matters: a caller that
    prints "sources absent" should name a path the reader can create, not one
    on a machine they have never seen.
    """
    override = os.environ.get(env_name, "").strip()
    candidates = [Path(override).expanduser()] if override else []
    candidates += [in_repo, legacy]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return in_repo


OUR_PROMPTS_DIR = _resolve_dir(
    OUR_PROMPTS_ENV,
    Path(__file__).with_name("knowledge") / "our_prompts",
    _LEGACY_ROOT / "fixtures" / "gen",
)
REFERENCE_CARDS_DIR = _resolve_dir(
    REFERENCE_CARDS_ENV,
    Path(__file__).with_name("knowledge") / "reference_cards",
    _LEGACY_ROOT / "references",
)

DENSE_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"  # apache-2.0, checked
DENSE_ENV_FLAG = "STUDIO_KNOWLEDGE_DENSE"


# -------------------------------------------------------------------- types


@dataclass(frozen=True)
class Entry:
    """One indexed piece of knowledge."""

    entry_id: int
    kind: str
    text: str
    palette: tuple[str, ...]
    light: str
    texture: str
    mood: str
    provenance: str
    weight: float
    source: str


def _result(
    outcome: str,
    note: str,
    *,
    checked: int = 0,
    violations: int = 0,
    unmeasured: int = 0,
    **extra: Any,
) -> dict:
    """Build the judging dict every module in the studio agrees on."""
    out: dict[str, Any] = {
        "outcome": outcome,
        "checked": checked,
        "violations": violations,
        "unmeasured": unmeasured,
        "note": note,
    }
    out.update(extra)
    return out


# ------------------------------------------------------------- text helpers


_WORD = re.compile(r"[a-z0-9][a-z0-9'-]*")


def _words(text: str) -> list[str]:
    """Split text into comparable lowercase tokens."""
    return _WORD.findall(text.lower())


def query_terms(text: str) -> list[str]:
    """Return the searchable terms of a free-text query, stopwords dropped."""
    seen: list[str] = []
    for word in _words(text):
        bare = word.strip("-'")
        if len(bare) < 3 or bare in STOPWORDS or bare in seen:
            continue
        seen.append(bare)
    return seen


def structure_from_text(text: str) -> dict[str, set[str]]:
    """Extract allow-list field values a piece of text commits to.

    An unmatched field comes back as an empty set and never counts as
    agreement — an unknown is not a match.

    >>> sorted(structure_from_text("warm amber light, grainy film")["palette"])
    ['amber']
    """
    found: dict[str, set[str]] = {field: set() for field in STRUCTURAL_FIELDS}
    lowered = text.lower()
    for field, words in FIELD_WORDS.items():
        for word in words:
            # Hyphenated allow-list words ("golden-hour") also occur spaced.
            if word in lowered or word.replace("-", " ") in lowered:
                found[field].add(word)
    for word in _words(text):
        mapped = SYNONYMS.get(word)
        if mapped is not None:
            found[mapped[0]].add(mapped[1])
    return found


def _structure_text(structure: Mapping[str, set[str]]) -> str:
    """Flatten structural fields into a string FTS5 can index."""
    parts: list[str] = []
    for field in STRUCTURAL_FIELDS:
        parts.extend(sorted(structure.get(field, ())))
    return " ".join(parts)


# ----------------------------------------------------------------- loaders


def load_core_rules(path: Path = CORE_RULES_PATH) -> list[dict]:
    """Read core_rules.md into one entry per `## ` section."""
    if not path.is_file():
        return []
    sections: list[dict] = []
    heading: str | None = None
    body: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            if heading is not None:
                sections.append(_core_entry(heading, body))
            heading = line[3:].strip()
            body = []
        elif heading is not None:
            body.append(line)
    if heading is not None:
        sections.append(_core_entry(heading, body))
    return sections


def _core_entry(heading: str, body: Sequence[str]) -> dict:
    text = (heading + ". " + " ".join(body)).strip()
    text = re.sub(r"\s+", " ", text)
    return {
        "kind": KIND_CORE,
        "text": text,
        "provenance": PROVENANCE_CORE,
        "source": "core_rules.md",
        "title": heading,
    }


def load_our_prompts(directory: Path = OUR_PROMPTS_DIR) -> list[dict]:
    """Read our own shipped generation prompts out of the fixture directory."""
    if not directory.is_dir():
        return []
    entries: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        prompt = (payload or {}).get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            continue
        entries.append(
            {
                "kind": KIND_OUR_PROMPT,
                "text": prompt.strip(),
                "provenance": PROVENANCE_OURS,
                "source": path.name,
            }
        )
    return entries


def load_style_cards(directory: Path = REFERENCE_CARDS_DIR) -> list[dict]:
    """Read the harvested style cards into prose entries.

    The card fields are already a controlled vocabulary; they are rendered as a
    sentence so that the same BM25 index serves them and the prose prompts.
    """
    if not directory.is_dir():
        return []
    entries: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        card = (payload or {}).get("card") or {}
        colours = [c for c in (card.get("colours") or []) if isinstance(c, str)]
        if not colours and not card.get("texture"):
            continue
        skeleton = (payload or {}).get("skeleton") or {}
        params = skeleton.get("params") or {}
        bits = [
            f"{', '.join(colours)} palette" if colours else "",
            f"{card.get('saturation')} saturation" if card.get("saturation") else "",
            str(card.get("texture") or ""),
            f"{card.get('value_key')} value key" if card.get("value_key") else "",
            f"aspect {params.get('ar')}" if params.get("ar") else "",
            f"{params.get('style')} style" if params.get("style") else "",
        ]
        entries.append(
            {
                "kind": KIND_STYLE_CARD,
                "text": ", ".join(bit for bit in bits if bit),
                "provenance": PROVENANCE_REFERENCE_CARD,
                "source": path.name,
                "card": card,
            }
        )
    return entries


def load_gallery_prompts(path: Path = GALLERY_PROMPTS_PATH) -> list[dict]:
    """Read harvested gallery prompts, if that file has been produced yet."""
    if not path.is_file():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        text = payload.get("prompt") or payload.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        declared = str(payload.get("provenance") or PROVENANCE_GALLERY)
        provenance = declared if _known_provenance(declared) else PROVENANCE_GALLERY
        rights = payload.get("rights")
        # `source_url` before the file name: a row whose source is only
        # "civitai_prompts.jsonl" cannot be gone and checked, and every row
        # in a 473-row file would carry the same one.
        source = str(payload.get("id") or payload.get("source_url") or path.name)
        entries.append(
            {
                "kind": KIND_GALLERY_PROMPT,
                "text": text.strip(),
                "provenance": provenance,
                # The rights marker travels with the row into every answer:
                # a file that moves without its origin is a file whose origin
                # gets forgotten.
                "source": f"{source} (rights={rights})" if rights else source,
            }
        )
    return entries


def load_eval_set(path: Path = EVAL_SET_PATH) -> list[dict]:
    """Read the gold set of queries from JSONL."""
    if not path.is_file():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        records.append(json.loads(line))
    return records


# --------------------------------------------------------------- the index


SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    palette TEXT NOT NULL,
    light TEXT NOT NULL,
    texture TEXT NOT NULL,
    mood TEXT NOT NULL,
    provenance TEXT NOT NULL,
    weight REAL NOT NULL,
    source TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(text, structured);
CREATE TABLE IF NOT EXISTS vectors (
    id INTEGER PRIMARY KEY,
    dim INTEGER NOT NULL,
    data BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def dense_probe(*, model_id: str = DENSE_MODEL_ID) -> dict:
    """Report whether the dense channel can run, with an error code if not.

    Never called unless dense embeddings were asked for: a test must not reach
    the network, and loading weights may.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # noqa: BLE001 - the code is the measurement
        return _result(
            UNMEASURED,
            f"sentence-transformers not importable: {type(exc).__name__}",
            unmeasured=1,
            error_code=type(exc).__name__,
            model=None,
        )
    try:
        model = SentenceTransformer(model_id)
    except Exception as exc:  # noqa: BLE001
        return _result(
            UNMEASURED,
            f"weights for {model_id} unavailable: {type(exc).__name__}: {exc}",
            unmeasured=1,
            error_code=type(exc).__name__,
            model=None,
        )
    return _result(
        PASS,
        f"dense channel ready on {model_id}",
        checked=1,
        model=model,
    )


class KnowledgeIndex:
    """A sqlite-backed hybrid index over the studio's prompt knowledge."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        # Guards every statement on `conn`. sqlite3 serialises access itself,
        # but a cursor's rows must be drained before the next statement runs on
        # the same connection, and two threads interleaving that is the bug.
        self.lock = threading.Lock()
        self.entries: list[Entry] = []
        self.by_id: dict[int, Entry] = {}
        self.dense_ids: list[int] = []
        self.dense_matrix: Any = None
        self.dense_model: Any = None
        self.dense_report: dict = _result(
            UNMEASURED, "dense channel not attempted", unmeasured=1, error_code="OFF"
        )
        self.build_report: dict = _result(UNMEASURED, "not built", unmeasured=1)

    # -- construction ----------------------------------------------------

    def add(self, records: Iterable[Mapping[str, Any]]) -> int:
        """Insert records, deriving their structural fields from their text."""
        added = 0
        for record in records:
            text = str(record["text"])
            structure = structure_from_text(text)
            card = record.get("card")
            if isinstance(card, Mapping):
                structure = _merge_card_structure(structure, card)
            palette = tuple(sorted(structure["palette"]))
            light = _first(structure["light"])
            texture = _first(structure["texture"])
            mood = _first(structure["mood"])
            provenance = str(record["provenance"])
            weight = provenance_weight(provenance)
            with self.lock:
                cur = self.conn.execute(
                    "INSERT INTO entries (kind, text, palette, light, texture, mood,"
                    " provenance, weight, source) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        str(record["kind"]),
                        text,
                        " ".join(palette),
                        light,
                        texture,
                        mood,
                        provenance,
                        weight,
                        str(record.get("source", "")),
                    ),
                )
                entry_id = int(cur.lastrowid or 0)
                self.conn.execute(
                    "INSERT INTO entries_fts (rowid, text, structured) VALUES (?,?,?)",
                    (entry_id, text, _structure_text(structure)),
                )
            added += 1
        with self.lock:
            self.conn.commit()
        return added

    def reload(self) -> None:
        """Refresh the in-memory mirror used by the non-lexical channels."""
        with self.lock:
            rows = self.conn.execute(
                "SELECT id, kind, text, palette, light, texture, mood, provenance,"
                " weight, source FROM entries ORDER BY id"
            ).fetchall()
        self.entries = [
            Entry(
                entry_id=int(row[0]),
                kind=row[1],
                text=row[2],
                palette=tuple(row[3].split()) if row[3] else (),
                light=row[4],
                texture=row[5],
                mood=row[6],
                provenance=row[7],
                weight=float(row[8]),
                source=row[9],
            )
            for row in rows
        ]
        self.by_id = {entry.entry_id: entry for entry in self.entries}

    def attach_dense(self, *, model_id: str = DENSE_MODEL_ID) -> dict:
        """Embed every non-core entry, or record why that could not be done."""
        probe = dense_probe(model_id=model_id)
        self.dense_report = probe
        if probe["outcome"] != PASS:
            return probe
        import numpy as np

        model = probe["model"]
        self.dense_model = model
        targets = [e for e in self.entries if e.kind != KIND_CORE]
        if not targets:
            self.dense_report = _result(
                UNMEASURED, "nothing to embed", unmeasured=1, error_code="EMPTY"
            )
            return self.dense_report
        vectors = model.encode([e.text for e in targets], normalize_embeddings=True, batch_size=64)
        matrix = np.asarray(vectors, dtype="float32")
        self.dense_ids = [e.entry_id for e in targets]
        self.dense_matrix = matrix
        dim = int(matrix.shape[1])
        with self.lock:
            for entry_id, row in zip(self.dense_ids, matrix):
                self.conn.execute(
                    "INSERT OR REPLACE INTO vectors (id, dim, data) VALUES (?,?,?)",
                    (entry_id, dim, row.tobytes()),
                )
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('dense_model', ?)",
                (model_id,),
            )
            self.conn.commit()
        self.dense_report = _result(
            PASS,
            f"embedded {len(self.dense_ids)} entries with {model_id}",
            checked=len(self.dense_ids),
        )
        return self.dense_report

    def load_dense_from_db(self, *, model_id: str = DENSE_MODEL_ID) -> dict:
        """Reuse vectors already stored in the file, without re-embedding."""
        with self.lock:
            rows = self.conn.execute("SELECT id, dim, data FROM vectors").fetchall()
        if not rows:
            self.dense_report = _result(
                UNMEASURED, "no stored vectors", unmeasured=1, error_code="EMPTY"
            )
            return self.dense_report
        probe = dense_probe(model_id=model_id)
        if probe["outcome"] != PASS:
            self.dense_report = probe
            return probe
        import numpy as np

        self.dense_model = probe["model"]
        self.dense_ids = [int(row[0]) for row in rows]
        dim = int(rows[0][1])
        self.dense_matrix = np.frombuffer(
            b"".join(row[2] for row in rows), dtype="float32"
        ).reshape(len(rows), dim)
        self.dense_report = _result(PASS, f"loaded {len(rows)} stored vectors", checked=len(rows))
        return self.dense_report

    # -- counting --------------------------------------------------------

    def counts(self) -> dict[str, int]:
        """Entry count per provenance, plus the total."""
        out: dict[str, int] = {}
        with self.lock:
            rows = self.conn.execute(
                "SELECT provenance, COUNT(*) FROM entries GROUP BY provenance"
            ).fetchall()
        for row in rows:
            out[str(row[0])] = int(row[1])
        out["total"] = sum(out.values())
        return out

    def core_entries(self) -> list[Entry]:
        """Core rules, in file order. They never compete for a slot in k."""
        return [e for e in self.entries if e.kind == KIND_CORE]


def _first(values: set[str]) -> str:
    """Pick one field value deterministically; empty means unknown."""
    return sorted(values)[0] if values else ""


CARD_VALUE_KEY_LIGHT: dict[str, str] = {
    "dark": "low-key",
    "light": "high-key",
    "mid": "soft",
}


def _merge_card_structure(
    structure: dict[str, set[str]], card: Mapping[str, Any]
) -> dict[str, set[str]]:
    """Fold a style card's own controlled fields into the extracted structure.

    The card fields were measured off the image by the harvester, so they beat
    anything guessed from the rendered sentence.
    """
    merged = {field: set(values) for field, values in structure.items()}
    value_key = str(card.get("value_key") or "")
    light = CARD_VALUE_KEY_LIGHT.get(value_key)
    if light:
        merged["light"].add(light)
    texture = str(card.get("texture") or "")
    if "grain" in texture:
        merged["texture"].add("film-grain")
    elif "flat" in texture or "smooth" in texture:
        merged["texture"].add("matte")
    return merged


def build_index(
    db_path: str | Path = ":memory:",
    *,
    core_rules: Path = CORE_RULES_PATH,
    our_prompts: Path = OUR_PROMPTS_DIR,
    reference_cards: Path = REFERENCE_CARDS_DIR,
    gallery_prompts: Path = GALLERY_PROMPTS_PATH,
    community_prompts: Path = COMMUNITY_PROMPTS_PATH,
    dense: bool | None = None,
) -> KnowledgeIndex:
    """Build the index from every source that is present.

    A missing source is reported, never fatal: the index must come up without
    the gallery harvest, because that file is produced by another agent.

    An index that comes up with core rules but no examples is reported as
    `could not measure`, not `pass`: it cannot answer a retrieval query.

    >>> index = build_index(core_rules=CORE_RULES_PATH,
    ...                     our_prompts=Path("/nowhere"),
    ...                     reference_cards=Path("/nowhere"),
    ...                     gallery_prompts=Path("/nowhere"),
    ...                     community_prompts=Path("/nowhere"))
    >>> index.build_report["outcome"], index.counts()["core"] > 0
    ('could not measure', True)
    """
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    # `check_same_thread=False`, with every statement taken under the index's
    # own lock. Every route in studio/app.py is a plain `def`, which FastAPI
    # runs in a threadpool worker; with sqlite3's default the first route to
    # call `retrieve()` from a worker raises ProgrammingError. Nothing calls it
    # yet, so this has never fired — which is exactly why it was worth fixing
    # before the commit that wires retrieval into the web layer.
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.executescript(SCHEMA)
    conn.execute("DELETE FROM entries")
    conn.execute("DELETE FROM entries_fts")
    conn.execute("DELETE FROM vectors")
    index = KnowledgeIndex(conn)

    loaded: dict[str, int] = {}
    missing: list[str] = []
    for name, records, where in (
        ("core", load_core_rules(core_rules), core_rules),
        ("ours", load_our_prompts(our_prompts), our_prompts),
        ("reference_card", load_style_cards(reference_cards), reference_cards),
        ("gallery", load_gallery_prompts(gallery_prompts), gallery_prompts),
        ("community", load_gallery_prompts(community_prompts), community_prompts),
    ):
        loaded[name] = index.add(records)
        if not records:
            missing.append(f"{name}({where})")
    index.reload()

    if dense is None:
        dense = os.environ.get(DENSE_ENV_FLAG, "") == "1"
    if dense:
        index.attach_dense()

    total = sum(loaded.values())
    examples = total - loaded["core"]
    if total == 0:
        outcome = UNMEASURED
        note = "no source produced a single entry"
    elif loaded["core"] == 0:
        outcome = FAIL
        note = "core rules missing: the index has examples but no source of truth"
    elif examples == 0:
        # The verdict that was missing, and its absence is what let the defect
        # above survive: an index holding only core rules reports PASS while
        # being unable to answer a single retrieval query. Zero examples is
        # never a built index; it is an index nobody can measure.
        outcome = UNMEASURED
        note = (
            f"{loaded['core']} core rules and 0 examples: every retrieval will "
            "answer 'could not measure' and evaluate cannot run"
        )
    else:
        outcome = PASS
        note = "built"
    index.build_report = _result(
        outcome,
        note + (f"; sources absent: {', '.join(missing)}" if missing else ""),
        checked=total,
        violations=0 if outcome != FAIL else 1,
        unmeasured=len(missing),
        per_source=loaded,
        dense=index.dense_report["outcome"],
        dense_note=index.dense_report["note"],
    )
    return index


# ------------------------------------------------------------------ search


def _phrases(terms: Sequence[str]) -> list[str]:
    """Contiguous n-grams of the query, longest first."""
    out: list[str] = []
    for size in range(PHRASE_MAX, 1, -1):
        for start in range(0, max(0, len(terms) - size + 1)):
            out.append(" ".join(terms[start : start + size]))
    return out


def _channel_phrase(
    index: KnowledgeIndex, terms: Sequence[str]
) -> tuple[list[int], dict[int, int]]:
    """Rank entries by the exact query phrases they contain.

    A longer phrase is stronger evidence, so a hit is worth its word count.
    """
    scores: dict[int, int] = defaultdict(int)
    for phrase in _phrases(terms):
        words = phrase.split()
        variants = {phrase, " ".join(SPELLINGS.get(w, w) for w in words)}
        weight = len(words)
        hit: set[int] = set()
        for variant in variants:
            try:
                # Under the index lock, like every other query in this file.
                # It was the one execute that was not, and CI caught it on
                # 2026-08-27: `ValueError: not enough values to unpack
                # (expected 1, got 0)` from the `(rowid,)` below, on Python
                # 3.12, in the threaded retrieval test. It never fires on a
                # machine whose sqlite3 reports `threadsafety == 3`
                # (serialized) — MEASURED 3 here — because that build
                # serialises the shared connection for us. Relying on the
                # runner's compile-time flag is not a guarantee; the lock is.
                with index.lock:
                    rows = index.conn.execute(
                        "SELECT rowid FROM entries_fts WHERE entries_fts MATCH ?",
                        (f'"{variant}"',),
                    ).fetchall()
            except sqlite3.OperationalError:
                continue
            hit.update(int(rowid) for (rowid,) in rows)
        for rowid in hit:
            scores[rowid] += weight
    ranking = sorted(scores, key=lambda i: (-scores[i], i))
    return ranking, dict(scores)


def _channel_bm25(index: KnowledgeIndex, terms: Sequence[str]) -> tuple[list[int], dict[int, int]]:
    """Rank entries by summed FTS5 BM25 over the query terms.

    Returns the ranking and, per entry, how many distinct query terms it
    carried — the hit count is what the admission floor is applied to.
    """
    scores: dict[int, float] = defaultdict(float)
    hits: dict[int, int] = defaultdict(int)
    for term in terms:
        variants = [term]
        alias = SPELLINGS.get(term)
        if alias:
            variants.append(alias)
        matched: set[int] = set()
        for variant in variants:
            escaped = variant.replace('"', "")
            if not escaped:
                continue
            try:
                with index.lock:
                    rows = index.conn.execute(
                        "SELECT rowid, bm25(entries_fts) FROM entries_fts"
                        " WHERE entries_fts MATCH ?",
                        (f'"{escaped}"',),
                    ).fetchall()
            except sqlite3.OperationalError:
                continue
            for rowid, score in rows:
                # FTS5 bm25() is negative, more negative is better.
                scores[int(rowid)] += -float(score)
                matched.add(int(rowid))
        for rowid in matched:
            hits[rowid] += 1
    ranking = sorted(scores, key=lambda i: (-scores[i], i))
    return ranking, dict(hits)


def _channel_structural(
    index: KnowledgeIndex, structure: Mapping[str, set[str]]
) -> tuple[list[int], dict[int, int]]:
    """Rank entries by how many allow-list fields they share with the query."""
    overlap: dict[int, int] = {}
    for entry in index.entries:
        if entry.kind == KIND_CORE:
            continue
        agree = 0
        if structure["palette"] & set(entry.palette):
            agree += 1
        for field, value in (
            ("light", entry.light),
            ("texture", entry.texture),
            ("mood", entry.mood),
        ):
            if value and value in structure[field]:
                agree += 1
        if agree:
            overlap[entry.entry_id] = agree
    ranking = sorted(overlap, key=lambda i: (-overlap[i], i))
    return ranking, overlap


def _channel_dense(index: KnowledgeIndex, text: str) -> tuple[list[int], dict[int, float]]:
    """Rank entries by cosine against the query embedding."""
    if index.dense_matrix is None or index.dense_model is None:
        return [], {}
    import numpy as np

    query = np.asarray(
        index.dense_model.encode([text], normalize_embeddings=True), dtype="float32"
    )[0]
    sims = index.dense_matrix @ query
    scored = {entry_id: float(sim) for entry_id, sim in zip(index.dense_ids, sims)}
    ranking = sorted(scored, key=lambda i: (-scored[i], i))
    return ranking, scored


def retrieve(
    spec_or_text: StyleSpec | str,
    *,
    k: int = DEFAULT_K,
    index: KnowledgeIndex | None = None,
) -> dict:
    """Return core rules plus up to `k` worked examples for a style request.

    Core rules are a separate field and never compete for a slot in `k`; no
    more than `MAX_PER_PROVENANCE` examples come from one provenance.

    :param spec_or_text: a `StyleSpec`, or the user's free text.
    :param k: how many examples to return.
    :param index: the index to search; the process-wide default if omitted.
    :returns: the studio judging dict plus `core_rules` and `examples`.

    >>> from studio.style import StyleSpec
    >>> idx = build_index()
    >>> out = retrieve("soft golden hour light, warm amber palette", index=idx)
    >>> out["outcome"] in ("pass", "fail", "could not measure")
    True
    """
    if index is None:
        index = default_index()
    if isinstance(spec_or_text, StyleSpec):
        text = " ".join(
            [
                " ".join(spec_or_text.palette),
                spec_or_text.light,
                spec_or_text.texture,
                spec_or_text.mood,
                spec_or_text.setting,
            ]
        ).strip()
        structure = {
            "palette": set(spec_or_text.palette),
            "light": {spec_or_text.light} if spec_or_text.light else set(),
            "texture": {spec_or_text.texture} if spec_or_text.texture else set(),
            "mood": {spec_or_text.mood} if spec_or_text.mood else set(),
        }
        structure = _merge(structure, structure_from_text(spec_or_text.setting))
    else:
        text = str(spec_or_text)
        structure = structure_from_text(text)

    core = [
        {"text": e.text, "source": e.source, "provenance": e.provenance}
        for e in index.core_entries()
    ]
    candidates = [e for e in index.entries if e.kind != KIND_CORE]
    if not candidates:
        return _result(
            UNMEASURED,
            "index holds no examples",
            unmeasured=1,
            core_rules=core,
            examples=[],
            k=k,
        )

    terms = query_terms(text)
    rankings: dict[str, list[int]] = {}
    admitted: set[int] = set()
    channels_off = 0

    if "bm25" in FUSION_CHANNELS:
        ranking, hits = _channel_bm25(index, terms)
        ranking = [i for i in ranking if index.by_id[i].kind != KIND_CORE]
        rankings["bm25"] = ranking
        floor = min(BM25_MIN_HITS, max(1, len(terms)))
        admitted |= {i for i in ranking if hits.get(i, 0) >= floor}
    else:
        channels_off += 1

    if "phrase" in FUSION_CHANNELS:
        ranking, phrase_hits = _channel_phrase(index, terms)
        ranking = [i for i in ranking if index.by_id[i].kind != KIND_CORE]
        if ranking:
            rankings["phrase"] = ranking
            admitted |= set(ranking)
    else:
        channels_off += 1

    if "structural" in FUSION_CHANNELS:
        ranking, overlap = _channel_structural(index, structure)
        rankings["structural"] = ranking
        admitted |= {i for i in ranking if overlap.get(i, 0) >= STRUCTURAL_MIN_FIELDS}
    else:
        channels_off += 1

    if "dense" in FUSION_CHANNELS:
        ranking, sims = _channel_dense(index, text)
        if ranking:
            rankings["dense"] = ranking
            admitted |= {i for i in ranking if sims.get(i, 0.0) >= DENSE_FLOOR}
        else:
            channels_off += 1
    else:
        channels_off += 1

    fused: dict[int, float] = defaultdict(float)
    for channel, ranking in rankings.items():
        weight = CHANNEL_WEIGHT.get(channel, 1.0)
        for position, entry_id in enumerate(ranking, start=1):
            fused[entry_id] += weight / (RRF_K + position)
    for entry_id in list(fused):
        fused[entry_id] *= index.by_id[entry_id].weight

    ordered = sorted((i for i in fused if i in admitted), key=lambda i: (-fused[i], i))
    # An entry that scored but did not clear the admission floor is the floor
    # doing its job, not a breach. It used to be reported as `violations`,
    # which made that field unreadable next to every other module's use of it.
    below_floor = len(fused) - len(ordered)

    picked: list[dict] = []
    per_provenance: dict[str, int] = defaultdict(int)
    seen_prefixes: set[str] = set()
    # How many entries the quota turned away. MEASURED 2026-08-26: with a
    # corpus of 4601 rows all carrying one provenance, the quota caps every
    # answer at 2 however large k is, and nothing in the result said so — a
    # caller asking for 5 got 2 and could not tell "the corpus has no more"
    # from "the guard stopped counting". The guard stays; the silence does not.
    quota_blocked = 0
    for entry_id in ordered:
        entry = index.by_id[entry_id]
        if per_provenance[entry.provenance] >= MAX_PER_PROVENANCE:
            quota_blocked += 1
            continue
        prefix = " ".join(entry.text.lower().split())[:DEDUP_PREFIX]
        if prefix in seen_prefixes:
            continue
        seen_prefixes.add(prefix)
        per_provenance[entry.provenance] += 1
        picked.append(
            {
                "id": entry.entry_id,
                "kind": entry.kind,
                "text": entry.text,
                "palette": list(entry.palette),
                "light": entry.light,
                "texture": entry.texture,
                "mood": entry.mood,
                "provenance": entry.provenance,
                "source": entry.source,
                "score": round(fused[entry_id], 6),
            }
        )
        if len(picked) >= k:
            break

    if picked:
        outcome, note = PASS, f"{len(picked)} examples above the floor"
        if len(picked) < k and quota_blocked:
            note = (
                f"{note}; {k} were asked for and the per-provenance quota of "
                f"{MAX_PER_PROVENANCE} turned away {quota_blocked} more — this "
                "index does not hold enough distinct sources to fill k"
            )
    else:
        outcome, note = FAIL, "nothing in the index clears the relevance floor"
    return _result(
        outcome,
        note,
        checked=len(candidates),
        violations=0,
        unmeasured=channels_off,
        core_rules=core,
        examples=picked,
        k=k,
        terms=terms,
        channels=sorted(rankings),
        below_floor=below_floor,
        quota_blocked=quota_blocked,
    )


def _merge(left: Mapping[str, set[str]], right: Mapping[str, set[str]]) -> dict[str, set[str]]:
    """Union two structural extractions field by field."""
    return {
        field: set(left.get(field, set())) | set(right.get(field, set()))
        for field in STRUCTURAL_FIELDS
    }


_DEFAULT_INDEX: KnowledgeIndex | None = None


def default_index(*, rebuild: bool = False) -> KnowledgeIndex:
    """Return the process-wide index, building it once on first use."""
    global _DEFAULT_INDEX
    if _DEFAULT_INDEX is None or rebuild:
        _DEFAULT_INDEX = build_index(DEFAULT_DB_PATH)
    return _DEFAULT_INDEX


# ---------------------------------------------------------------- evaluate


def _haystack(example: Mapping[str, Any]) -> str:
    """The text a `must_retrieve` phrase is looked for in."""
    return " ".join(
        [
            str(example.get("text", "")),
            " ".join(example.get("palette") or []),
            str(example.get("light", "")),
            str(example.get("texture", "")),
            str(example.get("mood", "")),
        ]
    ).lower()


def evaluate(
    index: KnowledgeIndex, eval_set: Sequence[Mapping[str, Any]], *, k: int = DEFAULT_K
) -> dict:
    """Score the index against the gold set and return recall@k / precision@k.

    A record with `"control": "negative"` must come back empty; one with
    `"control": "positive"` must come back non-empty and score full recall.
    Either control failing makes the whole run a FAIL however good the averages
    look — a retriever that cannot say "nothing here" is not measuring anything.

    :param index: the index under test.
    :param eval_set: records of {query, must_retrieve, must_not_retrieve}.
    :param k: cut-off for both metrics.
    :returns: the studio judging dict plus per-record and averaged numbers.
    """
    if not eval_set:
        return _result(UNMEASURED, "empty gold set", unmeasured=1, k=k)
    if not [e for e in index.entries if e.kind != KIND_CORE]:
        return _result(UNMEASURED, "index holds no examples", unmeasured=1, k=k, checked=0)

    recalls: list[float] = []
    precisions: list[float] = []
    per_record: list[dict] = []
    violations = 0
    unmeasured = 0
    controls = {"negative": {"checked": 0, "ok": 0}, "positive": {"checked": 0, "ok": 0}}

    for record in eval_set:
        query = str(record.get("query", ""))
        must = [str(m).lower() for m in record.get("must_retrieve") or []]
        must_not = [str(m).lower() for m in record.get("must_not_retrieve") or []]
        control = record.get("control")
        answer = retrieve(query, k=k, index=index)
        examples = answer["examples"]
        haystacks = [_haystack(example) for example in examples]
        blob = " ".join(haystacks)

        found = [phrase for phrase in must if phrase in blob]
        leaked = [phrase for phrase in must_not if phrase in blob]
        recall = len(found) / len(must) if must else None
        relevant = sum(1 for hay in haystacks if any(phrase in hay for phrase in must))
        precision = relevant / len(examples) if examples else (1.0 if not must else 0.0)

        ok = True
        if control == "negative":
            controls["negative"]["checked"] += 1
            ok = not examples
            controls["negative"]["ok"] += int(ok)
        elif control == "positive":
            controls["positive"]["checked"] += 1
            ok = bool(examples) and recall == 1.0
            controls["positive"]["ok"] += int(ok)
        if leaked:
            ok = False
        if recall is not None:
            recalls.append(recall)
            precisions.append(precision)
            if recall == 0.0:
                ok = False
        if not ok:
            violations += 1
        per_record.append(
            {
                "query": query,
                "control": control,
                "returned": len(examples),
                "recall": recall,
                "precision": precision if must else None,
                "found": found,
                "leaked": leaked,
                "ok": ok,
                "outcome": answer["outcome"],
            }
        )

    recall_at_k = sum(recalls) / len(recalls) if recalls else 0.0
    precision_at_k = sum(precisions) / len(precisions) if precisions else 0.0
    controls_ok = all(c["checked"] > 0 and c["ok"] == c["checked"] for c in controls.values())

    if not controls_ok:
        outcome = FAIL
        note = "a control failed: the instrument is not trustworthy on this run"
    elif recall_at_k < RECALL_FLOOR:
        outcome = FAIL
        note = f"recall@{k}={recall_at_k:.3f} below the floor {RECALL_FLOOR}"
    else:
        outcome = PASS
        note = f"recall@{k}={recall_at_k:.3f} precision@{k}={precision_at_k:.3f}"

    return _result(
        outcome,
        note,
        checked=len(eval_set),
        violations=violations,
        unmeasured=unmeasured,
        k=k,
        recall_at_k=round(recall_at_k, 4),
        precision_at_k=round(precision_at_k, 4),
        scored=len(recalls),
        controls=controls,
        per_record=per_record,
    )


def _cli() -> int:
    """Build the index and print the evaluation numbers."""
    dense = os.environ.get(DENSE_ENV_FLAG, "") == "1"
    index = build_index(DEFAULT_DB_PATH, dense=dense)
    print(
        "build:",
        json.dumps(
            {kk: vv for kk, vv in index.build_report.items() if kk != "per_source"},
            ensure_ascii=False,
        ),
    )
    print("per source:", index.build_report["per_source"])
    print("counts:", index.counts())
    print("dense:", index.dense_report["outcome"], "|", index.dense_report["note"])
    report = evaluate(index, load_eval_set())
    print(
        f"evaluate: outcome={report['outcome']} checked={report['checked']}"
        f" violations={report['violations']} unmeasured={report['unmeasured']}"
        f" recall@{report['k']}={report['recall_at_k']}"
        f" precision@{report['k']}={report['precision_at_k']}"
    )
    print("controls:", report["controls"])
    for row in report["per_record"]:
        if not row["ok"]:
            print(
                "  FAILING:",
                row["control"],
                "|",
                row["query"],
                "-> returned",
                row["returned"],
                "recall",
                row["recall"],
                "found",
                row["found"],
                "leaked",
                row["leaked"],
            )
    return 0 if report["outcome"] == PASS else 1


if __name__ == "__main__":  # pragma: no cover - entry point only
    raise SystemExit(_cli())
