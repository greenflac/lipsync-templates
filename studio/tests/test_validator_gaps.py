"""Находки независимого валидатора 2026-10-14 (G1–G11): каждая — литералом (Т2).

Сеть не нужна (Т4): где можно, база — синтетические факты; где проверяется
поведение продукта на живой базе, проверяется ФОРМА ответа, а не то, какую
модель база сегодня ставит первой.
"""

from __future__ import annotations

import json
import math
import unittest
from datetime import date

import studio.planner as pn
from studio import pipeline as pl
from studio import pricing
from studio.selfrag.facts import Fact

СЕГОДНЯ = date(2026, 10, 14)


def факт(model: str, attribute: str, value: str, tier: str = "vendor", url: str = "") -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=url or f"https://example.invalid/{model}",
        tier=tier,
        stated_on="2026-10-01",
    )


def оп(имя: str) -> pn.Operation:
    return next(о for о in pn.OPERATIONS if о.name == имя)


def имена(операции) -> list[str]:
    return [о.name for о in операции]


def замкнуто(бриф: str) -> list[str]:
    операции, _ = pn.замкнуть(pn.derive(бриф), pn.inputs_of(бриф), бриф)
    return имена(операции)


VEO = (
    "Standard $0.40/s at 720p and 1080p, $0.60/s at 4k; Fast $0.10/s (720p), $0.12/s (1080p), "
    "$0.30/s (4k); Lite $0.05/s (720p), $0.08/s (1080p), 4k not supported — paid tier, video "
    "with audio, USD per second"
)
LUMA = "5s: $0.15 at 540p, $0.30 at 720p, $1.20 at 1080p; HDR 5s $0.60 (720p) / $2.40 (1080p)"
LATENTSYNC = "$0.2 for videos up to 40 seconds, then $0.005 per second of output video"


class G1РоликБезГенерации(unittest.TestCase):
    """Ролик заказан — значит, его кто-то делает; цена ролика без видео — не цена ролика."""

    def test_сгенерированные_перебивки_это_генерация_видео(self) -> None:
        self.assertEqual(
            ["озвучка", "генерация_видео", "музыка"],
            замкнуто(
                "45-second product demo video for a smart water bottle, 16:9 1080p, generated "
                "b-roll shots of the product, voiceover in Spanish, background music"
            ),
        )

    def test_ролик_без_исходника_дописывает_генерацию_догадкой(self) -> None:
        бриф = "make a 30s video ad of a sneaker, voiceover in English, 9:16"
        операции, дописаны = pn.замкнуть(pn.derive(бриф), pn.inputs_of(бриф), бриф)
        self.assertEqual(["озвучка", "генерация_видео"], имена(операции))
        # Догадка помечена артефактом — и потому вопрос «видео уже снято?» остаётся.
        self.assertEqual({"генерация_видео": "видео"}, дописаны)
        вопрос = pn.вопрос_по_плану(бриф, операции, pn.inputs_of(бриф), дописаны)
        self.assertEqual("есть_ли_исходное_видео", вопрос.ось)

    def test_апскейл_моего_видео_это_апскейл_видео(self) -> None:
        self.assertEqual(["апскейл"], замкнуто("upscale my video to 4k"))
        # Негативный контроль: без слова о видео апскейл — картинки.
        self.assertEqual(["апскейл_изображения"], имена(pn.derive("апскейл фото до 4K")))

    def test_перевод_готового_видео_это_дубляж_и_губы(self) -> None:
        self.assertEqual(["дубляж", "липсинк"], замкнуто("перевести готовое видео на испанский"))
        # За кадром губ нет — липсинк не дописывается.
        self.assertNotIn(
            "липсинк", замкнуто("перевести готовое видео на испанский закадровым голосом")
        )

    def test_кадры_для_ролика_не_заказ_ролика(self) -> None:
        self.assertEqual(
            ["генерация_изображения"], замкнуто("ключевые кадры фотореалистичные для MMA ролика")
        )

    def test_нет_шага_с_видео_нет_цены_ролика(self) -> None:
        музыка = pn.Candidate(
            "м",
            (),
            0,
            1,
            0,
            "",
            cost=pn.Стоимость(
                (pricing.Option(0.45, "", None, "45 с"),),
                pricing.Option(0.45, "", None, "45 с"),
                pricing.Option(0.45, "", None, "45 с"),
                "",
            ),
        )
        итог = pn.смета_ролика({"note": "n"}, [(оп("музыка"), музыка)], 45.0, None, (), True)
        self.assertNotIn("за_ролик", итог)
        self.assertEqual("не смогли", итог["outcome"])
        self.assertIn("ЦЕНЫ РОЛИКА НЕТ", итог["note"])


