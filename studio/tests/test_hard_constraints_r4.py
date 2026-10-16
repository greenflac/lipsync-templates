"""Жёсткие требования в отборе, оптимизатор и юрисдикция — раунд 4 (2026-10-15).

Находки независимого валидатора:

1. «self-host on one RTX 4090, 1080p 5s» выбирал `kling-3.0` — открытых весов
   у неё нет; цены своего запуска (время GPU × аренда) не было вовсе.
2. «4K … quality over price» выбирал `kling-3.0` без цены и тарифа в 4K, а
   родной 4K-эндпоинт `kling-3.0-4k-t2v` стоял соседом.
3. После `видео_со_звуком` условный апскейл брал апскейлер КАРТИНКИ.
4. Оптимизатор под потолок менял измеренный `sync-lipsync` (за 2, против 1)
   на `latentsync` (за 1, против 3), когда на соседнем шаге была замена,
   не отдающая ничего измеренного.
5. «Japanese voice» давал юрисдикцию JP, «for us» — US, «поскорее» — KR,
   «штатный» — US.
6. Вопрос о юрисдикции задавался и тогда, когда отодвинутая модель не
   встала бы и при ответе «не исключена».

Т2: ожидаемое — литералы. Т4: сети нет. Классы `Живые*` — на живой базе: они
краснеют, когда база меняет ответ, и это нарочно.
"""

from __future__ import annotations

import unittest

from studio import hardneed as hn
from studio import pipeline as pl
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


def стоит(usd: float) -> "pn.Стоимость":
    o = pricing.Option(usd, "", None, f"{usd} usd")
    return pn.Стоимость((o,), o, o, "test")


# --------------------------------------------------------------------------
# 1. ЖЁСТКИЕ ТРЕБОВАНИЯ — ПРОСТЫМИ ЗНАЧЕНИЯМИ
# --------------------------------------------------------------------------


class ТребованияИзБрифа(unittest.TestCase):
    def test_gpu_по_имени_это_свой_запуск_и_память_из_таблицы(self) -> None:
        т = hn.from_brief("self-host on one RTX 4090, 1080p 5s clips, what model")
        self.assertEqual(
            (True, True, "rtx-4090", 24.0, ""),
            (т.self_host, т.weights_required, т.gpu, т.vram_gb, т.objective),
        )

    def test_память_названная_числом_перекрывает_таблицу(self) -> None:
        т = hn.from_brief("self-host on an RTX 4090 with 20 GB free")
        self.assertEqual(20.0, т.vram_gb)

    def test_open_source_это_веса_но_не_свой_gpu(self) -> None:
        т = hn.from_brief("must be open-source and commercially licensed")
        self.assertEqual((False, True), (т.self_host, т.weights_required))

    def test_слово_quality_в_описании_кадра_не_цель(self) -> None:
        # Негативные контроли: «quality» — про кадр, а не «качество важнее цены».
        for бриф in (
            "high quality product shot, budget $2",
            "quality control checklist video, 10s",
            "a 4K video of a quality watch",
        ):
            self.assertEqual("", hn.from_brief(бриф).objective, бриф)

    def test_качество_важнее_цены_цель(self) -> None:
        for бриф in (
            "4K 24fps cinematic 6s, no audio, quality over price",
            "с нуля: ролик 6 секунд 4K, качество важнее цены",
            "best possible quality, 8s",
        ):
            self.assertEqual("quality", hn.from_brief(бриф).objective, бриф)

    def test_без_gpu_и_весов_требований_нет(self) -> None:
        т = hn.from_brief("talking head ad for our SaaS, 30 seconds, budget $2")
        self.assertFalse(т.active)

    def test_spec_перекрывает_бриф(self) -> None:
        т = hn.from_spec(
            {
                "self_host": {"gpu": "RTX 3090"},
                "objective": "quality",
                "jurisdiction": "DE",
                "resolution": "4k",
            },
            hn.from_brief("self-host on one RTX 4090"),
        )
        self.assertEqual(
            ("rtx-3090", "quality", ("EU",), ("DE",), 2160),
            (т.gpu, т.objective, т.jurisdiction, т.countries, т.resolution),
        )
        self.assertEqual("spec", dict(т.sources)["gpu"])

    def test_spec_с_неизвестной_целью_отказ(self) -> None:
        with self.assertRaises(ValueError):
            hn.from_spec({"objective": "fastest"})


