"""`find_models`: вопрос о способности по всей базе, ранжированный по ОБЪЯВЛЕННОМУ свидетельству.

НАЙДЕНО валидатором 5-го круга: на «which lipsync handles profile faces»
вызывающая модель называла кандидатов по памяти. Шестой круг (валидатор v5,
14 вопросов): своя регулярка функций числила удаление фона липсинком, знак
читался по словарю слов («Non-commercial use ONLY» — хорошая новость о
коммерции), цена шла доводом, `fps = "24"` выигрывал интерполяцию.

Здесь — фикстура из литералов (Т2), не живая база; живая база — отдельным
классом в конце (несколько вопросов валидатора, на которых круг и упал).
"""

from __future__ import annotations

import json
import unittest

from studio import endpoints as ep
from studio import planner as pn
from studio.mcp import capability, server
from studio.selfrag import attrfamily
from studio.selfrag.facts import Fact

HF = "https://huggingface.co"


def _f(
    model: str,
    attribute: str,
    value: str,
    tier: str = "vendor",
    url: str = "",
    day: str = "2026-10-01",
    contra: bool | None = None,
) -> Fact:
    return Fact(
        model,
        attribute,
        value,
        url or f"https://{model}.test/{attribute}",
        tier,
        day,
        contra=contra,
    )


БАЗА = [
    # --- липсинк: условие «профиль» -------------------------------------------------
    _f("alpha-lipsync", "pose_range", "Native on extreme angles and side profiles", contra=False),
    _f("alpha-lipsync", "price_per_second", "$0.10 per second"),
    _f("beta-lipsync", "pose_range", "'Limited' on extreme angles", contra=True),
    _f(
        "beta-lipsync", "pose_range", "extreme profile views may yield suboptimal results", "portal"
    ),
    _f(
        "gamma-lipsync",
        "pose_range",
        "handles side profiles up to 80 degrees",
        "operator",
        contra=False,
    ),
    _f("gamma-lipsync", "failure_mode", "mouth smears on profile view at 90 degrees", "blog"),
    # Описание без знака: «справляется с профилем» — информация, не похвала.
    _f("delta-lipsync", "pose_range", "works on profile shots", "blog"),
    _f("delta-lipsync", "license", "Apache-2.0", url=f"{HF}/delta/lipsync"),
    _f("eps-lipsync", "failure_mode", "teeth render square on close-ups", "probe"),
    _f("eps-lipsync", "languages", "only English speech is supported"),
    _f("zeta-lipsync", "languages", "en, ru, de, fr, es"),
    _f("zeta-lipsync", "license", "CC-BY-NC-4.0, non-commercial", url=f"{HF}/zeta/lipsync"),
    # Удаление фона, в описании которого «talking heads», — НЕ липсинк.
    _f(
        "cutout-background-removal",
        "positioning",
        "removes backgrounds from talking heads and product shots",
        "portal",
    ),
    _f(
        "cutout-background-removal",
        "observed_behaviour",
        "hair edges stay clean",
        "operator",
        contra=False,
    ),
    _f("matte-bg-remove", "failure_mode", "flickering edge on fast motion", "blog"),
    # --- TTS: открытые веса и язык ---------------------------------------------------
    _f("open-tts", "license", "MIT", url=f"{HF}/open/tts"),
    _f("open-tts", "languages", "en, ru, de"),
    _f("nc-tts", "license", "CC BY-NC 4.0 (non-commercial)", url=f"{HF}/nc/tts"),
    _f("nc-tts", "languages", "Russian (5000 h of training data)"),
    _f("closed-tts", "license", "proprietary, API only"),
    _f("closed-tts", "languages", "English, Russian"),
    _f("nolang-tts", "license", "Apache-2.0", url=f"{HF}/nolang/tts"),
    _f("english-tts", "languages", "English only"),
    _f("english-tts", "license", "MIT", url=f"{HF}/english/tts"),
    # --- музыка: коммерция и язык ----------------------------------------------------
    _f("vox-music", "license", "Non-commercial use ONLY", url=f"{HF}/vox/music"),
    _f("vox-music", "languages", "en, es, fr, de, ja"),
    _f("free-music", "license", "Apache-2.0", url=f"{HF}/free/music"),
    _f("free-music", "languages", "English, Spanish"),
    _f("api-music", "positioning", "full songs with vocals and lyrics", "portal"),
    # --- t2v: руки, текст в кадре, цена ----------------------------------------------
    _f("kilo-t2v", "failure_mode", "hands mangle and fingers multiply in close-ups", "blog"),
    _f("kilo-t2v", "benchmark_score", "VTR-Bench (T2V): overall text WER 0.900", "paper"),
    _f("kilo-t2v", "price_per_second", "$0.05 per second, cheap"),
    _f(
        "mega-t2v",
        "observed_behaviour",
        "hands and fingers render correctly",
        "operator",
        contra=False,
    ),
    _f("mega-t2v", "benchmark_score", "VTR-Bench (T2V): overall text WER 0.300", "paper"),
    _f("giga-t2v", "limitation", "cannot render legible text or logos", "vendor"),
    _f("giga-t2v", "max_seconds", "5 exactly, 1080P at 30fps, MP4 H.264"),
    _f("tera-t2v", "max_seconds", "integer 2 to 15, 720P or 1080P"),
    _f("rigid-t2v", "fps", "24"),
    # --- i2v: логотип ----------------------------------------------------------------
    _f(
        "pix-i2v",
        "text_rendering",
        "logos and wordmarks stay legible from the first frame",
        contra=False,
    ),
    _f("blur-i2v", "text_rendering", "small text in the first frame turns to mush", contra=True),
    _f("plain-i2v", "positioning", "fast image-to-video drafts", "portal"),
    # --- интерполяция: частота кадров числом -----------------------------------------
    _f("smooth-interpolate", "fps", "output up to 120 fps"),
    _f("slow-interpolate", "fps", "output 60 fps"),
    _f("blank-interpolate", "positioning", "frame interpolation for anime", "portal"),
    # --- аватар: длина одного прогона ------------------------------------------------
    _f("long-avatar", "max_seconds", "600 (up to 10 minutes)"),
    _f("short-avatar", "max_seconds", "20 on the hosted API"),
    _f("mute-avatar", "positioning", "talking avatar for short clips", "portal"),
    # --- апскейл: кожа ---------------------------------------------------------------
    _f(
        "skin-upscale-video",
        "observed_behaviour",
        "keeps skin texture, no plastic faces",
        "operator",
        contra=False,
    ),
    _f("wax-upscale-video", "failure_mode", "plastic skin texture on faces", "blog"),
    _f("plain-upscale-image", "positioning", "4x photo upscaler", "portal"),
    # --- замена лица -----------------------------------------------------------------
    _f("x-faceswap", "positioning", "swaps a face in a photo", "portal"),
    # --- о классе --------------------------------------------------------------------
    _f(
        "*",
        "failure_mode",
        "every audio-driven model loses the mouth at full profile view",
        "paper",
    ),
]


