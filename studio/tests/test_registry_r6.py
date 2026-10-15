"""Шестой круг: реестр эндпоинтов (работы, заказываемость) и единицы цены.

Что сторожится (по отчёту независимого валидатора круга 5):

1. РАБОТА СОГЛАСНА СО СХЕМОЙ — свойство по ВСЕМУ живому реестру: у каждой
   работы узла обязательные входы и выход схемы не противоречат подписи работы
   (`endpoints.SIGNATURES`). И точечно: `heygen-avatar4-image-to-video` —
   аватар, `seedance-2.5-r2v` и `wan-2.6-r2v-flash` — r2v, реставрация не
   раскраска.
2. ЗАКАЗЫВАЕМЫЙ ⇔ ЕСТЬ МАРШРУТ (кто продаёт + идентификатор) — по всему
   реестру; `lustify-v2.0`, `wan2-1-14b-fusionx` — нет, `hunyuan-video` — да.
3. ЕДИНИЦЫ ЦЕНЫ: секунда вычисления не секунда ролика; «$1 per unit» — не
   цена; видео «за мегапиксель» — Мп × кадры.
4. ТАРИФЫ: звук шага выбирает строку `kling-3.0` ($0.084 без звука); разные
   ступени (кадр, звук) — не «источники расходятся».
5. НИЧЬЯ: при равных доводах записанная цена старше незаписанной.
6. 8K: старое поколение без цены не выигрывает у текущего с родным 4K.

Т2: ожидаемое — литералы.
"""

from __future__ import annotations

import unittest

from studio import endpoints as ep
from studio import planner as pn
from studio import pricing
from studio.factindex import FactIndex
from studio.selfrag.facts import Fact
from studio.selfrag.modelnames import fold

_ЖИВОЕ: dict[str, object] = {}


def живой() -> tuple[ep.Registry, dict[str, list[Fact]]]:
    if not _ЖИВОЕ:
        факты = FactIndex().facts
        строки: dict[str, list[Fact]] = {}
        for f in факты:
            строки.setdefault(fold(f.model), []).append(f)
        _ЖИВОЕ["реестр"] = ep.build(факты)
        _ЖИВОЕ["строки"] = строки
    return _ЖИВОЕ["реестр"], _ЖИВОЕ["строки"]  # type: ignore[return-value]


def факт(model: str, attribute: str, value: str, url: str, tier: str = "portal") -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=url,
        tier=tier,
        stated_on="2026-10-15",
    )


# --------------------------------------------------------------------------
# 1. РАБОТА И СХЕМА
# --------------------------------------------------------------------------


