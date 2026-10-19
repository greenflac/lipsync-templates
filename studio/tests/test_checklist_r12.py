"""Round 12: the long tail of the engineering checklist, and self-host on non-NVIDIA GPUs.

Every round-12 rule gets a POSITIVE and a NEGATIVE case written for this file
(paraphrased briefs, EN and RU — never a dev or holdout brief), read through
`checklist.fire`, the call `recipes.apply.note_ids` makes. Decision constants
are tested at their edges so that `scripts/mutate_round12.py` turns each mutant
red. Expected values are literals (T2); no network (T4).
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import hardneed as hn  # noqa: E402
from studio import l10n  # noqa: E402
from studio import planner  # noqa: E402
from studio.recipes import apply as ra  # noqa: E402
from studio.recipes import checklist as cl  # noqa: E402
from studio.recipes import table as rt  # noqa: E402
from studio.selfrag.facts import Fact  # noqa: E402


def _spec(raw: dict) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def _ids(raw: dict, steps: list[str], brief: str = "") -> list[str]:
    return [i for i, _ in cl.fire(_spec(raw), steps, text=brief)]


V = {"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 10, "people": []}
VS = {"task": "generate", "inputs": [], "outputs": ["video", "speech"], "duration_s": 30, "people": []}
IMG = {"task": "generate", "inputs": [], "outputs": ["image"], "shots": 1, "people": []}
S = {"task": "generate", "inputs": [{"kind": "text", "owned": True}], "outputs": ["speech"], "duration_s": 30, "people": []}
M = {"task": "generate", "inputs": [], "outputs": ["music"], "duration_s": 60, "people": []}
FX = {"task": "generate", "inputs": [], "outputs": ["sfx"], "duration_s": 5, "people": []}
PHOTO = [{"kind": "image", "owned": True}]
VID = [{"kind": "video", "owned": True, "duration_s": 20}]
GEN_V = ["генерация_видео"]
GEN_I = ["генерация_изображения"]
TTS = ["озвучка"]
MUS = ["музыка"]


def w(base: dict, **more: object) -> dict:
    return {**base, **more}


def person(**more: object) -> dict:
    return {"name": "X", "real": True, "public_figure": False, "consent": "stated", "claim": "none", **more}


#: rule id -> ((spec, steps, brief) that fires, (spec, steps, brief) that does not).
CASES: dict[str, tuple[tuple[dict, list[str], str], tuple[dict, list[str], str]]] = {
    "dcp_master": (
        (V, GEN_V, "a 60 s spot to run before features in cinemas"),
        (V, GEN_V, "a 60 s spot for our website"),
    ),
    "dcp_frame_rate": (
        (w(V, fps=25), GEN_V, "ролик для показа в кинотеатре"),
        (w(V, fps=24), GEN_V, "ролик для показа в кинотеатре"),
    ),
    "cinema_sound_reference": (
        (VS, ["генерация_видео", "озвучка"], "short film for a film festival screening"),
        (VS, ["генерация_видео", "озвучка"], "short film for Vimeo"),
    ),
    "cinema_big_screen_check": (
        (V, GEN_V, "трейлер для кинопрокат"),
        (w(S), TTS, "голос для трейлера в кинотеатре"),
    ),
    "broadcast_legal_range": (
        (V, GEN_V, "a 20 s spot for regional television"),
        (V, GEN_V, "a 20 s spot for our homepage hero"),
    ),
    "broadcast_closed_captions": (
        (VS, ["генерация_видео", "озвучка"], "explainer to air on a TV channel with a narrator"),
        (V, GEN_V, "silent ident to air on a TV channel"),
    ),
    "broadcast_safe_areas": (
        (V, GEN_V, "заставка для телеканала"),
        (V, GEN_V, "заставка для презентации"),
    ),
    "broadcast_frame_rate": (
        (V, GEN_V, "TV commercial for a US network"),
        (w(V, task="upscale", inputs=VID), ["апскейл"], "upscale our old TV commercial"),
    ),
    "streaming_imf_delivery": (
        (V, GEN_V, "title sequence for a Netflix series"),
        (V, GEN_V, "title sequence for a student film"),
    ),
    "streaming_dialogue_loudness": (
        (VS, ["генерация_видео", "озвучка"], "эпизод для Кинопоиска"),
        (VS, ["генерация_видео", "озвучка"], "эпизод для школьного проекта"),
    ),
    "streaming_genai_approval": (
        (V, GEN_V, "VFX shot for a Prime Video original"),
        (V, GEN_V, "VFX shot for a music video"),
    ),
    "me_stems_delivery": (
        (w(V, task="dub-translate", inputs=VID, languages=["fr"]), ["дубляж"], "dub the trailer into French"),
        (w(VS, languages=["en"]), ["генерация_видео", "озвучка"], "explainer in English"),
    ),
    "forced_narratives": (
        (w(V, task="dub-translate", inputs=VID, languages=["it"]), ["дубляж"], "переведи фильм на итальянский"),
        (w(V, task="captions", inputs=VID), ["расшифровка"], "subtitle the film"),
    ),
    "anime_on_twos_output": (
        (V, GEN_V, "a 10 s anime opening shot"),
        (V, GEN_V, "a 10 s photoreal drone shot"),
    ),
    "anime_upscaler": (
        (w(V, task="upscale", inputs=VID), ["апскейл"], "upscale our old cartoon episode"),
        (w(V, task="upscale", inputs=VID), ["апскейл"], "upscale our wedding video"),
    ),
    "script_text_overlay": (
        (w(IMG, languages=["ru"]), GEN_I, "постер с заголовком «Летняя распродажа»"),
        (w(IMG, languages=["ru"]), GEN_I, "постер с летним пейзажем"),
    ),
    "indic_shaping": (
        (w(V, task="captions", inputs=VID, languages=["hi"]), ["расшифровка"], "Hindi subtitles"),
        (w(V, task="captions", inputs=VID, languages=["es"]), ["расшифровка"], "Spanish subtitles"),
    ),
    "sea_line_break": (
        (w(V, task="captions", inputs=VID, languages=["th"]), ["расшифровка"], "субтитры на тайском"),
        (w(V, task="captions", inputs=VID, languages=["vi"]), ["расшифровка"], "субтитры на вьетнамском"),
    ),
    "cyrillic_locl": (
        (w(IMG, languages=["bg"]), GEN_I, "Bulgarian poster"),
        (w(IMG, languages=["uk"]), GEN_I, "Ukrainian poster"),
    ),
    "virtual_staging_disclosure": (
        (w(IMG, task="edit", inputs=PHOTO), ["редактирование_изображения"], "virtually stage the empty living room for our listing"),
        (w(IMG, task="edit", inputs=PHOTO), ["редактирование_изображения"], "add a sofa to my game concept art"),
    ),
    "real_estate_permanent_features": (
        (w(IMG, task="edit", inputs=PHOTO), ["редактирование_изображения"], "обставь пустую квартиру на продажу для объявления"),
        (w(IMG, task="edit", inputs=PHOTO), ["редактирование_изображения"], "обставь комнату в моей игре"),
    ),
    "retouch_label_france": (
        (w(IMG, task="edit", inputs=PHOTO), ["редактирование_изображения"], "retouch the model slimmer for our French billboard campaign"),
        (w(IMG, task="edit", inputs=PHOTO), ["редактирование_изображения"], "retouch the model slimmer for our German billboard campaign"),
    ),
    "cosmetic_ad_effect": (
        (IMG, GEN_I, "реклама крема от морщин с идеальной кожей"),
        (IMG, GEN_I, "портрет бабушки для семейного альбома"),
    ),
    "before_after_genuine": (
        (IMG, GEN_I, "before and after shots for our teeth whitening"),
        (IMG, GEN_I, "a shot of our teeth whitening kit"),
    ),
    "political_ai_disclosure": (
        (w(V, people=[person(claim="political")]), GEN_V, "a 15 s spot"),
        (w(V, people=[person()]), GEN_V, "a 15 s spot"),
    ),
    "political_paid_for_by": (
        (w(V, jurisdiction="US"), GEN_V, "an election ad for a city council candidate"),
        (w(V, jurisdiction="EU"), GEN_V, "an election ad for a city council candidate"),
    ),
    "fcc_ai_voice_robocall": (
        (S, TTS, "outbound phone calls reminding customers of payments"),
        (S, TTS, "IVR phone menu greeting"),
    ),
    "voice_bot_disclosure": (
        (S, TTS, "голосовой ассистент для колл-центра"),
        (S, TTS, "приветствие для ролика"),
    ),
    "backend_rocm": (
        (w(V, self_host={"gpu": "Radeon RX 7900 XTX", "vram_gb": 24}), GEN_V, "run it on my card"),
        (w(V, self_host={"gpu": "RTX 4090", "vram_gb": 24}), GEN_V, "run it on my card"),
    ),
    "backend_intel_xpu": (
        (w(IMG, self_host={"gpu": "Intel Arc A770", "vram_gb": 16}), GEN_I, "локально"),
        (w(IMG, self_host={"gpu": "Radeon RX 7900 XTX", "vram_gb": 24}), GEN_I, "локально"),
    ),
    "backend_apple_mps": (
        (w(IMG, self_host={"gpu": "M3 Max", "unified_memory_gb": 64}), GEN_I, "on my Mac"),
        (w(IMG, self_host={"gpu": "RTX 3090", "vram_gb": 24}), GEN_I, "on my PC"),
    ),
    "game_audio_variations": (
        (FX, ["звук_фон"], "footstep sounds for our indie game"),
        (FX, ["звук_фон"], "footstep sounds for a radio drama"),
    ),
    "game_music_layers": (
        (M, MUS, "музыка для нашей игры, уровень в лесу"),
        (M, MUS, "музыка для свадебного ролика"),
    ),
    "acx_audio_specs": (
        (w(S, duration_s=200), TTS, "narrate chapter one of my audiobook"),
        (w(S, duration_s=200), TTS, "narrate my blog post"),
    ),
    "audiobook_ai_narration": (
        (S, TTS, "озвучь аудиокнигу целиком"),
        (S, TTS, "озвучь рекламу"),
    ),
    "podcast_artwork_metadata": (
        (M, MUS, "intro music for my podcast"),
        (M, MUS, "intro music for my stream"),
    ),
    "podcast_ai_disclosure": (
        (S, TTS, "AI host voice for a weekly podcast"),
        (M, MUS, "a jingle for a weekly podcast"),
    ),
    "music_release_metadata": (
        (M, MUS, "a single I want to release on Spotify via DistroKid"),
        (M, MUS, "a background bed for my vlog"),
    ),
    "ai_music_distribution": (
        (M, MUS, "трек, который хочу выпустить трек через дистрибуцию"),
        (S, TTS, "дистрибуция аудиоролика"),
    ),
    "music_content_id": (
        (M, MUS, "theme for my channel, I want to monetise it"),
        (M, MUS, "theme for my wedding"),
    ),
    "stock_licence_scope": (
        (V, GEN_V, "mix our clip with stock footage from Shutterstock"),
        (V, GEN_V, "sell these clips on Shutterstock"),
    ),
    "stock_ai_submission": (
        (IMG, GEN_I, "images to sell on Adobe Stock"),
        (IMG, GEN_I, "images for our blog"),
    ),
    "print_cmyk_bleed": (
        (IMG, GEN_I, "A4 flyer for print"),
        (IMG, GEN_I, "Instagram post"),
    ),
    "print_vector_text": (
        (IMG, GEN_I, "печатный плакат А3 с заголовком"),
        (IMG, GEN_I, "печатный плакат А3 с горным пейзажем"),
    ),
    "short_form_length_cap": (
        (w(V, aspect="9:16", duration_s=240), GEN_V, "vertical video for YouTube Shorts"),
        (w(V, aspect="9:16", duration_s=180), GEN_V, "vertical video for YouTube Shorts"),
    ),
    "platform_thumbnail": (
        (V, GEN_V, "YouTube video plus its thumbnail"),
        (V, GEN_V, "YouTube video"),
    ),
    "social_commercial_music": (
        (w(V, outputs=["video", "music"]), ["генерация_видео", "музыка"], "TikTok ad for our sneakers with music"),
        (w(V, outputs=["video", "music"]), ["генерация_видео", "музыка"], "TikTok dance clip for my friends"),
    ),
    "branded_content_disclosure": (
        (V, GEN_V, "ролик для интеграции у блогера"),
        (V, GEN_V, "ролик для личного архива"),
    ),
    "marketplace_main_image": (
        (w(IMG, inputs=PHOTO), GEN_I, "main image of our product for an Amazon listing"),
        (w(IMG, inputs=PHOTO), GEN_I, "main image of our product for a magazine"),
    ),
    "wcag_captions": (
        (VS, ["генерация_видео", "озвучка"], "training video for a government agency site"),
        (VS, ["генерация_видео", "озвучка"], "training video for our sales team"),
    ),
    "audio_description": (
        (VS, ["генерация_видео", "озвучка"], "ролик, доступный для незрячих зрителей"),
        (VS, ["генерация_видео", "озвучка"], "ролик для отдела продаж"),
    ),
    "photosensitive_flashes": (
        (V, GEN_V, "music visual with strobe lights and glitch cuts"),
        (V, GEN_V, "calm music visual with drifting clouds"),
    ),
    "deceased_likeness": (
        (w(V, task="avatar", inputs=PHOTO, people=[person(deceased=True)]), ["говорящий_аватар"], "make my late grandfather speak"),
        (w(V, task="avatar", inputs=PHOTO, people=[person()]), ["говорящий_аватар"], "make me speak"),
    ),
    "minor_on_screen": (
        (w(V, task="animate", inputs=PHOTO, people=[person(minor=True)]), ["оживление"], "animate my son's photo"),
        (w(V, task="animate", inputs=PHOTO, people=[person()]), ["оживление"], "animate my photo"),
    ),
    "fake_endorsement": (
        (w(V, people=[person(claim="endorsement")]), GEN_V, "our trainer recommends the protein bar"),
        (w(V, people=[person()]), GEN_V, "our trainer shows a workout"),
    ),
    "voice_publicity_rights": (
        (w(S, people=[person(public_figure=True)]), TTS, "a famous singer reads our greeting"),
        (w(S, people=[person()]), TTS, "our manager reads our greeting"),
    ),
    "news_synthetic_label": (
        (V, GEN_V, "reconstruction of the flood for the evening news"),
        (V, GEN_V, "flood scene for a disaster movie pitch"),
    ),
    "china_ai_label": (
        (w(V, jurisdiction="CN"), GEN_V, "promo for a Shanghai launch"),
        (w(V, jurisdiction="JP"), GEN_V, "promo for a Tokyo launch"),
    ),
    "vfx_plate_handoff": (
        (V, GEN_V, "background plates for compositing in Nuke"),
        (V, GEN_V, "background clip for our website"),
    ),
    "editorial_handoff": (
        (V, GEN_V, "b-roll that our editor will cut in Premiere Pro"),
        (V, GEN_V, "b-roll for a quick post"),
    ),
    "health_ad_claims": (
        (V, GEN_V, "реклама БАД с врачом в кадре"),
        (V, GEN_V, "сериал про врача, сцена в больнице"),
    ),
    "financial_promo": (
        (V, GEN_V, "ad for our crypto trading app"),
        (V, GEN_V, "ad for our bakery"),
    ),
    "app_preview_specs": (
        (V, GEN_V, "app preview video for the App Store"),
        (V, GEN_V, "promo video for our cafe"),
    ),
}


class Таблица(unittest.TestCase):
    def test_не_меньше_60_новых_правил(self) -> None:
        self.assertGreaterEqual(len(cl.RULES_R12), 60)
        self.assertEqual(len(cl.RULES_LIST), len(cl.RULES))
        self.assertFalse(set(cl.RULES) & set(rt.NOTES))

    def test_каждое_новое_правило_проверено_в_обе_стороны(self) -> None:
        self.assertEqual({р.id for р in cl.RULES_R12}, set(CASES))

    def test_два_языка_тег_и_источник(self) -> None:
        поля = {"n": "2", "seconds": "600", "shots": "4", "langs": "hi", "vram": "8", "gpu": "RX 7900", "fps": "25"}
        for р in cl.RULES_R12:
            with self.subTest(rule=р.id):
                self.assertIn(р.tag, (rt.TAG_ENGINEERING, rt.TAG_REGULATION, rt.TAG_PLATFORM))
                if р.tag != rt.TAG_ENGINEERING:
                    self.assertTrue(р.sources)
                for url in р.sources:
                    self.assertTrue(url.startswith("https://"))
                self.assertEqual([], l10n.leaks({"says": р.ru.format(**поля)}, "ru"))
                self.assertEqual([], l10n.leaks({"says": р.en.format(**поля)}, "en"))


class Правила(unittest.TestCase):
    def test_положительный_и_отрицательный_случай(self) -> None:
        for rid, (да, нет) in CASES.items():
            with self.subTest(rule=rid):
                self.assertIn(rid, _ids(*да))
                self.assertNotIn(rid, _ids(*нет))


class Пороги(unittest.TestCase):
    """Decision constants at their edges (mutants of `scripts/mutate_round12.py`)."""

    def test_письменности_с_подменой_букв(self) -> None:
        for тег in ("ru", "el", "hy", "ka", "kk"):
            with self.subTest(тег=тег):
                self.assertIn("script_text_overlay", _ids(w(IMG, languages=[тег]), GEN_I, "poster with a headline"))
        self.assertNotIn("script_text_overlay", _ids(w(IMG, languages=["de"]), GEN_I, "poster with a headline"))

    def test_брахмические(self) -> None:
        for тег in ("hi", "bn", "ta", "te"):
            with self.subTest(тег=тег):
                self.assertIn("indic_shaping", _ids(w(IMG, languages=[тег]), GEN_I))
        self.assertNotIn("indic_shaping", _ids(w(IMG, languages=["ur"]), GEN_I))

    def test_без_пробелов(self) -> None:
        for тег in ("th", "lo", "km", "my"):
            with self.subTest(тег=тег):
                self.assertIn("sea_line_break", _ids(w(IMG, languages=[тег]), GEN_I))
        self.assertNotIn("sea_line_break", _ids(w(IMG, languages=["id"]), GEN_I))

    def test_локальные_формы(self) -> None:
        for тег in ("bg", "sr", "mk"):
            with self.subTest(тег=тег):
                self.assertIn("cyrillic_locl", _ids(w(IMG, languages=[тег]), GEN_I))
        self.assertNotIn("cyrillic_locl", _ids(w(IMG, languages=["ru"]), GEN_I))

    def test_частоты_dcp(self) -> None:
        for fps in (24, 48):
            self.assertNotIn("dcp_frame_rate", _ids(w(V, fps=fps), GEN_V, "for cinemas"))
        for fps in (25, 30, 50):
            self.assertIn("dcp_frame_rate", _ids(w(V, fps=fps), GEN_V, "for cinemas"))

    def test_три_минуты_коротких_видео(self) -> None:
        raw = w(V, aspect="9:16")
        self.assertNotIn("short_form_length_cap", _ids(w(raw, duration_s=180), GEN_V, "for Reels"))
        self.assertIn("short_form_length_cap", _ids(w(raw, duration_s=181), GEN_V, "for Reels"))

    def test_платформы_не_nvidia(self) -> None:
        self.assertEqual(frozenset({"rocm", "xpu", "apple-silicon"}), cl.NON_NVIDIA_PLATFORMS)


class НеNvidia(unittest.TestCase):
    """Self-host on AMD ROCm / Intel XPU: the backend is read, carried and ranks candidates."""

    def test_бэкенд_по_имени_карты(self) -> None:
        self.assertEqual("rocm", hn.gpu_backend("Radeon RX 7900 XTX"))
        self.assertEqual("rocm", hn.gpu_backend("Instinct MI300X"))
        self.assertEqual("xpu", hn.gpu_backend("Intel Arc B580"))
        self.assertEqual("", hn.gpu_backend("RTX 4090"))
        self.assertEqual("", hn.gpu_backend("Apple M2 Pro"))

    def test_имя_карты_и_память(self) -> None:
        h = hn.from_brief("self-host it on my Radeon RX 7900 XTX")
        self.assertEqual(("rx-7900-xtx", 24.0, "rocm", True), (h.gpu, h.vram_gb, h.gpu_backend, h.self_host))
        h = hn.from_brief("локально на Intel Arc A770")
        self.assertEqual(("arc-a770", 16.0, "xpu"), (h.gpu, h.vram_gb, h.gpu_backend))
        h = hn.from_brief("on one RTX 4090")
        self.assertEqual(("rtx-4090", ""), (h.gpu, h.gpu_backend))
        self.assertEqual("", hn.from_brief("an AMD-sponsored esports trailer").gpu_backend)

    def test_spec_несёт_платформу_и_жёсткое(self) -> None:
        spec = _spec({"self_host": {"gpu": "Radeon RX 7800 XT", "vram_gb": 16}})
        self.assertEqual("rocm", spec.self_host["platform"])
        self.assertEqual("rocm", bs.hard(spec, "").gpu_backend)
        spec = _spec({"self_host": {"gpu": "RTX 4080", "vram_gb": 16}})
        self.assertNotIn("platform", spec.self_host)
        self.assertEqual("", bs.hard(spec, "").gpu_backend)

    def test_состояние_бэкенда(self) -> None:
        да = Fact("m", "rocm_inference", "yes — via ComfyUI", "https://x.example/a", "blog", "2026-10-19")
        нет = Fact("m", "rocm_inference", "no — CUDA only", "https://x.example/b", "blog", "2026-10-19")
        чужой = Fact("m", "intel_xpu_inference", "yes — xpu", "https://x.example/c", "blog", "2026-10-19")
        self.assertEqual(hn.BACKEND_YES, hn.backend_state([да], "rocm")[0])
        self.assertEqual(hn.BACKEND_NO, hn.backend_state([нет], "rocm")[0])
        self.assertEqual(hn.BACKEND_UNKNOWN, hn.backend_state([чужой], "rocm")[0])
        self.assertEqual(hn.BACKEND_YES, hn.backend_state([чужой], "xpu")[0])
        self.assertLess(hn.BACKEND_ORDER[hn.BACKEND_YES], hn.BACKEND_ORDER[hn.BACKEND_UNKNOWN])
        self.assertLess(hn.BACKEND_ORDER[hn.BACKEND_UNKNOWN], hn.BACKEND_ORDER[hn.BACKEND_NO])

    def test_строка_шага_о_бэкенде(self) -> None:
        да = Fact("m", "rocm_inference", "yes — via ComfyUI", "https://x.example/a", "blog", "2026-10-19")
        self.assertTrue(planner.поддержка_бэкенда("m", [да], "rocm").startswith("recorded (AMD ROCm)"))
        self.assertTrue(planner.поддержка_бэкенда("m", [да], "xpu").startswith("unmeasured"))

    def test_нота_доходит_до_production_notes(self) -> None:
        spec = _spec(w(IMG, self_host={"gpu": "Radeon RX 7900 XTX", "vram_gb": 24}))
        en = {з["id"]: з for з in ra.notes(spec, GEN_I, english=True)}
        ru = {з["id"]: з for з in ra.notes(spec, GEN_I, english=False)}
        self.assertIn("AMD GPU (Radeon RX 7900 XTX)", en["backend_rocm"]["says"])
        self.assertIn("GPU AMD (Radeon RX 7900 XTX)", ru["backend_rocm"]["says"])


if __name__ == "__main__":
    unittest.main()
