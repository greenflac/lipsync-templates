"""Контракт шестого круга: вызывающий — языковая модель, и план строится ТОЛЬКО по spec.

Пять кругов подстрочных списков не сошлись: «transcribe interview», «restore
8mm», «stabilise drone», «make my cat photo sing» уходили в генерацию с нуля за
$394–$540, хотя заказчик принёс материал. Теперь:

1. spec без решающих полей — вопрос (`нужна_спецификация`) с перечнем полей и
   ЧЕРНОВИКОМ из текста; шагов и цены в таком ответе нет никогда;
2. полная spec — план по ней одной, текст только для нот и эха;
3. расширения: входы с владением, любые теги BCP-47, любое W:H, бюджет в
   любой валюте ISO 4217 (перевод только по записанному курсу), люди, условия;
4. новые работы: video-edit, r2v, music-visualiser, sing-photo, cut-to-shorts.

Т2: ожидания — литералы. Т4: сети нет; план собирается на синтетической базе
(состав шагов от базы не зависит), вопрос — на уровне инструмента сервера (план
не строится, база не читается). Т1: константы-решения мутируются в
`scripts/mutate_brief_spec.py`, и каждая сторожится здесь с обеих сторон.
"""

from __future__ import annotations

import json
import unittest
from datetime import date
from unittest import mock

import studio.planner as pn
from studio import brief_spec as bs
from studio import duration as dur
from studio.selfrag.facts import Fact

СЕГОДНЯ = date(2026, 10, 15)


def факт(model: str, attribute: str, value: str) -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=f"https://example.invalid/{model}",
        tier="vendor",
        stated_on="2026-10-01",
    )


БАЗА: tuple[Fact, ...] = (
    факт("x-t2i", "architecture", "text-to-image model"),
    факт("x-t2i", "price_per_image_usd", "$0.05 per image"),
    факт("x-i2v", "architecture", "image-to-video model"),
    факт("x-i2v", "max_seconds", "10"),
)


def свой(*виды: str, сек: float | None = None) -> list[dict]:
    """Входы заказчика в форме контракта: свои (owned=true), с длиной у видео/аудио."""
    return [
        {"kind": в, "owned": True, **({"duration_s": сек} if сек and в in ("video", "audio") else {})}
        for в in виды
    ]


def план(spec: dict, бриф: str = "spec-only call") -> dict:
    return pn.plan(бриф, facts=list(БАЗА), today=СЕГОДНЯ, full=True, spec=spec, spec_only=True)


def шаги(итог: dict) -> list[str]:
    return [ш["step"] for ш in итог["steps"]]


# --- 1. Свободный текст — вопрос с черновиком, никогда не план --------------------

#: Перефразировки (наши, не текст валидатора) и его же провалы пятого круга:
#: (бриф, работа черновика, вид входа, который черновик обязан увидеть).
#: Черновик бывает неточен — но работу над материалом заказчика он не зовёт
#: генерацией, а принесённый материал не теряет.
ПЕРЕФРАЗЫ: tuple[tuple[str, str, str], ...] = (
    ("Transcribe a 45-minute two-person interview in Russian with speaker labels", "transcribe", "video"),
    ("transcribe my 45 minute interview with speaker labels", "transcribe", "video"),
    ("Расшифруй запись созвона на 40 минут", "transcribe", "video"),
    ("Restore a scratched 1970s 8mm home movie, 5 minutes, keep it black and white", "restore", "video"),
    ("restore my grandfather's 8mm reels, 5 minutes", "restore", "video"),
    ("stabilise my shaky drone clip (90s)", "video-edit", "video"),
    ("Replace the sky in my 20s landscape timelapse with a dramatic aurora, 4K", "video-edit", "video"),
    ("Convert our vertical 9:16 TikTok (25s) into a horizontal 16:9 YouTube version", "video-edit", "video"),
    ("Remove the background from a 30s talking-head video so we can put it on green", "remove-background", "video"),
    ("remove the background from my 30s video", "remove-background", "video"),
    ("Add burned-in animated captions in Spanish to my 60s reel", "captions", "video"),
    ("add Spanish captions to my 60 second reel", "captions", "video"),
    ("clone my voice from a 3 minute recording and read this script", "voice-clone", "audio"),
    ("Склонируй голос нашего CEO (есть 3 минуты записи) и озвучь им 90 секунд текста", "voice-clone", "audio"),
    ("make my cat photo sing 'Never gonna give you up', 10 seconds, vertical", "sing-photo", "image"),
    ("Сделай так, чтобы фото моей собаки пело песню", "sing-photo", "image"),
    ("Music visualiser for my 4-minute techno track: abstract reactive shapes, 16:9", "music-visualiser", "audio"),
    ("music visualiser for my techno track, 4 minutes", "music-visualiser", "audio"),
    ("my 30-min interview → 10 shorts for TikTok, 60s each", "cut-to-shorts", "video"),
    ("Нарежь из нашего часового подкаста 8 коротких роликов по 30 секунд", "cut-to-shorts", "video"),
    ("Slow motion: turn my 4s 30fps clip of a skateboard trick into 120fps", "interpolate", "video"),
    ("Lipsync a side-profile shot of an actor to new English dialogue, we have the video and the audio", "lipsync", "video"),
    ("Translate our 90s product video from English into Polish and Turkish", "dub-translate", "video"),
)


