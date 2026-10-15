"""Бюджет ролика оптимизируется, разрешение проносится, лицензия не умолчание (2026-10-15).

Три находки независимой проверки плана на трёх брифах:

* «40s 9:16 1080x1920 ad with two consistent realistic fighters, English VO
  with lipsync, budget $15» — `minimax-h3` посчитана в 1440p, а апскейл за
  11.52 usd всё равно дописан: модель ЛИПСИНКА о разрешении молчит. И видео-
  моделью по умолчанию стояла `minimax-h3`, чья лицензия весов исключает EU,
  UK, US и KR, — вопрос о юрисдикции задавался ПОСЛЕ выбора;
* «lipsync 30 s, budget $3» — `sync-lipsync` 1.50 usd, сумма 3.98 «ПРЕВЫШЕН»,
  а `latentsync` 0.20 в той же полосе доводов лежала соседом;
* «8 second 1080p video with native audio, cheapest» — план не строился вовсе
  (вопрос «видео уже снято?»), а `veo-3.1-lite` (родной 1080p со звуком,
  0.08 usd/с -> 0.64 usd) не была даже соседом.

Т2: ожидаемое — литералы. Т4: сети нет. Первые классы — на собранных здесь
фактах; последний — на ЖИВОЙ базе и именно этих брифах: он краснеет, когда
база меняет ответ, и это нарочно — литерал сверяется глазами.
Т1: мутации — `scripts/mutate_planner.py`, раздел 2026-10-15.
"""

from __future__ import annotations

import unittest

from studio import planner as pn
from studio import pricing
from studio.selfrag.facts import Fact


def факт(model: str, attribute: str, value: str, url: str = "") -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=url or f"https://example.invalid/{model}",
        tier="vendor",
        stated_on="2026-10-01",
    )


def оп(имя: str) -> pn.Operation:
    return next(о for о in pn.OPERATIONS if о.name == имя)


def цена(usd: float, resolution: int | None = None, formula: str = "") -> pn.Стоимость:
    o = pricing.Option(usd, "", resolution, formula or f"{usd:g} usd")
    return pn.Стоимость((o,), o, o, "")


def кандидат(**поля) -> pn.Candidate:
    база = dict(model="м", evidence=(), applicability=0, capability=0, unresolved=0, price="")
    база.update(поля)
    return pn.Candidate(**база)


class РазрешениеСквозьПроход(unittest.TestCase):
    """№9: молчание модели-прохода о кадре не становится платным апскейлом."""

    КАДР = (1080, 1920)

    def test_кадр_тарифа_проносится_сквозь_молчащий_липсинк(self) -> None:
        выбор = [
            (оп("генерация_видео"), кандидат(model="gen", cost=цена(5.2, 1440))),
            (оп("липсинк"), кандидат(model="lip")),
        ]
        почему, условно, пронесено = pn.решить_апскейл(выбор, self.КАДР, [])
        self.assertEqual(("", False), (почему, условно))
        self.assertEqual(
            "кадр 1080x1920 пронесён от шага генерация_видео (gen: тариф шага посчитан в 1440p) "
            "через липсинк (lip): о разрешении их выхода база молчит, и принято, что проход "
            "кадр сохраняет — допущение, не замер",
            пронесено,
        )

    def test_оживление_кадр_не_проносит_оно_его_сочиняет(self) -> None:
        # Оживлению на вход нужен КАДР, а не видео: разрешение ролика решает
        # модель оживления, и большой ключевой кадр за неё не отвечает.
        выбор = [
            (оп("генерация_изображения"), кандидат(model="img", cost=цена(0.1, 2160))),
            (оп("оживление"), кандидат(model="i2v")),
        ]
        почему, условно, пронесено = pn.решить_апскейл(выбор, self.КАДР, [])
        self.assertTrue(почему.startswith("УСЛОВНО: в брифе заказан кадр 1080x1920, а модель шага оживление (i2v)"))
        self.assertEqual((True, ""), (условно, пронесено))

    def test_источник_молчит_апскейл_условный(self) -> None:
        выбор = [(оп("генерация_изображения"), кандидат(model="img"))]
        почему, условно, пронесено = pn.решить_апскейл(выбор, self.КАДР, [])
        self.assertTrue(почему.startswith("УСЛОВНО: в брифе заказан кадр 1080x1920"))
        self.assertEqual((True, ""), (условно, пронесено))

    def test_источник_ниже_по_записи_апскейл_безусловный(self) -> None:
        выбор = [
            (оп("генерация_видео"), кандидат(model="gen", cost=цена(0.48, 720))),
            (оп("липсинк"), кандидат(model="lip")),
        ]
        почему, условно, _ = pn.решить_апскейл(выбор, self.КАДР, [])
        self.assertEqual(
            "в брифе заказан кадр 1080x1920, а у модели шага генерация_видео (gen) он ниже "
            "по записи — тариф шага посчитан в 720p — ниже 1080p",
            почему,
        )
        self.assertFalse(условно)

    def test_проход_с_записанным_пределом_ниже_решает_сам(self) -> None:
        выбор = [
            (оп("генерация_видео"), кандидат(model="gen", cost=цена(5.2, 1440))),
            (оп("липсинк"), кандидат(model="lip")),
        ]
        факты = [факт("lip", "max_resolution", "720p")]
        почему, условно, _ = pn.решить_апскейл(выбор, self.КАДР, факты)
        self.assertIn("липсинк (lip)", почему)
        self.assertFalse(условно)


