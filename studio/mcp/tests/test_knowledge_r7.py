"""Седьмой круг (валидатор v7): `find_models` применяет записанное, ранжирование помнит провалы.

Что сторожится, и всё литералами (Т2):

1. язык — через нормализатор BCP-47 плановщика (`brief_spec.language_tag`):
   `kk`, `kazakh`, `he`, `hebrew`, `pt-BR` больше не «не поняты»;
2. знак по ЗНАЧЕНИЮ против спрошенного: нативный звук (`audio_output`),
   частота кадров и множитель частоты (с исходной частотой и без неё),
   память GPU («12GB» — против строк VRAM и нижней границы по параметрам);
3. правка, НАЗВАННАЯ идентификатором эндпоинта (`clean-plate`), — хорошая
   новость с пометкой `catalog` (способность, не применимость);
4. `open` без записи о весах — отсеяна в `excluded_unknown`, а не «прошла»;
5. плановщик: записанный провал не обгоняет объявленную хорошую новость без
   провалов (дубляж: sync-3, а не sync-lipsync v2), длина одним прогоном и
   число прогонов (8-минутный аватар: hedra, а не omnihuman-1.5);
6. юрисдикция: хостинг записан — судится, не записан — строка «не измерено»;
7. промахи реестра (живая база): Flash v2 — TTS, Kontext multi — правка
   картинки, FLUX.2 klein 9B — заказывается «у себя», субтитры и реставрация
   с ценой; описание `find_models` перечисляет ровно работы реестра.
"""

from __future__ import annotations

import unittest
from typing import Any

from studio import endpoints as ep
from studio import planner as pn
from studio.duration import DUR_IN, DUR_OVER
from studio.mcp import capability, server
from studio.selfrag.facts import Fact

HF = "https://huggingface.co"
FAL = "https://fal.ai/models"


def _f(
    model: str,
    attribute: str,
    value: str,
    tier: str = "vendor",
    url: str = "",
    contra: bool | None = None,
) -> Fact:
    return Fact(
        model,
        attribute,
        value,
        url or f"https://{model}.test/{attribute}",
        tier,
        "2026-10-01",
        contra=contra,
    )


def _на_фал(model: str, endpoint: str, category: str) -> Fact:
    return _f(
        model,
        "availability",
        f"on fal.ai as {endpoint} ({category}); listing status public",
        "portal",
        f"{FAL}/{endpoint}",
    )


БАЗА = [
    # --- TTS: языки вне словаря базы -------------------------------------------------
    _f("kaz-tts", "languages", "Kazakh, Russian, English"),
    _f("iso-tts", "languages", "en, ru, kk, uz, de"),
    _f("only-en-tts", "languages", "English only"),
    _f("br-tts", "languages", "Portuguese (Brazil), Spanish"),
    _f("mute-tts", "positioning", "fast speech synthesis", "portal"),
    _f("he-voice-clone", "languages", "Hebrew, Arabic, English"),
    _f("nohe-voice-clone", "languages", "English, German, French, Spanish"),
    # --- t2v: нативный звук -----------------------------------------------------------
    _f("loud-t2v", "audio_output", "native audio, always on (generated together with the video)"),
    _f(
        "switch-t2v",
        "audio_output",
        "native audio switch: schema field generate_audio (default true)",
        "portal",
    ),
    _f("silent-t2v", "audio_output", "no audio: silent video only"),
    _f("plain-t2v", "positioning", "text-to-video drafts", "portal"),
    # --- интерполяция: частота и множитель ---------------------------------------------
    _f(
        "turbo-interpolate", "frame_rate", "target_fps 16 to 120 fps (schema maximum 120)", "portal"
    ),
    _f("mult-interpolate", "frame_multiplier", "up to 4x input fps (num_frames 1-4)", "portal"),
    _f("blank-interpolate", "positioning", "frame interpolation", "portal"),
    # --- i2v: память GPU и открытые веса ----------------------------------------------
    _f("small-i2v", "license", "Apache-2.0", url=f"{HF}/acme/small-i2v"),
    _f("small-i2v", "min_vram_gb", "8 GB with model offloading"),
    _f("big-i2v", "license", "Apache-2.0", url=f"{HF}/acme/big-i2v"),
    _f("big-i2v", "parameter_count", "33.1B"),
    _f("mid-i2v", "license", "MIT", url=f"{HF}/acme/mid-i2v"),
    _f("mid-i2v", "min_vram_gb", "14 (with model offloading)"),
    _f("t5-i2v", "license", "MIT", url=f"{HF}/acme/t5-i2v"),
    _f("t5-i2v", "min_vram_gb", "24 (e.g. RTX 4090), with --offload_model --t5_cpu"),
    _f("nomem-i2v", "license", "Apache-2.0", url=f"{HF}/acme/nomem-i2v"),
    _f("unknown-i2v", "positioning", "image-to-video for ads", "portal"),
    # --- правка видео: названная и по инструкции ---------------------------------------
    _на_фал("acme-clean-plate", "acme/video/clean-plate", "video-to-video"),
    _на_фал("acme-edit-video", "acme/video/edit", "video-to-video"),
    _на_фал("acme-extend-video", "acme/video/extend", "video-to-video"),
]


