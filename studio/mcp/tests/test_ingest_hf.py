"""Канал HuggingFace: лицензия, шум обсуждений, три исхода.

Сеть за инъекцией (правило Т4), ожидаемое — литералы (Т2).
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "ingest_hf", Path(__file__).resolve().parents[3] / "scripts" / "ingest_hf.py"
)
assert SPEC and SPEC.loader
hf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hf)


class LicenceReading(unittest.TestCase):
    def test_a_territorial_carve_out_is_flagged(self):
        текст = "Excluded Territories means the European Union and the United States."
        self.assertIn("территориальное ограничение: права даны не везде", hf.license_flags(текст))

    def test_research_only_is_flagged(self):
        self.assertIn("только для исследований", hf.license_flags("For research purposes only."))

    def test_a_permissive_licence_raises_nothing(self):
        """Негативный контроль: прибор обязан уметь молчать."""
        apache = "Licensed under the Apache License, Version 2.0. You may obtain a copy."
        self.assertEqual(hf.license_flags(apache), [])

    def test_a_ban_on_training_other_models_is_flagged(self):
        текст = "You may not use the Outputs to improve any other artificial intelligence model."
        self.assertIn("запрет учить другие модели на выходах", hf.license_flags(текст))


class LicenceFiles(unittest.TestCase):
    def дерево(self, *paths: str):
        def get(url: str):
            if url.endswith("/tree/main"):
                return "ok", json.dumps([{"path": p} for p in paths]).encode()
            return "HTTP 404", b""

        return get

    def test_a_licence_with_an_unguessable_name_is_still_found(self):
        """Список имён провалился на первой живой модели; ищем по дереву."""
        got = hf.license_paths("x/y", self.дерево("LTX-Video-Open-Weights-License-0.X.txt"))
        self.assertEqual(got, ["LTX-Video-Open-Weights-License-0.X.txt"])

    def test_a_dependency_licence_is_not_the_models_licence(self):
        got = hf.license_paths("x/y", self.дерево("LICENSE", "third_party/dep/LICENSE"))
        self.assertEqual(got, ["LICENSE"])

    def test_a_repository_without_a_licence_file_yields_nothing(self):
        self.assertEqual(hf.license_paths("x/y", self.дерево("README.md")), [])


class DisagreeingLicences(unittest.TestCase):
    def test_files_with_different_clauses_are_called_out(self):
        """LTX-Video: два веса research-only, два нет — один файл соврёт."""
        licences = [
            {"file": "a", "flags": ["только для исследований"], "chars": 1},
            {"file": "b", "flags": [], "chars": 1},
        ]
        self.assertTrue(hf.licences_disagree(licences))

    def test_files_that_agree_are_not(self):
        licences = [{"file": "a", "flags": [], "chars": 1}, {"file": "b", "flags": [], "chars": 1}]
        self.assertFalse(hf.licences_disagree(licences))

    def test_a_single_file_never_disagrees_with_itself(self):
        self.assertFalse(hf.licences_disagree([{"file": "a", "flags": ["x"], "chars": 1}]))


class TroubleFilter(unittest.TestCase):
    def test_a_defect_report_is_kept(self):
        payload = {"discussions": [{"num": 1, "title": "Crash in Base Sampler", "status": "open"}]}
        self.assertEqual(len(hf.troubles(payload)), 1)

    def test_a_chinese_defect_report_is_kept_too(self):
        """Половина полезных тредов у китайских моделей — не по-английски."""
        payload = {"discussions": [{"num": 2, "title": "眨眼问题", "status": "open"}]}
        self.assertEqual(len(hf.troubles(payload)), 1)

    def test_a_job_ad_is_not_a_defect_report(self):
        payload = {"discussions": [{"num": 3, "title": "【招聘】 全球开源生态", "status": "open"}]}
        self.assertEqual(hf.troubles(payload), [])


class Verdict(unittest.TestCase):
    def test_a_model_whose_card_will_not_open_is_the_third_outcome(self):
        got = hf.survey("x/y", lambda url: ("HTTP 401", b""))
        self.assertEqual(got["outcome"], "не смогли")

    def test_naming_no_model_is_could_not_measure(self):
        self.assertEqual(hf.report([]), 2)

    def test_one_unreadable_model_out_of_two_is_not_a_pass(self):
        rows = [{"model_id": "a", "outcome": "не смогли", "note": "401"}]
        self.assertEqual(hf.report(rows), 2)


if __name__ == "__main__":
    unittest.main()
