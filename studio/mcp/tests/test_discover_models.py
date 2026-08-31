"""Опрос индексов: ловит ли он новое и молчит ли он о шуме.

Сеть сюда не заходит — каждый канал получает свой ответ инъекцией (правило Т4).
Ожидаемые значения — литералы (правило Т2).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "discover_models",
    Path(__file__).resolve().parents[3] / "scripts" / "discover_models.py",
)
assert SPEC and SPEC.loader
discover = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(discover)

FAMILIES = {"minimax", "flux", "wan", "kling"}


def hf(model_id: str, task: str = "text-to-video") -> dict:
    return {"id": model_id, "task": task}


class FamilyReading(unittest.TestCase):
    def test_the_uploader_is_not_the_family(self):
        self.assertEqual(discover.family_of("beike97/MiniMax-H3"), "minimax")

    def test_packaging_tails_are_not_a_family(self):
        self.assertEqual(discover.family_of("someone/wan-2.2-GGUF"), "wan")

    def test_a_name_that_is_only_packaging_yields_nothing(self):
        self.assertEqual(discover.family_of("someone/fp8-int8"), "")

    def test_a_run_together_version_still_finds_its_family(self):
        """`flux2` пишет комьюнити, `flux-2` — вендор. Это одно семейство."""
        self.assertEqual(discover.as_known("flux2", FAMILIES), "flux")

    def test_trimming_digits_never_invents_a_family(self):
        self.assertEqual(discover.as_known("nemotron3", FAMILIES), "")

    def test_a_name_of_only_digits_does_not_match_everything(self):
        self.assertEqual(discover.as_known("2024", FAMILIES), "")


class VersionStem(unittest.TestCase):
    def test_quantisations_of_one_model_share_a_stem(self):
        left = discover.version_stem("a/MiniMax-H3-fp8")
        right = discover.version_stem("b/MiniMax-H3-Turbo-Lora-Pruned")
        self.assertEqual(left, right)
        self.assertEqual(left, "minimax h3")

    def test_two_versions_of_one_family_do_not_merge(self):
        """Точка — часть номера версии, а не разделитель: 2.3 и 2.5 разные."""
        self.assertNotEqual(
            discover.version_stem("a/LTX-2.3-FP8"), discover.version_stem("b/LTX-2.5-MLX")
        )

    def test_a_dated_edit_keeps_its_date(self):
        self.assertEqual(
            discover.version_stem("x/Qwen-Image-Edit-2511-INT4"), "qwen image edit 2511"
        )


class Splitting(unittest.TestCase):
    def test_a_known_family_lands_in_versions_not_in_families(self):
        got = discover.split_findings([hf("a/MiniMax-H3"), hf("b/MiniMax-H3-fp8")], FAMILIES, set())
        self.assertEqual(got["new_families"], [])
        self.assertEqual([r["stem"] for r in got["new_versions"]], ["minimax h3"])

    def test_a_model_already_in_the_base_is_not_a_finding(self):
        got = discover.split_findings([hf("a/MiniMax-H3")], FAMILIES, {"minimax-h3"})
        self.assertEqual(got["new_versions"], [])

    def test_one_uploader_is_not_a_new_family(self):
        """Личная LoRA лежит под одним аккаунтом; настоящую модель заливают многие."""
        rows = [hf("solo/aros-VelvetLynx"), hf("solo/aros-MidnightVesper")]
        got = discover.split_findings(rows, FAMILIES, set())
        self.assertEqual(got["new_families"], [])

    def test_two_uploaders_are(self):
        rows = [hf("one/SenseNova-U1"), hf("two/SenseNova-U1-fp8")]
        got = discover.split_findings(rows, FAMILIES, set())
        self.assertEqual([r["family"] for r in got["new_families"]], ["sensenova"])

    def test_a_new_version_needs_no_second_uploader(self):
        """Семейство уже подтверждено вендором — ждать второго загрузчика значит
        пропустить релиз на сутки."""
        got = discover.split_findings([hf("solo/MiniMax-H3")], FAMILIES, set())
        self.assertEqual(len(got["new_versions"]), 1)

    def test_findings_are_ordered_by_how_loud_they_are(self):
        rows = [hf("a/Krea-2"), hf("b/Krea-2")] + [hf(f"u{i}/SenseNova-U1") for i in range(4)]
        got = discover.split_findings(rows, FAMILIES, set())
        self.assertEqual([r["family"] for r in got["new_families"]], ["sensenova", "krea"])


class Channels(unittest.TestCase):
    def test_a_refused_index_is_reported_not_swallowed(self):
        def refuse(url: str):
            return "HTTP 403", None

        got = discover.poll_hugging_face(refuse)
        self.assertEqual(got["answered"], 0)
        self.assertEqual(got["candidates"], [])
        self.assertEqual(len(got["refused"]), len(discover.HF_TASKS))

    def test_a_dead_index_makes_the_run_could_not_measure(self):
        """Р1: ни один канал не ответил — это третий исход, а не «нового нет»."""
        dead = {"answered": 0, "refused": ["всё"], "candidates": [], "clients": []}
        code = discover.report(dead, dead, {"new_families": [], "new_versions": []})
        self.assertEqual(code, 2)

    def test_a_live_index_with_nothing_new_is_still_a_pass(self):
        alive = {"answered": 1, "refused": [], "candidates": [], "clients": []}
        code = discover.report(alive, alive, {"new_families": [], "new_versions": []})
        self.assertEqual(code, 0)

    def test_pypi_reports_a_version_per_client(self):
        def answer(url: str):
            return "ok", {"info": {"version": "9.9.9"}}

        got = discover.poll_pypi(answer)
        self.assertEqual(got["answered"], len(discover.PYPI_CLIENTS))
        self.assertEqual(got["clients"][0]["version"], "9.9.9")


if __name__ == "__main__":
    unittest.main()