def _найти(need: str, function: str = "", terms: str = "", require: str = "", **kw) -> dict:
    return capability.find(need, function, terms, require, 8, facts=БАЗА, **kw)


def _верх(итог: dict, n: int = 3) -> list[str]:
    return [r["model"] for r in итог["ranked"][:n]]


#: (need, function, terms, require, исход, верх). EN и RU. Литералы (Т2).
ВОПРОСЫ: list[tuple[str, str, str, str, str, list[str]]] = [
    # 1-8: язык вне словаря базы
    ("Kazakh speech synthesis", "tts", "", "kk", "pass", ["iso-tts", "kaz-tts"]),
    ("speech synthesis", "tts", "", "kazakh", "pass", ["iso-tts", "kaz-tts"]),
    ("TTS", "tts", "", "kk-KZ", "pass", ["iso-tts", "kaz-tts"]),
    ("синтез казахской речи", "tts", "", "", "pass", ["iso-tts", "kaz-tts"]),
    ("Brazilian Portuguese voiceover", "tts", "", "pt-BR", "pass", ["br-tts"]),
    ("voice cloning that works in Hebrew", "voice-clone", "", "he", "pass", ["he-voice-clone"]),
    ("voice cloning", "voice-clone", "", "hebrew", "pass", ["he-voice-clone"]),
    ("клонирование голоса на иврите", "voice-clone", "", "", "pass", ["he-voice-clone"]),
    # 9-13: нативный звук
    (
        "text-to-video with native audio and dialogue",
        "t2v",
        "native audio, dialogue",
        "",
        "pass",
        ["loud-t2v", "switch-t2v", "silent-t2v"],
    ),
    ("t2v that generates audio", "t2v", "", "", "pass", ["loud-t2v", "switch-t2v", "silent-t2v"]),
    (
        "видео по тексту с нативным звуком",
        "t2v",
        "",
        "",
        "pass",
        ["loud-t2v", "switch-t2v", "silent-t2v"],
    ),
    ("video with synced audio", "t2v", "", "", "pass", ["loud-t2v", "switch-t2v", "silent-t2v"]),
    ("t2v со звуком", "t2v", "", "", "pass", ["loud-t2v", "switch-t2v", "silent-t2v"]),
    # 14-17: частота кадров
    (
        "frame interpolation to 120fps",
        "frame-interpolate",
        "fps",
        "",
        "pass",
        ["turbo-interpolate", "mult-interpolate"],
    ),
    (
        "interpolate from 30 to 120 fps",
        "frame-interpolate",
        "",
        "",
        "pass",
        ["mult-interpolate", "turbo-interpolate"],
    ),
    (
        "interpolate from 24 to 120 fps",
        "frame-interpolate",
        "",
        "",
        "pass",
        ["turbo-interpolate", "mult-interpolate"],
    ),
    (
        "интерполяция кадров до 120 fps",
        "frame-interpolate",
        "",
        "",
        "pass",
        ["turbo-interpolate", "mult-interpolate"],
    ),
    # 18-21: память GPU
    ("which i2v runs on 12GB VRAM", "i2v", "vram, 12GB", "open", "pass", ["small-i2v"]),
    ("i2v for an RTX 3060", "i2v", "", "open", "pass", ["small-i2v"]),
    (
        "какая i2v запускается на видеокарте 12 ГБ, открытые веса",
        "i2v",
        "",
        "",
        "pass",
        ["small-i2v"],
    ),
    # Равные (вендор, одна дата) — по имени: mid раньше small.
    ("i2v on a 48GB card", "i2v", "vram", "open", "pass", ["mid-i2v", "small-i2v", "t5-i2v"]),
    # 22-25: удаление объекта
    (
        "video object removal / inpainting",
        "v2v-edit",
        "object removal, inpainting",
        "",
        "pass",
        ["acme-clean-plate", "acme-edit-video"],
    ),
    (
        "remove an object from my video",
        "v2v-edit",
        "",
        "",
        "pass",
        ["acme-clean-plate", "acme-edit-video"],
    ),
    (
        "удаление объектов из видео",
        "v2v-edit",
        "",
        "",
        "pass",
        ["acme-clean-plate", "acme-edit-video"],
    ),
    ("clean plate for a shot", "v2v-edit", "", "", "pass", ["acme-clean-plate", "acme-edit-video"]),
    # 26-27: честное «не смогли»
    ("Kazakh TTS", "tts", "", "kk, open", "could not measure", []),
    ("i2v on a 4GB card", "i2v", "vram, 4GB", "open", "could not measure", []),
]


