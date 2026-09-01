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
        найдено, счёт = hf.наблюдения_модели("x/y", get=lambda u: ("HTTP 403", b""))
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