class Подпись(unittest.TestCase):
    def test_свойство_работа_согласна_со_схемой_по_всему_реестру(self) -> None:
        реестр, строки = живой()
        проверено = 0
        против: list[str] = []
        for узел in реестр.by_key.values():
            нужны = ep._виды(строки[узел.key], "requires_inputs")
            выходы = ep._виды(строки[узел.key], "produces_outputs")
            for работа in узел.functions:
                проверено += 1
                if not ep.consistent(работа, нужны, выходы):
                    против.append(f"{узел.model}: {работа} при {sorted(нужны)} -> {sorted(выходы)}")
        # Р1: ноль проверок — не «годно».
        self.assertGreater(проверено, 600)
        self.assertEqual([], против)

    def test_подпись_есть_у_каждой_работы(self) -> None:
        self.assertEqual(set(ep.FUNCTIONS), set(ep.SIGNATURES))

    def test_противоречие_только_по_обязательным_и_выходу(self) -> None:
        self.assertFalse(ep.consistent(ep.T2V, {"изображение"}, {"видео"}))
        self.assertFalse(ep.consistent(ep.T2V, {"текст"}, {"изображение"}))
        self.assertFalse(ep.consistent(ep.I2V, {"аудио", "изображение"}, {"видео"}))
        self.assertTrue(ep.consistent(ep.I2V, {"изображение", "текст"}, {"видео"}))
        # Не объявлено — не противоречит.
        self.assertTrue(ep.consistent(ep.T2I, set(), set()))

    def test_ответ_канала_против_схемы_уступает_следующему(self) -> None:
        строки = [
            факт(
                "acme-talk-text",
                "availability",
                "on fal.ai as acme/talk/text (text-to-video); listing status public",
                "https://fal.ai/models/acme/talk/text",
            ),
            факт(
                "acme-talk-text",
                "requires_inputs",
                "изображение, текст",
                "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=acme/talk/text",
            ),
            факт(
                "acme-talk-text",
                "produces_outputs",
                "видео",
                "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=acme/talk/text",
            ),
            факт(
                "acme-talk-text",
                "positioning",
                "generates a talking avatar video from a photo and a script",
                "https://fal.ai/models/acme/talk/text",
            ),
        ]
        работы, канал, нота = ep.classify("acme-talk-text", строки)
        self.assertEqual((("talking-avatar",), "docs"), (работы, канал))
        self.assertIn("отвергнуто схемой: category: t2v", нота)

    def test_живые_метки_шестого_круга(self) -> None:
        реестр, _ = живой()
        for имя, работы in (
            ("heygen-avatar4-image-to-video", ("talking-avatar",)),
            ("seedance-2.5-r2v", ("r2v",)),
            ("wan-2.6-r2v-flash", ("r2v",)),
            ("seedvr2-7b", ("upscale-video", "restore")),
            ("ddcolor", ("colorize",)),
            ("gen4_image", ("t2i",)),
            ("gemini-2.5-flash-image", ("t2i",)),
            # FLUX.2 [klein] хаб числит «image-to-image» (правка по референсам).
            ("flux.2-klein-base-4b", ("image-edit",)),
            ("i2vgen-xl", ("i2v",)),
            ("hedra-character-3", ("talking-avatar",)),
            # «turns any image into a talking video» — позиционирование VEED на fal.
            ("veed-fabric-1.0", ("talking-avatar",)),
            ("latentsync-1.6", ("lipsync",)),
        ):
            with self.subTest(имя=имя):
                узел = реестр.get(имя)
                assert узел is not None
                self.assertEqual(работы, узел.functions)

    def test_путь_площадки_старше_категории(self) -> None:
        строки = [
            факт(
                "acme-ref",
                "availability",
                "on fal.ai as acme/v1/reference-to-video (image-to-video); listing status public",
                "https://fal.ai/models/acme/v1/reference-to-video",
            ),
        ]
        self.assertEqual(("r2v",), ep.classify("acme-ref", строки)[0])

    def test_задача_хаба_весов(self) -> None:
        строки = [
            факт(
                "acme-xl",
                "pipeline_tag",
                "text-to-image",
                "https://huggingface.co/api/models/acme/xl",
            )
        ]
        self.assertEqual((("t2i",), "category"), ep.classify("acme-xl", строки)[:2])
        llm = [
            факт(
                "acme-llm",
                "pipeline_tag",
                "text-generation",
                "https://huggingface.co/api/models/acme/llm",
            )
        ]
        self.assertEqual((), ep.classify("acme-llm", llm)[0])

    def test_единица_цены_в_имени_атрибута(self) -> None:
        строки = [
            факт("acme-img", "price_per_image_usd_via_acme", "$0.04", "https://example.invalid/p")
        ]
        self.assertEqual((("t2i",), "price-unit"), ep.classify("acme-img", строки)[:2])


# --------------------------------------------------------------------------
# 2. ЗАКАЗЫВАЕМОСТЬ
# --------------------------------------------------------------------------


