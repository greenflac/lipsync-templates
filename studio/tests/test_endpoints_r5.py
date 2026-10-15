"""Реестр эндпоинтов, пятый круг (2026-10-15): кандидат шага — заказываемый эндпоинт его работы.

Диагноз валидатора круга 4, каждый пункт — литералом (Т2):

1. Узел семьи без своего маршрута не заказывается (`kling-3.0` без цены
   выбирался в 24 шагах); семья одалживает варианту применимость и длину
   прогона, но не цену.
2. Работа — из свидетельства (идентификатор, каталог, схема, документация,
   курированная строка со ссылкой); видеомодель не кандидат на липсинк, TTS —
   на шумы.
3. Новые работы (реставрация, удаление фона, интерполяция, расшифровка, клон
   голоса, оборот 360°, субтитры) — шаги маршрута по `spec.task`.
4. Цена «за прогон» — ceil(длительность / прогон); прогон не записан — семьи
   или осторожное допущение, и это сказано в расчёте.
5. «Самое дешёвое»: кандидат без цены — после всех с ценой.

Т4: сети нет. Т1: мутанты — `scripts/mutate_brief_spec.py` (раздел «реестр»).
"""

from __future__ import annotations

import unittest

from studio import brief_spec as bs
from studio import endpoints as ep
from studio import hardneed as hn
from studio import planner as pn
from studio import pricing
from studio.factindex import FactIndex
from studio.selfrag.facts import Fact
from studio.selfrag.modelnames import fold

FAL_API = "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id="


def факт(model: str, attribute: str, value: str, url: str = "", tier: str = "portal") -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=url or f"https://example.invalid/{model}",
        tier=tier,
        stated_on="2026-10-01",
    )


def на_фал(model: str, ид: str, категория: str) -> Fact:
    return факт(
        model,
        "availability",
        f"on fal.ai as {ид} ({категория}); listing status public",
        f"https://fal.ai/models/{ид}",
    )


def схема(model: str, ид: str, нужны: str, выход: str) -> list[Fact]:
    return [
        факт(model, "requires_inputs", нужны, FAL_API + ид),
        факт(model, "produces_outputs", выход, FAL_API + ид),
    ]


# --------------------------------------------------------------------------
# 1. РАБОТА ИЗ СВИДЕТЕЛЬСТВА


