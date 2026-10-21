"""Round 18 integration: the routes (agent A) and the specialist knowledge (agent B) on ONE order.

Every case is a paraphrase written for this file, never a dev or holdout brief. No network (T4).

a. try-on batch + `garment_print_drape` + `glass_liquid_optics`
b. restoration chain with faces + `domain` medical / science
c. speech batch for a game engine + `nonverbal_vocalisations` + the game loudness target
d. podcast -> video + loudness + captions for YouTube (the customer's own recording IS the sound)
e. vertical reframe + RTL / CJK typography
f. motion comic + textless master for 2+ markets (the lettering is part of the art)
g. sign-language accessibility + the podcast / explainer route (the round-7 gap stays, with the note)
h. figures put into caveats from memory (sources refused by the proxy) say so in EN and RU
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Any

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import expert_r18 as x18  # noqa: E402
from studio import l10n  # noqa: E402
from studio import routes_r18 as r18  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import checklist as cl  # noqa: E402

_PLANS: dict[str, dict] = {}


def plan(brief: str, spec: dict) -> dict:
    ключ = brief + json.dumps(spec, sort_keys=True, ensure_ascii=False)
    if ключ not in _PLANS:
        _PLANS[ключ] = json.loads(server.plan_pipeline(brief, spec=spec))
    return _PLANS[ключ]


def steps_of(d: dict) -> list[str]:
    return [str(ш.get("step")) for ш in d.get("steps") or []]


def notes(d: dict) -> list[str]:
    return [str(н.get("id")) for н in d.get("production_notes") or []]


def says(d: dict, rid: str) -> str:
    return next(str(н.get("says")) for н in d.get("production_notes") or [] if н.get("id") == rid)


def passes(d: dict, name: str) -> list[str]:
    for ш in d.get("steps") or []:
        if ш.get("step") == name:
            return [str(п.get("step")) for п in ш.get("passes") or []]
    raise AssertionError(f"no step {name}: {steps_of(d)}")


def assembly(d: dict) -> str:
    return " | ".join(str(с) for с in (d.get("assembly") or {}).get("why") or [])


def _spec(raw: dict) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def applied(brief: str, raw: dict) -> Any:
    from studio.recipes import apply as ra

    spec = bs.with_defaults(_spec(raw), ролик=True, текст=brief)
    return ra.rewrite(spec, bs.route(spec), brief)


def w(base: dict, **more: Any) -> dict:
    return {**base, **more}


def P(**more: Any) -> dict:
    return {"kind": "image", "owned": True, **more}


# --- a. try-on + garment + glass ------------------------------------------------------------------------

TRY = {"task": "generate", "inputs": [P(count=6, role="garment")], "outputs": ["image"], "shots": 18,
       "languages": [], "subject": ["garment", "transparent"], "people": [], "views": 3}


class ПримеркаОдеждаСтекло(unittest.TestCase):
    def test_маршрут_и_обе_оговорки(self) -> None:
        for brief in ("Our 6 sequined dresses with a glass clutch on a model, 3 views",
                      "Наши 6 платьев со стеклянным клатчем на модели, 3 ракурса",
                      "Nuestros 6 vestidos con un bolso de cristal, 3 vistas"):
            d = plan(brief, TRY)
            self.assertEqual(["генерация_изображения", "примерка"], steps_of(d), brief)
            self.assertIn("garment_print_drape", notes(d), brief)
            self.assertIn("glass_liquid_optics", notes(d), brief)

    def test_реальная_модель_в_своих_фото(self) -> None:
        # A real person listed on screen is in the customer's photos: no generated on-model base.
        talent = [{"name": "models", "real": True, "public_figure": False, "consent": "stated", "role": "talent",
                   "on_screen": True, "speaks": False}]
        raw = w(TRY, inputs=[P(count=15)], subject=["person", "garment"], people=talent, task="edit")
        raw = {k: v for k, v in raw.items() if k != "views"}
        for brief in ("Retouchez nos maillots portés par nos mannequins", "Отретушировать купальники на наших моделях",
                      "Retouch the swimsuits on our models"):
            а = applied(brief, raw)
            self.assertNotIn("генерация_изображения", а.route.шаги, brief)
        # Not on screen (a voice, a name in the credits): the base is generated as before.
        а = applied("Our swimsuits", w(raw, people=[{**talent[0], "on_screen": False}]))
        self.assertIn("генерация_изображения", а.route.шаги)

    def test_примерка_сама_несёт_одежду(self) -> None:
        # No `subject` garment and no garment words: the try-on step alone makes it a garment order.
        raw = w(TRY, subject=["transparent"])
        d = plan("Six items on our model, three angles", raw)
        self.assertIn("примерка", steps_of(d))
        self.assertIn("garment_print_drape", notes(d))
        self.assertIn("glass_liquid_optics", notes(d))

    def test_без_стекла_нет_оптики(self) -> None:
        d = plan("Six items on a model, three angles", w(TRY, subject=["garment"]))
        self.assertNotIn("glass_liquid_optics", notes(d))
        self.assertIn("garment_print_drape", notes(d))


# --- b. restoration chain with faces + medical / science --------------------------------------------------

OLD = {"task": "restore", "inputs": [P(source=["archival"], defects=["scratches"], resolution="800x600")],
       "outputs": ["image"], "resolution": "4k", "languages": [], "people": [], "colorize": True,
       "subject": ["person"], "domain": ["medical"]}


class РеставрацияМедицина(unittest.TestCase):
    CHAIN = ["реставрация_изображения", "раскраска_изображения", "апскейл_изображения"]

    def test_цепочка_и_проверка_эксперта(self) -> None:
        for brief in ("Restore the portrait of our hospital's founding surgeon",
                      "Отреставрировать портрет основателя нашей клиники",
                      "Restaurer le portrait du fondateur de notre hôpital"):
            d = plan(brief, OLD)
            self.assertEqual(self.CHAIN, steps_of(d), brief)
            self.assertEqual(["восстановление_лиц"], passes(d, "реставрация_изображения"), brief)
            self.assertIn("medical_science_review", notes(d), brief)
            self.assertIn("restore_chain", notes(d), brief)

    def test_наука_тоже(self) -> None:
        d = plan("Restore the lab photo of the 1950s research team", w(OLD, domain=["science"]))
        self.assertEqual(self.CHAIN, steps_of(d))
        self.assertEqual(["восстановление_лиц"], passes(d, "реставрация_изображения"))
        self.assertIn("medical_science_review", notes(d))

    def test_область_не_трогает_лица(self) -> None:
        # The domain adds a caveat; the face pass is still decided by the subject.
        d = plan("Restore the specimen plate", w(OLD, subject=["other"]))
        self.assertEqual([], passes(d, "реставрация_изображения"))
        self.assertIn("medical_science_review", notes(d))
        d = plan("Restore the portrait", w(OLD, domain=["education"]))
        self.assertEqual(["восстановление_лиц"], passes(d, "реставрация_изображения"))
        self.assertNotIn("medical_science_review", notes(d))


# --- c. speech batch for a game engine + nonverbal sounds + loudness ---------------------------------------

BARKS = {"task": "generate", "inputs": [{"kind": "text", "owned": True}], "outputs": ["speech"], "languages": ["en"],
         "people": [], "lines": 40, "variations": 2, "characters": 3, "delivery": {"platform": ["game-engine"]}}


class ПартияРепликИгра(unittest.TestCase):
    def test_партия_звуки_громкость(self) -> None:
        for brief in ("Combat barks for our game", "Боевые реплики для нашей игры", "Frases de combate"):
            d = plan(brief, BARKS)
            self.assertEqual(["озвучка"], steps_of(d), brief)
            self.assertIn("nonverbal_vocalisations", notes(d), brief)
            self.assertIn("-24 LUFS", says(d, "loudness_measure_after_mix"), brief)
            self.assertIn("-18 LUFS", says(d, "loudness_measure_after_mix"), brief)

    def test_по_русски(self) -> None:
        d = plan("Боевые реплики для нашей игры", w(BARKS, languages=["ru"]))
        self.assertIn("-24 LUFS", says(d, "loudness_measure_after_mix"))
        self.assertIn("ИТОГОВОМ миксе", says(d, "loudness_measure_after_mix"))

    def test_ivr_не_игра(self) -> None:
        d = plan("Phone menu prompts", w(BARKS, characters=1, variations=1, delivery={"platform": ["telephony"]}))
        self.assertNotIn("-24 LUFS", json.dumps(d.get("production_notes"), ensure_ascii=False))


# --- d. podcast -> video + loudness + captions for YouTube --------------------------------------------------

POD = {"task": "generate", "inputs": [{"kind": "audio", "owned": True, "duration_s": 2700}],
       "outputs": ["video"], "duration_s": 2700, "languages": ["en"], "people": [], "audio_content": ["speech"],
       "delivery": {"platform": ["youtube"]}, "accessibility": ["captions"]}


class ПодкастЮтуб(unittest.TestCase):
    def test_громкость_своей_записи(self) -> None:
        for brief in ("Turn our 45-minute episode into a YouTube video", "Видео из нашего выпуска для YouTube",
                      "Notre épisode en vidéo pour YouTube"):
            d = plan(brief, POD)
            self.assertEqual(["генерация_изображения", "расшифровка"], steps_of(d), brief)
            # The customer's recording is the soundtrack: the YouTube target is stated.
            self.assertIn("-14 LUFS", says(d, "loudness_measure_after_mix"), brief)
            self.assertIn("wcag_captions", notes(d), brief)
            self.assertIn("showwaves", assembly(d), brief)

    def test_без_площадки_и_субтитров_только_сборка(self) -> None:
        # A cover brought, no platform, no captions asked: the cover + the waveform is pure assembly.
        raw = {"task": "music-visualiser", "inputs": [{"kind": "audio", "owned": True, "duration_s": 3000}, P()],
               "outputs": ["video"], "duration_s": 3000, "aspect": "16:9", "people": [], "audio_content": ["speech"]}
        for brief in ("A waveform video of our podcast episode over our cover", "Видео-волна нашего подкаста на обложке",
                      "Une vidéo en forme d'onde de notre podcast"):
            d = plan(brief, raw)
            self.assertEqual([], steps_of(d), brief)
            self.assertEqual("только_монтаж", d.get("reason"), brief)
            self.assertIn("showwaves", json.dumps(d, ensure_ascii=False), brief)
            self.assertNotIn("расшифровк", json.dumps(d.get("steps"), ensure_ascii=False), brief)
        # Captions named by a field or by the words: the transcript comes back.
        self.assertEqual(["расшифровка"], steps_of(plan("Waveform video", w(raw, accessibility=["captions"]))))
        self.assertEqual(["расшифровка"], steps_of(plan("Waveform video with subtitles", raw)))
        self.assertEqual(["расшифровка"], steps_of(plan("Видео-волна с субтитрами", raw)))
        self.assertEqual(["расшифровка"], steps_of(plan("Waveform video", w(raw, delivery={"platform": ["youtube"]}))))
        self.assertEqual(["расшифровка"], steps_of(plan("Waveform video", w(raw, outputs=["video", "text"]))))

    def test_задача_субтитры_к_записи(self) -> None:
        raw = {"task": "captions", "inputs": [{"kind": "audio", "owned": True, "duration_s": 1800}, P()],
               "outputs": ["video"], "duration_s": 1800, "languages": ["en"], "accessibility": ["captions"],
               "delivery": {"platform": ["youtube"]}, "people": []}
        for brief in ("Captions for our episode as a YouTube video", "Субтитры к выпуску, видео для YouTube",
                      "Sous-titres de notre épisode pour YouTube"):
            d = plan(brief, raw)
            self.assertEqual(["расшифровка"], steps_of(d), brief)
            self.assertIn("showwaves", assembly(d), brief)
        # A song is a music visualiser's job, not an audiogram.
        self.assertFalse(r18.podcast_video(_spec(w(raw, audio_content=["song"])), "x"))
        # Captions of the customer's own video are not an audiogram.
        own = w(raw, inputs=[{"kind": "video", "owned": True, "duration_s": 60}])
        self.assertFalse(r18.podcast_video(_spec(own), "x"))

    def test_аватар_отказан_словами(self) -> None:
        raw = {"task": "generate", "inputs": [{"kind": "audio", "owned": True, "duration_s": 600}],
               "outputs": ["video"], "duration_s": 600, "people": [], "delivery": {"platform": ["youtube"]}}
        spec = _spec(raw)
        for слова in ("our podcast as a video, no avatars please", "our podcast without a talking head",
                      "видео из подкаста, без аватаров", "подкаст в видео, аватары не нужны"):
            self.assertFalse(r18.avatar_asked(spec, слова), слова)
            self.assertTrue(r18.podcast_video(spec, слова), слова)
        for слова in ("our podcast with a talking avatar of the host", "подкаст с аватаром ведущего"):
            self.assertTrue(r18.avatar_asked(spec, слова), слова)

    def test_субтитры_подкаста_по_полям(self) -> None:
        base = _spec({"task": "generate", "inputs": [{"kind": "audio", "owned": True, "duration_s": 60}],
                      "outputs": ["video"], "duration_s": 60, "people": []})
        self.assertFalse(r18.podcast_captions(base, "our episode"))
        self.assertTrue(r18.podcast_captions(base, "our episode with chapters"))
        self.assertTrue(r18.podcast_captions(base, "наш выпуск, расшифровка"))
        self.assertTrue(r18.podcast_captions(_spec({"task": "generate", "inputs": [{"kind": "audio", "owned": True}],
                                                     "outputs": ["video"], "people": [],
                                                     "delivery": {"format": ["srt"]}}), "x"))

    def test_без_звука_нет_громкости(self) -> None:
        d = plan("A silent cover video for our episode", w(POD, audio="none"))
        self.assertNotIn("loudness_measure_after_mix", notes(d))

    def test_звук_своей_записи_в_правиле(self) -> None:
        spec = _spec(POD)
        self.assertIn("loudness_measure_after_mix", dict(cl.fire(spec, ["генерация_изображения", "расшифровка"])))
        # An audio item with no video deliverable: nothing to mix into a picture.
        spec = _spec(w(POD, outputs=["text"], task="transcribe"))
        self.assertNotIn("loudness_measure_after_mix", dict(cl.fire(spec, ["расшифровка"])))


# --- e. vertical reframe + RTL / CJK typography ---------------------------------------------------------------

TALK = {"task": "video-edit", "inputs": [{"kind": "video", "owned": True, "duration_s": 60, "resolution": "1920x1080"}],
        "outputs": ["video"], "duration_s": 60, "aspect": "9:16", "languages": ["ar", "ja"], "people": [],
        "delivery": {"platform": ["tiktok"]}}


class ВертикальRTLCJK(unittest.TestCase):
    def test_рефрейм_и_типографика(self) -> None:
        for brief in ("Vertical version of our talk show for TikTok", "Вертикальная версия ток-шоу для TikTok",
                      "縦型にしてください"):
            d = plan(brief, TALK)
            self.assertEqual(["расшифровка"], steps_of(d), brief)
            self.assertIn("tracking", assembly(d), brief)
            for rid in ("vertical_safe_zone", "rtl_graphics_fonts", "cjk_locale_glyphs", "cjk_vertical_text"):
                self.assertIn(rid, notes(d), (brief, rid))
            self.assertIn("(ar)", says(d, "rtl_graphics_fonts"))

    def test_латиница_без_типографики(self) -> None:
        d = plan("Vertical version of our talk show for TikTok", w(TALK, languages=["en"]))
        for rid in ("rtl_graphics_fonts", "cjk_locale_glyphs", "cjk_vertical_text"):
            self.assertNotIn(rid, notes(d), rid)
        self.assertIn("vertical_safe_zone", notes(d))


# --- f. motion comic + textless master for 2+ markets -----------------------------------------------------------

COMIC = {"task": "animate", "inputs": [P(count=12, source=["comic"]), {"kind": "text", "owned": True}],
         "outputs": ["video"], "duration_s": 90, "languages": ["en"], "people": [], "jurisdiction": "US",
         "delivery": {"markets": ["DE", "JP"]}}


class КомиксБезТитров(unittest.TestCase):
    def test_рынки_дают_мастер_и_леттеринг(self) -> None:
        for brief in ("Motion comic of our 12 panels for the German and Japanese releases",
                      "Моушн-комикс из 12 панелей для немецкого и японского релиза",
                      "Cómic animado de nuestras 12 viñetas"):
            d = plan(brief, COMIC)
            self.assertEqual(["озвучка", "оживление", "звук_фон"], steps_of(d), brief)
            self.assertIn("textless_master", notes(d), brief)
            self.assertTrue(any(п in assembly(d) for п in r18.ASSEMBLY_COMIC_LETTERING), brief)

    def test_языки_тоже(self) -> None:
        raw = w(COMIC, languages=["en", "de"], delivery={})
        self.assertIn(r18.ASSEMBLY_COMIC_LETTERING, applied("Motion comic", raw).assembly)

    def test_один_рынок_без_леттеринга(self) -> None:
        raw = w(COMIC, delivery={"markets": ["US"]})
        а = applied("Motion comic of our panels", raw)
        self.assertNotIn(r18.ASSEMBLY_COMIC_LETTERING, а.assembly)
        self.assertIn(r18.ASSEMBLY_COMIC_SPLIT, а.assembly)
        d = plan("Motion comic of our panels", raw)
        self.assertNotIn("textless_master", notes(d))
        self.assertNotIn(r18.ASSEMBLY_COMIC_LETTERING[1], assembly(d))

    def test_строка_переведена(self) -> None:
        self.assertEqual(r18.ASSEMBLY_COMIC_LETTERING[1], l10n.localise(r18.ASSEMBLY_COMIC_LETTERING[0], "en"))


# --- g. sign language + podcast / explainer ----------------------------------------------------------------------

SIGN_POD = {"task": "generate", "inputs": [{"kind": "audio", "owned": True, "duration_s": 1800}],
            "outputs": ["video"], "duration_s": 1800, "languages": ["en", "bfi"], "people": [],
            "audio_content": ["speech"], "delivery": {"platform": ["youtube"]}, "accessibility": ["sign-language"]}
SIGN_EXPL = {"task": "generate", "inputs": [{"kind": "script", "owned": True}], "outputs": ["video", "speech"],
             "duration_s": 90, "languages": ["en", "ase"], "audio": "voiceover", "people": [],
             "accessibility": ["sign-language"]}


class ЯзыкЖестовМаршруты(unittest.TestCase):
    def test_подкаст_разрыв_с_заметкой(self) -> None:
        for brief in ("Turn our episode into a YouTube video with a signer", "Видео из выпуска с переводчиком жестового",
                      "Notre épisode en vidéo avec interprète"):
            d = plan(brief, SIGN_POD)
            self.assertEqual("работа_не_поддерживается", d.get("reason"), brief)
            self.assertEqual("sign-language", (d.get("gap") or {}).get("job"), brief)
            self.assertIn("BSL (bfi)", says(d, "sign_language_access"), brief)

    def test_ролик_разрыв_с_заметкой(self) -> None:
        d = plan("A 90-second explainer with a narrator", SIGN_EXPL)
        self.assertEqual("работа_не_поддерживается", d.get("reason"))
        self.assertIn("ASL (ase)", says(d, "sign_language_access"))

    def test_без_жестов_маршрут_цел(self) -> None:
        d = plan("Turn our episode into a YouTube video", w(SIGN_POD, accessibility=["captions"], languages=["en"]))
        self.assertEqual(["генерация_изображения", "расшифровка"], steps_of(d))
        self.assertNotIn("sign_language_access", notes(d))


# --- j. residuals of the routes on older sets -------------------------------------------------------------------


class ОстаткиМаршрутов(unittest.TestCase):
    def test_интерполяция_без_кадров_исходника(self) -> None:
        clip = {"task": "upscale", "inputs": [{"kind": "video", "owned": True, "duration_s": 600, "resolution": "1920x1080"}],
                "outputs": ["video"], "duration_s": 600, "resolution": "4k", "fps": 60, "people": []}
        # The delivery rate named, the source rate unknown: "60 fps" in the words is not a request.
        for brief in ("Upscale our 60 fps gameplay to 4K", "Апскейл нашего геймплея 60 fps в 4K", "Gameplay 60fps en 4K"):
            self.assertNotIn("интерполяция_кадров", applied(brief, clip).route.шаги, brief)
        self.assertIn("интерполяция_кадров", applied("Upscale to 4K and interpolate to 60 fps", clip).route.шаги)
        self.assertIn("интерполяция_кадров", applied("Апскейл и плавное движение", clip).route.шаги)
        # The source rate known: the fields decide both ways.
        own = w(clip, inputs=[{**clip["inputs"][0], "fps": 30}])
        self.assertIn("интерполяция_кадров", applied("x", own).route.шаги)
        own = w(clip, inputs=[{**clip["inputs"][0], "fps": 60}])
        self.assertNotIn("интерполяция_кадров", applied("smooth motion", own).route.шаги)

    def test_комикс_без_звука_без_эффектов(self) -> None:
        raw = {"task": "animate", "inputs": [P(count=40, source=["comic"])], "outputs": ["video"], "shots": 40,
               "per_shot_s": 4, "aspect": "9:16", "people": []}
        for brief in ("Animate our 40 comic panels", "Оживить 40 панелей комикса", "Animar 40 viñetas"):
            self.assertEqual(("оживление",), applied(brief, raw).route.шаги, brief)
        self.assertIn("звук_фон", applied("Animate our panels with sound effects", raw).route.шаги)
        self.assertIn("звук_фон", applied("Оживить панели со звуком", raw).route.шаги)
        self.assertIn("звук_фон", applied("x", w(raw, audio="native")).route.шаги)
        self.assertIn("звук_фон", applied("x", w(raw, outputs=["video", "sfx"])).route.шаги)
        # A voice-over makes it a sound-designed piece.
        self.assertIn("звук_фон", applied("x", w(raw, voiceover=True)).route.шаги)


# --- i. a pass is shown inside its host step ---------------------------------------------------------------------


class ПроходВШаге(unittest.TestCase):
    def test_проход_внутрь(self) -> None:
        from studio import planner

        ответ = {"steps": [{"step": "реставрация_изображения"}, {"step": "восстановление_лиц", "chosen": {"model": "c"}},
                           {"step": "раскраска_изображения"}]}
        got = planner.проходы_в_шаг(ответ)
        self.assertEqual(["реставрация_изображения", "раскраска_изображения"], steps_of(got))
        self.assertEqual([{"step": "восстановление_лиц", "chosen": {"model": "c"}}], got["steps"][0]["passes"])
        # The original answer is not changed in place.
        self.assertEqual(3, len(ответ["steps"]))

    def test_без_хозяина_как_было(self) -> None:
        from studio import planner

        ответ = {"steps": [{"step": "восстановление_лиц"}, {"step": "апскейл_изображения"}]}
        self.assertEqual(ответ, planner.проходы_в_шаг(ответ))
        ответ = {"steps": [{"step": "апскейл_изображения"}, {"step": "восстановление_лиц"}]}
        self.assertEqual(["апскейл_изображения", "восстановление_лиц"], steps_of(planner.проходы_в_шаг(ответ)))

    def test_цена_ролика_считает_проход(self) -> None:
        d = plan("Restore the portrait of our founder", w(OLD, domain=["education"]))
        сметы = {с["step"]: float(с["usd"]) for с in d["pipeline_price"]["смета"]["steps"]}
        self.assertIn("восстановление_лиц", сметы)
        self.assertAlmostEqual(sum(сметы.values()), float(d["pipeline_price"]["смета"]["usd"]), places=2)


# --- h. figures from memory are marked ---------------------------------------------------------------------------

MARK_EN = "from memory — source not reachable; verify"
MARK_RU = "по памяти — источник недоступен; проверить"


class ЦифрыПоПамяти(unittest.TestCase):
    def _rule(self, rid: str) -> Any:
        return next(r for r in cl.RULES_R18 if r.id == rid)

    def test_scorm(self) -> None:
        r = self._rule("elearning_scorm_package")
        self.assertIn("64,000 characters (both limits " + MARK_EN + ")", r.en)
        self.assertIn("64 000 символов (оба предела " + MARK_RU + ")", r.ru)

    def test_ofcom(self) -> None:
        r = self._rule("sign_language_access")
        self.assertIn("a sixth of the picture; " + MARK_EN, r.en)
        self.assertIn("шестой части кадра; " + MARK_RU, r.ru)

    def test_aes_и_aswg(self) -> None:
        for платформа in ("web", "internal", "app-store", "marketplace", "game-engine"):
            en, ru = x18.LOUDNESS_TARGETS[платформа]
            self.assertIn(MARK_EN, en, платформа)
            self.assertIn(MARK_RU, ru, платформа)
        # Targets read from a reachable source carry no marker.
        for платформа in ("broadcast", "podcast", "music-distribution"):
            en, ru = x18.LOUDNESS_TARGETS[платформа]
            self.assertNotIn(MARK_EN, en, платформа)
            self.assertNotIn(MARK_RU, ru, платформа)

    def test_в_плане(self) -> None:
        d = plan("Combat barks for our game", BARKS)
        self.assertIn(MARK_EN, says(d, "loudness_measure_after_mix"))
        d = plan("Боевые реплики для нашей игры", w(BARKS, languages=["ru"]))
        self.assertIn(MARK_RU, says(d, "loudness_measure_after_mix"))


if __name__ == "__main__":
    unittest.main()