class G2ТаблицаСтавок(unittest.TestCase):
    def test_veo_тарифы_и_разрешения_раздельно(self) -> None:
        ставки = pricing.rates(VEO, "price_per_second")
        self.assertEqual(
            [
                ("standard", (720, 1080), 0.4),
                ("standard", (2160,), 0.6),
                ("fast", (720,), 0.1),
                ("fast", (1080,), 0.12),
                ("fast", (2160,), 0.3),
                ("lite", (720,), 0.05),
                ("lite", (1080,), 0.08),
            ],
            [(r.tier, r.resolutions, r.amount) for r in ставки],
        )

    def test_veo_40_секунд_1080p_по_тарифам(self) -> None:
        варианты = pricing.estimate(
            pricing.rates(VEO, "price_per_second"), pricing.Need(seconds=40, resolution=1080)
        )
        self.assertEqual(
            [("standard", 16.0), ("fast", 4.8), ("lite", 3.2)],
            [(o.tier, o.usd) for o in варианты],
        )

    def test_luma_прогон_пять_секунд_по_нужному_разрешению(self) -> None:
        варианты = pricing.estimate(
            pricing.rates(LUMA, "price_per_run_usd"), pricing.Need(seconds=40, resolution=1080)
        )
        self.assertEqual([("", 9.6), ("hdr", 19.2)], [(o.tier, o.usd) for o in варианты])

    def test_фиксированная_цена_за_ролик_и_доплата(self) -> None:
        ставки = pricing.rates(LATENTSYNC, "price")
        self.assertEqual(
            [(0.2, "run", 40.0, 0.005)],
            [(r.amount, r.per, r.run_seconds, r.over_per_second) for r in ставки],
        )
        self.assertEqual(
            [3.0], [o.usd for o in pricing.estimate(ставки, pricing.Need(seconds=600))]
        )
        self.assertEqual([0.2], [o.usd for o in pricing.estimate(ставки, pricing.Need(seconds=30))])

    def test_пары_со_звуком_и_без_по_легенде(self) -> None:
        ставки = pricing.rates(
            "720p 0.045/0.060, 1080p 0.090/0.115 (no audio / with audio)", "price_per_second_usd"
        )
        self.assertEqual(
            [
                (0.045, (720,), False),
                (0.06, (720,), True),
                (0.09, (1080,), False),
                (0.115, (1080,), True),
            ],
            [(r.amount, r.resolutions, r.audio) for r in ставки],
        )

    def test_ноль_не_цена(self) -> None:
        self.assertEqual(
            [],
            pricing.estimate(
                pricing.rates("$0", "price_per_character_usd"), pricing.Need(chars=1000)
            ),
        )

    def test_за_знак_в_тысячу_раз_мельче_тысячи_знаков(self) -> None:
        варианты = pricing.estimate(
            pricing.rates("$0.00018", "price_per_character_usd_via_elevenlabs"),
            pricing.Need(chars=1000),
        )
        self.assertEqual([0.18], [o.usd for o in варианты])

    def test_кредиты_не_становятся_долларами(self) -> None:
        self.assertEqual(
            [],
            pricing.estimate(
                pricing.rates("40 credits/s with audio, 20 credits/s without", "price_per_second"),
                pricing.Need(seconds=10),
            ),
        )

    def test_нет_заказанного_кадра_считается_по_наибольшему(self) -> None:
        варианты = pricing.estimate(
            pricing.rates("$0.06 per second (720p)", "price_per_second_usd"),
            pricing.Need(seconds=10, resolution=4320),
        )
        self.assertEqual([(0.6, 720)], [(o.usd, o.resolution) for o in варианты])


#: Два шага под одним брифом: дубляж за минуту и липсинк за секунду.
ДВА_ШАГА: tuple[Fact, ...] = (
    факт("д-dubbing", "architecture", "dubbing of the source speech into another language"),
    факт("д-dubbing", "price_per_minute", "$1.2"),
    факт("д-dubbing", "license", "commercial use allowed"),
    факт("л-lipsync", "architecture", "lipsync talking-head"),
    факт("л-lipsync", "positioning", "lip-sync of an existing talking-head video to new speech"),
    факт("л-lipsync", "price_per_second_usd", "0.02"),
    факт("л-lipsync", "license", "apache-2.0"),
)