class Маршрут(unittest.TestCase):
    def test_свойство_заказываемый_тогда_и_только_тогда_есть_маршрут(self) -> None:
        реестр, _ = живой()
        расходятся = [e.model for e in реестр.by_key.values() if e.orderable != bool(e.route_ids)]
        self.assertEqual([], расходятся)
        без_ид = [
            e.model for e in реестр.by_key.values() for кто, ид in e.route_ids if not (кто and ид)
        ]
        self.assertEqual([], без_ид)

    def test_живые_узлы_круга(self) -> None:
        реестр, _ = живой()
        for имя, заказ in (
            ("lustify-v2.0", False),
            ("wan2-1-14b-fusionx", False),
            ("hunyuan-video", True),
        ):
            with self.subTest(имя=имя):
                узел = реестр.get(имя)
                assert узел is not None
                self.assertEqual(заказ, узел.orderable)
        hv = реестр.get("hunyuan-video")
        assert hv is not None
        self.assertIn(("fal", "fal-ai/hunyuan-video"), hv.route_ids)
        # Семья со схемой СОСЕДА заказываемой не становится.
        k = реестр.get("kling-3.0")
        assert k is not None
        self.assertEqual(False, k.orderable)

    def test_маршрут_строки_цены_и_страницы_вендора(self) -> None:
        строки = [
            факт(
                "acme-tts",
                "price_per_1000_chars",
                "$0.08 per 1K characters",
                "https://elevenlabs.io/pricing/api",
                tier="vendor",
            ),
        ]
        self.assertEqual(
            (("elevenlabs", "acme-tts"),),
            ep.own_routes("acme-tts", строки, family=False, price_routes=("elevenlabs",)),
        )
        документ = [
            факт("acme-v", "latency", "75 ms", "https://elevenlabs.io/docs/models", tier="vendor")
        ]
        self.assertEqual(
            (("elevenlabs", "acme-v"),),
            ep.own_routes(
                "acme-v", документ, family=False, vendor_hosts={"elevenlabs.io": "elevenlabs"}
            ),
        )
        # У семьи страница вендора маршрутом не считается.
        self.assertEqual(
            (),
            ep.own_routes(
                "acme-v", документ, family=True, vendor_hosts={"elevenlabs.io": "elevenlabs"}
            ),
        )
        # Строка ПОРТАЛА (пересказ) на хосте вендора — не страница API вендора.
        пересказ = [
            факт("acme-v", "latency", "75 ms", "https://elevenlabs.io/docs/models", tier="portal")
        ]
        self.assertEqual(
            (),
            ep.own_routes(
                "acme-v", пересказ, family=False, vendor_hosts={"elevenlabs.io": "elevenlabs"}
            ),
        )

    def test_страница_весов_это_репозиторий_а_не_поиск_по_каталогу(self) -> None:
        поиск = ep.build(
            [
                факт(
                    "acme-w",
                    "license",
                    "apache-2.0",
                    "https://huggingface.co/api/models?search=acme",
                )
            ]
        )
        репо = ep.build([факт("acme-w", "license", "apache-2.0", "https://huggingface.co/acme/w")])
        узел_поиска, узел_репо = поиск.get("acme-w"), репо.get("acme-w")
        assert узел_поиска is not None and узел_репо is not None
        self.assertEqual((False, ()), (узел_поиска.orderable, узел_поиска.route_ids))
        self.assertEqual(
            (True, (("self-host", "https://huggingface.co/acme/w"),)),
            (узел_репо.orderable, узел_репо.route_ids),
        )

    def test_ставка_без_единицы_не_цена_узла(self) -> None:
        реестр = ep.build(
            [факт("acme-p", "price", "$0.05 per banana", "https://fal.ai/models/acme/p")]
        )
        узел = реестр.get("acme-p")
        assert узел is not None
        self.assertEqual((True, False), (узел.orderable, узел.priced))


# --------------------------------------------------------------------------
# 3. ЕДИНИЦЫ ЦЕНЫ
# --------------------------------------------------------------------------


