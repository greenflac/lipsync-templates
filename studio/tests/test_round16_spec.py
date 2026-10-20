"""Round 16 (spec first, the rest): every decision round 15 left to EN/RU words reads its SPEC FIELD first.

Round 15 moved the round 13-14 decisions to spec fields and listed what stayed words-only
(`checklist.spec_fields_to_add()`, the recipe words of `studio/recipes/apply.py`, the
planner's community words). The round-16 hidden set failed exactly there: a halftone scan
in Spanish got no descreen note, passers-by anonymised in German got no model and no GDPR
note, a witness whose voice had to be unrecognisable was planned as a DUB (a dubbing
endpoint keeps the timbre), a documentary face swap got no model and no price, a cut into
shorts with no voice-over got no no-speech note.

Each decision is guarded three ways:

(a) the spec field ALONE decides, with a brief in zh / ja / ko / es / pt / de / fr / it / tr / ar
    that the keyword lists do not cover;
(b) the field wins over contradicting words, both ways (a named "no" silences EN words that
    would fire; a named "yes" fires on a brief whose words say nothing);
(c) with the field absent, the EN / RU words still decide — and the same foreign brief without
    the field does NOT (the gap the field closes).

The briefs are the fixer's own; none is a dev or holdout id. Expected values are literals (T2).
"""

from __future__ import annotations

import json
import os
import re
import unittest
from typing import Any

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import anonymise as an  # noqa: E402
from studio import brief_spec as bs  # noqa: E402
from studio import expert_r15 as x15  # noqa: E402
from studio import planner as pn  # noqa: E402
from studio import spec_first as sf  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import apply as rc  # noqa: E402
from studio.recipes import checklist as cl  # noqa: E402
from studio.recipes import delivery  # noqa: E402

V = {"kind": "video", "owned": True, "duration_s": 20}
A = {"kind": "audio", "owned": True, "duration_s": 60}
I = {"kind": "image", "owned": True}


def _spec(**raw: Any) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def _fired(brief: str, steps: list[str] | tuple[str, ...], raw: dict) -> set[str]:
    return {i for i, _ in cl.fire(_spec(**raw), list(steps), text=brief)}