class G7БюджетНаВесьРолик(unittest.TestCase):
    def test_знаков_в_секунде_речи(self) -> None:
        нужда = pn.нужда_шага(оп("озвучка"), pn.dur.просят("ролик 40 секунд"), None)
        self.assertEqual(600.0, нужда.chars)

    def test_никто_с_ценой_не_влез_цена_порядок_не_решает(self) -> None:
        факты = [
            факт("п-lipsync", "architecture", "lipsync talking-head"),
            факт(
                "п-lipsync",
                "observed_behaviour",
                "lipsync: губы держат синхрон всю реплику",
                "operator",
            ),
            факт("п-lipsync", "price_per_run_usd", "$5 per run"),
            факт("н-lipsync", "architecture", "lipsync talking-head"),
            # Шестой круг: заказываемый ⇔ есть маршрут — модель без цены, но в каталоге.
            факт(
                "н-lipsync",
                "availability",
                "on fal.ai as acme/n-lipsync (video-to-video); listing status public",
                "portal",
                "https://fal.ai/models/acme/n-lipsync",
            ),
        ]
        потолок = pn.Budget(0.1, "usd", ("clip",), "pass", "")
        найдены = pn.candidates_for(оп("липсинк"), pn.FactIndex(facts=факты), budget=потолок)
        # Измеренный, хоть и дороже потолка, — впереди модели, о цене которой молчат:
        # ставка на неизвестное не выдаётся за соблюдение бюджета.
        self.assertEqual(["п-lipsync", "н-lipsync"], [c.model for c in найдены])
        self.assertEqual("дороже бюджета", найдены[0].price_state)
        # Негативный контроль: когда кто-то с ценой влезает — цена снова старший ключ.
        факты.append(факт("н-lipsync", "price_per_run_usd", "$0.05 per run"))
        найдены = pn.candidates_for(оп("липсинк"), pn.FactIndex(facts=факты), budget=потолок)
        self.assertEqual(["н-lipsync", "п-lipsync"], [c.model for c in найдены])

    def test_бюджет_без_за_что_на_весь_ролик(self) -> None:
        b = pn.budget_from("бюджет $10")
        self.assertEqual(("clip",), b.per)

    def test_сумма_шагов_сравнивается_с_бюджетом_ролика(self) -> None:
        итог = pn.plan(
            "из готового ролика сделай липсинк под другой язык, ролик 30 секунд, бюджет $1",
            facts=list(ДВА_ШАГА),
            today=СЕГОДНЯ,
            full=True,
        )
        self.assertEqual(["дубляж", "липсинк"], [ш["step"] for ш in итог["steps"]])
        # Каждый шаг в отдельности в потолок влезает (0.6 < 1)...
        self.assertEqual(
            ["в бюджете", "в бюджете"], [ш["chosen"]["price_state"] for ш in итог["steps"]]
        )
        # ...а ролик целиком — нет: 0.6 + 0.6 = 1.2.
        цена = итог["pipeline_price"]
        self.assertEqual({"usd": 1.2}, цена["за_ролик"])
        self.assertEqual("не годно", цена["outcome"])
        self.assertIn("ПОТОЛОК 1 ПРЕВЫШЕН", цена["note"])
        # Валидатору бюджет ролика как потолок шага не передаётся.
        self.assertNotIn("цена", итог["classes"])

    def test_потолок_на_шаг_только_когда_назван(self) -> None:
        итог = pn.plan(
            "из готового ролика сделай липсинк под другой язык, ролик 30 секунд, бюджет $1 за шаг",
            facts=list(ДВА_ШАГА),
            today=СЕГОДНЯ,
            full=True,
        )
        self.assertEqual(["step"], итог["budget"]["per"])
        self.assertNotIn("НЕ передан", итог["budget"]["note"])

    def test_негодный_потолок_отказ_с_причиной(self) -> None:
        for плохой in (-5.0, math.nan, math.inf):
            итог = pn.plan("сделай липсинк", facts=list(ДВА_ШАГА), budget_usd=плохой)
            self.assertEqual(("fail", "бюджет_не_число"), (итог["outcome"], итог["reason"]), плохой)
            self.assertEqual([], итог["steps"])
        # Ноль — потолок, а не ошибка.
        self.assertNotEqual(
            "бюджет_не_число",
            pn.plan("сделай липсинк", facts=list(ДВА_ШАГА), budget_usd=0.0)["reason"],
        )