class Единицы(unittest.TestCase):
    AMT = "$0.000625 per compute second (fal-ai/amt-interpolation)"

    def test_секунда_вычисления(self) -> None:
        (r,) = pricing.rates(self.AMT, "price_unit_second_usd")
        self.assertEqual(("compute_second", 0.000625), (r.per, r.amount))
        self.assertEqual("compute_second", pricing.parse(self.AMT, "price_unit_second_usd").per)

    def test_без_отношения_цены_нет_а_не_секунды_ролика(self) -> None:
        ставки = pricing.rates(self.AMT, "price_unit_second_usd")
        self.assertEqual([], pricing.estimate(ставки, pricing.Need(seconds=4.0)))
        (o,) = pricing.estimate(ставки, pricing.Need(seconds=4.0, compute_ratio=3.0))
        self.assertEqual(0.0075, o.usd)

    def test_близнец_вычисления_того_же_маршрута(self) -> None:
        ставки = pricing.compute_twins(
            [
                (
                    "fal",
                    pricing.rates("Your request will cost $0.0013 per compute second.", "price"),
                ),
                ("fal", pricing.rates("$0.0013 per second", "price_unit_second_usd")),
                ("replicate", pricing.rates("$0.0013 per second", "price_unit_second_usd")),
            ]
        )
        self.assertEqual(["compute_second", "compute_second", "second"], [r.per for r in ставки])

    def test_живые_вычисления_без_цены_шага(self) -> None:
        _, строки = живой()
        for имя in ("amt-interpolation", "rife-video"):
            with self.subTest(имя=имя):
                self.assertIsNone(
                    pn.стоимость(строки[fold(имя)], pricing.Need(seconds=4.0, mode="v2v"))
                )

    def test_отношение_записанное_считается(self) -> None:
        строки = [
            факт(
                "acme-rife",
                "price",
                "$0.0013 per compute second",
                "https://fal.ai/models/acme/rife",
            ),
            факт(
                "acme-rife",
                pricing.COMPUTE_RATIO_ATTRIBUTE,
                "2.5",
                "https://example.invalid/bench",
                tier="benchmark",
            ),
        ]
        c = pn.стоимость(строки, pricing.Need(seconds=10.0))
        assert c is not None
        self.assertEqual(0.0325, c.default.usd)

    def test_единица_не_названа_не_цена(self) -> None:
        текст = "$1 per unit (billing unit 'units')"
        self.assertEqual([], pricing.rates(текст, "price_unit_usd"))
        self.assertIsNone(pricing.parse(текст, "price_unit_usd").amount)
        реестр, _ = живой()
        for имя in ("gpt-image-2", "nano-banana-2.1"):
            with self.subTest(имя=имя):
                узел = реестр.get(имя)
                assert узел is not None
                self.assertNotIn("", узел.price_units)

    def test_видео_за_мегапиксель_по_кадрам(self) -> None:
        # Пример страницы FlashVSR: 1920×1080 × 121 кадр ≈ $0.125.
        ставки = pricing.rates(
            "Your request will cost $0.0005 per megapixel of video data (width × height × frames).",
            "price",
        )
        нужда = pricing.Need(
            seconds=121 / 30, resolution=1080, megapixels=1920 * 1080 / 1e6, images=0.0, fps=30.0
        )
        (o,) = pricing.estimate(ставки, нужда)
        self.assertEqual(0.1255, o.usd)

    def test_минута_округляется_вверх(self) -> None:
        ставки = pricing.rates(
            "Your request will cost $0.6 per output audio minute. The audio will be rounded up to the closest minute.",
            "price",
        )
        (o,) = pricing.estimate(ставки, pricing.Need(seconds=30.0))
        self.assertEqual(0.6, o.usd)

    def test_прогон_n_секунд_в_начале_предложения(self) -> None:
        ставки = pricing.rates(
            "For a 10-second 30→60 fps job, Apollo costs $0.30 at 1080p or $0.60 at 4K", "price"
        )
        self.assertEqual(
            [("run", 10.0, (1080,)), ("run", 10.0, (2160,))],
            [(r.per, r.run_seconds, r.resolutions) for r in ставки],
        )

    def test_знаки_превью(self) -> None:
        (r,) = pricing.rates("$1.5 per clone, $0.3 per 1000 preview characters", "price")
        self.assertEqual(("1000_chars", 0.3), (r.per, r.amount))