class Работа(unittest.TestCase):
    def test_работа_в_пути_старше_режима(self) -> None:
        rows = [
            на_фал(
                "kling-video-lipsync-text-to-video",
                "fal-ai/kling-video/lipsync/text-to-video",
                "video-to-video",
            )
        ]
        self.assertEqual(
            (("lipsync",), "id"), ep.classify("kling-video-lipsync-text-to-video", rows)[:2]
        )

    def test_tts_по_пути_площадки(self) -> None:
        rows = [на_фал("eleven_v3", "fal-ai/elevenlabs/tts/eleven-v3", "text-to-audio")]
        self.assertEqual((("tts",), "id"), ep.classify("eleven_v3", rows)[:2])

    def test_i2v_по_имени(self) -> None:
        self.assertEqual(
            (("i2v",), "id"),
            ep.classify("hunyuanvideo-i2v", [факт("hunyuanvideo-i2v", "license", "x")])[:2],
        )

    def test_ti2v_оба_режима(self) -> None:
        self.assertEqual(("t2v", "i2v"), ep.classify("wan-2.2-ti2v-5b", [])[0])

    def test_категория_когда_имя_молчит(self) -> None:
        rows = [на_фал("acme-one", "acme/one", "text-to-video")]
        self.assertEqual((("t2v",), "category"), ep.classify("acme-one", rows)[:2])

    def test_обязательный_звук_старше_категории(self) -> None:
        rows = [
            на_фал("acme-human", "acme/human", "image-to-video"),
            *схема("acme-human", "acme/human", "аудио, изображение", "видео"),
        ]
        self.assertEqual((("talking-avatar",), "shape"), ep.classify("acme-human", rows)[:2])

    def test_текст_рядом_со_звуком_не_меняет_работу(self) -> None:
        rows = [
            на_фал("acme-talk", "acme/talk", "video-to-video"),
            *схема("acme-talk", "acme/talk", "аудио, изображение, текст", "видео"),
        ]
        self.assertEqual(("talking-avatar",), ep.classify("acme-talk", rows)[0])

    def test_липсинк_по_схеме(self) -> None:
        rows = [
            на_фал("acme-sync", "acme/sync", "video-to-video"),
            *схема("acme-sync", "acme/sync", "аудио, видео", "видео"),
        ]
        self.assertEqual((("lipsync",), "shape"), ep.classify("acme-sync", rows)[:2])

    def test_режим_из_имени_атрибута_документации(self) -> None:
        rows = [факт("acme-gen", "ratio_enum_text_to_video", "1280:720", tier="vendor")]
        self.assertEqual((("t2v",), "docs"), ep.classify("acme-gen", rows)[:2])

    def test_имя_атрибута_не_вендора_не_свидетельство(self) -> None:
        rows = [факт("acme-gen", "ratio_enum_text_to_video", "1280:720", tier="blog")]
        self.assertEqual((), ep.classify("acme-gen", rows)[0])

    def test_правка_в_имени_атрибута_не_режим(self) -> None:
        rows = [факт("acme-gen2", "edit_strength", "0.5", tier="vendor")]
        self.assertEqual((), ep.classify("acme-gen2", rows)[0])

    def test_принимаемые_входы_дают_оба_режима(self) -> None:
        rows = [
            факт("acme-open", "accepts_inputs", "текст, изображение", tier="vendor"),
            факт("acme-open", "produces_outputs", "видео", tier="vendor"),
        ]
        self.assertEqual((("t2v", "i2v"), "shape"), ep.classify("acme-open", rows)[:2])

    def test_текст_в_аудио_не_раскладывается(self) -> None:
        rows = [*схема("acme-audio", "acme/audio", "текст", "аудио")]
        self.assertEqual((), ep.classify("acme-audio", rows)[0])

    def test_апскейл_видео_и_картинки_порознь(self) -> None:
        self.assertEqual(("upscale-video",), ep.classify("topaz-upscale-video-precision", [])[0])
        self.assertEqual(("upscale-image",), ep.classify("topaz-upscale-image-precision", [])[0])
        self.assertEqual(("upscale-image", "upscale-video"), ep.classify("acme-upscaler", [])[0])

    def test_правка_видео_не_правка_картинки(self) -> None:
        self.assertEqual(("v2v-edit",), ep.classify("happy-horse-edit-video", [])[0])
        self.assertEqual(("image-edit",), ep.classify("flux-3-edit", [])[0])

    def test_курированная_строка_перекрывает(self) -> None:
        работы, канал, нота = ep.classify(
            "veo-3.1", [на_фал("veo-3.1", "fal-ai/veo3.1", "video-to-video")]
        )
        self.assertEqual((("t2v", "i2v"), "curated"), (работы, канал))
        self.assertIn("https://ai.google.dev/gemini-api/docs/veo", нота)

    def test_без_свидетельства_пусто(self) -> None:
        self.assertEqual(
            ((), "", ""), ep.classify("acme-mystery", [факт("acme-mystery", "license", "mit")])
        )

    def test_новые_работы_по_пути(self) -> None:
        for имя, работа in (
            ("ltx-2.3-quality-colorization", "colorize"),
            ("bria-video-background-removal-v3", "bg-remove"),
            ("acme-rife-interpolation", "frame-interpolate"),
            ("elevenlabs-speech-to-text", "transcribe-diarize"),
            ("minimax-voice-clone", "voice-clone"),
            ("elevenlabs-sound-effects-v2", "sfx"),
            ("acme-turntable", "turntable-360"),
        ):
            with self.subTest(имя=имя):
                self.assertEqual((работа,), ep.classify(имя, [])[0])

    def test_утилиты_названные_по_себе_не_правка_картинки(self) -> None:
        """Интеграция пятого круга: площадка числит их «image-to-image», а работа другая."""
        for имя, ид, категория, работа in (
            ("bria-rmbg-2.0", "fal-ai/bria/background/remove", "image-to-image", "bg-remove"),
            ("ddcolor", "fal-ai/ddcolor", "image-to-image", "colorize"),
            ("film", "fal-ai/film", "image-to-image", "frame-interpolate"),
            ("film-video", "fal-ai/film/video", "video-to-video", "frame-interpolate"),
        ):
            with self.subTest(имя=имя):
                self.assertEqual((работа,), ep.classify(имя, [на_фал(имя, ид, категория)])[0])

    def test_живой_реестр_утилит_пятого_круга(self) -> None:
        """Строки входа/выхода утилит переписаны после того, как у плановщика
        появились их работы: у каждой работы есть заказываемые с ценой."""
        реестр = ep.build(FactIndex().facts)
        for работа, модели in (
            ("bg-remove", {"birefnet", "bria-rmbg-2.0"}),
            ("frame-interpolate", {"rife", "film", "film-video", "topaz-interpolate-video"}),
            ("colorize", {"ddcolor"}),
        ):
            with self.subTest(работа=работа):
                есть = {e.model for e in реестр.orderable_for(работа)}
                self.assertLessEqual(модели, есть)
                self.assertTrue(any(e.priced for e in реестр.orderable_for(работа)))
        self.assertEqual(("изображение",), реестр.get("birefnet").outputs)  # type: ignore[union-attr]


