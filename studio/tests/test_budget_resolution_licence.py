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


class МеньшеВсегоЗамен(unittest.TestCase):
    """Потолок превышен — меняется НАИМЕНЬШЕЕ, а не всё (интеграция 2026-10-15).

    Перебор закрывает одна замена — берётся та, что теряет меньше мест в
    порядке доводов; не закрывает ни одна — жадно по «экономия на место».
    """

    def _шаги(self):
        в = оп("генерация_видео")
        л = оп("липсинк")
        видео = [
            кандидат(model="в1", cost=цена(2.0)),
            кандидат(model="в2", cost=цена(1.0)),
            кандидат(model="в3", cost=цена(0.5)),
        ]
        липсинк = [
            кандидат(model="л1", cost=цена(1.5)),
            кандидат(model="л2", cost=цена(1.4)),
            кандидат(model="л3", cost=цена(0.2)),
        ]
        return [(в, видео[0]), (л, липсинк[0])], {в.name: видео, л.name: липсинк}

    def test_одна_замена_с_меньшей_потерей(self) -> None:
        шаги, найдено = self._шаги()
        # Сумма 3.5, потолок 2.6: перебор 0.9 закрывают в1->в2 (1 место),
        # в1->в3 (2 места) и л1->л3 (2 места). Берётся ближняя.
        замены = pn.подобрать_под_потолок(шаги, найдено, 2.6)
        self.assertEqual({"генерация_видео": "в2"}, {ш: c.model for ш, c in замены.items()})

    def test_одной_мало_жадно_по_экономии_на_место(self) -> None:
        шаги, найдено = self._шаги()
        # Потолок 1.0: нужно отдать 2.5. Каждый шаг доходит до самого дешёвого.
        замены = pn.подобрать_под_потолок(шаги, найдено, 1.0)
        self.assertEqual(
            {"генерация_видео": "в3", "липсинк": "л3"}, {ш: c.model for ш, c in замены.items()}
        )

    def test_одной_заменой_а_не_двумя(self) -> None:
        """Лучшая «экономия на место» (в1->в2, 0.5 за место) перебор 0.9 не
        закрывает и потянула бы вторую замену; л1->л4 закрывает его одна."""
        в = оп("генерация_видео")
        л = оп("липсинк")
        видео = [кандидат(model="в1", cost=цена(2.0)), кандидат(model="в2", cost=цена(1.5))]
        липсинк = [
            кандидат(model="л1", cost=цена(1.5)),
            кандидат(model="л2", cost=цена(1.45)),
            кандидат(model="л3", cost=цена(1.4)),
            кандидат(model="л4", cost=цена(0.55)),
        ]
        замены = pn.подобрать_под_потолок(
            [(в, видео[0]), (л, липсинк[0])], {в.name: видео, л.name: липсинк}, 2.6
        )
        self.assertEqual({"липсинк": "л4"}, {ш: c.model for ш, c in замены.items()})

    def test_в_потолке_менять_нечего(self) -> None:
        шаги, найдено = self._шаги()
        self.assertEqual({}, pn.подобрать_под_потолок(шаги, найдено, 3.5))

    def test_другая_полоса_не_берётся(self) -> None:
        л = оп("липсинк")
        измерен = кандидат(model="измерен", applicability=2, cost=цена(1.5))
        немой = кандидат(model="немой", cost=цена(0.2))
        self.assertEqual({}, pn.подобрать_под_потолок([(л, измерен)], {л.name: [измерен, немой]}, 1.0))


class ЛицензияСемьиВарианту(unittest.TestCase):
    """Вариант без своей лицензии наследует ОСТОРОЖНОСТЬ семьи, а не факт."""

    ФАКТЫ = [
        факт("fam-h3", "license_excluded_territories", "EU, UK, South Korea, USA", "https://huggingface.co/x/LICENSE"),
        факт("fam-h3", "produces_outputs", "видео"),
        факт("fam-h3", "accepts_inputs", "текст"),
        факт("fam-h3-max-t2v", "produces_outputs", "видео"),
        факт("fam-h3-max-t2v", "accepts_inputs", "текст"),
        факт("fam-h3-max-t2v", "requires_inputs", "текст"),
    ]

    def _варианты(self, юрисдикции=None, факты=None):
        from studio.factindex import FactIndex

        найдены = pn.candidates_for(оп("генерация_видео"), FactIndex(facts=факты or self.ФАКТЫ), юрисдикции=юрисдикции)
        return {c.model: c for c in найдены}

    def test_вариант_отодвинут_и_сказано_честно(self) -> None:
        вариант = self._варианты()["fam-h3-max-t2v"]
        self.assertTrue(вариант.territory_unasked)
        self.assertEqual(
            "лицензия СЕМЬИ fam-h3 исключает территории EU, KR, UK, US — где работает заказчик?; "
            "лицензия для варианта fam-h3-max-t2v в базе НЕ записана — перенесена осторожность "
            "семьи, а не факт (https://huggingface.co/x/LICENSE)",
            вариант.licence_risk,
        )
        self.assertFalse(вариант.licence_blocked)

    def test_названная_исключённая_юрисдикция_держит_вариант_позади(self) -> None:
        self.assertTrue(self._варианты(("US",))["fam-h3-max-t2v"].territory_unasked)
        self.assertFalse(self._варианты(("BR",))["fam-h3-max-t2v"].territory_unasked)

    def test_своя_лицензия_варианта_переноса_нет(self) -> None:
        факты = self.ФАКТЫ + [факт("fam-h3-max-t2v", "license", "Apache-2.0")]
        вариант = self._варианты(факты=факты)["fam-h3-max-t2v"]
        self.assertFalse(вариант.territory_unasked)
        self.assertNotIn("СЕМЬИ", вариант.licence_risk)