class ВопросыСедьмогоКруга(unittest.TestCase):
    def test_исход_и_верх(self) -> None:
        self.assertGreaterEqual(len(ВОПРОСЫ), 25)
        for need, function, terms, require, исход, верх in ВОПРОСЫ:
            with self.subTest(need=need, require=require):
                итог = _найти(need, function, terms, require)
                self.assertEqual(исход, итог["outcome"])
                self.assertEqual(верх, _верх(итог, len(верх)) if верх else [])
                self.assertEqual([], итог["require_not_understood"])


class Языки(unittest.TestCase):
    def test_слово_требования_становится_языком(self) -> None:
        self.assertEqual(
            ["kk", "kk", "he", "he", "portuguese", "russian", "kk", ""],
            [
                capability.язык_слова(с)
                for с in ("kk", "kazakh", "he", "hebrew", "pt-BR", "ru", "казахский", "12gb")
            ],
        )

    def test_гигабайты_вне_слов_о_памяти_не_память(self) -> None:
        self.assertEqual(
            [None, 12.0, 12.0, 24.0],
            [
                capability._память("upload a 5GB video and remove the background"),
                capability._память("runs on 12GB"),
                capability._память("12gb", требование=True),
                capability._память("on one RTX 4090"),
            ],
        )

    def test_исключительный_список_отсеивает_kk(self) -> None:
        итог = _найти("Kazakh TTS", "tts", "", "kk")
        self.assertEqual(
            [{"model": "only-en-tts", "why": "languages: kk not in an exclusive list"}],
            итог["gaps"]["excluded_examples"],
        )

    def test_нет_hebrew_в_списке_языков_не_хорошая_новость(self) -> None:
        итог = _найти("voice cloning", "voice-clone", "", "he")
        строка = next(r for r in итог["ranked"] if r["model"] == "nohe-voice-clone")
        self.assertEqual(
            ("informational_only", "could not measure"),
            (строка["verdict"], строка["requirements"]["he"]["outcome"]),
        )


