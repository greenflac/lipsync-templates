"""Канал HuggingFace: лицензия, шум обсуждений, три исхода.

Сеть за инъекцией (правило Т4), ожидаемое — литералы (Т2).
"""

from __future__ import annotations

import email.message
import importlib.util
import json
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

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


class BehaviourVersusSetup(unittest.TestCase):
    """Проблема установки — не свойство модели, и смешивать их нельзя.

    ИЗМЕРЕНО 2026-08-31 на 49 тредах восьми моделей: 24 (49%) были про то, что
    «не ставится», «не грузится», «нет CUDA». Это настоящие проблемы людей, но
    они не говорят НИЧЕГО о том, как модель себя ведёт, — а за применимостью
    канал и заведён. Оценка выхода поправлена с 4.0 до 3.1 на модель.

    Фикстуры ниже — НАСТОЯЩИЕ заголовки из живых обсуждений, отобранные
    глазами. Правило по ключевым словам разъезжается при первой же правке, если
    его граница не закреплена.
    """

    ПОВЕДЕНИЕ = (
        "发现minimax的小瑕疵：眨眼问题，人物几乎不会眨眼睛",
        "Model hallucinations/Artifacts Issue",
        "Regarding the issues of clarity and character distortion",
        "distilled....screen distortion...unwanted spots appear in the video",
        "LoRA loads without error but has zero conditioning effect on 13B",
        "缺乏不同方向的文字识别能力",
    )
    УСТАНОВКА = (
        "Got an error trying to load from pretrained local files",
        "Issue: SD 3.5L Randomly Stalls on 'Loading VAE Model...' Step",
        "Running on <4gb Vram",
        "Google collab error. pip install does not work.",
        "AssertionError: You do not have CLIP state dict!",
    )

    def разложить(self, заголовки):
        полезные = hf.troubles(
            {"discussions": [{"num": i, "title": t} for i, t in enumerate(заголовки)]}
        )
        установка = hf.troubles(
            {"discussions": [{"num": i, "title": t} for i, t in enumerate(заголовки)]}, setup=True
        )
        return {t["title"] for t in полезные}, {t["title"] for t in установка}

    def test_behaviour_reports_stay_behaviour(self):
        поведение, _ = self.разложить(self.ПОВЕДЕНИЕ)
        self.assertEqual(поведение, set(self.ПОВЕДЕНИЕ))

    def test_a_lora_that_loads_but_does_nothing_is_behaviour(self):
        """Слово «loads» в заголовке не делает отчёт установочным.

        Ровно на этом правило один раз ошиблось: `\bload` съедал настоящий
        отчёт о том, что LoRA грузится и не влияет.
        """
        поведение, _ = self.разложить(
            ("LoRA loads without error but has zero conditioning effect",)
        )
        self.assertEqual(len(поведение), 1)

    def test_setup_problems_go_to_setup(self):
        поведение, установка = self.разложить(self.УСТАНОВКА)
        self.assertEqual(поведение, set())
        self.assertEqual(установка, set(self.УСТАНОВКА))

    def test_the_two_groups_never_overlap(self):
        поведение, установка = self.разложить(self.ПОВЕДЕНИЕ + self.УСТАНОВКА)
        self.assertEqual(поведение & установка, set())


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


class Заявки(unittest.TestCase):
    """Находки как утверждения. Ожидаемое — литералы (Т2)."""

    СТРОКА = {
        "model_id": "coqui/XTTS-v2",
        "outcome": "годно",
        "downloads": 7804353,
        "likes": 3755,
        "license_name": "coqui-public-model-license",
        "licences": [{"file": "LICENSE.txt", "flags": ["некоммерческая оговорка"], "chars": 4014}],
        "observations": [
            {
                "num": 122,
                "title": "GPT2InferenceModel has no attribute",
                "status": "open",
                "author": "kto-to",
                "sign": "провал",
                "attribute": "failure_mode",
                "observation": "On a 3090 at 22kHz the model raises AttributeError mid-generation.",
            }
        ],
        "card_url": "https://huggingface.co/coqui/XTTS-v2",
        "license_url": "https://huggingface.co/coqui/XTTS-v2/tree/main",
    }

    def test_имя_модели_без_аккаунта_и_в_нижнем_регистре(self):
        self.assertEqual({z[0] for z in hf.заявки(self.СТРОКА)}, {"xtts-v2"})

    def test_значение_это_слова_источника_и_ничего_больше(self):
        """Приписанное к значению своё слово уже разводило базу с гейтом."""
        по_атрибуту = {z[1]: z[2] for z in hf.заявки(self.СТРОКА)}
        self.assertEqual(по_атрибуту["license"], "coqui-public-model-license")
        self.assertEqual(
            по_атрибуту["failure_mode"],
            "On a 3090 at 22kHz the model raises AttributeError mid-generation.",
        )

    def test_поле_лицензии_и_прочитанный_текст_это_РАЗНЫЕ_атрибуты(self):
        """Иначе оговорка внутри файла затирает имя лицензии и наоборот."""
        атрибуты = [z[1] for z in hf.заявки(self.СТРОКА)]
        self.assertIn("license", атрибуты)
        self.assertIn("license_restriction", атрибуты)

    def test_принятость_это_порядок_а_не_счётчик(self):
        по_атрибуту = {z[1]: z[2] for z in hf.заявки(self.СТРОКА)}
        self.assertEqual(по_атрибуту["adoption"], "более 1 млн скачиваний")

    def test_ссылка_на_тред_ведёт_в_тред_а_не_на_карточку(self):
        ссылки = {z[1]: z[3] for z in hf.заявки(self.СТРОКА)}
        self.assertEqual(
            ссылки["failure_mode"], "https://huggingface.co/coqui/XTTS-v2/discussions/122"
        )

    def test_без_лицензии_и_без_тредов_остаётся_только_принятость(self):
        голая = dict(self.СТРОКА, license_name="", license="", licences=[], observations=[])
        self.assertEqual([z[1] for z in hf.заявки(голая)], ["adoption"])

    def test_тиры_пробуются_по_очереди_и_их_ровно_три(self):
        """Тир не выбирается каналом: его решает URL внутри advice.record."""
        self.assertEqual(hf.ТИРЫ_ПО_ОЧЕРЕДИ, ("portal", "vendor", "blog"))

    def test_порядок_не_шевелится_от_тика_счётчика(self):
        """Тот самый дефект: два чтения счётчика объявлялись противоречием."""
        self.assertEqual(hf.принятость(1_182_585), hf.принятость(1_182_590))

    def test_края_и_середина_каждого_порядка(self):
        """Фикстуры с обоих краёв диапазона и из середины (Т3)."""
        self.assertEqual(hf.принятость(10_000_000), "более 10 млн скачиваний")
        self.assertEqual(hf.принятость(9_999_999), "более 1 млн скачиваний")
        self.assertEqual(hf.принятость(1_000), "более 1 тыс. скачиваний")
        self.assertEqual(hf.принятость(999), "менее 1 тыс. скачиваний")
        self.assertEqual(hf.принятость(0), "менее 1 тыс. скачиваний")