class ЖивыеБрифы(unittest.TestCase):
    """Три брифа проверки — на живой базе, ответ целиком литералами."""

    def test_бойцы_15_долларов(self) -> None:
        итог = pn.plan(
            "40s 9:16 1080x1920 ad with two consistent realistic fighters, "
            "English VO with lipsync, budget $15",
            full=True,
        )
        # С интеграцией третьего круга (2026-10-15) «consistent fighters» —
        # кадры по референсу: кадр -> правка по референсу -> оживление.
        # Сверхразрешение (`drct-super-resolution`) правкой по референсу не
        # считается (чужая работа).
        self.assertEqual(
            [
                ("генерация_изображения", "gpt-image-2.5-flare"),
                ("редактирование_изображения", "flux-3-edit"),
                ("озвучка", "eleven_v3"),
                ("оживление", "wan-3.0-i2v"),
                ("липсинк", "sync-lipsync"),
            ],
            [(ш["step"], ш["chosen"]["model"]) for ш in итог["steps"]],
        )
        self.assertTrue(итог["resolution_carry"].startswith("кадр 1080x1920 пронесён от шага оживление (wan-3.0-i2v:"))
        self.assertTrue(
            итог["resolution_carry"].endswith(
                "через липсинк (sync-lipsync): о разрешении их выхода база "
                "молчит, и принято, что проход кадр сохраняет — допущение, не замер"
            )
        )
        видео = итог["steps"][3]
        self.assertEqual("minimax-h3", видео["licence_alternative"]["model"])
        self.assertIn(
            "условия API-площадки — другой документ: в базе НЕ записаны",
            видео["licence_alternative"]["licence_risk"],
        )
        self.assertEqual("юрисдикция", итог["question"]["axis"])
        # Круг 4: wan-3.0-i2v «$0.05 480p, $0.10 720p, or $0.20 1080p» — 1080p
        # стоит 0.20 usd/с (8.00 за 40 с), а не 0.05 (было 4.16 за весь план).
        self.assertEqual((10.16, "годно"), (итог["pipeline_price"]["смета"]["usd"], итог["pipeline_price"]["outcome"]))
        self.assertNotIn("optimised", итог["pipeline_price"])
        self.assertEqual("latentsync", итог["steps"][4]["cheaper_same_rank"]["model"])

    def test_липсинк_3_доллара(self) -> None:
        итог = pn.plan("lipsync 30 s, budget $3")
        # Провал НАСТОЯЩЕГО шага (липсинк) старше открытого вопроса о видео.
        self.assertEqual(("fail", "валидатор_отверг"), (итог["outcome"], итог["reason"]))
        оптимум = итог["pipeline_price"]["optimised"]
        # ПОТОЛОК — НЕ «САМОЕ ДЕШЁВОЕ» (2026-10-15): перебор 0.58 usd закрывает
        # одна замена липсинка; озвучка и видео остаются прежними.
        # eleven_v3 теперь по маршруту вендора: ≈450 знаков × 0.08 usd / 1000.
        self.assertEqual(
            [("липсинк", "sync-lipsync", "latentsync")],
            [(о["step"], о["from"], о["to"]) for о in оптимум["swaps"]],
        )
        self.assertEqual(
            [("озвучка", "eleven_v3"), ("генерация_видео", "wan-3.0-prime-t2v"), ("липсинк", "latentsync")],
            [(ш["step"], ш["chosen"]["model"]) for ш in итог["steps"]],
        )
        self.assertEqual((3.576, 2.276), (оптимум["before_usd"], оптимум["after_usd"]))
        self.assertEqual("total 3.58 usd is over the clip ceiling 3 usd", оптимум["why_en"])
        self.assertEqual("годно", итог["pipeline_price"]["outcome"])
        self.assertIn(
            "re-selected for the budget: sync-lipsync 1.50 -> latentsync 0.20 usd; traded off: "
            "sync-lipsync: измерено, но есть плохая новость, строк применимости 3 (за 2, против 1) "
            "-> latentsync: измерено, но есть плохая новость, строк применимости 4 (за 1, против 3)",
            итог["summary"],
        )
        self.assertIn("BUDGET OPTIMISED (total 3.58 usd is over the clip ceiling 3 usd): 3.58 -> 2.28 usd", итог["summary"])

    def test_липсинк_заказано_самое_дешёвое_меняет_всё(self) -> None:
        """Обратное направление: «cheapest» — каждый шаг к минимуму своей полосы."""
        итог = pn.plan("lipsync 30 s, budget $3, cheapest")
        оптимум = итог["pipeline_price"]["optimised"]
        self.assertEqual(
            [
                ("озвучка", "eleven_v3", "chatterbox-multilingual"),
                ("генерация_видео", "wan-3.0-prime-t2v", "xai-grok-imagine-video-v1.5-lite-t2v"),
                ("липсинк", "sync-lipsync", "latentsync"),
            ],
            [(о["step"], о["from"], о["to"]) for о in оптимум["swaps"]],
        )
        self.assertEqual((3.576, 0.8112), (оптимум["before_usd"], оптимум["after_usd"]))

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
        # Цена ролика — только шесть кадров (6 × 0.03612); условный апскейл 0.48 — рядом.
        self.assertEqual(0.22, итог["pipeline_price"]["смета"]["usd"])
        self.assertEqual(
            # Шесть кадров — шесть прогонов апскейла (2026-10-15): 6 × 0.08.
            [("апскейл_изображения", "topaz-upscale-image-transparent", 0.48)],
            [(у["step"], у["model"], у["usd"]) for у in итог["pipeline_price"]["conditional_steps"]],
        )


if __name__ == "__main__":
    unittest.main()