def _найти(need: str, function: str = "", terms: str = "", require: str = "", **kw) -> dict:
    return capability.find(need, function, terms, require, 8, facts=БАЗА, **kw)


def _верх(итог: dict, n: int = 3) -> list[str]:
    return [r["model"] for r in итог["ranked"][:n]]


#: ≥30 ВОПРОСОВ (EN + RU перефразы): (need, function, terms, require, верх-3,
#: пробелы). Литералы (Т2); каждый проверен чтением фикстуры.
ВОПРОСЫ: list[tuple[str, str, str, str, list[str], list[str]]] = [
    # 1-6: профиль
    (
        "which lipsync handles profile faces",
        "lipsync",
        "",
        "",
        ["alpha-lipsync", "delta-lipsync", "gamma-lipsync"],
        ["eps-lipsync", "zeta-lipsync"],
    ),
    (
        "which lipsync handles profile / side view faces",
        "lipsync",
        "profile, side view",
        "",
        ["alpha-lipsync", "delta-lipsync", "gamma-lipsync"],
        ["eps-lipsync", "zeta-lipsync"],
    ),
    (
        "lip sync on a side-profile shot",
        "lip sync",
        "",
        "",
        ["alpha-lipsync", "delta-lipsync", "gamma-lipsync"],
        ["eps-lipsync", "zeta-lipsync"],
    ),
    (
        "какой липсинк держит лицо в профиль",
        "липсинк",
        "",
        "",
        ["alpha-lipsync", "delta-lipsync", "gamma-lipsync"],
        ["eps-lipsync", "zeta-lipsync"],
    ),
    (
        "липсинк для ракурса сбоку",
        "lipsync",
        "ракурс",
        "",
        ["alpha-lipsync", "delta-lipsync", "gamma-lipsync"],
        ["eps-lipsync", "zeta-lipsync"],
    ),
    (
        "lipsync for extreme angles",
        "",
        "extreme angles",
        "",
        ["alpha-lipsync", "delta-lipsync", "gamma-lipsync"],
        ["eps-lipsync", "zeta-lipsync"],
    ),
    # 7-10: язык липсинка
    # eps: «only English» — исключительный список, отсеяна, а не пробел.
    (
        "which lipsync is best for Russian speech",
        "lipsync",
        "",
        "russian",
        ["zeta-lipsync"],
        ["alpha-lipsync", "beta-lipsync", "delta-lipsync", "gamma-lipsync"],
    ),
    (
        "какая модель липсинка лучше для русской речи",
        "lipsync",
        "",
        "",
        ["zeta-lipsync"],
        ["alpha-lipsync", "beta-lipsync", "delta-lipsync", "gamma-lipsync"],
    ),
    (
        "lipsync for English dialogue",
        "lipsync",
        "",
        "english",
        ["eps-lipsync", "zeta-lipsync"],
        ["alpha-lipsync", "beta-lipsync", "delta-lipsync", "gamma-lipsync"],
    ),
    # Веса не записаны — не «закрыта», а пробел.
    (
        "open-weights lipsync",
        "lipsync",
        "",
        "open",
        ["delta-lipsync", "zeta-lipsync"],
        ["alpha-lipsync", "beta-lipsync", "eps-lipsync", "gamma-lipsync"],
    ),
    # 11-15: TTS. CC BY-NC — открытые веса (nc-tts первой: свежесть равна, имя).
    # nolang-tts: веса открыты, язык не записан — после подтвердивших оба.
    (
        "best open-weights Russian TTS",
        "tts",
        "",
        "open, russian",
        ["nc-tts", "open-tts", "nolang-tts"],
        [],
    ),
    (
        "лучший открытый синтез речи на русском",
        "tts",
        "",
        "открытые веса, ru",
        ["nc-tts", "open-tts", "nolang-tts"],
        [],
    ),
    # Коммерция: nc-tts отсеяна лицензией.
    (
        "open TTS for Russian, commercial use",
        "tts",
        "",
        "open, russian, commercial",
        ["open-tts", "nolang-tts"],
        [],
    ),
    # nc-tts: язык записан, английского нет и список не исключительный — информация.
    (
        "text-to-speech in English",
        "",
        "",
        "en",
        ["closed-tts", "english-tts", "open-tts"],
        ["nolang-tts"],
    ),
    # english-tts: «English only» — отсеяна для русского.
    (
        "Russian voiceover model",
        "tts",
        "",
        "",
        ["closed-tts", "nc-tts", "open-tts"],
        ["nolang-tts"],
    ),
    # 16-18: музыка
    (
        "music model that sings lyrics in Spanish for commercial use",
        "music",
        "vocals, lyrics, commercial",
        "spanish",
        ["free-music", "api-music"],
        [],
    ),
    (
        "музыка с вокалом на испанском для коммерческого использования",
        "music",
        "",
        "spanish, commercial",
        ["free-music"],
        ["api-music"],
    ),
    ("music with vocals", "music", "vocals", "", ["api-music"], ["free-music", "vox-music"]),
    # 19-21: руки
    (
        "which t2v renders hands without extra fingers",
        "t2v",
        "hands, fingers",
        "",
        ["mega-t2v", "kilo-t2v"],
        ["giga-t2v", "rigid-t2v", "tera-t2v"],
    ),
    (
        "какая модель видео по тексту рисует руки",
        "t2v",
        "руки",
        "",
        ["mega-t2v", "kilo-t2v"],
        ["giga-t2v", "rigid-t2v", "tera-t2v"],
    ),
    (
        "hands in text to video",
        "",
        "hands",
        "",
        ["mega-t2v", "kilo-t2v"],
        ["giga-t2v", "rigid-t2v", "tera-t2v"],
    ),
    # 22-25: текст и логотип
    (
        "which text-to-video keeps on-screen text legible",
        "t2v",
        "text legibility",
        "",
        ["mega-t2v", "kilo-t2v", "giga-t2v"],
        ["rigid-t2v", "tera-t2v"],
    ),
    (
        "which image-to-video keeps logos legible",
        "i2v",
        "logo, legible",
        "",
        ["pix-i2v", "blur-i2v"],
        ["plain-i2v"],
    ),
    (
        "какое оживление фото сохраняет логотип читаемым",
        "i2v",
        "логотип",
        "",
        ["pix-i2v", "blur-i2v"],
        ["plain-i2v"],
    ),
    (
        "animate a logo wordmark",
        "image-to-video",
        "wordmark",
        "",
        ["pix-i2v", "blur-i2v"],
        ["plain-i2v"],
    ),
    # 26-27: интерполяция числом
    (
        "frame interpolation to 60/120 fps",
        "video",
        "interpolation, fps, slow motion",
        "",
        ["smooth-interpolate", "slow-interpolate"],
        ["blank-interpolate"],
    ),
    (
        "интерполяция кадров до 60 fps",
        "",
        "",
        "",
        ["slow-interpolate", "smooth-interpolate"],
        ["blank-interpolate"],
    ),
    # 28-29: длина прогона числом
    (
        "talking avatar that can do 5 minutes in one go",
        "avatar",
        "long, minutes, duration",
        "",
        ["long-avatar", "short-avatar"],
        ["mute-avatar"],
    ),
    (
        "аватар на 30 секунд за один прогон",
        "talking-avatar",
        "",
        "",
        ["long-avatar", "short-avatar"],
        ["mute-avatar"],
    ),
    # 30-31: апскейл
    (
        "which upscaler keeps skin texture, no plastic faces",
        "upscale",
        "skin, texture, plastic",
        "",
        ["skin-upscale-video", "wax-upscale-video"],
        ["plain-upscale-image"],
    ),
    (
        "апскейл видео без пластиковой кожи",
        "upscale-video",
        "кожа, plastic",
        "",
        ["skin-upscale-video", "wax-upscale-video"],
        [],
    ),
    # 32-33: удаление фона и замена лица — работы, которых не было в старом списке
    (
        "background removal for video, matting",
        "video",
        "background removal, matting, alpha, hair",
        "",
        ["cutout-background-removal"],
        ["matte-bg-remove"],
    ),
    ("anything", "faceswap", "", "", [], ["x-faceswap"]),
]