class КурированноеСоСсылкой(unittest.TestCase):
    """Курированная строка без своего адреса в базе — выдумка, а не прочитанное."""

    def test_источник_лежит_в_базе_под_этой_моделью(self) -> None:
        индекс = FactIndex()
        for модель, (_, почему, источник) in ep.CURATED.items():
            with self.subTest(модель=модель):
                адреса = {f.source_url for f in индекс.facts if fold(f.model) == fold(модель)}
                self.assertIn(источник, адреса)
                self.assertTrue(почему)


# --------------------------------------------------------------------------
# 2. УЗЕЛ СЕМЬИ, МАРШРУТ, ДЛИНА ПРОГОНА


def база_семьи() -> list[Fact]:
    return [
        факт("zeta-3.0", "max_seconds", "10", tier="vendor"),
        факт("zeta-3.0", "positioning", "text-to-video model family", tier="vendor"),
        факт("zeta-3.0", "failure_mode", "hands melt on fast motion", tier="operator"),
        на_фал("zeta-3.0-t2v", "zeta/v3/text-to-video", "text-to-video"),
        факт(
            "zeta-3.0-t2v",
            "price_per_second_usd",
            "$0.10 per second",
            "https://fal.ai/models/zeta/v3/text-to-video",
        ),
        на_фал("zeta-3.0-i2v", "zeta/v3/image-to-video", "image-to-video"),
        факт(
            "zeta-3.0-i2v",
            "price",
            "$0.49 per video generation",
            "https://fal.ai/models/zeta/v3/image-to-video",
        ),
        # Семья СО СВОЕЙ ценой у вендора и без своей работы.
        факт("omega-2", "price_per_second_usd", "$0.20 per second", tier="vendor"),
        факт("omega-2", "failure_mode", "faces smear in crowds", tier="operator"),
        на_фал("omega-2-t2v", "omega/v2/t2v", "text-to-video"),
        # Работа варианта — не режим семьи: семья липсинком не становится.
        на_фал("omega-2-lipsync", "omega/v2/lipsync", "video-to-video"),
        # Аватар-вариант семьи-генератора: строки генератора о нём не говорят.
        на_фал("zeta-3.0-avatar", "zeta/v3/avatar", "image-to-video"),
        факт(
            "zeta-3.0-avatar",
            "price_per_second_usd",
            "$0.30 per second",
            "https://fal.ai/models/zeta/v3/avatar",
        ),
    ]