class ЛицензияНеУмолчание(unittest.TestCase):
    """№13: исключающая территории лицензия при неназванной юрисдикции — сосед."""

    def test_исключающая_уступает_молчащей(self) -> None:
        h3 = кандидат(model="h3", applicability=6, territory_unasked=True)
        другая = кандидат(model="другая")
        self.assertEqual(["другая", "h3"], [c.model for c in sorted([h3, другая], key=pn.by_evidence)])
        self.assertIs(h3, pn.лучший_вне_исключений(другая, [другая, h3]))

    def test_названная_юрисдикция_поле_снимает(self) -> None:
        факты = [
            факт("h3", "license_excluded_territories", "EU, UK, South Korea, USA"),
            факт("h3", "produces_outputs", "видео"),
            факт("h3", "accepts_inputs", "текст"),
            факт("h3", "requires_inputs", "текст"),
        ]
        from studio.factindex import FactIndex

        индекс = FactIndex(facts=факты)
        без = pn.candidates_for(оп("генерация_видео"), индекс)
        с_ней = pn.candidates_for(оп("генерация_видео"), индекс, юрисдикции=("BR",))
        self.assertEqual([("h3", True)], [(c.model, c.territory_unasked) for c in без])
        self.assertEqual([("h3", False)], [(c.model, c.territory_unasked) for c in с_ней])

    def test_веса_и_api_разные_документы(self) -> None:
        веса = "https://huggingface.co/x/LICENSE"
        свои = [
            факт("h3", "license_excluded_territories", "EU, UK, South Korea, USA", веса),
            факт("h3", "price_per_second_usd", "$0.08"),
        ]
        self.assertEqual(
            "лицензия исключает территории EU, KR, UK, US — где работает заказчик?; "
            "это лицензия ВЕСОВ (самостоятельный запуск); условия API-площадки — другой "
            "документ: в базе НЕ записаны — переносятся ли на API исключения весов, неизвестно",
            pn.риск_лицензии(свои, None),
        )
        с_условиями = свои + [факт("h3", "api_terms", "no territorial limits", "https://t.invalid")]
        self.assertIn(
            "условия API-площадки — другой документ: api_terms = «no territorial limits» (https://t.invalid)",
            pn.риск_лицензии(с_условиями, None),
        )