class G6НольНеЦена(unittest.TestCase):
    def test_ноль_в_сравнимые_не_идёт(self) -> None:
        сравнимые, прочие = pl.comparable_prices([факт("m", "price_per_second_usd", "$0")])
        self.assertEqual(([], 1), (сравнимые, len(прочие)))


НАТИВНЫЙ: tuple[Fact, ...] = (
    факт("н-video", "max_seconds", "8"),
    факт("н-video", "prompt_skeleton", "subject, action, camera"),
    факт("н-video", "positioning", "8-second videos with native audio and lip-synced dialogue"),
    факт("н-video", "license", "commercial use allowed"),
    факт("т-tts", "architecture", "text-to-speech tts"),
    факт("л-lipsync", "architecture", "lipsync talking-head"),
)


class G3НативныйЗвукИАватар(unittest.TestCase):
    def test_нативный_звук_в_брифе_основной_путь(self) -> None:
        итог = pn.plan(
            "видео 8 секунд с нуля, говорящий ведущий, нативный звук",
            facts=list(НАТИВНЫЙ),
            today=СЕГОДНЯ,
            full=True,
        )
        self.assertEqual(["видео_со_звуком"], [ш["step"] for ш in итог["steps"]])
        self.assertEqual("н-video", итог["steps"][0]["chosen"]["model"])
        self.assertIsNone(итог["question"])
        # Негативный контроль: без слов о нативном звуке — прежняя цепочка.
        прежний = pn.plan(
            "видео 8 секунд с нуля, говорящий ведущий",
            facts=list(НАТИВНЫЙ),
            today=СЕГОДНЯ,
            full=True,
        )
        self.assertEqual(
            ["озвучка", "генерация_видео", "липсинк"], [ш["step"] for ш in прежний["steps"]]
        )

    def test_нативный_звук_узнаётся_словами(self) -> None:
        self.assertTrue(pn.нативный_звук_заказан("видео 40 секунд, нативный звук"))
        self.assertTrue(pn.нативный_звук_заказан("a clip with native audio"))
        self.assertFalse(pn.нативный_звук_заказан("видео 40 секунд, озвучка диктором"))

    def test_нативный_звук_заменяет_цепочку(self) -> None:
        операции = [оп("озвучка"), оп("генерация_видео"), оп("липсинк"), оп("музыка")]
        новые, пометки, заменено = pn.на_нативный_звук(операции, {"озвучка": "аудио"}, frozenset())
        self.assertEqual(["видео_со_звуком", "музыка"], имена(новые))
        self.assertEqual(["озвучка", "генерация_видео", "липсинк"], заменено)
        self.assertEqual(
            {
                "видео_со_звуком": f"{pn.NATIVE_MAIN_NOTE} (вместо: озвучка, генерация_видео, липсинк)"
            },
            пометки,
        )

    def test_нативный_звук_без_генерации_ничего_не_меняет(self) -> None:
        операции = [оп("липсинк")]
        self.assertEqual(
            (операции, {}, []), pn.на_нативный_звук(операции, {}, frozenset({"видео"}))
        )

    def test_оживить_фото_и_озвучить_это_аватар(self) -> None:
        self.assertEqual(
            ["озвучка", "говорящий_аватар"], замкнуто("оживить фото и озвучить по-английски")
        )
        self.assertEqual(
            ["озвучка", "говорящий_аватар"],
            замкнуто("talking photo: make my portrait photo speak an English greeting"),
        )

    def test_аватар_без_снимка_не_берётся(self) -> None:
        # Из текста стоковым лицом говорит другой продукт: снимка он не берёт.
        свои = [
            факт("x-avatar", "requires_inputs", "текст"),
            факт("x-avatar", "accepts_inputs", "текст"),
        ]
        self.assertTrue(pn.чужая_работа(оп("говорящий_аватар"), "x-avatar", свои))
        ведомая = [
            факт("y", "requires_inputs", "аудио, изображение"),
            факт("y", "accepts_inputs", "аудио, изображение, текст"),
        ]
        self.assertFalse(pn.чужая_работа(оп("говорящий_аватар"), "y", ведомая))

    def test_несколько_говорящих_названо(self) -> None:
        self.assertTrue(pn.говорящих_несколько("говорящий анонсер и комментаторы"))
        self.assertFalse(pn.говорящих_несколько("говорящий анонсер"))
        свои = [факт("m", "max_speakers", "up to 2 speakers")]
        self.assertIn("up to 2 speakers", pn.про_говорящих("m", свои))
        self.assertIn("ничего не записано", pn.про_говорящих("m", [факт("m", "license", "mit")]))