class ЗнакПоЗначению(unittest.TestCase):
    def test_звук_нет_это_плохо(self) -> None:
        итог = _найти("t2v with native audio", "t2v")
        тихая = next(r for r in итог["ranked"] if r["model"] == "silent-t2v")
        self.assertEqual("bad_news_only", тихая["verdict"])
        громкая = итог["ranked"][0]
        self.assertIn("not measured applicability", громкая["good"][0]["why"])
        self.assertEqual(["plain-t2v"], итог["gaps"]["examples"])

    def test_множитель_без_исходника_информация_с_порогом(self) -> None:
        итог = _найти("frame interpolation to 120fps", "frame-interpolate", "fps")
        м = next(r for r in итог["ranked"] if r["model"] == "mult-interpolate")
        self.assertEqual("informational_only", м["verdict"])
        self.assertIn(">= 30 fps", м["informational"][0]["why"])

    def test_множитель_с_исходником_считается(self) -> None:
        за = next(
            r
            for r in _найти("interpolate from 30 to 120 fps", "frame-interpolate")["ranked"]
            if r["model"] == "mult-interpolate"
        )
        против = next(
            r
            for r in _найти("interpolate from 24 to 120 fps", "frame-interpolate")["ranked"]
            if r["model"] == "mult-interpolate"
        )
        self.assertEqual(("good_news_only", "bad_news_only"), (за["verdict"], против["verdict"]))
        self.assertEqual("x4 of 30 fps = 120 fps >= asked 120", за["good"][0]["why"])

    def test_память_отсеивает_и_не_ранжирует_лицензией(self) -> None:
        итог = _найти("which i2v runs on 12GB VRAM", "i2v", "vram, 12GB", "open")
        self.assertEqual(
            ["big-i2v", "mid-i2v", "t5-i2v"],
            sorted(e["model"] for e in итог["gaps"]["excluded_examples"]),
        )
        self.assertEqual(
            ["unknown-i2v"], [e["model"] for e in итог["gaps"]["excluded_unknown_examples"]]
        )
        # Лицензия подтверждена, но о памяти не записано ничего — пробел, а не довод.
        self.assertEqual(["nomem-i2v"], итог["gaps"]["examples"])
        self.assertEqual(["min_vram_gb"], [g["attribute"] for g in итог["ranked"][0]["good"]])
        self.assertEqual(["open", "vram<=12GB"], итог["require"])

    def test_оценка_снизу_не_влезает_а_не_измерено(self) -> None:
        итог = _найти("i2v on a 48GB card", "i2v", "vram", "open")
        большая = next(r for r in итог["ranked"] if r["model"] == "big-i2v")
        self.assertEqual(
            ("informational_only", "could not measure"),
            (большая["verdict"], большая["requirements"]["vram<=48GB"]["outcome"]),
        )
        self.assertIn("lower bound", большая["requirements"]["vram<=48GB"]["why"])

    def test_t5_не_пять_гигабайт(self) -> None:
        from studio import hardneed as hn

        self.assertEqual(24.0, hn.vram_need([БАЗА[[f.model for f in БАЗА].index("t5-i2v") + 1]])[0])

    def test_правка_названная_идентификатором_каталог(self) -> None:
        итог = _найти("video object removal", "v2v-edit")
        верх = итог["ranked"][0]
        self.assertEqual(
            ("good_news_only", "catalog"), (верх["verdict"], верх["good"][0]["polarity"])
        )
        второй = итог["ranked"][1]
        self.assertEqual("informational_only", второй["verdict"])
        self.assertEqual(["acme-extend-video"], итог["gaps"]["examples"])

    def test_только_требования_лицензия_и_есть_ответ(self) -> None:
        итог = _найти("open-weights image-to-video", "i2v", "", "open")
        self.assertEqual("pass", итог["outcome"])
        self.assertEqual("license", итог["ranked"][0]["good"][0]["attribute"])