def _route(brief: str, **raw: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(steps after the recipes, assembly lines in Russian) — the planner's own route + rewrite."""
    spec = bs.with_defaults(_spec(**raw), ролик=True, текст=brief)
    applied = rc.rewrite(spec, bs.route(spec), brief)
    return applied.route.шаги, tuple(ru for ru, _ in applied.assembly)


_PLANS: dict[str, dict] = {}


def _plan(brief: str, **spec: Any) -> dict:
    key = brief + json.dumps(spec, sort_keys=True, ensure_ascii=False)
    if key not in _PLANS:
        _PLANS[key] = json.loads(server.plan_pipeline(brief, spec=dict(spec)))
    return _PLANS[key]


def _note_ids(answer: dict) -> list[str]:
    return [n.get("id") for n in answer.get("production_notes") or []]


def _chosen(answer: dict) -> dict[str, tuple[str | None, bool]]:
    """step -> (chosen model, priced)."""
    out: dict[str, tuple[str | None, bool]] = {}
    for s in answer.get("steps") or []:
        ch = s.get("chosen") or {}
        out[s["step"]] = (ch.get("model"), bool(ch.get("price")) and "no price" not in str(ch.get("price")))
    return out


# --- 0. the fields themselves -------------------------------------------------------------------


class ПоляРазбираются(unittest.TestCase):
    def test_значения(self) -> None:
        spec = _spec(
            anonymise={"voice": True, "method": ["blur", "voice-replace"]}, voiceover=False,
            delivery={"platform": "podcast", "dynamic_range": "hdr", "stems": True, "direction": "outbound", "format": ["glb"]},
            domain=["news"], style="photoreal", subject=["product", "logo"], accessibility=[], display="additive",
            audio_content=["song"], follows_picture=False, animate_input=True, community=True,
            inputs=[{"kind": "image", "source": ["print-scan"], "defects": "halftone", "fps": 18}],
        )
        self.assertEqual({"faces": True, "voice": True, "method": "blur"}, dict(spec.anonymise))
        self.assertEqual(
            {"platform": ("podcast",), "dynamic_range": "hdr", "stems": True, "direction": "outbound", "format": ("glb",)},
            dict(spec.delivery),
        )
        self.assertEqual(
            (False, ("news",), "photoreal", ("product", "logo"), (), "additive", ("song",), False, True, True),
            (spec.voiceover, spec.domain, spec.style, spec.subject, spec.accessibility, spec.display,
             spec.audio_content, spec.follows_picture, spec.animate_input, spec.community),
        )
        self.assertEqual(
            {"kind": "photo", "owned": None, "source": ("print-scan",), "defects": ("halftone",), "fps": 18.0},
            spec.input_items[0],
        )

    def test_ложь_анонимизации_и_умолчание_метода(self) -> None:
        self.assertEqual({"faces": False, "voice": False, "method": None}, dict(_spec(anonymise=False).anonymise))
        self.assertEqual({"faces": True, "voice": False, "method": "swap"}, dict(_spec(anonymise={"faces": True}).anonymise))
        self.assertEqual({"faces": False, "voice": True, "method": None},
                         dict(_spec(anonymise={"method": "voice-replace"}).anonymise))

    def test_рынки(self) -> None:
        self.assertEqual(("FR", "DE"), _spec(delivery={"markets": ["fr", "DE"]}).delivery["markets"])
        self.assertEqual(["spec.delivery.markets: FRANCE — ISO 3166-1 alpha-2 country codes (FR, DE, US)"],
                         bs.parse_spec({"delivery": {"markets": ["France"]}})[1])

    def test_строгость(self) -> None:
        _, errors = bs.parse_spec({
            "anonymise": {"faces": "y", "x": 1, "method": "mask"}, "delivery": {"platform": "radio", "dynamic_range": "x"},
            "style": "anime", "voiceover": "no", "inputs": [{"kind": "video", "defects": ["dust"], "source": "vhs"}],
        })
        self.assertEqual(
            [
                "spec.inputs[0].source: vhs not in print-scan, archival, cine-film, timelapse, green-screen, stock, "
                "third-party-song, screen-recording, slides, own",
                "spec.inputs[0].defects: dust not in halftone, blur, noise, hum, echo, scratches, flicker",
                "spec.anonymise: unknown field(s) x (known: faces, voice, method)",
                "spec.anonymise.faces='y': must be true or false",
                "spec.anonymise.method: mask not in swap, blur, pixelate, voice-replace",
                "spec.delivery.platform: radio not in broadcast, cinema, streaming-premium, youtube, youtube-shorts, "
                "tiktok, instagram, reels, web, podcast, audiobook, telephony, voice-agent, game-engine, marketplace, "
                "print, vfx, editorial, app-store, music-distribution, other",
                "spec.delivery.dynamic_range: x not in sdr, hdr",
                "spec.voiceover='no': must be true or false",
                "spec.style: anime not in photoreal, stylised, limited-animation",
            ],
            errors,
        )

    def test_эхо_называет_поля(self) -> None:
        echo = bs.echo(_spec(anonymise={"voice": True}, domain=["documentary"]))
        self.assertEqual({"value": {"faces": False, "voice": True, "method": None}, "from": "spec"}, echo["fields"]["anonymise"])
        self.assertEqual({"value": ["documentary"], "from": "spec"}, echo["fields"]["domain"])

    def test_описание_инструмента_и_подсказки(self) -> None:
        doc = " ".join((server.plan_pipeline.__doc__ or "").split())
        for name in ("anonymise {faces?, voice?, method?: swap | blur | pixelate | voice-replace}", "voiceover",
                     "delivery {platform:", "domain", "style photoreal | stylised | limited-animation", "subject",
                     "accessibility", "audio_content", "follows_picture, animate_input, community",
                     "inputs[].source", "inputs[].defects", "inputs[].fps"):
            self.assertIn(name, doc)
        for name in bs.DECISION_FIELDS_R16:
            self.assertIn(name, bs.OPTIONAL_HELP)
            self.assertIn(name, bs.DECISION_FIELDS)


# --- 1. the checklist caveats: field alone (10 languages), field beats words, words fallback ------------

#: Base specs and the plan steps the caveat is judged on.
TTS = ({"task": "generate", "outputs": ["speech"]}, ["озвучка"])
VID = ({"task": "generate", "outputs": ["video"]}, ["генерация_видео"])
VID_TTS = ({"task": "generate", "outputs": ["video", "speech"], "languages": ["it"]}, ["генерация_видео", "озвучка"])
MUS = ({"task": "generate", "outputs": ["music"]}, ["музыка"])
SFX = ({"task": "generate", "outputs": ["sfx"]}, ["звук_фон"])
IMG = ({"task": "generate", "outputs": ["image"]}, ["генерация_изображения"])
EDIT = ({"task": "video-edit", "inputs": [V], "outputs": ["video"]}, ["правка_видео"])
LIPS = ({"task": "lipsync", "inputs": [V, A], "outputs": ["video"]}, ["липсинк"])
INTERP = ({"task": "interpolate", "inputs": [V], "outputs": ["video"]}, ["интерполяция_кадров"])
UPS = ({"task": "upscale", "inputs": [V], "outputs": ["video"]}, ["апскейл"])
ANIM = ({"task": "animate", "inputs": [I], "outputs": ["video"]}, ["оживление"])
RESTORE = ({"task": "restore", "inputs": [V], "outputs": ["video"]}, ["реставрация"])
RESTORE_IMG = ({"task": "restore", "inputs": [I], "outputs": ["image"]}, ["реставрация_изображения"])
AVATAR = ({"task": "avatar", "inputs": [V], "outputs": ["video"]}, ["говорящий_аватар"])
ASR = ({"task": "transcribe", "inputs": [A], "outputs": ["text"]}, ["расшифровка"])
SHORTS = (
    {"task": "cut-to-shorts", "inputs": [{"kind": "video", "owned": True, "duration_s": 2400}], "outputs": ["video"],
     "shots": 5, "per_shot_s": 30},
    ["расшифровка"],
)
VOICE_DUB = ({"task": "dub-translate", "inputs": [V], "outputs": ["video", "speech"], "languages": ["es"]},
             ["расшифровка", "озвучка"])


def _with_input(base: dict, **item: Any) -> dict:
    """The base spec with its first input record carrying `item` fields."""
    входы = [dict(з) for з in base.get("inputs") or []]
    входы[0].update(item)
    return {**base, "inputs": входы}


#: rules -> (base and steps, field ON, field OFF, foreign brief, EN brief that fires without the field).
CASES: list[tuple[tuple[str, ...], tuple[dict, list[str]], dict, dict, str, str]] = [
    (("telephony_audio",), TTS, {"delivery": {"platform": "telephony"}}, {"delivery": {"platform": ["web"]}},
     "为我们的电话语音菜单录制提示音", "prompts for our IVR phone menu"),
    (("podcast_loudness", "podcast_artwork_metadata", "podcast_ai_disclosure"), TTS,
     {"delivery": {"platform": "podcast"}}, {"delivery": {"platform": ["youtube"]}},
     "毎週配信する音声番組のナレーション", "narration for our weekly podcast"),
    (("broadcast_loudness", "broadcast_legal_range", "broadcast_safe_areas", "broadcast_frame_rate"), VID,
     {"delivery": {"platform": "broadcast"}}, {"delivery": {"platform": ["tiktok"]}},
     "지상파 채널에 내보낼 30초 광고", "a 30 s spot for broadcast"),
    (("broadcast_closed_captions",), VID_TTS, {"delivery": {"platform": "broadcast"}}, {"delivery": {"platform": ["web"]}},
     "지상파 채널에 내보낼 해설 영상", "a narrated film for broadcast"),
    (("dcp_master", "cinema_sound_reference", "cinema_big_screen_check"), VID, {"delivery": {"platform": "cinema"}},
     {"delivery": {"platform": ["web"]}}, "Anuncio de 20 segundos para proyectar en salas antes de la película",
     "a 20 s ad for cinema screening"),
    (("dcp_frame_rate",), ({"task": "generate", "outputs": ["video"], "fps": 30}, ["генерация_видео"]),
     {"delivery": {"platform": "cinema"}}, {"delivery": {"platform": ["web"]}},
     "Anuncio de 20 segundos para proyectar en salas antes de la película", "a 20 s ad for cinema screening"),
    (("streaming_imf_delivery", "streaming_dialogue_loudness", "streaming_genai_approval"), VID,
     {"delivery": {"platform": "streaming-premium"}}, {"delivery": {"platform": ["web"]}},
     "Episódio piloto para uma grande plataforma de vídeo por assinatura", "a pilot episode for Netflix"),
    (("platform_encode",), VID, {"delivery": {"platform": "tiktok"}}, {"delivery": {"platform": ["broadcast"]}},
     "Ein kurzer Clip für unseren Kanal auf der Kurzvideo-Plattform", "a clip for our TikTok"),
    (("platform_thumbnail",), ({"task": "generate", "outputs": ["video", "image"]}, ["генерация_видео"]),
     {"delivery": {"platform": "youtube"}}, {"delivery": {"platform": ["broadcast"]}},
     "Kanalımız için bir video ve kapak görseli", "a YouTube video with a thumbnail"),
    (("short_form_length_cap",), ({"task": "generate", "outputs": ["video"], "aspect": "9:16", "duration_s": 200},
                                  ["генерация_видео"]),
     {"delivery": {"platform": "reels"}}, {"delivery": {"platform": ["broadcast"]}},
     "فيديو عمودي طويل لمنصة المقاطع القصيرة", "a vertical TikTok video"),
    (("hdr_delivery",), VID, {"delivery": {"dynamic_range": "hdr"}}, {"delivery": {"dynamic_range": "sdr"}},
     "Un film de marque masterisé en haute gamme dynamique", "a brand film mastered in HDR"),
    (("me_stems_delivery",), VID_TTS, {"delivery": {"stems": True}}, {"delivery": {"stems": False}},
     "Spot con tracce separate di musica ed effetti per altri paesi", "localise it later — keep the M&E"),
    (("fcc_ai_voice_robocall",), TTS, {"delivery": {"platform": "telephony", "direction": "outbound"}},
     {"delivery": {"platform": "telephony", "direction": "inbound"}},
     "Müşterilerimize otomatik arama ile ödeme hatırlatması", "outbound calls to our customers about payments"),
    (("voice_bot_disclosure",), TTS, {"delivery": {"platform": "voice-agent"}}, {"delivery": {"platform": ["web"]}},
     "مساعد صوتي يرد على مكالمات العملاء", "a voice bot that answers the calls"),
    (("game_audio_variations",), SFX, {"delivery": {"platform": "game-engine"}}, {"delivery": {"platform": ["web"]}},
     "我们独立游戏里的脚步声和开门声", "footsteps for our video game"),
    (("game_music_layers",), MUS, {"delivery": {"platform": "game-engine"}}, {"delivery": {"platform": ["web"]}},
     "ボス戦のための戦闘曲", "boss battle music for our video game"),
    (("acx_audio_specs", "audiobook_ai_narration"), TTS, {"delivery": {"platform": "audiobook"}},
     {"delivery": {"platform": ["podcast"]}}, "소설 한 권 전체 낭독 녹음", "narrate our audiobook"),
    (("music_release_metadata",), MUS, {"delivery": {"platform": "music-distribution"}},
     {"delivery": {"platform": ["web"]}}, "Una canción para publicar en las tiendas de música",
     "release the track on Spotify via DistroKid"),
    (("ai_music_distribution",), MUS, {"delivery": {"platform": "music-distribution"}},
     {"delivery": {"platform": ["web"]}}, "Faixa para lançar nas lojas de música e gerar receita",
     "release it on Spotify via DistroKid"),
    (("marketplace_main_image",), IMG, {"subject": ["product"], "delivery": {"platform": "marketplace"}},
     {"subject": ["product"], "delivery": {"platform": ["web"]}},
     "Hauptbild für unseren Shop-Eintrag, freigestellt", "the main image of our product for Amazon"),
    (("print_cmyk_bleed",), IMG, {"delivery": {"platform": "print"}}, {"delivery": {"platform": ["web"]}},
     "Affiche A2 pour la vitrine du magasin", "a poster for print"),
    (("print_vector_text",), IMG, {"delivery": {"platform": "print"}, "subject": ["text"]},
     {"delivery": {"platform": ["web"]}, "subject": ["text"]},
     "Affiche A2 avec le slogan pour la vitrine", "a poster with our headline for print"),
    (("hologram_black_background",), VID, {"display": "additive"}, {"display": "standard"},
     "Conteúdo para o nosso ecrã de ventoinha 3D na loja", "content for our hologram fan"),
    (("cosmetic_ad_effect",), VID, {"subject": ["cosmetic"], "domain": ["advertising"]},
     {"subject": ["product"], "domain": ["entertainment"]}, "Spot per il nostro siero viso", "an ad for our anti-ageing serum"),
    (("before_after_genuine",), IMG, {"subject": ["before-after"]}, {"subject": ["product"]},
     "Öncesi ve sonrası karşılaştırma görseli", "a before and after image"),
    (("social_commercial_music",), ({"task": "generate", "outputs": ["video", "music"]}, ["генерация_видео", "музыка"]),
     {"delivery": {"platform": "tiktok"}, "domain": ["advertising"]},
     {"delivery": {"platform": ["broadcast"]}, "domain": ["advertising"]},
     "إعلان لمنصة المقاطع القصيرة مع لحن", "a TikTok ad with music"),
    (("branded_content_disclosure",), VID, {"domain": ["branded-content"]}, {"domain": ["entertainment"]},
     "网红合作的赞助视频", "a sponsored influencer video"),
    (("financial_promo",), VID, {"domain": ["financial-advertising"]}, {"domain": ["entertainment"]},
     "投資アプリの広告", "an ad for our crypto trading app"),
    (("health_ad_claims",), VID, {"domain": ["health-advertising"]}, {"domain": ["entertainment"]},
     "건강 보조제 광고", "an ad for our medical supplement"),
    (("news_synthetic_label",), VID, {"domain": ["news"]}, {"domain": ["entertainment"]},
     "Reconstrucción para el noticiero de la noche", "a reconstruction for the evening news"),
    (("virtual_staging_disclosure", "real_estate_permanent_features"), IMG, {"domain": ["real-estate"]},
     {"domain": ["advertising"]}, "Fotos do apartamento à venda com móveis virtuais",
     "virtually stage the apartment for sale"),
    (("political_ai_disclosure",), VID, {"domain": ["political"]}, {"domain": ["entertainment"]},
     "Wahlwerbespot für unsere Kandidatin", "a video for our election candidate"),
    (("retouch_label_france",), IMG, {"edit_target": "person", "domain": ["advertising"], "delivery": {"markets": ["FR"]}},
     {"edit_target": "person", "domain": ["advertising"], "delivery": {"markets": ["DE"]}},
     "Publicité : affiner la silhouette du mannequin", "retouch the model's skin for our ad in France"),
    (("interp_limited_animation",), INTERP, {"style": "limited-animation"}, {"style": "photoreal"},
     "Portare a 60 fotogrammi il nostro cartone animato giapponese", "interpolate our anime episode to 60 fps"),
    (("anime_on_twos_output",), VID, {"style": "limited-animation"}, {"style": "photoreal"},
     "Japon çizgi film tarzında kısa bir sahne", "an anime-style short scene"),
    (("anime_upscaler",), UPS, {"style": "limited-animation"}, {"style": "photoreal"},
     "رفع دقة حلقة رسوم متحركة يابانية", "upscale our anime episode"),
    (("synthetic_people_disclosure",), VID, {"style": "photoreal"}, {"style": "stylised"},
     "一个看起来像真人的女人在咖啡馆里", "a photorealistic woman in a cafe"),
    (("stylised_face_photoreal_model",), LIPS, {"style": "stylised"}, {"style": "photoreal"},
     "うちのマスコットキャラの口パク", "lip sync our cartoon mascot"),
    (("product_fidelity",), ANIM, {"subject": ["product"]}, {"subject": ["person"]},
     "우리 향수병 사진을 움직이게", "animate the photo of our product"),
    (("reflective_surfaces",), IMG, {"subject": ["reflective"]}, {"subject": ["product"]},
     "Un reloj de acero pulido sobre mármol", "a chrome watch on marble"),
    (("wcag_captions",), VID, {"accessibility": ["captions"]}, {"accessibility": []},
     "Lehrvideo für eine Behörde, barrierefrei", "an accessible training video for the public sector"),
    (("audio_description",), VID, {"accessibility": ["audio-description"]}, {"accessibility": ["captions"]},
     "Vidéo pour une administration, décrite pour les malvoyants", "an accessible training video for the public sector"),
    (("singing_vocal_stem",), LIPS, {"audio_content": ["song"]}, {"audio_content": ["speech"]},
     "La cantante interpreta il nostro brano", "she sings our song"),
    (("slides_screen_real",), AVATAR, {"inputs": [{**V, "source": ["slides"]}]}, {"inputs": [{**V, "source": ["own"]}]},
     "Sunum sayfalarımızın üzerine bir anlatıcı", "a presenter over our slide deck"),
    (("restore_grain", "archival_ai_disclosure"), RESTORE, {"inputs": [{**V, "source": ["archival"]}]},
     {"inputs": [{**V, "source": ["own"]}]}, "ترميم فيلم عائلي قديم", "restore our archival footage from the 1960s"),
    (("cine_film_speed",), RESTORE, {"inputs": [{**V, "fps": 16}]}, {"inputs": [{**V, "fps": 25, "source": ["own"]}]},
     "Restaurar las bobinas familiares", "restore our super 8 reels"),
    (("green_screen_keying",), EDIT, {"inputs": [{**V, "source": ["green-screen"]}]}, {"inputs": [{**V, "source": ["own"]}]},
     "演员在绿幕前拍摄，换成办公室背景", "replace the green screen with an office"),
    (("stock_licence_scope",), EDIT, {"inputs": [{**V, "source": ["stock"]}]}, {"inputs": [{**V, "source": ["own"]}]},
     "購入した素材動画を編集", "edit our stock footage"),
    (("cover_song_rights",), LIPS, {"inputs": [V, {**A, "source": ["third-party-song"]}]},
     {"inputs": [V, {**A, "source": ["own"]}]}, "유명 가수의 노래를 따라 부르는 영상", "a cover of a famous song"),
    (("timelapse_interpolation",), INTERP, {"inputs": [{**V, "source": ["timelapse"]}]},
     {"inputs": [{**V, "source": ["own"]}]}, "Suavizar nuestra secuencia de fotos a intervalos de la ciudad",
     "smooth our timelapse of the city"),
    (("descreen_halftone",), RESTORE_IMG, {"inputs": [{**I, "defects": ["halftone"]}]},
     {"inputs": [{**I, "defects": ["scratches"]}]}, "Restaurar uma foto recortada de um jornal antigo",
     "restore a photo from an old newspaper"),
    (("audio_cleanup_chain",), ASR, {"inputs": [{**A, "defects": ["noise"]}]}, {"inputs": [{**A, "defects": ["blur"]}]},
     "Die Aufnahme hat starkes Rauschen und Brummen", "remove the background noise and hum"),
    (("app_preview_specs",), VID, {"delivery": {"platform": "app-store"}}, {"delivery": {"platform": ["web"]}},
     "应用商店的预览视频", "an App Store preview video"),
    (("vfx_plate_handoff",), EDIT, {"delivery": {"platform": "vfx"}}, {"delivery": {"platform": ["web"]}},
     "合成用の素材をポスプロ会社へ納品", "plates for compositing in Nuke"),
    (("editorial_handoff",), EDIT, {"delivery": {"platform": "editorial"}}, {"delivery": {"platform": ["web"]}},
     "편집자가 프로젝트에서 이어서 작업", "our editor will finish it in Premiere Pro"),
    (("anonymisation_gdpr",), EDIT, {"anonymise": {"faces": True}}, {"anonymise": False},
     "Gesichter der Passanten unkenntlich machen", "blur the faces of passers-by"),
    (("voice_anonymisation",), VOICE_DUB, {"anonymise": {"voice": True}}, {"anonymise": False},
     "La voz del testigo no debe ser reconocible", "disguise the witness's voice"),
    (("no_speech_short",), SHORTS, {"voiceover": False}, {"voiceover": True},
     "음성 해설 없이 음악과 자막만", "no voiceover, music only"),
]


def _merge(base: dict, extra: dict) -> dict:
    return {**base, **extra}


class ПравилаПоПолю(unittest.TestCase):
    def test_покрыт_каждый_пункт_списка(self) -> None:
        """Every caveat that named its field in round 15 is cased here — or in round 15 (its own fields)."""
        round15 = {"made_for_kids", "relight_limits", "style_consistency_set", "seamless_loop", "long_ambient_loop",
                   "tileable_texture", "outputs_as_training_data", "face_swap_dataset_consent", "photosensitive_flashes"}
        listed = {r for rules in cl.spec_fields_to_add().values() for r in rules}
        cased = {r for rules, *_ in CASES for r in rules}
        self.assertEqual(set(), listed - cased - round15)

    def test_а_поле_решает_на_любом_языке(self) -> None:
        for rules, (base, steps), on, _, foreign, _ in CASES:
            with self.subTest(rules=rules):
                got = _fired(foreign, steps, _merge(base, on))
                self.assertEqual(set(rules), set(rules) & got)

    def test_б_названное_нет_старше_слов(self) -> None:
        for rules, (base, steps), _, off, _, en in CASES:
            with self.subTest(rules=rules):
                self.assertEqual(set(), set(rules) & _fired(en, steps, _merge(base, off)))

    def test_в_без_поля_слова(self) -> None:
        for rules, (base, steps), _, _, _, en in CASES:
            with self.subTest(rules=rules):
                self.assertEqual(set(rules), set(rules) & _fired(en, steps, base))

    def test_г_без_поля_чужой_язык_молчит(self) -> None:
        """The gap the field closes: the same foreign brief with no field carries no caveat."""
        for rules, (base, steps), _, _, foreign, _ in CASES:
            with self.subTest(rules=rules):
                self.assertEqual(set(), set(rules) & _fired(foreign, steps, base))

    def test_русские_слова_запасом(self) -> None:
        for rules, (base, steps), brief in (
            (("descreen_halftone",), RESTORE_IMG, "отреставрировать фото из газеты"),
            (("anonymisation_gdpr",), EDIT, "размыть лица прохожих"),
            (("voice_anonymisation",), VOICE_DUB, "голос свидетеля должен быть неузнаваем"),
            (("no_speech_short",), SHORTS, "без закадра, только музыка"),
            (("podcast_loudness",), TTS, "озвучка для нашего подкаста"),
            (("broadcast_loudness",), VID, "ролик для телеэфира"),
        ):
            with self.subTest(rules=rules):
                self.assertEqual(set(rules), set(rules) & _fired(brief, steps, base))

    def test_обложка_без_выхода_картинки_словами(self) -> None:
        """The thumbnail field is one-sided: outputs without an image leave the words to decide."""
        self.assertIn("platform_thumbnail", _fired("a YouTube video with a thumbnail", ["генерация_видео"],
                                                   {"task": "generate", "outputs": ["video"]}))

    def test_мерцание_через_условия(self) -> None:
        """Flashing: the existing `conditions` field carries it (an EN phrase the caller writes)."""
        base, steps = VID
        self.assertIn("photosensitive_flashes", _fired("Videoclip con lampi di luce rapidissimi", steps,
                                                       _merge(base, {"conditions": ["flashing"]})))
        self.assertNotIn("photosensitive_flashes", _fired("Videoclip con lampi di luce rapidissimi", steps, base))

    def test_печатный_скан_без_дефектов_тоже_растр(self) -> None:
        base, steps = RESTORE_IMG
        self.assertIn("descreen_halftone", _fired("Restaurar", steps, _merge(base, {"inputs": [{**I, "source": ["print-scan"]}]})))
        # defects named without halftone overrule the print-scan source
        self.assertNotIn("descreen_halftone", _fired(
            "restore a photo from an old newspaper", steps,
            _merge(base, {"inputs": [{**I, "source": ["print-scan"], "defects": ["scratches"]}]})))


# --- 2. the no-speech short: conservative ------------------------------------------------------------


class ШортсБезРечи(unittest.TestCase):
    def test_структура_одна_не_решает(self) -> None:
        """A cut from the customer's footage with no speech output is NOT read as no-speech (a vlog keeps its voice)."""
        base, steps = SHORTS
        self.assertNotIn("no_speech_short", _fired("Fünf kurze Clips aus unserem Vlog", steps, base))

    def test_звук_без_речи_решает(self) -> None:
        base, steps = SHORTS
        self.assertIn("no_speech_short", _fired("x", steps, _merge(base, {"audio_content": ["music"]})))
        self.assertNotIn("no_speech_short", _fired("no voiceover, music only", steps,
                                                   _merge(base, {"audio_content": ["music", "speech"]})))

    def test_длина_шортса_а_не_исходника(self) -> None:
        """The short is judged by its own length (per_shot_s), not by the 40-minute source."""
        base, steps = SHORTS
        self.assertIn("no_speech_short", _fired("x", steps, _merge(base, {"voiceover": False})))
        # ten shorts of 30 s: 300 s in all, each one short
        self.assertIn("no_speech_short", _fired("x", steps, _merge(base, {"voiceover": False, "shots": 10, "duration_s": 300})))
        self.assertNotIn("no_speech_short", _fired("x", steps, _merge(base, {"voiceover": False, "per_shot_s": 240, "shots": 1})))

    def test_план(self) -> None:
        brief = "Aus unserem 40-minütigen Vlog fünf kurze Clips schneiden, nur Musik und Texteinblendungen"
        self.assertIn("no_speech_short", _note_ids(_plan(brief, **SHORTS[0], voiceover=False)))
        self.assertNotIn("no_speech_short", _note_ids(_plan(brief, **SHORTS[0])))


# --- 3. anonymisation routes ---------------------------------------------------------------------------


STREET = {"task": "video-edit", "inputs": [{"kind": "video", "owned": True, "duration_s": 60}], "outputs": ["video"]}
WITNESS = {"task": "dub-translate", "inputs": [{"kind": "video", "owned": True, "duration_s": 120}],
           "outputs": ["video", "speech"], "languages": ["es"]}


class АнонимизацияМаршруты(unittest.TestCase):
    def test_лица_замена_по_полю(self) -> None:
        for brief in ("Gesichter der Passanten unkenntlich machen", "通行人の顔を分からなくして", "행인들의 얼굴을 가려 주세요"):
            with self.subTest(brief=brief):
                self.assertEqual(
                    (("генерация_изображения", "замена_персонажа"), (x15.ASSEMBLY_ANON_BLUR_ALT[0],)),
                    _route(brief, **STREET, anonymise={"faces": True}),
                )

    def test_лица_размытие_и_пикселизация(self) -> None:
        self.assertEqual(((), (x15.ASSEMBLY_ANON_BLUR[0],)), _route("Flouter les visages des passants", **STREET,
                                                           anonymise={"faces": True, "method": "blur"}))
        self.assertEqual(((), (an.ASSEMBLY_PIXELATE[0],)), _route("Pixelare i volti dei passanti", **STREET,
                                                                  anonymise={"method": "pixelate"}))

    def test_голос_не_дубляж(self) -> None:
        """A same-language dub-translate with anonymise.voice: transcript + a different stock voice, no dub, no lips."""
        steps, assembly = _route("La voz del testigo no debe ser reconocible", **WITNESS, anonymise={"voice": True})
        self.assertEqual(("расшифровка", "озвучка"), steps)
        self.assertEqual((an.ASSEMBLY_VOICE[0],), assembly)
        spec = bs.with_defaults(_spec(**WITNESS, lipsync=False, anonymise={"voice": True}), ролик=True, текст="x")
        applied = rc.rewrite(spec, bs.route(spec), "x")
        self.assertEqual(((), an.CLONE_ONLY_MODELS), (applied.route.сборка, applied.avoid["озвучка"]))
        self.assertEqual((True, False), (bool(re.search(an.CLONE_ONLY_MODELS, "elevenlabs-instant-voice-clone")),
                                         bool(re.search(an.CLONE_ONLY_MODELS, "kokoro-without-voice-cloning"))))

    def test_допущение_выключается(self) -> None:
        steps, _ = _route("x", **WITNESS, lipsync=False, anonymise={"voice": True}, priors={"anonymise_voice_replace": False})
        self.assertEqual(("дубляж",), steps)

    def test_оба(self) -> None:
        steps, assembly = _route("Tanığın yüzü ve sesi tanınmamalı", **WITNESS, anonymise={"faces": True, "voice": True})
        self.assertEqual(("расшифровка", "озвучка", "генерация_изображения", "замена_персонажа"), steps)
        self.assertEqual((x15.ASSEMBLY_ANON_BLUR_ALT[0], an.ASSEMBLY_VOICE[0]), assembly)

    def test_поле_нет_старше_слов(self) -> None:
        self.assertEqual((("правка_видео",), ()), _route("blur the faces of passers-by, GDPR", **STREET, anonymise=False))
        steps, _ = _route("the witness's voice must not be recognisable", **WITNESS, lipsync=False, anonymise=False)
        self.assertEqual(("дубляж",), steps)

    def test_слова_запасом(self) -> None:
        self.assertEqual(
            (("генерация_изображения", "замена_персонажа"), (x15.ASSEMBLY_ANON_BLUR_ALT[0],)),
            _route("anonymise the passers-by in our street video (GDPR)", **STREET),
        )
        self.assertEqual(((), (x15.ASSEMBLY_ANON_BLUR[0],)), _route("размыть лица прохожих", **STREET))
        steps, _ = _route("Interview with a witness: the voice must not be recognisable", **WITNESS)
        self.assertEqual(("расшифровка", "озвучка"), steps)
        # «change the voice» alone is not an anonymity order
        steps, _ = _route("change the voice of the narrator to Spanish", **WITNESS, lipsync=False)
        self.assertEqual(("дубляж",), steps)

    def test_аудио_без_картинки(self) -> None:
        steps, _ = _route("播客：举报人的声音必须替换", task="transcribe", inputs=[A], outputs=["speech"], languages=["zh"],
                          anonymise={"voice": True})
        self.assertEqual(("расшифровка", "озвучка"), steps)

    def test_план_лица_модель_цена_и_заметка(self) -> None:
        answer = _plan("Unser Straßenvideo: Gesichter der Passanten unkenntlich machen, bevor wir es veröffentlichen",
                       **STREET, anonymise={"faces": True})
        self.assertEqual(("wavespeed-video-face-swap", True), _chosen(answer)["замена_персонажа"])
        self.assertIn("anonymisation_gdpr", _note_ids(answer))

    def test_план_строка_монтажа_одна(self) -> None:
        answer = _plan("Tanığın yüzü ve sesi tanınmamalı", **{**WITNESS, "languages": ["tr"]},
                       anonymise={"faces": True, "voice": True, "method": "pixelate"})
        self.assertEqual(1, answer["assembly"]["why"].count(an.ASSEMBLY_PIXELATE[1]))

    def test_план_голос(self) -> None:
        answer = _plan("Entrevista con un testigo: la voz no debe ser reconocible, mismo idioma", **WITNESS,
                       anonymise={"voice": True})
        self.assertEqual(["расшифровка", "озвучка"], [s["step"] for s in answer["steps"]])
        notes = _note_ids(answer)
        self.assertIn("voice_anonymisation", notes)
        self.assertIn("anonymisation_gdpr", notes)
        for dub_note in ("translation_review", "dub_time_fit", "forced_narratives"):
            self.assertNotIn(dub_note, notes)


# --- 4. a face swap in the customer's own footage (documentary, consented) ---------------------------


class ЗаменаЛицаБезСнимка(unittest.TestCase):
    DOC = {"task": "face-replace", "inputs": [{"kind": "video", "owned": True, "duration_s": 45}], "outputs": ["video"]}

    def test_модель_и_цена(self) -> None:
        for brief in ("Documentário próprio: trocar o rosto do protagonista, ele consentiu", "纪录片：替换主角的脸，他已同意"):
            with self.subTest(brief=brief):
                answer = _plan(brief, **self.DOC)
                self.assertEqual(("wavespeed-video-face-swap", True), _chosen(answer)["замена_персонажа"])

    def test_референс_допущение_а_не_шаг(self) -> None:
        self.assertEqual({"изображение"}, an.assumed_inputs("замена_персонажа", _spec(**self.DOC), "изображение"))
        self.assertEqual(set(), an.assumed_inputs("замена_персонажа", _spec(task="video-edit"), "изображение"))
        self.assertEqual((("замена_персонажа",), ()), _route("x", **self.DOC))


# --- 5. the recipe words and the planner's community words --------------------------------------------


class РецептыПоПолю(unittest.TestCase):
    def test_логотип_и_текст(self) -> None:
        self.assertEqual((True, False), (rc.logo_named(_spec(subject=["logo"])), rc.logo_named(_spec(subject=["product"], conditions=["logo"]))))
        self.assertEqual(True, rc.logo_named(_spec(conditions=["logo end card"])))
        self.assertEqual((True, False), (rc.exact_text_named(_spec(subject=["text"])), rc.exact_text_named(_spec(subject=["person"], conditions=["headline"]))))

    def test_размытие_архива(self) -> None:
        self.assertEqual(True, rc.blur_named(_spec(inputs=[{**V, "defects": ["blur"]}])))
        self.assertEqual(False, rc.blur_named(_spec(inputs=[{**V, "defects": ["scratches"]}], conditions=["blurry"])))
        self.assertEqual(True, rc.blur_named(_spec(conditions=["blurry"])))

    def test_визуализатор(self) -> None:
        self.assertEqual((True, False), (rc.scenes_named(_spec(outputs=[{"kind": "video", "loop": False}])),
                                         rc.scenes_named(_spec(outputs=[{"kind": "video", "loop": True}], conditions=["scenes"]))))
        self.assertEqual(True, rc.art_moves(_spec(outputs=[{"kind": "video", "loop": True}])))
        self.assertEqual((True, False, True), (rc.art_moves(_spec(animate_input=True)),
                                               rc.art_moves(_spec(animate_input=False, conditions=["animate it"])),
                                               rc.art_moves(_spec(conditions=["animate it"]))))

    def test_персонаж_примерка_тур(self) -> None:
        self.assertEqual((True, False), (rc.whole_character(_spec(subject=["mascot"])),
                                         rc.whole_character(_spec(subject=["person"]), "a costume mascot")))
        self.assertEqual((True, False), (rc.wants_try_on(_spec(subject=["garment"])),
                                         rc.wants_try_on(_spec(subject=["product"]), "a model wearing our dress")))
        tour = {"inputs": [{"kind": "image", "count": 6}], "outputs": ["video"]}
        self.assertEqual((True, True, False), (rc.walkthrough(_spec(**tour, subject=["interior"])),
                                               rc.walkthrough(_spec(**tour, domain=["real-estate"])),
                                               rc.walkthrough(_spec(**tour, subject=["product"]), "a virtual tour")))

    def test_рисованное_локальное_звук_сетка(self) -> None:
        self.assertEqual((True, False), (rc.drawn(_spec(style="stylised")), rc.drawn(_spec(style="photoreal"), "our anime")))
        self.assertEqual((False, True), (rc.local_only(_spec(self_host=False), "offline please"), rc.local_only(_spec(), "offline please")))
        self.assertEqual((True, False), (rc.follows_picture(_spec(follows_picture=True)),
                                         rc.follows_picture(_spec(follows_picture=False), "sync to the action")))
        self.assertEqual((True, False), (rc.wants_mesh(_spec(delivery={"format": ["usdz"]})),
                                         rc.wants_mesh(_spec(delivery={"format": ["mp4"]}), "a GLB model")))

    def test_печать(self) -> None:
        self.assertEqual((True, False), (delivery.is_print(_spec(outputs=["image"], delivery={"platform": "print"})),
                                         delivery.is_print(_spec(outputs=["image"], delivery={"platform": "web"}), "a poster")))

    def test_сообщество(self) -> None:
        self.assertEqual((True, False, True), (pn.community_asked(_spec(community=True), "x"),
                                               pn.community_asked(_spec(community=False), "a civitai LoRA"),
                                               pn.community_asked(_spec(), "a civitai LoRA")))
        self.assertEqual(frozenset(), pn.requested_flags(_spec(community=False), "a civitai LoRA"))
        self.assertEqual(frozenset({"community_checkpoint", "style_lora"}), pn.requested_flags(_spec(community=True), "x"))


# --- 6. the spec question: decision fields ---------------------------------------------------------------


class ЧерновикПоляШестнадцатогоКруга(unittest.TestCase):
    def test_слова_подсказывают(self) -> None:
        got = {f["field"]: f["read_from_text"] for f in bs.decision_fields(
            "Anonymise the passers-by; the witness's voice must not be recognisable; no voiceover; for broadcast "
            "in HDR; an ad for our product; restore a photo from an old newspaper; a civitai LoRA")
            if f["field"] in bs.DECISION_FIELDS_R16}
        self.assertEqual(
            {"anonymise": {"faces": True, "voice": True, "method": "swap"}, "voiceover": False,
             "delivery.platform": ["broadcast"], "delivery.dynamic_range": "hdr", "delivery.stems": None,
             "delivery.direction": None, "delivery.format": None, "delivery.markets": None, "domain": ["advertising"], "style": None,
             "subject": ["product"], "accessibility": None, "display": None, "audio_content": None,
             "follows_picture": None, "animate_input": None, "community": True, "inputs[].source": None,
             "inputs[].defects": ["halftone"], "inputs[].fps": None},
            got,
        )

    def test_названные_не_предлагаются(self) -> None:
        names = [f["field"] for f in bs.decision_fields("x", {"anonymise": False, "delivery": {"platform": "web"},
                                                               "inputs": [{"kind": "video", "source": ["own"]}]})]
        for name in ("anonymise", "delivery.platform", "delivery.stems", "inputs[].source"):
            self.assertNotIn(name, names)
        for name in ("inputs[].defects", "voiceover", "domain"):
            self.assertIn(name, names)

    def test_вопрос_называет_поля(self) -> None:
        answer = json.loads(server.plan_pipeline("Gesichter der Passanten in unserem Video unkenntlich machen"))
        self.assertEqual("нужна_спецификация", answer["reason"])
        fields = [f["field"] for f in answer["spec_needed"]["draft"]["decision_fields"]]
        for name in ("anonymise", "voiceover", "delivery.platform", "inputs[].defects"):
            self.assertIn(name, fields)
            self.assertIn(name, answer["spec_needed"]["allowed"])


# --- 7. the readers ---------------------------------------------------------------------------------------


class Читатели(unittest.TestCase):
    def test_не_названо_это_None(self) -> None:
        spec = _spec(task="generate")
        self.assertEqual(
            (None, None, None, None, None, None, None, None, None, None),
            (sf.platform(spec, "print"), sf.domain(spec, "news"), sf.subject(spec, "logo"), sf.style(spec, "photoreal"),
             sf.accessibility(spec), sf.input_source(spec, "stock"), sf.halftone(spec), sf.anonymise_faces(spec),
             sf.no_speech(spec), sf.flag(spec, "community")),
        )

    def test_пустой_список_это_нет(self) -> None:
        self.assertEqual(False, sf.accessibility(_spec(accessibility=[])))
        self.assertEqual(False, sf.domain(_spec(domain=[]), "news"))

    def test_порядок_речи(self) -> None:
        """voiceover first, then audio_content, then people[].speaks."""
        self.assertEqual(False, sf.no_speech(_spec(voiceover=True, audio_content=["music"])))
        self.assertEqual(True, sf.no_speech(_spec(audio_content=["music"], people=[{"name": "a", "speaks": True}])))
        self.assertEqual(True, sf.no_speech(_spec(people=[{"name": "a", "real": False, "speaks": False}])))


if __name__ == "__main__":
    unittest.main()