class СвободныйТекст(unittest.TestCase):
    """Вызов без spec: ответ — вопрос, поля и черновик; плана, шагов и цены нет."""

    @classmethod
    def setUpClass(cls) -> None:
        from studio.mcp import server

        cls.server = server

    def ответ(self, бриф: str, **kw) -> dict:
        return json.loads(self.server.plan_pipeline(бриф, **kw))

    def test_text_only_is_a_question_with_a_draft_never_a_plan(self) -> None:
        self.assertGreaterEqual(len(ПЕРЕФРАЗЫ), 20)
        for бриф, _, _ in ПЕРЕФРАЗЫ:
            with self.subTest(бриф=бриф):
                о = self.ответ(бриф)
                self.assertEqual("could not measure", о["outcome"])
                self.assertEqual("нужна_спецификация", о["reason"])
                self.assertEqual([], о["steps"])
                self.assertEqual({}, о["pipeline_price"])
                self.assertIsNotNone(о["question"])
                нужно = о["spec_needed"]
                self.assertTrue(нужно["missing"])
                self.assertTrue(нужно["draft"]["status"].startswith("DRAFT — UNCONFIRMED"))
                self.assertIn("task", нужно["example"])

    def test_draft_reads_the_job_and_keeps_what_the_customer_brought(self) -> None:
        for бриф, работа, вход in ПЕРЕФРАЗЫ:
            with self.subTest(бриф=бриф):
                черновик = bs.draft(бриф)["spec"]
                задача = черновик.get("task")
                главная = задача[0] if isinstance(задача, list) else задача
                self.assertEqual(работа, главная)
                self.assertIn(вход, [в["kind"] for в in черновик.get("inputs", [])])
                self.assertNotEqual("generate", главная)

    def test_draft_is_a_valid_spec_once_the_customer_confirms_it(self) -> None:
        черновик = bs.draft("my 30-min interview → 10 shorts for TikTok, 60s each")
        self.assertEqual(["inputs[0].owned"], черновик["still_missing"])
        подтверждён = dict(черновик["spec"])
        подтверждён["inputs"] = [{**подтверждён["inputs"][0], "owned": True}]
        _, ошибки, нет = bs.gaps(подтверждён)
        self.assertEqual([], ошибки)
        self.assertEqual([], нет)

    def test_a_complete_draft_needs_nothing_more(self) -> None:
        черновик = bs.draft("stabilise my shaky drone clip (90s)")
        self.assertEqual([], черновик["still_missing"])
        self.assertEqual("video-edit", черновик["spec"]["task"])

    def test_have_phrase_reads_both_things_brought(self) -> None:
        черновик = bs.draft("Lipsync the actor to new dialogue, we have the video and the audio")["spec"]
        self.assertEqual(["video", "audio"], [в["kind"] for в in черновик["inputs"]])

    def test_have_phrase_window_stops_where_the_thing_is_far(self) -> None:
        черновик = bs.draft("we have a lot of ideas for the brand, and want a new video")["spec"]
        self.assertNotIn("inputs", черновик)

    def test_have_phrase_stops_at_nothing_and_at_make(self) -> None:
        self.assertNotIn("inputs", bs.draft("we have nothing yet, make a promo video")["spec"])

    def test_fields_the_caller_named_stay_the_callers(self) -> None:
        черновик = bs.draft("generate a 10s clip", {"task": "restore"})
        self.assertEqual("restore", черновик["spec"]["task"])
        self.assertNotIn("task", черновик["read_from_text"])

    def test_partial_spec_is_a_question_naming_only_what_is_missing(self) -> None:
        о = self.ответ("restore my 8mm film", spec={"task": "restore", "outputs": ["video"]})
        self.assertEqual("нужна_спецификация", о["reason"])
        self.assertEqual(["inputs", "duration_s"], [м["field"] for м in о["spec_needed"]["missing"]])
        self.assertEqual("restore", о["spec_needed"]["draft"]["spec"]["task"])

    def test_bad_spec_field_is_fail_not_a_question(self) -> None:
        о = self.ответ("x", spec={"task": "teleport", "inputs": [], "outputs": ["video"], "duration_s": 5})
        self.assertEqual("fail", о["outcome"])
        self.assertEqual("spec_не_разобран", о["reason"])

    def test_banned_brief_is_refused_before_the_spec_question(self) -> None:
        о = self.ответ("Хочу дипфейк Илона Маска: его лицо на моём видео")
        self.assertNotEqual("нужна_спецификация", о["reason"])


