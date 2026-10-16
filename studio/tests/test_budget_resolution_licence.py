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
        # С интеграции пятого круга молчание — нота, а не условный шаг.
        self.assertEqual(("", False), (почему, условно))
        self.assertTrue(пронесено.startswith("кадр 1080x1920 не подтверждён: модель шага оживление (i2v)"))

    def test_источник_молчит_апскейла_нет_есть_нота(self) -> None:
        # Интеграция пятого круга (2026-10-15): молчание записи о кадре не
        # дописывает шаг (даже условный) — апскейл только при «ниже по записи».
        выбор = [(оп("генерация_изображения"), кандидат(model="img"))]
        почему, условно, пронесено = pn.решить_апскейл(выбор, self.КАДР, [])
        self.assertEqual(("", False), (почему, условно))
        self.assertTrue(пронесено.startswith("кадр 1080x1920 не подтверждён: модель шага генерация_изображения (img)"))
        self.assertIn("апскейл не дописан", пронесено)

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

    def test_семья_одалживает_только_ниже(self) -> None:
        # Интеграция пятого круга: свои строки варианта молчат, предел семьи
        # записан НИЖЕ заказа — апскейл безусловный и назван по записи семьи.
        выбор = [(оп("генерация_видео"), кандидат(model="wan2.2-ti2v-5b-diffusers"))]
        свои = [факт("wan2.2-ti2v-5b-diffusers", "license", "apache-2.0")]
        ниже = свои + [факт("wan-2.2-ti2v-5b", "max_resolution", "720p")]
        почему, условно, _ = pn.решить_апскейл(выбор, self.КАДР, ниже)
        self.assertIn("по записи семьи wan-2.2-ti2v-5b", почему)
        self.assertFalse(условно)
        # «Принимает» у семьи не одалживается: кадр — свойство тарифа.
        выше = свои + [факт("wan-2.2-ti2v-5b", "max_resolution", "2160p")]
        почему, условно, нота = pn.решить_апскейл(выбор, self.КАДР, выше)
        self.assertEqual(("", False), (почему, условно))
        self.assertIn("не подтверждён", нота)

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
        # Пятый круг (реестр эндпоинтов): тарифы `kling-3.0` делят измеренные
        # доводы своей семьи и обгоняют неизмеренный `wan-3.0-i2v`; кадр 1080p у
        # `kling-3.0-standard-i2v` не записан.
        # ИНТЕГРАЦИЯ ПЯТОГО КРУГА (2026-10-15), проверено как верное для продукта:
        # * правка по референсу — `nano-banana-edit`: у неё ОДНА измеренная строка
        #   применимости без плохих новостей (свидетель владельца), а у
        #   `seedream-5-flash-edit` — ни одной; прежде она проигрывала лишь
        #   положением цены («цена не записана»), теперь цена записана
        #   (0.0398 usd за картинку) — и доводы старше цены;
        # * апскейла НЕТ: кадр у `kling-3.0-standard-i2v` не записан — это
        #   молчание, а не «ниже»; молчание — нота, а не (даже условный) шаг.
        self.assertEqual(
            [
                ("генерация_изображения", "gpt-image-2.5-flare"),
                ("редактирование_изображения", "nano-banana-edit"),
                ("озвучка", "eleven_v3"),
                ("оживление", "kling-3.0-standard-i2v"),
                # СЕДЬМОЙ КРУГ (валидатор v7): у `sync-lipsync` записан провал
                # рта (probe), у `sync-lipsync-v3` — объявленная похвала вендора
                # и ни одного провала: запись провала больше не обгоняет её
                # (`FAILURE_KEY_FIELD`), а потолок 15 usd её вмещает.
                ("липсинк", "sync-lipsync-v3"),
            ],
            [(ш["step"], ш["chosen"]["model"]) for ш in итог["steps"]],
        )
        # Кадр 1080x1920 у `kling-3.0-standard-i2v` не записан — его не
        # «проносят» допущением и не дописывают апскейл: нота говорит, чья
        # запись молчит.
        self.assertTrue(
            итог["resolution_carry"].startswith(
                "frame 1080x1920 not confirmed: the model of step photo to video "
                "(kling-3.0-standard-i2v) neither confirms nor refutes it"
            ),
            итог["resolution_carry"],
        )
        self.assertIn("no upscale step added", итог["resolution_carry"])
        видео = итог["steps"][3]
        self.assertEqual("minimax-h3", видео["licence_alternative"]["model"])
        self.assertIn(
            "the API platform's terms are another document: NOT recorded in the base",
            видео["licence_alternative"]["licence_risk"],
        )
        self.assertEqual("юрисдикция", итог["question"]["axis"])
        # ЧЕТВЁРТЫЙ КРУГ (2026-10-15), цены и шоты вместе; ПЯТЫЙ — реестр. Ролик
        # 40 с из ключевых кадров — кадр на КАЖДЫЙ шот: предел прогона
        # `kling-3.0-standard-i2v` записан 15 с, ⌈40/15⌉ = 3.
        #   кадры           3 × 0.03612            = 0.1084
        #   правка по реф.  3 × 0.0398             = 0.1194 (nano-banana-edit)
        #   озвучка         ≈600 знаков × 0.08/1000 = 0.048
        #   оживление       40 с × 0.084 usd/с     = 3.36 (шестой круг: строка «$0.084
        #                   (audio off)» страницы fal, а не голые $0.14 pricing API —
        #                   оживление без звука; за секунду: шоты суммы не меняют)
        #   липсинк         40 с × 0.70 usd/мин ÷ 60 = 0.4667 (пятый круг фактов:
        #                   `fal-ai/sync-lipsync` — это Lipsync 1.9 за 0.70 usd/мин;
        #                   3 usd/мин — цена отдельного `sync-lipsync-2`)
        #   итого 4.1025 -> 4.1.
        # СЕДЬМОЙ КРУГ: липсинк — `sync-lipsync-v3`, 40 с × 0.133 usd/с = 5.32
        # (ставка неоднозначна — взята наибольшая): 0.1084 + 0.1194 + 0.048 +
        # 3.36 + 5.32 = 8.9558 -> 8.96, под потолком 15.
        # ВОСЬМОЙ КРУГ: кадры — по заказанному размеру (`тариф_по_размеру`):
        # голые 0.03612 — ступень `high 1024x768`, а кадр 1080x1920 — `high
        # 1920x1080` за 0.0396: 3 × 0.0396 = 0.1188, итого 8.9662 -> 8.97.
        self.assertEqual((8.97, "годно"), (итог["pipeline_price"]["смета"]["usd"], итог["pipeline_price"]["outcome"]))
        self.assertEqual(
            [3, 3, None, 3, None], [ш["shots"] for ш in итог["steps"]]
        )
        self.assertNotIn("optimised", итог["pipeline_price"])
        # Дешевле при тех же доводах — никого: `latentsync` с провалами ниже.
        self.assertIsNone(итог["steps"][4].get("cheaper_same_rank"))

    def test_липсинк_3_доллара(self) -> None:
        итог = pn.plan("lipsync 30 s, budget $3")
        # Провал НАСТОЯЩЕГО шага (липсинк) старше открытого вопроса о видео.
        self.assertEqual(("fail", "валидатор_отверг"), (итог["outcome"], итог["reason"]))
        # ИНТЕГРАЦИЯ ПЯТОГО КРУГА (2026-10-15), проверено как верное для продукта:
        # `fal-ai/sync-lipsync` — это Lipsync 1.9 за 0.70 usd/мин (3 usd/мин —
        # отдельный `sync-lipsync-2`), и `wan-3.0-t2v` выигрывает генерацию по
        # записанному бенчмарку. Смета 0.036 + 1.50 + 0.35 = 1.886 — НИЖЕ потолка
        # 3 usd, и перевыбирать нечего: оптимизатора нет. Сам потолок
        # сторожит `test_липсинк_потолок_1_80`.
        # ШЕСТОЙ КРУГ: кадр генерации не назван — тариф по кадру-допущению
        # плана (1080p), а не по самому дешёвому (480p): `wan-3.0-t2v` стоит
        # 30 × 0.20 = 6.00 — выше потолка, и цена поднимает `kling-3.0-standard-
        # t2v` (30 × 0.084 = 2.52, без звука). Смета 0.036 + 2.52 + 0.35 = 2.906.
        self.assertEqual(
            [
                ("озвучка", "eleven_v3"),
                ("генерация_видео", "kling-3.0-standard-t2v"),
                ("липсинк", "sync-lipsync"),
            ],
            [(ш["step"], ш["chosen"]["model"]) for ш in итог["steps"]],
        )
        self.assertEqual((2.91, "годно"), (итог["pipeline_price"]["смета"]["usd"], итог["pipeline_price"]["outcome"]))
        self.assertNotIn("optimised", итог["pipeline_price"])

    def test_липсинк_потолок_1_80(self) -> None:
        """Потолок — не «самое дешёвое»: замены по ступеням, ничьи раньше худшего баланса.

        Интеграция пятого круга: прежний бриф «budget $3» больше не превышает
        потолок (см. выше), поэтому потолок взят 1.80 usd, перебор 0.086 usd.
        Первая ступень — ничья неизмеренных TTS (`eleven_v3` -> `xai-tts-v1`,
        экономия 0.029, не закрывает); видео одно в своей полосе (бенчмарк);
        остаётся липсинк, с худшим балансом (`sync-lipsync` -> `latentsync`).
        """
        # Шестой круг: смета без потолка — 2.906 (кадр-допущение 1080p), и
        # потолок взят 2.80 usd, перебор 0.106 usd.
        итог = pn.plan("lipsync 30 s, budget $2.80")
        оптимум = итог["pipeline_price"]["optimised"]
        self.assertEqual(
            # Седьмой круг: `openai-tts-1` (0.015 usd за 1000 знаков, вендор)
            # равен `xai-tts-v1` ценой; ничья решена именем.
            [("озвучка", "eleven_v3", "openai-tts-1"), ("липсинк", "sync-lipsync", "latentsync")],
            [(о["step"], о["from"], о["to"]) for о in оптимум["swaps"]],
        )
        self.assertEqual((2.906, 2.7267), (оптимум["before_usd"], оптимум["after_usd"]))
        self.assertEqual("total 2.91 usd is over the clip ceiling 2.8 usd", оптимум["why_en"])
        self.assertEqual("годно", итог["pipeline_price"]["outcome"])
        self.assertEqual("kling-3.0-standard-t2v", итог["steps"][1]["chosen"]["model"])

    def test_липсинк_заказано_самое_дешёвое_меняет_всё(self) -> None:
        """Обратное направление: «cheapest» — каждый шаг к минимуму своей полосы."""
        итог = pn.plan("lipsync 30 s, budget $3, cheapest")
        оптимум = итог["pipeline_price"]["optimised"]
        self.assertEqual(
            [
                # Пятый круг: `xai-tts-v1` (0.015 usd за 1000 знаков) — эндпоинт
                # TTS по реестру, найденный не словом, а работой; дешевле
                # `chatterbox-multilingual` (0.025) в той же полосе.
                # Седьмой круг: `openai-tts-1` (OpenAI, 0.015 usd за 1000 знаков,
                # страница цен вендора) — ничья ценой с `xai-tts-v1`, решена именем.
                ("озвучка", "eleven_v3", "openai-tts-1"),
                # Интеграция пятого круга: `wan-3.0-t2v` один в своей полосе
                # (записанный бенчмарк) — «самое дешёвое» его не меняет: дешевле
                # можно только ниже по доводам.
                ("липсинк", "sync-lipsync", "latentsync"),
            ],
            [(о["step"], о["from"], о["to"]) for о in оптимум["swaps"]],
        )
        # 0.036 + 2.52 + 0.35 = 2.906 (видео по кадру-допущению 1080p, шестой
        # круг; липсинк 1.9 за 0.70 usd/мин) -> 0.0067 + 2.52 + 0.20.
        self.assertEqual((2.906, 2.7267), (оптимум["before_usd"], оптимум["after_usd"]))

    def test_нативный_звук_1080p_самое_дешёвое(self) -> None:
        итог = pn.plan("8 second 1080p video with native audio, cheapest")
        # Вопроса «видео уже снято?» нет: нативный звук бывает только у
        # сгенерированного. Вопрос о юрисдикции есть: измеренная `minimax-h3`
        # отодвинута лицензией и встала бы первой вне исключённых территорий.
        self.assertEqual("юрисдикция", итог["question"]["axis"])
        self.assertEqual("minimax-h3", итог["steps"][0]["licence_alternative"]["model"])
        # ПЯТЫЙ КРУГ (реестр эндпоинтов): узел семьи `kling-3.0` не заказывается,
        # его измеренные строки одалживаются тарифам семьи — и они в полосе
        # «чисто», выше неизмеренной `veo-3.1-lite-t2v` (0.64). «Самое дешёвое»
        # меняет выбор только ВНУТРИ полосы: ничья тарифов kling решена ценой
        # (`standard`, 1.12, а не `4k`, 3.36). Кадр 1080p у него не записан —
        # с интеграции пятого круга это нота, а не (условный) шаг апскейла.
        # `veo-3.1-lite-t2v` остаётся соседом.
        self.assertEqual(
            [("видео_со_звуком", "kling-3.0-standard-t2v")],
            [(ш["step"], ш["chosen"]["model"]) for ш in итог["steps"]],
        )
        self.assertIn("no upscale step added", итог["resolution_carry"])
        # Шестой круг: со звуком — строка «$0.126 (audio on)», 8 × 0.126 = 1.008;
        # тарифы kling делят доводы семьи (ничья, решена ценой), рядом — 4k.
        # ВОСЬМОЙ КРУГ: у `blackforestlabs-flux-3-text-to-video-draft` тариф
        # «0.06 $ per second … (720p)» — верхняя ступень, а голые «$0.03 per
        # second» больше её не обгоняют при заказе 1080p (`UNTIERED_ABOVE_TOP`):
        # 0.48 usd «ниже заказанного 1080p» — и соседом встаёт `veo-3.1-lite-t2v`.
        self.assertEqual(
            ["kling-3.0-4k-t2v", "veo-3.1-lite-t2v"],
            [а["model"] for а in итог["steps"][0]["alternatives"]],
        )
        self.assertEqual(1.01, итог["pipeline_price"]["смета"]["usd"])
        оптимум = итог["pipeline_price"]["optimised"]
        self.assertEqual("the cheapest was asked", оптимум["why_en"])
        self.assertEqual([], оптимум["swaps"])
        self.assertEqual([], оптимум["unpriced_steps"])

    def test_ключевые_кадры_без_апскейла_нота_о_кадре(self) -> None:
        итог = pn.plan("6 фотореалистичных ключевых кадров 1080x1920, бюджет 1 доллар")
        # Интеграция пятого круга (2026-10-15): кадр 1080x1920 у
        # `gpt-image-2.5-flare` не записан — молчание, а не «ниже», и апскейл
        # не дописывается даже условно: в плане один шаг, о кадре — нота.
        self.assertEqual(
            [("генерация_изображения", None)],
            [(ш["step"], ш.get("conditional")) for ш in итог["steps"]],
        )
        self.assertEqual("годно", итог["pipeline_price"]["outcome"])
        # Цена ролика — шесть кадров; восьмой круг — по заказанному размеру:
        # 6 × 0.0396 (`high 1920x1080`) = 0.2376, а не 6 × 0.03612 (`1024x768`).
        self.assertEqual(0.24, итог["pipeline_price"]["смета"]["usd"])
        self.assertEqual([], итог["pipeline_price"].get("conditional_steps") or [])
        # ВОСЬМОЙ КРУГ: кадр теперь подтверждён ТАРИФОМ — `high 1920x1080`
        # (`тариф_по_размеру`), и ноты «не подтверждён» больше нет.
        self.assertEqual("", итог["resolution_carry"])

if __name__ == "__main__":
    unittest.main()
