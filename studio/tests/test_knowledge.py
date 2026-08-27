"""Tests for studio.knowledge: the instrument first, then the index.

The network is closed by the runner below, not by a convention: every test in
this module runs with the socket layer replaced by a raising stub, and the
dense channel is therefore always stubbed rather than downloaded.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio import knowledge as K
from studio.knowledge import (
    KIND_CORE,
    KIND_GALLERY_PROMPT,
    KIND_OUR_PROMPT,
    KIND_STYLE_CARD,
    KnowledgeIndex,
    build_index,
    evaluate,
    load_eval_set,
    query_terms,
    retrieve,
    structure_from_text,
)
from studio.style import LIGHT_WORDS, MOOD_WORDS, PALETTE_WORDS, TEXTURE_WORDS, StyleSpec

_REAL_SOCKET = socket.socket
_REAL_CONNECT = socket.create_connection

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = REPO_ROOT / "studio" / "knowledge"


class NetworkTouched(AssertionError):
    """Raised when a test reaches for a socket. A test that needs one is broken."""


def setUpModule() -> None:
    """Close the network for the whole module. Enforcement, not agreement (T4)."""

    def _blocked(*args: object, **kwargs: object) -> None:
        raise NetworkTouched("a test tried to open a socket")

    socket.socket = _blocked  # type: ignore[assignment, misc]
    socket.create_connection = _blocked  # type: ignore[assignment]


def tearDownModule() -> None:
    socket.socket = _REAL_SOCKET  # type: ignore[misc]
    socket.create_connection = _REAL_CONNECT


# A corpus small enough to reason about by hand. Every expected value in this
# module is a literal read off these strings, never a value imported back out
# of the module under test.
CORE_TEXT = "The formula. Subject then action then location then composition then style."

OURS = [
    "A quiet rooftop at golden hour, warm amber and gold light, soft film grain.",
    "A kitchen window in the morning, clean diffused daylight on matte paper texture.",
    "A night street under deep indigo sky, low-key light, smoky haze.",
]

CARDS = [
    {
        "text": "amber, gold, sand palette, moderate saturation, "
        "visible grain and tactile surface texture, mid value key",
        "card": {"value_key": "mid", "texture": "visible grain"},
    },
    {
        "text": "slate grey, charcoal palette, muted saturation, "
        "clean flat surfaces with smooth, untextured colour, dark value key",
        "card": {"value_key": "dark", "texture": "clean flat surfaces"},
    },
    {
        "text": "rose, ivory palette, muted saturation, "
        "clean flat surfaces with smooth, untextured colour, light value key",
        "card": {"value_key": "light", "texture": "clean flat surfaces"},
    },
]


def tiny_index() -> KnowledgeIndex:
    """Build an in-memory index over the hand-written corpus above.

    The connection is opened the same way `build_index` opens it, thread flag
    included. A helper that connects differently from production is a helper
    that tests a different object.
    """
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(K.SCHEMA)
    index = KnowledgeIndex(conn)
    index.add(
        [
            {
                "kind": KIND_CORE,
                "text": CORE_TEXT,
                "provenance": K.PROVENANCE_CORE,
                "source": "core_rules.md",
            }
        ]
    )
    index.add(
        {
            "kind": KIND_OUR_PROMPT,
            "text": text,
            "provenance": K.PROVENANCE_OURS,
            "source": f"ours-{n}",
        }
        for n, text in enumerate(OURS)
    )
    index.add(
        {
            "kind": KIND_STYLE_CARD,
            "text": card["text"],
            "card": card["card"],
            "provenance": K.PROVENANCE_REFERENCE_CARD,
            "source": f"card-{n}",
        }
        for n, card in enumerate(CARDS)
    )
    index.reload()
    return index


class StubDense:
    """A deterministic stand-in for the embedding model.

    It scores by shared words, which is enough to exercise the dense channel's
    plumbing and its floor without ever reaching a weights server.
    """

    def __init__(self, vocabulary: list[str]) -> None:
        self.vocabulary = vocabulary

    def encode(self, texts, normalize_embeddings=True, batch_size=64):  # noqa: ANN001
        import numpy as np

        rows = []
        for text in texts:
            words = set(text.lower().split())
            row = np.array(
                [1.0 if word in words else 0.0 for word in self.vocabulary],
                dtype="float32",
            )
            norm = float(np.linalg.norm(row)) or 1.0
            rows.append(row / norm)
        return np.asarray(rows, dtype="float32")


def attach_stub_dense(index: KnowledgeIndex) -> None:
    """Attach the stub embedder to an index, exactly as attach_dense would."""
    import numpy as np

    vocabulary = sorted({word for entry in index.entries for word in entry.text.lower().split()})
    model = StubDense(vocabulary)
    targets = [e for e in index.entries if e.kind != KIND_CORE]
    index.dense_model = model
    index.dense_ids = [e.entry_id for e in targets]
    index.dense_matrix = np.asarray(model.encode([e.text for e in targets]), dtype="float32")


class SingleSourceOfTruth(unittest.TestCase):
    """The structural vocabulary has one home, and it is studio.style."""

    def test_field_words_are_the_style_lists_themselves(self) -> None:
        self.assertIs(K.FIELD_WORDS["palette"], PALETTE_WORDS)
        self.assertIs(K.FIELD_WORDS["light"], LIGHT_WORDS)
        self.assertIs(K.FIELD_WORDS["texture"], TEXTURE_WORDS)
        self.assertIs(K.FIELD_WORDS["mood"], MOOD_WORDS)

    def test_module_not_shadowed_by_the_data_directory(self) -> None:
        # studio/knowledge.py and studio/knowledge/ share a name on purpose;
        # if the directory ever wins the import, every caller breaks silently.
        self.assertTrue(K.__file__.endswith("knowledge.py"))

    def test_synonyms_only_ever_point_at_allow_list_words(self) -> None:
        for word, (field, target) in K.SYNONYMS.items():
            self.assertIn(field, K.STRUCTURAL_FIELDS, word)
            self.assertIn(target, K.FIELD_WORDS[field], word)


class Extraction(unittest.TestCase):
    """Free text becomes allow-list fields, or nothing at all."""

    def test_direct_words(self) -> None:
        found = structure_from_text("warm amber light with film-grain, dreamy")
        self.assertEqual(sorted(found["palette"]), ["amber"])
        self.assertEqual(sorted(found["texture"]), ["film-grain"])
        self.assertEqual(sorted(found["mood"]), ["dreamy"])

    def test_spaced_form_of_a_hyphenated_word(self) -> None:
        self.assertEqual(sorted(structure_from_text("golden hour")["light"]), ["golden-hour"])

    def test_synonym_maps_onto_the_allow_list(self) -> None:
        found = structure_from_text("olive and sage tones at sunset, cosy")
        self.assertEqual(sorted(found["palette"]), ["emerald"])
        self.assertEqual(sorted(found["light"]), ["golden-hour"])
        self.assertEqual(sorted(found["mood"]), ["calm"])

    def test_unknown_text_yields_no_fields(self) -> None:
        found = structure_from_text("a quarterly value added tax return")
        self.assertEqual(
            {field: sorted(v) for field, v in found.items()},
            {"palette": [], "light": [], "texture": [], "mood": []},
        )

    def test_stopwords_are_dropped_from_query_terms(self) -> None:
        self.assertEqual(query_terms("I want a photo with soft light"), ["soft", "light"])


class Building(unittest.TestCase):
    """Three outcomes at build time, and never PASS on nothing."""

    def test_missing_everything_is_unmeasured(self) -> None:
        index = build_index(
            core_rules=Path("/nowhere/core.md"),
            our_prompts=Path("/nowhere/gen"),
            reference_cards=Path("/nowhere/refs"),
            gallery_prompts=Path("/nowhere/gallery.jsonl"),
            community_prompts=Path("/nowhere/community.jsonl"),
        )
        self.assertEqual(index.build_report["outcome"], UNMEASURED)
        self.assertEqual(index.build_report["checked"], 0)

    def test_examples_without_core_rules_is_a_fail(self) -> None:
        # Core is the source of truth, not an optional extra: an index full of
        # examples and empty of rules is wrong, not merely unmeasured.
        with tempfile.TemporaryDirectory() as tmp:
            gallery = Path(tmp) / "gallery_prompts.jsonl"
            gallery.write_text(
                json.dumps({"prompt": "soft golden hour light on film grain"}) + "\n",
                encoding="utf-8",
            )
            index = build_index(
                core_rules=Path("/nowhere/core.md"),
                our_prompts=Path("/nowhere/gen"),
                reference_cards=Path("/nowhere/refs"),
                gallery_prompts=gallery,
                community_prompts=Path("/nowhere/community.jsonl"),
            )
        self.assertEqual(index.build_report["outcome"], FAIL)
        self.assertEqual(index.build_report["violations"], 1)
        self.assertEqual(index.build_report["per_source"]["gallery"], 1)

    def test_core_rules_alone_are_not_a_built_index(self) -> None:
        """This test used to assert PASS, and that assertion is what let the
        real defect hide for a session: with both example corpora behind
        absolute paths to one machine, every other machine built exactly this
        index — 12 core rules, 0 examples — and was told it had passed. Such an
        index cannot answer a single retrieval query and `evaluate` cannot run
        against it, so the honest verdict is "could not measure"."""
        index = build_index(
            core_rules=KNOWLEDGE_DIR / "core_rules.md",
            our_prompts=Path("/nowhere/gen"),
            reference_cards=Path("/nowhere/refs"),
            gallery_prompts=Path("/nowhere/gallery.jsonl"),
            community_prompts=Path("/nowhere/community.jsonl"),
        )
        self.assertEqual(index.build_report["outcome"], UNMEASURED)
        self.assertIn("0 examples", index.build_report["note"])
        self.assertGreaterEqual(index.build_report["per_source"]["core"], 10)
        self.assertEqual(index.build_report["unmeasured"], 4)

    def test_one_example_is_enough_to_make_it_a_built_index(self) -> None:
        """The other side of the mutation above: add a single example and the
        verdict must flip. A floor nothing can cross is a floor nobody has
        measured."""
        with tempfile.TemporaryDirectory() as tmp:
            gallery = Path(tmp) / "gallery.jsonl"
            gallery.write_text(
                json.dumps({"prompt": "amber golden-hour light, film-grain texture"}) + "\n",
                encoding="utf-8",
            )
            index = build_index(
                core_rules=KNOWLEDGE_DIR / "core_rules.md",
                our_prompts=Path("/nowhere/gen"),
                reference_cards=Path("/nowhere/refs"),
                gallery_prompts=gallery,
                community_prompts=Path("/nowhere/community.jsonl"),
            )
        self.assertEqual(index.build_report["outcome"], PASS)

    def test_the_corpus_directories_are_not_one_machine(self) -> None:
        """They were absolute paths into one developer's home directory, so
        every other clone built an empty index. The resolver now takes an
        environment override first, then a path inside this repository, and
        only then the original absolute path."""
        with tempfile.TemporaryDirectory() as tmp:
            here = Path(tmp)
            (here / "gen").mkdir()
            with mock.patch.dict(os.environ, {K.OUR_PROMPTS_ENV: str(here / "gen")}, clear=False):
                self.assertEqual(
                    K._resolve_dir(
                        K.OUR_PROMPTS_ENV, Path("/nowhere/in-repo"), Path("/nowhere/legacy")
                    ),
                    here / "gen",
                )
        # With nothing set and nothing on disk, the path it names belongs to
        # this repository — a reader can create it. Naming a stranger's home
        # directory is what made the original failure unactionable.
        with mock.patch.dict(os.environ, {K.OUR_PROMPTS_ENV: ""}, clear=False):
            fallback = K._resolve_dir(
                K.OUR_PROMPTS_ENV, Path("/nowhere/in-repo"), Path("/nowhere/legacy")
            )
        self.assertEqual(fallback, Path("/nowhere/in-repo"))

    def test_retrieve_is_safe_from_several_threads(self) -> None:
        """Every route in studio/app.py is a plain `def`, which FastAPI runs in
        a threadpool worker. With sqlite3's default check_same_thread the first
        such call raises ProgrammingError. Nothing calls retrieve() from the web
        layer yet, so this guards the commit that will."""
        index = tiny_index()
        errors: list[BaseException] = []

        def query() -> None:
            try:
                for _ in range(10):
                    retrieve("amber golden-hour light film-grain", index=index)
            except BaseException as exc:  # noqa: BLE001 - the point is to catch it
                errors.append(exc)

        threads = [threading.Thread(target=query) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [], f"threaded retrieval raised {errors[:1]}")

    def test_the_thread_guard_would_notice_the_old_connection(self) -> None:
        """The mutation: a connection opened the old way must fail from another
        thread, or the test above proves nothing."""
        conn = sqlite3.connect(":memory:", check_same_thread=True)
        conn.execute("CREATE TABLE t (x INTEGER)")
        errors: list[BaseException] = []

        def touch() -> None:
            try:
                conn.execute("SELECT * FROM t").fetchall()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        thread = threading.Thread(target=touch)
        thread.start()
        thread.join()
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], sqlite3.ProgrammingError)

    def test_below_floor_candidates_are_not_reported_as_violations(self) -> None:
        """An entry that scored but did not clear the admission floor is the
        floor working. Counting it as a violation made that field unreadable
        against every other module's use of it."""
        index = tiny_index()
        out = retrieve("amber golden-hour light film-grain", index=index)
        self.assertEqual(out["violations"], 0)
        self.assertIn("below_floor", out)
        self.assertGreaterEqual(out["below_floor"], 0)

    def test_a_namespaced_provenance_counts_as_its_own_source(self) -> None:
        """MEASURED 2026-08-27. A community corpus was collected with one
        provenance per uploader — 1409 rows across 106 people — precisely so
        the per-answer quota would see many sources. The loader then collapsed
        every provenance it did not recognise into PROVENANCE_GALLERY, so all
        106 became one and the quota capped every answer at 2 again. The corpus
        had done the right thing and the reader undid it.

        The guard itself was never the problem and is NOT relaxed here: it
        still admits at most MAX_PER_PROVENANCE per source. It just sees the
        sources now.
        """
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.executescript(K.SCHEMA)
        index = KnowledgeIndex(conn)
        index.add(
            [
                {
                    "kind": KIND_GALLERY_PROMPT,
                    "text": f"warm amber golden hour light soft film grain variant {n}",
                    "provenance": f"civitai:author{n % 9}",
                    "source": f"c-{n}",
                }
                for n in range(18)
            ]
        )
        index.reload()
        out = retrieve("warm amber golden hour light soft film grain", index=index, k=6)
        self.assertEqual(len(out["examples"]), 6)
        self.assertEqual(out["quota_blocked"], 0)
        self.assertEqual(len({e["provenance"] for e in out["examples"]}), 6)

    def test_the_LOADER_keeps_a_namespaced_provenance(self) -> None:
        """The defect site itself, and the reason this test exists separately.

        Found by mutation: restoring the old collapse left every test above
        GREEN, because they all call `index.add()` directly and the flattening
        lives in the JSONL loader. A test that does not go through the code
        that broke is not a test of it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "community.jsonl"
            path.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "prompt": f"warm amber golden hour light variant {n}",
                            "provenance": f"civitai:author{n}",
                            "rights": "owner_authorisation_2026-08-27",
                            "id": f"c-{n}",
                        }
                    )
                    for n in range(4)
                )
                + "\n",
                encoding="utf-8",
            )
            rows = K.load_gallery_prompts(path)
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            sorted(r["provenance"] for r in rows),
            ["civitai:author0", "civitai:author1", "civitai:author2", "civitai:author3"],
        )

    def test_the_LOADER_still_collapses_a_family_nobody_declared(self) -> None:
        """The negative control on the loader: namespacing is not a bypass."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "odd.jsonl"
            path.write_text(
                json.dumps({"prompt": "amber light", "provenance": "madeup:someone", "id": "x"})
                + "\n",
                encoding="utf-8",
            )
            rows = K.load_gallery_prompts(path)
        self.assertEqual(rows[0]["provenance"], K.PROVENANCE_GALLERY)

    def test_one_namespaced_author_is_still_capped(self) -> None:
        """The negative control, and the whole reason the guard exists. Naming
        a source more precisely must not become a way around the quota: 18 rows
        from ONE uploader still yield MAX_PER_PROVENANCE."""
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.executescript(K.SCHEMA)
        index = KnowledgeIndex(conn)
        index.add(
            [
                {
                    "kind": KIND_GALLERY_PROMPT,
                    "text": f"warm amber golden hour light soft film grain variant {n}",
                    "provenance": "civitai:one-prolific-person",
                    "source": f"c-{n}",
                }
                for n in range(18)
            ]
        )
        index.reload()
        out = retrieve("warm amber golden hour light soft film grain", index=index, k=6)
        self.assertEqual(len(out["examples"]), K.MAX_PER_PROVENANCE)
        self.assertGreater(out["quota_blocked"], 0)

    def test_the_family_carries_the_weight_and_the_whole_string_the_identity(self) -> None:
        """Two halves of one rule, as literals. Trust is a property of the KIND
        of source; "no single source fills the answer" is a statement about
        people."""
        self.assertEqual(K.provenance_family("civitai:Lykon"), "civitai")
        self.assertEqual(K.provenance_family("ours"), "ours")
        self.assertEqual(K.provenance_weight("civitai:Lykon"), 0.6)
        self.assertEqual(K.provenance_weight("civitai:Merjic"), 0.6)
        self.assertEqual(K.provenance_weight("ours"), 0.9)

    def test_an_author_name_containing_the_separator_still_lands_in_its_family(self) -> None:
        self.assertEqual(K.provenance_family("civitai:odd:name"), "civitai")
        self.assertEqual(K.provenance_weight("civitai:odd:name"), 0.6)

    def test_a_provenance_from_no_known_family_is_still_collapsed(self) -> None:
        """The other negative control: namespacing is not a blank cheque. A
        family nobody has classified does not get to invent itself a rung."""
        self.assertFalse(K._known_provenance("madeup:someone"))
        self.assertEqual(K.provenance_weight("madeup:someone"), 0.5)

    def test_a_single_source_index_says_the_quota_capped_the_answer(self) -> None:
        """MEASURED 2026-08-26 on a real 4601-row corpus: every row shared one
        provenance, so the quota capped every answer at MAX_PER_PROVENANCE
        however large k was, and the result did not say so. A caller asking for
        5 and getting 2 could not tell "the corpus has no more" from "the guard
        stopped counting"."""
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.executescript(K.SCHEMA)
        index = KnowledgeIndex(conn)
        index.add(
            [
                {
                    "kind": KIND_CORE,
                    "text": CORE_TEXT,
                    "provenance": K.PROVENANCE_CORE,
                    "source": "core_rules.md",
                }
            ]
        )
        index.add(
            [
                {
                    "kind": KIND_GALLERY_PROMPT,
                    "text": f"warm amber golden hour light with soft film grain, variant {n}",
                    "provenance": K.PROVENANCE_THIRD_PARTY,
                    "source": f"g-{n}",
                }
                for n in range(8)
            ]
        )
        index.reload()
        out = retrieve("warm amber golden hour light soft film grain", index=index, k=5)
        self.assertEqual(out["outcome"], PASS)
        self.assertEqual(len(out["examples"]), K.MAX_PER_PROVENANCE)
        self.assertGreater(out["quota_blocked"], 0)
        self.assertIn("quota", out["note"])

    def test_a_multi_source_index_fills_k_without_the_quota_note(self) -> None:
        """The other direction: with enough distinct sources the quota never
        bites, and the note must not claim it did."""
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.executescript(K.SCHEMA)
        index = KnowledgeIndex(conn)
        index.add(
            [
                {
                    "kind": KIND_CORE,
                    "text": CORE_TEXT,
                    "provenance": K.PROVENANCE_CORE,
                    "source": "core_rules.md",
                }
            ]
        )
        for n, provenance in enumerate(
            (K.PROVENANCE_OURS, K.PROVENANCE_REFERENCE_CARD, K.PROVENANCE_THIRD_PARTY)
        ):
            index.add(
                [
                    {
                        "kind": KIND_GALLERY_PROMPT,
                        "text": f"warm amber golden hour light with soft film grain, take {n}{m}",
                        "provenance": provenance,
                        "source": f"s-{n}-{m}",
                    }
                    for m in range(2)
                ]
            )
        index.reload()
        out = retrieve("warm amber golden hour light soft film grain", index=index, k=5)
        self.assertEqual(len(out["examples"]), 5)
        self.assertNotIn("quota", out["note"])

    def test_the_community_corpus_is_a_source_of_the_index(self) -> None:
        """The counter before the knob. Without this, deleting the community
        line from `build_index` leaves every other test green — the corpus is
        gitignored, so on a fresh clone nothing would notice it stopped being
        loaded, and the whole point of collecting it would quietly lapse."""
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "civitai_prompts.jsonl"
            corpus.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "prompt": f"amber golden-hour light on film grain, take {n}",
                            "provenance": f"civitai:author{n}",
                            "rights": "owner_authorisation_2026-08-27",
                            "source_url": f"https://civitai.com/api/v1/model-versions/{n}",
                        }
                    )
                    for n in range(3)
                )
                + "\n",
                encoding="utf-8",
            )
            index = build_index(
                core_rules=KNOWLEDGE_DIR / "core_rules.md",
                our_prompts=Path("/nowhere/gen"),
                reference_cards=Path("/nowhere/refs"),
                gallery_prompts=Path("/nowhere/gallery.jsonl"),
                community_prompts=corpus,
            )
            self.assertEqual(index.build_report["per_source"]["community"], 3)
            self.assertEqual(index.build_report["outcome"], PASS)
            out = retrieve("amber golden hour light film grain", index=index, k=5)
            # Three authors, quota two per provenance: all three survive only
            # because the namespace makes them three sources, not one corpus.
            self.assertEqual(len(out["examples"]), 3, out["note"])
            sources = {e["source"] for e in out["examples"]}
            self.assertTrue(
                all("civitai.com/api/v1/model-versions/" in s for s in sources),
                f"a row must cite where it can be re-read, got {sources}",
            )

    def test_a_missing_gallery_file_is_reported_not_fatal(self) -> None:
        index = build_index(
            core_rules=KNOWLEDGE_DIR / "core_rules.md",
            our_prompts=Path("/nowhere/gen"),
            reference_cards=Path("/nowhere/refs"),
            gallery_prompts=Path("/nowhere/gallery.jsonl"),
            community_prompts=Path("/nowhere/community.jsonl"),
        )
        self.assertIn("gallery", index.build_report["note"])

    def test_dense_is_off_unless_asked(self) -> None:
        index = build_index(
            core_rules=KNOWLEDGE_DIR / "core_rules.md",
            our_prompts=Path("/nowhere/gen"),
            reference_cards=Path("/nowhere/refs"),
            gallery_prompts=Path("/nowhere/gallery.jsonl"),
            community_prompts=Path("/nowhere/community.jsonl"),
        )
        self.assertEqual(index.dense_report["outcome"], UNMEASURED)
        self.assertEqual(index.dense_report["error_code"], "OFF")

    def test_card_fields_beat_the_rendered_sentence(self) -> None:
        index = tiny_index()
        card = [e for e in index.entries if e.source == "card-1"][0]
        self.assertEqual(card.light, "low-key")
        self.assertEqual(card.texture, "matte")