class ВесаИПамять(unittest.TestCase):
    def test_веса_на_странице_весов_да(self) -> None:
        строки = [факт("m", "license", "apache-2.0", "https://huggingface.co/Org/M")]
        self.assertEqual(hn.WEIGHTS_YES, hn.weights_state(строки)[0])

    def test_только_api_нет(self) -> None:
        строки = [
            факт(
                "wan-3.0",
                "license",
                "not released as open weights — API only",
                "https://huggingface.co/api/models?author=Wan-AI&sort=createdAt",
            )
        ]
        self.assertEqual(hn.WEIGHTS_NO, hn.weights_state(строки)[0])

    def test_поиск_по_каталогу_не_страница_весов(self) -> None:
        строки = [
            факт("m", "license", "apache-2.0", "https://huggingface.co/api/models?author=Org")
        ]
        self.assertEqual(hn.WEIGHTS_UNKNOWN, hn.weights_state(строки)[0])

    def test_лицензия_на_странице_вендора_api_не_веса(self) -> None:
        строки = [факт("m", "license", "commercial", "https://vendor.example/terms")]
        self.assertEqual(hn.WEIGHTS_UNKNOWN, hn.weights_state(строки)[0])

    def test_веса_семьи_перенос_помечен(self) -> None:
        семья = [("fam", [факт("fam", "licence", "Apache 2.0", "https://huggingface.co/Org/Fam")])]
        состояние, нота = hn.weights_state([], семья)
        self.assertEqual(hn.WEIGHTS_FAMILY, состояние)
        self.assertIn("в базе НЕ записано", нота)

    def test_память_наименьшее_число_строки(self) -> None:
        строки = [факт("m", "min_vram_gb", "60 GB for 720p; 45 GB for 544p; 80 GB recommended")]
        self.assertEqual((45.0, False), hn.vram_need(строки)[0::2])

    def test_память_оценка_снизу_по_параметрам(self) -> None:
        строки = [факт("m", "parameter_count", "33.1B (safetensors total 33,122,992,896)")]
        гб, нота, оценка = hn.vram_need(строки)
        assert гб is not None
        self.assertEqual((33.122992896, True), (round(гб, 9), оценка))
        self.assertIn("ОЦЕНКА снизу", нота)

    def test_оценка_решает_только_нет(self) -> None:
        self.assertEqual(hn.VRAM_OVER, hn.vram_state(33.1, True, 24.0))
        self.assertEqual(hn.VRAM_UNKNOWN, hn.vram_state(19.0, True, 24.0))
        self.assertEqual(hn.VRAM_FITS, hn.vram_state(24.0, False, 24.0))
        self.assertEqual(hn.VRAM_OVER, hn.vram_state(24.5, False, 24.0))
        self.assertEqual(hn.VRAM_UNKNOWN, hn.vram_state(None, False, 24.0))


class ЦенаСвоегоЗапуска(unittest.TestCase):
    СТАВКА = [
        факт(
            "runpod-rtx-4090",
            "gpu_price_per_hour_usd",
            "0.34 usd/h Community Cloud; 0.74 usd/h Secure Cloud",
        )
    ]

    def test_ставка_и_время_дают_оценку(self) -> None:
        ставка = hn.gpu_rate(self.СТАВКА, "rtx-4090")
        время = hn.gpu_time(
            [факт("m", "gpu_seconds_per_clip", "540 GPU-s per 5 s clip at 720p on 1x RTX 4090")]
        )
        assert ставка is not None and время is not None
        цена = hn.self_host_cost(время, ставка, 10.0)
        # 540 × 10/5 = 1080 GPU-с; × 0.34 / 3600 = 0.102; × 0.74 / 3600 = 0.222.
        self.assertEqual((0.102, 0.222), (round(цена.low, 4), round(цена.high, 4)))
        self.assertTrue(цена.formula.startswith("ОЦЕНКА: "))

    def test_время_чужого_режима_не_цена(self) -> None:
        строки = [
            факт(
                "m", "gpu_seconds_per_clip", "75 GPU-s per run on 1x RTX 4090 — 480p image-to-video"
            )
        ]
        self.assertIsNone(hn.gpu_time(строки, "t2v"))
        время = hn.gpu_time(строки, "i2v")
        assert время is not None
        self.assertEqual(75.0, время.seconds)

    def test_ставки_другого_gpu_нет(self) -> None:
        self.assertIsNone(hn.gpu_rate(self.СТАВКА, "rtx-3090"))


