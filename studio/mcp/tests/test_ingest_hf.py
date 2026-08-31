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


#: Настоящая лицензия — это тысячи символов. Фикстуры добиваются до
#: правдоподобной длины нейтральным текстом: короче порога прибор обязан
#: говорить «обрывок», и он прав.
ОБВЯЗКА = (
    " This Agreement sets out the terms under which the Licensor grants rights"
    " to the Licensee, including definitions, scope, and termination clauses."
) * 4


class LicenceReading(unittest.TestCase):
    def test_a_territorial_carve_out_is_flagged(self):
        текст = "Excluded Territories means the European Union and the United States." + ОБВЯЗКА
        self.assertIn("территориальное ограничение: права даны не везде", hf.license_flags(текст))

    def test_research_only_is_flagged(self):
        self.assertIn(
            "только для исследований", hf.license_flags("For research purposes only." + ОБВЯЗКА)
        )

    def test_a_permissive_licence_raises_nothing(self):
        """Негативный контроль: прибор обязан уметь молчать."""
        apache = "Licensed under the Apache License, Version 2.0. You may obtain a copy." + ОБВЯЗКА
        self.assertEqual(hf.license_flags(apache), [])

    def test_a_ban_on_training_other_models_is_flagged(self):
        текст = (
            "You may not use the Outputs to improve any other artificial intelligence model."
            + ОБВЯЗКА
        )
        self.assertIn("запрет учить другие модели на выходах", hf.license_flags(текст))


class ForeignLicence(unittest.TestCase):
    """Р1 в этом приборе: «оговорок нет» и «прочитать не смогли» — разное.

    Поймано на IndexTeam/IndexTTS-2 2026-08-31: `LICENSE.txt` несёт
    некоммерческую оговорку, `LICENSE_ZH.txt` — та же лицензия по-китайски.
    Детектор читает только по-английски и молча выдал по ней «оговорок не
    нашли», после чего прибор объявил РАСХОЖДЕНИЕ между весами. Отсутствие
    свидетельства выдавалось за свидетельство отсутствия, да ещё и за находку.
    """

    def test_a_chinese_licence_is_not_reported_as_clean(self):
        китайская = "本许可协议规定了模型的使用条款和条件，包括商业使用的限制条款。" * 20
        self.assertEqual(
            hf.license_flags(китайская), [hf.CANNOT_READ + ": язык не тот, оговорки не проверены"]
        )

    def test_an_english_licence_with_a_few_dashes_is_still_readable(self):
        английская = "This licence — see § 3 — is for research purposes only. " * 12
        self.assertIn("только для исследований", hf.license_flags(английская))

    def test_an_unread_file_does_not_create_a_disagreement(self):
        licences = [
            {"file": "LICENSE.txt", "flags": ["некоммерческая оговорка"], "chars": 1},
            {"file": "LICENSE_ZH.txt", "flags": [hf.CANNOT_READ + ": язык"], "chars": 1},
        ]
        self.assertFalse(hf.licences_disagree(licences))

    def test_a_real_disagreement_still_fires_beside_an_unread_file(self):
        """Непрочитанный файл глушит ложную тревогу, а не настоящую."""
        licences = [
            {"file": "a", "flags": ["только для исследований"], "chars": 1},
            {"file": "b", "flags": [], "chars": 1},
            {"file": "zh", "flags": [hf.CANNOT_READ + ": язык"], "chars": 1},
        ]
        self.assertTrue(hf.licences_disagree(licences))

    def test_a_bilingual_licence_is_unreadable_too(self):
        """Настоящие файлы двуязычные: половина строк английские, половина нет.

        На чисто китайском тексте порог не проверяется — там доля 1.0, и
        сработает любое значение. Различает прибор именно смесь.
        """
        смесь = "Article 3. Commercial use. 第三条 商业使用受到限制，" * 6
        доля = sum(1 for ch in смесь if ord(ch) > 127) / len(смесь)
        self.assertGreater(доля, 0.2)
        self.assertLess(доля, 0.9)
        self.assertTrue(hf.license_flags(смесь)[0].startswith(hf.CANNOT_READ))

    def test_an_empty_file_is_unreadable_not_clean(self):
        self.assertTrue(hf.license_flags("")[0].startswith(hf.CANNOT_READ))

    def test_a_git_lfs_pointer_is_not_a_clean_licence(self):
        """131 символ метаданных вместо PDF на 137 КБ, который мы не видели."""
        указатель = (
            "version https://git-lfs.github.com/spec/v1\n"
            "oid sha256:b82a2805162bde714a4eb27b9063c4fc\nsize 137711\n"
        )
        метки = hf.license_flags(указатель)
        self.assertTrue(метки[0].startswith(hf.CANNOT_READ))
        self.assertIn("git-lfs", метки[0])

    def test_a_short_snippet_is_a_fragment_not_a_licence(self):
        """Обрывок без всяких LFS: сто символов лицензией не бывают."""
        обрывок = "Copyright 2026. Some rights reserved. See website for terms."
        метки = hf.license_flags(обрывок)
        self.assertTrue(метки[0].startswith(hf.CANNOT_READ))
        self.assertIn("обрывок", метки[0])

    def test_a_short_permissive_snippet_is_not_reported_as_clean(self):
        """Самая опасная форма: короткий текст без оговорок читается как «чисто»."""
        self.assertNotEqual(hf.license_flags("MIT License. Permission is granted."), [])

    def test_the_reason_is_named_and_not_borrowed_from_another_cause(self):
        """Указатель — это не «язык не тот»: третий исход обязан быть честным."""
        указатель = "version https://git-lfs.github.com/spec/v1\noid sha256:aa\nsize 1\n"
        self.assertNotIn("язык", hf.license_flags(указатель)[0])


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


class WhatTheBaseAlreadyHas(unittest.TestCase):
    """Точное совпадение и просто похожее имя — РАЗНОЕ.

    `omnigen2` и `omnihuman-1` делят четыре первые буквы и не имеют друг к
    другу отношения: разные вендоры, разные задачи. Печатать их как «уже в
    базе» значит подсказывать неверно (поймано на живой выдаче 2026-08-31).
    """

    def store(self, *models):
        from studio.selfrag.facts import Fact, FactStore

        return FactStore(
            [
                Fact(
                    model=m,
                    attribute="max_seconds",
                    value="5",
                    source_url="https://example.test/x",
                    tier="vendor",
                    stated_on="2026-08-31",
                )
                for m in models
            ]
        )

    def test_a_neighbour_is_not_reported_as_the_same_model(self):
        got = hf.already_known("OmniGen2/OmniGen2", self.store("omnihuman-1", "omniweaving"))
        self.assertEqual(got["exact"], [])
        self.assertEqual(got["neighbours"], ["omnihuman-1", "omniweaving"])

    def test_an_exact_match_is_reported_as_one(self):
        got = hf.already_known("krea/Krea-2", self.store("krea-2"))
        self.assertEqual(got["exact"], ["krea-2"])

    def test_attributes_come_from_the_exact_match_only(self):
        """Иначе свойства чужой модели выглядят как уже записанные про эту."""
        got = hf.already_known("OmniGen2/OmniGen2", self.store("omnihuman-1"))
        self.assertEqual(got["attributes"], [])


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