class Вопросы(unittest.TestCase):
    """Тридцать с лишним вопросов: верх-3 и пробелы — литералы (Т2)."""

    def test_верх_и_пробелы(self) -> None:
        self.assertGreaterEqual(len(ВОПРОСЫ), 30)
        for need, function, terms, require, верх, пробелы in ВОПРОСЫ:
            with self.subTest(need=need):
                итог = _найти(need, function, terms, require)
                self.assertEqual(верх, _верх(итог))
                self.assertEqual(пробелы, итог["gaps"]["examples"])


class Знак(unittest.TestCase):
    def test_хорошая_новость_только_объявленная(self) -> None:
        """СВОЙСТВО: каждая строка, поданная хорошей новостью, объявлена хорошей.

        Объявлена — значит `contra=False` у записи, или значение прочитано ПО
        АТРИБУТУ против ограничения вопроса (язык в списке, предел покрывает
        длину, лицензия разрешает заявленное). Строка без знака — никогда.
        """
        по_ключу = {(f.model, f.attribute, f.source_url, f.value[:60]): f for f in БАЗА}
        проверено = 0
        for need, function, terms, require, *_ in ВОПРОСЫ:
            итог = _найти(need, function, terms, require)
            for r in итог["ranked"]:
                for строка in r["good"]:
                    проверено += 1
                    self.assertIn(строка["polarity"], ("declared", "constraint"), строка)
                    if строка["polarity"] == "declared":
                        f = по_ключу[
                            (
                                r["model"],
                                строка["attribute"],
                                строка["source_url"],
                                строка["value"][:60],
                            )
                        ]
                        self.assertIs(False, f.contra)
        self.assertGreater(проверено, 20)

    def test_без_знака_информация(self) -> None:
        f = _f("x", "pose_range", "may yield suboptimal results on profiles", "portal")
        self.assertEqual("informational", capability.знак(f)[0])
        f2 = _f("x", "pose_range", "handles side profiles well", "portal")
        self.assertEqual("informational", capability.знак(f2)[0])

    def test_цена_никогда_не_довод(self) -> None:
        f = _f("x", "price_per_second", "$0.10 per second", contra=None)
        self.assertEqual(("informational", "none"), capability.знак(f)[:2])
        итог = _найти("cheapest text to video", "t2v", "cheap, price")
        self.assertEqual("could not measure", итог["outcome"])
        self.assertIn("Price is not capability", итог["note"])

    def test_некоммерческая_лицензия_дисквалифицирует(self) -> None:
        итог = _найти("music for commercial use", "music", "", "")
        self.assertEqual(["vox-music"], [e["model"] for e in итог["gaps"]["excluded_examples"]])
        self.assertNotIn("vox-music", _верх(итог, 8))

    def test_язык_по_коду_в_списке(self) -> None:
        f = _f("x", "languages", "ar, da, de, el, en, es, ru, sv")
        вопрос = capability.Вопрос("russian tts", "", "russian")
        self.assertEqual("good", capability.знак(f, вопрос)[0])
        # «it» в английской фразе — не итальянский: кодов меньше трёх.
        вопрос_it = capability.Вопрос("italian tts", "", "italian")
        f_it = _f("x", "languages", "it speaks clearly")
        self.assertEqual("informational", capability.знак(f_it, вопрос_it)[0])

    def test_исключительный_список_языков_отсеивает(self) -> None:
        итог = _найти("russian tts", "tts", "", "russian")
        self.assertIn("english-tts", [e["model"] for e in итог["gaps"]["excluded_examples"]])

    def test_длительность_по_единицам(self) -> None:
        self.assertEqual(
            5.0, capability.секунд_в_строке("max_seconds", "5 exactly, 1080P at 30fps, MP4 H.264")
        )
        self.assertEqual(600.0, capability.секунд_в_строке("max_seconds", "600 (up to 10 minutes)"))
        self.assertEqual(
            15.0, capability.секунд_в_строке("max_seconds", "integer 2 to 15, 720P or 1080P")
        )
        self.assertEqual(2.5, capability.секунд_в_строке("max_duration_ms", "2500"))
        self.assertIsNone(capability.секунд_в_строке("max_seconds", "follows the audio"))

    def test_минута_покупки_не_предел(self) -> None:
        вопрос = capability.Вопрос("cheapest 1 minute of 1080p video", "1080p, cheap, price", "")
        self.assertIsNone(вопрос.секунды)
        self.assertNotIn("max_seconds", вопрос.семьи)

    def test_fps_числом_а_не_присутствием(self) -> None:
        итог = _найти("frame interpolation to 60/120 fps", "video", "interpolation, fps", "")
        по_модели = {r["model"]: r["verdict"] for r in итог["ranked"]}
        self.assertEqual("good_news_only", по_модели["smooth-interpolate"])
        self.assertEqual("bad_news_only", по_модели["slow-interpolate"])
        self.assertNotIn("rigid-t2v", по_модели)

    def test_бенчмарк_условия_с_единицей(self) -> None:
        итог = _найти("legible text in video", "t2v", "text", "")
        метрики = {r["model"]: r.get("metric") for r in итог["ranked"]}
        self.assertEqual("vtr-bench WER 0.3", метрики["mega-t2v"])
        self.assertEqual("vtr-bench WER 0.9", метрики["kilo-t2v"])