class ТелоТреда(unittest.TestCase):
    """Наблюдение из тела, а не заголовок. Ожидаемое — литералы (Т2), сети нет (Т4)."""

    ТЕЛО = (
        "Currently testing LTX 2.5 on my RTX 3060 12GB, and the speed is mind-blowing. "
        "Running a basic, default ComfyUI workflow (960x544, T2V) gets me a 15-second "
        "video in just about 5 minutes."
    )

    def test_версия_модели_не_рвётся_точкой(self):
        """Значение — слова источника целиком; «LTX 2.5» не делится пополам."""
        self.assertTrue(hf.наблюдение(self.ТЕЛО).startswith("Currently testing LTX 2.5"))

    def test_нужны_И_условия_И_исход(self):
        self.assertEqual(hf.наблюдение("Has anyone tried this? I get an error."), "")
        self.assertEqual(hf.наблюдение("I ran it on a 4090 with 30 steps at 1280x720."), "")

    def test_наблюдение_с_условиями_и_исходом_берётся(self):
        фраза = "On a 4090 at 1280x720 with 30 steps the mouth desyncs after 6 seconds."
        self.assertEqual(hf.наблюдение(фраза), фраза)

    def test_короче_порога_не_берётся(self):
        """Край диапазона снизу (Т3): 39 символов против порога 40."""
        self.assertEqual(hf.МИН_ДЛИНА_НАБЛЮДЕНИЯ, 40)
        self.assertEqual(hf.наблюдение("On a 3090 it works at 512x512 30 fps"), "")

    def test_стектрейс_не_наблюдение(self):
        """Машинный вывод несёт и условия, и слово про исход, а наблюдения нет."""
        self.assertEqual(
            hf.наблюдение('File "/home/u/ComfyUI/execution.py", line 344, in get_output_data'),
            "",
        )

    def test_предложение_про_чужую_модель_отбрасывается(self):
        """Записать чужое наблюдение под своим именем — худший класс дефекта."""
        фраза = "Seedance 2.5 generates a single native clip up to 30 seconds at 1080x1920."
        self.assertEqual(hf.наблюдение(фраза, "Lightricks/LTX-2.5"), "")
        self.assertTrue(hf.про_чужую_модель(фраза, "Lightricks/LTX-2.5"))

    def test_своё_имя_чужим_не_считается(self):
        фраза = "LTX 2.5 renders 15-second video on a 3060 in about 5 minutes."
        self.assertFalse(hf.про_чужую_модель(фраза, "Lightricks/LTX-2.5"))
        self.assertEqual(hf.наблюдение(фраза, "Lightricks/LTX-2.5"), фраза)

    def test_знак_решает_атрибут_и_имеет_три_исхода(self):
        self.assertEqual(hf.знак("works great and fast, no issues"), "удача")
        self.assertEqual(hf.знак("it fails and the output is garbage"), "провал")
        self.assertEqual(hf.знак("I set the resolution to 720p and pressed run"), "неясно")
        self.assertEqual(hf.знак("works great but it also fails sometimes"), "неясно")

    def test_положительный_отчёт_не_попадает_под_failure_mode(self):
        """Тот самый дефект: «Impressive ... Out of the Box» лежало провалом."""
        self.assertEqual(hf.АТРИБУТ_ПО_ЗНАКУ["удача"], "runs_on")
        self.assertEqual(hf.АТРИБУТ_ПО_ЗНАКУ["провал"], "failure_mode")
        self.assertEqual(hf.АТРИБУТ_ПО_ЗНАКУ["неясно"], "observed_behaviour")

    def test_первое_сообщение_берёт_автора_наблюдения(self):
        payload = {
            "events": [
                {"type": "status-change", "data": {}},
                {"type": "comment", "author": {"name": "LabMike3D"}, "data": {"raw": "текст"}},
                {"type": "comment", "author": {"name": "другой"}, "data": {"raw": "ответ"}},
            ]
        }
        self.assertEqual(hf.первое_сообщение(payload), ("текст", "LabMike3D"))

    def test_тред_без_комментариев_даёт_пустое(self):
        self.assertEqual(hf.первое_сообщение({"events": []}), ("", ""))

    def test_канал_не_ответил_это_третий_исход(self):
        """Р1: «не смогли прочесть» не сворачивается в «наблюдений нет»."""
        найдено, счёт, _ = hf.наблюдения_модели("x/y", get=lambda u: ("HTTP 403", b""))
        self.assertEqual(найдено, [])
        self.assertEqual(счёт, {"канал не ответил": 1})

    def test_вопрос_не_наблюдение_даже_с_условиями(self):
        """Поймано независимым оценщиком: 21 из 27 осуждённых были вопросами."""
        for вопрос in (
            "Can we get the diffusers structured format in place for the 5B model at 720p?",
            "Is there a way to implement this in a comfyui workflow with 30 steps?",
            "How do I run this on a 3090 at 720p with 30 steps?",
            "Anyone got this working on a 4090 at 1280x720 with 30 steps yet?",
        ):
            self.assertEqual(hf.наблюдение(вопрос), "", f"пропущен вопрос: {вопрос}")

    def test_отчёт_о_прогоне_вопросом_не_считается(self):
        """Вторая половина контроля: без неё прошёл бы фильтр, режущий всё."""
        отчёт = "On a 4090 at 1280x720 with 30 steps the mouth desyncs after 6 seconds."
        self.assertEqual(hf.наблюдение(отчёт), отчёт)

    def test_придаточное_с_when_это_не_вопрос(self):
        """Исправление собственной первой редакции: она резала наблюдения."""
        о = "When using the official model, generating a 15-second 720p video takes 3 minutes."
        self.assertEqual(hf.наблюдение(о), о)

    def test_инверсия_без_знака_вопроса_всё_равно_вопрос(self):
        self.assertEqual(hf.наблюдение("Can we get bf16 weights for the 5B model at 720p"), "")

    def test_порог_дословного_совпадает_с_гейтом_ремесла(self):
        """Е1: два места знают одно число — расхождение обязано краснеть.

        Ожидаемое — литерал (Т2), а не импорт из проверяемого модуля.
        """
        import re as _re
        from pathlib import Path as _Path

        текст = (_Path(__file__).resolve().parents[3] / "scripts" / "check_craft.py").read_text(
            encoding="utf-8"
        )
        найдено = _re.search(r"VERBATIM_MAX_WORDS\s*=\s*(\d+)", текст)
        self.assertIsNotNone(найдено)
        self.assertEqual(hf.ДОСЛОВНО_СЛОВ, 15)
        self.assertEqual(int(найдено.group(1)), 15)

    def test_длинная_цитата_не_записывается_вовсе(self):
        """Чужой абзац не режется по слову: обрезок — уже не слова источника."""
        длинное = " ".join(f"слово{i}" for i in range(30))
        строка = dict(
            Заявки.СТРОКА,
            license_name="",
            license="",
            licences=[],
            observations=[
                {
                    "num": 7,
                    "title": "t",
                    "status": "open",
                    "author": "kto-to",
                    "sign": "провал",
                    "attribute": "failure_mode",
                    "observation": длинное,
                }
            ],
        )
        self.assertEqual([z[1] for z in hf.заявки(строка)], ["adoption"])

    def test_короткое_наблюдение_проходит(self):
        """Вторая половина контроля: без неё прошёл бы фильтр, режущий всё."""
        коротко = "On a 3090 at 720p the mouth desyncs after six seconds."
        строка = dict(
            Заявки.СТРОКА,
            license_name="",
            license="",
            licences=[],
            observations=[
                {
                    "num": 7,
                    "title": "t",
                    "status": "open",
                    "author": "kto-to",
                    "sign": "провал",
                    "attribute": "failure_mode",
                    "observation": коротко,
                }
            ],
        )
        по = {z[1]: z[2] for z in hf.заявки(строка)}
        self.assertEqual(по["failure_mode"], коротко)

    def test_ник_автора_никуда_не_пишется(self):
        """Персональные данные не нужны ни одному ответу."""
        строка = dict(
            Заявки.СТРОКА,
            observations=[
                {
                    "num": 7,
                    "title": "t",
                    "status": "open",
                    "author": "dzft3w",
                    "sign": "провал",
                    "attribute": "failure_mode",
                    "observation": "On a 3090 it desyncs after six seconds.",
                }
            ],
        )
        for заявка in hf.заявки(строка):
            self.assertNotIn("dzft3w", " ".join(str(x) for x in заявка))