class GalleryRows(unittest.TestCase):
    """The harvester's rows keep their own origin fields (knowledge/PROVENANCE.md)."""

    def row(self, **overrides: object) -> str:
        payload = {
            "id": "00094d24d42befc7",
            "prompt": "soft golden light on visible grain",
            "source_url": "https://aidsgn.ru/sets",
            "harvested": "2026-08-25",
            "provenance": "third_party_gallery",
            "rights": "owner_decision_2026-08-25",
        }
        payload.update(overrides)
        return json.dumps(payload)

    def load(self, line: str) -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gallery_prompts.jsonl"
            path.write_text(line + "\n", encoding="utf-8")
            return K.load_gallery_prompts(path)

    def test_declared_provenance_and_rights_survive_the_load(self) -> None:
        loaded = self.load(self.row())
        self.assertEqual(loaded[0]["provenance"], "third_party_gallery")
        self.assertEqual(loaded[0]["source"], "00094d24d42befc7 (rights=owner_decision_2026-08-25)")

    def test_an_unknown_provenance_falls_back_rather_than_scoring_unknown(self) -> None:
        loaded = self.load(self.row(provenance="something_nobody_weighted"))
        self.assertEqual(loaded[0]["provenance"], "gallery")

    def test_a_row_without_wording_is_skipped(self) -> None:
        self.assertEqual(self.load(self.row(prompt="")), [])