class Область(unittest.TestCase):
    def test_удаление_фона_не_липсинк(self) -> None:
        итог = _найти("which lipsync handles profile faces", "lipsync")
        все = _верх(итог, 30) + итог["gaps"]["examples"]
        self.assertNotIn("cutout-background-removal", все)

    def test_каждая_работа_реестра_принимается(self) -> None:
        for работа in ep.FUNCTIONS:
            with self.subTest(работа=работа):
                итог = _найти("anything", работа)
                self.assertNotEqual("function_unknown", итог.get("reason"))
                self.assertEqual(
                    [работа],
                    [итог["function"]] if isinstance(итог["function"], str) else итог["function"],
                )

    def test_короткое_слово_работы_только_целым(self) -> None:
        self.assertEqual((), ep.job_words("settings for a dubai trip"))
        self.assertEqual(("lipsync",), ep.job_words("лучшая модель липсинка"))

    def test_каждая_работа_называется_своим_словом(self) -> None:
        self.assertEqual(set(ep.FUNCTIONS), set(ep.JOB_WORDS))
        for работа, слова in ep.JOB_WORDS.items():
            self.assertIn(работа, слова)

    def test_широкое_слово_уточняется_вопросом(self) -> None:
        self.assertEqual(
            ("bg-remove",),
            capability.scope("video", "background removal for a talking-head video")[0],
        )
        self.assertEqual(
            ("t2v", "i2v", "r2v", "v2v-edit"), capability.scope("video", "a nice clip")[0]
        )
        self.assertEqual(("frame-interpolate",), capability.scope("", "интерполяция кадров")[0])

    def test_незнакомая_функция(self) -> None:
        итог = _найти("anything", "teleport")
        self.assertEqual(
            ("could not measure", "function_unknown"), (итог["outcome"], итог["reason"])
        )
        self.assertEqual(list(ep.FUNCTIONS), итог["functions"])

    def test_находка_о_классе_отдельно(self) -> None:
        итог = _найти("which lipsync handles profile faces", "lipsync")
        self.assertEqual(["*"], [c["scope"] for c in итог["class_findings"]])

    def test_ни_одной_хорошей_новости_не_pass(self) -> None:
        итог = _найти("frame interpolation for anime", "frame-interpolate", "anime", "")
        self.assertEqual("could not measure", итог["outcome"])

    def test_непонятое_требование_названо(self) -> None:
        итог = _найти("lipsync open weights", "lipsync", "", "open, apache, cheap")
        self.assertEqual(["apache", "cheap"], итог["require_not_understood"])