# --------------------------------------------------------------------------
# 4. ТАРИФЫ ПО ЗВУКУ И КАДРУ, «ИСТОЧНИКИ РАСХОДЯТСЯ»
# --------------------------------------------------------------------------


class Тарифы(unittest.TestCase):
    def стоимость(self, имя: str, **нужда: object) -> pn.Стоимость:
        _, строки = живой()
        c = pn.стоимость(строки[fold(имя)], pricing.Need(**нужда))  # type: ignore[arg-type]
        assert c is not None
        return c

    def test_kling_звук_выбирает_строку(self) -> None:
        без = self.стоимость(
            "kling-3.0-standard-t2v", seconds=10.0, resolution=1080, audio=False, mode="t2v"
        )
        со = self.стоимость(
            "kling-3.0-standard-t2v", seconds=10.0, resolution=1080, audio=True, mode="t2v"
        )
        self.assertEqual((0.84, 1.26), (без.default.usd, со.default.usd))
        self.assertEqual(((), ()), (без.contradictions, со.contradictions))

    def test_wan_кадр_выбирает_строку_без_спора(self) -> None:
        for кадр, сумма in ((480, 0.5), (720, 1.0), (1080, 2.0)):
            with self.subTest(кадр=кадр):
                c = self.стоимость(
                    "wan-3.0-t2v", seconds=10.0, resolution=кадр, audio=False, mode="t2v"
                )
                self.assertEqual((сумма, ()), (c.default.usd, c.contradictions))

    def test_wan_prime_480p_по_странице(self) -> None:
        c = self.стоимость(
            "wan-3.0-prime-t2v", seconds=10.0, resolution=480, audio=False, mode="t2v"
        )
        self.assertEqual((0.68, ()), (c.default.usd, c.contradictions))

    def test_музыка_elevenlabs_маршруты_порознь(self) -> None:
        c = self.стоимость("elevenlabs-music", seconds=30.0)
        self.assertEqual(("elevenlabs", 0.075), (c.route, c.default.usd))
        self.assertEqual([("fal", 0.6)], [(м, o.usd) for м, o in c.other_routes])
        self.assertEqual((), c.contradictions)

    def test_спор_той_же_ступени_остаётся(self) -> None:
        строки = [
            факт(
                "acme-v",
                "price_per_second_usd",
                "$0.10 per second at 720p",
                "https://fal.ai/models/acme/v",
            ),
            факт(
                "acme-v",
                "price",
                "Your request will cost $0.20 per second at 720p",
                "https://fal.ai/models/acme/v/api",
            ),
        ]
        c = pn.стоимость(строки, pricing.Need(seconds=10.0, resolution=720))
        assert c is not None
        self.assertEqual(1, len(c.contradictions))

    def test_кадр_и_звук_разных_строк_не_спор(self) -> None:
        for имя, строки, сумма in (
            (
                "кадр",
                [
                    (
                        "price_per_second_usd",
                        "$0.10 per second at 720p",
                        "https://fal.ai/models/acme/v",
                    ),
                    (
                        "price",
                        "Your request will cost $0.20 per second at 1080p",
                        "https://fal.ai/models/acme/v/api",
                    ),
                ],
                1.0,
            ),
            (
                "звук",
                [
                    (
                        "price_per_second_usd",
                        "$0.10 per second (audio off)",
                        "https://fal.ai/models/acme/v",
                    ),
                    (
                        "price",
                        "Your request will cost $0.15 per second (audio on)",
                        "https://fal.ai/models/acme/v/api",
                    ),
                ],
                1.5,
            ),
        ):
            with self.subTest(имя=имя):
                c = pn.стоимость(
                    [факт("acme-v", а, з, у) for а, з, у in строки], pricing.Need(seconds=10.0)
                )
                assert c is not None
                self.assertEqual((сумма, ()), (c.default.usd, c.contradictions))

    def test_разные_ступени_не_спор(self) -> None:
        строки = [
            факт(
                "acme-v",
                "price_per_second_usd",
                "$0.10 per second at 720p",
                "https://fal.ai/models/acme/v",
            ),
            факт(
                "acme-v",
                "price_unit_second_usd",
                "$0.05 per second",
                "https://fal.ai/models/acme/v",
            ),
        ]
        c = pn.стоимость(строки, pricing.Need(seconds=10.0, resolution=720))
        assert c is not None
        self.assertEqual((1.0, ()), (c.default.usd, c.contradictions))