class ЖивойСвойGpu(unittest.TestCase):
    """Бриф валидатора — на живой базе."""

    итог: dict

    @classmethod
    def setUpClass(cls) -> None:
        cls.итог = pn.plan("self-host on one RTX 4090, 1080p 5s clips, what model", full=True)

    def test_не_kling_а_модель_с_весами_в_24_гб(self) -> None:
        шаг = self.итог["steps"][0]
        self.assertEqual(
            # Пятый круг: те же веса в формате diffusers — эндпоинт работы t2v из
            # реестра; узел `wan-2.2-ti2v-5b` записан с кадром ниже 1080p.
            ("генерация_видео", "wan2.2-ti2v-5b-diffusers"), (шаг["step"], шаг["chosen"]["model"])
        )
        отсеяны = {о["model"] for о in шаг["hard_excluded"]}
        self.assertNotIn("kling-3.0", {a["model"] for a in шаг["alternatives"]})
        self.assertGreaterEqual(шаг["hard_excluded_count"], 1)
        self.assertTrue(отсеяны)

    def test_kling_отсеяна_за_веса_minimax_за_память(self) -> None:
        найдены = pn.candidates_for(
            next(о for о in pn.OPERATIONS if о.name == "генерация_видео"),
            pn.FactIndex(),
            hard=hn.from_brief("self-host on one RTX 4090"),
        )
        # Пятый круг: узел семьи `kling-3.0` не кандидат вовсе (реестр: своей
        # цены и идентификатора площадки нет) — за веса отсеиваются её тарифы.
        self.assertNotIn("kling-3.0", [c.model for c in найдены])
        self.assertIn("о весах не записано", найдены.исключены["kling-3.0-standard-t2v"])
        self.assertIn("нужно 33 ГБ", найдены.исключены["minimax-h3"])
        self.assertIn("нужно 80 ГБ", найдены.исключены["wan-2.2-t2v-a14b"])
        self.assertIn("весов нет: только API", найдены.исключены["wan-3.0-t2v"])

    def test_цена_временем_gpu_и_это_оценка(self) -> None:
        цена = self.итог["steps"][0]["chosen"]["price"]
        self.assertTrue(
            цена.startswith("0.11 usd per step: via own GPU — ESTIMATE: 540 GPU-s per 5 s clip"), цена
        )
        self.assertIn("CONSTRAINTS: own GPU (rtx-4090 24 GB)", self.итог["summary"])

    def test_апскейл_тоже_на_своём_gpu(self) -> None:
        self.assertEqual(
            [("генерация_видео", "wan2.2-ti2v-5b-diffusers"), ("апскейл", "seedvr2-3b")],
            [(ш["step"], ш["chosen"]["model"]) for ш in self.итог["steps"]],
        )

    def test_негативный_контроль_без_своего_gpu_kling_не_отсеяна(self) -> None:
        итог = pn.plan("generate a video from scratch, 1080p 5s clips", full=True)
        self.assertEqual(0, итог["steps"][0]["hard_excluded_count"])
        # Пятый круг: узел семьи `kling-3.0` не заказывается. Интеграция пятого
        # круга (проверено как верное для продукта): `wan-3.0-t2v` обходит тарифы
        # kling по записанному бенчмарку генерации по тексту (VTR-Bench, строки
        # фактов пятого круга). Суть контроля прежняя: без своего GPU никто не
        # отсеян, а выбран API-эндпоинт без весов.
        self.assertEqual("wan-3.0-t2v", итог["steps"][0]["chosen"]["model"])


# --------------------------------------------------------------------------
# 2. ЦЕЛЬ «КАЧЕСТВО» — РОДНОЙ КАДР
# --------------------------------------------------------------------------