class Условия(unittest.TestCase):
    def test_условия_через_attrfamily(self) -> None:
        self.assertEqual("pose_range", attrfamily.условие("profile face"))
        self.assertEqual("text_legibility", attrfamily.условие("logo legible"))
        self.assertEqual("hands", attrfamily.условие("hands"))
        self.assertEqual("", attrfamily.условие("text-to-video"))
        self.assertTrue(attrfamily.об_условии("pose_range", "occlusion_handling"))
        self.assertTrue(attrfamily.об_условии("text_legibility", "text_rendering"))
        self.assertFalse(attrfamily.об_условии("pose_range", "face_requirement"))

    def test_темы_условий_есть_у_валидатора(self) -> None:
        from studio import pipeline as pl

        for у, правило in attrfamily.УСЛОВИЯ.items():
            self.assertIn(правило["тема"], pl.CONDITION_THEMES, у)

    def test_ступени_условия(self) -> None:
        строки = {f.model: [g for g in БАЗА if g.model == f.model] for f in БАЗА}
        self.assertEqual(0, capability.condition_state(строки["alpha-lipsync"], ["pose_range"])[0])
        self.assertEqual(2, capability.condition_state(строки["beta-lipsync"], ["pose_range"])[0])
        # Похвала оператора и провал из блога — против: плохая новость не перевешивается.
        self.assertEqual(2, capability.condition_state(строки["gamma-lipsync"], ["pose_range"])[0])
        self.assertEqual(1, capability.condition_state(строки["delta-lipsync"], ["pose_range"])[0])
        # Провал на крупном плане — не о профиле.
        self.assertEqual(1, capability.condition_state(строки["eps-lipsync"], ["pose_range"])[0])
        self.assertEqual((1, "", []), capability.condition_state(строки["alpha-lipsync"], []))

    def test_числа_ступеней_у_плановщика_те_же(self) -> None:
        self.assertEqual(
            {
                0: capability.CONDITION_POSITIVE,
                1: capability.CONDITION_UNKNOWN,
                2: capability.CONDITION_NEGATIVE,
            },
            {к: к for к in pn.CONDITION_WORDS},
        )
        self.assertEqual(
            pn.KEY_FIELDS.index(pn.CONDITION_KEY_FIELD) + 1,
            pn.KEY_FIELDS.index("знак измеренного: чисто / спорно / только плохое / молчание"),
        )

    def test_плановщик_отодвигает_провал_на_условии(self) -> None:
        """Провал на заявленном условии ниже молчания, похвала — выше измеренного.

        Литералы повторяют w19: у `sync-lipsync` три строки применимости (две за),
        у `sync-lipsync-v3` — ни одной, но вендор пишет «Native on extreme angles».
        """
        измеренная = pn.Candidate(
            model="measured",
            evidence=(),
            applicability=3,
            capability=0,
            unresolved=0,
            price="",
            against=1,
            condition_rank=1,
        )
        похвала = pn.Candidate(
            model="praised",
            evidence=(),
            applicability=0,
            capability=0,
            unresolved=0,
            price="",
            condition_rank=0,
            condition_note="for — pose_range: vendor table: Native",
        )
        провал = pn.Candidate(
            model="limited",
            evidence=(),
            applicability=4,
            capability=0,
            unresolved=0,
            price="",
            against=0,
            condition_rank=2,
        )
        порядок = sorted([провал, измеренная, похвала], key=pn.by_evidence)
        self.assertEqual(["praised", "measured", "limited"], [c.model for c in порядок])
        self.assertIn(pn.CONDITION_KEY_FIELD, pn.why_not(похвала, измеренная))
        self.assertIn("Native", pn.why_not(похвала, измеренная))

    def test_слова_условий_спецификации(self) -> None:
        self.assertEqual(
            (("pose_range", "text_legibility", "hands"), ("purple glitter",)),
            capability.conditions_of(["profile face", "logo legible", "hands", "purple glitter"]),
        )