class Семья(unittest.TestCase):
    def setUp(self) -> None:
        self.р = ep.build(база_семьи())

    def test_узел_семьи_без_маршрута_не_заказывается(self) -> None:
        e = self.р.get("zeta-3.0")
        assert e is not None
        self.assertEqual(
            (False, ("zeta-3.0-avatar", "zeta-3.0-i2v", "zeta-3.0-t2v")), (e.orderable, e.variants)
        )
        self.assertIn("узел семьи", e.why_not_orderable)

    def test_вариант_заказывается_и_знает_семью(self) -> None:
        e = self.р.get("zeta-3.0-t2v")
        assert e is not None
        self.assertEqual(
            (True, "zeta-3.0", ("t2v",), True), (e.orderable, e.family, e.functions, e.priced)
        )

    def test_длина_прогона_одалживается_семьёй(self) -> None:
        e = self.р.get("zeta-3.0-i2v")
        assert e is not None
        self.assertEqual((10.0, "семья zeta-3.0"), (e.run_s, e.run_basis))

    def test_цена_не_одалживается(self) -> None:
        e = self.р.get("zeta-3.0")
        assert e is not None
        self.assertEqual((False, ()), (e.priced, e.price_units))

    def test_семья_с_ценой_берёт_режимы_вариантов(self) -> None:
        e = self.р.get("omega-2")
        assert e is not None
        self.assertEqual((True, ("t2v",), "variants"), (e.orderable, e.functions, e.evidence))

    def test_работа_варианта_не_режим_семьи(self) -> None:
        e = self.р.get("omega-2")
        assert e is not None
        self.assertNotIn("lipsync", e.functions)

    def test_кэш_держит_базы_до_предела(self) -> None:
        # Литералы (Т2): восемь баз помещаются, девятая сбрасывает кэш.
        ep._КЭШ.clear()
        базы = [[факт(f"m-{i}", "license", "mit")] for i in range(9)]
        первый = ep.build(базы[0])
        for б in базы[1:8]:
            ep.build(б)
        self.assertIs(первый, ep.build(базы[0]))
        ep.build(базы[8])
        self.assertLessEqual(len(ep._КЭШ), 8)

    def test_индекс_работ_только_заказываемые(self) -> None:
        self.assertEqual(
            ["omega-2", "omega-2-t2v", "zeta-3.0-t2v"],
            sorted(e.model for e in self.р.orderable_for("t2v")),
        )

    def test_покрытие_по_работе(self) -> None:
        строка = next(r for r in ep.coverage(self.р) if r["function"] == "i2v")
        self.assertEqual(
            {
                "orderable": 1,
                "priced": 1,
                "priced_pct": 100.0,
                "with_run_length": 1,
                "run_length_pct": 100.0,
            },
            {
                к: строка[к]
                for к in ("orderable", "priced", "priced_pct", "with_run_length", "run_length_pct")
            },
        )


# --------------------------------------------------------------------------
# 3. ОТБОР КАНДИДАТОВ ПО РЕЕСТРУ


def операция(имя: str) -> pn.Operation:
    return next(о for о in pn.OPERATIONS if о.name == имя)