class ОтветХоста:
    """Заглушка ответа `urlopen`: контекст-менеджер с `read`."""

    def __init__(self, тело: bytes) -> None:
        self._тело = тело

    def __enter__(self) -> "ОтветХоста":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, cap: int) -> bytes:
        return self._тело[:cap]


def отказ(код: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    заголовки = email.message.Message()
    if retry_after is not None:
        заголовки["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://x/", код, "no", заголовки, None)


class Вежливость(unittest.TestCase):
    """Канал не долбит хост: пауза, повтор на «не сейчас», отказ на «нет».

    Сети здесь нет (Т4): `urlopen` и `sleep` подменены, а ожидаемые числа —
    литералы (Т2), а не пересчёт формулы из проверяемого модуля.
    """

    def прогон(self, ответы: list[object]) -> tuple[str, bytes, list[float], int]:
        сны: list[float] = []
        счёт = {"n": 0}

        def urlopen(request: object, timeout: int = 0) -> object:
            счёт["n"] += 1
            ответ = ответы[min(счёт["n"] - 1, len(ответы) - 1)]
            if isinstance(ответ, BaseException):
                raise ответ
            return ответ

        with (
            mock.patch.object(hf.urllib.request, "urlopen", urlopen),
            mock.patch.object(hf.time, "sleep", сны.append),
        ):
            состояние, тело = hf._get("https://x/")
        return состояние, тело, сны, счёт["n"]

    def test_на_429_ждём_и_повторяем(self):
        """Половина контроля «прибор обязан шевельнуться»."""
        состояние, тело, сны, запросов = self.прогон([отказ(429), ОтветХоста(b"ok")])
        self.assertEqual(состояние, "ok")
        self.assertEqual(тело, b"ok")
        self.assertEqual(запросов, 2)
        # 0.2 — пауза отката перед вторым запросом, 0.2 — пауза после удачи.
        self.assertEqual(сны, [0.2, 0.2])

    def test_на_404_не_повторяем(self):
        """Вторая половина контроля: «нет» — это ответ, а не перегрузка (И5)."""
        состояние, _, сны, запросов = self.прогон([отказ(404)])
        self.assertEqual(состояние, "HTTP 404")
        self.assertEqual(запросов, 1)
        self.assertEqual(сны, [])

    def test_откат_растёт_и_повторов_конечное_число(self):
        состояние, _, сны, запросов = self.прогон([отказ(503)])
        self.assertEqual(состояние, "HTTP 503")
        self.assertEqual(запросов, 4)
        self.assertEqual(сны, [0.2, 0.4, 0.8])

    def test_слово_хоста_важнее_нашей_формулы(self):
        _, _, сны, _ = self.прогон([отказ(429, "7"), ОтветХоста(b"ok")])
        self.assertEqual(сны, [7.0, 0.2])

    def test_ожидание_упирается_в_потолок(self):
        _, _, сны, _ = self.прогон([отказ(429, "3600"), ОтветХоста(b"ok")])
        self.assertEqual(сны, [60.0, 0.2])

    def test_неразобранный_retry_after_откатывается_к_формуле(self):
        _, _, сны, _ = self.прогон([отказ(429, "Wed, 21 Oct 2026 07:28:00 GMT"), ОтветХоста(b"ok")])
        self.assertEqual(сны, [0.2, 0.2])

    def test_после_удачи_пауза_есть(self):
        _, _, сны, запросов = self.прогон([ОтветХоста(b"ok")])
        self.assertEqual(запросов, 1)
        self.assertEqual(сны, [0.2])

    def test_обрыв_связи_не_крутится_бесконечно(self):
        состояние, _, _, запросов = self.прогон([TimeoutError()])
        self.assertEqual(состояние, "TimeoutError")
        self.assertEqual(запросов, 1)

    def test_мы_представляемся(self):
        """Анонимный запрос администратору нечем ответить, кроме бана."""
        имена: list[str] = []

        def urlopen(request: urllib.request.Request, timeout: int = 0) -> object:
            имена.append(request.headers.get("User-agent") or "")
            return ОтветХоста(b"ok")

        with (
            mock.patch.object(hf.urllib.request, "urlopen", urlopen),
            mock.patch.object(hf.time, "sleep", lambda _: None),
        ):
            hf._get("https://x/")
        self.assertEqual(len(имена), 1)
        self.assertIn("github.com/greenflac/lipsync-templates", имена[0])


class ЛишнихЗапросовНет(unittest.TestCase):
    """Один заход по модели не спрашивает у хоста одно и то же дважды (Е1)."""

    КАРТОЧКА = json.dumps({"author": "V", "downloads": 1, "likes": 1, "createdAt": "2026-01-01"})
    ЛИСТИНГ = json.dumps({"count": 0, "discussions": []})

    def test_обсуждения_тянутся_один_раз(self):
        спрошено: list[str] = []

        def get(url: str) -> tuple[str, bytes]:
            спрошено.append(url)
            if url.endswith("/discussions"):
                return "ok", self.ЛИСТИНГ.encode()
            if "/api/models/" in url:
                return "ok", self.КАРТОЧКА.encode()
            return "HTTP 404", b""

        hf.survey("V/M", get=get)
        повторы = [u for u in set(спрошено) if спрошено.count(u) > 1]
        self.assertEqual(повторы, [])
        self.assertEqual(спрошено.count("https://huggingface.co/api/models/V/M/discussions"), 1)


class КодИПрикидка(unittest.TestCase):
    """Найдено разбором СОБСТВЕННОГО улова глазами (П3), 2026-09-02.

    Заход по 54 моделям дал пять наблюдений из тел. Я открыл все пять и увидел,
    что три из них — не наблюдения: две строки кода и одна прикидка. Все три
    прошли и фильтр вопроса, и фильтр машинного вывода: они несут условия
    прогона (имя модели, числа, железо) и слово про исход, а рассказывают
    НОЛЬ. Ожидаемое здесь — литералы с того самого прогона (Т2).
    """

    КОД_С_ПРОГОНА = (
        "export MODEL_BASE=FastVideo/FastWan2.2-TI2V-5B-Full-Diffusers and then run training",
        "output_np = (output_np * 0.5 * 127).astype(np.int8) # Adjust the factor (0.5) if needed",
    )
    ПРИКИДКА_С_ПРОГОНА = (
        "If quantized to ~1.5GB, LTX could potentially generate short clips on Snapdragon 865.",
    )
    НАСТОЯЩИЕ_С_ПРОГОНА = (
        "However, I am working with a laptop that has an NVIDIA GTX 1650 (4GB VRAM) and it fails.",
        "Around 10 seconds in, the glitching starts and the output breaks on my RTX 3090.",
    )

    def test_строка_кода_не_наблюдение(self):
        for текст in self.КОД_С_ПРОГОНА:
            self.assertEqual(hf.наблюдение(текст), "", текст)

    def test_прикидка_не_наблюдение(self):
        """«could potentially» — это то, что человек предполагает, а не видел.
        Записанная как observed_behaviour, она становится свидетельством,
        которого не было."""
        for текст in self.ПРИКИДКА_С_ПРОГОНА:
            self.assertEqual(hf.наблюдение(текст), "", текст)

    def test_настоящие_наблюдения_того_же_захода_остались(self):
        """Вторая половина контроля (И5): фильтр, режущий всё, тоже даёт ноль
        мусора, и без этой проверки он неотличим от работающего."""
        for текст in self.НАСТОЯЩИЕ_С_ПРОГОНА:
            self.assertNotEqual(hf.наблюдение(текст), "", текст)

    def test_оговорка_внутри_отчёта_отчётом_и_остаётся(self):
        """`should` у человека, который СКАЗАЛ, что запускал, — оговорка, а не
        прогноз вместо отчёта. Без этого исключения фильтр съедал бы половину
        настоящих отчётов практиков."""
        текст = "I ran it on a 4090 at 720p with 30 steps, and it should work for anyone on 24GB."
        self.assertNotEqual(hf.наблюдение(текст), "")

    def test_обычное_настоящее_время_прикидкой_не_считается(self):
        """Дыра, найденная мутацией: расширь список модальных до `is`/`are` —
        и фильтр съест обычный отчёт в настоящем времени, а тесты этого не
        заметят. Теперь заметят."""
        текст = "The lips are out of sync after 6 seconds at 720p and 24 fps, every render."
        self.assertNotEqual(hf.наблюдение(текст), "")

    def test_команда_с_рассказом_об_исходе_остаётся(self):
        """Признак — не слово «python» в строке, а отсутствие рассказа. Человек,
        назвавший команду И то, что вышло, остаётся свидетелем."""
        текст = "Running it at 512x512 on my 3060 takes 40 seconds per frame and the lips desync."
        self.assertNotEqual(hf.наблюдение(текст), "")


class Скорость(unittest.TestCase):
    """Владелец назвал скорость прямо: агент следит за ценой И СКОРОСТЬЮ.

    ИЗМЕРЕНО 2026-09-02: во всей базе 77 моделей с ценой и ПЯТЬ со скоростью,
    из 477. При этом практики пишут о ней постоянно — в заходе по репозиториям
    Wan попалось «Each iteration for a video of 5 seconds took about 65 minutes
    with my setup», и канал положил это в `observed_behaviour`, то есть туда,
    где ни один вопрос о скорости его не найдёт.

    Ожидаемое — литералы с живого следа (Т2).
    """

    СКОРОСТЬ_НАСТОЯЩАЯ = (
        "Each iteration for a video of 5 seconds took about 65 minutes with my setup.",
        "Rendering a 5s clip takes 40 seconds per frame on a 3060.",
        "The model runs in 12 minutes for a 5-second clip.",
        "I get about 3.5 it/s on a 4090 at 512x512 with 30 steps.",
    )
    НЕ_СКОРОСТЬ = (
        # Длина ролика, а не время прогона.
        "It generates a 5 second video at 720p.",
        # Частота кадров РЕЗУЛЬТАТА — свойство ролика.
        "Output is 24 fps at 720p.",
        # Момент, когда началась беда: секунды идут по ролику, а не по счёту.
        "Around 10 seconds in, the glitching starts and the output breaks on my RTX 3090.",
    )

    def test_отчёт_о_времени_прогона_это_скорость(self):
        for текст in self.СКОРОСТЬ_НАСТОЯЩАЯ:
            self.assertTrue(hf.про_скорость(текст), текст)

    def test_длина_ролика_и_частота_кадров_скоростью_не_считаются(self):
        """Половина контроля, ради которой признак и сужался: чужое число,
        записанное как наша производительность, — это выдуманный факт."""
        for текст in self.НЕ_СКОРОСТЬ:
            self.assertFalse(hf.про_скорость(текст), текст)

    def test_ставка_обходится_без_отдельного_времени(self):
        """`3.5 it/s` — единица сама несёт время. Найдено своей же проверкой:
        первая редакция требовала «число + единица времени» и такую строку
        теряла."""
        self.assertTrue(hf.про_скорость("about 3.5 it/s here"))

    def test_отчёт_о_поломке_остаётся_поломкой(self):
        """Поймано разбором собственного улова глазами (П3), 2026-09-02.

        «I often get videos with this screen distortion... takes 2 minutes»
        уехало в `generation_time`: поломка стала невидимой для вопроса о
        поломках И неверной как скорость. Из трёх находок захода такой была
        одна — треть. У отчёта О ПОЛОМКЕ главное поломка, время в нём —
        обстоятельство.
        """
        текст = (
            "I often get videos with this screen distortion and unwanted spots appear, "
            "and the whole thing takes 2 minutes on my card."
        )
        self.assertTrue(hf.про_скорость(текст), "время в тексте есть")
        self.assertEqual(hf.знак(текст), "провал")
        # Проверяется РЕШЕНИЕ ОБ АТРИБУТЕ, а не две его половины по
        # отдельности: первая редакция теста сверяла именно половины, и
        # мутация «скорость перебивает всё» прошла молча.
        найдено = self._наблюдения(текст)
        self.assertEqual([н["attribute"] for н in найдено], ["failure_mode"])

    def _наблюдения(self, текст: str) -> list:
        тело = {
            "events": [
                {
                    "type": "comment",
                    "data": {"latest": {"raw": текст}, "author": {"name": "кто-то"}},
                }
            ]
        }
        найдено, _, _ = hf.наблюдения_модели(
            "x/y",
            get=lambda url: (
                ("ok", json.dumps({"count": 1, "discussions": [{"num": 1, "title": "t"}]}).encode())
                if url.endswith("/discussions")
                else ("ok", json.dumps(тело).encode())
            ),
        )
        return найдено

    def test_скорость_перебивает_знак(self):
        """Отчёт о времени идёт в `generation_time`, под каким бы знаком ни
        шёл, иначе вопрос о скорости его не найдёт."""
        тело = {
            "events": [
                {
                    "type": "comment",
                    "data": {
                        "latest": {
                            "raw": (
                                "Works great on my 4090, but each iteration for a 5 second "
                                "video took about 65 minutes with my setup."
                            )
                        },
                        "author": {"name": "кто-то"},
                    },
                }
            ]
        }
        найдено, счёт, _ = hf.наблюдения_модели(
            "x/y",
            get=lambda url: (
                ("ok", json.dumps({"count": 1, "discussions": [{"num": 1, "title": "t"}]}).encode())
                if url.endswith("/discussions")
                else ("ok", json.dumps(тело).encode())
            ),
        )
        self.assertEqual([н["attribute"] for н in найдено], ["generation_time"])
        self.assertEqual([н["sign"] for н in найдено], ["удача"], "знак обязан сохраниться")


class СводкаСкорости(unittest.TestCase):
    """Длинный отчёт о скорости пересказывается ЧИСЛАМИ, а не выбрасывается.

    Правило «чужая проза длиннее 15 слов не коммитится» верное, но оно молча
    съедало ровно лучшие отчёты: ИЗМЕРЕНО 2026-09-02, из четырёх найденных за
    заход отчётов о скорости записался ОДИН, три ушли по длине. Числа не
    проза: время прогона, разрешение и карта — факты, и они пересказываются
    нашими словами со ссылкой на источник.

    Ожидаемое — литералы (Т2), тексты сняты с живого следа.
    """

    def test_время_прогона_а_не_длина_ролика(self):
        """Поймано собственной проверкой на первой редакции: сводка выдавала
        «5 seconds» — длину ролика вместо времени счёта."""
        текст = "Each iteration for a video of 5 seconds took about 65 minutes with my setup."
        self.assertEqual(hf.сводка_скорости(текст), "65 minutes")

    def test_условия_прогона_попадают_в_сводку(self):
        текст = (
            "Got this running on a GTX 1650 (4 GB VRAM, laptop GPU) --- turns out you don't "
            "need much VRAM! Test at 768×512 (took ~27 minutes total)."
        )
        self.assertEqual(hf.сводка_скорости(текст), "27 minutes; 768x512; GTX 1650 4 GB")

    def test_ставка_это_уже_факт(self):
        self.assertEqual(
            hf.сводка_скорости("I get about 3.5 it/s on a 4090 at 512x512 with 30 steps."),
            "3.5 it/s; 512x512; 4090",
        )

    def test_память_берётся_только_у_своей_карты(self):
        """СОБСТВЕННАЯ ЛОЖЬ, пойманная чтением записанного (П3, 2026-09-02).

        Сводка выдала «GTX1070 39 GB», потому что в конце того же отчёта
        стояло «you gotta download this whole repo, its around 39 gb» — размер
        РЕПОЗИТОРИЯ. У GTX 1070 восемь гигабайт, и такой строки не написал
        никто: её сочинил канал. Обещание продукта — не врать, значит поле,
        которое нельзя привязать к своему числу, не пишется вовсе.
        """
        текст = (
            "i did this with gtx1070 and if u wonder about perfomance its kinda good "
            "actually, around 4.7 it/s and takes around 1.5 minutes to generate 896x1152 "
            "image. so first of all you gotta download this whole repo, its around 39 gb."
        )
        self.assertEqual(hf.сводка_скорости(текст), "4.7 it/s; 896x1152; GTX1070")

    def test_память_рядом_с_картой_записывается(self):
        """Вторая половина (И5): без неё правило «никогда не писать память»
        тоже дало бы ноль лжи — и ноль пользы."""
        self.assertEqual(
            hf.сводка_скорости("On a 4090 24GB it takes 30 seconds per clip."),
            "30 seconds; 4090 24 GB",
        )

    def test_без_чисел_сводки_нет(self):
        """Половина контроля (И5): отчёт со словом «takes» и без единого числа
        ничего не измеряет, и придумывать за него нельзя."""
        self.assertEqual(hf.сводка_скорости("It takes forever on my card, no idea how long."), "")

    def test_длинный_отчёт_о_скорости_записывается_сводкой(self):
        строка = dict(
            Заявки.СТРОКА,
            observations=[
                {
                    "num": 112,
                    "title": "t",
                    "status": "open",
                    "author": "кто-то",
                    "sign": "неясно",
                    "attribute": "generation_time",
                    "observation": (
                        "Got this running on a GTX 1650 (4 GB VRAM, laptop GPU) --- turns out "
                        "you don't need much VRAM! Test at 768×512 (took ~27 minutes total)."
                    ),
                }
            ],
        )
        по = {z[1]: z[2] for z in hf.заявки(строка)}
        self.assertEqual(по["generation_time"], "27 minutes; 768x512; GTX 1650 4 GB")

    def test_длинное_НЕ_про_скорость_выбрасывается_и_считается(self):
        """Р2: молчаливая потеря — это «ноль нарушений при нуле проверок»
        наоборот. Выброшенное считается и печатается."""
        строка = dict(
            Заявки.СТРОКА,
            observations=[
                {
                    "num": 7,
                    "title": "t",
                    "status": "open",
                    "author": "кто-то",
                    "sign": "провал",
                    "attribute": "failure_mode",
                    "observation": " ".join(["слово"] * 40),
                }
            ],
        )
        заявлено = hf.заявки(строка)
        self.assertNotIn("failure_mode", {z[1] for z in заявлено})
        self.assertEqual(строка["dropped_long"], 1)


class Подводка(unittest.TestCase):
    """Предложение, кончающееся двоеточием, объявляет содержимое, а не несёт его.

    Обе строки попали в базу и обе пришлось смотреть глазами, чтобы увидеть,
    что там ноль: «I got the following error when trying to load the model:» и
    «My local ComfyUI inference workflow uses:». Первая отозвана.
    """

    def test_подводка_наблюдением_не_считается(self):
        for текст in (
            "I got the following error when trying to load the model:",
            "My local ComfyUI inference workflow uses:",
        ):
            self.assertEqual(hf.наблюдение(текст), "", текст)

    def test_двоеточие_внутри_предложения_не_мешает(self):
        """Половина контроля (И5): режется ТОЛЬКО двоеточие в конце, иначе
        правило съело бы настоящие отчёты с пояснением после двоеточия."""
        текст = "I ran the sample as is but it failed with OSError: Cannot load model weights."
        self.assertNotEqual(hf.наблюдение(текст), "")


class ПоломкаБезЖелеза(unittest.TestCase):
    """Отчёт о поломке — факт сам по себе, и требовать к нему железо значит
    выбрасывать то, ради чего канал заведён.

    ИЗМЕРЕНО 2026-09-02 на 30 тредах LTX-Video: правило «условия И исход»
    отвергало 20 предложений, среди которых были настоящие находки. После
    послабления наблюдений стало 9 против 6, и все новые — настоящие, кроме
    одной, о которой ниже.
    """

    НАСТОЯЩИЕ = (
        "The temporal and spatial upscalers fail to load when placed inside models/upscale_models.",
        "I ran the sample as is but it failed with OSError: Cannot load model weights.",
        "Using the base-fp8 workflow, I get a crash in the LTXV Base Sampler node at 0/8.",
        "The custom LoRAs produce zero change in the output and no warnings appear.",
    )
    НЕ_НАБЛЮДЕНИЯ = (
        # Слишком коротко: сообщения нет.
        "It doesn't work.",
        "This is broken.",
        # Похвала вендора: ни поломки, ни прогона.
        "Lightricks has been quietly building the most efficient video generation models.",
    )

    def test_поломка_с_названной_частью_проходит(self):
        for текст in self.НАСТОЯЩИЕ:
            self.assertTrue(hf.поломка_без_железа(текст), текст)

    def test_без_названной_части_и_без_длины_не_проходит(self):
        for текст in self.НЕ_НАБЛЮДЕНИЯ:
            self.assertFalse(hf.поломка_без_железа(текст), текст)

    def test_короткая_жалоба_с_названной_частью_не_проходит(self):
        """Дыра, найденная мутацией: порог 8 слов можно было опустить до трёх,
        и «The model is broken» стало бы наблюдением. Это не отчёт, это
        настроение: не сказано ни что делали, ни что увидели."""
        for текст in ("The model is broken.", "The node crashes.", "Output is garbage."):
            self.assertFalse(hf.поломка_без_железа(текст), текст)

    def test_жалоба_без_названной_части_не_проходит(self):
        """Вторая дыра оттуда же: без требования назвать часть системы
        проходило «I tried everything and it still fails after every attempt» —
        двенадцать слов, а сообщения ноль."""
        текст = "I tried everything and it still fails after every single attempt today."
        self.assertFalse(hf.поломка_без_железа(текст), текст)

    def test_отрицание_поломки_поломкой_не_считается(self):
        """ПОЙМАНО ПЕРВЫМ ЖЕ ЖИВЫМ ПРОГОНОМ после послабления. «...so NOTHING
        WILL BREAK in term of usage» попало в находки: слово поломки внутри
        отрицания. Такая строка не просто мусор — она записывает у модели
        поломку, которой у неё нет.

        Тот же класс независимый оценщик уже ловил в канале Civitai на
        «without any OOM errors»."""
        for текст in (
            "Note that the model is still tagged as both text-to-video and image-to-video "
            "so nothing will break in term of usage.",
            "It ran for an hour without any OOM errors on the 3090 with the model loaded.",
            "The workflow does not crash any more after the node update was applied.",
        ):
            self.assertFalse(hf.поломка_без_железа(текст), текст)

    def test_у_скорости_и_удачи_правило_прежнее(self):
        """Половина контроля (И5): послабление дано ТОЛЬКО отчётам о поломке.
        Отчёт об удаче без железа ничего не сообщает — «works great» не факт."""
        self.assertFalse(hf.поломка_без_железа("It works great with the model and the workflow."))
        self.assertEqual(hf.наблюдение("It works great with the model and the workflow."), "")


class ЧеловекНеПонялЭтоНеПоломка(unittest.TestCase):
    """Поймано чтением собственной выдачи (П3) на живом заходе 2026-09-02.

    В базу ушло `pocket-tts-without-voice-cloning / failure_mode` со словами
    «I failed to find what advantage without-voice-cloning provides over the
    plain pocket-tts model». Знак провала есть, часть системы названа, девять
    слов — все три условия сошлись, и модель получила поломку, которой у неё
    нет. Такая строка хуже мусора: её прочитают как отчёт о дефекте.
    """

    def test_не_нашёл_смысла_это_не_поломка(self) -> None:
        assert not hf.поломка_без_железа(
            "I failed to find what advantage without-voice-cloning provides "
            "over the plain pocket-tts model."
        )

    def test_не_понял_поведения_это_не_поломка(self) -> None:
        assert not hf.поломка_без_железа(
            "I could not understand why the model outputs are different from the demo page"
        )

    def test_не_смог_запустить_это_поломка(self) -> None:
        """Вторая половина (И5): различает не первое лицо, а глагол ПОСЛЕ
        провала. «failed to run» — поломка, «failed to find» — не нашёл, и
        сузить правило до «любое I failed» значит выбросить настоящие отчёты."""
        assert hf.поломка_без_железа(
            "I failed to run the model on my GPU because of an out of memory error today"
        )

    def test_чужой_отчёт_о_поломке_не_задет(self) -> None:
        assert hf.поломка_без_железа(
            "The temporal and spatial upscalers fail to load when placed "
            "inside models/upscale_models"
        )


class ОднаОговоркаОднаСтрока(unittest.TestCase):
    """Поймано там же: у LTX-Video два файла лицензии, оба со словами
    «research only», и за один заход в базу ушли ДВЕ строки с одним ключом.

    Первая догадка («повтор прочитается как подтверждение») проверена и
    неверна: вторая строка вытесняет первую, база отвечает «from 1 source(s)».
    Настоящая потеря — нота: вытеснение оставляет имя ТОЛЬКО последнего файла,
    и знание «оговорка стоит в двух файлах» пропадает, хотя именно оно
    отвечает, нельзя ли обойти лицензию, взяв другой файл."""

    def _строка(self, licences: list[dict]) -> list[tuple[str, str, str, str, str]]:
        row = {
            "model_id": "Lightricks/LTX-Video",
            "card_url": "https://huggingface.co/Lightricks/LTX-Video",
            "license_url": "https://huggingface.co/Lightricks/LTX-Video/tree/main",
            "licences": licences,
            "downloads": 1,
            "likes": 1,
            "threads": [],
        }
        return [з for з in hf.заявки(row) if з[1] == "license_restriction"]

    def test_два_файла_одна_оговорка_одна_строка(self) -> None:
        строки = self._строка(
            [
                {"file": "LICENSE.txt", "chars": 100, "flags": ["только для исследований"]},
                {"file": "LICENSE.md", "chars": 120, "flags": ["только для исследований"]},
            ]
        )
        assert len(строки) == 1, строки

    def test_имена_файлов_не_теряются(self) -> None:
        """Схлопнуть значит потерять, если не сказать, что схлопнули: читающий
        ноту должен видеть, что оговорка стоит в двух файлах, а не в одном."""
        нота = self._строка(
            [
                {"file": "LICENSE.txt", "chars": 100, "flags": ["только для исследований"]},
                {"file": "LICENSE.md", "chars": 120, "flags": ["только для исследований"]},
            ]
        )[0][4]
        assert "LICENSE.txt" in нота and "LICENSE.md" in нота, нота
        assert "2 файлах" in нота, нота

    def test_разные_оговорки_остаются_разными(self) -> None:
        """Вторая половина (И5): схлопывание идёт по ОГОВОРКЕ, а не по модели.
        Две разные оговорки в двух файлах — два разных факта."""
        строки = self._строка(
            [
                {"file": "LICENSE.txt", "chars": 100, "flags": ["только для исследований"]},
                {"file": "OPENRAIL.md", "chars": 120, "flags": ["некоммерческая оговорка"]},
            ]
        )
        assert len(строки) == 2, строки


class УдачаЛовитсяТемиЖеСловами(unittest.TestCase):
    """ИЗМЕРЕНО 2026-09-02: из 314 строк с обсуждений HuggingFace `failure_mode`
    — 221, а «удача» — 6.

    Причина не в том, что практики не хвалят, а в асимметрии прибора: провал
    ловился обычными словами оценки (bad, poor, wrong), удача требовала сильных
    идиом (impressive, works perfectly). Одна и та же речь ловилась с одной
    стороны и пропускалась с другой — а «успешные кейсы» владелец назвал первым
    пунктом предмета мониторинга.
    """

    def test_обычная_похвала_результата_это_удача(self):
        assert hf.знак("I get better result from lightning 8 step lora for upscaling.") == "удача"
        assert hf.знак("its kinda good actually, around 4.7 it/s on my gtx1070") == "удача"

    def test_похвала_не_результату_удачей_не_считается(self):
        """«I am working with a laptop that has a GTX 1650» — слово про работу
        относится к ноутбуку, а не к модели. Без близости к исходу таких строк
        набралось четыре из двадцати одной."""
        assert (
            hf.знак("However, I am working with a laptop that has an NVIDIA GTX 1650 (4GB VRAM).")
            != "удача"
        )

    def test_оценка_вдали_от_исхода_удачей_не_считается(self):
        """Живая строка базы: «the vendor's own good-prompt example is a
        multi-sentence scene description». Слово `good` тут — часть названия
        примера, а не оценка результата прогона, и рядом с ним нет ни одного
        слова об исходе. Без правила близости строка стала бы удачей.

        Мутант «близость не требуется» промолчал ровно здесь: прежний
        отрицательный пример ловился оговоркой, а не близостью, и правило
        оставалось без сторожа."""
        assert (
            hf.знак(
                "English-only prompting, and terse prompts underperform — the vendor's own "
                "good-prompt example is a multi-sentence scene description"
            )
            != "удача"
        )

    def test_похвала_с_оговоркой_это_не_удача(self):
        """«I think it's already better, BUT even slower, a full generation is
        now 1000 seconds» — половина сравнения. Записать удачей значит
        приписать модели успех, о котором автор говорит с оговоркой."""
        assert (
            hf.знак("I think it's already better, but even slower, a full generation is 1000 s")
            != "удача"
        )

    def test_похвала_в_прошедшем_это_не_удача(self):
        """«A few weeks ago I used flux.2 and everything seemed good» — начало
        жалобы на то, что стало хуже."""
        assert (
            hf.знак("A few weeks ago, I used flux.2, and everything seemed good, speed normal")
            != "удача"
        )

    def test_провал_по_прежнему_главнее(self):
        """Вторая половина (И5): расширив удачу, нельзя отобрать у провала его
        строки. Текст с обоими знаками — «неясно», а не «удача»."""
        assert hf.знак("the quality is good but the model crashes on every second run") != "удача"

    def test_безнаковый_текст_остаётся_безнаковым(self):
        """Третий исход не сворачивается ни в первый, ни во второй: «steps 8,
        10; cfgScale 1» — прогон без знака, и он записывается как
        `observed_behaviour`, а не выбрасывается."""
        assert hf.знак("steps 8, 10; cfgScale 1; sampler Euler") == "неясно"
        assert hf.АТРИБУТ_ПО_ЗНАКУ["неясно"] == "observed_behaviour"
