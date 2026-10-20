"""Round 15 (expert knowledge & pricing): caveats, long ambient loops, batch and transcription prices, cartoon
dubs, product insertion, anonymising bystanders.

Every case is a paraphrase written for this file (EN and RU), never a dev or holdout brief.
Decision constants are tested at their edges so that `scripts/mutate_round15_knowledge.py`
turns each mutant red. No network (T4).

1. CAVEATS — `checklist.RULES_R15`, structured fields first (`outputs[].loop|tileable`,
   `consistency`, `people[].speaks`, `edit_target`), the words second; both ways.
2. PRICING — hours of ambience are one loopable segment (`expert_r15.ambient_segment_s`);
   a lip-sync batch pays its per-clip fees and blocks in every clip; transcription is priced
   over all the material and states what diarisation costs on the chosen ASR.
3. STEPS / MODELS — a 2D cartoon dub keeps lip sync on a model recorded for drawn faces;
   a product put into existing footage is an object edit (no character replacement) with a
   price; anonymising passers-by picks a video face swap (or assembly blur) with the GDPR note.
"""

from __future__ import annotations

import json
import os
import unittest

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import expert_r15 as x15  # noqa: E402
from studio import l10n  # noqa: E402
from studio import planner  # noqa: E402
from studio import pricing  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import apply as ra  # noqa: E402
from studio.recipes import checklist as cl  # noqa: E402
from studio.selfrag.facts import Fact  # noqa: E402
from studio.selfrag.modelnames import fold  # noqa: E402

_PLANS: dict[str, dict] = {}


def plan(brief: str, spec: dict) -> dict:
    ключ = brief + json.dumps(spec, sort_keys=True, ensure_ascii=False)
    if ключ not in _PLANS:
        _PLANS[ключ] = json.loads(server.plan_pipeline(brief, spec=spec))
    return _PLANS[ключ]


def steps_of(d: dict) -> list[str]:
    return [ш.get("step") for ш in d.get("steps") or []]


def step(d: dict, name: str) -> dict:
    for ш in d.get("steps") or []:
        if ш.get("step") == name:
            return ш
    raise AssertionError(f"no step {name}: {steps_of(d)}")


def model_of(d: dict, name: str) -> str:
    return str((step(d, name).get("chosen") or {}).get("model") or "")


def clip_usd(d: dict) -> float | None:
    цена = d.get("pipeline_price") or {}
    return (цена.get("за_ролик") or {}).get("usd") or (цена.get("смета") or {}).get("usd")


def _spec(raw: dict) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def fired(raw: dict, steps: list[str], brief: str = "") -> list[str]:
    return [i for i, _ in cl.fire(_spec(raw), steps, text=brief)]


def F(model: str, attribute: str, value: str, url: str = "https://example.org/x", tier: str = "portal") -> Fact:
    return Fact(model, attribute, value, url, tier)


def w(base: dict, **more: object) -> dict:
    return {**base, **more}