class Отбор(unittest.TestCase):
    def база(self) -> list[Fact]:
        return [
            *база_семьи(),
            # Видеомодель, о которой в наблюдениях говорят словами липсинка.
            факт("vidgen-i2v", "failure_mode", "lipsync drifts on talking heads", tier="operator"),
            факт("vidgen-i2v", "price_per_second_usd", "$0.05 per second", tier="vendor"),
            # Настоящий липсинк.
            на_фал("acme-sync", "acme/sync", "video-to-video"),
            *схема("acme-sync", "acme/sync", "аудио, видео", "видео"),
            факт(
                "acme-sync",
                "price_per_second_usd",
                "$0.10 per second",
                "https://fal.ai/models/acme/sync",
            ),
        ]

    def test_видеомодель_не_кандидат_на_липсинк(self) -> None:
        найдены = pn.candidates_for(операция("липсинк"), FactIndex(facts=self.база()))
        self.assertEqual(["acme-sync", "omega-2-lipsync"], [c.model for c in найдены])
        self.assertEqual(1, найдены.реестр["other_job_count"])
        self.assertEqual("vidgen-i2v", найдены.реестр["other_job"][0]["model"])

    def test_узел_семьи_не_кандидат_а_одалживает_применимость(self) -> None:
        найдены = pn.candidates_for(операция("генерация_видео"), FactIndex(facts=self.база()))
        имена = [c.model for c in найдены]
        self.assertNotIn("zeta-3.0", имена)
        вариант = next(c for c in найдены if c.model == "zeta-3.0-t2v")
        self.assertEqual(1, вариант.applicability)
        self.assertEqual(["zeta-3.0"], [м["model"] for м in найдены.реестр["not_orderable"]])

    #: Шестой круг: узел без маршрута не заказывается вовсе, поэтому у
    #: «неустановленной» модели есть маршрут — строка цены у продавца.
    ЦЕНА_ЗАГАДКИ = факт(
        "mystery-model", "price_per_second_usd", "$0.10 per second", "https://mystery.example/pricing"
    )

    def test_без_установленной_работы_не_кандидат_когда_реестр_знает_работу(self) -> None:
        база = [
            *self.база(),
            факт("mystery-model", "failure_mode", "lipsync drifts on long takes", tier="operator"),
            self.ЦЕНА_ЗАГАДКИ,
        ]
        найдены = pn.candidates_for(операция("липсинк"), FactIndex(facts=база))
        self.assertNotIn("mystery-model", [c.model for c in найдены])
        self.assertEqual(["mystery-model"], найдены.реестр["unclassified_dropped"])

    def test_без_установленной_работы_остаётся_когда_реестр_работы_не_знает(self) -> None:
        база = [
            факт("mystery-model", "failure_mode", "lipsync drifts on long takes", tier="operator"),
            self.ЦЕНА_ЗАГАДКИ,
        ]
        найдены = pn.candidates_for(операция("липсинк"), FactIndex(facts=база))
        self.assertEqual([("mystery-model", True)], [(c.model, c.unclassified) for c in найдены])

    def test_без_маршрута_не_кандидат(self) -> None:
        """Шестой круг: та же модель без строки цены — маршрута нет, кандидата нет."""
        база = [
            *self.база(),
            факт("mystery-model", "failure_mode", "lipsync drifts on long takes", tier="operator"),
        ]
        найдены = pn.candidates_for(операция("липсинк"), FactIndex(facts=база))
        self.assertNotIn("mystery-model", [c.model for c in найдены])
        self.assertIn("mystery-model", [м["model"] for м in найдены.реестр["not_orderable"]])

    def test_работы_пятого_круга_только_из_реестра(self) -> None:
        база = [
            факт(
                "mystery-model",
                "failure_mode",
                "frame interpolation ghosts on fast motion",
                tier="operator",
            ),
            self.ЦЕНА_ЗАГАДКИ,
        ]
        найдены = pn.candidates_for(операция("интерполяция_кадров"), FactIndex(facts=база))
        self.assertEqual([], [c.model for c in найдены])
        self.assertEqual(1, найдены.реестр["unclassified_dropped_count"])

    def test_заказываемая_семья_не_одалживает(self) -> None:
        найдены = pn.candidates_for(операция("генерация_видео"), FactIndex(facts=self.база()))
        вариант = next(c for c in найдены if c.model == "omega-2-t2v")
        self.assertEqual(0, вариант.applicability)

    def test_аватар_вариант_не_берёт_строк_генератора(self) -> None:
        найдены = pn.candidates_for(операция("говорящий_аватар"), FactIndex(facts=self.база()))
        вариант = next(c for c in найдены if c.model == "zeta-3.0-avatar")
        self.assertEqual(0, вариант.applicability)

    def test_узел_семьи_с_весами_кандидат_на_своём_gpu(self) -> None:
        база = [
            факт("kappa-1", "positioning", "text-to-video model family", tier="vendor"),
            факт(
                "kappa-1",
                "license",
                "apache-2.0",
                "https://huggingface.co/acme/kappa-1",
                tier="vendor",
            ),
            на_фал("kappa-1-t2v", "acme/kappa-1/text-to-video", "text-to-video"),
            факт(
                "kappa-1-t2v",
                "price_per_second_usd",
                "$0.10 per second",
                "https://fal.ai/models/acme/kappa-1/text-to-video",
            ),
        ]
        e = ep.build(база).get("kappa-1")
        assert e is not None
        # Седьмой круг (валидатор v7, `flux.2-klein-9b`): у узла семьи СВОЯ
        # страница весов с лицензией — это опубликованный чекпойнт, и маршрут
        # «запустить у себя» у него есть (прежде: не заказывался вовсе).
        self.assertEqual(
            (True, True, (("self-host", "https://huggingface.co/acme/kappa-1"),)),
            (e.orderable, e.self_hostable, e.route_ids),
        )
        op = операция("генерация_видео")
        через_api = [c.model for c in pn.candidates_for(op, FactIndex(facts=база))]
        свой_gpu = [
            c.model
            for c in pn.candidates_for(op, FactIndex(facts=база), hard=hn.Hard(self_host=True))
        ]
        self.assertEqual((False, True), ("kappa-1" in через_api, "kappa-1" in свой_gpu))

    def test_аватар_вариант_не_берёт_строк_семьи_без_работы(self) -> None:
        # Узел семьи без установленной работы одалживает строки только режимам
        # генерации: аватар-вариант их не берёт.
        база = [
            факт("theta-2", "failure_mode", "faces smear in crowds", tier="operator"),
            на_фал("theta-2-t2v", "acme/theta-2/text-to-video", "text-to-video"),
            на_фал("theta-2-avatar", "acme/theta-2/avatar", "image-to-video"),
        ]
        self.assertEqual((), ep.build(база).get("theta-2").functions)  # type: ignore[union-attr]
        аватар = next(
            c
            for c in pn.candidates_for(операция("говорящий_аватар"), FactIndex(facts=база))
            if c.model == "theta-2-avatar"
        )
        генератор = next(
            c
            for c in pn.candidates_for(операция("генерация_видео"), FactIndex(facts=база))
            if c.model == "theta-2-t2v"
        )
        self.assertEqual((0, 1), (аватар.applicability, генератор.applicability))

    def test_реестр_добавляет_не_найденных_словами(self) -> None:
        # У `zeta-3.0-t2v` нет ни одного слова операции в строках — только каталог
        # и имя: работа установлена идентификатором.
        найдены = pn.candidates_for(операция("генерация_видео"), FactIndex(facts=self.база()))
        вариант = next(c for c in найдены if c.model == "zeta-3.0-t2v")
        self.assertEqual("t2v: id — zeta-3.0-t2v; zeta/v3/text-to-video", вариант.registry_note)

    def test_запасная_работа_оборота(self) -> None:
        работы, нота = pn.работы_шага(операция("оборот_360"), ep.build(self.база()))
        self.assertEqual(("i2v",), работы)
        self.assertIn("orbiting camera", нота)