class ПолосаБюджета(unittest.TestCase):
    """№10: перевыбор под бюджет — внутри полосы доводов и по полной цене."""

    def test_та_же_полоса_дешевле_берётся(self) -> None:
        sync = кандидат(model="sync", applicability=3, against=1, cost=цена(1.5))
        latent = кандидат(model="latent", applicability=4, against=3, cost=цена(0.2))
        self.assertIs(latent, pn.дешевле_в_полосе(sync, [sync, latent], оп("липсинк")))
        self.assertEqual(
            {"step": "липсинк", "from": "sync", "to": "latent", "from_usd": 1.5, "to_usd": 0.2, "saved_usd": 1.3},
            {к: в for к, в in pn.обмен("липсинк", sync, latent).items() if к != "traded"},
        )

    def test_другой_знак_измеренного_не_та_полоса(self) -> None:
        измерен = кандидат(model="измерен", applicability=2, cost=цена(1.5))
        немой = кандидат(model="немой", cost=цена(0.2))
        self.assertIsNone(pn.дешевле_в_полосе(измерен, [измерен, немой], оп("липсинк")))

    def test_ниже_кадра_не_та_полоса(self) -> None:
        родной = кандидат(model="родной", cost=цена(0.64, 1080))
        мелкий = кандидат(model="мелкий", cost=цена(0.48, 720), below_frame=True)
        self.assertIsNone(pn.дешевле_в_полосе(родной, [родной, мелкий], оп("генерация_видео")))
        self.assertEqual(["родной", "мелкий"], [c.model for c in sorted([мелкий, родной], key=pn.by_evidence)])

    def test_неполная_цена_не_берётся(self) -> None:
        выбран = кандидат(model="в", cost=цена(2.0))
        прогон = кандидат(
            model="п",
            cost=цена(0.49, None, "0.49 usd за прогон (сколько секунд даёт прогон — не записано) = 0.49 usd"),
        )
        мп = кандидат(model="мп", cost=цена(0.01, None, "1 кадр(ов) × 1 Мп × 0.002 usd = 0.00 usd"))
        self.assertIsNone(pn.дешевле_в_полосе(выбран, [выбран, прогон], оп("генерация_видео")))
        self.assertIsNone(pn.дешевле_в_полосе(выбран, [выбран, мп], оп("озвучка")))
        self.assertIs(мп, pn.дешевле_в_полосе(выбран, [выбран, мп], оп("генерация_изображения")))

    def test_самое_дешёвое_названо(self) -> None:
        self.assertTrue(pn.дешевле_всего_заказано("8 second 1080p video with native audio, cheapest"))
        self.assertTrue(pn.дешевле_всего_заказано("самый дешёвый вариант ролика"))
        self.assertFalse(pn.дешевле_всего_заказано("lipsync 30 s, budget $3"))


