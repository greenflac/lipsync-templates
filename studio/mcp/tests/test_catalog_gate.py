"""Гейт каталога: утечка, три исхода и опрос с подставленной сетью.

Ни один тест не ходит в сеть: `poll_openrouter`/`poll_deepinfra` принимают
`get` первым аргументом, и сюда передаётся функция, возвращающая записанный
ответ (правило Т4). Ни один тест не читает и не пишет настоящие
`studio/knowledge/*.jsonl` — каждый работает во временном каталоге; последний
тест это проверяет байтами.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import check_catalog, poll_catalogs  # noqa: E402

from studio.mcp import catalog  # noqa: E402

#: Сокращённые, но настоящие ответы площадок 2026-08-31.
OPENROUTER_PAYLOAD: dict[str, Any] = {
    "data": [
        {
            "id": "openrouter/auto",
            "canonical_slug": "openrouter/auto",
            "context_length": 2000000,
            "architecture": {"modality": "text->text"},
            "pricing": {"prompt": "-1", "completion": "-1"},
            "description": "Маркетинговая проза, которой не место в репозитории",
        },
        {
            "id": "z-ai/glm-5.3",
            "context_length": 200000,
            "architecture": {"modality": "text->text"},
            "pricing": {"prompt": "0.0000006", "completion": "0.0000021", "overrides": {}},
            "expiration_date": "2098-12-31",
        },
        {
            "id": "z-ai/glm-4.5",
            "context_length": 131072,
            "architecture": {"modality": "text->text"},
            "pricing": {"prompt": "0.00000032", "completion": "0.0000013"},
            "expiration_date": "2026-12-31",
        },
    ]
}

DEEPINFRA_PAYLOAD: list[dict[str, Any]] = [
    {
        "model_name": "allenai/olmOCR-7B-1025",
        "type": "text-generation",
        "reported_type": "text-generation",
        "pricing": {"type": "tokens", "cents_per_input_token": 1.4e-05, "rate_per_flex": 0.5},
        "max_tokens": 16384,
        "replaced_by": "google/gemma-4-31B-it",
        "deprecated": 1778120282,
        "description": "Чужая проза",
    },
    {
        "model_name": "Bria/video_eraser",
        "type": "text-to-video",
        "reported_type": "text-to-video",
        "pricing": {"type": "output_length", "cents_per_output_sec": 5.0},
        "deprecated": None,
    },
    {
        "model_name": "Wan-AI/Wan2.6-T2V",
        "type": "text-to-video",
        "reported_type": "text-to-video",
        "pricing": {"type": "output_length", "cents_per_output_sec": 4.0},
        "deprecated": None,
    },
]


def fake_get(url: str) -> tuple[str, Any]:
    if url == poll_catalogs.OPENROUTER_URL:
        return "ok", OPENROUTER_PAYLOAD
    if url == poll_catalogs.DEEPINFRA_URL:
        return "ok", DEEPINFRA_PAYLOAD
    raise AssertionError(f"тест попытался выйти в сеть: {url}")


def refused_get(url: str) -> tuple[str, Any]:
    return "HTTP 503", None


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )


class Poll(unittest.TestCase):
    def test_openrouter_prices_become_three_separate_fields(self) -> None:
        rows = poll_catalogs.poll_openrouter(fake_get)["records"]
        glm = next(r for r in rows if r["name"] == "z-ai/glm-4.5")
        self.assertEqual(
            glm["prices"],
            [
                {"amount": 3.2e-07, "unit": "usd_per_token", "condition": "prompt"},
                {"amount": 1.3e-06, "unit": "usd_per_token", "condition": "completion"},
            ],
        )

    def test_deepinfra_cents_become_dollars(self) -> None:
        # Единица делится на сто ровно в одном месте: разъехавшаяся единица —
        # это цена, отличающаяся в сто раз, и заметить её потом нечем.
        rows = poll_catalogs.poll_deepinfra(fake_get)["records"]
        olmo = next(r for r in rows if r["name"] == "allenai/olmOCR-7B-1025")
        self.assertEqual(
            olmo["prices"],
            [{"amount": 1.4e-07, "unit": "usd_per_token", "condition": "input token"}],
        )

    def test_deprecation_timestamp_becomes_a_date_and_a_boolean(self) -> None:
        rows = poll_catalogs.poll_deepinfra(fake_get)["records"]
        olmo = next(r for r in rows if r["name"] == "allenai/olmOCR-7B-1025")
        self.assertIs(olmo["deprecated"], True)
        self.assertEqual(olmo["deprecated_on"], "2026-05-07")

    def test_successor_carries_the_marketplace_that_named_it(self) -> None:
        rows = poll_catalogs.poll_deepinfra(fake_get)["records"]
        olmo = next(r for r in rows if r["name"] == "allenai/olmOCR-7B-1025")
        self.assertEqual(
            olmo["replaced_by"], {"name": "google/gemma-4-31B-it", "said_by": "deepinfra"}
        )

    def test_vendor_prose_never_enters_a_record(self) -> None:
        rows = poll_catalogs.poll_openrouter(fake_get)["records"]
        rows += poll_catalogs.poll_deepinfra(fake_get)["records"]
        self.assertEqual([], [r for r in rows if set(r) - catalog.ALLOWED])
        self.assertTrue(all(catalog.validate(r) == [] for r in rows))

    def test_every_polled_record_passes_its_own_schema(self) -> None:
        for record in poll_catalogs.poll_openrouter(fake_get)["records"]:
            self.assertEqual(catalog.validate(record), [], record["name"])

    def test_a_refused_channel_is_a_state_not_a_crash(self) -> None:
        poll = poll_catalogs.poll_openrouter(refused_get)
        self.assertEqual((poll["state"], poll["records"]), ("HTTP 503", []))

    def test_keyed_catalogs_are_recorded_as_could_not_measure(self) -> None:
        channels = poll_catalogs.keyed_channels()
        self.assertEqual(
            sorted(c["catalog"] for c in channels),
            ["artificialanalysis", "replicate", "together", "wavespeed"],
        )
        self.assertEqual({c["state"] for c in channels}, {"could not measure"})
        self.assertEqual({c["reason"] for c in channels}, {"нужен ключ"})

    def test_summary_counts_the_keyed_catalogs_as_unanswered(self) -> None:
        polls = [poll_catalogs.poll_openrouter(fake_get), poll_catalogs.poll_deepinfra(fake_get)]
        records = [r for p in polls for r in p["records"]]
        summary = poll_catalogs.summarise(polls, records)
        self.assertEqual(summary["channels_answered"], 2)
        self.assertEqual(len(summary["keyed_out"]), 4)
        self.assertEqual(summary["checked"], 6)
        self.assertEqual(summary["rejected"], 4)
        self.assertEqual(summary["admitted"], 2)
        self.assertEqual(
            summary["by_rule"], {"router": 1, "forever_date": 1, "deprecated": 1, "edit_op": 1}
        )


class Leak(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.dir = Path(self._dir.name)
        self.catalog = self.dir / "catalog.jsonl"
        self.facts = self.dir / "model_facts.jsonl"
        polls = [poll_catalogs.poll_openrouter(fake_get), poll_catalogs.poll_deepinfra(fake_get)]
        catalog.write_catalog([r for p in polls for r in p["records"]], self.catalog)

    def test_clean_base_passes_with_counts(self) -> None:
        _write(
            self.facts,
            [
                {
                    "model": "wan2.6-t2v",
                    "attribute": "max_seconds",
                    "value": "5",
                    "source_url": "https://huggingface.co/Wan-AI/Wan2.6-T2V",
                    "tier": "vendor",
                }
            ],
        )
        got = catalog.audit(self.catalog, self.facts)
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual((got["checked"], got["rejected"], got["admitted"]), (6, 4, 2))
        self.assertEqual(got["leaks"], [])

    def test_a_deprecated_model_read_from_its_vendor_is_not_a_leak(self) -> None:
        # ИЗМЕРЕНО 2026-08-31: пять имён, помеченных deepinfra как снятые, уже
        # есть в базе ЗАКОННО — из вендорских источников. Совпадение имени само
        # по себе не улика, иначе гейт наказывал бы за правильную работу.
        _write(
            self.facts,
            [
                {
                    "model": "allenai/olmOCR-7B-1025",
                    "attribute": "context",
                    "value": "16384",
                    "source_url": "https://huggingface.co/allenai/olmOCR-7B-1025",
                    "tier": "vendor",
                }
            ],
        )
        self.assertEqual(catalog.audit(self.catalog, self.facts)["outcome"], "pass")

    def test_the_same_model_imported_from_the_catalog_is_a_leak(self) -> None:
        _write(
            self.facts,
            [
                {
                    "model": "allenai/olmOCR-7B-1025",
                    "attribute": "context",
                    "value": "16384",
                    "source_url": "https://api.deepinfra.com/models/list",
                    "tier": "portal",
                }
            ],
        )
        got = catalog.audit(self.catalog, self.facts)
        self.assertEqual(got["outcome"], "fail")
        self.assertEqual([leak["rule"] for leak in got["leaks"]], ["deprecated"])

    def test_a_router_is_a_leak_whatever_the_source(self) -> None:
        _write(
            self.facts,
            [
                {
                    "model": "openrouter/auto",
                    "attribute": "context",
                    "value": "2000000",
                    "source_url": "https://openrouter.ai/docs/models",
                    "tier": "vendor",
                }
            ],
        )
        got = catalog.audit(self.catalog, self.facts)
        self.assertEqual((got["outcome"], got["leaks"][0]["rule"]), ("fail", "router"))

    def test_an_editing_operation_imported_from_the_catalog_is_a_leak(self) -> None:
        _write(
            self.facts,
            [
                {
                    "model": "Bria/video_eraser",
                    "attribute": "max_seconds",
                    "value": "10",
                    "source_url": "https://api.deepinfra.com/models/list",
                    "tier": "portal",
                }
            ],
        )
        self.assertEqual(
            [leak["rule"] for leak in catalog.audit(self.catalog, self.facts)["leaks"]], ["edit_op"]
        )

    def test_a_withdrawn_row_is_not_a_leak(self) -> None:
        _write(
            self.facts,
            [
                {
                    "model": "openrouter/auto",
                    "attribute": "context",
                    "value": "2000000",
                    "source_url": "https://openrouter.ai/api/v1/models",
                    "withdrawn": True,
                }
            ],
        )
        self.assertEqual(catalog.audit(self.catalog, self.facts)["leaks"], [])


class ThirdOutcome(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.dir = Path(self._dir.name)
        self.facts = self.dir / "model_facts.jsonl"
        _write(self.facts, [{"model": "wan2.6-t2v", "source_url": "https://huggingface.co/x"}])

    def test_empty_catalog_is_not_a_pass(self) -> None:
        empty = self.dir / "empty.jsonl"
        empty.write_text("// пусто\n", encoding="utf-8")
        got = catalog.audit(empty, self.facts)
        self.assertEqual((got["outcome"], got["checked"]), ("could not measure", 0))

    def test_missing_catalog_is_not_a_pass(self) -> None:
        got = catalog.audit(self.dir / "нет-такого.jsonl", self.facts)
        self.assertEqual(got["outcome"], "could not measure")

    def test_a_catalog_that_rejects_nothing_measured_nothing(self) -> None:
        path = self.dir / "all_clean.jsonl"
        catalog.write_catalog(
            [r for r in poll_catalogs.poll_deepinfra(fake_get)["records"]][2:], path
        )
        got = catalog.audit(path, self.facts)
        self.assertEqual((got["outcome"], got["rejected"]), ("could not measure", 0))

    def test_a_catalog_that_admits_nothing_is_not_strictness(self) -> None:
        # Гейт, отсекающий всё, проходит «утечек нет» идеально и бесполезен.
        path = self.dir / "all_dirty.jsonl"
        rows = [
            r
            for r in poll_catalogs.poll_deepinfra(fake_get)["records"]
            if r["name"] != "Wan-AI/Wan2.6-T2V"
        ]
        catalog.write_catalog(rows, path)
        got = catalog.audit(path, self.facts)
        self.assertEqual((got["outcome"], got["admitted"]), ("could not measure", 0))

    def test_a_broken_line_is_counted_not_ignored(self) -> None:
        path = self.dir / "broken.jsonl"
        polls = poll_catalogs.poll_deepinfra(fake_get)["records"]
        catalog.write_catalog(polls, path)
        path.write_text(path.read_text(encoding="utf-8") + "{не json\n", encoding="utf-8")
        got = catalog.audit(path, self.facts)
        self.assertEqual(got["unmeasured"], 1)


class KeyedChannelsStayVisible(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "catalog_poll.json"

    def _write(self, channels: list[dict]) -> None:
        self.path.write_text(json.dumps({"keyed_out": channels}), encoding="utf-8")

    def test_all_four_recorded_is_a_pass(self) -> None:
        self._write(poll_catalogs.keyed_channels())
        self.assertEqual(check_catalog.keyed_gap(self.path)["outcome"], "pass")

    def test_a_channel_dropped_from_the_report_is_a_failure(self) -> None:
        self._write([c for c in poll_catalogs.keyed_channels() if c["catalog"] != "wavespeed"])
        got = check_catalog.keyed_gap(self.path)
        self.assertEqual((got["outcome"], got["missing"]), ("fail", ["wavespeed"]))

    def test_a_channel_recorded_as_answered_without_a_key_is_a_failure(self) -> None:
        channels = poll_catalogs.keyed_channels()
        channels[0] = {**channels[0], "state": "ok", "reason": ""}
        self._write(channels)
        self.assertEqual(check_catalog.keyed_gap(self.path)["outcome"], "fail")

    def test_a_missing_report_is_the_third_outcome(self) -> None:
        self.assertEqual(
            check_catalog.keyed_gap(self.path.parent / "нет.json")["outcome"], "could not measure"
        )


class NothingTouchesTheRealBase(unittest.TestCase):
    def test_polling_and_auditing_leave_model_facts_untouched(self) -> None:
        facts = ROOT / "studio" / "knowledge" / "model_facts.jsonl"
        before = hashlib.sha256(facts.read_bytes()).hexdigest()
        polls = [poll_catalogs.poll_openrouter(fake_get), poll_catalogs.poll_deepinfra(fake_get)]
        poll_catalogs.summarise(polls, [r for p in polls for r in p["records"]])
        catalog.audit()
        self.assertEqual(hashlib.sha256(facts.read_bytes()).hexdigest(), before)

    def test_the_catalog_module_cannot_write_to_the_fact_base(self) -> None:
        source = (ROOT / "studio" / "mcp" / "catalog.py").read_text(encoding="utf-8")
        self.assertNotIn("write_text(", source.split("def write_catalog")[0])


if __name__ == "__main__":
    unittest.main()