class ЖивоеКачество(unittest.TestCase):
    def test_4k_качество_родной_4k_эндпоинт(self) -> None:
        итог = pn.plan(
            "generate a video from scratch: cinematic 6s 4K 24fps, no audio, quality over price",
            full=True,
        )
        шаг = итог["steps"][0]
        self.assertEqual("kling-3.0-4k-t2v", шаг["chosen"]["model"])
        # Родной 720p у seedance-2.0 (карточка вендора) — отсев, хоть тариф 2160p и продаётся.
        отсеяны = {о["model"]: о["why"] for о in шаг["hard_excluded"]}
        # Ответ на английский бриф — по-английски (`studio/l10n.py`).
        self.assertTrue(any("the native frame is BELOW the one asked" in п for п in отсеяны.values()), отсеяны)
        self.assertNotIn("апскейл", [ш["step"] for ш in итог["steps"]])

    def test_по_русски_то_же(self) -> None:
        итог = pn.plan(
            "с нуля: кинематографичный ролик 6 секунд 4K 24 кадра, без звука, качество важнее цены"
        )
        self.assertEqual("kling-3.0-4k-t2v", итог["steps"][0]["chosen"]["model"])

    def test_негативный_контроль_без_цели_качество(self) -> None:
        итог = pn.plan("generate a video from scratch: cinematic 6s 4K 24fps, no audio", full=True)
        # Без цели «качество» никто не отсеян жёстким требованием...
        self.assertEqual(0, итог["steps"][0]["hard_excluded_count"])
        # ...но ВОСЬМОЙ КРУГ: 4K — требование заказа до цены при ЛЮБОЙ цели
        # (`REQUIREMENT_KEY_FIELD`), и родной 4K-эндпоинт стоит выше тарифа,
        # чей кадр не записан (прежде — `kling-3.0-standard-t2v` ценой).
        self.assertEqual("kling-3.0-4k-t2v", итог["steps"][0]["chosen"]["model"])

    def test_родной_выход_старше_тарифа(self) -> None:
        op = next(о for о in pn.OPERATIONS if о.name == "генерация_видео")
        строки = [
            факт(
                "m",
                "max_resolution",
                "480p and 720p native output — contradicts the 3840x2160 read off a reseller",
            )
        ]
        self.assertIs(False, pn._кадр_родной(op, строки, стоит(1.0), (3840, 2160)))
        строки = [факт("m", "max_resolution", "4K native")]
        self.assertIs(True, pn._кадр_родной(op, строки, стоит(1.0), (3840, 2160)))
        self.assertIsNone(pn._кадр_родной(op, [], стоит(1.0), (3840, 2160)))


# --------------------------------------------------------------------------
# 3. ВИДЕО СО ЗВУКОМ — ТОЖЕ ВИДЕО
# --------------------------------------------------------------------------


class ВидеоСоЗвукомДелаетВидео(unittest.TestCase):
    def test_в_списке(self) -> None:
        self.assertIn("видео_со_звуком", pn.VIDEO_MAKERS)

    def test_молчание_о_кадре_нота_а_не_апскейл(self) -> None:
        # Интеграция пятого круга (2026-10-15): кадр 1080p у выбранного тарифа
        # не записан — прежде дописывался условный апскейл (видео, а не
        # картинки); теперь шага нет, а нота называет, чья запись молчит.
        # Что апскейл видео выбирается для `видео_со_звуком`, сторожит
        # `test_в_списке` (`VIDEO_MAKERS`).
        итог = pn.plan(
            "Сгенерировать с нуля, видео не снято: 8 секунд 1080p с нативным звуком, "
            "диалог по-английски, бюджет 2 доллара",
            full=True,
        )
        шаги = [ш["step"] for ш in итог["steps"]]
        self.assertEqual(["видео_со_звуком"], шаги)
        self.assertTrue(итог["resolution_carry"].startswith("кадр 1920x1080 не подтверждён: модель шага видео_со_звуком"))


# --------------------------------------------------------------------------
# 4. ОПТИМИЗАТОР: БАЛАНС ДОВОДОВ СТАРШЕ МЕСТА
# --------------------------------------------------------------------------


def _липсинк(имя: str, за: int, против: int, usd: float) -> "pn.Candidate":
    return pn.Candidate(имя, (), за + против, 0, 0, "", against=против, cost=стоит(usd))


