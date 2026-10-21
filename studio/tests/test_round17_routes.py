"""Round 17 (agent A, missing routes): the routes a fresh hidden set found missing.

Every route is decided by a spec field in any brief language (briefs here in EN, RU and at least one
other language per route), the EN/RU words are read only when the field is absent, and a named field
wins both ways. Literal step lists, notes and prices; negatives keep the old plan. Every case is a
paraphrase written for this file, never a dev or holdout brief. No network (T4).

1. burned-in subtitles to translate (`inputs[].subtitles`)
2. a singer's music video from a performer reference (`performer_shots`, `people[].on_screen/speaks`)
3. a 3D walkthrough / tour (`reconstruct_3d`, `delivery.format` ply / splat / spz)
4. a consented internal deepfake drill (`studio/consented_simulation.py`): planned with safeguards;
   every refusal it does not name still holds
5. a whole-person replacement (`edit: ["replace-person"]`) vs a face swap
6. a UGC product batch: stills <= products + one shared presenter (`products`)
7. narration named with no audio brought: a TTS step (`voiceover`, `audio`, `audio_content`)
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Any

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import consented_simulation as cs  # noqa: E402
from studio import routes_r17 as r17  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import apply as ra  # noqa: E402
from studio.recipes import checklist as cl  # noqa: E402
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


def notes(d: dict) -> list[str]:
    return [str(н.get("id")) for н in d.get("production_notes") or []]


def assembly(d: dict) -> str:
    return " | ".join(str(с) for с in (d.get("assembly") or {}).get("why") or [])


def _spec(raw: dict) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def applied(brief: str, raw: dict) -> ra.Applied:
    spec = bs.with_defaults(_spec(raw), ролик=True, текст=brief)
    return ra.rewrite(spec, bs.route(spec), brief)


def fired(raw: dict, steps: list[str], brief: str = "") -> list[str]:
    return [i for i, _ in cl.fire(bs.with_defaults(_spec(raw), ролик=True, текст=brief), steps, text=brief)]


def w(base: dict, **more: Any) -> dict:
    return {**base, **more}


def V(**more: Any) -> dict:
    return {"kind": "video", "owned": True, "duration_s": 60, **more}


# --- 1. burned-in subtitles ------------------------------------------------------------------------

SUBS = {"task": "video-edit", "inputs": [V(subtitles="burned")], "outputs": ["video"], "duration_s": 60,
        "languages": ["en"], "people": []}


class ВшитыеСубтитры(unittest.TestCase):
    def test_поле_на_трёх_языках(self) -> None:
        for brief in ("Traduce nuestro anuncio al inglés", "Переведите наш ролик на английский",
                      "把我们的宣传片翻译成英文"):
            а = applied(brief, SUBS)
            self.assertEqual(("расшифровка", "правка_видео"), а.route.шаги, brief)
            self.assertIn("burned_subtitles_replace", а.priors)
            self.assertIn(r17.ASSEMBLY_SUBS_BURN, а.assembly)

    def test_правка_снимает_текст(self) -> None:
        spec = bs.with_defaults(_spec(w(SUBS, task="captions", outputs=["video", "text"])), ролик=True, текст="x")
        self.assertEqual(("video-edit", ("remove-object",), "text"), (spec.task, spec.edit, spec.edit_target))

    def test_поле_нет_против_слов(self) -> None:
        а = applied("Translate our promo, the subtitles are burned in", w(SUBS, inputs=[V(subtitles="none")]))
        self.assertNotIn("burned_subtitles_replace", а.priors)
        self.assertNotIn("расшифровка", а.route.шаги)

    def test_слова_без_поля(self) -> None:
        for brief in ("Translate our promo; it has hardcoded Spanish subtitles",
                      "Переведите ролик, субтитры вшиты в кадр"):
            а = applied(brief, w(SUBS, inputs=[V()]))
            self.assertIn("burned_subtitles_replace", а.priors, brief)
        а = applied("Traduce el anuncio, los subtítulos están quemados", w(SUBS, inputs=[V()]))
        self.assertNotIn("burned_subtitles_replace", а.priors)

    def test_мягкая_дорожка(self) -> None:
        а = applied("x", w(SUBS, delivery={"platform": ["youtube"]}))
        self.assertIn(r17.ASSEMBLY_SUBS_SOFT, а.assembly)
        self.assertNotIn(r17.ASSEMBLY_SUBS_BURN, а.assembly)
        а = applied("x", w(SUBS, delivery={"platform": ["tiktok"]}))
        self.assertIn(r17.ASSEMBLY_SUBS_BURN, а.assembly)
        а = applied("x", w(SUBS, delivery={"format": ["srt"]}))
        self.assertIn(r17.ASSEMBLY_SUBS_SOFT, а.assembly)

    def test_без_речи_нет_расшифровки(self) -> None:
        а = applied("x", w(SUBS, audio_content=["music"]))
        self.assertEqual(("правка_видео",), а.route.шаги)

    def test_дубляж_снимает_старые(self) -> None:
        а = applied("x", w(SUBS, task="dub-translate", outputs=["video", "speech"]))
        self.assertEqual(("дубляж", "липсинк", "правка_видео"), а.route.шаги)

    def test_цены_строк(self) -> None:
        а = applied("x", SUBS)
        текст = " ".join(en for _, en in а.assembly)
        self.assertIn("≈900 chars × 20 usd per 1M = 0.02 usd", текст)
        self.assertIn("1 min × 0.15 usd = 0.15 usd", текст)
        а = applied("x", w(SUBS, languages=["en", "de"], duration_s=600, inputs=[V(subtitles="burned", duration_s=600)]))
        текст = " ".join(en for _, en in а.assembly)
        self.assertIn("≈18000 chars × 20 usd per 1M = 0.36 usd", текст)
        self.assertIn("10 min × 0.15 usd = 1.50 usd", текст)

    def test_факты_цен_записаны(self) -> None:
        строки = {(f.model, f.attribute): f.value for f in load_facts()}
        self.assertIn("$20.00 per million", строки[("google-cloud-translation", "price_per_million_chars_usd")])
        self.assertIn("$0.15 per minute", строки[("google-cloud-video-intelligence", "price_text_detection_per_minute_usd")])

    def test_план(self) -> None:
        d = plan("Traduisez notre vidéo promo en anglais", SUBS)
        self.assertEqual(["правка_видео", "расшифровка"], sorted(steps_of(d)))
        self.assertIn("usd", price_of(d, "правка_видео"))
        self.assertIn("usd", price_of(d, "расшифровка"))
        self.assertIn("burned_subtitles_translation", notes(d))
        self.assertIn("Google Cloud Translation", assembly(d))
        self.assertNotIn("no transcription needed", assembly(d))

    def test_оговорка_молчит_без_субтитров(self) -> None:
        self.assertNotIn("burned_subtitles_translation", fired(w(SUBS, inputs=[V()]), ["правка_видео"], "Übersetzen"))
        self.assertIn("burned_subtitles_translation", fired(SUBS, ["правка_видео"], "Übersetzen"))

    def test_ошибка_поля(self) -> None:
        _, errors = bs.parse_spec(w(SUBS, inputs=[V(subtitles="painted")]))
        self.assertTrue(any("subtitles: painted not in burned, soft, none" in e for e in errors), errors)


# --- 2. singer music video --------------------------------------------------------------------------

SINGER = {"name": "Mara", "real": True, "public_figure": False, "consent": "stated", "role": "talent",
          "on_screen": True, "speaks": True}
MV = {"task": "r2v", "inputs": [{"kind": "image", "owned": True, "count": 3}, {"kind": "audio", "owned": True, "duration_s": 180}],
      "outputs": ["video"], "duration_s": 180, "shots": 12, "languages": ["en"], "audio_content": ["song"],
      "performer_shots": 6, "people": [SINGER]}


class КлипИсполнителя(unittest.TestCase):
    def test_поле_на_трёх_языках(self) -> None:
        for brief in ("Videoclip para nuestra cantante", "Клип для нашей певицы", "歌手のミュージックビデオ"):
            а = applied(brief, MV)
            self.assertEqual(("генерация_изображения", "видео_по_референсу", "липсинк", "оживление"), а.route.шаги, brief)
            self.assertEqual({"генерация_изображения": 6, "липсинк": 6, "видео_по_референсу": 6, "оживление": 6}, dict(а.route.штук))
            self.assertEqual((90.0, 15.0), а.step_seconds["липсинк"])
            self.assertEqual((90.0, 15.0), а.step_seconds["оживление"])

    def test_все_шоты_поёт(self) -> None:
        raw = {k: v for k, v in MV.items() if k != "performer_shots"}
        а = applied("x", raw)
        self.assertEqual(("видео_по_референсу", "липсинк"), а.route.шаги)
        self.assertEqual((180.0, 15.0), а.step_seconds["липсинк"])

    def test_без_фото_один_референс(self) -> None:
        а = applied("x", w(MV, inputs=[{"kind": "audio", "owned": True, "duration_s": 180}]))
        self.assertEqual(7, а.route.штук["генерация_изображения"])

    def test_никто_не_поёт(self) -> None:
        for raw in (w(MV, people=[{**SINGER, "speaks": False}]), w(MV, lipsync=False), w(MV, performer_shots=0)):
            а = applied("She sings on camera", raw)
            self.assertNotIn("липсинк", а.route.шаги)
            self.assertNotIn("performer_music_video", а.recipes)

    def test_слова_без_полей(self) -> None:
        raw = w(MV, people=[{"name": "Mara", "real": True, "public_figure": False, "consent": "stated"}])
        self.assertIn("performer_music_video", applied("Music video, she sings on camera in every scene", raw).recipes)
        self.assertNotIn("performer_music_video", applied("Musikvideo mit unserer Sängerin", raw).recipes)

    def test_ошибка_поля(self) -> None:
        _, errors = bs.parse_spec(w(MV, performer_shots=-1))
        self.assertTrue(any("performer_shots" in e for e in errors), errors)

    def test_план(self) -> None:
        d = plan("Videoclip para nuestra cantante Mara", MV)
        self.assertEqual(["генерация_изображения", "оживление", "видео_по_референсу", "липсинк"], steps_of(d))
        self.assertIn("90 s", price_of(d, "липсинк"))
        self.assertIn("90 s", price_of(d, "оживление"))
        self.assertIn("6 image(s)", price_of(d, "генерация_изображения"))
        self.assertNotIn("говорящий_аватар", steps_of(d))


# --- 3. 3D walkthrough ---------------------------------------------------------------------------------

TOUR = {"task": "generate", "inputs": [{"kind": "image", "owned": True, "count": 150}], "outputs": ["video"],
        "duration_s": 60, "languages": [], "people": [], "reconstruct_3d": True}


class ТрёхмерныйТур(unittest.TestCase):
    def test_поле_на_трёх_языках(self) -> None:
        for brief in ("Recorrido 3D de nuestro piso", "3D-тур по квартире", "아파트 3D 투어"):
            а = applied(brief, TOUR)
            self.assertEqual(("реконструкция_3d",), а.route.шаги, brief)
            self.assertIn(r17.GAP_SPLAT_COMPUTE, а.assembly)
            self.assertIn(r17.ASSEMBLY_SPLAT_RENDER, а.assembly)

    def test_видео_как_съёмка(self) -> None:
        а = applied("x", w(TOUR, inputs=[{"kind": "video", "owned": True, "duration_s": 120}]))
        self.assertEqual(("реконструкция_3d",), а.route.шаги)

    def test_формат_сплата(self) -> None:
        raw = {k: v for k, v in TOUR.items() if k != "reconstruct_3d"}
        а = applied("x", w(raw, outputs=["video"], delivery={"format": ["spz"]}))
        self.assertEqual(("реконструкция_3d",), а.route.шаги)
        self.assertIn(r17.ASSEMBLY_SPLAT_VIEWER, а.assembly)

    def test_поле_нет_против_слов(self) -> None:
        а = applied("A 3D walkthrough of our flat", w(TOUR, reconstruct_3d=False, subject=["interior"]))
        self.assertNotIn("реконструкция_3d", а.route.шаги)
        self.assertIn("оживление", а.route.шаги)
        self.assertIn(ra.ASSEMBLY_WALKTHROUGH, а.assembly)

    def test_слова_без_поля(self) -> None:
        raw = {k: v for k, v in TOUR.items() if k != "reconstruct_3d"}
        self.assertIn("scene_3d", applied("Gaussian splat tour of our flat", raw).recipes)
        self.assertIn("scene_3d", applied("3D-тур по квартире", raw).recipes)
        self.assertNotIn("scene_3d", applied("Visite de notre appartement", raw).recipes)

    def test_план_пробел_цены(self) -> None:
        d = plan("Visite 3D de notre appartement", TOUR)
        self.assertEqual(["реконструкция_3d"], steps_of(d))
        for видео in ("оживление", "генерация_видео", "оборот_360"):
            self.assertNotIn(видео, steps_of(d))
        self.assertIn("splat_scene_capture", notes(d))
        self.assertIn("GPU minutes per scene are not recorded", assembly(d))
        self.assertIn("ns-render", assembly(d))

    def test_факты_и_пробелы_записаны(self) -> None:
        строки = {(f.model, f.attribute): f.value for f in load_facts()}
        self.assertEqual("Apache-2.0", строки[("gsplat", "licence")])
        self.assertIn("~6 GB", строки[("nerfstudio-splatfacto", "vram_gb")])
        self.assertIn("non-commercial", строки[("gaussian-splatting-inria", "licence")])
        for gap in (("postshot", "price_gap"), ("polycam", "price_gap"), ("luma-3d-capture", "price_gap"),
                    ("gaussian-splat-training", "gpu_seconds_gap")):
            self.assertTrue(строки[gap].startswith("not recorded"), gap)


# --- 4. consented internal deepfake drill ------------------------------------------------------------------

CEO = {"name": "Anna Berg", "real": True, "public_figure": True, "role": "employee", "consent": "stated",
       "claim": "news", "on_screen": True, "speaks": True}
DRILL = {"task": "avatar", "inputs": [{"kind": "video", "owned": True, "duration_s": 120}, {"kind": "text", "owned": True}],
         "outputs": ["video", "speech"], "duration_s": 60, "languages": ["en"], "people": [CEO],
         "domain": ["security-awareness"], "delivery": {"platform": ["internal"]}, "live": False}


def refused(d: dict) -> bool:
    return d.get("outcome") == "fail" and not d.get("steps")


class СогласованныеУчения(unittest.TestCase):
    def test_план_на_трёх_языках(self) -> None:
        for brief in (
            "Security awareness drill: a deepfake of our CEO Anna Berg announcing an urgent acquisition, internal only",
            "Учения по безопасности: дипфейк гендиректора Анны Берг, только внутри компании",
            "Sicherheitsschulung: Deepfake unserer CEO Anna Berg, nur intern",
        ):
            d = plan(brief, DRILL)
            self.assertFalse(refused(d), brief)
            self.assertEqual(["клонирование_голоса", "озвучка", "липсинк"], steps_of(d), brief)
            self.assertEqual("consented_simulation", d["consented_simulation"]["rule"])
            self.assertIn("consented_simulation_safeguards", notes(d))
            self.assertRegex(assembly(d), "SIMULATION|СИМУЛЯЦИЯ")
            self.assertIn("1.50 usd", price_of(d, "клонирование_голоса"))

    def test_отказы_остаются(self) -> None:
        brief = "Security awareness drill: a deepfake of our CEO Anna Berg, internal only"
        for raw in (
            w(DRILL, delivery={"platform": ["youtube"]}),
            w(DRILL, delivery={"platform": ["internal", "web"]}),
            w(DRILL, domain=["corporate"]),
            w(DRILL, people=[{**CEO, "consent": "none"}]),
            w(DRILL, people=[{**CEO, "consent": "unknown"}]),
            w(DRILL, people=[{**CEO, "claim": "endorsement"}]),
            w(DRILL, people=[{**CEO, "claim": "political"}]),
            w(DRILL, people=[{**CEO, "role": "talent"}]),
            w(DRILL, claims=[{"type": "political"}]),
        ):
            d = plan(brief, raw)
            self.assertTrue(refused(d), raw)
            self.assertNotIn("consented_simulation", d)

    def test_политика_словами_закрывает(self) -> None:
        d = plan("Deepfake of our CEO endorsing a candidate in the election, internal security training", DRILL)
        self.assertTrue(refused(d))

    def test_без_отказа_дверь_не_нужна(self) -> None:
        d = plan("Phishing simulation with our CFO", w(DRILL, people=[{**CEO, "public_figure": False, "claim": "other"}]))
        self.assertFalse(refused(d))
        self.assertNotIn("consented_simulation", d)
        self.assertIn("consented_simulation_safeguards", notes(d))

    def test_поля_двери(self) -> None:
        self.assertTrue(cs.internal_training(DRILL))
        self.assertFalse(cs.internal_training(w(DRILL, delivery={"platform": ["internal", "youtube"]})))
        self.assertTrue(cs.in_house(CEO))
        self.assertFalse(cs.in_house({**CEO, "role": "other"}))

    def test_слова_оговорки_без_поля(self) -> None:
        raw = {k: v for k, v in DRILL.items() if k != "domain"}
        self.assertIn("consented_simulation_safeguards", fired(raw, ["липсинк"], "phishing simulation for staff"))
        self.assertNotIn("consented_simulation_safeguards", fired(raw, ["липсинк"], "Schulung"))
        self.assertNotIn("consented_simulation_safeguards", fired(w(DRILL, domain=["corporate"]), ["липсинк"], "phishing drill"))


# --- 5. whole person vs face ------------------------------------------------------------------------------

SWAP = {"task": "video-edit", "inputs": [V(duration_s=20), {"kind": "image", "owned": True}], "outputs": ["video"],
        "duration_s": 20, "edit": ["replace-person"], "edit_target": "person", "languages": [], "people": []}


class ЗаменаЧеловекаЦеликом(unittest.TestCase):
    def test_поле_на_трёх_языках(self) -> None:
        for brief in ("Sustituye al actor por otro personaje", "Замените актёра другим персонажем", "替换视频中的演员"):
            а = applied(brief, SWAP)
            self.assertEqual(("замена_фигуры",), а.route.шаги, brief)
            self.assertIn("whole_person_replace", а.priors)

    def test_без_референса_генерируется(self) -> None:
        а = applied("x", w(SWAP, inputs=[V(duration_s=20)]))
        self.assertEqual(("генерация_изображения", "замена_фигуры"), а.route.шаги)
        self.assertEqual(1, а.route.штук["генерация_изображения"])

    def test_лицо_остаётся_заменой_лица(self) -> None:
        raw = {"task": "face-replace", "inputs": [V(duration_s=20), {"kind": "image", "owned": True}], "outputs": ["video"],
               "duration_s": 20, "languages": [], "people": []}
        self.assertEqual(("замена_персонажа",), applied("Swap the actor's face for mine", raw).route.шаги)
        self.assertEqual(("замена_фигуры",), applied("Replace the actor head to toe, whole body and costume", raw).route.шаги)
        self.assertEqual(("замена_персонажа",), applied("Ersetze den Schauspieler komplett", raw).route.шаги)

    def test_названная_правка_старше_слов(self) -> None:
        raw = w(SWAP, edit=["relight"], edit_target="person")
        self.assertNotIn("замена_фигуры", applied("Replace the whole body of the actor", raw).route.шаги)

    def test_план(self) -> None:
        d = plan("Remplacez l'acteur entier par notre personnage", SWAP)
        self.assertEqual(["замена_фигуры"], steps_of(d))
        self.assertIn("animate-replace", model_of(d, "замена_фигуры"))
        self.assertIn("20 s × 0.08 usd/s = 1.60 usd", price_of(d, "замена_фигуры"))


# --- 6. UGC product batch ----------------------------------------------------------------------------------

UGC = {"task": "generate", "inputs": [], "outputs": ["video", "speech"], "shots": 12, "per_shot_s": 15, "products": 4,
       "languages": ["en"], "aspect": "9:16", "delivery": {"platform": ["tiktok"]}, "subject": ["product"],
       "consistency": ["style"], "people": [{"name": "creator", "real": False, "on_screen": True, "speaks": True}]}


class ПачкаUGC(unittest.TestCase):
    def test_поле_на_трёх_языках(self) -> None:
        for brief in ("12 vídeos UGC para TikTok Shop", "12 UGC-роликов для тикток-шопа", "TikTok Shop用のUGC動画12本"):
            а = applied(brief, UGC)
            self.assertEqual(5, а.route.штук["генерация_изображения"], brief)
            self.assertIn("ugc_shared_references", а.priors)
            self.assertIn("генерация_изображения", а.shared)

    def test_принесённые_кадры_товара(self) -> None:
        а = applied("x", w(UGC, inputs=[{"kind": "image", "owned": True, "count": 4}]))
        self.assertEqual(1, а.route.штук.get("генерация_изображения"))

    def test_аватар_без_фото(self) -> None:
        а = applied("x", w(UGC, task="avatar", inputs=[{"kind": "text", "owned": True, "count": 12}], consistency=[]))
        self.assertEqual(5, а.route.штук["генерация_изображения"])

    def test_слова_без_поля(self) -> None:
        raw = {k: v for k, v in UGC.items() if k != "products"}
        self.assertEqual(4, applied("12 UGC clips for 4 products", raw).route.штук["генерация_изображения"] - 1)
        self.assertNotIn("ugc_shared_references", applied("12 Clips für vier Produkte", w(raw, subject=[])).priors)

    def test_не_пачка(self) -> None:
        self.assertNotIn("ugc_shared_references", applied("x", w(UGC, shots=2, per_shot_s=15)).priors)

    def test_план(self) -> None:
        d = plan("12 vídeos UGC para TikTok Shop, 4 productos", UGC)
        self.assertIn("5 image(s)", price_of(d, "генерация_изображения"))
        self.assertNotIn("12 image(s)", price_of(d, "генерация_изображения"))


# --- 7. narration without audio ----------------------------------------------------------------------------

EXPL = {"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 60, "languages": ["en"], "people": []}


class ОзвучкаБезЗвука(unittest.TestCase):
    def test_поля(self) -> None:
        for raw in (w(EXPL, voiceover=True), w(EXPL, audio="voiceover"), w(EXPL, audio_content=["speech"])):
            а = applied("Erklärvideo über unsere App", raw)
            self.assertIn("озвучка", а.route.шаги, raw)

    def test_нет_речи(self) -> None:
        for raw in (EXPL, w(EXPL, voiceover=False), w(EXPL, voiceover=False, audio_content=["speech"]),
                    w(EXPL, inputs=[{"kind": "audio", "owned": True, "duration_s": 60}], voiceover=True)):
            self.assertNotIn("озвучка", applied("x", raw).route.шаги, raw)

    def test_своё_видео(self) -> None:
        raw = {"task": "video-edit", "inputs": [V()], "outputs": ["video"], "duration_s": 60, "languages": ["en"],
               "people": [], "edit": ["trim"]}
        self.assertIn("озвучка", applied("x", w(raw, voiceover=True)).route.шаги)
        self.assertNotIn("озвучка", applied("x", w(raw, audio_content=["speech"])).route.шаги)

    def test_план_на_трёх_языках(self) -> None:
        for brief in ("Explainer about our app with a voiceover", "Объясняющий ролик с закадровым голосом",
                      "Vídeo explicativo con locución"):
            d = plan(brief, w(EXPL, voiceover=True))
            self.assertEqual(["озвучка", "генерация_видео"], steps_of(d), brief)
            self.assertIn("≈900 ", price_of(d, "озвучка"))


# --- the contract: fields offered, priors and recipes registered ----------------------------------------------


class Контракт(unittest.TestCase):
    def test_поля_в_вопросе(self) -> None:
        for поле in ("inputs[].subtitles", "performer_shots", "products", "reconstruct_3d"):
            self.assertIn(поле, bs.DECISION_FIELDS)
            self.assertIn(поле, bs.OPTIONAL_HELP)
        for поле in ("performer_shots", "products", "reconstruct_3d"):
            self.assertIn(поле, bs.SPEC_FIELDS)
        self.assertIn("replace-person", bs.EDIT_VALUES)
        self.assertIn("internal", bs.DELIVERY_PLATFORMS)
        self.assertIn("security-awareness", bs.DOMAINS)
        self.assertIn("spz", bs.DELIVERY_FORMATS)

    def test_описание_инструмента(self) -> None:
        описание = server.plan_pipeline.__doc__ or ""
        for слово in ("inputs[].subtitles", "performer_shots", "products", "reconstruct_3d", "replace-person",
                      "security-awareness"):
            self.assertIn(слово, описание)

    def test_прочитано_словами(self) -> None:
        поля = {п["field"]: п["read_from_text"] for п in bs.decision_fields("3D tour of 12 products, hardcoded subtitles")}
        self.assertEqual(("burned", True, 12), (поля["inputs[].subtitles"], поля["reconstruct_3d"], поля["products"]))
        поля = {п["field"]: п["read_from_text"] for п in bs.decision_fields("全景导览")}
        self.assertIsNone(поля["reconstruct_3d"])

    def test_допущения_зарегистрированы(self) -> None:
        for п in ("burned_subtitles_replace", "performer_reference_lips", "gaussian_splat_scene", "whole_person_replace",
                  "ugc_shared_references"):
            self.assertIn(п, rt.PRIORS)
        for р in ("burned_subtitles", "performer_music_video", "scene_3d", "whole_person_replacement", "ugc_product_batch"):
            self.assertIn(р, rt.RECIPES)

    def test_перевод_пометок(self) -> None:
        from studio import l10n

        for ru, en in r17.NOTE_PAIRS:
            self.assertEqual(en, l10n.localise(ru, "en"))
            self.assertEqual(en, bs.note_en(ru) or en)


if __name__ == "__main__":
    unittest.main()