class Ранг(unittest.TestCase):
    def кандидат(self, имя: str, usd: float | None, **поля: object) -> pn.Candidate:
        цена = None
        if usd is not None:
            o = pricing.Option(usd, "", None, f"{usd} usd")
            цена = pn.Стоимость((o,), o, o, "test")
        поля = {"applicability": 0, **поля}
        return pn.Candidate(
            model=имя,
            evidence=(),
            capability=0,
            unresolved=0,
            price="",
            cost=цена,
            **поля,
        )  # type: ignore[arg-type]

    def test_самое_дешёвое_без_цены_последним(self) -> None:
        без = self.кандидат("a-model", None, unpriced_last=True)
        с_ценой = self.кандидат("z-model", 9.0, unpriced_last=True)
        self.assertEqual(
            ["z-model", "a-model"], [c.model for c in sorted([без, с_ценой], key=pn.by_evidence)]
        )

    def test_при_равных_доводах_цена_старше(self) -> None:
        """Шестой круг: и без «самого дешёвого» записанная цена при равных
        доводах старше незаписанной (`birefnet-v2-video` против Bria $0.05/с)."""
        без = self.кандидат("a-model", None)
        с_ценой = self.кандидат("z-model", 9.0)
        self.assertEqual(
            ["z-model", "a-model"], [c.model for c in sorted([без, с_ценой], key=pn.by_evidence)]
        )

    def test_доводы_старше_цены(self) -> None:
        """…но строка применимости старше цены: цена решает только при равных доводах."""
        без = self.кандидат("a-model", None, applicability=1)
        с_ценой = self.кандидат("z-model", 9.0)
        self.assertEqual(
            ["a-model", "z-model"], [c.model for c in sorted([без, с_ценой], key=pn.by_evidence)]
        )

    def test_нижняя_граница_не_цена(self) -> None:
        o = pricing.Option(0.49, "", None, "f", lower_bound=pricing.LOWER_BOUND_RUN)
        c = pn.Candidate(
            model="m",
            evidence=(),
            applicability=0,
            capability=0,
            unresolved=0,
            price="",
            cost=pn.Стоимость((o,), o, o, "t"),
        )
        self.assertFalse(pn.цена_есть(c))

    def test_ступени_работы(self) -> None:
        своя = self.кандидат("c", 1.0)
        неустановленная = self.кандидат("b", 1.0, unclassified=True)
        чужая = self.кандидат("a", 1.0, foreign=True)
        self.assertEqual(
            ["c", "b", "a"],
            [c.model for c in sorted([чужая, неустановленная, своя], key=pn.by_evidence)],
        )
        self.assertEqual((1, 2), (pn.UNCLASSIFIED_RANK, pn.FOREIGN_RANK))