def _видео(имя: str, usd: float) -> "pn.Candidate":
    return pn.Candidate(имя, (), 0, 0, 0, "", cost=стоит(usd))


class Оптимизатор(unittest.TestCase):
    ЛИПСИНК = next(о for о in pn.OPERATIONS if о.name == "липсинк")
    ВИДЕО = next(о for о in pn.OPERATIONS if о.name == "генерация_видео")

    def _шаги(self, видео: list) -> tuple:
        sync = _липсинк("sync", 2, 1, 1.50)
        latent = _липсинк("latent", 1, 3, 0.20)
        найдено = {"липсинк": [sync, latent], "генерация_видео": видео}
        return [(self.ЛИПСИНК, sync), (self.ВИДЕО, видео[0])], найдено

    def test_потеря_доводов_литерал(self) -> None:
        self.assertEqual(3, pn.потеря_доводов(_липсинк("a", 2, 1, 1), _липсинк("b", 1, 3, 1)))
        self.assertEqual(0, pn.потеря_доводов(_липсинк("a", 1, 3, 1), _липсинк("b", 2, 1, 1)))

    def test_ступени(self) -> None:
        self.assertEqual(pn.SWAP_TIE, pn.ступень_обмена(_видео("a", 2), _видео("b", 1)))
        self.assertEqual(
            pn.SWAP_WORSE_BALANCE, pn.ступень_обмена(_липсинк("a", 2, 1, 1), _липсинк("b", 1, 3, 1))
        )

    def test_не_отдаёт_измеренное_пока_есть_ничья(self) -> None:
        # Сумма 3.54, потолок 2.9: перебор 0.64. Ничья `wan` (0.54) его не
        # закрывает, ничья `flash` (1.14) закрывает — и липсинк не тронут.
        шаги, найдено = self._шаги(
            [_видео("prime", 2.04), _видео("wan", 1.50), _видео("flash", 0.90)]
        )
        замены = pn.подобрать_под_потолок(шаги, найдено, 2.9)
        self.assertEqual({"генерация_видео": "flash"}, {ш: c.model for ш, c in замены.items()})

    def test_худший_баланс_когда_иначе_не_влезть(self) -> None:
        # Обратное направление: видео заменить не на что — тогда и только тогда
        # отдаётся баланс доводов липсинка.
        шаги, найдено = self._шаги([_видео("prime", 2.04)])
        замены = pn.подобрать_под_потолок(шаги, найдено, 2.9)
        self.assertEqual({"липсинк": "latent"}, {ш: c.model for ш, c in замены.items()})

    def test_ничья_недостаточна_но_берётся_первой(self) -> None:
        # Ничья экономит 0.54 при переборе 0.64 — берётся первой, затем худшим
        # балансом добирается только то, чего не хватило.
        шаги, найдено = self._шаги([_видео("prime", 2.04), _видео("wan", 1.50)])
        замены = pn.подобрать_под_потолок(шаги, найдено, 2.9)
        self.assertEqual(
            {"генерация_видео": "wan", "липсинк": "latent"}, {ш: c.model for ш, c in замены.items()}
        )


# --------------------------------------------------------------------------
# 5. ЮРИСДИКЦИЯ — СТРАНЫ И РЕГИОНЫ ЦЕЛЫМ СЛОВОМ
# --------------------------------------------------------------------------


