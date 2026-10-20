"""Round 16 (model expertise & pricing): the seven failure themes of the hidden set.

Every case is a paraphrase written for this file (EN, RU and at least one other language per
theme), never a dev or holdout brief. Decision constants are tested at their edges so that
`scripts/mutate_round16_knowledge.py` turns each mutant red (both ways). No network (T4).

1. TRANSCRIPTION of sensitive material / open weights: open-weights ASR runs on the
   customer's GPU when no API hosts it (`expert_r16.open_weights_route`); the caveat names
   self-hosting, diarisation by pyannote and human review.
2. TEXT-HEAVY STILLS are ranked by RECORDED text rendering (`text_legibility` condition).
3. SPATIAL AUDIO carries the ambisonics / binaural caveat (`outputs[].spatial` first).
4. VIDEO EDIT TIERS: the cheapest adequate tier of the band unless `objective: quality`.
5. BATCHES of lip-sync / avatar clips take the cheapest adequate model.
6. SERIES: a narrated explainer series is made from key visuals; a narrator off screen
   gets no lip sync.
7. DRAWN DUBS: script adaptation; visual lip sync is an OPTIONAL step priced apart.
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Any

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import expert_r16 as x16  # noqa: E402
from studio import hardneed as hn  # noqa: E402
from studio.mcp import capability as cap  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import apply as ra  # noqa: E402
from studio.recipes import checklist as cl  # noqa: E402
from studio.selfrag.facts import Fact, load_facts  # noqa: E402

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


def clip_usd(d: dict) -> float | None:
    цена = d.get("pipeline_price") or {}
    return (цена.get("за_ролик") or {}).get("usd") or (цена.get("смета") or {}).get("usd")


def text_ranked(d: dict) -> bool:
    """The chosen still has a recorded strength on lettering (`condition_note` «for — text_legibility …»)."""
    note = str((step(d, "генерация_изображения").get("chosen") or {}).get("condition_note") or "")
    return note.startswith(("for — text_legibility", "за — text_legibility"))


def notes(d: dict) -> list[str]:
    return [str(н.get("id")) for н in d.get("production_notes") or []]


def _spec(raw: dict) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def fired(raw: dict, steps: list[str], brief: str = "") -> list[str]:
    return [i for i, _ in cl.fire(_spec(raw), steps, text=brief)]


def route(brief: str, raw: dict) -> bs.Маршрут:
    return bs.route(bs.with_defaults(_spec(raw), ролик=True, текст=brief))


def F(model: str, attribute: str, value: str, contra: bool | None = None) -> Fact:
    return Fact(model, attribute, value, "https://example.org/x", "portal", contra=contra)


def w(base: dict, **more: Any) -> dict:
    return {**base, **more}


OPEN_ASR = frozenset({"faster-whisper", "whisper-large-v3", "whisper-large-v3-turbo", "whisper.cpp", "parakeet-tdt-0.6b-v3"})

ASR = {"task": "transcribe", "inputs": [{"kind": "audio", "owned": True, "duration_s": 1200, "count": 3}], "outputs": ["text"],
       "languages": ["en"], "people": []}
IMG = {"task": "generate", "inputs": [], "outputs": ["image"], "shots": 1, "languages": ["en"], "people": []}
SFX = {"task": "generate", "inputs": [], "outputs": ["sfx"], "duration_s": 120, "languages": [], "people": []}
EDV = {"task": "video-edit", "inputs": [{"kind": "video", "owned": True, "duration_s": 30}], "outputs": ["video"], "duration_s": 30,
       "edit_target": "background", "languages": [], "people": []}
UGC = {"task": "avatar", "inputs": [{"kind": "text", "owned": True, "count": 10}], "outputs": ["video", "speech"], "shots": 10,
       "per_shot_s": 15, "characters": 1, "languages": ["en"], "aspect": "9:16",
       "people": [{"name": "creator", "real": False, "on_screen": True, "speaks": True}]}
SER = {"task": "generate", "inputs": [], "outputs": ["video", "speech"], "shots": 20, "per_shot_s": 9, "languages": ["en"],
       "people": []}
DUB = {"task": "dub-translate", "inputs": [{"kind": "video", "owned": True, "duration_s": 1320}], "outputs": ["video", "speech"],
       "duration_s": 1320, "languages": ["es"], "people": [{"name": "hero", "real": False, "on_screen": True, "speaks": True}]}


# --- 1. transcription of sensitive material ------------------------------------------------


class Расшифровка(unittest.TestCase):
    def test_открытые_веса_без_своего_gpu_ru(self) -> None:
        d = plan("Расшифровать записи приёмов врача, только открытые модели", w(ASR, languages=["ru"], open_weights=True))
        self.assertIn(model_of(d, "расшифровка"), OPEN_ASR)
        self.assertIn("GPU", step(d, "расшифровка").get("own_gpu_route", ""))
        self.assertEqual(0.0, clip_usd(d))
        self.assertIn("confidential_transcription", notes(d))

    def test_суд_на_своём_gpu_en(self) -> None:
        d = plan("Transcribe 3 court hearing recordings, confidential, speaker labels needed",
                 w(ASR, self_host={"gpu": "RTX 4090", "vram_gb": 24}))
        self.assertIn(model_of(d, "расшифровка"), OPEN_ASR)
        self.assertIn("pyannote", step(d, "расшифровка").get("speaker_labels", ""))
        self.assertIn("confidential_transcription", notes(d))
        # Self-hosted: the API part is 0 usd and the GPU-time estimate is printed beside it.
        self.assertIn("rented GPU", str((step(d, "расшифровка").get("chosen") or {}).get("price")))

    def test_немецкий_суд_по_полю(self) -> None:
        d = plan("Gerichtsverhandlung transkribieren, vertraulich", w(ASR, languages=["de"], open_weights=True))
        self.assertIn(model_of(d, "расшифровка"), OPEN_ASR)
        self.assertIn("confidential_transcription", notes(d))

    def test_подкаст_без_флагов_api(self) -> None:
        d = plan("Transcribe our weekly podcast", ASR)
        self.assertNotIn(model_of(d, "расшифровка"), OPEN_ASR)
        self.assertNotIn("own_gpu_route", step(d, "расшифровка"))
        self.assertNotIn("confidential_transcription", notes(d))

    def test_маршрут_своего_gpu(self) -> None:
        свой = x16.open_weights_route(hn.Hard(open_weights=True))
        assert свой is not None
        self.assertTrue(свой.self_host)
        self.assertEqual(x16.OPEN_WEIGHTS_SOURCE, dict(свой.sources)["self_host"])
        self.assertIsNone(x16.open_weights_route(hn.Hard(self_host=True, open_weights=True)))
        self.assertIsNone(x16.open_weights_route(hn.Hard()))
        self.assertIsNone(x16.open_weights_route(None))

    def test_чувствительный_материал(self) -> None:
        self.assertTrue(x16.sensitive_material(_spec(w(ASR, self_host=True)), "our podcast"))
        self.assertTrue(x16.sensitive_material(_spec(ASR), "deposition of the witness"))
        self.assertTrue(x16.sensitive_material(_spec(ASR), "записи судебного заседания"))
        self.assertTrue(x16.sensitive_material(_spec(w(ASR, conditions=["HIPAA"])), ""))
        self.assertFalse(x16.sensitive_material(_spec(ASR), "our weekly podcast about coffee"))
        self.assertIn("confidential_transcription", fired(ASR, ["расшифровка"], "medical consultation recordings"))
        self.assertNotIn("confidential_transcription", fired(ASR, ["расшифровка"], "a podcast"))
        self.assertNotIn("confidential_transcription", fired(IMG, ["генерация_изображения"], "court sketch poster"))

    def test_записи_о_весах_asr(self) -> None:
        факты = load_facts()
        parakeet = [f for f in факты if f.model == "parakeet-tdt-0.6b-v3"]
        self.assertIn(("license", "cc-by-4.0"), {(f.attribute, f.value) for f in parakeet})
        self.assertIn(("pipeline_tag", "automatic-speech-recognition"), {(f.attribute, f.value) for f in parakeet})
        время = hn.gpu_time([f for f in факты if f.model == "faster-whisper"])
        assert время is not None
        self.assertEqual((63.0, 780.0), (время.seconds, время.clip_seconds))


# --- 2. text-heavy stills ------------------------------------------------------------------


class ТекстНаКартинке(unittest.TestCase):
    def test_постер_en(self) -> None:
        d = plan("A festival poster with the headline 'SUMMER NIGHTS' and the dates", IMG)
        self.assertIn("text_legibility", (d.get("stated_conditions") or {}).get("understood") or [])
        self.assertTrue(text_ranked(d), step(d, "генерация_изображения").get("chosen"))
        self.assertIn("text_heavy_image", notes(d))

    def test_упаковка_ru(self) -> None:
        d = plan("Упаковка чая с надписью «Иван-чай» и составом", w(IMG, languages=["ru"]))
        self.assertTrue(text_ranked(d))
        self.assertIn("text_heavy_image", notes(d))

    def test_вывеска_es_кавычки(self) -> None:
        # A quoted string is the lettering in any language; the Spanish words are not read.
        d = plan("Cartel de la tienda con el texto 'Panadería Ñandú'", w(IMG, languages=["es"]))
        self.assertTrue(text_ranked(d))

    def test_условие_по_полю_ja(self) -> None:
        d = plan("店の看板、正確な文字", w(IMG, languages=["ja"], conditions=["exact lettering"]))
        self.assertTrue(text_ranked(d))

    def test_просто_кошка_без_условия(self) -> None:
        d = plan("A cat sleeping on a sofa, photo", IMG)
        self.assertNotIn("text_legibility", (d.get("stated_conditions") or {}).get("understood") or [])
        self.assertNotIn("text_heavy_image", notes(d))

    def test_слова_и_кавычки(self) -> None:
        self.assertTrue(x16.text_heavy(_spec(IMG), "a poster for our bakery"))
        self.assertTrue(x16.text_heavy(_spec(IMG), "афиша концерта"))
        self.assertTrue(x16.text_heavy(_spec(IMG), "un cartel que diga «Feliz Año»"))
        self.assertTrue(x16.text_heavy(_spec(w(IMG, conditions=["typography"])), ""))
        self.assertFalse(x16.text_heavy(_spec(IMG), "don't make it dark, it's for a calm mood"))
        self.assertFalse(x16.text_heavy(_spec(IMG), "a mountain lake at dawn"))
        self.assertFalse(x16.text_heavy(_spec(SFX), "a poster jingle"))

    def test_знак_только_на_условии(self) -> None:
        сильная = F("m-a", "text_rendering", "Built to deliver exceptional text rendering accuracy")
        оговорка = F("m-b", "text_rendering", "Although significantly improved, the model can still struggle with text")
        self.assertEqual(cap.CONDITION_POSITIVE, cap.condition_state([сильная], ["text_legibility"])[0])
        self.assertEqual(cap.CONDITION_UNKNOWN, cap.condition_state([оговорка], ["text_legibility"])[0])
        # The same row says nothing on another condition, and is not declared good news.
        self.assertEqual(cap.CONDITION_UNKNOWN, cap.condition_state([сильная], ["hands"])[0])
        self.assertEqual(cap.INFO, cap.знак(сильная)[0])

    def test_записанная_отрисовка_текста(self) -> None:
        за = {f.model for f in load_facts() if f.attribute == "text_rendering"
              and cap.condition_state([f], ["text_legibility"])[0] == cap.CONDITION_POSITIVE}
        self.assertTrue({"ideogram-v3", "recraft-v3", "flux-2-flex", "nano-banana-pro"} <= за, за)
        self.assertNotIn("gpt-image-2", за)


# --- 3. spatial audio ----------------------------------------------------------------------


class ПространственныйЗвук(unittest.TestCase):
    def test_слова_en_ru(self) -> None:
        self.assertIn("spatial_audio", fired(SFX, ["звук_фон"], "ambisonic forest ambience for our VR experience"))
        self.assertIn("spatial_audio", fired(SFX, ["звук_фон"], "объёмный звук леса для VR"))

    def test_поле_zh(self) -> None:
        raw = w(SFX, outputs=[{"kind": "sfx", "spatial": True}])
        self.assertTrue(_spec(raw).spatial)
        self.assertIn("spatial_audio", fired(raw, ["звук_фон"], "森林的声音"))

    def test_поле_старше_слов(self) -> None:
        raw = w(SFX, outputs=[{"kind": "sfx", "spatial": False}])
        self.assertNotIn("spatial_audio", fired(raw, ["звук_фон"], "binaural forest for VR"))

    def test_молчит(self) -> None:
        self.assertNotIn("spatial_audio", fired(SFX, ["звук_фон"], "stereo rain ambience"))
        self.assertNotIn("spatial_audio", fired(IMG, ["генерация_изображения"], "a VR headset product shot"))

    def test_плохое_значение_поля(self) -> None:
        _, errors = bs.parse_spec(w(SFX, outputs=[{"kind": "sfx", "spatial": "yes"}]))
        self.assertTrue(any("spatial" in e for e in errors), errors)

    def test_план_с_полем(self) -> None:
        d = plan("Ambiente de bosque para nuestra experiencia de realidad virtual", w(SFX, outputs=[{"kind": "sfx", "spatial": True}]))
        self.assertIn("spatial_audio", notes(d))


# --- 4. video edit tiers ---------------------------------------------------------------------


class СтупеньПравки(unittest.TestCase):
    def test_фон_без_премиума_en(self) -> None:
        d = plan("Replace the background of our 30 s product video with a beach", EDV)
        премиум = plan("Replace the background of our 30 s product video with a beach", w(EDV, objective="quality"))
        self.assertLess(clip_usd(d), clip_usd(премиум))
        swap = step(d, "правка_видео").get("budget_swap") or {}
        self.assertEqual(list(x16.REASON_EDIT_TIER), list(swap.get("reason") or []))
        self.assertNotIn("budget_swap", step(премиум, "правка_видео"))

    def test_фон_ru_pt(self) -> None:
        for brief in ("Заменить фон в нашем 30-секундном ролике на пляж", "Trocar o fundo do nosso vídeo de 30 s por uma praia"):
            with self.subTest(brief=brief):
                d = plan(brief, EDV)
                self.assertIn("budget_swap", step(d, "правка_видео"))
                self.assertLessEqual(clip_usd(d), 5.0)

    def test_правило(self) -> None:
        self.assertTrue(x16.edit_tier_applies("правка_видео", ""))
        self.assertTrue(x16.edit_tier_applies("правка_видео", "balanced"))
        self.assertFalse(x16.edit_tier_applies("правка_видео", "quality"))
        self.assertFalse(x16.edit_tier_applies("генерация_видео", ""))

    def test_копейки_не_обмен(self) -> None:
        self.assertFalse(x16.edit_tier_worth(1.5, 1.0))
        self.assertTrue(x16.edit_tier_worth(1.51, 1.0))
        self.assertFalse(x16.edit_tier_worth(1.2, 0.0))
        # A 4K source: the cents saved are not worth a model whose output frame is not on record.
        d = plan("Replace the red car with a blue one in our clip", {
            "task": "video-edit", "edit": ["replace-object"], "outputs": ["video"], "duration_s": 8, "people": [],
            "inputs": [{"kind": "video", "owned": True, "duration_s": 8, "resolution": "3840x2160"}]})
        self.assertNotIn("budget_swap", step(d, "правка_видео"))

    def test_тариф_ниже_кадра_негоден(self) -> None:
        class C:
            below_frame = False

            class cost:
                class default:
                    formula = "[720p ниже заказанного 1080p — нужен апскейл] 30 s × 0.03"

        self.assertFalse(x16.adequate_frame(C))
        C.cost.default.formula = "30 s × 0.14 usd/s"
        self.assertTrue(x16.adequate_frame(C))
        C.below_frame = True
        self.assertFalse(x16.adequate_frame(C))


# --- 5. batches --------------------------------------------------------------------------------


class Пачка(unittest.TestCase):
    def test_ugc_en(self) -> None:
        d = plan("10 UGC ads, the same AI creator talking to camera, 15 s each", UGC)
        премиум = plan("10 UGC ads, the same AI creator talking to camera, 15 s each", w(UGC, objective="quality"))
        self.assertLess(clip_usd(d), clip_usd(премиум))
        swap = step(d, "говорящий_аватар").get("budget_swap") or {}
        self.assertEqual(list(x16.REASON_BATCH), list(swap.get("reason") or []))
        # The shared avatar is made once for the whole batch.
        self.assertEqual(1, next(а for а in d.get("shared_assets") or [] if а.get("step") == "генерация_изображения")["made"])

    def test_ugc_ru_de(self) -> None:
        for brief in ("10 UGC-роликов, один и тот же ИИ-блогер говорит в камеру, по 15 секунд",
                      "10 UGC-Clips, dieselbe KI-Creatorin spricht in die Kamera, je 15 Sekunden"):
            with self.subTest(brief=brief):
                self.assertIn("budget_swap", step(plan(brief, UGC), "говорящий_аватар"))

    def test_два_ролика_не_пачка(self) -> None:
        d = plan("2 UGC ads, the same AI creator talking to camera, 15 s each", w(UGC, shots=2,
                 inputs=[{"kind": "text", "owned": True, "count": 2}]))
        self.assertNotIn("budget_swap", step(d, "говорящий_аватар"))

    def test_края(self) -> None:
        self.assertTrue(x16.batch_cheap_applies("говорящий_аватар", 3, ""))
        self.assertFalse(x16.batch_cheap_applies("говорящий_аватар", 2, ""))
        self.assertTrue(x16.batch_cheap_applies("липсинк", 3, "cheapest"))
        self.assertFalse(x16.batch_cheap_applies("липсинк", 30, "quality"))
        self.assertFalse(x16.batch_cheap_applies("оживление", 30, ""))
        self.assertFalse(x16.batch_ratio_exceeded(1.5, 1.0))
        self.assertTrue(x16.batch_ratio_exceeded(1.51, 1.0))
        self.assertFalse(x16.batch_ratio_exceeded(5.0, 0.0))


# --- 6. series ---------------------------------------------------------------------------------


class Серии(unittest.TestCase):
    def test_объясняющая_серия_en(self) -> None:
        м = route("An explainer series for our SaaS, 4 episodes, voiceover", SER)
        self.assertEqual(("генерация_изображения", "оживление", "озвучка"), м.шаги)
        self.assertEqual(20, м.штук["генерация_изображения"])

    def test_объясняющая_серия_ru(self) -> None:
        м = route("Серия из 4 объясняющих роликов про наш сервис, закадровый голос", w(SER, languages=["ru"]))
        self.assertIn("генерация_изображения", м.шаги)
        self.assertNotIn("генерация_видео", м.шаги)

    def test_поле_стиля_fr(self) -> None:
        # French words are not read: the field decides both ways.
        brief = "Une série de vidéos explicatives pour notre logiciel, voix off"
        self.assertIn("генерация_изображения", route(brief, w(SER, languages=["fr"], consistency=["style"])).шаги)
        self.assertIn("генерация_видео", route(brief, w(SER, languages=["fr"])).шаги)

    def test_края_шотов(self) -> None:
        self.assertIn("генерация_изображения", route("an explainer series", w(SER, shots=4)).шаги)
        self.assertIn("генерация_видео", route("an explainer series", w(SER, shots=3)).шаги)

    def test_не_серия_ключевых_кадров(self) -> None:
        self.assertIn("генерация_видео", route("a 20-shot ad with a voiceover", SER).шаги)
        м = route("an explainer series where our presenter talks to camera", w(SER, characters=1))
        self.assertNotIn("генерация_видео", м.шаги)
        self.assertIn("липсинк", м.шаги)

    def test_антология_рассказчик_за_кадром_ru(self) -> None:
        м = route("Антология: 4 эпизода, в каждом свой герой рассказывает историю, голос за кадром",
                  w(SER, languages=["ru"], characters=4))
        self.assertNotIn("липсинк", м.шаги)

    def test_антология_рассказчик_по_полю_es(self) -> None:
        м = route("Antología de 4 episodios, personajes distintos en cada uno", w(SER, languages=["es"], characters=4,
                  people=[{"name": "narrador", "real": False, "on_screen": False, "speaks": True}]))
        self.assertNotIn("липсинк", м.шаги)

    def test_диалог_в_кадре_остаётся(self) -> None:
        м = route("4 episodes, two robots talk to each other in every shot", w(SER, characters=2))
        self.assertIn("липсинк", м.шаги)

    def test_план_серии_дешевле_t2v(self) -> None:
        d = plan("An explainer series for our SaaS, 4 episodes, voiceover", SER)
        self.assertIn("генерация_изображения", steps_of(d))
        self.assertIn("style_consistency_set", notes(d))


# --- 7. drawn dubs -----------------------------------------------------------------------------


class РисованныйДубляж(unittest.TestCase):
    def test_аниме_en(self) -> None:
        d = plan("Dub our 22-minute anime episode into Spanish", w(DUB, conditions=["anime"]))
        липсинк = step(d, "липсинк")
        self.assertTrue(липсинк.get("optional"))
        self.assertTrue(липсинк.get("conditional"))
        дубляж_usd = next(с["usd"] for с in d["pipeline_price"]["смета"]["steps"] if с["step"] == "дубляж")
        self.assertEqual(round(дубляж_usd, 2), round(clip_usd(d), 2))
        отдельно = [у for у in d["pipeline_price"].get("conditional_steps") or [] if у["step"] == "липсинк"]
        self.assertTrue(отдельно and отдельно[0].get("optional") and отдельно[0].get("usd"))
        self.assertIn("drawn_dub_adaptation", notes(d))
        self.assertIn("OPTIONAL", d.get("summary", ""))

    def test_мультфильм_ru(self) -> None:
        d = plan("Переозвучить наш мультфильм на русский, 22 минуты", w(DUB, languages=["ru"]))
        self.assertTrue(step(d, "липсинк").get("optional"))
        self.assertIn("адаптац", step(d, "дубляж").get("inferred", ""))

    def test_ja_по_условию(self) -> None:
        d = plan("このアニメを英語に吹き替えてください", w(DUB, languages=["en"], conditions=["anime"]))
        self.assertTrue(step(d, "липсинк").get("optional"))

    def test_липсинк_заказан(self) -> None:
        d = plan("Dub our 22-minute anime episode into Spanish with lip sync", w(DUB, conditions=["anime"], lipsync=True))
        self.assertFalse(step(d, "липсинк").get("optional"))
        без = plan("Dub our 22-minute anime episode into Spanish", w(DUB, conditions=["anime"]))
        self.assertGreater(clip_usd(d), clip_usd(без))
        self.assertNotIn("drawn_dub_adaptation", notes(d))

    def test_снятое_интервью(self) -> None:
        d = plan("Dub our filmed interview into Spanish", w(DUB, lipsync=True, people=[
            {"name": "host", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}]))
        self.assertFalse(step(d, "липсинк").get("optional"))

    def test_правило(self) -> None:
        self.assertTrue(x16.optional_lips(_spec(DUB), drawn=True))
        self.assertFalse(x16.optional_lips(_spec(w(DUB, lipsync=True)), drawn=True))
        self.assertFalse(x16.optional_lips(_spec(DUB), drawn=False))
        а = ra.rewrite(_spec(w(DUB, conditions=["anime"])), bs.Маршрут(("дубляж", "липсинк"), {}), "")
        self.assertEqual((x16.OPTIONAL_LIPS_STEP,), а.optional)
        self.assertEqual(x16.NOTE_DRAWN_ADAPT[0], а.route.пометки["дубляж"])


if __name__ == "__main__":
    unittest.main()