# --------------------------------------------------------------------------
# 4. ПРОГОНЫ


HAILUO = "Your request will cost $0.49 per video generation."


class Прогоны(unittest.TestCase):
    def test_допущение_без_записи_и_семьи(self) -> None:
        self.assertEqual(
            (
                5.0,
                "длина прогона не записана ни у модели, ни у семьи — допущено 5 с (осторожно: больше прогонов)",
            ),
            pn.запасной_прогон(операция("генерация_видео"), None, []),
        )

    def test_не_видео_без_допущения(self) -> None:
        self.assertIsNone(pn.запасной_прогон(операция("клонирование_голоса"), None, []))

    def test_своя_запись_без_допущения(self) -> None:
        self.assertIsNone(
            pn.запасной_прогон(операция("генерация_видео"), None, [факт("m", "max_seconds", "10")])
        )

    def test_600_секунд_по_049_за_прогон(self) -> None:
        need = pricing.Need(seconds=600, max_run_seconds=5.0, run_basis="допущение")
        (o,) = pricing.estimate(pricing.rates(HAILUO, "price"), need)
        self.assertEqual((58.8, ""), (round(o.usd, 4), o.lower_bound))
        self.assertIn("прогон = 5 с; допущение", o.formula)

    def test_семья_даёт_прогон_цене(self) -> None:
        р = ep.build(база_семьи())
        все = [f for f in база_семьи() if f.model == "zeta-3.0-i2v"]
        запас = pn.запасной_прогон(операция("оживление"), р.get("zeta-3.0-i2v"), все)
        self.assertEqual((10.0, "длина прогона — семья zeta-3.0: 10 с"), запас)
        сколько = pn.стоимость(все, pricing.Need(seconds=60), запас)
        assert сколько is not None
        self.assertEqual(2.94, round(сколько.default.usd, 4))
        self.assertIn("семья zeta-3.0", сколько.default.formula)


# --------------------------------------------------------------------------
# 5. МАРШРУТ НОВЫХ РАБОТ


class Маршрут(unittest.TestCase):
    def шаги(self, задача: str, входы: list[str]) -> tuple[str, ...]:
        spec, ошибки = bs.parse_spec({"task": задача, "inputs": входы})
        self.assertEqual([], ошибки)
        return bs.route(spec).шаги

    def test_работы_над_материалом(self) -> None:
        self.assertEqual(("реставрация",), self.шаги("restore", ["video"]))
        self.assertEqual(("интерполяция_кадров",), self.шаги("interpolate", ["video"]))
        self.assertEqual(("удаление_фона",), self.шаги("remove-background", ["photo"]))
        self.assertEqual(("удаление_фона_видео",), self.шаги("remove-background", ["video"]))
        self.assertEqual(("расшифровка",), self.шаги("transcribe", ["audio"]))
        self.assertEqual(("клонирование_голоса",), self.шаги("voice-clone", ["audio", "script"]))
        self.assertEqual(("оборот_360",), self.шаги("turntable", ["photo"]))

    def test_субтитры_вжигает_монтаж(self) -> None:
        spec, _ = bs.parse_spec({"task": "captions", "inputs": ["video"]})
        маршрут = bs.route(spec)
        self.assertEqual(
            (("расшифровка",), bs.NOTE_CAPTIONS), (маршрут.шаги, маршрут.пометки["расшифровка"])
        )

    def test_нет_входа_вопрос(self) -> None:
        spec, _ = bs.parse_spec({"task": "voice-clone", "inputs": []})
        маршрут = bs.route(spec)
        self.assertEqual(
            ((), "вход_задачи"), (маршрут.шаги, маршрут.нехватка[0] if маршрут.нехватка else None)
        )

    def test_у_каждого_шага_маршрута_есть_работа(self) -> None:
        for варианты in bs.ROUTE_TASKS.values():
            for _, шаг in варианты:
                with self.subTest(шаг=шаг):
                    self.assertIn(шаг, pn.ФУНКЦИЯ_ОПЕРАЦИИ)
                    операция(шаг)

    def test_новые_шаги_подсказками_не_выводятся(self) -> None:
        for имя in (
            "реставрация",
            "интерполяция_кадров",
            "удаление_фона",
            "расшифровка",
            "клонирование_голоса",
            "оборот_360",
        ):
            with self.subTest(имя=имя):
                self.assertEqual((), операция(имя).cues)


