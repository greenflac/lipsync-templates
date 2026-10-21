"""Round 11: the engineering checklist, self-host pricing at API 0 usd, and the cheaper alternative over budget.

Every checklist rule gets a POSITIVE and a NEGATIVE case written for this file
(paraphrased briefs, EN and RU — never a dev or holdout brief). The rule is read
through `checklist.fire`, the same call `recipes.apply.note_ids` makes, so a
case states (spec, plan steps, brief words) -> fires / does not fire.

Decision constants are tested at their edges so that `scripts/mutate_round11.py`
turns each mutant red. Expected values are literals (T2); no network (T4).
"""

from __future__ import annotations

import json
import os
import unittest

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import l10n  # noqa: E402
from studio import planner  # noqa: E402
from studio.recipes import apply as ra  # noqa: E402
from studio.recipes import checklist as cl  # noqa: E402
from studio.recipes import table as rt  # noqa: E402


def _spec(raw: dict) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def _ids(raw: dict, steps: list[str], brief: str = "") -> list[str]:
    return [i for i, _ in cl.fire(_spec(raw), steps, text=brief)]


V = {"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 10, "people": []}
IMG = {"task": "generate", "inputs": [], "outputs": ["image"], "shots": 1, "people": []}
S = {"task": "generate", "inputs": [{"kind": "text", "owned": True}], "outputs": ["speech"], "duration_s": 30, "people": []}
M = {"task": "generate", "inputs": [], "outputs": ["music"], "duration_s": 60, "people": []}
PHOTO = [{"kind": "image", "owned": True}]
VID = [{"kind": "video", "owned": True, "duration_s": 20}]
AUD = [{"kind": "audio", "owned": True, "duration_s": 20}]
ME = {"name": "our CEO", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}
ACTOR = {"name": "the actor", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}


def w(base: dict, **more: object) -> dict:
    return {**base, **more}


#: rule id -> ((spec, steps, brief) that fires, (spec, steps, brief) that does not).
CASES: dict[str, tuple[tuple[dict, list[str], str], tuple[dict, list[str], str]]] = {
    "still_variants_seed": (
        (IMG, ["генерация_изображения"], "Обложка для подкаста, квадрат"),
        (V, ["генерация_видео"], "a 10 s clip of a city at night"),
    ),
    "still_anatomy_text_check": (
        (IMG, ["генерация_изображения"], "portrait of a smiling nurse for our clinic"),
        (IMG, ["генерация_изображения"], "минималистичный пейзаж горы на рассвете"),
    ),
    "product_fidelity": (
        (w(V, task="animate", inputs=PHOTO), ["оживление"], "animate our shampoo bottle product shot for a marketplace card"),
        (w(V, task="animate", inputs=PHOTO), ["оживление"], "оживи моё фото с моря"),
    ),
    "video_takes": (
        (V, ["генерация_видео"], "ролик про осенний лес"),
        (S, ["озвучка"], "read this script aloud"),
    ),
    "i2v_first_frame": (
        (w(V, task="animate", inputs=PHOTO), ["оживление"], "оживи старую открытку"),
        (V, ["генерация_видео"], "a fox running through snow"),
    ),
    "shot_continuity": (
        (w(V, shots=3, duration_s=24), ["генерация_видео"], "three scenes of a chef cooking"),
        (w(V, shots=1), ["генерация_видео"], "одна сцена с поваром"),
    ),
    "frame_rate_conform": (
        (w(V, inputs=PHOTO), ["оживление", "говорящий_аватар"], "an intro shot then a talking host"),
        (V, ["генерация_видео"], "one shot of rain"),
    ),
    "seamless_loop": (
        (V, ["генерация_видео"], "a seamless looping background of drifting clouds for our site"),
        (V, ["генерация_видео"], "облака с закатом в финале"),
    ),
    "logo_motion_vector": (
        (V, ["генерация_видео"], "анимируй наш логотип в заставке"),
        (V, ["генерация_видео"], "a drone shot over a forest"),
    ),
    "character_sheet": (
        (w(V, task="r2v", inputs=PHOTO), ["видео_по_референсу"], "the same hero in every episode"),
        (w(V, shots=1), ["генерация_видео"], "a waterfall"),
    ),
    "avatar_reference_photo": (
        (w(V, task="avatar", inputs=PHOTO + AUD), ["говорящий_аватар"], "make my photo talk"),
        (w(V, task="lipsync", inputs=VID + AUD), ["липсинк"], "sync my clip to the new voice"),
    ),
    "lipsync_face_crop": (
        (w(V, task="lipsync", inputs=VID + AUD), ["липсинк"], "подложи новый звук под губы"),
        (w(V, task="avatar", inputs=PHOTO + AUD), ["говорящий_аватар"], "talking photo"),
    ),
    "lipsync_hard_faces": (
        (w(V, task="lipsync", inputs=VID + AUD), ["липсинк"], "спикер снят в профиль и с бородой"),
        (w(V, task="lipsync", inputs=VID + AUD), ["липсинк"], "frontal webcam talk, good light"),
    ),
    "singing_vocal_stem": (
        (w(V, task="lipsync", inputs=VID + AUD), ["липсинк"], "сделай, чтобы губы попадали в песню"),
        (w(V, task="lipsync", inputs=VID + AUD), ["липсинк"], "replace the spoken line in my interview"),
    ),
    "slides_screen_real": (
        (w(V, task="avatar", inputs=PHOTO), ["говорящий_аватар"], "an avatar presenting our quarterly slides"),
        (w(V, task="avatar", inputs=PHOTO), ["говорящий_аватар"], "аватар приветствует покупателей"),
    ),
    "tts_pronunciation": (
        (S, ["озвучка"], "озвучь инструкцию"),
        (M, ["музыка"], "a calm piano bed"),
    ),
    "voice_casting": (
        (S, ["озвучка"], "диалог двух персонажей для аудиоспектакля"),
        (S, ["озвучка"], "one narrator reads the article"),
    ),
    "rtl_tts_diacritics": (
        (w(S, languages=["ar"]), ["озвучка"], "voice the welcome message"),
        (w(S, languages=["fr"]), ["озвучка"], "voice the welcome message"),
    ),
    "dub_time_fit": (
        (w(V, task="dub-translate", inputs=VID, languages=["de"]), ["дубляж"], "dub my course into German"),
        (S, ["озвучка"], "read the course text"),
    ),
    "dub_music_effects": (
        (w(V, task="dub-translate", inputs=VID, languages=["es"]), ["дубляж"], "переведи ролик на испанский"),
        (S, ["озвучка"], "озвучь текст"),
    ),
    "translation_review": (
        (w(S, languages=["en", "es"]), ["озвучка"], "the same promo in English and Spanish"),
        (w(S, languages=["en"]), ["озвучка"], "the promo in English"),
    ),
    "voice_clone_consent": (
        (w(S, task="voice-clone", inputs=AUD), ["клонирование_голоса"], "сделай клон моего голоса"),
        (S, ["озвучка"], "a stock voice is fine"),
    ),
    "voice_licence": (
        (S, ["озвучка"], "voice for an ad"),
        (IMG, ["генерация_изображения"], "a poster image"),
    ),
    "long_audio_chunks": (
        (w(S, duration_s=900), ["озвучка"], "аудиокнига, глава на 15 минут"),
        (w(S, duration_s=60), ["озвучка"], "a one-minute greeting"),
    ),
    "telephony_audio": (
        (S, ["озвучка"], "greeting for our IVR phone menu"),
        (S, ["озвучка"], "озвучка для ролика на ютуб"),
    ),
    "podcast_loudness": (
        (M, ["музыка"], "intro jingle for my podcast"),
        (M, ["музыка"], "музыка для трейлера игры"),
    ),
    "broadcast_loudness": (
        (V, ["генерация_видео"], "30 s TV spot for regional television"),
        (V, ["генерация_видео"], "30 s spot for Instagram"),
    ),
    "audio_mix_48k": (
        (w(V, outputs=["video", "speech"]), ["озвучка", "генерация_видео"], "explainer with a voice"),
        (V, ["генерация_видео"], "silent b-roll"),
    ),
    "audio_cleanup_chain": (
        ({"inputs": AUD, "outputs": ["speech"], "people": []}, [], "убрать шум и эхо с записи интервью"),
        ({"inputs": AUD, "outputs": ["speech"], "people": []}, [], "trim the first minute of my recording"),
    ),
    "music_to_length": (
        (M, ["музыка"], "фоновая музыка для ролика"),
        (S, ["озвучка"], "voice the ad"),
    ),
    "music_sections": (
        (w(M, duration_s=400), ["музыка"], "a long ambient track for a stream"),
        (w(M, duration_s=120), ["музыка"], "a two-minute track"),
    ),
    "music_master_loudness": (
        (M, ["музыка"], "a track for Spotify"),
        (IMG, ["генерация_изображения"], "album cover"),
    ),
    "sfx_layers": (
        (w(V, outputs=["sfx"]), ["звук_фон"], "шаги и скрип двери"),
        (M, ["музыка"], "a melody"),
    ),
    "sfx_sync_check": (
        (w(V, task=None, inputs=VID, outputs=["video", "sfx"]), ["звук_фон"], "add foley to my clip"),
        ({"task": "generate", "inputs": [], "outputs": ["sfx"], "duration_s": 5, "people": []}, ["звук_фон"], "a thunder sound"),
    ),
    "image_edit_masked": (
        (w(IMG, task="edit", inputs=PHOTO), ["редактирование_изображения"], "убери провода с фото"),
        (IMG, ["генерация_изображения"], "a new illustration"),
    ),
    "video_edit_temporal": (
        (w(V, task="video-edit", inputs=VID, edit=["remove-object"]), ["правка_видео"], "remove the boom mic from the shot"),
        (V, ["генерация_видео"], "новый ролик"),
    ),
    "face_swap_match": (
        (w(V, task="face-replace", inputs=VID + PHOTO, people=[ACTOR]), ["замена_персонажа"], "put my face on the stunt double"),
        (w(V, task="video-edit", inputs=VID, edit=["relight"]), ["правка_видео"], "relight the shot"),
    ),
    "restore_chain": (
        (w(V, task="restore", inputs=VID), ["реставрация"], "restore the old film"),
        (w(V, task="upscale", inputs=VID), ["апскейл"], "upscale to 4k"),
    ),
    "restore_grain": (
        (w(V, task="restore", inputs=VID), ["реставрация"], "restore my grandparents' wedding film"),
        (w(V, task="restore", inputs=VID), ["реставрация"], "clean up yesterday's phone clip"),
    ),
    "archival_ai_disclosure": (
        (w(V, task="colorize", inputs=VID), ["раскраска"], "раскрась хронику"),
        (w(V, task="restore", inputs=VID), ["реставрация"], "fix yesterday's drone clip"),
    ),
    "colorize_reference": (
        (w(IMG, task="colorize", inputs=PHOTO), ["раскраска_изображения"], "colourise this photo"),
        (w(V, task="restore", inputs=VID), ["реставрация"], "restore the clip"),
    ),
    "upscale_faithful": (
        (w(V, task="upscale", inputs=VID), ["апскейл"], "подними разрешение до 4K"),
        (w(V, task="interpolate", inputs=VID), ["интерполяция_кадров"], "make it 60 fps"),
    ),
    "interp_scene_cuts": (
        (w(V, task="interpolate", inputs=VID), ["интерполяция_кадров"], "smooth my edit to 60 fps"),
        (w(V, task="upscale", inputs=VID), ["апскейл"], "sharper please"),
    ),
    "interp_limited_animation": (
        (w(V, task="interpolate", inputs=VID), ["интерполяция_кадров"], "make our anime episode 60 fps"),
        (w(V, task="interpolate", inputs=VID), ["интерполяция_кадров"], "сделай мой скейт-ролик 60 к/с"),
    ),
    "cine_film_speed": (
        (w(V, task="restore", inputs=VID), ["реставрация"], "оцифрованная плёнка Super 8 из семейного архива"),
        (w(V, task="restore", inputs=VID), ["реставрация"], "a VHS wedding tape"),
    ),
    "vertical_safe_zone": (
        (w(V, aspect="9:16"), ["генерация_видео"], "вертикальный ролик"),
        (w(V, aspect="16:9"), ["генерация_видео"], "a widescreen clip"),
    ),
    "shorts_captions": (
        (w(V, task="cut-to-shorts", inputs=VID), [], "cut my stream into shorts"),
        (V, ["генерация_видео"], "a clip"),
    ),
    "captions_reading_speed": (
        (w(V, task="captions", inputs=VID), ["расшифровка"], "добавь субтитры"),
        (V, ["генерация_видео"], "no words"),
    ),
    "rtl_typesetting": (
        (w(V, task="captions", inputs=VID, languages=["he"]), ["расшифровка"], "Hebrew subtitles"),
        (w(V, task="captions", inputs=VID, languages=["de"]), ["расшифровка"], "German subtitles"),
    ),
    "cjk_typesetting": (
        (w(IMG, languages=["ja"]), ["генерация_изображения"], "poster for a Tokyo cafe"),
        (w(IMG, languages=["en"]), ["генерация_изображения"], "poster for a London cafe"),
    ),
    "platform_encode": (
        (V, ["генерация_видео"], "clip for our TikTok"),
        (V, ["генерация_видео"], "ролик для экрана в холле"),
    ),
    "hdr_delivery": (
        (V, ["генерация_видео"], "deliver in HDR10"),
        (V, ["генерация_видео"], "deliver SDR 1080p"),
    ),
    "eight_k_master": (
        (w(V, resolution="8k"), ["генерация_видео", "апскейл"], "8K showreel"),
        (w(V, resolution="4k"), ["генерация_видео"], "4K showreel"),
    ),
    "turntable_closes": (
        (w(V, task="turntable", inputs=PHOTO), ["оборот_360"], "spin the sneaker"),
        (V, ["генерация_видео"], "a street"),
    ),
    "reflective_surfaces": (
        (w(V, task="turntable", inputs=PHOTO), ["оборот_360"], "360 spin of our glass perfume bottle"),
        (w(V, task="turntable", inputs=PHOTO), ["оборот_360"], "оборот шерстяного свитера"),
    ),
    "mesh_cleanup": (
        (w(V, task="turntable", inputs=PHOTO), ["модель_3d"], "a GLB of the chair"),
        (w(V, task="turntable", inputs=PHOTO), ["оборот_360"], "a spin video"),
    ),
    "asr_review": (
        (w(S, task="transcribe", inputs=AUD, outputs=["text"]), ["расшифровка"], "transcribe the lecture"),
        (S, ["озвучка"], "voice it"),
    ),
    "diarization": (
        (w(S, task="transcribe", inputs=AUD, outputs=["text"]), ["расшифровка"], "расшифруй интервью"),
        (w(S, task="transcribe", inputs=AUD, outputs=["text"]), ["расшифровка"], "transcribe my voice memo"),
    ),
    "matte_edges": (
        (w(IMG, task="remove-background", inputs=PHOTO), ["удаление_фона"], "вырежи фон"),
        (IMG, ["генерация_изображения"], "a picture"),
    ),
    "self_host_gpu_time": (
        (w(V, self_host={"gpu": "RTX 4090", "vram_gb": 24}), ["генерация_видео"], "run it on my card"),
        (V, ["генерация_видео"], "any service is fine"),
    ),
    "low_vram": (
        (w(V, self_host={"gpu": "RTX 3060 Ti", "vram_gb": 8}), ["генерация_видео"], "на моей видеокарте"),
        (w(V, self_host={"gpu": "RTX 4090", "vram_gb": 24}), ["генерация_видео"], "on my card"),
    ),
    "edge_device": (
        (w(S, self_host={"gpu": "Jetson Orin Nano"}), ["озвучка"], "offline voice for a kiosk"),
        (w(S, self_host={"gpu": "RTX 4090", "vram_gb": 24}), ["озвучка"], "local voice"),
    ),
    "batch_queue": (
        (w(IMG, shots=40), ["генерация_изображения"], "40 product shots"),
        (w(IMG, shots=4), ["генерация_изображения"], "four product shots"),
    ),
    "synthetic_people_disclosure": (
        (w(V, task="avatar", inputs=PHOTO + AUD, people=[ME]), ["говорящий_аватар"], "our CEO announces the results"),
        (V, ["генерация_видео"], "an animated fox in the woods"),
    ),
    "made_for_kids": (
        (V, ["генерация_видео"], "мультик для детей про ёжика"),
        (V, ["генерация_видео"], "an explainer for accountants"),
    ),
}


class Таблица(unittest.TestCase):
    def test_не_меньше_60_правил_с_уникальными_id(self) -> None:
        self.assertGreaterEqual(len(cl.RULES_LIST), 60)
        self.assertEqual(len(cl.RULES_LIST), len(cl.RULES))
        self.assertFalse(set(cl.RULES) & set(rt.NOTES), "a checklist id shadows a round-9/10 note")

    def test_каждое_правило_с_двумя_языками_тегом_и_источником_нормы(self) -> None:
        поля = {"n": "2", "seconds": "600", "shots": "4", "langs": "ar, he", "vram": "8", "gpu": "Jetson", "fps": "25"}
        for р in cl.RULES_LIST:
            self.assertIn(р.tag, (rt.TAG_ENGINEERING, rt.TAG_REGULATION, rt.TAG_PLATFORM), р.id)
            if р.tag == rt.TAG_REGULATION:
                self.assertTrue(р.sources, р.id)
            for url in р.sources:
                self.assertTrue(url.startswith("https://"), р.id)
            self.assertEqual([], l10n.leaks({"says": р.ru.format(**поля)}, "ru"), р.id)
            self.assertEqual([], l10n.leaks({"says": р.en.format(**поля)}, "en"), р.id)

    def test_каждое_правило_проверено_в_обе_стороны(self) -> None:
        # Round-12 rules are cased in `test_checklist_r12`, round-13 in `test_round13_models`,
        # round-14 in `test_round14_models`, round-15 in `test_round15_knowledge`, round-16 in
        # `test_round16_spec` and `test_round16_knowledge`, round-17 in `test_round17_knowledge`.
        self.assertEqual(
            set(cl.RULES) - {р.id for р in cl.RULES_R12} - {р.id for р in cl.RULES_R13} - {р.id for р in cl.RULES_R14}
            - {р.id for р in cl.RULES_R15} - {р.id for р in cl.RULES_R16}
            # Round 17: the missing routes in `test_round17_routes`, the knowledge in `test_round17_knowledge`.
            - {р.id for р in cl.RULES_R17},
            set(CASES),
        )

    def test_поля_спецификации_к_добавлению_названы(self) -> None:
        поля = cl.spec_fields_to_add()
        self.assertIn("telephony_audio", поля["spec.delivery.platform = 'telephony'"])
        self.assertIn("made_for_kids", поля["spec.audience = 'children'"])

    def test_тег_площадки_по_русски(self) -> None:
        self.assertEqual("правило площадки", rt.TAG_RU[rt.TAG_PLATFORM])


class Правила(unittest.TestCase):
    def test_положительный_и_отрицательный_случай(self) -> None:
        for rid, (да, нет) in CASES.items():
            with self.subTest(rule=rid):
                self.assertIn(rid, _ids(*да))
                self.assertNotIn(rid, _ids(*нет))


class Пороги(unittest.TestCase):
    """Decision constants at their edges (mutants of `scripts/mutate_round11.py`)."""

    def test_длинный_звук(self) -> None:
        self.assertNotIn("long_audio_chunks", _ids(w(S, duration_s=300), ["озвучка"]))
        self.assertIn("long_audio_chunks", _ids(w(S, duration_s=301), ["озвучка"]))

    def test_длинная_музыка(self) -> None:
        self.assertNotIn("music_sections", _ids(w(M, duration_s=240), ["музыка"]))
        self.assertIn("music_sections", _ids(w(M, duration_s=241), ["музыка"]))

    def test_мало_видеопамяти(self) -> None:
        self.assertIn("low_vram", _ids(w(V, self_host={"gpu": "RTX 3060", "vram_gb": 12}), ["генерация_видео"]))
        self.assertNotIn("low_vram", _ids(w(V, self_host={"gpu": "RTX 4070 Ti", "vram_gb": 16}), ["генерация_видео"]))

    def test_пакет(self) -> None:
        self.assertIn("batch_queue", _ids(w(IMG, shots=20), ["генерация_изображения"]))
        self.assertNotIn("batch_queue", _ids(w(IMG, shots=19), ["генерация_изображения"]))

    def test_переходы_со_второго_шота(self) -> None:
        self.assertIn("shot_continuity", _ids(w(V, shots=2), ["генерация_видео"]))
        self.assertNotIn("shot_continuity", _ids(w(V, shots=1), ["генерация_видео"]))

    def test_серия_с_третьего_шота(self) -> None:
        people = [{"name": "Mia", "real": False}]
        self.assertIn("character_sheet", _ids(w(V, shots=3, people=people), ["генерация_видео"]))
        self.assertNotIn("character_sheet", _ids(w(V, shots=2, people=people), ["генерация_видео"]))

    def test_голоса_с_двух(self) -> None:
        двое = [{"name": "A", "real": False}, {"name": "B", "real": False}]
        self.assertIn("voice_casting", _ids(w(S, people=двое), ["озвучка"]))
        self.assertNotIn("voice_casting", _ids(w(S, people=двое[:1]), ["озвучка"]))

    def test_письмо_справа_налево_каждого_языка(self) -> None:
        for тег in ("ar", "he", "fa", "ur"):
            with self.subTest(тег=тег):
                self.assertIn("rtl_typesetting", _ids(w(IMG, languages=[тег]), ["генерация_изображения"]))
                self.assertIn("rtl_tts_diacritics", _ids(w(S, languages=[тег]), ["озвучка"]))
        self.assertNotIn("rtl_tts_diacritics", _ids(w(S, languages=["yi"]), ["озвучка"]))

    def test_cjk_каждого_языка(self) -> None:
        for тег in ("zh", "ja", "ko"):
            with self.subTest(тег=тег):
                self.assertIn("cjk_typesetting", _ids(w(IMG, languages=[тег]), ["генерация_изображения"]))
        self.assertNotIn("cjk_typesetting", _ids(w(IMG, languages=["vi"]), ["генерация_изображения"]))


class Уточнения(unittest.TestCase):
    def test_прозрачный_фон_не_стекло(self) -> None:
        raw = w(V, task="animate", inputs=PHOTO)
        self.assertNotIn("reflective_surfaces", _ids(raw, ["оживление"], "mascot on a transparent background"))
        self.assertNotIn("reflective_surfaces", _ids(raw, ["оживление"], "персонаж на прозрачном фоне"))
        self.assertIn("reflective_surfaces", _ids(raw, ["оживление"], "a transparent glass vase"))

    def test_логотип_уже_наложен_рецептом(self) -> None:
        spec = _spec(V)
        self.assertIn("logo_motion_vector", [i for i, _ in cl.fire(spec, ["генерация_видео"], "logo intro")])
        self.assertNotIn(
            "logo_motion_vector", [i for i, _ in cl.fire(spec, ["генерация_видео"], "logo intro", priors=["logo_overlay"])]
        )

    def test_3d_вместо_оборота_без_ноты_оборота(self) -> None:
        raw = w(V, task="turntable", inputs=PHOTO)
        self.assertNotIn("turntable_closes", _ids(raw, ["модель_3d"]))
        self.assertIn("turntable_closes", _ids(raw, ["оборот_360"]))

    def test_правила_условий_раньше_общих(self) -> None:
        ids = _ids(w(S, languages=["ar"]), ["озвучка"], "IVR greeting")
        self.assertLess(ids.index("telephony_audio"), ids.index("voice_licence"))
        self.assertLess(ids.index("rtl_tts_diacritics"), ids.index("voice_licence"))


class Потолок(unittest.TestCase):
    def test_объявление_обрезки_входит_в_потолок(self) -> None:
        from studio.mcp import server as S

        payload = {"note": "n", **{f"list{i:02d}": ["x" * 100] * 20 for i in range(30)}}
        out = S.cap_response(payload, limit=8_000, tool="plan_pipeline")
        self.assertLessEqual(len(out), 8_000)
        self.assertIn("8000-character cap", json.loads(out)["note"])


class Заметки(unittest.TestCase):
    def test_правила_доходят_до_production_notes_на_языке_ответа(self) -> None:
        spec = _spec(w(S, languages=["ar"]))
        en = {з["id"]: з for з in ra.notes(spec, ["озвучка"], english=True, text="IVR greeting")}
        ru = {з["id"]: з for з in ra.notes(spec, ["озвучка"], english=False, text="IVR greeting")}
        self.assertIn("8 kHz mono", en["telephony_audio"]["says"])
        self.assertEqual("platform policy", en["telephony_audio"]["tag"])
        self.assertEqual([{"url": "https://www.itu.int/rec/T-REC-G.711"}], en["telephony_audio"]["sources"])
        self.assertIn("8 кГц моно", ru["telephony_audio"]["says"])
        self.assertEqual("правило площадки", ru["telephony_audio"]["tag"])
        self.assertTrue(en["rtl_tts_diacritics"]["says"].startswith("ar: "))


# --- self-host: API 0 usd, GPU time as an estimate; over budget: a cheaper alternative ---


def _plan(brief: str, spec: dict) -> dict:
    from studio.mcp import server

    return json.loads(server.plan_pipeline(brief, spec=spec))


class СвоёЖелезо(unittest.TestCase):
    def test_свой_gpu_без_записанного_времени_цена_0_и_вердикт(self) -> None:
        d = _plan(
            "Lip-sync a 90 s interview to a new English track on our own RTX 6000 Ada, no money to spend",
            {"task": "lipsync", "inputs": [{"kind": "video", "owned": True, "duration_s": 90}, {"kind": "audio", "owned": True, "duration_s": 90}], "outputs": ["video"], "duration_s": 90, "languages": ["en"], "budget": {"amount": 0, "currency": "USD"}, "self_host": {"gpu": "RTX 6000 Ada", "vram_gb": 48}, "open_weights": True, "people": [ACTOR]},
        )
        self.assertEqual({"usd": 0.0}, d["pipeline_price"]["за_ролик"])
        self.assertEqual([], d["pipeline_price"]["steps_without_price"])
        self.assertEqual("pass", d["budget"]["outcome"])
        self.assertIn("API 0 usd", d["pipeline_price"]["note"])
        self.assertIn("self_host_gpu_time", [з["id"] for з in d["production_notes"]])

    def test_время_gpu_оценкой_рядом_с_ценой_0(self) -> None:
        d = _plan(
            "Сгенерируй 5 секунд 720p волн на своей RTX 4090, открытые веса",
            {"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 5, "resolution": "720p", "self_host": {"gpu": "RTX 4090", "vram_gb": 24}, "open_weights": True, "people": []},
        )
        self.assertEqual({"usd": 0.0}, d["pipeline_price"]["за_ролик"])
        note = d["pipeline_price"]["note"]
        self.assertIn("API 0 usd", note)
        self.assertIn("ОЦЕНКА", note)
        self.assertIn("на арендованном GPU тот же прогон стоил бы", note)

    def test_ничья_своего_gpu_решается_арендой(self) -> None:
        a = planner.Candidate(model="a", evidence=(), applicability=0, capability=0, unresolved=0, price="", gpu_rent_usd=0.5)
        b = planner.Candidate(model="b", evidence=(), applicability=0, capability=0, unresolved=0, price="", gpu_rent_usd=0.1)
        c = planner.Candidate(model="c", evidence=(), applicability=0, capability=0, unresolved=0, price="")
        self.assertEqual([(0, 0.1), (0, 0.5), (1, 0.0)], sorted(planner.цена_ничьей(x) for x in (a, b, c)))
        self.assertTrue(planner.цена_есть(a))
        self.assertFalse(planner.цена_есть(c))


class ДешевлеПотолка(unittest.TestCase):
    def test_дороже_потолка_называет_вариант(self) -> None:
        d = _plan(
            "A 30 second 1080p promo with a voice-over for 40 cents",
            {"task": "generate", "inputs": [], "outputs": ["video", "speech"], "duration_s": 30, "resolution": "1080p", "languages": ["en"], "budget": {"amount": 0.4, "currency": "USD"}, "people": []},
        )
        self.assertEqual("дороже_потолка", d["reason"])
        варианты = d["budget"]["cheaper_alternatives"]
        self.assertIn("cheapest_models", [в["kind"] for в in варианты])
        self.assertIn("Cheaper alternatives: (1) ", d["что_дальше"])

    def test_короче_по_доле(self) -> None:
        цена = {"over_ceiling": {"least_known_usd": 100.0, "ceiling_usd": 25.0}}
        out = planner.дешевле_варианты([], {}, цена, 100.0, None, True)
        self.assertEqual([("shorter", 25)], [(в["kind"], в["seconds"]) for в in out])
        цена = {"over_ceiling": {"least_known_usd": 100.0, "ceiling_usd": 24.0}}
        self.assertEqual([], planner.дешевле_варианты([], {}, цена, 100.0, None, True))

    def test_без_превышения_вариантов_нет(self) -> None:
        self.assertEqual([], planner.дешевле_варианты([], {}, {}, 30.0, None, False))


if __name__ == "__main__":
    unittest.main()