class Юрисдикции(unittest.TestCase):
    НЕ_ЮРИСДИКЦИИ = (
        "anime style 10s with Japanese voice",
        "make a promo video for us, 8s",
        "tell us about your product",
        "сделайте ролик поскорее",
        "штатный диктор, 20 секунд",
        "Korean BBQ restaurant ad",
        "корейский ресторан, ролик 10 секунд",
        "японская озвучка",
        "european-style castle at dusk",
        "европейский стиль, 8 секунд",
        "Chinese New Year greeting",
        "Indian food delivery ad",
        "Indiana Jones style adventure",
        "plus Russian voiceover",
        "на английском языке",
        "British accent narrator",
        "American football highlight",
        "американский стиль",
        "Германский шрифт в титрах",
        "данные клиента в кадре",
        "a ukulele cover",
        "eau-de-cologne bottle on a neutral table",
        "the sun rises over us",
        "budget 5 USD per clip",
        "export over USB-C",
    )

    def test_национальность_и_язык_не_юрисдикция(self) -> None:
        for текст in self.НЕ_ЮРИСДИКЦИИ:
            self.assertEqual((), pl.jurisdictions_in(текст), текст)

    def test_страны_и_регионы(self) -> None:
        случаи = {
            "client in Germany": ("EU",),
            "работаем в Германии": ("EU",),
            "for the US market": ("US",),
            "in the U.S. and the UK": ("UK", "US"),
            "для рынка США": ("US",),
            "в Штатах": ("US",),
            "снимаем для Кореи": ("KR",),
            "used in China and Japan": ("CN", "JP"),
            "ролик для Японии": ("JP",),
            "клиент из России": ("RU",),
            "audience in India": ("IN",),
            "across Europe": ("EU",),
            "EU, UK, South Korea, USA": ("EU", "KR", "UK", "US"),
            "the licence excludes territories EU, KR, UK, US": ("EU", "KR", "UK", "US"),
        }
        for текст, ждём in случаи.items():
            self.assertEqual(ждём, pl.jurisdictions_in(текст), текст)

    def test_страна_ес_печатается_кодом(self) -> None:
        self.assertEqual({"DE": "EU"}, pl.countries_in("client in Germany"))
        итог = pn.plan("generate a video from scratch: 8s 1080p, client is in Germany")
        self.assertEqual(
            (["EU"], ["DE"]), (итог["hard"]["jurisdiction"], итог["hard"]["countries"])
        )


# --------------------------------------------------------------------------
# 6. ВОПРОС О ЮРИСДИКЦИИ — ТОЛЬКО КОГДА ОТВЕТ МЕНЯЕТ ВЫБОР
# --------------------------------------------------------------------------


class ВопросОЮрисдикции(unittest.TestCase):
    def test_дороже_потолка_не_выиграет(self) -> None:
        выбран = _видео("cheap", 0.90)
        вне = pn.Candidate("held", (), 0, 0, 0, "", cost=стоит(2.40), territory_unasked=True)
        self.assertEqual(
            "с ней план стоит 3.94 usd — выше потолка ролика 3 usd",
            pn.отодвинутая_не_выиграет(выбран, вне, [выбран, вне], 2.44, 3.0, False),
        )
        # Обратное: потолок шире — встала бы, вопрос нужен.
        self.assertEqual(
            "", pn.отодвинутая_не_выиграет(выбран, вне, [выбран, вне], 2.44, 5.0, False)
        )
        # Без потолка и без «самого дешёвого» — встала бы.
        self.assertEqual(
            "", pn.отодвинутая_не_выиграет(выбран, вне, [выбран, вне], 2.44, None, False)
        )

    def test_живой_бриф_с_потолком_нота_а_не_вопрос(self) -> None:
        итог = pn.plan("lipsync a generated face to 30s English voiceover, budget $3", full=True)
        self.assertNotEqual("юрисдикция", (итог["question"] or {}).get("axis"))
        # Интеграция пятого круга (проверено как верное для продукта): генерацию
        # выигрывает `wan-3.0-t2v` по записанному бенчмарку, и у неё нет
        # модели, отодвинутой лицензией, — ни вопроса, ни ноты о юрисдикции нет
        # вовсе. Ветку «отодвинутая не выиграла бы под потолком — нота»
        # сторожит `test_дороже_потолка_не_выиграет` выше.
        self.assertNotIn("юрисдикц", итог["note"])
        self.assertNotIn("jurisdiction", итог["note"])
        шаг = next(ш for ш in итог["steps"] if ш["step"] == "генерация_видео")
        # Шестой круг: тариф по кадру-допущению 1080p — `wan-3.0-t2v` (6.00 usd)
        # выше потолка, выбор — `kling-3.0-standard-t2v` (2.52 usd без звука).
        self.assertEqual("kling-3.0-standard-t2v", шаг["chosen"]["model"])
        self.assertIsNone(шаг["licence_alternative"])

    def test_живой_бриф_без_потолка_вопрос_остаётся(self) -> None:
        итог = pn.plan("8s 1080p product teaser with native audio", full=True)
        self.assertEqual("юрисдикция", (итог["question"] or {}).get("axis"))


if __name__ == "__main__":
    unittest.main()