class Ранжирование(unittest.TestCase):
    """Плановщик: провал против объявленной хорошей новости, прогоны, один дубль."""

    @staticmethod
    def _c(model: str, **kw: Any) -> pn.Candidate:
        поля: dict[str, Any] = {
            "evidence": (),
            "applicability": 0,
            "capability": 0,
            "unresolved": 0,
            "price": "",
        }
        поля.update(kw)
        return pn.Candidate(model=model, **поля)

    def test_провал_ниже_объявленной_похвалы(self) -> None:
        v2 = self._c("sync-lipsync", applicability=3, against=1)
        v3 = self._c("sync-lipsync-v3", declared_good=2)
        self.assertEqual((1, 0), (pn.failure_rank(v2), pn.failure_rank(v3)))
        self.assertLess(pn.by_evidence(v3), pn.by_evidence(v2))
        self.assertIn(pn.FAILURE_KEY_FIELD, pn.why_not(v3, v2))

    def test_молчание_без_похвалы_по_прежнему_ниже_провала(self) -> None:
        v2 = self._c("sync-lipsync", applicability=3, against=1)
        молчит = self._c("veed-lipsync")
        self.assertEqual(1, pn.failure_rank(молчит))
        self.assertLess(pn.by_evidence(v2), pn.by_evidence(молчит))

    def test_похвала_с_провалом_не_чиста(self) -> None:
        self.assertEqual(
            1, pn.failure_rank(self._c("x", applicability=2, against=1, declared_good=3))
        )

    def test_один_дубль_чище_кусков(self) -> None:
        self.assertEqual(0, pn.failure_rank(self._c("hedra", one_take=True)))

    def test_прогонов(self) -> None:
        self.assertEqual(
            [8, 1, 1, 1, 2, 16],
            [
                pn.прогонов(480, 60),
                pn.прогонов(480, 600),
                pn.прогонов(None, 60),
                pn.прогонов(60, 60),
                pn.прогонов(61, 60),
                pn.прогонов(480, 30),
            ],
        )

    def test_меньше_прогонов_при_равных_доводах(self) -> None:
        один = self._c("a", runs=1)
        шестнадцать = self._c("b", runs=16)
        self.assertLess(pn.by_evidence(один), pn.by_evidence(шестнадцать))
        self.assertIn(pn.RUNS_KEY_FIELD, pn.why_not(один, шестнадцать))

    def test_один_дубль_только_на_аватаре_и_только_при_кусках(self) -> None:
        аватар = next(op for op in pn.OPERATIONS if op.name == "говорящий_аватар")
        липсинк = next(op for op in pn.OPERATIONS if op.name == "липсинк")
        найдены = [
            self._c("omni", runs=8, run_s=60.0, dur_state=DUR_OVER),
            self._c("hedra", runs=1, run_s=600.0, dur_state=DUR_IN),
            self._c("quiet", runs=1),
        ]
        self.assertEqual([False, True, False], [c.one_take for c in pn.один_дубль(найдены, аватар)])
        self.assertEqual(
            [False, False, False], [c.one_take for c in pn.один_дубль(найдены, липсинк)]
        )
        без_кусков = [найдены[1], найдены[2]]
        self.assertEqual([False, False], [c.one_take for c in pn.один_дубль(без_кусков, аватар)])

    def test_объявленная_похвала_считается_без_цены(self) -> None:
        строки = [
            _f("m", "pose_range", "Native", contra=False),
            _f("m", "price_per_second", "$0.1", contra=False),
            _f("m", "failure_mode", "mouth smears", contra=True),
            _f("m", "positioning", "lipsync"),
        ]
        self.assertEqual(1, pn.declared_good(строки))


class Юрисдикция(unittest.TestCase):
    def test_хостинг_вне_юрисдикции_отсеивает_записанный(self) -> None:
        us = ep.Endpoint(
            model="us-tts", key="us-tts", hosting=("US",), hosting_note="serving_regions = «USA»"
        )
        eu_us = ep.Endpoint(model="eu-tts", key="eu-tts", hosting=("EU", "US"))
        молчит = ep.Endpoint(model="quiet-tts", key="quiet-tts")
        # Девятый круг: регион вне вашей юрисдикции без записанного закрепления
        # отсеивает — вендор сам решает, где обработать запрос.
        eu_pinned = ep.Endpoint(model="pin-tts", key="pin-tts", hosting=("EU", "US"), hosting_pinned=("EU",))
        self.assertEqual(
            [
                "хостинг/юрисдикция вендора по записи: US — ни одна не ваша (EU): serving_regions = «USA»",
                "хостинг вендора по записи: EU, US — запрос может уйти в US, а закрепить регион (EU) запись "
                "не позволяет: ",
                "",
                "",
            ],
            [pn.хостинг_вне(e, ("EU",)) for e in (us, eu_us, eu_pinned, молчит)],
        )
        self.assertEqual("", pn.хостинг_вне(us, None))

    def test_план_называет_неизмеренный_хостинг(self) -> None:
        база = [
            _f("eleven-tts", "serving_regions", "USA, Netherlands, Singapore"),
            _f("quiet-tts", "positioning", "speech synthesis", "portal"),
        ]
        op = next(op for op in pn.OPERATIONS if op.name == "озвучка")
        выбор = [(op, Ранжирование._c("eleven-tts")), (op, Ранжирование._c("quiet-tts"))]
        итог = pn.хостинг_плана(выбор, база, ("EU",))
        assert итог is not None
        self.assertEqual(
            [
                {
                    "step": "озвучка",
                    "model": "eleven-tts",
                    "state": "recorded",
                    "hosting": ["EU", "SG", "US"],
                },
                {"step": "озвучка", "model": "quiet-tts", "state": pn.HOSTING_NOT_MEASURED},
            ],
            итог["steps"],
        )
        self.assertEqual(
            "jurisdiction EU: licence territories checked per model; "
            "hosting/vendor jurisdiction not measured for quiet-tts",
            итог["note"],
        )
        self.assertIsNone(pn.хостинг_плана(выбор, база, None))