# --------------------------------------------------------------------------
# 6. ГЕЙТ ПОКРЫТИЯ (`scripts/endpoint_report.py`)


def _отчёт():  # type: ignore[no-untyped-def]
    import importlib.util
    from pathlib import Path

    путь = Path(__file__).resolve().parents[2] / "scripts" / "endpoint_report.py"
    spec = importlib.util.spec_from_file_location("endpoint_report", путь)
    assert spec is not None and spec.loader is not None
    модуль = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(модуль)
    return модуль


class ГейтПокрытия(unittest.TestCase):
    СТРОКА = {"function": "t2v", "orderable": 10, "priced": 8, "with_run_length": 7}

    def test_падение_любого_счёта_провал(self) -> None:
        отчёт = _отчёт()
        for поле in ("orderable", "priced", "with_run_length"):
            with self.subTest(поле=поле):
                сейчас = [{**self.СТРОКА, поле: self.СТРОКА[поле] - 1}]
                упало, _ = отчёт.compare(сейчас, [self.СТРОКА])
                self.assertEqual(
                    [f"t2v.{поле}: {self.СТРОКА[поле]} -> {self.СТРОКА[поле] - 1}"], упало
                )

    def test_рост_не_провал(self) -> None:
        упало, выросло = _отчёт().compare([{**self.СТРОКА, "priced": 9}], [self.СТРОКА])
        self.assertEqual(([], ["t2v.priced: 8 -> 9"]), (упало, выросло))

    def test_живая_база_не_ниже_записанного(self) -> None:
        self.assertEqual(0, _отчёт().main(["--check"]))


# --------------------------------------------------------------------------
# 7. ЖИВАЯ БАЗА: находки валидатора круга 4 не возвращаются


class ЖиваяБаза(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.индекс = FactIndex()
        cls.реестр = ep.build(cls.индекс.facts)

    def test_kling_3_0_не_заказывается(self) -> None:
        e = self.реестр.get("kling-3.0")
        assert e is not None
        self.assertFalse(e.orderable)

    def test_липсинк_не_видеомодель(self) -> None:
        найдены = pn.candidates_for(операция("липсинк"), self.индекс)
        self.assertNotIn("hunyuanvideo-i2v", [c.model for c in найдены])
        self.assertTrue(найдены)
        for c in найдены[:5]:
            e = self.реестр.get(c.model)
            self.assertTrue(e is None or not e.functions or "lipsync" in e.functions, c.model)

    def test_шумы_не_tts(self) -> None:
        найдены = pn.candidates_for(операция("звук_фон"), self.индекс)
        self.assertNotIn("eleven_v3", [c.model for c in найдены])

    def test_самое_дешёвое_выбирает_с_ценой(self) -> None:
        жёсткие = hn.Hard(objective=hn.OBJECTIVE_CHEAPEST)
        need = pn.нужда_шага(операция("генерация_видео"), pn.dur.Запрос(60.0, "60 с"), (1920, 1080))
        найдены = pn.candidates_for(
            операция("генерация_видео"), self.индекс, need=need, hard=жёсткие
        )
        self.assertTrue(pn.цена_есть(найдены[0]), найдены[0].model)


if __name__ == "__main__":
    unittest.main()