class Обёртка(unittest.TestCase):
    def test_обёртка_и_язык(self) -> None:
        ответ = json.loads(server.find_models("какой липсинк держит профиль", "lipsync", top=3))
        self.assertIn(ответ["outcome"], ("pass", "could not measure", "не смогли", "годно"))
        self.assertIn("ranked", ответ)

    def test_описание_учит_звать_вместо_догадки(self) -> None:
        док = server.find_models.__doc__ or ""
        self.assertIn("INSTEAD OF GUESSING CANDIDATES", док)
        self.assertIn("never good news", док)


class ЖиваяБаза(unittest.TestCase):
    """Вопросы валидатора на ЖИВОЙ базе: на них шестой круг и упал."""

    @classmethod
    def setUpClass(cls) -> None:
        from studio.mcp.advice import store_for

        cls.база = store_for().facts

    def _найти(self, *a: str) -> dict:
        return capability.find(*a, top=30, facts=self.база)

    def test_f01_профиль_sync3_выше_lipsync2pro_и_19(self) -> None:
        итог = self._найти(
            "which lipsync handles profile / side view faces", "lipsync", "profile, side view", ""
        )
        порядок = [r["model"] for r in итог["ranked"]]
        self.assertEqual("sync-lipsync-v3", порядок[0])
        self.assertLess(порядок.index("sync-lipsync-v3"), порядок.index("sync-lipsync-v2-pro"))
        self.assertEqual(
            "bad_news_only",
            next(r for r in итог["ranked"] if r["model"] == "sync-lipsync-v2-pro")["verdict"],
        )
        self.assertNotIn("bria-video-background-removal-v3", порядок + итог["gaps"]["examples"])

    def test_f03_открытый_русский_tts_не_пробелы(self) -> None:
        итог = self._найти("best open-weights Russian TTS", "tts", "", "open, russian")
        порядок = [r["model"] for r in итог["ranked"]]
        for имя in ("silero-tts-v5", "f5-tts-russian", "chatterbox-multilingual"):
            self.assertIn(имя, порядок)
            self.assertNotIn(имя, итог["gaps"]["examples"])

    def test_f05_minimax_h3_не_интерполятор(self) -> None:
        итог = self._найти(
            "frame interpolation to 60/120 fps", "video", "interpolation, fps, slow motion", ""
        )
        self.assertEqual("frame-interpolate", итог["function"])
        self.assertNotIn("minimax-h3", [r["model"] for r in итог["ranked"]])

    def test_f08_некоммерческая_не_хорошая_новость(self) -> None:
        итог = self._найти(
            "music model that sings lyrics in Spanish for commercial use",
            "music",
            "vocals, lyrics, commercial",
            "spanish",
        )
        for r in итог["ranked"]:
            for строка in r["good"]:
                self.assertNotRegex(строка["value"].lower(), r"non-?commercial|cc-by-nc")
        self.assertNotIn("openaudio-s1-mini", [r["model"] for r in итог["ranked"]])

    def test_w19_план_берёт_sync3_и_говорит_почему(self) -> None:
        бриф = (
            "Lipsync a side-profile (90 degree) shot of an actor to new English dialogue, "
            "12 seconds, we have the video and the audio"
        )
        итог = pn.plan(бриф, self.база, full=True)
        шаг = итог["steps"][0]
        self.assertEqual("sync-lipsync-v3", шаг["chosen"]["model"])
        self.assertIn("pose_range", шаг["chosen"]["condition_note"])
        # «dialogue» — тема валидатора «несколько людей» (`CONDITION_THEMES`).
        self.assertEqual(["multiple_people", "pose_range"], итог["stated_conditions"]["understood"])
        self.assertNotEqual("fail", итог["outcome"])
