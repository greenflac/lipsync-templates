"""Round 18 (specialist knowledge & pricing residuals): the themes of the hidden set.

Every case is a paraphrase written for this file (EN, RU and at least one other language per
theme), never a dev or holdout brief. Each trigger reads the spec field first and the EN/RU
words only when the field is absent; both directions are pinned, each fallback word is pinned
ALONE, and decision constants are tested at their edges so that
`scripts/mutate_round18_knowledge.py` turns each mutant red. No network (T4).

1. SCORM / xAPI packaging (`elearning_scorm_package`, `delivery.format` scorm | xapi).
2. Medical / scientific explainers (`medical_science_review`, `domain` medical | science);
   the claims policy decides claims unchanged.
3. Sign language (`sign_language_access`, `accessibility` sign-language, sign-language tags).
4. Loudness by `delivery.platform`, measured after the mix (`loudness_measure_after_mix`).
5. Room tone / ADR (`adr_room_tone_match`) and nonverbal sounds (`nonverbal_vocalisations`).
6. CJK locale glyphs / vertical text, RTL graphics (`cjk_locale_glyphs`, `cjk_vertical_text`,
   `rtl_graphics_fonts`).
7. Textless master (`textless_master`).
8. Garment print / drape, glass / liquid (`garment_print_drape`, `glass_liquid_optics`).
9. Render from data (`render_from_data`, `subject` chart | map).
10. Voice locale / accent (`voice_locale_accent`); `mul` for TTS / voice-over jobs.
11. Pricing residuals: a condensed cut ordered as a video edit, one programme brought twice.
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Any

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import expert_r15 as x15  # noqa: E402
from studio import expert_r17 as x17  # noqa: E402
from studio import expert_r18 as x18  # noqa: E402
from studio import l10n  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import checklist as cl  # noqa: E402
from studio.selfrag.facts import load_facts  # noqa: E402

_PLANS: dict[str, dict] = {}


def plan(brief: str, spec: dict) -> dict:
    ключ = brief + json.dumps(spec, sort_keys=True, ensure_ascii=False)
    if ключ not in _PLANS:
        _PLANS[ключ] = json.loads(server.plan_pipeline(brief, spec=spec))
    return _PLANS[ключ]


def steps_of(d: dict) -> list[str]:
    return [str(ш.get("step")) for ш in d.get("steps") or []]


def clip_usd(d: dict) -> float | None:
    цена = d.get("pipeline_price") or {}
    return (цена.get("за_ролик") or {}).get("usd")


def step_usd(d: dict, name: str) -> float:
    return next(float(с["usd"]) for с in d["pipeline_price"]["смета"]["steps"] if с["step"] == name)


def notes(d: dict) -> list[str]:
    return [str(н.get("id")) for н in d.get("production_notes") or []]


def says(d: dict, rid: str) -> str:
    return next(str(н.get("says")) for н in d.get("production_notes") or [] if н.get("id") == rid)


def _spec(raw: dict) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def fired(raw: dict, steps: list[str], brief: str = "") -> dict[str, dict[str, str]]:
    return dict(cl.fire(_spec(raw), steps, text=brief))


def w(base: dict, **more: Any) -> dict:
    return {**base, **more}


def drop(base: dict, *keys: str) -> dict:
    return {k: v for k, v in base.items() if k not in keys}


COURSE = {"task": "generate", "inputs": [{"kind": "script", "owned": True}], "outputs": ["video", "speech"],
          "duration_s": 300, "languages": ["en"], "audio": "voiceover", "people": []}
COURSE_STEPS = ["озвучка", "генерация_видео"]
EXPLAINER = {"task": "generate", "inputs": [{"kind": "script", "owned": True}], "outputs": ["video", "speech"],
             "duration_s": 90, "languages": ["en"], "audio": "voiceover", "people": []}
OWN = {"task": "captions", "inputs": [{"kind": "video", "owned": True, "duration_s": 300}], "outputs": ["video"],
       "duration_s": 300, "languages": ["en"], "people": []}
EDIT = {"task": "video-edit", "inputs": [{"kind": "video", "owned": True, "duration_s": 120}], "outputs": ["video"],
        "duration_s": 120, "edit": ["stabilise"], "people": []}
VO = {"task": "generate", "inputs": [{"kind": "script", "owned": True}], "outputs": ["speech"], "duration_s": 30,
      "languages": ["en"], "people": []}
DUB = {"task": "dub-translate", "inputs": [{"kind": "video", "owned": True, "duration_s": 120}], "outputs": ["video", "speech"],
       "duration_s": 120, "languages": ["de"], "people": []}
STILL = {"task": "generate", "inputs": [{"kind": "text", "owned": True}], "outputs": ["image"], "shots": 1, "people": []}
CLIP = {"task": "generate", "inputs": [{"kind": "text", "owned": True}], "outputs": ["video"], "duration_s": 8, "people": []}
SERIES = {"task": "video-edit", "inputs": [{"kind": "video", "owned": True, "duration_s": 600, "count": 12}],
          "outputs": ["video", "speech"], "duration_s": 60, "languages": ["en"], "audio": "voiceover", "people": []}
LECTURE = {"task": "transcribe", "inputs": [{"kind": "video", "owned": True, "duration_s": 3600}],
           "outputs": ["text", "video"], "languages": ["en"], "accessibility": ["captions", "audio-description"],
           "people": []}


# --- 1. SCORM / xAPI -----------------------------------------------------------------------------


class ЭлектронныйКурс(unittest.TestCase):
    RID = "elearning_scorm_package"

    def test_поле_формата_en(self) -> None:
        d = plan("Five compliance training videos with a narrator, packaged for our company LMS",
                 w(COURSE, delivery={"platform": ["internal"], "format": ["scorm"]}))
        self.assertIn(self.RID, notes(d))
        self.assertIn("4,096 characters of suspend_data", says(d, self.RID))
        self.assertIn("imsmanifest.xml", says(d, self.RID))
        self.assertEqual([], l10n.leaks(d, "en"))

    def test_поле_ru(self) -> None:
        d = plan("Пять обучающих роликов с диктором, упаковать для СДО компании", w(COURSE, delivery={"format": ["xapi"]}))
        self.assertIn("4096 символов suspend_data", says(d, self.RID))

    def test_поле_de(self) -> None:
        # German words are not read: the field decides.
        self.assertIn(self.RID, fired(w(COURSE, delivery={"format": ["scorm"]}), COURSE_STEPS, "Schulungsvideos für die Lernplattform"))

    def test_поле_старше_слов(self) -> None:
        self.assertNotIn(self.RID, fired(w(COURSE, delivery={"format": ["mp4"]}), COURSE_STEPS, "a SCORM course for our LMS"))
        self.assertFalse(x18.elearning_package(_spec(w(COURSE, delivery={"format": ["mp4"]})), "scorm"))

    def test_каждое_слово_отдельно(self) -> None:
        for слово in ("SCORM", "xAPI", "Experience API", "Tin Can API", "cmi5", "our LMS", "a learning management system",
                      "Moodle", "Articulate", "Storyline", "e-learning module", "в СДО",
                      "система дистанционного обучения", "электронный курс"):
            with self.subTest(слово=слово):
                self.assertTrue(x18.elearning_package(_spec(COURSE), слово))

    def test_молчит(self) -> None:
        self.assertNotIn(self.RID, fired(COURSE, COURSE_STEPS, "a training video for our staff"))
        self.assertNotIn(self.RID, fired(COURSE, [], "a SCORM course"))  # nothing planned
        self.assertEqual(("scorm", "xapi"), x18.ELEARNING_FORMATS)
        self.assertIn("scorm", bs.DELIVERY_FORMATS)


# --- 2. medical and scientific explainers ----------------------------------------------------------


class Медицина(unittest.TestCase):
    RID = "medical_science_review"

    def test_поле_области_en(self) -> None:
        d = plan("A 90-second patient explainer of how the knee joint works", w(EXPLAINER, domain=["medical"]))
        self.assertIn(self.RID, notes(d))
        self.assertIn("21 CFR 202.1", says(d, self.RID))
        self.assertIn("invent anatomy", says(d, self.RID))

    def test_наука_ru(self) -> None:
        d = plan("Научно-популярный ролик о фотосинтезе на 90 секунд", w(EXPLAINER, domain=["science"], languages=["ru"]))
        self.assertIn("эксперт по предмету", says(d, self.RID))

    def test_поле_es(self) -> None:
        self.assertIn(self.RID, fired(w(EXPLAINER, domain=["medical"]), COURSE_STEPS, "vídeo explicativo para pacientes"))

    def test_поле_старше_слов(self) -> None:
        self.assertNotIn(self.RID, fired(w(EXPLAINER, domain=["education"]), COURSE_STEPS, "an anatomy explainer"))

    def test_каждое_слово_отдельно(self) -> None:
        for слово in ("anatomy", "a medical explainer", "patient education", "mechanism of action", "the MoA", "pharma",
                      "clinical", "surgery", "physiology", "pathology", "a scientific animation", "molecule",
                      "cell biology", "анатомия", "медицинский", "для пациентов", "механизм действия",
                      "фармацевтический", "клинический", "хирургия", "физиология", "научный ролик", "молекула"):
            with self.subTest(слово=слово):
                self.assertTrue(x18.medical_science(_spec(EXPLAINER), слово))

    def test_молчит(self) -> None:
        self.assertNotIn(self.RID, fired(EXPLAINER, COURSE_STEPS, "an explainer of our banking app"))
        self.assertEqual(("medical", "science"), x18.SCIENCE_DOMAINS)

    def test_политика_заявлений_не_слабее(self) -> None:
        заявление = [{"type": "health_claim", "substantiated": False}]
        реклама = w(EXPLAINER, domain=["health-advertising"], claims=заявление)
        медицина = w(EXPLAINER, domain=["health-advertising", "medical"], claims=заявление)
        brief = "An ad: our tea cures diabetes"
        self.assertEqual(plan(brief, реклама)["claims_policy"]["decision"], plan(brief, медицина)["claims_policy"]["decision"])
        self.assertEqual("refuse", plan(brief, медицина)["claims_policy"]["decision"])


# --- 3. sign language ---------------------------------------------------------------------------------


class ЯзыкЖестов(unittest.TestCase):
    RID = "sign_language_access"

    def test_поле_с_тегом_en(self) -> None:
        d = plan("Our explainer with a signed version", w(OWN, accessibility=["captions", "sign-language"],
                                                         languages=["en-GB", "bfi"]))
        self.assertEqual("sign-language", d["gap"]["job"])
        self.assertIn("BSL (bfi)", says(d, self.RID))
        self.assertIn("native Deaf signers", says(d, self.RID))
        self.assertIn("WFD and WASLI", says(d, self.RID))

    def test_поле_без_тега_ru(self) -> None:
        d = plan("Наш ролик с переводом на жестовый язык", w(OWN, accessibility=["sign-language"], languages=["ru"]))
        self.assertIn("язык жестов региона аудитории — назовите его", says(d, self.RID))
        self.assertEqual([], l10n.leaks({"notes": d["production_notes"]}, "ru"))

    def test_тег_ja(self) -> None:
        d = plan("手話通訳付きの説明動画", w(OWN, languages=["ja", "jsl"]))
        self.assertIn("JSL (jsl)", says(d, self.RID))

    def test_поле_старше_слов(self) -> None:
        # accessibility named without the sign-language need: the words no longer open the gap.
        d = plan("Captions for our explainer and a BSL interpreter inset", w(OWN, accessibility=["captions"]))
        self.assertNotIn("gap", {k for k, v in d.items() if v})
        self.assertFalse(bs.sign_language(_spec(w(OWN, accessibility=["captions"])), "a BSL interpreter"))
        # Without the field the words still decide.
        self.assertTrue(bs.sign_language(_spec(OWN), "a BSL interpreter"))
        # A sign-language tag decides whatever the field says.
        self.assertTrue(bs.sign_language(_spec(w(OWN, accessibility=["captions"], languages=["en", "ase"])), ""))

    def test_имена(self) -> None:
        self.assertEqual("ASL", x18.SIGN_LANGUAGE_NAMES["ase"])
        self.assertEqual("RSL", x18.SIGN_LANGUAGE_NAMES["rsl"])
        self.assertEqual(["RSL (rsl)"], x18.sign_languages(_spec(w(OWN, languages=["ru", "rsl"]))))
        self.assertEqual("sign-language", bs.ACCESSIBILITY_SIGN_LANGUAGE)
        self.assertIn("sign-language", bs.ACCESSIBILITY_NEEDS)

    def test_язык_жестов_не_версия(self) -> None:
        ctx = cl.context(_spec(w(OWN, languages=["en", "ase"])), [])
        self.assertEqual({"en"}, ctx.langs)


# --- 4. loudness ----------------------------------------------------------------------------------------


class Громкость(unittest.TestCase):
    RID = "loudness_measure_after_mix"

    def test_youtube_en(self) -> None:
        d = plan("A 90-second explainer with a narrator for our YouTube channel",
                 w(EXPLAINER, delivery={"platform": ["youtube"]}))
        self.assertIn("about -14 LUFS integrated", says(d, self.RID))
        self.assertIn("FINAL mix", says(d, self.RID))

    def test_эфир_ru(self) -> None:
        d = plan("Ролик на 90 секунд с диктором для эфира", w(EXPLAINER, delivery={"platform": ["broadcast"]}, languages=["ru"]))
        self.assertIn("-23 LUFS интегрально", says(d, self.RID))
        self.assertIn("ИТОГОВОМ миксе", says(d, self.RID))

    def test_площадки_fr(self) -> None:
        def цель(*площадки: str) -> str:
            got = fired(w(EXPLAINER, delivery={"platform": list(площадки)}), COURSE_STEPS, "une vidéo explicative")
            return got.get(self.RID, {}).get("target_en", "")

        self.assertIn("-16 LUFS", цель("podcast"))
        self.assertIn("-24 LUFS", цель("game-engine"))
        self.assertIn("-16 LUFS", цель("web"))
        self.assertIn("-27 LKFS", цель("streaming-premium"))
        self.assertIn("Spotify", цель("music-distribution"))
        self.assertIn("TikTok", цель("tiktok"))
        self.assertIn("-23 LUFS", цель("print", "broadcast"))
        self.assertEqual("", цель("print"))

    def test_без_площадки_слова(self) -> None:
        for слово in ("LUFS", "LKFS", "dBTP", "loudness", "EBU R128", "громкость"):
            with self.subTest(слово=слово):
                self.assertEqual(x18.LOUDNESS_ASK, x18.loudness_target(_spec(EXPLAINER), слово))
        self.assertNotIn(self.RID, fired(EXPLAINER, COURSE_STEPS, "an explainer"))
        # The platform named decides: no loudness target on a print platform whatever the words say.
        self.assertIsNone(x18.loudness_target(_spec(w(EXPLAINER, delivery={"platform": ["print"]})), "LUFS"))

    def test_звук_в_результате(self) -> None:
        тихий = w(CLIP, delivery={"platform": ["youtube"]})
        self.assertNotIn(self.RID, fired(тихий, ["генерация_видео"]))
        свой = w(EDIT, delivery={"platform": ["youtube"]})
        self.assertIn(self.RID, fired(свой, ["правка_видео"]))
        self.assertNotIn(self.RID, fired(w(свой, audio="none"), ["правка_видео"]))


# --- 5. dialogue replacement, nonverbal sounds -----------------------------------------------------------


class ЗаменаРеплик(unittest.TestCase):
    RID = "adr_room_tone_match"

    def test_дубляж_с_губами_en(self) -> None:
        d = plan("Dub our 2-minute product video into German with lip sync", DUB)
        self.assertIn(self.RID, notes(d))
        self.assertIn("room tone", says(d, self.RID))

    def test_липсинк_новой_фразы_ru(self) -> None:
        raw = {"task": "lipsync", "inputs": [{"kind": "video", "owned": True, "duration_s": 20}, {"kind": "script", "owned": True}],
               "outputs": ["video"], "duration_s": 20, "languages": ["ru"], "people": []}
        self.assertIn(self.RID, fired(raw, ["озвучка", "липсинк"], "заменить одну фразу в интервью"))
        self.assertIn(self.RID, fired(raw, ["озвучка", "липсинк"], "neue Zeile im Interview"))  # de: structure decides

    def test_закадровый_дубляж_молчит(self) -> None:
        закадр = w(DUB, lipsync=False, audio="voiceover")
        self.assertNotIn(self.RID, fired(закадр, ["дубляж"], "dub into German as a voice-over"))
        self.assertNotIn(self.RID, fired(w(VO), ["озвучка"], "re-record the line"))  # no footage of theirs

    def test_каждое_слово_отдельно(self) -> None:
        for слово in ("ADR", "re-record the line", "dialogue replacement", "room tone", "replace one word",
                      "fix the line", "change a sentence", "переозвучка", "рум-тон", "заменить фразу", "исправить реплику"):
            with self.subTest(слово=слово):
                self.assertIn(self.RID, fired(w(DUB, lipsync=False, audio="voiceover"), ["дубляж"], слово))


class Неречевые(unittest.TestCase):
    RID = "nonverbal_vocalisations"

    def test_игра_en(self) -> None:
        d = plan("40 combat barks for our game hero", w(VO, delivery={"platform": ["game-engine"]}, duration_s=120))
        self.assertIn(self.RID, notes(d))
        self.assertIn("[laughs]", says(d, self.RID))
        self.assertIn("3-5 takes per bark", says(d, self.RID))

    def test_площадка_игры_de(self) -> None:
        игра = w(VO, delivery={"platform": ["game-engine"]})
        self.assertIn(self.RID, fired(игра, ["озвучка"], "Sprachaufnahmen für unseren Helden"))
        self.assertNotIn(self.RID, fired(w(игра, delivery={"platform": ["web"]}), ["озвучка"], "Sprachaufnahmen"))

    def test_поля_ru_es(self) -> None:
        self.assertIn(self.RID, fired(w(VO, domain=["entertainment"]), ["озвучка"], "радиоспектакль"))
        двое = w(VO, characters=2)
        self.assertIn(self.RID, fired(двое, ["озвучка"], "un diálogo entre dos personajes"))

    def test_каждое_слово_отдельно(self) -> None:
        for слово in ("she laughs", "a breath", "sighs", "screams", "grunts", "efforts", "barks", "gasps", "crying",
                      "sobbing", "whispering", "vocalisations", "nonverbal", "смех", "смеётся", "вздох", "дыхание",
                      "крик", "кряхтение", "стон", "плач", "шёпот", "шепчет", "междометия", "возгласы"):
            with self.subTest(слово=слово):
                self.assertIn(self.RID, fired(VO, ["озвучка"], слово))

    def test_молчит(self) -> None:
        self.assertNotIn(self.RID, fired(VO, ["озвучка"], "a calm corporate voice-over"))
        self.assertNotIn(self.RID, fired(STILL, ["генерация_изображения"], "a laughing child"))


# --- 6. typography -----------------------------------------------------------------------------------------


class Типографика(unittest.TestCase):
    def test_японский_en(self) -> None:
        got = fired(w(OWN, languages=["ja"]), ["расшифровка"], "Japanese subtitles for our film")
        self.assertIn("cjk_locale_glyphs", got)
        self.assertEqual({"locales": "ja"}, got["cjk_vertical_text"])
        self.assertIn("tate-chu-yoko", cl.RULES["cjk_vertical_text"].en)
        self.assertIn("Noto Sans CJK JP / SC / TC / HK / KR", cl.RULES["cjk_locale_glyphs"].en)

    def test_китайский_ru(self) -> None:
        голый = fired(w(OWN, languages=["zh"]), ["расшифровка"], "китайские субтитры")
        self.assertIn("zh-Hans / zh-Hant", голый["cjk_locale_glyphs"]["locales"])
        self.assertNotIn("cjk_vertical_text", голый)
        тайвань = fired(w(OWN, languages=["zh-TW"]), ["расшифровка"], "субтитры для Тайваня")
        self.assertEqual({"locales": "zh-TW"}, тайвань["cjk_locale_glyphs"])
        self.assertIn("cjk_vertical_text", тайвань)
        self.assertNotIn("cjk_vertical_text", fired(w(OWN, languages=["zh-CN"]), ["расшифровка"]))
        self.assertNotIn("cjk_vertical_text", fired(w(OWN, languages=["ko"]), ["расшифровка"]))

    def test_без_картинки_молчит(self) -> None:
        got = fired(w(VO, languages=["ja"]), ["озвучка"], "ナレーション")
        self.assertNotIn("cjk_locale_glyphs", got)
        self.assertNotIn("cjk_vertical_text", got)

    def test_rtl_графика_fr(self) -> None:
        got = fired(w(EXPLAINER, languages=["ar", "ur"]), COURSE_STEPS, "une vidéo en arabe et en ourdou")
        self.assertEqual({"langs": "ar, ur"}, got["rtl_graphics_fonts"])
        self.assertIn("Nastaliq", cl.RULES["rtl_graphics_fonts"].en)
        текст = {"task": "transcribe", "inputs": [{"kind": "audio", "owned": True, "duration_s": 60}], "outputs": ["text"],
                 "languages": ["ar"], "people": []}
        self.assertNotIn("rtl_graphics_fonts", fired(текст, ["расшифровка"]))

    def test_вертикальные_локали(self) -> None:
        self.assertEqual((["ja"], True, False), x18.cjk_locales(["ja"]))
        self.assertEqual((["zh-Hant"], True, False), x18.cjk_locales(["zh-Hant"]))
        self.assertEqual((["zh-HK"], True, False), x18.cjk_locales(["zh-HK"]))
        self.assertEqual((["zh-Hans"], False, False), x18.cjk_locales(["zh-Hans"]))


# --- 7. textless master ----------------------------------------------------------------------------------


class БезТитров(unittest.TestCase):
    RID = "textless_master"

    def test_языки_en(self) -> None:
        d = plan("A 90-second explainer in English and French", w(EXPLAINER, languages=["en", "fr"]))
        self.assertIn(self.RID, notes(d))
        self.assertIn("TEXTLESS version", says(d, self.RID))

    def test_рынки_ru_и_дубляж(self) -> None:
        self.assertIn(self.RID, fired(w(EXPLAINER, delivery={"markets": ["DE", "FR"]}), COURSE_STEPS, "ролик для двух рынков"))
        self.assertIn(self.RID, fired(DUB, ["дубляж", "липсинк"], "doblaje al alemán"))

    def test_поле_старше_слов(self) -> None:
        self.assertNotIn(self.RID, fired(EXPLAINER, COURSE_STEPS, "deliver a textless version too"))
        self.assertNotIn(self.RID, fired(w(EXPLAINER, delivery={"markets": ["DE"]}), COURSE_STEPS, "textless please"))

    def test_каждое_слово_отдельно(self) -> None:
        без = drop(EXPLAINER, "languages")
        for слово in ("a textless master", "a clean feed", "a version without titles", "an international version",
                      "the M&E", "versions for 5 markets", "без титров", "без надписей", "чистая версия", "текстлесс",
                      "международная версия"):
            with self.subTest(слово=слово):
                self.assertIn(self.RID, fired(без, COURSE_STEPS, слово))
        self.assertNotIn(self.RID, fired(без, COURSE_STEPS, "an explainer"))

    def test_смешанная_дорожка_не_версии(self) -> None:
        смесь = w(EXPLAINER, languages=["hi", "en", "mul"])
        self.assertNotIn(self.RID, fired(смесь, COURSE_STEPS, "Hinglish explainer"))
        self.assertEqual(2, x18.TEXTLESS_MIN_VERSIONS)


# --- 8. garments, glass and liquid ------------------------------------------------------------------------


class ОдеждаИСтекло(unittest.TestCase):
    def test_примерка_en(self) -> None:
        self.assertIn("garment_print_drape", fired(w(STILL, subject=["garment"]), ["генерация_изображения"], "a lookbook shot"))
        self.assertIn("garment_print_drape", fired(STILL, ["примерка"], "virtuelle Anprobe"))
        self.assertIn("a 5 cm check stays 5 cm", cl.RULES["garment_print_drape"].en)

    def test_поле_старше_слов_ru(self) -> None:
        self.assertNotIn("garment_print_drape", fired(w(STILL, subject=["product"]), ["генерация_изображения"], "платье на модели"))

    def test_каждое_слово_одежды(self) -> None:
        for слово in ("try-on", "garment", "a dress", "fabric", "apparel", "clothing", "outfit", "t-shirt", "jacket",
                      "printed pattern", "примерка", "одежда", "ткань", "платье", "футболка", "куртка", "принт"):
            with self.subTest(слово=слово):
                self.assertIn("garment_print_drape", fired(STILL, ["генерация_изображения"], слово))
        self.assertNotIn("garment_print_drape", fired(VO, ["озвучка"], "a dress shop jingle"))

    def test_стекло_поле_es(self) -> None:
        self.assertIn("glass_liquid_optics", fired(w(CLIP, subject=["transparent"]), ["генерация_видео"], "un anuncio de perfume"))
        self.assertNotIn("glass_liquid_optics", fired(w(CLIP, subject=["reflective"]), ["генерация_видео"], "a glass bottle"))
        self.assertIn("IOR about 1.5", cl.RULES["glass_liquid_optics"].en)
        self.assertEqual(("transparent",), x18.GLASS_SUBJECTS)

    def test_каждое_слово_стекла(self) -> None:
        for слово in ("glassware", "liquid", "a bottle", "perfume", "fragrance", "pouring", "splash", "beverage", "drinks",
                      "ice cubes", "juice", "cocktail", "стекло", "стакан", "жидкость", "флакон", "бутылка", "парфюм",
                      "духи", "напиток", "наливается", "брызги", "коктейль", "сок"):
            with self.subTest(слово=слово):
                self.assertIn("glass_liquid_optics", fired(CLIP, ["генерация_видео"], слово))
        self.assertNotIn("glass_liquid_optics", fired(CLIP, ["генерация_видео"], "a sneaker on a rock"))
        self.assertNotIn("glass_liquid_optics", fired(VO, ["озвучка"], "a perfume jingle"))


# --- 9. render from data --------------------------------------------------------------------------------------


class ИзДанных(unittest.TestCase):
    RID = "render_from_data"

    def test_поле_en_ru_de(self) -> None:
        d = plan("A 90-second explainer of our quarterly results", w(EXPLAINER, subject=["chart"]))
        self.assertIn(self.RID, notes(d))
        self.assertIn("render them FROM the data", says(d, self.RID))
        self.assertIn(self.RID, fired(w(EXPLAINER, subject=["map"]), COURSE_STEPS, "ролик о маршруте экспедиции"))
        self.assertIn(self.RID, fired(w(STILL, subject=["chart"]), ["генерация_изображения"], "Quartalszahlen als Grafik"))

    def test_поле_старше_слов(self) -> None:
        self.assertNotIn(self.RID, fired(w(EXPLAINER, subject=["product"]), COURSE_STEPS, "a bar chart of sales"))
        self.assertEqual(("chart", "map"), x18.DATA_SUBJECTS)
        self.assertIn("map", bs.SUBJECTS)

    def test_каждое_слово_отдельно(self) -> None:
        for слово in ("a chart", "graphs", "an infographic", "data viz", "a dashboard", "statistics", "a bar chart",
                      "a pie chart", "our KPIs", "a route map", "a world map", "map of Europe", "диаграмма", "график",
                      "инфографика", "статистика", "дашборд", "карта мира", "анимированная карта"):
            with self.subTest(слово=слово):
                self.assertIn(self.RID, fired(EXPLAINER, COURSE_STEPS, слово))
        for слово in ("a depth map", "the roadmap talk", "a texture map"):
            with self.subTest(слово=слово):
                self.assertNotIn(self.RID, fired(EXPLAINER, COURSE_STEPS, слово))
        self.assertNotIn(self.RID, fired(VO, ["озвучка"], "read the statistics aloud"))


# --- 10. accents, mixed-language voice -------------------------------------------------------------------------


class Акцент(unittest.TestCase):
    RID = "voice_locale_accent"

    def test_регион_en(self) -> None:
        d = plan("A 30-second radio spot for Mexico", w(VO, languages=["es-MX"]))
        self.assertIn(self.RID, notes(d))
        self.assertIn("accent and locale (es-MX)", says(d, self.RID))

    def test_голый_тег_ru_pt(self) -> None:
        got = fired(w(VO, languages=["pt"]), ["озвучка"], "озвучка рекламы на португальском")
        self.assertEqual({"locales": "pt (pt-BR / pt-PT?)"}, got[self.RID])
        self.assertEqual({"locales": "es (es-ES / es-MX / es-US?)"}, fired(w(VO, languages=["es"]), ["озвучка"])[self.RID])
        self.assertEqual({"locales": "en-GB"}, fired(w(VO, languages=["en-GB"]), ["озвучка"])[self.RID])

    def test_молчит(self) -> None:
        self.assertNotIn(self.RID, fired(VO, ["озвучка"], "an English voice-over"))
        self.assertNotIn(self.RID, fired(w(VO, languages=["fr", "de"]), ["озвучка"]))
        self.assertNotIn(self.RID, fired(w(VO, languages=["es-MX"]), ["генерация_изображения"]))
        # Languages named: the accent words do not add a variant.
        self.assertNotIn(self.RID, fired(w(VO, languages=["ja"]), ["озвучка"], "with a Kansai accent"))

    def test_слова_без_языков(self) -> None:
        без = drop(VO, "languages")
        for слово in ("an accent", "dialect", "LatAm", "Latin American Spanish", "Castilian", "Brazilian Portuguese",
                      "European Portuguese", "Canadian French", "акцент", "диалект", "латиноамериканский",
                      "бразильский португальский", "европейский португальский"):
            with self.subTest(слово=слово):
                self.assertIn(self.RID, fired(без, ["озвучка"], слово))

    def test_константы(self) -> None:
        self.assertEqual(frozenset({"es", "pt", "ar", "zh"}), x18.BARE_UNDECIDED)
        self.assertIn("de", x18.PLURICENTRIC)
        self.assertEqual({"locales": "de-AT"}, fired(w(VO, languages=["de-AT"]), ["озвучка"])[self.RID])


class СмешаннаяОзвучка(unittest.TestCase):
    def test_mul_озвучка_hi(self) -> None:
        d = plan("हिंग्लिश में 30 सेकंड का रेडियो विज्ञापन", w(VO, languages=["hi", "en", "mul"]))
        self.assertIn("code_switching_speech", notes(d))
        self.assertNotIn("translation_review", notes(d))
        self.assertEqual(0.04, clip_usd(d))

    def test_mul_закадр_видео_en(self) -> None:
        d = plan("A 60-second Hinglish explainer with a voice-over", w(EXPLAINER, duration_s=60, languages=["hi", "en", "mul"]))
        self.assertIn("code_switching_speech", notes(d))
        self.assertNotIn("translation_review", notes(d))
        self.assertNotIn("me_stems_delivery", notes(d))
        self.assertNotIn("textless_master", notes(d))
        self.assertEqual(0.07, round(step_usd(d, "озвучка"), 2))

    def test_слова_ru(self) -> None:
        got = fired(w(VO, languages=["ru", "en"]), ["озвучка"], "диктор говорит вперемешку по-русски и по-английски")
        self.assertIn("code_switching_speech", got)
        self.assertNotIn("translation_review", got)

    def test_две_версии_перевод_остаётся(self) -> None:
        self.assertIn("translation_review", fired(w(VO, languages=["hi", "en"]), ["озвучка"], "two versions"))
        # A transcript of mixed speech keeps the round-17 behaviour (the translation may follow).
        asr = {"task": "transcribe", "inputs": [{"kind": "audio", "owned": True, "duration_s": 600}], "outputs": ["text"],
               "languages": ["hi", "en", "mul"], "people": []}
        self.assertIn("translation_review", fired(asr, ["расшифровка"]))
        self.assertEqual({"hi", "en"}, cl.context(_spec(asr), []).langs)


# --- 11. pricing residuals -----------------------------------------------------------------------------------


class Цены(unittest.TestCase):
    def test_сезон_за_минуту_en(self) -> None:
        d = plan("Season one in a minute, narrated", SERIES)
        self.assertEqual(["расшифровка", "озвучка"], steps_of(d))
        self.assertNotIn("правка_видео", steps_of(d))
        self.assertEqual(0.96, step_usd(d, "расшифровка"))
        self.assertEqual(1.03, clip_usd(d))
        self.assertIn("highlight_selection", notes(d))

    def test_сезон_ru_ja(self) -> None:
        d = plan("Весь сезон за минуту, с диктором", SERIES)
        self.assertNotIn("правка_видео", steps_of(d))
        d = plan("シーズン1を1分でまとめて、ナレーション付き", SERIES)
        self.assertEqual(1.03, clip_usd(d))

    def test_порог_сжатия(self) -> None:
        self.assertEqual(0.5, x18.CONDENSE_SHARE)
        один = {"task": "video-edit", "inputs": [{"kind": "video", "owned": True, "duration_s": 120}], "outputs": ["video"],
                "people": []}
        self.assertTrue(x18.condensed_cut(_spec(w(один, duration_s=60))))
        self.assertFalse(x18.condensed_cut(_spec(w(один, duration_s=61))))
        self.assertFalse(x18.condensed_cut(_spec(w(один, duration_s=60, edit=["stabilise"]))))
        self.assertFalse(x18.condensed_cut(_spec(w(один, duration_s=60, edit_target="sky"))))
        self.assertFalse(x18.condensed_cut(_spec(w(один, duration_s=60, task="dub-translate"))))
        # Without a named length nothing is condensed.
        self.assertFalse(x18.condensed_cut(_spec(один)))
        self.assertFalse(x17.recap_edit(_spec(w(один, duration_s=61)), "make it nicer"))
        self.assertTrue(x17.recap_edit(_spec(w(один, duration_s=60)), "make it nicer"))

    def test_одна_программа_дважды(self) -> None:
        двойной = w(LECTURE, inputs=[{"kind": "video", "owned": True, "duration_s": 3600},
                                     {"kind": "audio", "owned": True, "duration_s": 3600}])
        d = plan("Lecture video plus the lavalier recording: captions, transcript and audio description", двойной)
        self.assertEqual(0.48, step_usd(d, "расшифровка"))
        self.assertEqual(0.68, clip_usd(d))
        self.assertEqual(3600.0, x18.programme_seconds(_spec(двойной)))
        self.assertEqual(3600.0, x15.material_seconds(_spec(двойной)))
        self.assertEqual(3600.0, x17.material_seconds(_spec(двойной)))
        # Different lengths are different material.
        разные = w(двойной, inputs=[{"kind": "video", "owned": True, "duration_s": 3600},
                                    {"kind": "audio", "owned": True, "duration_s": 1800}])
        self.assertEqual(5400.0, x18.programme_seconds(_spec(разные)))
        self.assertEqual(5400.0, x15.material_seconds(_spec(разные)))

    def test_пакет_расшифровкой_ru(self) -> None:
        d = plan("Пакет доступности для лекции на час: субтитры, расшифровка и тифлокомментарий", w(LECTURE, outputs=["text"]))
        self.assertEqual(0.68, clip_usd(d))


# --- the table, the fields, the facts -------------------------------------------------------------------------


class Таблица(unittest.TestCase):
    def test_правила_с_источниками(self) -> None:
        ids = [р.id for р in cl.RULES_R18]
        self.assertEqual(
            ["elearning_scorm_package", "medical_science_review", "sign_language_access", "loudness_measure_after_mix",
             "adr_room_tone_match", "nonverbal_vocalisations", "cjk_locale_glyphs", "cjk_vertical_text",
             "rtl_graphics_fonts", "textless_master", "garment_print_drape", "glass_liquid_optics", "render_from_data",
             "voice_locale_accent"], ids)
        for р in cl.RULES_R18:
            self.assertTrue(all(u.startswith("https://") for u in р.sources), р.id)
            if р.tag == cl.TAG_REGULATION:
                self.assertTrue(р.sources, р.id)

    def test_поля_принимаются(self) -> None:
        raw = w(EXPLAINER, delivery={"format": ["scorm", "xapi"]}, domain=["medical", "science"],
                subject=["chart", "map"], accessibility=["sign-language"])
        _spec(raw)
        help_ = {**bs.FIELD_HELP, **bs.OPTIONAL_HELP}
        self.assertIn("scorm / xapi = an e-learning package", help_["delivery.format"])
        self.assertIn("medical / science", help_["domain"])
        self.assertIn("chart / map", help_["subject"])
        self.assertIn("sign-language = a signed version", help_["accessibility"])

    def test_описание_инструмента(self) -> None:
        описание = server.plan_pipeline.__doc__ or ""
        self.assertIn("delivery.format scorm | xapi", описание)
        self.assertIn("subject chart | map", описание)

    def test_запасные_слова_в_черновике(self) -> None:
        got = bs._прочитано_словами("A SCORM course on knee anatomy with charts and a BSL interpreter",
                                    "a scorm course on knee anatomy with charts and a bsl interpreter")
        self.assertEqual(["scorm"], got["delivery.format"])
        self.assertIn("medical", got["domain"])
        self.assertIn("chart", got["subject"])
        self.assertEqual(["sign-language"], got["accessibility"])

    def test_факты(self) -> None:
        факты = {(f.model, f.attribute): f.value for f in load_facts()}
        self.assertIn("(laughs)", факты[("dia-1.6b", "capabilities")])
        self.assertIn("[sighs]", факты[("eleven_v4", "capabilities")])
        self.assertIn("audio tags", факты[("eleven_v3", "capabilities")])


if __name__ == "__main__":
    unittest.main()
