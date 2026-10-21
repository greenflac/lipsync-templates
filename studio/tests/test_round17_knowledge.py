"""Round 17 (specialist knowledge & pricing): the themes of the hidden set.

Every case is a paraphrase written for this file (EN, RU and at least one other language per
theme), never a dev or holdout brief. Each trigger reads the spec field first and the EN/RU
words only when the field is absent; both directions are pinned, and decision constants are
tested at their edges so that `scripts/mutate_round17_knowledge.py` turns each mutant red.
No network (T4).

1. AUDIO DESCRIPTION as a production (`audio_description_track`) and its pricing: one
   transcript, a description voice priced for the gaps (`AD_GAP_SHARE`), not the runtime.
2. CODE-SWITCHING speech (`code_switching_speech`): one mixed track, priced once.
3. PROVIDER DATA TERMS for client / personal / confidential uploads (`provider_data_terms`).
4. HIGHLIGHT SELECTION (`highlight_selection`) and a recap priced as an edit plus a short
   voice-over by the recap's length.
5. FRAME-RATE STANDARDS CONVERSION (`standards_conversion`) from `inputs[].fps` against
   `fps` / `delivery.markets`.
6. STEM SEPARATION (`stem_separation`).
7. BACKGROUND BLUR (`background_blur`): a matte and a blur at assembly, never a generative edit.
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Any

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import expert_r17 as x17  # noqa: E402
from studio import l10n  # noqa: E402
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


def clip_usd(d: dict) -> float | None:
    цена = d.get("pipeline_price") or {}
    return (цена.get("за_ролик") or {}).get("usd")


def step_usd(d: dict, name: str) -> float:
    return next(float(с["usd"]) for с in d["pipeline_price"]["смета"]["steps"] if с["step"] == name)


def notes(d: dict) -> list[str]:
    return [str(н.get("id")) for н in d.get("production_notes") or []]


def _spec(raw: dict) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def fired(raw: dict, steps: list[str], brief: str = "") -> list[str]:
    return [i for i, _ in cl.fire(_spec(raw), steps, text=brief)]


def w(base: dict, **more: Any) -> dict:
    return {**base, **more}


LECTURE = {"task": "captions", "inputs": [{"kind": "video", "owned": True, "duration_s": 3600}],
           "outputs": ["video", "text", "speech"], "duration_s": 3600, "languages": ["en", "es"],
           "accessibility": ["captions", "audio-description"], "domain": ["education"], "people": []}
SPOT = {"task": "generate", "inputs": [{"kind": "text", "owned": True}], "outputs": ["speech"], "duration_s": 30,
        "languages": ["es-US", "en-US"], "people": []}
ASR = {"task": "transcribe", "inputs": [{"kind": "audio", "owned": True, "duration_s": 1800}], "outputs": ["text"],
       "languages": ["hi", "en"], "people": []}
DUB = {"task": "dub-translate", "inputs": [{"kind": "video", "owned": True, "duration_s": 300}], "outputs": ["video", "speech"],
       "duration_s": 300, "languages": ["de"], "lipsync": False, "audio": "voiceover", "people": []}
RECAP = {"task": "cut-to-shorts", "inputs": [{"kind": "video", "owned": True, "duration_s": 720, "count": 10}],
         "outputs": ["video", "speech"], "duration_s": 90, "languages": ["en"], "audio": "voiceover", "people": []}
RECAP_EDIT = {"task": "video-edit", "inputs": [{"kind": "video", "owned": True, "duration_s": 7200}],
              "outputs": ["video", "speech"], "duration_s": 90, "languages": ["en"], "people": []}
DOC = {"task": "video-edit", "inputs": [{"kind": "video", "owned": True, "duration_s": 1500, "fps": 25}], "outputs": ["video"],
       "duration_s": 1500, "edit": ["trim"], "people": []}
MIX = {"task": "dub-translate", "inputs": [{"kind": "video", "owned": True, "duration_s": 600}], "outputs": ["video", "speech"],
       "duration_s": 600, "languages": ["es"], "lipsync": False, "audio": "voiceover", "people": []}
BLUR = {"task": "video-edit", "inputs": [{"kind": "video", "owned": True, "duration_s": 180}], "outputs": ["video"],
        "duration_s": 180, "people": []}


# --- 1. audio description -------------------------------------------------------------------


class Тифлокомментарий(unittest.TestCase):
    def test_пакет_доступности_en(self) -> None:
        d = plan("Accessibility package for our 60-minute lecture: captions, a transcript, a Spanish translation "
                 "and audio description", LECTURE)
        self.assertEqual(["расшифровка", "озвучка"], steps_of(d))
        # ONE transcript for captions, text and translation: 3600 s once, not per language.
        self.assertEqual(0.48, step_usd(d, "расшифровка"))
        self.assertIn("the transcript is made ONCE", str(step(d, "расшифровка").get("inferred")))
        # The description voice: 15 % of the runtime (540 s) in each of the two languages, not 3600 s.
        self.assertIn("540 s", str(step(d, "озвучка").get("inferred")))
        self.assertEqual(0.89, clip_usd(d))
        self.assertIn("audio_description_track", notes(d))
        self.assertEqual([], l10n.leaks(d, "en"))

    def test_пакет_ru(self) -> None:
        d = plan("Пакет доступности для лекции на час: субтитры, расшифровка, перевод на испанский и тифлокомментарий",
                 LECTURE)
        self.assertIn("тифлокомментар", str(step(d, "озвучка").get("inferred")))
        self.assertIn("audio_description_track", notes(d))

    def test_поле_de(self) -> None:
        # German words are not read: the field decides.
        d = plan("Barrierefreies Paket für unsere Vorlesung: Untertitel und Audiodeskription",
                 w(LECTURE, languages=["de"]))
        self.assertIn("озвучка", steps_of(d))
        self.assertIn("audio_description_track", notes(d))

    def test_поле_старше_слов(self) -> None:
        raw = w(LECTURE, accessibility=["captions"])
        self.assertNotIn("audio_description_track", fired(raw, ["расшифровка"], "captions and audio description"))
        self.assertFalse(x17.ad_package(_spec(raw), "captions and audio description"))
        d = plan("Captions and audio description for our lecture", raw)
        self.assertEqual(["расшифровка"], steps_of(d))

    def test_слова_без_поля(self) -> None:
        raw = {k: v for k, v in LECTURE.items() if k != "accessibility"}
        self.assertIn("audio_description_track", fired(raw, ["расшифровка"], "captions and audio description please"))
        self.assertIn("audio_description_track", fired(raw, ["расшифровка"], "нужен тифлокомментарий"))
        self.assertNotIn("audio_description_track", fired(raw, ["расшифровка"], "captions please"))

    def test_без_видео_молчит(self) -> None:
        raw = {"task": "transcribe", "inputs": [{"kind": "audio", "owned": True, "duration_s": 600}], "outputs": ["text"],
               "languages": ["en"], "accessibility": ["audio-description"], "people": []}
        self.assertFalse(x17.audio_description(_spec(raw)))
        self.assertNotIn("audio_description_track", fired(raw, ["расшифровка"]))

    def test_секунды_пауз(self) -> None:
        self.assertEqual(0.15, x17.AD_GAP_SHARE)
        self.assertEqual(540.0, x17.ad_voice_seconds(3600))
        self.assertEqual(0.0, x17.ad_voice_seconds(0))
        self.assertEqual(3600.0, x17.material_seconds(_spec(LECTURE)))
        self.assertEqual(7200.0, x17.material_seconds(_spec(RECAP)))

    def test_задачи_пакета(self) -> None:
        self.assertTrue(x17.ad_package(_spec(w(LECTURE, task="transcribe")), ""))
        self.assertFalse(x17.ad_package(_spec(w(LECTURE, task="dub-translate")), ""))
        # The voice reads in the gaps: a clone-only model is ranked last.
        а = ra.rewrite(_spec(LECTURE), bs.Маршрут(("расшифровка",), {}), "")
        self.assertIn("ad_gap_voice", а.priors)
        self.assertEqual((540.0, 540.0), а.step_seconds["озвучка"])
        self.assertIn(x17.ASSEMBLY_AD_MIX, а.assembly)
        выкл = ra.rewrite(_spec(w(LECTURE, priors={"ad_gap_voice": False})), bs.Маршрут(("расшифровка",), {}), "")
        self.assertNotIn("озвучка", выкл.route.шаги)


# --- 2. code-switching ---------------------------------------------------------------------------


class СмешениеЯзыков(unittest.TestCase):
    def test_spanglish_en_одна_дорожка(self) -> None:
        brief = "A 30-second radio spot in Spanglish, the announcer switches languages mid-sentence"
        d = plan(brief, SPOT)
        двуязычный = plan("A 30-second radio spot in English and a Spanish version", SPOT)
        self.assertIn("code_switching_speech", notes(d))
        self.assertNotIn("code_switching_speech", notes(двуязычный))
        # One mixed track is priced once; two separate versions are priced per language.
        self.assertEqual(0.04, clip_usd(d))
        self.assertEqual(0.07, clip_usd(двуязычный))

    def test_каждое_слово_отдельно(self) -> None:
        self.assertTrue(x17.code_switching(_spec(SPOT), "a Spanglish jingle"))
        self.assertTrue(x17.code_switching(_spec(SPOT), "говорят вперемешку"))

    def test_ru_слова(self) -> None:
        self.assertIn("code_switching_speech", fired(w(ASR, languages=["ru", "en"]), ["расшифровка"],
                                                     "ведущие говорят вперемешку на русском и английском"))

    def test_тег_mul_hi(self) -> None:
        # Hindi words are not read: the `mul` tag names a mixed-language track.
        d = plan("हमारे पॉडकास्ट का ट्रांसक्रिप्ट चाहिए, होस्ट हिंदी और अंग्रेज़ी मिलाकर बोलते हैं",
                 w(ASR, languages=["mul", "hi", "en"]))
        self.assertIn("code_switching_speech", notes(d))
        self.assertTrue(x17.code_switching(_spec(w(ASR, languages=["mul"])), ""))

    def test_условие_es(self) -> None:
        self.assertTrue(x17.code_switching(_spec(w(SPOT, conditions=["code-switching"])), "anuncio de radio"))

    def test_молчит(self) -> None:
        self.assertFalse(x17.code_switching(_spec(ASR), "an interview in Hindi with English subtitles"))
        self.assertFalse(x17.code_switching(_spec(ASR), "mix the music and the voice"))
        self.assertNotIn("code_switching_speech", fired(w(BLUR, edit=["stabilise"]), ["правка_видео"], "Spanglish"))


# --- 3. provider data terms ---------------------------------------------------------------------


class УсловияПровайдера(unittest.TestCase):
    def test_клиент_nda_en(self) -> None:
        d = plan("Dub our client's internal training video into German, it is under NDA", DUB)
        self.assertIn("provider_data_terms", notes(d))
        rule = cl.RULES["provider_data_terms"]
        self.assertIn("X-Fal-Store-IO: 0", rule.en)
        self.assertIn("does not cover dubbing", rule.en)

    def test_каждое_слово_отдельно(self) -> None:
        self.assertTrue(x17.provider_data_terms(_spec(DUB), "клиентское видео"))
        self.assertTrue(x17.provider_data_terms(_spec(DUB), "it is under NDA"))

    def test_клиент_ru(self) -> None:
        self.assertIn("provider_data_terms", fired(DUB, ["дубляж"], "переозвучить клиентское видео, оно под nda"))

    def test_поле_области_fr(self) -> None:
        d = plan("Doubler la vidéo de formation interne de notre client en allemand", w(DUB, domain=["corporate"]))
        self.assertIn("provider_data_terms", notes(d))

    def test_обучение_и_дети_es(self) -> None:
        self.assertIn("provider_data_terms", fired(w(DUB, training_use=True), ["дубляж"], "doblar nuestros vídeos"))
        niño = w(DUB, people=[{"name": "niño", "real": True, "minor": True, "consent": "stated", "claim": "none"}])
        self.assertTrue(x17.provider_data_terms(_spec(niño), "doblar el vídeo de la familia"))

    def test_молчит(self) -> None:
        self.assertNotIn("provider_data_terms", fired(DUB, ["дубляж"], "dub our cooking show into German"))
        self.assertNotIn("provider_data_terms", fired(w(DUB, domain=["entertainment"]), ["дубляж"], "dub our show"))
        # Own GPU: nothing is uploaded.
        свой = w(DUB, self_host={"gpu": "RTX 4090", "vram_gb": 24})
        self.assertFalse(x17.provider_data_terms(_spec(свой), "our client's footage under NDA"))
        # Nothing brought: nothing to upload.
        self.assertFalse(x17.provider_data_terms(_spec({"task": "generate", "inputs": [], "outputs": ["image"], "shots": 1,
                                                        "people": []}), "an image for our client under NDA"))

    def test_расшифровка_суда_своей_оговоркой(self) -> None:
        raw = {"task": "transcribe", "inputs": [{"kind": "audio", "owned": True, "duration_s": 600}], "outputs": ["text"],
               "languages": ["en"], "people": []}
        ids = fired(raw, ["расшифровка"], "confidential court hearing recordings")
        self.assertIn("confidential_transcription", ids)
        self.assertNotIn("provider_data_terms", ids)

    def test_записанное_хранение(self) -> None:
        факты = {(f.model, f.attribute): f.value for f in load_facts() if f.attribute == "data_retention"}
        self.assertIn("not covered by Zero Retention Mode", факты[("elevenlabs-dubbing", "data_retention")])
        self.assertIn("enable_logging=false", факты[("scribe-v2", "data_retention")])


# --- 4. highlights and recaps ---------------------------------------------------------------------


class Пересказ(unittest.TestCase):
    def test_пересказ_en_цена_по_длине_пересказа(self) -> None:
        d = plan("A 90-second recap of our 10-episode web drama, 12 minutes each, with a short narrator", RECAP)
        self.assertEqual(["расшифровка", "озвучка"], steps_of(d))
        self.assertEqual(0.96, step_usd(d, "расшифровка"))
        self.assertIn("(90 s)", str(step(d, "озвучка").get("inferred")))
        self.assertEqual(1.07, clip_usd(d))
        self.assertIn("highlight_selection", notes(d))

    def test_пересказ_правкой_не_генерация(self) -> None:
        d = plan("Make a 90-second recap of our web drama with a voice-over", RECAP_EDIT)
        self.assertNotIn("правка_видео", steps_of(d))
        self.assertEqual(["расшифровка", "озвучка"], steps_of(d))
        self.assertEqual(1.07, clip_usd(d))

    def test_ru_нарезка(self) -> None:
        d = plan("Нарезка лучших моментов нашего веб-сериала на 90 секунд с закадровым голосом", RECAP_EDIT)
        self.assertNotIn("правка_видео", steps_of(d))
        self.assertIn("highlight_selection", notes(d))

    def test_поле_задачи_de(self) -> None:
        d = plan("Eine Zusammenfassung unserer Webserie, 90 Sekunden", w(RECAP, audio=None))
        self.assertIn("highlight_selection", notes(d))
        # No narrator named (audio silent, German words not read): no voice-over step.
        self.assertEqual(["расшифровка"], steps_of(d))

    def test_шорты_по_длине_пересказа(self) -> None:
        шорты = w(RECAP, duration_s=None, shots=3, per_shot_s=30)
        d = plan("Three 30-second recaps of our web drama with a narrator", шорты)
        self.assertIn("(90 s)", str(step(d, "озвучка").get("inferred")))
        self.assertEqual(0.11, round(step_usd(d, "озвучка"), 2))
        self.assertEqual(1.07, clip_usd(d))
        # With the defaults filled (the material's length derived), the narrator is still the recap's.
        self.assertEqual(90.0, x17.recap_vo_seconds(bs.with_defaults(_spec(шорты), ролик=True, текст="")))
        self.assertTrue(x17.highlight_selection(_spec(w(RECAP_EDIT, task="video-edit")), "нарезка из сериала"))

    def test_голос_по_полю_и_длине(self) -> None:
        self.assertTrue(x17.recap_narration(_spec(RECAP), ""))
        self.assertFalse(x17.recap_narration(_spec(w(RECAP, audio="native")), "with a voice-over"))
        self.assertEqual(90.0, x17.recap_vo_seconds(_spec(RECAP)))
        шорты = w(RECAP, duration_s=None, shots=3, per_shot_s=30)
        self.assertEqual(90.0, x17.recap_vo_seconds(_spec(шорты)))
        # No recap length named: the series length is not the narrator's.
        self.assertIsNone(x17.recap_vo_seconds(_spec(w(RECAP, duration_s=None))))
        без_длины = ra.rewrite(_spec(w(RECAP, duration_s=None)), bs.Маршрут(("расшифровка",), {}), "")
        self.assertNotIn("озвучка", без_длины.route.шаги)
        с_длиной = ra.rewrite(_spec(RECAP), bs.Маршрут(("расшифровка",), {}), "")
        self.assertEqual(("расшифровка", "озвучка"), с_длиной.route.шаги)
        self.assertIn("recap_short_vo", с_длиной.priors)

    def test_правка_с_названной_правкой_не_пересказ(self) -> None:
        self.assertFalse(x17.recap_edit(_spec(w(RECAP_EDIT, edit=["stabilise"])), "a recap"))
        self.assertFalse(x17.recap_edit(_spec(w(RECAP_EDIT, edit_target="sky")), "a recap"))
        self.assertFalse(x17.highlight_selection(_spec(w(RECAP_EDIT, task="video-edit")), "replace the sky"))
        self.assertFalse(x17.highlight_selection(_spec(w(RECAP_EDIT, task="video-edit")), "highlight our logo"))


# --- 5. frame-rate standards conversion -----------------------------------------------------------


class ЧастотаКадров(unittest.TestCase):
    def test_pal_в_сша_ja(self) -> None:
        raw = w(DOC, delivery={"platform": ["broadcast"], "markets": ["US"]})
        self.assertIn("standards_conversion", fired(raw, [], "このドキュメンタリーを米国で放送"))

    def test_то_же_семейство_молчит(self) -> None:
        self.assertNotIn("standards_conversion", fired(w(DOC, delivery={"markets": ["DE"]}), [], "PAL to NTSC"))
        self.assertNotIn("standards_conversion", fired(w(DOC, fps=50), [], ""))
        # A web upload keeps its native rate whatever the market.
        self.assertNotIn("standards_conversion", fired(w(DOC, delivery={"platform": ["youtube"], "markets": ["US"]}), [], ""))

    def test_кино_в_европу_и_поле_fps(self) -> None:
        кино = w(DOC, inputs=[{"kind": "video", "owned": True, "duration_s": 1500, "fps": 23.976}])
        self.assertIn("standards_conversion", fired(w(кино, delivery={"markets": ["FR"]}), [], ""))
        self.assertIn("standards_conversion", fired(w(DOC, fps=30), [], ""))

    def test_слова_en_ru(self) -> None:
        без = w(DOC, inputs=[{"kind": "video", "owned": True, "duration_s": 1500}])
        self.assertIn("standards_conversion", fired(без, [], "convert our PAL master for NTSC"))
        self.assertIn("standards_conversion", fired(без, [], "чересстрочный исходник 50i для эфира"))
        self.assertIn("standards_conversion", fired(без, [], "чересстрочный исходник"))
        self.assertNotIn("standards_conversion", fired(без, [], "trim the first minute"))

    def test_семейства(self) -> None:
        self.assertEqual("film", x17.fps_family(23.976))
        self.assertEqual("pal", x17.fps_family(25))
        self.assertEqual("ntsc", x17.fps_family(29.97))
        self.assertEqual("ntsc", x17.fps_family(60))
        self.assertIsNone(x17.fps_family(16))
        self.assertIn("US", x17.NTSC_MARKETS)
        self.assertIn("JP", x17.NTSC_MARKETS)
        self.assertNotIn("GB", x17.NTSC_MARKETS)

    def test_план(self) -> None:
        d = plan("Our 25 fps documentary must air on a US channel", w(DOC, delivery={"platform": ["broadcast"], "markets": ["US"]}))
        self.assertIn("standards_conversion", notes(d))


# --- 6. stem separation ---------------------------------------------------------------------------


class Стемы(unittest.TestCase):
    def test_стемы_по_полю_es(self) -> None:
        raw = w(MIX, delivery={"stems": True})
        self.assertIn("stem_separation", fired(raw, ["дубляж"], "doblar nuestra película al español"))
        d = plan("Doblar nuestra película al español con pistas separadas", raw)
        self.assertIn("stem_separation", notes(d))

    def test_поле_старше_слов(self) -> None:
        self.assertNotIn("stem_separation", fired(w(MIX, delivery={"stems": False}), ["дубляж"], "make a karaoke version"))

    def test_слова_en_ru(self) -> None:
        self.assertIn("stem_separation", fired(MIX, ["дубляж"], "a karaoke version of the song"))
        self.assertIn("stem_separation", fired(MIX, ["дубляж"], "isolate the vocals from the mix"))
        self.assertIn("stem_separation", fired(MIX, ["дубляж"], "нужна минусовка песни"))
        self.assertIn("stem_separation", fired(MIX, ["дубляж"], "отделить вокал от музыки"))

    def test_молчит(self) -> None:
        self.assertNotIn("stem_separation", fired(MIX, ["дубляж"], "a separate voice for each character"))
        self.assertNotIn("stem_separation", fired(MIX, ["дубляж"], "система дубляжа"))
        self.assertFalse(x17.stem_separation(_spec({"task": "generate", "inputs": [], "outputs": ["music"],
                                                    "duration_s": 60, "people": []}), "karaoke track"))

    def test_записанные_модели(self) -> None:
        факты = {(f.model, f.attribute): f.value for f in load_facts()}
        self.assertTrue(факты[("htdemucs", "license")].startswith("mit"))
        self.assertIn("9.80 dB", факты[("bs-roformer", "benchmark_score")])
        self.assertIn("$0.0007 per second", факты[("htdemucs", "price_per_second_usd")])


# --- 7. background blur ---------------------------------------------------------------------------


class РазмытиеФона(unittest.TestCase):
    def test_поле_de(self) -> None:
        d = plan("Hintergrund unseres Interviews unscharf machen", w(BLUR, edit=["blur-background"]))
        self.assertEqual(["удаление_фона_видео"], steps_of(d))
        self.assertEqual(9.0, clip_usd(d))
        self.assertIn("background_blur", notes(d))

    def test_слова_en(self) -> None:
        d = plan("Blur the background of our 3-minute interview, soft bokeh, keep the speaker sharp",
                 w(BLUR, edit_target="background"))
        self.assertNotIn("правка_видео", steps_of(d))
        self.assertEqual(9.0, clip_usd(d))

    def test_слова_ru(self) -> None:
        d = plan("Размыть фон в нашем интервью, как на светосильном объективе", BLUR)
        self.assertEqual(["удаление_фона_видео"], steps_of(d))
        self.assertIn("маск", str(step(d, "удаление_фона_видео").get("inferred")))

    def test_алиас(self) -> None:
        self.assertEqual(("blur-background",), _spec(w(BLUR, edit=["bokeh"])).edit)
        self.assertEqual(x17.EDIT_BLUR_BACKGROUND, bs.EDIT_BLUR_BACKGROUND)
        self.assertIn(x17.EDIT_BLUR_BACKGROUND, bs.EDIT_VALUES)

    def test_поле_старше_слов(self) -> None:
        self.assertFalse(x17.background_blur(_spec(w(BLUR, edit_target="person")), "bokeh behind him"))
        self.assertFalse(x17.background_blur(_spec(w(BLUR, edit=["stabilise"])), "and a bokeh background"))
        self.assertFalse(x17.background_blur(_spec(BLUR), "blur the faces of passers-by"))
        self.assertFalse(x17.background_blur(_spec(w(BLUR, task="dub-translate", languages=["es"])), "bokeh"))

    def test_записанные_маски(self) -> None:
        факты = {(f.model, f.attribute): f.value for f in load_facts()}
        self.assertTrue(факты[("robust-video-matting", "license")].startswith("gpl-3.0"))
        self.assertIn("cc-by-nc-4.0", факты[("video-depth-anything", "license")])


# --- the table ---------------------------------------------------------------------------------------


class Таблица(unittest.TestCase):
    def test_правила_с_источниками(self) -> None:
        ids = {р.id for р in cl.RULES_R17}
        self.assertEqual({"audio_description_track", "code_switching_speech", "provider_data_terms", "highlight_selection",
                          "standards_conversion", "stem_separation", "background_blur"}, ids)
        for р in cl.RULES_R17:
            self.assertTrue(р.sources, р.id)
            self.assertTrue(all(u.startswith("https://") for u in р.sources), р.id)

    def test_допущения_рецептов(self) -> None:
        for п in ("ad_gap_voice", "recap_short_vo", "matte_background_blur"):
            self.assertIn(п, rt.PRIORS)
        self.assertEqual(frozenset({"accessibility_package", "series_recap"}), x17.ROUTE_ORDER_RECIPES)

    def test_перевод_пометок(self) -> None:
        for ru, en in x17.NOTE_PAIRS:
            self.assertEqual(en, l10n.localise(ru, "en"))
        голос_ru, голос_en = x17.NOTE_AD_VOICE
        self.assertEqual(голос_en.format(share="15", n="540"), l10n.localise(голос_ru.format(share="15", n="540"), "en"))
        пересказ_ru, пересказ_en = x17.NOTE_RECAP_VO
        self.assertEqual(пересказ_en.format(n="90"), l10n.localise(пересказ_ru.format(n="90"), "en"))


if __name__ == "__main__":
    unittest.main()