class G4ПоколениеИСообщество(unittest.TestCase):
    def test_семья_и_версия(self) -> None:
        self.assertEqual(("flux", (1,)), pn.семья_и_версия("flux.1-dev"))
        self.assertEqual(("flux", (2,)), pn.семья_и_версия("flux-2-pro"))
        self.assertEqual(("omnihuman", (1, 5)), pn.семья_и_версия("omnihuman-1.5"))
        self.assertEqual(("seedance", (2,)), pn.семья_и_версия("seedance-2.0"))
        # Разные продукты одного вендора — разные семьи.
        self.assertEqual(("elevenlabs-dubbing", (2,)), pn.семья_и_версия("elevenlabs-dubbing-v2"))
        self.assertEqual(("elevenlabs-music", (2, 5)), pn.семья_и_версия("elevenlabs-music-v2.5"))
        self.assertIsNone(pn.семья_и_версия("qwen-image"))

    @staticmethod
    def _к(имя: str, применимость: int = 0) -> pn.Candidate:
        return pn.Candidate(имя, (), применимость, 1, 0, "", anchored=1)

    def test_старшая_версия_семьи_вытесняет(self) -> None:
        помечены = pn.поколения(
            [self._к("flux.1-dev", применимость=4), self._к("flux-2-pro")], {}, False
        )
        self.assertEqual(
            ["в той же семье есть новее: flux-2-pro", ""], [c.superseded for c in помечены]
        )
        # Текущее поколение без замера впереди вытесненного с замером.
        помечены.sort(key=pn.by_evidence)
        self.assertEqual(["flux-2-pro", "flux.1-dev"], [c.model for c in помечены])

    def test_строка_базы_о_смене_поколения(self) -> None:
        свои = {
            pn.fold("seedream-4"): [
                факт(
                    "seedream-4", "availability", "Shipping. Seedream 4.5 is the scaled successor."
                )
            ]
        }
        (c,) = pn.поколения([self._к("seedream-4")], свои, False)
        self.assertIn("successor", c.superseded)

    def test_сообщество_последним_если_не_просили(self) -> None:
        (c,) = pn.поколения([self._к("wan-2.2-uncensored-merge-workflow")], {}, False)
        self.assertTrue(c.community)
        (c,) = pn.поколения([self._к("wan-2.2-uncensored-merge-workflow")], {}, True)
        self.assertFalse(c.community)

    def test_дата_выпуска_старше_порога_вытесняет(self) -> None:
        свои = {
            pn.fold("а-старая"): [факт("а-старая", "release_date", "2024-07-01")],
            pn.fold("б-средняя"): [факт("б-средняя", "release_date", "2025-05-15")],
            pn.fold("в-новая"): [факт("в-новая", "release_date", "2026-03-10")],
        }
        помечены = pn.поколения(
            [self._к("а-старая"), self._к("б-средняя"), self._к("в-новая")], свои, False
        )
        # 20 месяцев до новейшей — прошлое поколение, 10 — ещё нет.
        self.assertEqual(
            ["выпущена 2024-07, на 20 мес. раньше новейшего кандидата", "", ""],
            [c.superseded for c in помечены],
        )

    def test_сообщество_уходит_за_продукт(self) -> None:
        найдены = pn.поколения(
            [self._к("x-lora-workflow", применимость=4), self._к("y-product")], {}, False
        )
        найдены.sort(key=pn.by_evidence)
        self.assertEqual(["y-product", "x-lora-workflow"], [c.model for c in найдены])

    def test_ничья_называется_ничьей(self) -> None:
        а, б = self._к("а-модель"), self._к("б-модель")
        self.assertEqual(["б-модель"], pn.ничья(а, [а, б]))
        self.assertTrue(pn.why_not(а, б).startswith("НИЧЬЯ"))


ПРОВАЛ_ТЕКСТА = факт(
    "к-t2i",
    "failure_mode",
    "Chinese text rendering collapses on rare characters: word accuracy drops to 40%",
    "benchmark",
)