GEN = {"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 20, "people": []}
MUS = {"task": "generate", "inputs": [], "outputs": ["music"], "duration_s": 10800, "people": []}
IMG = {"task": "generate", "inputs": [], "outputs": ["image"], "shots": 1, "people": []}
SET = {"task": "generate", "inputs": [], "outputs": ["image"], "shots": 12, "people": []}
SING = {"task": "sing-photo", "inputs": [{"kind": "image", "owned": True}, {"kind": "audio", "owned": False, "duration_s": 30}],
        "outputs": ["video"], "duration_s": 30, "people": []}
REST = {"task": "restore", "inputs": [{"kind": "image", "owned": True}], "outputs": ["image"], "people": []}
INTERP = {"task": "interpolate", "inputs": [{"kind": "video", "owned": True, "duration_s": 30}], "outputs": ["video"], "fps": 60,
          "people": []}
EDV = {"task": "video-edit", "inputs": [{"kind": "video", "owned": True, "duration_s": 120}], "outputs": ["video"], "duration_s": 120,
       "people": []}

# --- 1. caveats -------------------------------------------------------------------------------

#: rule -> (firing cases [(spec, steps, brief)], silent cases).
CAVEATS: dict[str, tuple[list[tuple[dict, list[str], str]], list[tuple[dict, list[str], str]]]] = {
    "cover_song_rights": (
        [(SING, ["говорящий_аватар"], "my dog sings 'Bohemian Rhapsody', 30 seconds"),
         (GEN, ["генерация_видео"], "our band's acoustic cover of a famous song, 20 s"),
         (w(GEN, outputs=["video"]), ["генерация_видео"], "кавер на известную песню для нашего канала"),
         (SING, ["говорящий_аватар"], "кот поёт «Подмосковные вечера»")],
        [(GEN, ["генерация_видео"], "a cover image for our new song"),
         (w(SING, inputs=[{"kind": "image", "owned": True}, {"kind": "audio", "owned": True, "duration_s": 30}]),
          ["говорящий_аватар"], "my cat sings our own jingle"),
         (MUS, ["музыка"], "write an original pop song about coffee"),
         (SING, ["говорящий_аватар"], "my cat sings our own jingle that our agency wrote"),
         (GEN, ["генерация_видео"], "обложка для трека, 20 секунд анимации")],
    ),
    "long_ambient_loop": (
        [(MUS, ["музыка"], "3 hours of rain ambience for sleep"),
         (w(GEN, duration_s=28800), ["генерация_видео"], "8 hours of a crackling fireplace"),
         (w(GEN, duration_s=36000), ["генерация_видео"], "10 часов камина для ютуба"),
         (w(GEN, duration_s=3600, outputs=[{"kind": "video", "loop": True}]), ["генерация_видео"], "")],
        [(w(MUS, duration_s=600), ["музыка"], "rain ambience for sleep"),
         (w(GEN, duration_s=2700), ["генерация_видео"], "a 45-minute documentary about whales"),
         (w(GEN, duration_s=7200, outputs=[{"kind": "video", "loop": False}]), ["генерация_видео"], "2 hours of fireplace"),
         (w(GEN, duration_s=3600), ["генерация_видео"], "часовой фильм о путешествии")],
    ),
    "tileable_texture": (
        [(IMG, ["генерация_изображения"], "a seamless tileable stone texture for our game"),
         (IMG, ["генерация_изображения"], "бесшовная текстура дерева для 3D"),
         (w(IMG, outputs=[{"kind": "image", "tileable": True}]), ["генерация_изображения"], "")],
        [(IMG, ["генерация_изображения"], "a stone wall photo for a poster"),
         (w(IMG, outputs=[{"kind": "image", "tileable": False}]), ["генерация_изображения"], "seamless pattern"),
         (IMG, ["генерация_изображения"], "плитка в ванной, рекламный кадр")],
    ),
    "descreen_halftone": (
        [(REST, ["реставрация"], "restore grandpa's photo cut from an old newspaper"),
         (w(REST, task="upscale"), ["апскейл_изображения"], "upscale a magazine scan of our 1985 ad, there is moire"),
         (REST, ["реставрация"], "восстановить фото из газеты 1960 года")],
        [(REST, ["реставрация"], "restore a scratched family photo from the album"),
         (IMG, ["генерация_изображения"], "a newspaper-style illustration of a cat"),
         (REST, ["реставрация"], "восстановить старое семейное фото")],
    ),
    "timelapse_interpolation": (
        [(INTERP, ["интерполяция_кадров"], "smooth my sunset timelapse to 60 fps"),
         (INTERP, ["интерполяция_кадров"], "сгладить таймлапс города до 60 кадров")],
        [(INTERP, ["интерполяция_кадров"], "slow motion of my skateboard trick"),
         (GEN, ["генерация_видео"], "a timelapse of clouds over mountains"),
         (INTERP, ["интерполяция_кадров"], "плавное слоумо прыжка")],
    ),
    "style_consistency_set": (
        [(SET, ["генерация_изображения"], "12 illustrations for a children's book in a consistent style"),
         (SET, ["генерация_изображения"], "12 иллюстраций в едином стиле для сайта"),
         (w(SET, consistency=["style"]), ["генерация_изображения"], "")],
        [(w(SET, shots=1), ["генерация_изображения"], "one poster in the same style as our logo"),
         (SET, ["генерация_изображения"], "12 product shots on white"),
         (w(SET, consistency=["light"]), ["генерация_изображения"], "в одном стиле")],
    ),
    "no_speech_short": (
        [(w(GEN, duration_s=15), ["генерация_видео"], "a 15 s TikTok for our sneakers, no voiceover, just music and text"),
         (w(GEN, duration_s=20), ["генерация_видео"], "ролик для рилс без слов, только музыка и титры"),
         (w(GEN, duration_s=30, people=[{"name": "barista", "real": False, "speaks": False}]), ["генерация_видео"], "")],
        [(w(GEN, duration_s=30), ["генерация_видео"], "a 30 s ad with a warm voiceover"),
         (w(GEN, duration_s=30, outputs=["video", "speech"]), ["генерация_видео", "озвучка"], "no music, a voiceover"),
         (w(GEN, duration_s=30, people=[{"name": "host", "real": False, "speaks": True}]), ["генерация_видео"], "без слов"),
         (w(GEN, duration_s=30, people=[{"name": "a", "real": False, "speaks": False},
                                        {"name": "b", "real": False, "speaks": True}]), ["генерация_видео"], ""),
         (w(GEN, duration_s=600), ["генерация_видео"], "a 10-minute film without dialogue")],
    ),
    "product_insertion": (
        [(EDV, ["правка_видео"], "put our soda can on the table in this clip"),
         (EDV, ["правка_видео"], "вставить нашу бутылку на стол в этом ролике"),
         (w(EDV, edit_target="object"), ["правка_видео"], "our perfume bottle")],
        [(EDV, ["правка_видео"], "add our logo into the video"),
         (EDV, ["правка_видео"], "replace the sky in this clip"),
         (w(EDV, edit_target="person"), ["правка_видео"], "put the presenter into the scene")],
    ),
    "anonymisation_gdpr": (
        [(EDV, ["правка_видео"], "blur the faces of passers-by in our street footage for GDPR"),
         (EDV, ["правка_видео"], "обезличить прохожих: размыть лица в ролике с улицы"),
         (EDV, ["замена_персонажа"], "anonymise bystanders by swapping their faces")],
        [(EDV, ["правка_видео"], "passers-by walk past our shop window"),
         (EDV, ["правка_видео"], "replace the sky over the street"),
         (EDV, ["правка_видео"], "прохожие идут мимо витрины")],
    ),
}


class Предостережения(unittest.TestCase):
    def test_каждое_правило_в_обе_стороны(self) -> None:
        self.assertEqual({р.id for р in cl.RULES_R15}, set(CAVEATS))
        for rid, (да, нет) in CAVEATS.items():
            for raw, steps, brief in да:
                with self.subTest(rule=rid, fires=brief or raw):
                    self.assertIn(rid, fired(raw, steps, brief))
            for raw, steps, brief in нет:
                with self.subTest(rule=rid, silent=brief or raw):
                    self.assertNotIn(rid, fired(raw, steps, brief))

    def test_длина_фонового_на_краю(self) -> None:
        # Pinned at half an hour: from there a generated full length pays for the same sound many times over.
        self.assertIn("long_ambient_loop", fired(w(MUS, duration_s=1800), ["музыка"], "rain ambience"))
        self.assertNotIn("long_ambient_loop", fired(w(MUS, duration_s=1799), ["музыка"], "rain ambience"))

    def test_серия_стиля_на_краю(self) -> None:
        self.assertIn("style_consistency_set", fired(w(SET, shots=3), ["генерация_изображения"], "same style"))
        self.assertNotIn("style_consistency_set", fired(w(SET, shots=2), ["генерация_изображения"], "same style"))

    def test_шортс_без_речи_на_краю(self) -> None:
        self.assertIn("no_speech_short", fired(w(GEN, duration_s=180), ["генерация_видео"], "no voiceover"))
        self.assertNotIn("no_speech_short", fired(w(GEN, duration_s=181), ["генерация_видео"], "no voiceover"))

    def test_ноты_на_двух_языках_без_утечек(self) -> None:
        поля = {"n": "12", "seconds": "10800"}
        for р in cl.RULES_R15:
            self.assertEqual([], l10n.leaks({"says": р.ru.format(**поля)}, "ru"), р.id)
            self.assertEqual([], l10n.leaks({"says": р.en.format(**поля)}, "en"), р.id)

    def test_правило_в_плане(self) -> None:
        d = plan("a 3-hour rain ambience track for sleep, seamless, for YouTube", MUS)
        self.assertIn("long_ambient_loop", [n.get("id") for n in d.get("production_notes") or []])


# --- 2. pricing --------------------------------------------------------------------------------


class ДлинныйФон(unittest.TestCase):
    """Hours of ambience: one loopable segment generated once, repeated at assembly at 0 usd."""

    def test_музыка_часами_en(self) -> None:
        d = plan("3 hours of rain ambience for sleep, seamless", MUS)
        self.assertEqual(["музыка"], steps_of(d))
        self.assertLess(clip_usd(d), 10.0)
        self.assertIn(str(x15.AMBIENT_AUDIO_SEGMENT_S), json.dumps(step(d, "музыка"), ensure_ascii=False))

    def test_видео_с_камином_ru(self) -> None:
        d = plan("10-часовое видео с камином для ютуба", w(GEN, duration_s=36000))
        self.assertIn("генерация_видео", steps_of(d))
        self.assertLess(clip_usd(d), 20.0)
        self.assertIn("стык", json.dumps(d.get("assembly"), ensure_ascii=False))

    def test_документалка_не_петля(self) -> None:
        d = plan("a 45-minute documentary about whales", w(GEN, duration_s=2700))
        self.assertGreater(clip_usd(d), 100.0)

    def test_поле_петли_ложно_побеждает_слова(self) -> None:
        a = ra.rewrite(_spec(w(MUS, outputs=[{"kind": "music", "loop": False}])),
                       bs.Маршрут(("музыка",), {}), "3 hours of rain ambience for sleep")
        self.assertNotIn("музыка", a.step_seconds)
        b = ra.rewrite(_spec(MUS), bs.Маршрут(("музыка",), {}), "3 hours of rain ambience for sleep")
        self.assertEqual((float(x15.AMBIENT_AUDIO_SEGMENT_S),) * 2, b.step_seconds["музыка"])

    def test_отрезок_видео_и_звука(self) -> None:
        s = _spec(w(GEN, duration_s=7200))
        # Pinned: three minutes of audio fit one music-model run (`checklist.MUSIC_RUN_MAX_S`) and hide the
        # repeat; ten seconds of video is one generator run.
        self.assertEqual(10.0, x15.ambient_segment_s(s, "2 hours of fireplace", audio=False))
        self.assertEqual(180.0, x15.ambient_segment_s(s, "2 hours of fireplace", audio=True))
        self.assertLessEqual(x15.AMBIENT_AUDIO_SEGMENT_S, cl.MUSIC_RUN_MAX_S)
        self.assertIsNone(x15.ambient_segment_s(s, "a 2-hour lecture", audio=False))
        self.assertIsNone(x15.ambient_segment_s(_spec(w(GEN, duration_s=cl.AMBIENT_LOOP_MIN_S - 1)), "fireplace", audio=False))


class ПачкаЛипсинка(unittest.TestCase):
    """UGC batches: per-clip fees and blocks apply in every clip; over budget names the cheapest route."""

    def test_блок_пять_секунд_в_каждом_ролике(self) -> None:
        r = pricing.rates("Your request will be priced $0.014 per input video seconds, rolling up to closest 5 second "
                          "increment.", "price_per_second_usd")
        self.assertEqual(5.0, r[0].block)
        варианты = pricing.estimate(r, pricing.Need(seconds=360, shots=30))
        self.assertAlmostEqual(6.30, варианты[0].usd, places=2)  # 30 x 15 s, not 360 s
        варианты = pricing.estimate(r, pricing.Need(seconds=360, shots=1))
        self.assertAlmostEqual(5.04, варианты[0].usd, places=2)

    def test_минута_в_каждом_ролике(self) -> None:
        r = pricing.rates("$0.6 per minute, rounded up to closest minute", "price")
        self.assertAlmostEqual(12.0, pricing.estimate(r, pricing.Need(seconds=600, shots=20))[0].usd)
        self.assertAlmostEqual(6.0, pricing.estimate(r, pricing.Need(seconds=600, shots=1))[0].usd)

    def test_липсинк_пачкой_по_роликам(self) -> None:
        self.assertIn("липсинк", x15.BATCH_PRICED_STEPS)
        op = next(о for о in planner.OPERATIONS if о.name == "липсинк")
        need = planner.нужда_шага(op, planner.dur.Запрос(360.0, "test"), None, 1, клипов=30)
        self.assertEqual(30, need.shots)

    def test_пачка_аватаров_дороже_потолка_ru(self) -> None:
        d = plan("50 UGC-роликов с одним ИИ-ведущим по 20 секунд, бюджет $10 на всё",
                 {"task": "avatar", "inputs": [{"kind": "text", "owned": True}], "outputs": ["video"], "shots": 50,
                  "per_shot_s": 20, "budget_usd": 10, "languages": ["ru"], "people": [{"name": "ведущий", "real": False}]})
        self.assertEqual("дороже_потолка", d.get("reason"))
        дешевле = (d.get("budget") or {}).get("cheaper_alternatives") or []
        self.assertTrue(any(a.get("kind") == "cheapest_models" and a.get("steps") for a in дешевле))
        self.assertEqual(1, step(d, "генерация_изображения").get("shots") or 1)

    def test_пачка_в_потолке_en(self) -> None:
        d = plan("50 UGC testimonials with the same AI presenter, 20 s each, total budget $100",
                 {"task": "avatar", "inputs": [{"kind": "text", "owned": True}], "outputs": ["video"], "shots": 50,
                  "per_shot_s": 20, "budget_usd": 100, "languages": ["en"], "people": [{"name": "host", "real": False}]})
        self.assertNotEqual("дороже_потолка", d.get("reason"))
        self.assertLessEqual(clip_usd(d), 100.0)


class Расшифровка(unittest.TestCase):
    """All the material is priced; the speaker-label cost is stated by record of the chosen ASR."""

    def test_все_интервью_en(self) -> None:
        d = plan("transcribe 20 interviews of 45 minutes each with speaker labels",
                 {"task": "transcribe", "inputs": [{"kind": "audio", "owned": True, "duration_s": 2700, "count": 20}],
                  "outputs": ["text"], "duration_s": 2700, "characters": 2, "languages": ["en"]})
        self.assertIn("54000", (step(d, "расшифровка").get("chosen") or {}).get("price", ""))
        self.assertIn("diarises by record", step(d, "расшифровка").get("speaker_labels", ""))

    def test_метки_говорящих_ru(self) -> None:
        d = plan("расшифровать часовое интервью двух человек, кто что сказал",
                 {"task": "transcribe", "inputs": [{"kind": "audio", "owned": True, "duration_s": 3600}],
                  "outputs": ["text"], "duration_s": 3600, "languages": ["ru"]})
        self.assertIn("метки говорящих", step(d, "расшифровка").get("speaker_labels", ""))

    def test_лекция_одного_без_меток(self) -> None:
        d = plan("transcribe this 30 minute lecture",
                 {"task": "transcribe", "inputs": [{"kind": "audio", "owned": True, "duration_s": 1800}],
                  "outputs": ["text"], "duration_s": 1800, "languages": ["en"]})
        self.assertNotIn("speaker_labels", step(d, "расшифровка"))

    def test_материал_по_счёту(self) -> None:
        s = _spec({"task": "transcribe", "inputs": [{"kind": "audio", "owned": True, "duration_s": 600, "count": 3},
                                                    {"kind": "video", "owned": True, "duration_s": 60}],
                   "outputs": ["text"], "languages": ["en"]})
        self.assertEqual(1860.0, x15.material_seconds(s))

    def test_разметка_по_записи(self) -> None:
        факты = [F("asr-a", "diarization", "speaker diarisation in the same call"),
                 F("asr-b", "price", "$0.15/hour; speaker diarization add-on $0.02/hour"),
                 F("asr-c", "languages", "99 languages")]
        self.assertIn("already covers", x15.diarisation_line("asr-a", факты, fold, True))
        self.assertIn("add-on", x15.diarisation_line("asr-b", факты, fold, True))
        self.assertIn("separate diarisation pass", x15.diarisation_line("asr-c", факты, fold, True))
        self.assertIn("НЕ записана", x15.diarisation_line("asr-c", факты, fold, False))


# --- 3. steps and models ----------------------------------------------------------------------

DUB = {"task": "dub-translate", "inputs": [{"kind": "video", "owned": True, "duration_s": 300}], "outputs": ["video"],
       "duration_s": 300}


class МультДубляж(unittest.TestCase):
    def test_мультфильм_en(self) -> None:
        d = plan("dub our 2D cartoon episode from English to Spanish", w(DUB, languages=["es"]))
        self.assertIn("липсинк", steps_of(d))
        self.assertIn(fold(model_of(d, "липсинк")), planner.стилизованные_лица(planner.FactIndex().facts))

    def test_мультфильм_ru(self) -> None:
        d = plan("переозвучить наш мультфильм на английский", w(DUB, languages=["en"]))
        self.assertIn("липсинк", steps_of(d))
        self.assertIn("рисованн", step(d, "липсинк").get("inferred", ""))

    def test_животные_записи_нет(self) -> None:
        а = ra.rewrite(_spec(w(DUB, languages=["en"])), bs.Маршрут(("дубляж", "липсинк"), {}),
                       "dub our cartoon about a fox and a bear")
        self.assertEqual(ra.NOTE_DRAWN_DUB_ANIMAL[0], а.route.пометки["липсинк"])

    def test_снятое_интервью_без_предпочтения(self) -> None:
        а = ra.rewrite(_spec(w(DUB, languages=["en"])), bs.Маршрут(("дубляж", "липсинк"), {}), "dub my interview")
        self.assertEqual((), а.prefer_stylised)

    def test_запись_о_рисованных_лицах(self) -> None:
        факты = [F("lip-a", "face_styles", "human characters (real/3D/2D)"), F("lip-b", "max_seconds", "60")]
        self.assertEqual(frozenset({fold("lip-a")}), planner.стилизованные_лица(факты))


class ВставкаТовара(unittest.TestCase):
    def test_банка_на_столе_en(self) -> None:
        d = plan("put our soda can on the table in this existing 10 s clip",
                 {"task": "video-edit", "inputs": [{"kind": "video", "owned": True, "duration_s": 10}, {"kind": "image", "owned": True}],
                  "outputs": ["video"], "duration_s": 10, "edit": ["replace-object"], "people": []})
        модель = model_of(d, "правка_видео")
        self.assertTrue(модель)
        self.assertFalse(planner.персонажная_замена(модель), модель)
        self.assertIsNotNone(clip_usd(d))

    def test_флакон_ru_по_полю(self) -> None:
        d = plan("поставить наш флакон на полку в готовом ролике",
                 {"task": "video-edit", "inputs": [{"kind": "video", "owned": True, "duration_s": 8}], "outputs": ["video"],
                  "duration_s": 8, "edit_target": "object", "people": []})
        self.assertFalse(planner.персонажная_замена(model_of(d, "правка_видео")))
        self.assertIsNotNone(clip_usd(d))

    def test_цель_человек(self) -> None:
        self.assertTrue(x15.person_edit(_spec(w(EDV, edit_target="person")), ""))
        self.assertFalse(x15.person_edit(_spec(w(EDV, edit_target="object")), "replace the actor"))
        self.assertTrue(x15.person_edit(_spec(EDV), "replace the actor with a robot"))
        self.assertFalse(x15.person_edit(_spec(EDV), "put our can on the table"))
        self.assertTrue(x15.person_edit(_spec(w(EDV, task="face-replace")), ""))
        self.assertTrue(planner.персонажная_замена("wan-animate-replace"))
        self.assertFalse(planner.персонажная_замена("wan-2.7-edit-video"))


class Анонимизация(unittest.TestCase):
    def test_замена_лиц_en(self) -> None:
        d = plan("anonymise the faces of passers-by in our street footage for GDPR by swapping them with synthetic faces",
                 w(EDV, task="face-replace"))
        self.assertEqual(["генерация_изображения", "замена_персонажа"], steps_of(d))
        self.assertIn("face-swap", model_of(d, "замена_персонажа"))
        self.assertIsNotNone(clip_usd(d))
        self.assertIn("anonymisation_gdpr", [n.get("id") for n in d.get("production_notes") or []])

    def test_замена_лиц_ru(self) -> None:
        d = plan("обезличить прохожих в нашем ролике с улицы, заменить их лица на сгенерированные", w(EDV, duration_s=180))
        self.assertIn("face-swap", model_of(d, "замена_персонажа"))

    def test_размытие_монтажом(self) -> None:
        d = plan("blur the faces of passers-by in our 2-minute street footage for GDPR", EDV)
        self.assertEqual("только_монтаж", d.get("reason"))
        self.assertIn("deface", json.dumps(d.get("assembly"), ensure_ascii=False))

    def test_способ(self) -> None:
        s = _spec(EDV)
        self.assertEqual("swap", x15.anonymise_method(s, "anonymise the bystanders for GDPR"))
        self.assertEqual("blur", x15.anonymise_method(s, "pixelate passers-by for GDPR"))
        self.assertEqual("blur", x15.anonymise_method(s, "размыть лица прохожих"))
        self.assertIsNone(x15.anonymise_method(s, "swap my face onto the actor"))
        self.assertIsNone(x15.anonymise_method(_spec(w(EDV, edit_target="sky")), "blur passers-by"))
        self.assertIsNone(x15.anonymise_method(s, "passers-by walk past the shop"))
        self.assertEqual("swap", x15.anonymise_method(s, "instead of blurring, swap the faces of passers-by for GDPR"))

    def test_рецепт_размытия(self) -> None:
        а = ra.rewrite(_spec(EDV), bs.Маршрут(("правка_видео",), {}), "pixelate the faces of bystanders for GDPR")
        self.assertEqual((), а.route.шаги)
        self.assertIn(x15.ASSEMBLY_ANON_BLUR, а.assembly)
        self.assertIn(x15.ASSEMBLY_ANON_BLUR[0], а.route.сборка)


if __name__ == "__main__":
    unittest.main()