# --- 2. Пробелы spec: решающие поля --------------------------------------------------


class РешающиеПоля(unittest.TestCase):
    def пробелы(self, spec: dict) -> list[str]:
        _, ошибки, нет = bs.gaps(spec)
        self.assertEqual([], ошибки)
        return [н["field"] for н in нет]

    def test_nothing_named_names_four_fields(self) -> None:
        self.assertEqual(["task", "inputs", "outputs"], self.пробелы({}))

    def test_legacy_string_input_asks_who_owns_it(self) -> None:
        self.assertEqual(
            ["inputs[0].owned"],
            self.пробелы({"task": "restore", "inputs": ["video"], "outputs": ["video"], "duration_s": 60}),
        )

    def test_material_task_takes_its_length_from_the_input(self) -> None:
        spec = {"task": "restore", "inputs": свой("video", сек=300), "outputs": ["video"]}
        self.assertEqual([], self.пробелы(spec))

    def test_generation_does_not_take_its_length_from_an_input(self) -> None:
        spec = {"task": "generate", "inputs": свой("audio", сек=300), "outputs": ["video"]}
        self.assertEqual(["duration_s"], self.пробелы(spec))

    def test_avatar_over_the_customers_track_takes_the_tracks_length(self) -> None:
        spec = {"task": "avatar", "inputs": [*свой("image"), *свой("audio", сек=20)],
                "outputs": ["video"]}
        self.assertEqual([], self.пробелы(spec))
        без_дорожки = {"task": "avatar", "inputs": свой("image"), "outputs": ["video"]}
        self.assertEqual(["duration_s"], self.пробелы(без_дорожки))

    def test_avatar_plan_is_as_long_as_the_track(self) -> None:
        итог = план({"task": "avatar", "inputs": [*свой("image"), *свой("audio", сек=20)],
                     "outputs": ["video"]})
        self.assertTrue(итог["steps"])
        self.assertEqual({"value": 20.0, "from": "derived"}, итог["understood_as"]["fields"]["duration_s"])

    def test_images_need_a_count(self) -> None:
        self.assertEqual(["shots"], self.пробелы({"task": "generate", "inputs": [], "outputs": ["image"]}))
        self.assertEqual([], self.пробелы({"task": "generate", "inputs": [], "outputs": ["image"], "shots": 4}))

    def test_speech_needs_a_language_and_empty_is_not_one(self) -> None:
        spec = {"task": "generate", "inputs": [], "outputs": ["speech"], "duration_s": 30}
        self.assertEqual(["languages"], self.пробелы(spec))
        self.assertEqual(["languages"], self.пробелы({**spec, "languages": []}))
        self.assertEqual([], self.пробелы({**spec, "languages": ["kk"]}))

    def test_silent_video_takes_no_language(self) -> None:
        spec = {"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 6}
        self.assertEqual([], self.пробелы(spec))

    def test_text_output_needs_a_length(self) -> None:
        spec = {"task": "transcribe", "inputs": свой("audio"), "outputs": ["text"], "languages": ["ru"]}
        self.assertEqual(["duration_s"], self.пробелы(spec))

    def test_transcription_needs_the_language_of_the_recording(self) -> None:
        spec = {"task": "transcribe", "inputs": свой("audio", сек=60), "outputs": ["text"]}
        self.assertEqual(["languages"], self.пробелы(spec))

    def test_shorts_need_count_and_length(self) -> None:
        spec = {"task": "cut-to-shorts", "inputs": свой("video", сек=1800), "outputs": ["video"]}
        self.assertEqual(["shots", "per_shot_s"], self.пробелы(spec))


# --- 3. Расширения формы -------------------------------------------------------------


class ФормаSpec(unittest.TestCase):
    def test_any_bcp47_tag_is_accepted_and_names_map_to_tags(self) -> None:
        spec, ошибки = bs.parse_spec({"languages": ["kk", "pl", "he", "pt-br", "english", "zh-hant-tw"]})
        self.assertEqual([], ошибки)
        self.assertEqual(("kk", "pl", "he", "pt-BR", "en", "zh-Hant-TW"), spec.language_tags)
        self.assertEqual(("kk", "pl", "he", "portuguese", "english", "chinese"), spec.languages)

    def test_a_word_that_is_not_a_tag_is_refused(self) -> None:
        _, ошибки = bs.parse_spec({"languages": ["klingon", "e"]})
        self.assertEqual(2, len(ошибки))

    def test_any_aspect_ratio(self) -> None:
        for raw, метка in (("2.39:1", "2.39:1"), ("2.39", "2.39:1"), ("9:16", "9:16"), ("vertical", "9:16"), ("4/3", "4:3")):
            with self.subTest(raw=raw):
                spec, ошибки = bs.parse_spec({"aspect": raw})
                self.assertEqual([], ошибки)
                self.assertEqual(метка, spec.aspect)

    def test_aspect_limit_both_ways(self) -> None:
        self.assertEqual("10:1", bs.aspect_label("10:1"))
        self.assertIsNone(bs.aspect_label("10.5:1"))
        self.assertEqual("1:10", bs.aspect_label("1:10"))
        self.assertIsNone(bs.aspect_label("1:10.5"))
        self.assertIsNone(bs.aspect_label("0:1"))

    def test_frame_of_a_wide_aspect_is_landscape(self) -> None:
        spec, _ = bs.parse_spec({"resolution": "1080p", "aspect": "2.39:1"})
        self.assertEqual((1920, 1080), bs.frame(spec))

    def test_budget_in_usd_is_a_ceiling(self) -> None:
        spec, ошибки = bs.parse_spec({"budget": {"amount": 40, "currency": "usd"}})
        self.assertEqual([], ошибки)
        self.assertEqual(40.0, spec.budget_usd)

    def test_budget_in_another_currency_without_a_recorded_rate_has_no_verdict(self) -> None:
        spec, ошибки = bs.parse_spec({"budget": {"amount": 12, "currency": "EUR"}})
        self.assertEqual([], ошибки)
        self.assertIsNone(spec.budget_usd)
        self.assertEqual("EUR", spec.budget_currency)
        self.assertIn("NO budget verdict", spec.budget_note)

    def test_budget_converts_only_at_a_recorded_rate(self) -> None:
        with mock.patch.dict(bs.RECORDED_RATES, {"EUR": (1.1, "https://example.invalid/ecb", "2026-10-01")}):
            spec, _ = bs.parse_spec({"budget": {"amount": 10, "currency": "EUR"}})
        self.assertAlmostEqual(11.0, spec.budget_usd)
        self.assertIn("recorded rate", spec.budget_note)

    def test_recorded_rates_are_empty_until_somebody_records_one(self) -> None:
        self.assertEqual({}, bs.RECORDED_RATES)

    def test_budget_currency_must_be_iso(self) -> None:
        _, ошибки = bs.parse_spec({"budget": {"amount": 10, "currency": "euro"}})
        self.assertEqual(1, len(ошибки))

    def test_people_and_conditions_are_carried(self) -> None:
        spec, ошибки = bs.parse_spec(
            {
                "people": [{"name": "Macron", "real": True, "public_figure": True, "consent": "none", "claim": "political"}],
                "conditions": ["profile face", "hands"],
            }
        )
        self.assertEqual([], ошибки)
        self.assertEqual("political", spec.people[0]["claim"])
        self.assertEqual(("profile face", "hands"), spec.conditions)

    def test_people_values_outside_the_lists_are_refused(self) -> None:
        _, ошибки = bs.parse_spec({"people": [{"name": "x", "consent": "maybe", "claim": "satire"}]})
        self.assertEqual(2, len(ошибки))

    def test_apple_silicon_memory_is_not_vram(self) -> None:
        spec, ошибки = bs.parse_spec({"self_host": {"gpu": "Apple M3 Max", "vram_gb": 128}})
        self.assertEqual([], ошибки)
        self.assertIsNone(spec.self_host["vram_gb"])
        self.assertEqual(128.0, spec.self_host["unified_memory_gb"])
        жёсткие = bs.hard(spec, "")
        self.assertIsNone(жёсткие.vram_gb)

    def test_cuda_gpu_memory_stays_vram(self) -> None:
        spec, _ = bs.parse_spec({"self_host": {"gpu": "RTX 4090", "vram_gb": 24}})
        self.assertEqual(24.0, spec.self_host["vram_gb"])

    def test_task_chain(self) -> None:
        spec, ошибки = bs.parse_spec({"task": ["video-edit", "upscale"]})
        self.assertEqual([], ошибки)
        self.assertEqual(("video-edit", ("upscale",)), (spec.task, spec.then_tasks))


# --- 4. Деньги в тексте черновика: число вплотную к валюте ------------------------------


class ДеньгиВТексте(unittest.TestCase):
    СЛУЧАИ = (
        ("15-second 1080p product teaser, 9:16, generated, budget €12", (12.0, "EUR")),
        ("Сгенерируй 4 картинки, 1:1, бюджет 100 рублей", (100.0, "RUB")),
        ("озвучка 2 минуты, бюджет 3000 тенге", (3000.0, "KZT")),
        ("budget $2 total", (2.0, "USD")),
        ("12 EUR per video", (12.0, "EUR")),
        ("бюджет 5к рублей", (5000.0, "RUB")),
        ("9:16 1080p", None),
    )

    def test_amount_is_the_number_next_to_the_currency(self) -> None:
        for текст, ждём in self.СЛУЧАИ:
            with self.subTest(текст=текст):
                self.assertEqual(ждём, bs.money_in_text(текст))

    def test_planner_names_the_foreign_amount_not_the_aspect(self) -> None:
        self.assertIn("12 eur", pn.budget_from("15-second teaser, 9:16, budget €12").note)
        self.assertIn("100 rub", pn.budget_from("4 картинки 1:1, бюджет 100 рублей").note)


# --- 5. Полная spec — план по ней одной -------------------------------------------------


class ПланПоSpec(unittest.TestCase):
    """Каждый класс сценария валидатора: шаги из spec, генерации поверх материала нет."""

    def test_text_cues_do_not_add_steps_to_a_complete_spec(self) -> None:
        итог = план(
            {"task": "transcribe", "inputs": свой("video", сек=2700), "outputs": ["text"], "languages": ["ru"]},
            бриф="make a video from scratch with music and a voiceover",
        )
        self.assertEqual(["расшифровка"], шаги(итог))
        self.assertEqual("make a video from scratch with music and a voiceover", итог["brief"])

    def test_text_money_does_not_set_a_ceiling_over_a_complete_spec(self) -> None:
        итог = план(
            {"task": "generate", "inputs": [], "outputs": ["image"], "shots": 2},
            бриф="two pictures of a dragon, budget $1",
        )
        self.assertIsNone(итог["budget"]["amount"])

    def test_transcribe_is_priced_by_the_recording(self) -> None:
        итог = план({"task": "transcribe", "inputs": свой("video", сек=2700), "outputs": ["text"], "languages": ["ru"]})
        self.assertEqual({"value": 2700.0, "from": "derived"}, итог["understood_as"]["fields"]["duration_s"])

    def test_restore(self) -> None:
        итог = план({"task": "restore", "inputs": свой("video", сек=300), "outputs": ["video"], "resolution": "1080p"})
        self.assertEqual(["реставрация"], шаги(итог))

    def test_video_edit_stabilise_then_upscale(self) -> None:
        итог = план(
            {"task": ["video-edit", "upscale"], "inputs": свой("video", сек=90), "outputs": ["video"], "resolution": "4k"}
        )
        self.assertEqual(["правка_видео", "апскейл"], шаги(итог))

    def test_restore_then_upscale_keeps_the_named_order(self) -> None:
        итог = план(
            {"task": ["restore", "upscale"], "inputs": свой("video", сек=300), "outputs": ["video"], "resolution": "4k"}
        )
        self.assertEqual(["реставрация", "апскейл"], шаги(итог))

    def test_edit_over_the_customers_video_is_a_video_edit(self) -> None:
        итог = план({"task": "edit", "inputs": свой("video", сек=20), "outputs": ["video"]})
        self.assertEqual(["правка_видео"], шаги(итог))

    def test_edit_over_a_photo_stays_an_image_edit(self) -> None:
        итог = план({"task": "edit", "inputs": свой("image"), "outputs": ["image"], "shots": 6})
        self.assertEqual(["редактирование_изображения"], шаги(итог))

    def test_remove_background_video(self) -> None:
        итог = план({"task": "remove-background", "inputs": свой("video", сек=30), "outputs": ["video"]})
        self.assertEqual(["удаление_фона_видео"], шаги(итог))

    def test_captions(self) -> None:
        итог = план({"task": "captions", "inputs": свой("video", сек=60), "outputs": ["video"], "languages": ["es"]})
        self.assertEqual(["расшифровка"], шаги(итог))

    def test_voice_clone(self) -> None:
        итог = план(
            {"task": "voice-clone", "inputs": свой("audio", "text", сек=180), "outputs": ["speech"], "duration_s": 90, "languages": ["ru"]}
        )
        self.assertEqual(["клонирование_голоса"], шаги(итог))

    def test_sing_photo_is_one_audio_driven_avatar(self) -> None:
        итог = план({"task": "sing-photo", "inputs": свой("image", "audio", сек=10), "outputs": ["video"]})
        self.assertEqual(["говорящий_аватар"], шаги(итог))

    def test_sing_photo_without_the_track_asks_for_it(self) -> None:
        итог = план({"task": "sing-photo", "inputs": свой("image"), "outputs": ["video"], "duration_s": 10})
        self.assertEqual("нужен_ответ_заказчика", итог["reason"])
        self.assertEqual([], итог["steps"])

    def test_music_visualiser_generates_no_music(self) -> None:
        итог = план({"task": "music-visualiser", "inputs": свой("audio", сек=240), "outputs": ["video", "music"]})
        self.assertEqual(["генерация_видео"], шаги(итог))
        self.assertIn("YOUR track is laid under the visuals (its length is the clip length)", итог["assembly"]["why"])

    def test_cut_to_shorts_cuts_and_does_not_generate(self) -> None:
        итог = план(
            {"task": "cut-to-shorts", "inputs": свой("video", сек=1800), "outputs": ["video"], "shots": 10, "per_shot_s": 60, "languages": ["en"]}
        )
        self.assertEqual(["расшифровка", "правка_видео"], шаги(итог))
        self.assertEqual(10, итог["steps"][1]["shots"])
        self.assertTrue(any("picked from the transcript" in п for п in итог["assembly"]["why"]))

    def test_highlight_reel_with_music_adds_a_music_bed_not_a_voice(self) -> None:
        итог = план(
            {"task": "cut-to-shorts", "inputs": свой("video", сек=7200), "outputs": ["video", "music", "speech"],
             "shots": 1, "per_shot_s": 180, "languages": ["en"]}
        )
        self.assertEqual(["расшифровка", "правка_видео", "музыка"], шаги(итог))

    def test_r2v_makes_the_reference_once(self) -> None:
        итог = план({"task": "r2v", "inputs": [], "outputs": ["video"], "duration_s": 30, "shots": 4})
        self.assertEqual(["генерация_изображения", "видео_по_референсу"], шаги(итог))

    def test_r2v_from_the_customers_reference(self) -> None:
        итог = план({"task": "r2v", "inputs": свой("image"), "outputs": ["video"], "duration_s": 30, "shots": 4})
        self.assertEqual(["видео_по_референсу"], шаги(итог))

    def test_new_jobs_take_candidates_from_the_registry(self) -> None:
        self.assertEqual("v2v-edit", pn.ФУНКЦИЯ_ОПЕРАЦИИ["правка_видео"])
        self.assertEqual("r2v", pn.ФУНКЦИЯ_ОПЕРАЦИИ["видео_по_референсу"])
        self.assertIn("правка_видео", pn.ТОЛЬКО_РЕЕСТР)
        self.assertIn("видео_по_референсу", pn.ТОЛЬКО_РЕЕСТР)

    def test_footage_with_generate_builds_no_second_video(self) -> None:
        итог = план({"task": "generate", "inputs": свой("video", сек=20), "outputs": ["video"], "duration_s": 20})
        self.assertNotIn("генерация_видео", шаги(итог))

    def test_any_language_plans_and_is_unmeasured_not_refused(self) -> None:
        итог = план(
            {"task": "generate", "inputs": свой("text"), "outputs": ["speech"], "duration_s": 120, "languages": ["kk"]}
        )
        self.assertEqual(["озвучка"], шаги(итог))
        self.assertTrue(any("kk" in д and "UNMEASURED" in д for д in итог["understood_as"]["assumptions"]))

    def test_wide_aspect_plans(self) -> None:
        итог = план(
            {"task": "generate", "inputs": [], "outputs": ["video", "sfx"], "duration_s": 45, "aspect": "2.39:1", "audio": "native"}
        )
        self.assertNotEqual("spec_не_разобран", итог["reason"])
        self.assertEqual("2.39:1", итог["understood_as"]["fields"]["aspect"]["value"])

    def test_foreign_budget_gives_no_verdict(self) -> None:
        итог = план(
            {"task": "generate", "inputs": [], "outputs": ["image"], "shots": 4, "budget": {"amount": 100, "currency": "RUB"}}
        )
        self.assertIsNone(итог["budget"]["amount"])
        self.assertIn("NO budget verdict", итог["budget"]["note"])

    def test_not_owned_input_is_said_out_loud(self) -> None:
        итог = план(
            {"task": "restore", "inputs": [{"kind": "video", "owned": False, "duration_s": 60}], "outputs": ["video"]}
        )
        self.assertTrue(any("NOT the customer's own" in д for д in итог["understood_as"]["assumptions"]))

    def test_apple_silicon_is_noted_and_unmeasured_per_step(self) -> None:
        итог = план(
            {
                "task": "animate",
                "inputs": свой("image"),
                "outputs": ["video"],
                "duration_s": 5,
                "self_host": {"gpu": "Apple M3 Max", "unified_memory_gb": 128},
            }
        )
        self.assertTrue(any("NOT CUDA VRAM" in д for д in итог["understood_as"]["assumptions"]))
        выбраны = [ш for ш in итог["steps"] if ш["chosen"]]
        for ш in выбраны:
            self.assertTrue(ш["apple_silicon"].startswith("unmeasured"))

    def test_apple_runtime_record_is_read(self) -> None:
        facts = [факт("x-i2v", "runs_on", "community MLX port available")]
        self.assertTrue(pn.поддержка_apple("x-i2v", facts).startswith("recorded"))
        self.assertTrue(pn.поддержка_apple("x-i2v", [факт("x-i2v", "runs_on", "CUDA only")]).startswith("unmeasured"))

    def test_language_support_per_model(self) -> None:
        facts = [факт("x-tts", "languages", "English, Kazakh, Russian")]
        self.assertEqual(
            {"kk": "recorded", "pl": "unmeasured"}, pn.поддержка_языков("x-tts", facts, ["kk", "pl"])
        )


# --- 6. Кратность: цена × языков × шотов ------------------------------------------------


class Кратность(unittest.TestCase):
    def операция(self, имя: str) -> pn.Operation:
        return next(оп for оп in pn.OPERATIONS if оп.name == имя)

    def test_speech_step_seconds_times_languages(self) -> None:
        нужда = pn.нужда_шага(self.операция("озвучка"), dur.Запрос(480.0, "8 min"), None, языков=3)
        self.assertEqual(1440.0, нужда.seconds)
        self.assertEqual(1440.0 * pn.pricing.CHARS_PER_SECOND, нужда.chars)

    def test_one_language_is_one_run(self) -> None:
        нужда = pn.нужда_шага(self.операция("озвучка"), dur.Запрос(480.0, "8 min"), None)
        self.assertEqual(480.0, нужда.seconds)

    def test_per_language_steps(self) -> None:
        self.assertIn("говорящий_аватар", pn.PER_LANGUAGE_STEPS)
        self.assertIn("клонирование_голоса", pn.PER_LANGUAGE_STEPS)
        self.assertNotIn("генерация_видео", pn.PER_LANGUAGE_STEPS)
        self.assertNotIn("расшифровка", pn.PER_LANGUAGE_STEPS)

    def test_plan_marks_the_language_multiplier(self) -> None:
        итог = план(
            {
                "task": "avatar",
                "inputs": свой("image", "text"),
                "outputs": ["video", "speech"],
                "duration_s": 480,
                "languages": ["en", "de", "ja"],
            }
        )
        строки = {ш["step"]: ш for ш in итог["steps"]}
        self.assertEqual(3, строки["говорящий_аватар"]["languages_multiplier"])

    def test_text_languages_do_not_multiply(self) -> None:
        итог = pn.plan(
            "talking avatar in English, German and Japanese, 8 minutes, from our photo",
            facts=list(БАЗА),
            today=СЕГОДНЯ,
            full=True,
        )
        for ш in итог["steps"]:
            self.assertNotIn("languages_multiplier", ш)

    def test_shorts_source_is_transcribed_whole(self) -> None:
        self.assertIn("расшифровка", pn.ON_SOURCE_STEPS)
        self.assertNotIn("правка_видео", pn.ON_SOURCE_STEPS)


if __name__ == "__main__":
    unittest.main()


class ПометкиПоАнглийски(unittest.TestCase):
    """Пометка маршрута доезжает до английского заказчика целиком: шаблон
    `l10n.EN` переводит её раньше, чем термин «видео» съест её середину."""

    def test_every_route_note_localises_without_cyrillic(self) -> None:
        from studio import l10n

        пометки = [*bs.NOTES_EN, *(ru for ru, _ in bs.ASSEMBLY_REASONS.values())]
        self.assertGreaterEqual(len(пометки), 9)
        утекли = [п for п in пометки if l10n.CYR.search(str(l10n.localise(п, "en")))]
        self.assertEqual([], утекли)