class G6ПровалПриЧужомУсловии(unittest.TestCase):
    def test_условие_брифа_решает(self) -> None:
        self.assertFalse(
            pl.in_conditions(ПРОВАЛ_ТЕКСТА, pl.conditions_of_brief("keyframe, no people"))
        )
        self.assertTrue(
            pl.in_conditions(ПРОВАЛ_ТЕКСТА, pl.conditions_of_brief("постер с надписью"))
        )
        # Бриф не подан — отбора нет.
        self.assertTrue(pl.in_conditions(ПРОВАЛ_ТЕКСТА, None))
        общий = факт("к-t2i", "failure_mode", "faces melt in every output", "benchmark")
        self.assertTrue(pl.in_conditions(общий, ()))

    def test_длинный_ролик_по_длительности(self) -> None:
        self.assertEqual(("длинный ролик",), pl.conditions_of_brief("ролик", 45.0))
        self.assertEqual((), pl.conditions_of_brief("ролик", 15.0))

    def test_вердикт_не_валится_чужим_провалом(self) -> None:
        шаг = pl.Step(
            name="генерация_изображения",
            model="к-t2i",
            requirement="text to image, prompt adherence",
            conditions=pl.conditions_of_brief("keyframe for an MMA poster, no people"),
        )
        проба = pl.probe_applicability(шаг, [ПРОВАЛ_ТЕКСТА])
        self.assertNotEqual("fail", проба.outcome)


ТЕРРИТОРИИ = (
    факт("т-i2v", "license_excluded_territories", "EU, UK, South Korea, USA"),
    факт("т-i2v", "license_revenue_threshold", "20 000 000 USD в год"),
    факт(
        "т-i2v",
        "license",
        "open weights, commercial use under conditions",
        url="https://huggingface.co/t",
    ),
)


class G8ТерриторииЛицензии(unittest.TestCase):
    def test_юрисдикция_не_названа_не_смогли(self) -> None:
        проба = pl.probe_licence(pl.Step("оживление", "т-i2v", ""), list(ТЕРРИТОРИИ))
        self.assertEqual((True, "could not measure"), (проба.fired, проба.outcome))
        self.assertIn("исключены территории: EU, KR, UK, US", проба.note)

    def test_исключённая_юрисдикция_не_годно(self) -> None:
        шаг = pl.Step(
            "оживление", "т-i2v", "", jurisdictions=pl.jurisdictions_in("работаем в Германии")
        )
        self.assertEqual("fail", pl.probe_licence(шаг, list(ТЕРРИТОРИИ)).outcome)

    def test_риск_для_заказа_словами(self) -> None:
        self.assertEqual(
            "лицензия исключает территории EU, KR, UK, US — где работает заказчик?; порог выручки "
            "20 000 000 USD в год — выше него нужна отдельная лицензия",
            pn.риск_лицензии(list(ТЕРРИТОРИИ), None),
        )


class G11КраткийОтвет(unittest.TestCase):
    def test_по_умолчанию_краткий_и_это_сказано(self) -> None:
        итог = pn.plan(
            "из готового ролика сделай липсинк под другой язык, ролик 30 секунд, бюджет $1",
            facts=list(ДВА_ШАГА),
            today=СЕГОДНЯ,
        )
        self.assertFalse(итог["full"])
        self.assertEqual(pn.COMPACT_OMITTED, итог["omitted"])
        self.assertNotIn("probes", json.dumps(итог["validator"], ensure_ascii=False))
        self.assertEqual(1, len(итог["steps"][1]["chosen"]["evidence"]))
        полный = pn.plan(
            "из готового ролика сделай липсинк под другой язык, ролик 30 секунд, бюджет $1",
            facts=list(ДВА_ШАГА),
            today=СЕГОДНЯ,
            full=True,
        )
        self.assertLess(1, len(полный["steps"][1]["chosen"]["evidence"]))

    def test_полный_по_флагу(self) -> None:
        итог = pn.plan(
            "из готового ролика сделай липсинк под другой язык, ролик 30 секунд, бюджет $1",
            facts=list(ДВА_ШАГА),
            today=СЕГОДНЯ,
            full=True,
        )
        self.assertTrue(итог["full"])
        self.assertIn("probes", итог["validator"]["steps"][0])

    def test_ставка_за_секунду_названа_только_посекундной(self) -> None:
        итог = pn.в_ролик(
            {"lower_bound": {"usd за second": 0.02, "usd за 1000_chars": 0.1}, "note": "n"},
            None,
            None,
        )
        self.assertIn("это СТАВКА ЗА СЕКУНДУ, а не цена ролика (0.02 usd за second;", итог["note"])
        self.assertNotIn("0.1 usd за 1000_chars;", итог["note"])


if __name__ == "__main__":
    unittest.main()