class ЖивыеБрифы(unittest.TestCase):
    """Три брифа проверки — на живой базе, ответ целиком литералами."""

    def test_бойцы_15_долларов(self) -> None:
        итог = pn.plan(
            "40s 9:16 1080x1920 ad with two consistent realistic fighters, "
            "English VO with lipsync, budget $15",
            full=True,
        )
        self.assertEqual(
            [("озвучка", "eleven_v3"), ("генерация_видео", "wan-3.0-prime-t2v"), ("липсинк", "sync-lipsync")],
            [(ш["step"], ш["chosen"]["model"]) for ш in итог["steps"]],
        )
        self.assertEqual(
            "кадр 1080x1920 пронесён от шага генерация_видео (wan-3.0-prime-t2v: тариф шага "
            "посчитан в 1080p) через липсинк (sync-lipsync): о разрешении их выхода база "
            "молчит, и принято, что проход кадр сохраняет — допущение, не замер",
            итог["resolution_carry"],
        )
        видео = итог["steps"][1]
        self.assertEqual("minimax-h3", видео["licence_alternative"]["model"])
        self.assertIn(
            "условия API-площадки — другой документ: в базе НЕ записаны",
            видео["licence_alternative"]["licence_risk"],
        )
        self.assertEqual("юрисдикция", итог["question"]["axis"])
        self.assertEqual((13.31, "годно"), (итог["pipeline_price"]["смета"]["usd"], итог["pipeline_price"]["outcome"]))
        self.assertNotIn("optimised", итог["pipeline_price"])
        self.assertEqual("latentsync", итог["steps"][2]["cheaper_same_rank"]["model"])

    def test_липсинк_3_доллара(self) -> None:
        итог = pn.plan("lipsync 30 s, budget $3")
        # Провал НАСТОЯЩЕГО шага (липсинк) старше открытого вопроса о видео.
        self.assertEqual(("fail", "валидатор_отверг"), (итог["outcome"], итог["reason"]))
        оптимум = итог["pipeline_price"]["optimised"]
        self.assertEqual(
            [
                ("озвучка", "eleven_v3", "chatterbox-multilingual"),
                ("генерация_видео", "wan-3.0-prime-t2v", "xai-grok-imagine-video-v1.5-lite-t2v"),
                ("липсинк", "sync-lipsync", "latentsync"),
            ],
            [(о["step"], о["from"], о["to"]) for о in оптимум["swaps"]],
        )
        self.assertEqual((3.621, 0.8112), (оптимум["before_usd"], оптимум["after_usd"]))
        self.assertEqual("total 3.62 usd is over the clip ceiling 3 usd", оптимум["why_en"])
        self.assertEqual("годно", итог["pipeline_price"]["outcome"])
        self.assertIn(
            "re-selected for the budget: sync-lipsync 1.50 -> latentsync 0.20 usd; traded off: "
            "sync-lipsync: измерено, но есть плохая новость, строк применимости 3 (за 2, против 1) "
            "-> latentsync: измерено, но есть плохая новость, строк применимости 4 (за 1, против 3)",
            итог["summary"],
        )
        self.assertIn("BUDGET OPTIMISED (total 3.62 usd is over the clip ceiling 3 usd): 3.62 -> 0.81 usd", итог["summary"])

    def test_нативный_звук_1080p_самое_дешёвое(self) -> None:
        итог = pn.plan("8 second 1080p video with native audio, cheapest")
        # Вопроса «видео уже снято?» нет: нативный звук бывает только у
        # сгенерированного. Вопрос о юрисдикции есть: измеренная `minimax-h3`
        # отодвинута лицензией и встала бы первой вне исключённых территорий.
        self.assertEqual("юрисдикция", итог["question"]["axis"])
        self.assertEqual("minimax-h3", итог["steps"][0]["licence_alternative"]["model"])
        self.assertEqual(
            [("видео_со_звуком", "veo-3.1-lite-t2v")],
            [(ш["step"], ш["chosen"]["model"]) for ш in итог["steps"]],
        )
        self.assertEqual(0.64, итог["pipeline_price"]["смета"]["usd"])
        оптимум = итог["pipeline_price"]["optimised"]
        self.assertEqual("the cheapest was asked", оптимум["why_en"])
        self.assertEqual(
            [("видео_со_звуком", "flux-3-t2v", 2.32, "veo-3.1-lite-t2v", 0.64)],
            [(о["step"], о["from"], о["from_usd"], о["to"], о["to_usd"]) for о in оптимум["swaps"]],
        )

    def test_ключевые_кадры_апскейл_условный_и_вне_вердикта(self) -> None:
        итог = pn.plan("6 фотореалистичных ключевых кадров 1080x1920, бюджет 1 доллар")
        self.assertEqual(
            [("генерация_изображения", None), ("апскейл_изображения", True)],
            [(ш["step"], ш.get("conditional")) for ш in итог["steps"]],
        )
        self.assertEqual("годно", итог["pipeline_price"]["outcome"])
        self.assertEqual(
            [("апскейл_изображения", "topaz-upscale-image-transparent", 0.08)],
            [(у["step"], у["model"], у["usd"]) for у in итог["pipeline_price"]["conditional_steps"]],
        )


if __name__ == "__main__":
    unittest.main()