class Retrieval(unittest.TestCase):
    """Three outcomes at query time, plus the two structural fuses."""

    def setUp(self) -> None:
        self.index = tiny_index()

    def test_a_hit_is_a_pass_and_carries_core_rules_separately(self) -> None:
        answer = retrieve("golden hour warm amber light, film grain", index=self.index)
        self.assertEqual(answer["outcome"], PASS)
        self.assertTrue(answer["examples"])
        self.assertEqual([r["text"] for r in answer["core_rules"]], [CORE_TEXT])
        for example in answer["examples"]:
            self.assertNotEqual(example["kind"], KIND_CORE)

    def test_core_rules_do_not_eat_a_slot_in_k(self) -> None:
        answer = retrieve("palette", k=2, index=self.index)
        self.assertLessEqual(len(answer["examples"]), 2)
        self.assertEqual(len(answer["core_rules"]), 1)

    def test_an_absent_topic_returns_nothing_and_says_so(self) -> None:
        answer = retrieve("quarterly value added tax return filing deadline", index=self.index)
        self.assertEqual(answer["examples"], [])
        self.assertEqual(answer["outcome"], FAIL)

    def test_an_empty_index_is_unmeasured_not_a_fail(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.executescript(K.SCHEMA)
        empty = KnowledgeIndex(conn)
        empty.reload()
        answer = retrieve("golden hour", index=empty)
        self.assertEqual(answer["outcome"], UNMEASURED)
        self.assertEqual(answer["unmeasured"], 1)

    def test_quota_caps_one_provenance(self) -> None:
        answer = retrieve("palette grain light", k=6, index=self.index)
        counts: dict[str, int] = {}
        for example in answer["examples"]:
            counts[example["provenance"]] = counts.get(example["provenance"], 0) + 1
        for provenance, count in counts.items():
            self.assertLessEqual(count, 2, provenance)

    def test_a_style_spec_is_accepted_as_well_as_text(self) -> None:
        spec = StyleSpec(
            palette=("amber", "gold"),
            light="golden-hour",
            texture="film-grain",
            mood="nostalgic",
            setting="a quiet rooftop at dusk",
        )
        answer = retrieve(spec, index=self.index)
        self.assertEqual(answer["outcome"], PASS)

    def test_near_duplicates_do_not_take_two_slots(self) -> None:
        index = tiny_index()
        index.add(
            [
                {
                    "kind": KIND_OUR_PROMPT,
                    "text": OURS[0],
                    "provenance": K.PROVENANCE_OURS,
                    "source": "ours-copy",
                }
            ]
        )
        index.reload()
        answer = retrieve("golden hour warm amber gold film grain", k=5, index=index)
        texts = [e["text"] for e in answer["examples"]]
        self.assertEqual(len(texts), len(set(texts)))


class DenseChannel(unittest.TestCase):
    """The dense channel is optional, floored, and reports why it is absent."""

    def test_absent_weights_are_a_measured_unmeasured_with_a_code(self) -> None:
        report = K.dense_probe(model_id="definitely/not-a-real-model-id")
        self.assertEqual(report["outcome"], UNMEASURED)
        self.assertEqual(report["unmeasured"], 1)
        self.assertIsInstance(report["error_code"], str)
        self.assertIsNone(report["model"])

    def test_the_dense_floor_still_refuses_an_absent_topic(self) -> None:
        index = tiny_index()
        attach_stub_dense(index)
        answer = retrieve("quarterly value added tax return filing", index=index)
        self.assertEqual(answer["examples"], [])


class Evaluating(unittest.TestCase):
    """The instrument itself: it must be able to say no, and to say 'cannot'."""

    def setUp(self) -> None:
        self.index = tiny_index()
        self.gold = [
            {
                "query": "golden hour warm amber light with film grain",
                "must_retrieve": ["amber"],
                "must_not_retrieve": [],
                "control": "positive",
            },
            {
                "query": "quarterly value added tax return filing deadline",
                "must_retrieve": [],
                "must_not_retrieve": ["palette"],
                "control": "negative",
            },
            {
                "query": "deep indigo night street, low-key",
                "must_retrieve": ["indigo"],
                "must_not_retrieve": [],
                "control": None,
            },
        ]

    def test_an_empty_gold_set_is_unmeasured(self) -> None:
        report = evaluate(self.index, [])
        self.assertEqual(report["outcome"], UNMEASURED)
        self.assertEqual(report["checked"], 0)

    def test_an_empty_index_is_unmeasured(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.executescript(K.SCHEMA)
        empty = KnowledgeIndex(conn)
        empty.reload()
        report = evaluate(empty, self.gold)
        self.assertEqual(report["outcome"], UNMEASURED)

    def test_a_good_index_passes_with_numbers(self) -> None:
        report = evaluate(self.index, self.gold)
        self.assertEqual(report["outcome"], PASS)
        self.assertEqual(report["checked"], 3)
        self.assertEqual(report["violations"], 0)
        self.assertEqual(report["recall_at_k"], 1.0)
        self.assertEqual(report["controls"]["negative"], {"checked": 1, "ok": 1})
        self.assertEqual(report["controls"]["positive"], {"checked": 1, "ok": 1})

    def test_a_gold_set_without_controls_can_never_pass(self) -> None:
        uncontrolled = [dict(record, control=None) for record in self.gold]
        report = evaluate(self.index, uncontrolled)
        self.assertEqual(report["outcome"], FAIL)
        self.assertIn("control", report["note"])

    def test_a_broken_negative_control_fails_however_high_recall_is(self) -> None:
        # A query that DOES exist in the corpus, mislabelled as absent: the run
        # must fail even though every other record scores perfectly.
        gold = self.gold + [
            {
                "query": "golden hour amber",
                "must_retrieve": [],
                "must_not_retrieve": [],
                "control": "negative",
            }
        ]
        report = evaluate(self.index, gold)
        self.assertEqual(report["outcome"], FAIL)
        self.assertEqual(report["recall_at_k"], 1.0)

    def test_a_leaked_forbidden_phrase_is_a_violation(self) -> None:
        gold = self.gold + [
            {
                "query": "deep indigo night street",
                "must_retrieve": ["indigo"],
                "must_not_retrieve": ["indigo"],
                "control": None,
            }
        ]
        report = evaluate(self.index, gold)
        self.assertGreaterEqual(report["violations"], 1)


class GoldSetFile(unittest.TestCase):
    """The shipped gold set is a fixture and is checked like one."""

    def setUp(self) -> None:
        self.records = load_eval_set(KNOWLEDGE_DIR / "eval_set.jsonl")

    def test_size_and_shape(self) -> None:
        self.assertGreaterEqual(len(self.records), 30)
        self.assertLessEqual(len(self.records), 40)
        for record in self.records:
            self.assertIn("query", record)
            self.assertIn("must_retrieve", record)
            self.assertIn("must_not_retrieve", record)

    def test_both_controls_are_present(self) -> None:
        controls = [r.get("control") for r in self.records]
        self.assertGreaterEqual(controls.count("negative"), 1)
        self.assertGreaterEqual(controls.count("positive"), 1)

    def test_every_line_is_valid_json(self) -> None:
        raw = (KNOWLEDGE_DIR / "eval_set.jsonl").read_text(encoding="utf-8")
        for line in raw.splitlines():
            if line.strip():
                json.loads(line)


class Mutation(unittest.TestCase):
    """Every decision constant is mutated both ways; a silent one is unguarded."""

    def setUp(self) -> None:
        self.index = tiny_index()
        self.gold = [
            {
                "query": "clean diffused daylight on matte paper texture",
                "must_retrieve": ["matte paper texture"],
                "must_not_retrieve": [],
                "control": "positive",
            },
            {
                "query": "quarterly value added tax return filing deadline",
                "must_retrieve": [],
                "must_not_retrieve": [],
                "control": "negative",
            },
        ]

    def test_quota_mutated_tighter_and_looser(self) -> None:
        index = tiny_index()
        query = "palette saturation value key"
        original = K.MAX_PER_PROVENANCE
        try:
            K.MAX_PER_PROVENANCE = 1
            tight = retrieve(query, k=6, index=index)
            K.MAX_PER_PROVENANCE = 99
            loose = retrieve(query, k=6, index=index)
        finally:
            K.MAX_PER_PROVENANCE = original
        tight_cards = sum(
            1 for e in tight["examples"] if e["provenance"] == K.PROVENANCE_REFERENCE_CARD
        )
        loose_cards = sum(
            1 for e in loose["examples"] if e["provenance"] == K.PROVENANCE_REFERENCE_CARD
        )
        self.assertEqual(tight_cards, 1)
        self.assertGreaterEqual(loose_cards, 3)

    def test_recall_floor_mutated_tighter_and_looser(self) -> None:
        gold = self.gold + [
            {
                "query": "a topic the corpus has never heard of, quarterly tax",
                "must_retrieve": ["amber"],
                "must_not_retrieve": [],
                "control": None,
            }
        ]
        original = K.RECALL_FLOOR
        try:
            K.RECALL_FLOOR = 0.0
            lenient = evaluate(self.index, gold)
            K.RECALL_FLOOR = 0.99
            strict = evaluate(self.index, gold)
        finally:
            K.RECALL_FLOOR = original
        self.assertEqual(lenient["outcome"], PASS)
        self.assertEqual(strict["outcome"], FAIL)

    def test_dense_floor_mutated_tighter_and_looser(self) -> None:
        index = tiny_index()
        attach_stub_dense(index)
        query = "quarterly value added tax return filing"
        original = K.DENSE_FLOOR
        try:
            K.DENSE_FLOOR = 0.0
            open_floor = retrieve(query, index=index)
            K.DENSE_FLOOR = 0.99
            closed_floor = retrieve(query, index=index)
        finally:
            K.DENSE_FLOOR = original
        self.assertTrue(open_floor["examples"])
        self.assertEqual(closed_floor["examples"], [])

    def test_bm25_hit_floor_mutated_tighter_and_looser(self) -> None:
        index = tiny_index()
        original_channels = K.FUSION_CHANNELS
        original_floor = K.BM25_MIN_HITS
        query = "palette tax return deadline"
        try:
            K.FUSION_CHANNELS = ("bm25",)
            K.BM25_MIN_HITS = 1
            loose = retrieve(query, k=6, index=index)
            K.BM25_MIN_HITS = 4
            tight = retrieve(query, k=6, index=index)
        finally:
            K.FUSION_CHANNELS = original_channels
            K.BM25_MIN_HITS = original_floor
        self.assertTrue(loose["examples"])
        self.assertEqual(tight["examples"], [])


class ShippedIndex(unittest.TestCase):
    """The real corpus, if it is on this machine. Absent sources are not a failure."""

    def test_full_build_and_evaluation(self) -> None:
        index = build_index(
            core_rules=KNOWLEDGE_DIR / "core_rules.md",
            gallery_prompts=KNOWLEDGE_DIR / "gallery_prompts.jsonl",
        )
        if index.build_report["per_source"]["ours"] == 0:
            self.skipTest("the prompt fixtures are not on this machine")
        report = evaluate(index, load_eval_set(KNOWLEDGE_DIR / "eval_set.jsonl"))
        self.assertEqual(report["outcome"], PASS, report["note"])
        self.assertGreaterEqual(report["recall_at_k"], K.RECALL_FLOOR)
        self.assertEqual(report["controls"]["negative"]["ok"], 2)
        self.assertEqual(report["controls"]["positive"]["ok"], 2)

    def test_dropping_the_fusion_to_bm25_only_costs_recall(self) -> None:
        # The mutation the hybrid exists to justify: with only the lexical
        # channel left, recall must fall and a control must break. If this
        # test goes quiet, nothing is guarding the fusion.
        index = build_index(
            core_rules=KNOWLEDGE_DIR / "core_rules.md",
            gallery_prompts=KNOWLEDGE_DIR / "gallery_prompts.jsonl",
        )
        if index.build_report["per_source"]["ours"] == 0:
            self.skipTest("the prompt fixtures are not on this machine")
        gold = load_eval_set(KNOWLEDGE_DIR / "eval_set.jsonl")
        full = evaluate(index, gold)
        original = K.FUSION_CHANNELS
        try:
            K.FUSION_CHANNELS = ("bm25",)
            lexical = evaluate(index, gold)
        finally:
            K.FUSION_CHANNELS = original
        self.assertEqual(full["outcome"], PASS)
        self.assertEqual(lexical["outcome"], FAIL)
        self.assertLess(lexical["recall_at_k"], full["recall_at_k"])
        self.assertGreater(lexical["violations"], full["violations"])


if __name__ == "__main__":
    unittest.main()
