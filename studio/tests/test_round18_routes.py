"""Round 18 (agent A, routes & decomposition): the decompositions a fresh hidden set found wrong.

Every route is decided by a spec field in any brief language (briefs here in EN, RU and at least one
other language per route), the EN/RU words are read only when the field is absent, and a named field
wins both ways. Literal step lists, counts, seconds and prices; negatives keep the old plan. Every case is
a paraphrase written for this file, never a dev or holdout brief. No network (T4).

1. virtual try-on batch (`inputs[].role`, `products`, `views`)
2. restoration chain (`task` chain, `colorize`, `resolution`, `inputs[].source / defects / fps`, faces)
3. speech batch (`lines`, `variations`, `characters`, `shots`)
4. podcast -> video (`audio_content`, `delivery.platform`, avatar only when asked)
5. vertical reframe (`aspect`, `edit`, `delivery.platform`)
6. motion comic (`inputs[].source: comic`, `inputs[].role: panel`)
7. dance performance (`dance`)
8. residuals: a 3D tour planned without a task, an explainer's voice-over, one presenter still
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Any

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import endpoints as ep  # noqa: E402
from studio import routes_r17 as r17  # noqa: E402
from studio import routes_r18 as r18  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import apply as ra  # noqa: E402
from studio.recipes import table as rt  # noqa: E402
from studio.selfrag.facts import load_facts  # noqa: E402

_PLANS: dict[str, dict] = {}


def plan(brief: str, spec: dict) -> dict:
    ключ = brief + json.dumps(spec, sort_keys=True, ensure_ascii=False)
    if ключ not in _PLANS:
        _PLANS[ключ] = json.loads(server.plan_pipeline(brief, spec=spec))
    return _PLANS[ключ]


def steps_of(d: dict) -> list[str]:
    return [str(ш.get("step")) for ш in d.get("steps") or []]


def step(d: dict, name: str) -> dict:
    for ш in d.get("steps") or []:
        if ш.get("step") == name:
            return ш
    raise AssertionError(f"no step {name}: {steps_of(d)}")


def model_of(d: dict, name: str) -> str:
    return str((step(d, name).get("chosen") or {}).get("model") or "")


def price_of(d: dict, name: str) -> str:
    return str((step(d, name).get("chosen") or {}).get("price") or "")


def assembly(d: dict) -> str:
    return " | ".join(str(с) for с in (d.get("assembly") or {}).get("why") or [])


def _spec(raw: dict) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def defaults(brief: str, raw: dict) -> bs.Spec:
    return bs.with_defaults(_spec(raw), ролик=True, текст=brief)


def applied(brief: str, raw: dict) -> ra.Applied:
    spec = defaults(brief, raw)
    return ra.rewrite(spec, bs.route(spec), brief)


def as_planner(brief: str, raw: dict) -> ra.Applied:
    """As `planner.plan` calls the recipes: the PARSED spec over the route of the defaulted one."""
    return ra.rewrite(_spec(raw), bs.route(defaults(brief, raw)), brief)


def w(base: dict, **more: Any) -> dict:
    return {**base, **more}


def P(**more: Any) -> dict:
    return {"kind": "image", "owned": True, **more}


# --- 1. virtual try-on batch ---------------------------------------------------------------------------

TRY = {"task": "generate", "inputs": [P(count=6, role="garment")], "outputs": ["image"], "shots": 18,
       "languages": [], "subject": ["garment"], "people": [], "views": 3}


class ПримеркаПартией(unittest.TestCase):
    def test_поле_на_трёх_языках(self) -> None:
        for brief in ("Fotos de nuestros 6 vestidos puestos, 3 vistas", "Наши 6 платьев на модели, 3 ракурса",
                      "Bilder unserer Kleider am Model"):
            а = applied(brief, TRY)
            self.assertEqual(("генерация_изображения", "примерка"), а.route.шаги, brief)
            self.assertEqual({"генерация_изображения": 3, "примерка": 18}, dict(а.route.штук))
            self.assertIn("try_on_shared_model", а.priors)
            self.assertIn("генерация_изображения", а.shared)

    def test_своё_фото_модели(self) -> None:
        raw = w(TRY, inputs=[P(count=6, role="garment"), P(role="model")])
        а = applied("Unsere Kleider auf unserem Model", raw)
        self.assertEqual(("примерка",), а.route.шаги)
        self.assertEqual(18, а.route.штук["примерка"])

    def test_поле_роли_сильнее_слов(self) -> None:
        # The words say "our model photo", the field says the only item is garments: the base is generated.
        а = applied("Put the dresses on our model photo", TRY)
        self.assertIn("генерация_изображения", а.route.шаги)
        # The field says a model is brought; the words "no model" do not override it.
        а = applied("We have no model", w(TRY, inputs=[P(count=6, role="garment"), P(role="model")]))
        self.assertNotIn("генерация_изображения", а.route.шаги)

    def test_слова_без_поля(self) -> None:
        raw = w(TRY, inputs=[P(count=4)], views=None, shots=None)
        raw = {k: v for k, v in raw.items() if v is not None}
        а = applied("Put our 4 jackets on our model photo, 2 angles each", w(raw, inputs=[P(count=4), P()]))
        self.assertEqual(("примерка",), а.route.шаги)
        self.assertEqual(8, а.route.штук["примерка"])
        а = applied("Наши 4 куртки на сгенерированной модели, 2 ракурса", raw)
        self.assertEqual({"генерация_изображения": 2, "примерка": 8}, dict(а.route.штук))

    def test_модель_без_роли(self) -> None:
        raw = {k: v for k, v in TRY.items() if k not in ("views", "shots")}
        # One item of 4 photos + the words of a model photo: the model is brought.
        а = applied("Put our 4 jackets on our model photo", w(raw, inputs=[P(count=4)]))
        self.assertEqual(("примерка",), а.route.шаги)
        self.assertEqual(4, а.route.штук["примерка"])
        # Two photo items, no role, no words: garment + model (the r10 reading).
        а = applied("x", w(raw, inputs=[P(count=4), P()]))
        self.assertEqual(("примерка",), а.route.шаги)
        # One item, no words: N garments, the base is generated.
        self.assertIn("генерация_изображения", applied("x", w(raw, inputs=[P(count=4)])).route.шаги)

    def test_ракурсы_из_шотов(self) -> None:
        raw = {k: v for k, v in TRY.items() if k != "views"}
        self.assertEqual(3, r18.try_on_views(_spec(raw)))
        self.assertEqual(1, r18.try_on_views(_spec(w(raw, shots=6))))

    def test_не_одежда(self) -> None:
        а = applied("Product shots", w(TRY, subject=["product"], inputs=[P(count=6)]))
        self.assertNotIn("примерка", а.route.шаги)

    def test_план_и_цена(self) -> None:
        d = plan("Fotos de nuestros 6 vestidos en modelo, 3 vistas cada uno", TRY)
        self.assertEqual(["генерация_изображения", "примерка"], steps_of(d))
        self.assertIn("3 image(s)", price_of(d, "генерация_изображения"))
        self.assertIn("18 image(s) × 0.04 usd = 0.72 usd", price_of(d, "примерка"))

    def test_ошибка_поля(self) -> None:
        _, errors = bs.parse_spec(w(TRY, inputs=[P(role="mannequin")]))
        self.assertTrue(any("role: mannequin not in" in e for e in errors), errors)
        _, errors = bs.parse_spec(w(TRY, views=0))
        self.assertTrue(any("spec.views" in e for e in errors), errors)


# --- 2. restoration chain ----------------------------------------------------------------------------

OLD = {"task": "restore", "inputs": [P(source=["archival"], defects=["scratches"], resolution="800x600")],
       "outputs": ["image"], "resolution": "4k", "languages": [], "people": [], "colorize": True, "subject": ["person"]}
FILM = {"task": "restore", "inputs": [{"kind": "video", "owned": True, "duration_s": 120, "resolution": "640x480",
                                         "source": ["cine-film"], "defects": ["flicker"], "fps": 18}],
        "outputs": ["video"], "duration_s": 120, "resolution": "1080p", "languages": [], "people": []}


class ЦепочкаРеставрации(unittest.TestCase):
    def test_поле_на_трёх_языках(self) -> None:
        for brief in ("Restaurar la foto del abuelo", "Отреставрировать фото дедушки", "Restaurer la photo"):
            а = applied(brief, OLD)
            self.assertEqual(
                ("реставрация_изображения", "восстановление_лиц", "раскраска_изображения", "апскейл_изображения"),
                а.route.шаги, brief,
            )
            self.assertIn("restore_faces_upscale_colour", а.priors)

    def test_без_раскраски(self) -> None:
        а = applied("Colourise it too", w(OLD, colorize=False))
        self.assertNotIn("раскраска_изображения", а.route.шаги)
        raw = {k: v for k, v in OLD.items() if k != "colorize"}
        self.assertIn("раскраска_изображения", applied("Restore and colourise", raw).route.шаги)
        self.assertNotIn("раскраска_изображения", applied("Restore it, no colourising: keep it black and white", raw).route.шаги)
        self.assertNotIn("раскраска_изображения", applied("Restaurar y colorear", raw).route.шаги)

    def test_апскейл_по_кадру(self) -> None:
        self.assertNotIn("апскейл_изображения", applied("x", w(OLD, resolution="800x600")).route.шаги)
        raw = {k: v for k, v in OLD.items() if k != "resolution"}
        self.assertNotIn("апскейл_изображения", applied("x", raw).route.шаги)
        self.assertIn("апскейл_изображения", applied("restore and upscale it", raw).route.шаги)
        # The archive's own frame unknown: a named delivery frame >= 720 is an upscale.
        а = applied("x", w(OLD, inputs=[P(source=["archival"], defects=["scratches"])]))
        self.assertIn("апскейл_изображения", а.route.шаги)

    def test_лица(self) -> None:
        self.assertNotIn("восстановление_лиц", applied("x", w(OLD, subject=["interior"])).route.шаги)
        raw = {k: v for k, v in OLD.items() if k != "subject"}
        self.assertNotIn("восстановление_лиц", applied("an old street", raw).route.шаги)
        self.assertIn("восстановление_лиц", applied("our family portrait", raw).route.шаги)
        self.assertIn("восстановление_лиц", applied("семейный портрет", raw).route.шаги)
        self.assertNotIn("восстановление_лиц", applied("retrato familiar", raw).route.шаги)
        persons = [{"name": "grandma", "real": True, "public_figure": False, "consent": "stated", "deceased": True}]
        self.assertIn("восстановление_лиц", applied("x", w(raw, people=persons)).route.шаги)

    def test_названная_цепочка_не_трогается(self) -> None:
        а = applied("restore, upscale, colourise", w(OLD, task=["restore", "colorize"]))
        self.assertNotIn("апскейл_изображения", а.route.шаги)

    def test_плёнка(self) -> None:
        for brief in ("Restaurar película de 8 mm", "Восстановить плёнку 8 мм", "8mm-Film restaurieren"):
            а = applied(brief, FILM)
            self.assertEqual(("реставрация", "апскейл"), а.route.шаги, brief)
            self.assertIn(r18.ASSEMBLY_FILM_DEFLICKER, а.assembly)
        а = applied("x", w(FILM, colorize=True, fps=24))
        self.assertEqual(("реставрация", "раскраска", "апскейл", "интерполяция_кадров"), а.route.шаги)
        self.assertNotIn("интерполяция_кадров", applied("x", w(FILM, fps=18)).route.шаги)

    def test_реестр_лиц(self) -> None:
        self.assertIn(ep.FACE_RESTORE, ep.build(load_facts()).get("codeformer").functions)

    def test_план_и_цена(self) -> None:
        d = plan("Restaurar, colorear y ampliar a 4K la foto de mi abuela", OLD)
        self.assertEqual(
            ["реставрация_изображения", "восстановление_лиц", "раскраска_изображения", "апскейл_изображения"],
            steps_of(d),
        )
        self.assertEqual("codeformer", model_of(d, "восстановление_лиц"))
        self.assertIn("0.0021 usd", price_of(d, "восстановление_лиц"))
        for s in ("раскраска_изображения", "апскейл_изображения"):
            self.assertIn("usd", price_of(d, s))


# --- 3. speech batch ----------------------------------------------------------------------------------

BARKS = {"task": "generate", "inputs": [{"kind": "text", "owned": True}], "outputs": ["speech"], "languages": ["en"],
         "people": [], "lines": 40, "variations": 2, "characters": 3, "delivery": {"platform": ["game-engine"]}}


class ПартияРеплик(unittest.TestCase):
    def test_поле_на_трёх_языках(self) -> None:
        for brief in ("Frases de combate para nuestro juego", "Реплики персонажей для игры", "ゲームのボイス"):
            а = applied(brief, BARKS)
            self.assertEqual(("озвучка",), а.route.шаги, brief)
            self.assertEqual(240, а.route.штук["озвучка"])
            self.assertEqual((480.0, 2.0), а.step_seconds["озвучка"])
            self.assertIn(r18.ASSEMBLY_SPEECH_FILES, а.assembly)

    def test_цена_по_репликам(self) -> None:
        а = applied("x", BARKS)
        текст = " ".join(en for _, en in а.assembly)
        self.assertIn("240 × ~30 characters = 7200 characters", текст)
        self.assertIn("12000 billable characters there", текст)

    def test_ivr_по_шотам(self) -> None:
        raw = {"inputs": [{"kind": "text", "owned": True}], "outputs": ["speech"], "languages": ["de"], "people": [],
               "shots": 25, "delivery": {"platform": ["telephony"]}}
        а = applied("Telefonansagen für unsere Hotline", raw)
        self.assertEqual("generate", defaults("x", raw).task)
        self.assertEqual(25, а.route.штук["озвучка"])
        self.assertEqual((150.0, 6.0), а.step_seconds["озвучка"])

    def test_слова_без_поля(self) -> None:
        raw = {k: v for k, v in BARKS.items() if k not in ("lines", "variations", "characters")}
        а = applied("40 voice lines, 3 variations each", raw)
        self.assertEqual(120, а.route.штук["озвучка"])
        а = applied("120 строк для курса", w(raw, delivery={"platform": ["web"]}))
        self.assertEqual((960.0, 8.0), а.step_seconds["озвучка"])

    def test_озвучка_к_видео_не_партия(self) -> None:
        raw = w(BARKS, task=None, inputs=[{"kind": "video", "owned": True, "duration_s": 60}, {"kind": "text", "owned": True}])
        raw = {k: v for k, v in raw.items() if v is not None}
        self.assertFalse(r18.speech_batch(_spec(raw)))
        self.assertFalse(r18.speech_batch(_spec(w(BARKS, inputs=[P()]))))

    def test_не_партия(self) -> None:
        raw = {"task": "generate", "inputs": [{"kind": "text", "owned": True}], "outputs": ["speech"],
               "duration_s": 10800, "languages": ["en"], "people": []}
        а = applied("Audiobook narration from our manuscript", raw)
        self.assertNotIn("speech_batch", а.recipes)
        self.assertNotIn("озвучка", а.step_seconds)

    def test_план_и_цена(self) -> None:
        d = plan("Frases de combate: 40 líneas, 3 personajes, 2 variantes", BARKS)
        self.assertEqual(["озвучка"], steps_of(d))
        self.assertIn("≈7200 chars", price_of(d, "озвучка"))


# --- 4. podcast -> video ----------------------------------------------------------------------------------

POD = {"task": "music-visualiser", "inputs": [{"kind": "audio", "owned": True, "duration_s": 2700}],
       "outputs": ["video"], "duration_s": 2700, "languages": ["en"], "people": [], "audio_content": ["speech"],
       "delivery": {"platform": ["youtube"]}}


class ПодкастВВидео(unittest.TestCase):
    def test_поле_на_трёх_языках(self) -> None:
        for brief in ("Convertir nuestro episodio en video para YouTube", "Сделать видео из выпуска", "Notre épisode en vidéo"):
            а = applied(brief, POD)
            self.assertEqual(("генерация_изображения", "расшифровка"), а.route.шаги, brief)
            self.assertEqual(1, а.route.штук["генерация_изображения"])
            self.assertEqual((2700.0, 2700.0), а.step_seconds["расшифровка"])
            self.assertIn(r18.ASSEMBLY_AUDIOGRAM, а.assembly)
            self.assertIn(r18.ASSEMBLY_CAPTIONS_SOFT, а.assembly)

    def test_своя_обложка_и_тикток(self) -> None:
        а = applied("x", w(POD, inputs=[*POD["inputs"], P(role="cover")], delivery={"platform": ["tiktok"]}))
        self.assertEqual(("расшифровка",), а.route.шаги)
        self.assertIn(r18.ASSEMBLY_CAPTIONS_BURN, а.assembly)

    def test_песня_не_подкаст(self) -> None:
        а = applied("Visualiser for our podcast", w(POD, audio_content=["song"]))
        self.assertNotIn("podcast_audiogram", а.priors)

    def test_аватар_только_по_просьбе(self) -> None:
        self.assertNotIn("podcast_audiogram", applied("x", w(POD, lipsync=True)).priors)
        self.assertNotIn("podcast_audiogram", applied("Our podcast with a talking avatar of the host", w(POD, audio_content=[])).priors)

    def test_слова_без_поля(self) -> None:
        raw = {k: v for k, v in POD.items() if k != "audio_content"}
        self.assertIn("podcast_audiogram", applied("Turn our podcast into a video", w(raw, task="generate")).priors)
        self.assertNotIn("podcast_audiogram", applied("Video for our new single", w(raw, task="generate", delivery={})).priors)

    def test_строки_визуализатора_сняты(self) -> None:
        а = as_planner("x", POD)
        self.assertNotIn(bs.NOTE_VISUALISER, а.route.сборка)
        self.assertNotIn(bs.NOTE_VISUALISER_SYNC, а.route.сборка)

    def test_без_задачи(self) -> None:
        raw = {k: v for k, v in POD.items() if k != "task"}
        self.assertEqual("generate", defaults("x", raw).task)

    def test_план_и_цена(self) -> None:
        d = plan("Convertir nuestro episodio de 45 minutos en video para YouTube", w(POD, task="generate"))
        self.assertEqual(["генерация_изображения", "расшифровка"], steps_of(d))
        self.assertIn("2700 s × 0.008 usd/min", price_of(d, "расшифровка"))
        self.assertIn("1 image(s)", price_of(d, "генерация_изображения"))
        self.assertNotIn("NO CLIP PRICE", json.dumps(d.get("pipeline_price"), ensure_ascii=False))
        self.assertIn("showwaves", assembly(d))


# --- 5. vertical reframe -------------------------------------------------------------------------------------

TALK = {"task": "video-edit", "inputs": [{"kind": "video", "owned": True, "duration_s": 60, "resolution": "1920x1080"}],
        "outputs": ["video"], "duration_s": 60, "aspect": "9:16", "languages": ["en"], "people": [],
        "delivery": {"platform": ["tiktok"]}}


class ВертикальныйРефрейм(unittest.TestCase):
    def test_поле_на_трёх_языках(self) -> None:
        for brief in ("Versión vertical de nuestro programa", "Вертикальная версия ток-шоу", "縦型にしてください"):
            а = applied(brief, TALK)
            self.assertEqual(("расшифровка",), а.route.шаги, brief)
            self.assertIn(r18.ASSEMBLY_CAPTIONS_BURN, а.assembly)
            self.assertIn("reframe_tracked_crop", а.priors)
            self.assertNotIn("правка_видео", а.route.шаги)

    def test_альтернатива_эндпоинта(self) -> None:
        текст = " ".join(en for _, en in applied("x", TALK).assembly)
        self.assertIn("ltx-2.3-reframe", текст)
        self.assertIn("1080p 0.2 usd/s → 12.00 usd", текст)

    def test_ютуб_без_вшивки(self) -> None:
        а = applied("x", w(TALK, delivery={"platform": ["youtube"]}))
        self.assertEqual((), а.route.шаги)

    def test_названная_правка_сильнее(self) -> None:
        а = applied("make it vertical", w(TALK, edit=["replace-sky"]))
        self.assertIn("правка_видео", а.route.шаги)

    def test_горизонталь_не_рефрейм(self) -> None:
        self.assertEqual((), defaults("x", w(TALK, aspect="16:9")).edit)
        self.assertEqual((), defaults("x", w(TALK, aspect="1:1")).edit)

    def test_исходник_уже_вертикальный(self) -> None:
        raw = w(TALK, inputs=[{"kind": "video", "owned": True, "duration_s": 60, "resolution": "1080x1920"}])
        self.assertEqual((), defaults("x", raw).edit)

    def test_план(self) -> None:
        d = plan("Versión vertical de nuestro talk show para TikTok", TALK)
        self.assertEqual(["расшифровка"], steps_of(d))
        self.assertIn("60 s × 0.008 usd/min", price_of(d, "расшифровка"))
        self.assertIn("tracker", assembly(d))


# --- 6. motion comic ---------------------------------------------------------------------------------------

COMIC = {"task": "animate", "inputs": [P(count=12, source=["comic"]), {"kind": "text", "owned": True}],
         "outputs": ["video"], "duration_s": 90, "languages": ["en"], "people": [], "jurisdiction": "US"}


class МоушнКомикс(unittest.TestCase):
    def test_поле_на_трёх_языках(self) -> None:
        for brief in ("Cómic animado de nuestras viñetas", "Оживить наш комикс", "マンガをモーションコミックに"):
            а = applied(brief, COMIC)
            self.assertEqual(("оживление", "озвучка", "звук_фон"), а.route.шаги, brief)
            self.assertEqual(12, а.route.штук["оживление"])
            self.assertEqual((90.0, 7.5), а.step_seconds["оживление"])
            self.assertIn(r18.ASSEMBLY_COMIC_SPLIT, а.assembly)
            self.assertIn(r18.ASSEMBLY_COMIC_PARALLAX, а.assembly)

    def test_без_аватара(self) -> None:
        raw = w(COMIC, people=[{"name": "hero", "real": False, "on_screen": True, "speaks": True}])
        а = applied("The hero speaks", raw)
        self.assertNotIn("говорящий_аватар", а.route.шаги)
        self.assertNotIn("липсинк", а.route.шаги)

    def test_задача_аватар(self) -> None:
        а = applied("x", w(COMIC, task="avatar"))
        self.assertNotIn("говорящий_аватар", а.route.шаги)
        self.assertIn("оживление", а.route.шаги)

    def test_без_голоса_со_сценарием(self) -> None:
        а = applied("Motion comic with narration", w(COMIC, voiceover=False))
        self.assertNotIn("озвучка", а.route.шаги)

    def test_без_голоса(self) -> None:
        а = applied("x", w(COMIC, voiceover=False, inputs=[P(count=12, source=["comic"])]))
        self.assertNotIn("озвучка", а.route.шаги)
        а = applied("x", w(COMIC, audio="none", voiceover=False, inputs=[P(count=12, source=["comic"])]))
        self.assertEqual(("оживление",), а.route.шаги)

    def test_слова_без_поля(self) -> None:
        raw = w(COMIC, inputs=[P(count=12), {"kind": "text", "owned": True}])
        self.assertIn("comic_panel_motion", applied("Motion comic from our panels", raw).priors)
        self.assertNotIn("comic_panel_motion", applied("Animate our holiday photos", raw).priors)
        self.assertNotIn("comic_panel_motion", applied("Motion comic", w(raw, inputs=[P(count=12, source=["own"])])).priors)

    def test_план(self) -> None:
        d = plan("Cómic animado de nuestras 12 viñetas con narración y efectos", COMIC)
        self.assertEqual(["озвучка", "оживление", "звук_фон"], steps_of(d))
        self.assertIn("90 s", price_of(d, "оживление"))
        self.assertNotIn("говорящий_аватар", steps_of(d))


# --- 7. dance performance -------------------------------------------------------------------------------------

IDOL = {"task": "r2v", "inputs": [P(count=2), {"kind": "audio", "owned": True, "duration_s": 30}],
        "outputs": ["video"], "duration_s": 30, "languages": [], "people": [], "characters": 2, "dance": True,
        "jurisdiction": "KR"}


class ТанцевальныйНомер(unittest.TestCase):
    def test_поле_на_трёх_языках(self) -> None:
        for brief in ("우리 아이돌 두 명의 퍼포먼스 영상", "Выступление двух участниц группы", "Video de nuestras dos idols"):
            а = applied(brief, IDOL)
            self.assertEqual(("перенос_движения",), а.route.шаги, brief)
            self.assertEqual((60.0, 30.0), а.step_seconds["перенос_движения"])
            self.assertEqual(r18.DANCE_AVOID, а.avoid["перенос_движения"])
            self.assertIn(r18.ASSEMBLY_DANCE_DRIVER, а.assembly)

    def test_без_фото_по_референсу_на_исполнителя(self) -> None:
        а = applied("x", w(IDOL, inputs=[{"kind": "audio", "owned": True, "duration_s": 30}], shots=6))
        self.assertEqual(("генерация_изображения", "перенос_движения"), а.route.шаги)
        self.assertEqual(2, а.route.штук["генерация_изображения"])

    def test_своё_видео_танца(self) -> None:
        raw = w(IDOL, inputs=[*IDOL["inputs"], {"kind": "video", "owned": True, "duration_s": 30, "role": "motion"}])
        self.assertIn(r18.ASSEMBLY_DANCE_OWN_DRIVER, applied("x", raw).assembly)

    def test_поле_нет_против_слов(self) -> None:
        self.assertNotIn("dance_motion_transfer", applied("A dance video", w(IDOL, dance=False)).priors)
        raw = {k: v for k, v in IDOL.items() if k != "dance"}
        self.assertIn("dance_motion_transfer", applied("A dance performance of our idols", raw).priors)
        self.assertNotIn("dance_motion_transfer", applied("Ein Musikvideo", raw).priors)

    def test_план_и_цена(self) -> None:
        d = plan("우리 아이돌 두 명의 댄스 영상", IDOL)
        self.assertEqual(["перенос_движения"], steps_of(d))
        self.assertEqual("kling-3.0-pro-motion-control", model_of(d, "перенос_движения"))
        self.assertIn("60 s × 0.168 usd/s = 10.08 usd", price_of(d, "перенос_движения"))

    def test_факты(self) -> None:
        строки = {(f.model, f.attribute): f.value for f in load_facts()}
        self.assertIn("dance", строки[("kling-2.6-motion-control", "best_for")])
        self.assertIn("portraits and simple animations", строки[("kling-video-v3-standard-motion-control", "best_for")])
        self.assertIn("NON-COMMERCIAL", строки[("codeformer-upstream", "licence")])
        self.assertIn("Apache-2.0", строки[("gfpgan", "licence")])


# --- 8. residuals ---------------------------------------------------------------------------------------------

FLAT = {"inputs": [P(count=60)], "outputs": ["video"], "duration_s": 60, "languages": [], "people": [],
        "domain": ["real-estate"]}
EXPLAINER = {"task": "generate", "inputs": [{"kind": "text", "owned": True}], "outputs": ["video"], "duration_s": 60,
             "languages": ["en"], "people": []}
UGC = {"task": "avatar", "inputs": [{"kind": "text", "owned": True}], "outputs": ["video", "speech"], "shots": 5,
       "duration_s": 75, "languages": ["en"], "people": []}


class Остатки(unittest.TestCase):
    def test_тур_без_задачи(self) -> None:
        for brief in ("A virtual tour of our apartment", "Виртуальный тур по квартире", "Visite virtuelle 3D"):
            spec = defaults(brief, FLAT)
            self.assertEqual(("generate", True), (spec.task, spec.reconstruct_3d), brief)
            self.assertEqual(("реконструкция_3d",), applied(brief, FLAT).route.шаги)
            self.assertTrue(any("3D reconstruction" in а for а in spec.assumptions))
        self.assertEqual([], bs.gaps(FLAT, "A virtual tour of our apartment")[2])

    def test_тур_как_у_плановщика(self) -> None:
        а = as_planner("A virtual tour of our apartment", w(FLAT, task="generate"))
        self.assertEqual(("реконструкция_3d",), а.route.шаги)

    def test_тур_поле_нет(self) -> None:
        а = applied("A virtual tour", w(FLAT, task="generate", reconstruct_3d=False))
        self.assertNotIn("реконструкция_3d", а.route.шаги)

    def test_мало_снимков_облёт(self) -> None:
        а = applied("A virtual tour", w(FLAT, task="generate", inputs=[P(count=8)]))
        self.assertNotIn("реконструкция_3d", а.route.шаги)

    def test_озвучка_по_сценарию(self) -> None:
        for brief in ("Video explicativo con nuestro guion", "Объясняющий ролик по сценарию", "Erklärvideo"):
            spec = defaults(brief, EXPLAINER)
            self.assertIn("speech", spec.outputs, brief)
            self.assertIn("озвучка", bs.route(spec).шаги)
        self.assertNotIn("speech", defaults("x", w(EXPLAINER, voiceover=False)).outputs)
        self.assertNotIn("speech", defaults("x", w(EXPLAINER, inputs=[])).outputs)

    def test_один_ведущий(self) -> None:
        for brief in ("5 anuncios UGC con una presentadora", "5 UGC-роликов с одной ведущей", "5 UGC Clips"):
            а = applied(brief, UGC)
            self.assertEqual(1, а.route.штук["генерация_изображения"], brief)
        а = applied("x", w(UGC, characters=2))
        self.assertNotEqual(1, а.route.штук.get("генерация_изображения"))

    def test_план_ugc(self) -> None:
        d = plan("5 anuncios UGC con una presentadora para nuestro sérum", UGC)
        self.assertIn("1 image(s)", price_of(d, "генерация_изображения"))


# --- contract: fields, priors, notes --------------------------------------------------------------------------


class Контракт(unittest.TestCase):
    def test_поля_в_контракте(self) -> None:
        for поле in r18.SPEC_FIELDS_R18:
            self.assertIn(поле, bs.SPEC_FIELDS)
            self.assertIn(поле, bs.OPTIONAL_HELP)
        for поле in bs.DECISION_FIELDS_R18:
            self.assertIn(поле, bs.DECISION_FIELDS)
        self.assertIn("comic", bs.INPUT_SOURCES)
        self.assertEqual(r18.INPUT_ROLES, bs.INPUT_ROLES)

    def test_приоры_и_рецепты(self) -> None:
        for п in ("try_on_shared_model", "restore_faces_upscale_colour", "speech_lines_per_file", "podcast_audiogram",
                  "reframe_tracked_crop", "comic_panel_motion", "dance_motion_transfer"):
            self.assertIn(п, rt.PRIORS)
        for р in ("virtual_try_on_batch", "restoration_chain", "speech_batch", "podcast_video", "vertical_reframe",
                  "motion_comic", "dance_performance"):
            self.assertIn(р, rt.RECIPES)

    def test_выключатель_приора(self) -> None:
        а = applied("x", w(POD, priors={"podcast_audiogram": False}))
        self.assertIn("podcast_audiogram", а.overridden)
        self.assertNotEqual(("генерация_изображения", "расшифровка"), а.route.шаги)

    def test_перевод_нот(self) -> None:
        from studio import l10n

        for ru, en in r18.NOTE_PAIRS:
            self.assertEqual(en, l10n.localise(ru, "en"))
        ru, en = r18.NOTE_TRY_ON_SKU
        self.assertEqual(en.format(skus=6, views=3, n=18), l10n.localise(ru.format(skus=6, views=3, n=18), "en"))

    def test_r17_не_тронут(self) -> None:
        self.assertEqual(20, r17.SPLAT_PHOTOS_MIN)
        self.assertEqual(r17.SPLAT_PHOTOS_MIN, r18.TOUR_PHOTOS_MIN)


if __name__ == "__main__":
    unittest.main()