class ПлановыйКадр(unittest.TestCase):
    def test_видео_плана_без_кадра_считается_по_допущению(self) -> None:
        """w11/w29: генерация без названного кадра считалась по 480p, с кадром-
        допущением спецификации — по 1080p. Теперь тариф следует кадру плана."""
        import json

        from studio.mcp import server

        план = json.loads(
            server.plan_pipeline(
                "a 10 second video of a red fox running through snow, from scratch",
                spec={"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 10},
            )
        )
        # С 6-го круга кадр не назван в ПОЛНОЙ spec — допущение 1080p делает
        # сама спецификация (`bs.DEFAULT_VIDEO_RESOLUTION`), и тариф идёт по нему.
        допущения = план["understood_as"]["assumptions"]
        self.assertTrue(
            any("1080p assumed" in д for д in допущения) or pn.ASSUMED_PRICE_FRAME in допущения,
            допущения,
        )
        смета = план["pipeline_price"]["смета"]["steps"]
        self.assertTrue(смета)
        self.assertEqual([1080], [ш["options"][0]["resolution"] for ш in смета])

    def test_текстовый_путь_допущение_планировщика(self) -> None:
        """Допущение кадра цены делает и сам планировщик — на текстовом пути
        (`план_по_тексту`), где спецификация кадра не допускает."""
        import json

        from studio.mcp import server

        план = json.loads(
            server.план_по_тексту(
                "a 10 second video of a red fox running through snow, from scratch"
            )
        )
        self.assertIn(pn.ASSUMED_PRICE_FRAME, план["understood_as"]["assumptions"])


class Ничья(unittest.TestCase):
    def test_живое_удаление_фона_видео_цена_старше(self) -> None:
        op = next(о for о in pn.OPERATIONS if о.name == "удаление_фона_видео")
        найдены = pn.candidates_for(op, FactIndex(), need=pricing.Need(seconds=15.0))
        self.assertEqual(
            ["bria-video-background-removal-v3", "birefnet-v2-video"],
            [c.model for c in найдены[:2]],
        )
        self.assertFalse(найдены[0].foreign)


# --------------------------------------------------------------------------
# 5–6. ПОКОЛЕНИЕ И 8K
# --------------------------------------------------------------------------


class Поколение(unittest.TestCase):
    def test_семья_и_версия(self) -> None:
        self.assertEqual(
            ("kling", (1, 6)), pn.семья_и_версия("kling-video-v1.6-standard-text-to-video")
        )
        self.assertEqual(("kling", (3,)), pn.семья_и_версия("kling-3.0-standard-t2v"))
        self.assertIsNone(pn.семья_и_версия("kling-o3-4k"))

    def test_родной_предел_своя_запись_старше_семьи(self) -> None:
        своя = [факт("m", "max_resolution", "4K native", "https://fal.ai/models/m")]
        семья = [("fam", [факт("fam", "max_resolution", "4K native", "https://example.invalid/f")])]
        self.assertEqual(2160, pn.родной_предел(своя, семья, None))
        self.assertEqual(2159, pn.родной_предел([], семья, None))
        self.assertEqual(1, pn.родной_предел([], [], None))
        # Тариф перепродавца выше родного выхода семьи — предел по семье.
        родная_семья = [
            ("fam", [факт("fam", "native_resolution", "720p native", "https://example.invalid/f")])
        ]
        self.assertEqual(719, pn.родной_предел([], родная_семья, 2160))


class ВосемьК(unittest.TestCase):
    def test_8k_качество_текущее_с_родным_4k_и_апскейл(self) -> None:
        """r27_8k_spec: выбиралась `kling-video-v1.6-standard-text-to-video`
        (старая, без цены, без 4K); теперь — текущая с родным 4K и апскейл."""
        import json

        from studio.mcp import server

        план = json.loads(
            server.plan_pipeline(
                "8K 10s drone flyover of Norwegian fjords at sunrise, quality over everything",
                spec={
                    "task": "generate",
                    "outputs": ["video"],
                    "duration_s": 10,
                    "resolution": "8k",
                    "objective": "quality",
                    "inputs": [],
                },
            )
        )
        шаги = {ш["step"]: ш["chosen"]["model"] for ш in план["steps"]}
        self.assertEqual("kling-3.0-4k-t2v", шаги["генерация_видео"])
        self.assertIn("апскейл", шаги)

    def test_шаг_над_готовым_видео_исключает_ниже_записанных(self) -> None:
        ниже = pn.Candidate(
            model="m",
            evidence=(),
            applicability=0,
            capability=0,
            unresolved=0,
            price="",
            hard_rank=(3, 4),
            native_below_px=720,
            native_below_why="ниже",
        )
        молчит = pn.Candidate(
            model="n",
            evidence=(),
            applicability=0,
            capability=0,
            unresolved=0,
            price="",
            hard_rank=(2, 4),
        )
        op = next(о for о in pn.OPERATIONS if о.name == "липсинк")
        исключены: dict[str, str] = {}
        self.assertEqual(
            ["n"], [c.model for c in pn.родной_кадр_или_ближайший([ниже, молчит], исключены, op)]
        )
        self.assertEqual({"m": "ниже"}, исключены)
        генерация = next(о for о in pn.OPERATIONS if о.name == "генерация_видео")
        итог = pn.родной_кадр_или_ближайший([ниже, молчит], {}, генерация)
        self.assertEqual([(1.5 + (4320 - 720) / 43200, 4), (2, 4)], [c.hard_rank for c in итог])


class Длительность(unittest.TestCase):
    """Кодек, контейнер и версия — не секунды (найдено агентом B: «MP4 H.264» -> 264 с)."""

    def test_кодек_не_секунды(self) -> None:
        from studio import duration as dur

        for значение, секунды in (
            ("5 exactly, silent output, 480P or 1080P at 30fps, MP4 H.264", 5.0),
            ("30fps fixed, 720P or 1080P, 2 to 15 whole seconds, MP4 H.264", 15.0),
            ("x265 encoded, 8 seconds", 8.0),
            ("up to 10 s (v2.1)", 10.0),
            ("60", 60.0),
        ):
            with self.subTest(значение=значение):
                self.assertEqual(секунды, dur.предел_из_строк([("max_seconds", значение)]).секунды)
        self.assertIsNone(
            dur.предел_из_строк([("max_seconds", "mp4, prores (up to 4444 XQ)")]).секунды
        )

    def test_живой_прогон_wan_22_plus(self) -> None:
        _, строки = живой()
        self.assertEqual(5.0, pn.предел_прогона(строки[fold("wan-2.2-t2v-plus")]))


if __name__ == "__main__":
    unittest.main()