class Реестр(unittest.TestCase):
    def test_названная_правка(self) -> None:
        self.assertEqual(
            [frozenset({ep.EDIT_REMOVE_OBJECT}), frozenset(), frozenset({ep.EDIT_REMOVE_OBJECT})],
            [
                ep.edit_named("fal-ai/ltx-2.3-quality/clean-plate"),
                ep.edit_named("fal-ai/kling-video/o3/standard/video-to-video/edit"),
                ep.edit_named("fal-ai/ltx-2.3-quality/inpaint"),
            ],
        )

    def test_шумодав_реставрация(self) -> None:
        работы, _, _ = ep.classify(
            "acme-deblur-video",
            [_на_фал("acme-deblur-video", "acme/deblur/video", "video-to-video")],
        )
        self.assertEqual((ep.V2V_EDIT, ep.RESTORE), работы)

    def test_описание_перечисляет_работы_реестра(self) -> None:
        док = " ".join((server.find_models.__doc__ or "").split())
        список = док.split("a job of the endpoint registry — ")[1].split(" — or a word")[0]
        self.assertEqual(list(ep.FUNCTIONS), [р.strip() for р in список.split("|")])
        self.assertNotIn("restore-colorize", док)


class ЖиваяБаза(unittest.TestCase):
    """Вопросы валидатора v7 и его планы на ЖИВОЙ базе."""

    база: list[Fact]
    реестр: ep.Registry

    @classmethod
    def setUpClass(cls) -> None:
        from studio.mcp.advice import store_for

        cls.база = store_for().facts
        cls.реестр = ep.build(cls.база)

    def _найти(self, need: str, function: str, terms: str = "", require: str = "") -> dict:
        return capability.find(need, function, terms, require, top=30, facts=self.база)

    def test_f05_нативный_звук(self) -> None:
        итог = self._найти(
            "text-to-video with native audio and dialogue lipsync", "t2v", "native audio, dialogue"
        )
        self.assertEqual(
            ("pass", "seedance-2.0-t2v"), (итог["outcome"], итог["ranked"][0]["model"])
        )
        вео = next(r for r in итог["ranked"] if r["model"] == "veo-3.1-fast-t2v")
        self.assertEqual("good_news_only", вео["verdict"])

    def test_f09_120_кадров(self) -> None:
        итог = self._найти("frame interpolation to 120fps", "frame-interpolate", "fps")
        self.assertEqual(
            ("pass", "topaz-interpolate-video"), (итог["outcome"], итог["ranked"][0]["model"])
        )
        rife = next(r for r in итог["ranked"] if r["model"] == "rife-video")
        self.assertIn(">= 30 fps", rife["informational"][0]["why"])

    def test_f16_удаление_объекта(self) -> None:
        итог = self._найти(
            "video object removal / inpainting", "v2v-edit", "object removal, inpainting"
        )
        self.assertEqual(
            ("pass", "ltx-2.3-quality-clean-plate", "catalog"),
            (итог["outcome"], итог["ranked"][0]["model"], итог["ranked"][0]["good"][0]["polarity"]),
        )

    def test_f18_12gb(self) -> None:
        итог = self._найти("which i2v runs on 12GB VRAM", "i2v", "vram, 12GB", "open")
        отсеяны = {e["model"]: e["why"] for e in итог["gaps"]["excluded_examples"]}
        self.assertTrue(отсеяны["minimax-h3"].startswith("vram: needs >= 33.1 GB, asked 12 GB"))
        self.assertNotIn("minimax-h3", [r["model"] for r in итог["ranked"]])
        # Ни одна i2v не записала VRAM <= 12 ГБ: честное «не смогли», а наверху —
        # LTX-2.5 со строками «runs on RTX 3060 12GB» (blog: информация, не довод).
        self.assertEqual(
            ("could not measure", "ltx-2.5", "informational_only"),
            (итог["outcome"], итог["ranked"][0]["model"], итог["ranked"][0]["verdict"]),
        )
        self.assertGreater(итог["gaps"]["excluded_unknown"], 0)
        for r in итог["ranked"]:
            self.assertNotIn("license", [g["attribute"] for g in r["good"]])

    def test_f07_f10_языки_поняты(self) -> None:
        kk = self._найти("Kazakh speech synthesis", "tts", "", "kk")
        he = self._найти("voice cloning that works in Hebrew", "voice-clone", "", "he")
        self.assertEqual(
            ([], ["kk"], [], ["he"]),
            (
                kk["require_not_understood"],
                kk["require"],
                he["require_not_understood"],
                he["require"],
            ),
        )
        self.assertEqual("eleven_v3", kk["ranked"][0]["model"])
        self.assertEqual("pass", kk["ranked"][0]["requirements"]["kk"]["outcome"])

    def test_промахи_реестра(self) -> None:
        р = self.реестр

        def узел(имя: str) -> ep.Endpoint:
            найден = р.get(имя)
            assert найден is not None, имя
            return найден

        self.assertEqual(("tts",), узел("eleven_flash_v2").functions)
        self.assertEqual(("image-edit",), узел("flux-1-kontext-max-multi").functions)
        klein = узел("flux.2-klein-9b")
        self.assertEqual(
            (True, (("self-host", "https://huggingface.co/black-forest-labs/FLUX.2-klein-9B"),)),
            (klein.orderable, klein.route_ids),
        )
        покрытие = {r["function"]: r for r in ep.coverage(р)}
        self.assertGreaterEqual(покрытие["captions"]["priced"], 3)
        self.assertGreaterEqual(покрытие["restore"]["priced"], 3)
        self.assertGreaterEqual(покрытие["tts"]["priced"], 18)

    def test_дубляж_берёт_sync3_а_не_провал(self) -> None:
        бриф = "Translate our 90s product video from English into Polish and Turkish, keep the speaker's own voice, lipsync обязательно"
        итог = pn.plan(
            бриф,
            self.база,
            full=True,
            spec={
                "task": "dub-translate",
                "inputs": [{"kind": "video", "owned": True, "duration_s": 90}],
                "outputs": ["video", "speech"],
                "duration_s": 90,
                "languages": ["pl", "tr"],
                "people": [
                    {
                        "name": "the speaker",
                        "real": True,
                        "public_figure": False,
                        "consent": "unknown",
                        "claim": "none",
                    }
                ],
            },
        )
        шаг = next(ш for ш in итог["steps"] if ш["step"] == "липсинк")
        self.assertEqual("sync-lipsync-v3", шаг["chosen"]["model"])
        self.assertNotEqual("fail", итог["outcome"])

    def test_долгий_аватар_hedra_а_не_omnihuman(self) -> None:
        бриф = "Corporate compliance training: an AI presenter avatar speaks for 8 minutes, 1080p 16:9, from our stock presenter photo"
        итог = pn.plan(
            бриф,
            self.база,
            full=True,
            spec={
                "task": "avatar",
                "inputs": [{"kind": "image", "owned": True}, {"kind": "text", "owned": True}],
                "outputs": ["video", "speech"],
                "duration_s": 480,
                "resolution": "1080p",
                "aspect": "16:9",
                "languages": ["en", "de", "ja"],
                "people": [
                    {
                        "name": "stock presenter",
                        "real": True,
                        "public_figure": False,
                        "consent": "stated",
                        "claim": "none",
                    }
                ],
            },
        )
        шаг = next(ш for ш in итог["steps"] if ш["step"] == "говорящий_аватар")
        self.assertEqual("hedra-character-3", шаг["chosen"]["model"])


if __name__ == "__main__":
    unittest.main()
